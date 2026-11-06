"""Модульные тесты анализатора и визуализатора (этапы 1–5)."""

import json
import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as element_tree
from contextlib import redirect_stderr, redirect_stdout
from io import BytesIO, StringIO
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cargo_repo import (
    CargoGraphSource,
    RepoError,
    fetch_direct_dependencies,
    matches_version_req,
    select_best_version,
    sparse_index_path,
)
from dep_graph import (
    build_graph_dfs,
    load_test_repository,
)
from load_order import compute_load_order
from main import (
    ConfigError,
    build_arg_parser,
    main,
    resolve_options,
    validate_filter,
    validate_output_file,
    validate_package_name,
    validate_repository,
    validate_version,
)
from svg_renderer import render_builtin_svg
from visualizer import format_ascii_tree, generate_d2


ROOT = Path(__file__).resolve().parents[1]


class FakeCargoSource:
    """Подменяет сетевой источник Cargo заранее известным графом."""

    def __init__(self, repository, root_package, root_version=None):
        """Сохраняет версии и зависимости тестового графа."""
        self.resolved = {
            "http": root_version or "1.1.0",
            "bytes": "1.12.1",
            "fnv": "1.0.7",
            "itoa": "1.0.18",
        }
        self.graph = {
            "http": ["bytes", "fnv", "itoa"],
            "bytes": [],
            "fnv": [],
            "itoa": [],
        }

    def neighbors(self, package_name):
        """Возвращает прямые зависимости пакета."""
        return self.graph[package_name]


class CliTests(unittest.TestCase):
    """Проверяет работу CLI без файла конфигурации."""

    def run_cli_in_temp_cwd(self, argv):
        """Запускает CLI во временной папке для изоляции создаваемых SVG."""
        output, errors = StringIO(), StringIO()
        prev_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as tmp_dir:
            os.chdir(tmp_dir)
            try:
                with redirect_stdout(output), redirect_stderr(errors):
                    code = main(argv)
                svg_files = {p.name: p.read_text("utf-8") for p in
                             Path(tmp_dir).glob("*.svg")}
            finally:
                os.chdir(prev_cwd)
        return code, output.getvalue(), errors.getvalue(), svg_files

    def test_default_options_real_mode(self):
        options = resolve_options(build_arg_parser().parse_args([]))
        self.assertEqual(options["package_name"], "serde_derive")
        self.assertEqual(options["repository"], "https://crates.io")
        self.assertEqual(options["output_file"], "graph.svg")
        self.assertFalse(options["test_mode"])
        self.assertIsNone(options["package_version"])
        self.assertTrue(options["ascii_tree"])

    def test_default_options_test_mode(self):
        options = resolve_options(
            build_arg_parser().parse_args(["--test-mode"])
        )
        self.assertEqual(options["package_name"], "A")
        self.assertEqual(options["package_version"], "1.0.0")
        self.assertEqual(options["output_file"], "test-graph.svg")
        self.assertTrue(options["test_mode"])
        self.assertTrue(options["repository"].endswith(
            "test-repository.txt"))

    def test_test_mode_picture_and_tree_contain_versions(self):
        code, text, _, svgs = self.run_cli_in_temp_cwd(
            ["--test-mode", "--show-graph", "--load-order"]
        )
        self.assertEqual(code, 0)
        self.assertIn("test-graph.svg", svgs)
        self.assertIn('"A": "A (1.0.0)"', text)
        self.assertIn('"A" -> "B"', text)
        self.assertIn("A v1.0.0", text)
        self.assertIn("v1.2.0", text)
        self.assertIn("v1.0.0", svgs["test-graph.svg"])
        element_tree.fromstring(svgs["test-graph.svg"])

    def test_ascii_tree_can_be_disabled(self):
        code, text, _, _ = self.run_cli_in_temp_cwd(
            ["--test-mode", "--no-ascii-tree"]
        )
        self.assertEqual(code, 0)
        self.assertNotIn("ASCII-дерево зависимостей:", text)

    def test_real_mode_uses_cli_values_and_shows_versions(self):
        with patch("main.CargoGraphSource", FakeCargoSource):
            code, text, _, svgs = self.run_cli_in_temp_cwd(
                ["--package", "http", "--version", "1.1.0",
                 "--output", "http-graph.svg"]
            )
        self.assertEqual(code, 0)
        self.assertIn('"http": "http (1.1.0)"', text)
        self.assertIn("http v1.1.0", text)
        self.assertIn("http-graph.svg", svgs)
        svg = svgs["http-graph.svg"]
        self.assertIn("v1.1.0", svg)
        self.assertIn("v1.12.1", svg)
        element_tree.fromstring(svg)

    def test_invalid_cli_arguments_return_error(self):
        code, _, errors, _ = self.run_cli_in_temp_cwd(
            ["--package", "bad package!"]
        )
        self.assertEqual(code, 1)
        self.assertIn("E04", errors)

    def test_e04_bad_name(self):
        with self.assertRaises(ConfigError) as ctx:
            validate_package_name("bad package!", False)
        self.assertEqual(ctx.exception.code, "E04")

    def test_e04_test_mode_requires_uppercase_latin(self):
        with self.assertRaises(ConfigError) as ctx:
            validate_package_name("serde", True)
        self.assertEqual(ctx.exception.code, "E04")

    def test_e06_bad_url(self):
        with self.assertRaises(ConfigError) as ctx:
            validate_repository("invalid-url", False)
        self.assertEqual(ctx.exception.code, "E06")

    def test_e06_missing_test_repository(self):
        with tempfile.TemporaryDirectory() as folder:
            missing = str(Path(folder) / "missing-repo.txt")
            with self.assertRaises(ConfigError) as ctx:
                validate_repository(missing, True)
        self.assertEqual(ctx.exception.code, "E06")

    def test_e07_bad_version(self):
        with self.assertRaises(ConfigError) as ctx:
            validate_version("latest")
        self.assertEqual(ctx.exception.code, "E07")

    def test_e08_bad_output(self):
        with self.assertRaises(ConfigError) as ctx:
            validate_output_file("diagram.png")
        self.assertEqual(ctx.exception.code, "E08")

    def test_e09_invalid_filter(self):
        with self.assertRaises(ConfigError) as ctx:
            validate_filter("bad\x00x")
        self.assertEqual(ctx.exception.code, "E09")


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
        body = json.dumps(payload)
        with patch("cargo_repo.http_get_text", return_value=body):
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

    def test_semver_matching_and_short_caret(self):
        self.assertTrue(matches_version_req("2.0.87", "^2.0.56"))
        self.assertTrue(matches_version_req("1.9.0", "^1"))
        self.assertTrue(matches_version_req("1.4.2", "^1.0"))
        self.assertFalse(matches_version_req("2.0.0", "^1"))
        chosen = select_best_version(["1.0.1", "1.0.9", "2.0.0"], "^1.0")
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
        self.assertEqual(graph["mid"], ["leaf"])

    def test_latest_root_version_when_omitted(self):
        with patch(
            "cargo_repo.fetch_available_versions",
            return_value=["1.0.0", "2.1.0"],
        ), patch(
            "cargo_repo.fetch_direct_dependencies",
            return_value=[],
        ):
            source = CargoGraphSource("https://crates.io", "root")
        self.assertEqual(source.resolved["root"], "2.1.0")

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


class GraphOrderAndVizTests(unittest.TestCase):
    """Тесты графа DFS, порядка загрузки, D2, SVG и ASCII-дерева."""

    def test_diamond_wave_load_order(self):
        repo = load_test_repository(ROOT / "examples" / "test-repository.txt")
        graph, cycles = build_graph_dfs("A", "", lambda n: repo[n])
        result = compute_load_order(graph, cycles)
        self.assertEqual(result["order"], ["E", "G", "D", "F", "B", "C", "A"])

    def test_test_repository_parses_versions(self):
        repo = load_test_repository(ROOT / "examples" / "test-repository.txt")
        self.assertEqual(repo.versions["A"], "1.0.0")
        self.assertEqual(repo.versions["B"], "1.2.0")
        self.assertEqual(repo.versions["G"], "3.1.4")
        self.assertEqual(repo["A"], ["B", "C"])

    def test_cycle_detection_and_visualizers(self):
        path = ROOT / "examples" / "test-cycle-repository.txt"
        repo = load_test_repository(path)
        graph, cycles = build_graph_dfs("A", "", lambda n: repo[n])
        d2 = generate_d2("A", graph, cycles)
        self.assertIn("direction: down", d2)
        self.assertIn('"C" -> "A": "cycle"', d2)
        tree = format_ascii_tree("A", graph)
        self.assertIn("A [цикл]", tree)
        self.assertIn("D [цикл]", tree)
        svg = render_builtin_svg("A", graph, cycles)
        element_tree.fromstring(svg)

    def test_versions_are_rendered_in_d2_svg_and_tree(self):
        versions = {"A": "1.0.0", "B": "1.2.0"}
        graph = {"A": ["B"], "B": []}
        d2 = generate_d2("A", graph, (), versions)
        self.assertIn('"A": "A (1.0.0)"', d2)
        svg = render_builtin_svg("A", graph, (), versions)
        self.assertIn("v1.0.0", svg)
        self.assertIn("v1.2.0", svg)
        self.assertIn("B v1.2.0", format_ascii_tree("A", graph, versions))

    def test_ascii_tree_marks_repeated_subtrees(self):
        graph = {"A": ["B", "C"], "B": ["D"], "C": ["B"], "D": []}
        versions = {"A": "1.0.0", "B": "1.1.0", "C": "1.2.0", "D": "1.3.0"}
        tree = format_ascii_tree("A", graph, versions)
        self.assertIn("A v1.0.0", tree)
        self.assertIn("B v1.1.0 (*)", tree)

    def test_empty_filtered_graph_svg_and_tree(self):
        svg = render_builtin_svg("A", {})
        element_tree.fromstring(svg)
        self.assertIn("отфильтрован", format_ascii_tree("A", {}))

    def test_deep_chain_without_recursion_limit(self):
        depth = 1500
        nodes = [f"N{i}" for i in range(depth)]
        repo = {nodes[i]: [nodes[i + 1]] for i in range(depth - 1)}
        repo[nodes[-1]] = []
        graph, cycles = build_graph_dfs("N0", "", lambda n: repo[n])
        tree = format_ascii_tree("N0", graph)
        self.assertEqual(len(tree.splitlines()), depth)
        self.assertEqual(cycles, [])

    def test_invalid_test_repository_format_raises_e15(self):
        with tempfile.TemporaryDirectory() as folder:
            bad_file = Path(folder) / "bad.txt"
            bad_file.write_text("a_lower: B\n", encoding="utf-8")
            with self.assertRaisesRegex(RepoError, "E15"):
                load_test_repository(bad_file)

    def test_invalid_test_repository_version_raises_e15(self):
        with tempfile.TemporaryDirectory() as folder:
            bad_file = Path(folder) / "bad.txt"
            bad_file.write_text("A@not-a-version: B\n", encoding="utf-8")
            with self.assertRaisesRegex(RepoError, "E15"):
                load_test_repository(bad_file)


if __name__ == "__main__":
    unittest.main()
