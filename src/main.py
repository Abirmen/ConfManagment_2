"""Точка входа CLI, проверка XML и визуализация графа (этап 5)."""

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
from load_order import format_load_order_report
from visualizer import format_ascii_tree, generate_d2, save_svg_graph


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
FORBIDDEN_FILTER_CHARS = ("\x00", "\n", "\r")
EXIT_OK = 0
EXIT_ERROR = 1


class ConfigError(ValueError):
    """Ошибка пользовательской конфигурации с кодом."""

    def __init__(self, code, message):
        """Сохраняет код и текст ошибки конфигурации."""
        super().__init__(f"{code}: {message}")
        self.code = code


def parse_xml_root(path):
    """Открывает XML-файл и проверяет корневой тег <config>."""
    try:
        root = ET.parse(path).getroot()
    except (OSError, UnicodeError) as exc:
        raise ConfigError("E01", f"Не удаётся прочитать файл: {exc}") from exc
    except ET.ParseError as exc:
        raise ConfigError("E02", f"Неверный XML: {exc}") from exc
    if root.tag != "config" or root.attrib:
        raise ConfigError("E03", "Корень должен быть <config> без атрибутов")
    return root


def validate_xml_element(element, seen):
    """Проверяет отдельный дочерний элемент XML на допустимость."""
    if element.tag not in FIELDS or element.attrib or list(element):
        raise ConfigError("E03", f"Неожиданный элемент: {element.tag}")
    if element.tag in seen:
        raise ConfigError("E10", f"Повтор параметра: {element.tag}")


def read_config(path):
    """Читает XML и проверяет наличие всех обязательных полей."""
    root = parse_xml_root(path)
    result = {}
    for element in root:
        validate_xml_element(element, result)
        text = element.text if element.text is not None else ""
        result[element.tag] = text.strip()
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


def validate_output_file(output):
    """Проверяет корректность имени выходного SVG-файла."""
    if not output or Path(output).name != output:
        raise ConfigError("E08", "Укажите имя файла, например graph.svg")
    if output in {".", ".."} or not output.endswith(".svg"):
        raise ConfigError("E08", "Укажите имя файла, например graph.svg")


def validate_config(config, config_path):
    """Проверяет значения всех семи полей."""
    test_mode = parse_boolean(config, "test_mode")
    ascii_tree = parse_boolean(config, "ascii_tree")
    validate_package_name(config["package_name"], test_mode)
    validate_repository(config["repository"], test_mode, config_path)
    if not VERSION_RE.fullmatch(config["package_version"]):
        raise ConfigError("E07", "Версия должна иметь вид 1.2.3")
    validate_output_file(config["output_file"])
    substring = config["filter_substring"]
    if any(ch in substring for ch in FORBIDDEN_FILTER_CHARS):
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
    graph, cycles = build_graph_dfs(
        root, config["filter_substring"], lambda pkg: repo_map.get(pkg, [])
    )
    return graph, cycles, None


def build_from_cargo_repo(config):
    """Строит транзитивный граф зависимостей из репозитория Cargo."""
    source = CargoGraphSource(
        config["repository"],
        config["package_name"],
        config["package_version"],
    )
    graph, cycles = build_graph_dfs(
        config["package_name"], config["filter_substring"], source.neighbors
    )
    return graph, cycles, source.resolved


def run_stage_five(config, config_path, args):
    """Выполняет генерацию D2, сохранение SVG и опциональный вывод дерева."""
    if config["test_mode"]:
        graph, cycles, versions = build_from_test_repo(config, config_path)
    else:
        graph, cycles, versions = build_from_cargo_repo(config)
    root = config["package_name"]
    if args.show_graph:
        print(format_graph_report(root, graph, cycles))
    if args.load_order:
        print(format_load_order_report(root, graph, cycles, versions))
    d2_text = generate_d2(root, graph, cycles, versions)
    out_path = Path(config["output_file"]).resolve()
    save_svg_graph(d2_text, out_path, root, graph, cycles, versions)
    print("Описание графа на языке D2:")
    print(d2_text.rstrip())
    print(f"SVG-изображение сохранено: {out_path.name}")
    if config["ascii_tree"]:
        print("ASCII-дерево зависимостей:")
        print(format_ascii_tree(root, graph, versions))


def build_arg_parser():
    """Создаёт парсер аргументов командной строки для этапа 5."""
    parser = argparse.ArgumentParser(description="Вариант 2 — этап 5")
    parser.add_argument(
        "--config", default="config.xml", help="Путь к XML-конфигурации"
    )
    parser.add_argument(
        "--show-graph",
        action="store_true",
        help="Дополнительно вывести список смежности графа",
    )
    parser.add_argument(
        "--load-order",
        action="store_true",
        help="Дополнительно вывести порядок загрузки зависимостей",
    )
    return parser


def main(argv=None):
    """Точка входа CLI для визуализации графа зависимостей."""
    args = build_arg_parser().parse_args(argv)
    try:
        path = Path(args.config).expanduser().resolve()
        config = validate_config(read_config(path), path)
        run_stage_five(config, path, args)
    except (ConfigError, RepoError) as exc:
        print(f"Ошибка {exc}", file=sys.stderr)
        return EXIT_ERROR
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())