"""Точка входа CLI: параметры задаются аргументами, файл конфигурации не нужен."""

import argparse
import re
import sys
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


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TEST_REPO = PROJECT_ROOT / "examples" / "test-repository.txt"
DEFAULT_PACKAGE = "serde_derive"
DEFAULT_REPOSITORY = "https://crates.io"
DEFAULT_TEST_PACKAGE = "A"
DEFAULT_TEST_VERSION = "1.0.0"
PACKAGE_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_-]*$")
VERSION_RE = re.compile(
    r"^[0-9]+\.[0-9]+\.[0-9]+"
    r"(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)
FORBIDDEN_FILTER_CHARS = ("\x00", "\n", "\r")
EXIT_OK = 0
EXIT_ERROR = 1


class ConfigError(ValueError):
    """Ошибка пользовательских параметров с кодом."""

    def __init__(self, code, message):
        """Сохраняет код и текст ошибки параметров."""
        super().__init__(f"{code}: {message}")
        self.code = code


def resolve_test_repo_path(value):
    """Вычисляет абсолютный путь к файлу тестового репозитория."""
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        cwd_candidate = candidate.resolve()
        if cwd_candidate.is_file():
            return cwd_candidate
        candidate = PROJECT_ROOT / candidate
    return candidate.resolve()


def validate_package_name(name, test_mode):
    """Проверяет имя пакета с учётом ограничений тестового режима."""
    if not PACKAGE_RE.fullmatch(name):
        raise ConfigError("E04", "Неверное имя пакета")
    if test_mode and not TEST_PKG_RE.fullmatch(name):
        msg = "В тестовом режиме имя пакета только из заглавных букв A-Z"
        raise ConfigError("E04", msg)


def validate_repository(value, test_mode):
    """Проверяет источник данных и возвращает путь или URL."""
    if not value:
        raise ConfigError("E06", "repository не может быть пустым")
    if test_mode:
        candidate = resolve_test_repo_path(value)
        if not candidate.is_file():
            raise ConfigError("E06", f"Тестовый файл не найден: {candidate}")
        return candidate
    url = urlparse(value)
    if (url.scheme not in {"http", "https"} or not url.hostname
            or any(char.isspace() for char in value)):
        raise ConfigError("E06", "Требуется URL вида https://host/path")
    return value


def validate_version(value):
    """Проверяет формат версии пакета, если она задана явно."""
    if value is not None and not VERSION_RE.fullmatch(value):
        raise ConfigError("E07", "Версия должна иметь вид 1.2.3")


def validate_output_file(output):
    """Проверяет корректность имени выходного SVG-файла."""
    if not output or Path(output).name != output:
        raise ConfigError("E08", "Укажите имя файла, например graph.svg")
    if output in {".", ".."} or not output.endswith(".svg"):
        raise ConfigError("E08", "Укажите имя файла, например graph.svg")


def validate_filter(substring):
    """Проверяет подстроку фильтрации на управляющие символы."""
    if any(ch in substring for ch in FORBIDDEN_FILTER_CHARS):
        raise ConfigError("E09", "Недопустимые символы в фильтре")


def build_arg_parser():
    """Создаёт парсер аргументов командной строки."""
    parser = argparse.ArgumentParser(
        description="Визуализатор графа зависимостей Cargo (вариант 2)"
    )
    parser.add_argument(
        "-p", "--package",
        default=None,
        help=f"Имя пакета (по умолчанию: {DEFAULT_PACKAGE})",
    )
    parser.add_argument(
        "-r", "--repository",
        default=None,
        help=f"URL реестра Cargo (по умолчанию: {DEFAULT_REPOSITORY})",
    )
    parser.add_argument(
        "--test-mode",
        action="store_true",
        help="Работать с файлом тестового репозитория",
    )
    parser.add_argument(
        "--version",
        dest="package_version",
        default=None,
        help="Версия пакета (по умолчанию: последняя стабильная; "
             "в тестовом режиме: 1.0.0)",
    )
    parser.add_argument(
        "-o", "--output",
        default=None,
        help="Имя выходного SVG-файла (по умолчанию: graph.svg)",
    )
    parser.add_argument(
        "--ascii-tree",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Выводить ASCII-дерево зависимостей (включено по умолчанию)",
    )
    parser.add_argument(
        "--filter",
        dest="filter_substring",
        default="",
        help="Подстрока для исключения пакетов",
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


def resolve_options(args):
    """Дополняет аргументы значениями по умолчанию для выбранного режима."""
    test_mode = args.test_mode
    package = args.package
    if package is None:
        package = DEFAULT_TEST_PACKAGE if test_mode else DEFAULT_PACKAGE
    repository = args.repository
    if repository is None:
        repository = (str(DEFAULT_TEST_REPO) if test_mode
                      else DEFAULT_REPOSITORY)
    version = args.package_version
    if version is None and test_mode:
        version = DEFAULT_TEST_VERSION
    output = args.output
    if output is None:
        output = "test-graph.svg" if test_mode else "graph.svg"
    return {
        "package_name": package,
        "repository": repository,
        "test_mode": test_mode,
        "package_version": version,
        "output_file": output,
        "ascii_tree": args.ascii_tree,
        "filter_substring": args.filter_substring,
    }


def validate_options(options):
    """Проверяет значения всех параметров перед запуском."""
    test_mode = options["test_mode"]
    validate_package_name(options["package_name"], test_mode)
    validate_version(options["package_version"])
    validate_output_file(options["output_file"])
    validate_filter(options["filter_substring"])
    options["repository"] = validate_repository(
        options["repository"], test_mode
    )
    return options


def build_from_test_repo(options):
    """Строит граф зависимостей по файлу тестового репозитория."""
    repo_map = load_test_repository(options["repository"])
    root = options["package_name"]
    if root not in repo_map:
        msg = f"Пакет '{root}' отсутствует в тестовом репозитории"
        raise RepoError("E11", msg)
    graph, cycles = build_graph_dfs(
        root, options["filter_substring"], lambda pkg: repo_map.get(pkg, [])
    )
    versions = dict(getattr(repo_map, "versions", {}))
    if root not in versions and options["package_version"]:
        versions[root] = options["package_version"]
    return graph, cycles, versions


def build_from_cargo_repo(options):
    """Строит транзитивный граф зависимостей из репозитория Cargo."""
    source = CargoGraphSource(
        options["repository"],
        options["package_name"],
        options["package_version"],
    )
    graph, cycles = build_graph_dfs(
        options["package_name"],
        options["filter_substring"],
        source.neighbors,
    )
    return graph, cycles, source.resolved


def run_stage_five(options, args):
    """Выполняет генерацию D2, сохранение SVG и опциональный вывод дерева."""
    if options["test_mode"]:
        graph, cycles, versions = build_from_test_repo(options)
    else:
        graph, cycles, versions = build_from_cargo_repo(options)
    root = options["package_name"]
    if args.show_graph:
        print(format_graph_report(root, graph, cycles))
    if args.load_order:
        print(format_load_order_report(root, graph, cycles, versions))
    d2_text = generate_d2(root, graph, cycles, versions)
    out_path = Path(options["output_file"]).resolve()
    save_svg_graph(d2_text, out_path, root, graph, cycles, versions)
    print("Описание графа на языке D2:")
    print(d2_text.rstrip())
    print(f"SVG-изображение сохранено: {out_path.name}")
    if options["ascii_tree"]:
        print("ASCII-дерево зависимостей:")
        print(format_ascii_tree(root, graph, versions))


def configure_console():
    """Переключает потоки вывода в UTF-8, чтобы русский текст не падал."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def main(argv=None):
    """Точка входа CLI для визуализации графа зависимостей."""
    configure_console()
    args = build_arg_parser().parse_args(argv)
    try:
        options = validate_options(resolve_options(args))
        run_stage_five(options, args)
    except (ConfigError, RepoError) as exc:
        print(f"Ошибка {exc}", file=sys.stderr)
        return EXIT_ERROR
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
