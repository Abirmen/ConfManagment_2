"""Модульные тесты конфигурации, клиента Cargo и графа DFS (этапы 1–3)."""

import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import BytesIO, StringIO
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cargo_repo import (  # noqa: E402
    CargoGraphSource,
    RepoError,
    fetch_direct_dependencies,
    matches_version_req,
    select_best_version,
    sparse_index_path,
)
from dep_graph import (  # noqa: E402
    build_graph_dfs,
    load_test_repository,
)
from main import (  # noqa: E402
    ConfigError,
    main,
    read_config,
    validate_config,
)


ROOT = Path(__file__).resolve().parents[1]


class ConfigTests(unittest.TestCase):
    """Позитивные и негативные сценарии конфигурации и запуска CLI."""

    def setUp(self):
        self.sample = read_config(ROOT / "config.xml")

    def check_error(self, field, value, code):
        """Проверяет код ошибки после замены одного параметра."""
        config = self.sample.copy()
        config[field] = value
        with self.assertRaises(ConfigError) as context:
            validate_config(config, ROOT / "config.xml")
        self.assertEqual(context.exception.code, code)

    def test_valid(self):
        self.assertTrue(validate_config(self.sample, ROOT / "config.xml"))

    def test_valid_test_mode(self):
        path = ROOT / "examples" / "config-test.xml"
        config = read_config(path)
        self.assertTrue(validate_config(config, path)["test_mode"])

    def test_test_mode_requires_uppercase_latin_package(self):
        config = read_config(ROOT / "examples" / "config-test.xml")
        config["package_name"] = "serde"
        path = ROOT / "examples" / "config-test.xml"
        with self.assertRaises(ConfigError) as ctx:
            validate_config(config, path)
        self.assertEqual(ctx.exception.code, "E04")

    def test_main_runs_test_mode_with_filter(self):
        output = StringIO()
        cfg = str(ROOT / "examples" / "config-test.xml")
        with redirect_stdout(output):
            result = main(["--config", cfg])
        self.assertEqual(result, 0)
        text = output.getvalue()
        self.assertIn("A -> C", text)
        self.assertNotIn("B ->", text)

    def test_main_runs_cycle_config(self):
        output = StringIO()
        cfg = str(ROOT / "examples" / "config-cycle.xml")
        with redirect_stdout(output):
            result = main(["--config", cfg])
        self.assertEqual(result, 0)
        text = output.getvalue()
        self.assertIn("Обнаружены циклические зависимости", text)
        self.assertIn("C -> A", text)
        self.assertIn("D -> D", text)

    def test_e01_missing_file(self):
        with self.assertRaisesRegex(ConfigError, "E01"):
            read_config(ROOT / "missing.xml")

    def test_e02_bad_xml(self):
        self.check_xml("<config>", "E02")

    def test_e03_missing_parameter(self):
        self.check_xml("<config></config>", "E03")

    def test_e03_extra_parameter(self):
        xml = self.xml_text().replace("</config>", "<extra>x</extra></config>")
        self.check_xml(xml, "E03")

    def test_e04_bad_name(self):
        self.check_error("package_name", "bad package!", "E04")

    def test_e05_bad_test_mode(self):
        self.check_error("test_mode", "yes", "E05")

    def test_e05_bad_ascii_tree(self):
        self.check_error("ascii_tree", "1", "E05")

    def test_e06_bad_url(self):
        self.check_error("repository", "invalid-url", "E06")

    def test_e06_missing_test_repository(self):
        config = self.sample.copy()
        config["test_mode"] = "true"
        config["package_name"] = "A"
        config["repository"] = "missing-repo.txt"
        with self.assertRaisesRegex(ConfigError, "E06"):
            validate_config(config, ROOT / "config.xml")

    def test_e07_bad_version(self):
        self.check_error("package_version", "latest", "E07")

    def test_e08_bad_output(self):
        self.check_error("output_file", "diagram.png", "E08")

    def test_e09_invalid_filter(self):
        self.check_error("filter_substring", "bad\x00x", "E09")

    def test_e10_duplicate_parameter(self):
        xml = self.xml_text().replace(
            "</config>", "<package_name>A</package_name></config>"
        )
        self.check_xml(xml, "E10")

    def xml_text(self):
        """Возвращает эталонный XML."""
        return (ROOT / "config.xml").read_text(encoding="utf-8")

    def check_xml(self, content, code):
        """Проверяет ошибку чтения временного XML-файла."""
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.xml"
            path.write_text(content, encoding="utf-8")
            with self.assertRaises(ConfigError) as context:
                read_config(path)
            self.assertEqual(context.exception.code, code)


class CargoRepoTests(unittest.TestCase):
    """Тесты извлечения зависимостей Cargo и разрешения SemVer."""

    def test_api_filters_dev_build_and_optional(self):
        payload = {
            "dependencies": [
                {"crate_id": "syn", "req": "^2.0", "kind": "normal"},
                {"crate_id": "quote", "req": "^1.0", "optional": False},
                {"crate_id": "opt_dep", "req": "^1.0", "optional": True},
                {"crate_id": "dev_dep", "req": "^1.0", "kind": "dev"},
                {"crate_id": "cc", "req": "^1.0", "kind": "build"},
            ]
        }
        with patch("cargo_repo.http_get_text", return_value=json.dumps(payload)):
            deps = fetch_direct_dependencies(
                "https://crates.io", "serde_derive", "1.0.210"
            )
        self.assertEqual(deps, [("quote", "^1.0"), ("syn", "^2.0")])

    def test_sparse_index_paths_and_parsing(self):
        self.assertEqual(sparse_index_path("a"), "1/a")
        self.assertEqual(sparse_index_path("cc"), "2/cc")
        self.assertEqual(sparse_index_path("syn"), "3/s/syn")
        self.assertEqual(sparse_index_path("Serde"), "se/rd/serde")
        lines = "\n".join([
            json.dumps({"vers": "1.0.0", "deps": []}),
            json.dumps({
                "vers": "1.0.1",
                "deps": [{"name": "alias", "package": "pkg", "req": "^0.5"}],
            }),
        ])
        with patch("cargo_repo.http_get_text", return_value=lines):
            deps = fetch_direct_dependencies(
                "https://index.crates.io", "demo", "1.0.1"
            )
        self.assertEqual(deps, [("pkg", "^0.5")])

    def test_semver_matching_and_selection(self):
        self.assertTrue(matches_version_req("2.0.87", "^2.0.56"))
        self.assertFalse(matches_version_req("3.0.0", "^2.0.56"))
        self.assertTrue(matches_version_req("0.2.9", "^0.2.1"))
        self.assertFalse(matches_version_req("0.3.0", "^0.2.1"))
        self.assertTrue(matches_version_req("1.4.9", "~1.4.2"))
        self.assertFalse(matches_version_req("1.5.0", "~1.4.2"))
        chosen = select_best_version(["1.0.1", "1.0.9", "2.0.0"], "^1.0.0")
        self.assertEqual(chosen, "1.0.9")

    def test_cargo_graph_source_transitive(self):
        deps_map = {
            ("root", "1.0.0"): [("mid", "^1.0")],
            ("mid", "1.2.0"): [("leaf", "^0.3")],
            ("leaf", "0.3.5"): [],
        }
        vers_map = {"mid": ["1.0.0", "1.2.0"], "leaf": ["0.3.5", "0.4.0"]}
        with patch(
            "cargo_repo.fetch_direct_dependencies",
            side_effect=lambda _, p, v: deps_map[(p, v)],
        ), patch(
            "cargo_repo.fetch_available_versions",
            side_effect=lambda _, p: vers_map[p],
        ):
            src = CargoGraphSource("https://crates.io", "root", "1.0.0")
            graph, cycles = build_graph_dfs("root", "", src.neighbors)
        self.assertEqual(cycles, [])
        self.assertEqual(graph["root"], ["mid"])
        self.assertEqual(graph["mid"], ["leaf"])
        self.assertEqual(graph["leaf"], [])

    def test_e11_e12_e13_errors(self):
        raw = BytesIO(b'{"errors":[{"detail":"not found"}]}')
        err = HTTPError("https://crates.io", 404, "Not Found", {}, raw)
        with patch("cargo_repo.urlopen", side_effect=err):
            with self.assertRaisesRegex(RepoError, "E11"):
                fetch_direct_dependencies("https://crates.io", "x", "1.0.0")
        with patch("cargo_repo.urlopen", side_effect=URLError("offline")):
            with self.assertRaisesRegex(RepoError, "E12"):
                fetch_direct_dependencies("https://crates.io", "x", "1.0.0")
        with patch("cargo_repo.http_get_text", return_value="{bad"):
            with self.assertRaisesRegex(RepoError, "E13"):
                fetch_direct_dependencies("https://crates.io", "x", "1.0.0")


class DepGraphTests(unittest.TestCase):
    """Тесты нерекурсивного DFS, фильтрации, циклов и тестового файла."""

    def test_diamond_and_filter(self):
        repo = {"A": ["B", "C"], "B": ["D"], "C": ["D"], "D": []}
        graph, cycles = build_graph_dfs("A", "", lambda n: repo[n])
        self.assertEqual(cycles, [])
        self.assertEqual(graph["D"], [])
        filtered, _ = build_graph_dfs("A", "B", lambda n: repo[n])
        self.assertNotIn("B", filtered)
        self.assertEqual(filtered["A"], ["C"])

    def test_filtered_root_returns_empty_graph(self):
        repo = {"A": ["B"], "B": []}
        graph, cycles = build_graph_dfs("A", "A", lambda n: repo[n])
        self.assertEqual(graph, {})
        self.assertEqual(cycles, [])

    def test_deep_chain_without_recursion_limit(self):
        depth = 1500
        nodes = [f"N{i}" for i in range(depth)]
        repo = {nodes[i]: [nodes[i + 1]] for i in range(depth - 1)}
        repo[nodes[-1]] = []
        graph, cycles = build_graph_dfs("N0", "", lambda n: repo[n])
        self.assertEqual(len(graph), depth)
        self.assertEqual(cycles, [])

    def test_invalid_test_repository_format_raises_e15(self):
        with tempfile.TemporaryDirectory() as folder:
            bad_file = Path(folder) / "bad.txt"
            bad_file.write_text("a_lower: B\n", encoding="utf-8")
            with self.assertRaises(RepoError) as ctx:
                load_test_repository(bad_file)
            self.assertEqual(ctx.exception.code, "E15")


if __name__ == "__main__":
    unittest.main()