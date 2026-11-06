"""Модульные тесты чтения и проверки XML-конфигурации."""

import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from main import ConfigError, main, read_config, validate_config


ROOT = Path(__file__).resolve().parents[1]


class ConfigTests(unittest.TestCase):
    """Позитивные и негативные сценарии конфигурации."""

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

    def test_main_prints_all_fields(self):
        output = StringIO()
        with redirect_stdout(output):
            result = main(["--config", str(ROOT / "config.xml")])
        self.assertEqual(result, 0)
        self.assertEqual(len(output.getvalue().splitlines()), 7)

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


if __name__ == "__main__":
    unittest.main()
