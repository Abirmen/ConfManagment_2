"""Точка входа CLI и проверка XML-конфигурации (этап 2)."""

import argparse
import re
import sys
import xml.etree.ElementTree as element_tree
from pathlib import Path
from urllib.parse import urlparse

from cargo_repo import RepoError, fetch_direct_dependencies


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
        """Сохраняет код и текст ошибки параметров."""
        super().__init__(f"{code}: {message}")
        self.code = code


def load_config_root(path):
    """Читает XML-файл и возвращает корневой элемент."""
    try:
        return element_tree.parse(path).getroot()
    except (OSError, UnicodeError) as exc:
        raise ConfigError("E01", f"Не удаётся прочитать файл: {exc}") from exc
    except element_tree.ParseError as exc:
        raise ConfigError("E02", f"Неверный XML: {exc}") from exc


def check_config_element(element, result):
    """Проверяет один элемент конфигурации и сохраняет его значение."""
    if element.tag not in FIELDS or element.attrib or len(element):
        raise ConfigError("E03", f"Неожиданный элемент: {element.tag}")
    if element.tag in result:
        raise ConfigError("E10", f"Повтор параметра: {element.tag}")
    result[element.tag] = (element.text or "").strip()


def collect_config_fields(root):
    """Проверяет корень и собирает поля конфигурации."""
    if root.tag != "config" or root.attrib:
        raise ConfigError("E03", "Корень должен быть <config> без атрибутов")
    result = {}
    for element in root:
        check_config_element(element, result)
    return result


def find_missing_fields(config):
    """Возвращает список отсутствующих обязательных полей."""
    return [field for field in FIELDS if field not in config]


def read_config(path):
    """Читает XML и проверяет структуру полей."""
    config = collect_config_fields(load_config_root(path))
    missing = find_missing_fields(config)
    if missing:
        raise ConfigError("E03", "Отсутствуют поля: " + ", ".join(missing))
    return config


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


def format_direct_dependencies(package_name, version, dependencies):
    """Форматирует прямые зависимости пакета для вывода в консоль."""
    header = f"Прямые зависимости {package_name} {version}:"
    if not dependencies:
        return f"{header} отсутствуют"
    lines = [header]
    for dep_name, version_req in dependencies:
        lines.append(f"- {dep_name} ({version_req})")
    return "\n".join(lines)


def run_stage_two(config):
    """Загружает и выводит прямые зависимости пакета Cargo."""
    if config["test_mode"]:
        msg = "Режим тестового репозитория реализуется на этапе 3"
        raise RepoError("E14", msg)
    deps = fetch_direct_dependencies(
        config["repository"],
        config["package_name"],
        config["package_version"],
    )
    print(
        format_direct_dependencies(
            config["package_name"], config["package_version"], deps
        )
    )


def main(argv=None):
    """Точка входа; проверяет XML и выводит прямые зависимости пакета."""
    parser = argparse.ArgumentParser(description="Вариант 2 — этап 2")
    parser.add_argument(
        "--config", default="config.xml", help="Путь к XML-конфигурации"
    )
    args = parser.parse_args(argv)
    try:
        path = Path(args.config).expanduser().resolve()
        config = validate_config(read_config(path), path)
        run_stage_two(config)
    except (ConfigError, RepoError) as exc:
        print(f"Ошибка {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())