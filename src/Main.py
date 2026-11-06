"""Параметры CLI-приложения и их проверка (вариант 2, этап 1).

Точка входа: параметры задаются аргументами командной строки и
выводятся в формате «ключ: значение».
"""

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import urlparse


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PACKAGE = "serde_derive"
DEFAULT_REPOSITORY = "https://crates.io"
DEFAULT_VERSION = "0.8.5"
DEFAULT_OUTPUT = "graph.svg"
PACKAGE_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_-]*$")
VERSION_RE = re.compile(
    r"^[0-9]+\.[0-9]+\.[0-9]+"
    r"(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)
FORBIDDEN_FILTER_CHARS = ("\x00", "\n", "\r")
FIELDS = (
    "package_name",
    "repository",
    "test_mode",
    "package_version",
    "output_file",
    "ascii_tree",
    "filter_substring",
)
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


def validate_package_name(name):
    """Проверяет корректность имени пакета."""
    if not PACKAGE_RE.fullmatch(name):
        raise ConfigError("E04", "Неверное имя пакета")


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
    """Проверяет формат версии пакета."""
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


def add_source_arguments(parser):
    """Добавляет аргументы пакета, репозитория и версии."""
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
        help=f"Версия пакета (по умолчанию: {DEFAULT_VERSION})",
    )


def add_output_arguments(parser):
    """Добавляет аргументы выходного файла и ASCII-дерева."""
    parser.add_argument(
        "-o", "--output",
        default=None,
        help=f"Имя выходного SVG-файла (по умолчанию: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--ascii-tree",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Выводить ASCII-дерево зависимостей",
    )


def add_report_arguments(parser):
    """Добавляет аргумент фильтра пакетов."""
    parser.add_argument(
        "--filter",
        dest="filter_substring",
        default="",
        help="Подстрока для исключения пакетов",
    )


def build_arg_parser():
    """Создаёт парсер аргументов командной строки."""
    parser = argparse.ArgumentParser(
        description="Визуализатор графа зависимостей Cargo (вариант 2, этап 1)"
    )
    add_source_arguments(parser)
    add_output_arguments(parser)
    add_report_arguments(parser)
    return parser


def resolve_options(args):
    """Дополняет аргументы значениями по умолчанию."""
    package = args.package if args.package is not None else DEFAULT_PACKAGE
    repository = (args.repository if args.repository is not None
                  else DEFAULT_REPOSITORY)
    version = (args.package_version if args.package_version is not None
               else DEFAULT_VERSION)
    output = args.output if args.output is not None else DEFAULT_OUTPUT
    return {
        "package_name": package,
        "repository": repository,
        "test_mode": args.test_mode,
        "package_version": version,
        "output_file": output,
        "ascii_tree": args.ascii_tree,
        "filter_substring": args.filter_substring,
    }


def validate_options(options):
    """Проверяет значения всех параметров перед запуском."""
    test_mode = options["test_mode"]
    validate_package_name(options["package_name"])
    validate_version(options["package_version"])
    validate_output_file(options["output_file"])
    validate_filter(options["filter_substring"])
    options["repository"] = validate_repository(
        options["repository"], test_mode
    )
    return options


def format_config(options):
    """Форматирует параметры приложения в виде строк «ключ: значение»."""
    lines = []
    for key in FIELDS:
        value = options[key]
        display = str(value).lower() if isinstance(value, bool) else value
        lines.append(f"{key}: {display}")
    return "\n".join(lines)


def configure_console():
    """Переключает потоки вывода в UTF-8, чтобы русский текст не падал."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def main(argv=None):
    """Точка входа CLI: печатает проверенную конфигурацию."""
    configure_console()
    args = build_arg_parser().parse_args(argv)
    try:
        options = validate_options(resolve_options(args))
    except ConfigError as exc:
        print(f"Ошибка {exc}", file=sys.stderr)
        return EXIT_ERROR
    print(format_config(options))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
