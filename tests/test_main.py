"""Модульные тесты конфигурации (этап 1) и сбора данных Cargo (этап 2)."""

import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import BytesIO, StringIO
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cargo_repo import (
    RepoError,
    fetch_direct_dependencies,
    sparse_index_path,
)
from main import (
    ConfigError,
    format_direct_dependencies,
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

    def test_main_prints_direct_dependencies(self):
        mock_deps = [("proc-macro2", "^1.0.74"), ("syn", "^2.0.56")]
        output = StringIO()
        with patch("main.fetch_direct_dependencies", return_value=mock_deps):
            with redirect_stdout(output):
                result = main(["--config", str(ROOT / "config.xml")])
        self.assertEqual(result, 0)
        text = output.getvalue()
        self.assertIn("- proc-macro2 (^1.0.74)", text)
        self.assertIn("- syn (^2.0.56)", text)

    def test_main_rejects_test_mode_in_stage_two(self):
        err = StringIO()
        cfg = str(ROOT / "examples" / "config-test.xml")
        with redirect_stderr(err):
            result = main(["--config", cfg])
        self.assertEqual(result, 1)
        self.assertIn("E14", err.getvalue())

    def test_valid_test_mode(self):
        path = ROOT / "examples" / "config-test.xml"
        config = read_config(path)
        self.assertTrue(validate_config(config, path)["test_mode"])

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
    """Тесты извлечения прямых зависимостей Cargo и кодов E11–E13."""

    def test_api_filters_dev_build_and_optional(self):
        payload = {
            "dependencies": [
                {"crate_id": "syn", "req": "^2.0", "kind": "normal"},
                {"crate_id": "quote", "req": "^1.0", "optional": False},
                {"crate_id": "opt_dep", "req": "^1.0", "optional": True},
                {"crate_id": "dev_dep", "req": "^1.0", "kind": "dev"},
                {"crate_id": "cc", "req": "^1.0", "kind": "build"},
                {"crate_id": "syn", "req": "^2.0", "kind": "normal"},
            ]
        }
        body = json.dumps(payload)
        with patch("cargo_repo.http_get_text", return_value=body):
            deps = fetch_direct_dependencies(
                "https://crates.io", "serde_derive", "1.0.210"
            )
        self.assertEqual(deps, [("quote", "^1.0"), ("syn", "^2.0")])

    def test_empty_dependencies_formatting(self):
        text = format_direct_dependencies("itoa", "1.0.11", [])
        self.assertEqual(text, "Прямые зависимости itoa 1.0.11: отсутствуют")

    def test_sparse_index_paths_and_parsing(self):
        self.assertEqual(sparse_index_path("a"), "1/a")
        self.assertEqual(sparse_index_path("cc"), "2/cc")
        self.assertEqual(sparse_index_path("syn"), "3/s/syn")
        self.assertEqual(sparse_index_path("Serde"), "se/rd/serde")
        lines = "\n".join([
            json.dumps({"vers": "1.0.0", "deps": []}),
            json.dumps({
                "vers": "1.0.1",
                "deps": [
                    {"name": "alias", "package": "real_pkg", "req": "^0.5"},
                    {"name": "dev_only", "req": "^1.0", "kind": "dev"},
                ],
            }),
        ])
        with patch("cargo_repo.http_get_text", return_value=lines):
            deps = fetch_direct_dependencies(
                "https://index.crates.io", "demo", "1.0.1"
            )
        self.assertEqual(deps, [("real_pkg", "^0.5")])

    def test_e11_http_404_not_found(self):
        raw = BytesIO(b'{"errors":[{"detail":"crate does not exist"}]}')
        err = HTTPError("https://crates.io", 404, "Not Found", {}, raw)
        with patch("cargo_repo.urlopen", side_effect=err):
            with self.assertRaises(RepoError) as ctx:
                fetch_direct_dependencies("https://crates.io", "none", "1.0.0")
        self.assertEqual(ctx.exception.code, "E11")

    def test_e11_missing_version_in_sparse(self):
        body = json.dumps({"vers": "0.1.0", "deps": []})
        with patch("cargo_repo.http_get_text", return_value=body):
            with self.assertRaises(RepoError) as ctx:
                fetch_direct_dependencies(
                    "https://index.crates.io", "itoa", "9.9.9"
                )
        self.assertEqual(ctx.exception.code, "E11")

    def test_e12_network_failure(self):
        with patch("cargo_repo.urlopen", side_effect=URLError("offline")):
            with self.assertRaises(RepoError) as ctx:
                fetch_direct_dependencies("https://crates.io", "itoa", "1.0.0")
        self.assertEqual(ctx.exception.code, "E12")

    def test_e13_malformed_json(self):
        with patch("cargo_repo.http_get_text", return_value="{bad-json"):
            with self.assertRaises(RepoError) as ctx:
                fetch_direct_dependencies("https://crates.io", "itoa", "1.0.0")
        self.assertEqual(ctx.exception.code, "E13")


if __name__ == "__main__":
    unittest.main()