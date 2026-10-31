import argparse
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlparse


FIELDS = (
    "package_name",
    "repository",
    "test_mode",
    "package_version",
    "output_file",
    "ascii_tree",
    "filter_substring",
)
BOOL_FIELDS = ("test_mode", "ascii_tree")
PACKAGE_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_-]*$")
VERSION_RE = re.compile(
    r"^[0-9]+\.[0-9]+\.[0-9]+"
    r"(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)


class ConfigError(ValueError):
    """Ошибка пользовательской конфигурации с кодом."""

    def __init__(self, code, message):
        super().__init__(f"{code}: {message}")
        self.code = code


def read_config(path):
    """Читает XML и проверяет структуру полей."""
    try:
        root = ET.parse(path).getroot()
    except (OSError, UnicodeError) as exc:
        raise ConfigError("E01", f"Не удаётся прочитать файл: {exc}") from exc
    except ET.ParseError as exc:
        raise ConfigError("E02", f"Неверный XML: {exc}") from exc

    if root.tag != "config" or root.attrib:
        raise ConfigError("E03", "Корень должен быть <config> без атрибутов")

    result = {}
    for element in root:
        if element.tag not in FIELDS or element.attrib or len(element):
            raise ConfigError("E03", f"Неожиданный элемент: {element.tag}")
        if element.tag in result:
            raise ConfigError("E10", f"Повтор параметра: {element.tag}")
        result[element.tag] = (element.text or "").strip()

    missing = [field for field in FIELDS if field not in result]
    if missing:
        raise ConfigError("E03", "Отсутствуют поля: " + ", ".join(missing))
    return result


def parse_boolean(config, field):
    """Преобразует строго true/false в bool."""
    value = config[field].lower()
    if value not in {"true", "false"}:
        raise ConfigError("E05", f"{field}: укажите true либо false")
    return value == "true"


def validate_repository(value, test_mode, config_path):
    """Проверяет источник относительно режима работы."""
    if not value:
        raise ConfigError("E06", "repository не может быть пустым")
    if test_mode:
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            candidate = config_path.parent / candidate
        if not candidate.is_file():
            raise ConfigError("E06", f"Тестовый файл не найден: {candidate}")
    else:
        url = urlparse(value)
        if (url.scheme not in {"http", "https"} or not url.hostname
                or any(char.isspace() for char in value)):
            raise ConfigError("E06", "Требуется URL вида https://host/path")


def validate_config(config, config_path):
    """Проверяет значения всех семи полей."""
    name = config["package_name"]
    if not PACKAGE_RE.fullmatch(name):
        raise ConfigError("E04", "Неверное имя пакета")

    test_mode = parse_boolean(config, "test_mode")
    ascii_tree = parse_boolean(config, "ascii_tree")
    validate_repository(config["repository"], test_mode, config_path)

    if not VERSION_RE.fullmatch(config["package_version"]):
        raise ConfigError("E07", "Версия должна иметь вид 1.2.3")

    output = config["output_file"]
    if (not output or Path(output).name != output
            or output in {".", ".."} or not output.endswith(".svg")):
        raise ConfigError("E08", "Укажите имя файла, например graph.svg")

    substring = config["filter_substring"]
    if "\x00" in substring or "\n" in substring or "\r" in substring:
        raise ConfigError("E09", "Недопустимые символы в фильтре")

    config["test_mode"] = test_mode
    config["ascii_tree"] = ascii_tree
    return config


def main(argv=None):
    """Точка входа; печатает конфигурацию в формате ключ: значение."""
    parser = argparse.ArgumentParser(description="Вариант 2 — этап 1")
    parser.add_argument(
        "--config", default="config.xml", help="Путь к XML-конфигурации"
    )
    args = parser.parse_args(argv)
    try:
        path = Path(args.config).expanduser().resolve()
        config = validate_config(read_config(path), path)
    except ConfigError as exc:
        print(f"Ошибка {exc}", file=sys.stderr)
        return 1

    for key in FIELDS:
        value = config[key]
        display = str(value).lower() if isinstance(value, bool) else value
        print(f"{key}: {display}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
