"""Точка входа CLI, проверка XML и построение графа (этап 3)."""

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlparse

from cargo_repo import CargoGraphSource, RepoError
from dep_graph import (
    TEST_PKG_RE,
    build_graph_dfs,
    format_graph_report,
    load_test_repository,
)


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


def resolve_test_repo_path(value, config_path):
    """Вычисляет абсолютный путь к файлу тестового репозитория."""
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = config_path.parent / candidate
    return candidate.resolve()


def validate_repository(value, test_mode, config_path):
    """Проверяет источник относительно режима работы."""
    if not value:
        raise ConfigError("E06", "repository не может быть пустым")
    if test_mode:
        candidate = resolve_test_repo_path(value, config_path)
        if not candidate.is_file():
            raise ConfigError("E06", f"Тестовый файл не найден: {candidate}")
    else:
        url = urlparse(value)
        if (url.scheme not in {"http", "https"} or not url.hostname
                or any(char.isspace() for char in value)):
            raise ConfigError("E06", "Требуется URL вида https://host/path")


def validate_package_name(name, test_mode):
    """Проверяет имя пакета с учётом ограничений тестового режима."""
    if not PACKAGE_RE.fullmatch(name):
        raise ConfigError("E04", "Неверное имя пакета")
    if test_mode and not TEST_PKG_RE.fullmatch(name):
        msg = "В тестовом режиме имя пакета только из заглавных букв A-Z"
        raise ConfigError("E04", msg)


def validate_config(config, config_path):
    """Проверяет значения всех семи полей."""
    test_mode = parse_boolean(config, "test_mode")
    ascii_tree = parse_boolean(config, "ascii_tree")
    validate_package_name(config["package_name"], test_mode)
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


def build_from_test_repo(config, config_path):
    """Строит граф зависимостей по файлу тестового репозитория."""
    repo_path = resolve_test_repo_path(config["repository"], config_path)
    repo_map = load_test_repository(repo_path)
    root = config["package_name"]
    if root not in repo_map:
        msg = f"Пакет '{root}' отсутствует в тестовом репозитории"
        raise RepoError("E11", msg)
    return build_graph_dfs(
        root, config["filter_substring"], lambda pkg: repo_map.get(pkg, [])
    )


def build_from_cargo_repo(config):
    """Строит транзитивный граф зависимостей из репозитория Cargo."""
    source = CargoGraphSource(
        config["repository"],
        config["package_name"],
        config["package_version"],
    )
    return build_graph_dfs(
        config["package_name"], config["filter_substring"], source.neighbors
    )


def run_stage_three(config, config_path):
    """Выполняет построение графа и выводит результат анализа."""
    if config["test_mode"]:
        graph, cycles = build_from_test_repo(config, config_path)
    else:
        graph, cycles = build_from_cargo_repo(config)
    print(format_graph_report(config["package_name"], graph, cycles))


def main(argv=None):
    """Точка входа CLI для построения графа зависимостей (этап 3)."""
    parser = argparse.ArgumentParser(description="Вариант 2 — этап 3")
    parser.add_argument(
        "--config", default="config.xml", help="Путь к XML-конфигурации"
    )
    args = parser.parse_args(argv)
    try:
        path = Path(args.config).expanduser().resolve()
        config = validate_config(read_config(path), path)
        run_stage_three(config, path)
    except (ConfigError, RepoError) as exc:
        print(f"Ошибка {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())