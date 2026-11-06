"""Прямые зависимости пакетов Cargo (вариант 2, этап 2).

Точка входа CLI: параметры задаются аргументами командной строки.
"""

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen


DEFAULT_PACKAGE = "serde_derive"
DEFAULT_REPOSITORY = "https://crates.io"
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


def validate_package_name(name):
    """Проверяет корректность имени пакета."""
    if not PACKAGE_RE.fullmatch(name):
        raise ConfigError("E04", "Неверное имя пакета")


def validate_repository(value):
    """Проверяет URL реестра Cargo."""
    if not value:
        raise ConfigError("E06", "repository не может быть пустым")
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
        help="Работать с файлом тестового репозитория (этап 3)",
    )
    parser.add_argument(
        "--version",
        dest="package_version",
        default=None,
        help="Версия пакета (обязательна для реестра Cargo)",
    )


def add_output_arguments(parser):
    """Добавляет аргументы выходного файла и ASCII-дерева."""
    parser.add_argument(
        "-o", "--output",
        default=None,
        help="Имя выходного SVG-файла (по умолчанию: graph.svg)",
    )
    parser.add_argument(
        "--ascii-tree",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Выводить ASCII-дерево зависимостей (этап 5)",
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
        description="Визуализатор графа зависимостей Cargo (вариант 2, этап 2)"
    )
    add_source_arguments(parser)
    add_output_arguments(parser)
    add_report_arguments(parser)
    return parser


def resolve_options(args):
    """Дополняет аргументы значениями по умолчанию для выбранного режима."""
    package = args.package
    if package is None:
        package = DEFAULT_PACKAGE
    repository = args.repository
    if repository is None:
        repository = DEFAULT_REPOSITORY
    output = args.output
    if output is None:
        output = "graph.svg"
    return {
        "package_name": package,
        "repository": repository,
        "test_mode": args.test_mode,
        "package_version": args.package_version,
        "output_file": output,
        "ascii_tree": args.ascii_tree,
        "filter_substring": args.filter_substring,
    }


def validate_options(options):
    """Проверяет значения всех параметров перед запуском."""
    validate_package_name(options["package_name"])
    if options["test_mode"]:
        msg = "Режим тестового репозитория реализуется на этапе 3"
        raise RepoError("E14", msg)
    if options["package_version"] is None:
        raise ConfigError("E07", "Для реестра Cargo укажите версию (1.2.3)")
    validate_version(options["package_version"])
    validate_output_file(options["output_file"])
    validate_filter(options["filter_substring"])
    options["repository"] = validate_repository(options["repository"])
    return options


def run_stage_two(options):
    """Загружает и выводит прямые зависимости пакета Cargo."""
    deps = fetch_direct_dependencies(
        options["repository"],
        options["package_name"],
        options["package_version"],
    )
    print(
        format_direct_dependencies(
            options["package_name"], options["package_version"], deps
        )
    )


def format_direct_dependencies(package_name, version, dependencies):
    """Форматирует прямые зависимости пакета для вывода в консоль."""
    header = f"Прямые зависимости {package_name} {version}:"
    if not dependencies:
        return f"{header} отсутствуют"
    lines = [header]
    for dep_name, version_req in dependencies:
        lines.append(f"- {dep_name} ({version_req})")
    return "\n".join(lines)


def configure_console():
    """Переключает потоки вывода в UTF-8, чтобы русский текст не падал."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def main(argv=None):
    """Точка входа CLI для вывода прямых зависимостей (этап 2)."""
    configure_console()
    args = build_arg_parser().parse_args(argv)
    try:
        options = validate_options(resolve_options(args))
        run_stage_two(options)
    except (ConfigError, RepoError) as exc:
        print(f"Ошибка {exc}", file=sys.stderr)
        return EXIT_ERROR
    return EXIT_OK


# ====================================================================
# Зависимости Cargo: HTTP-клиент и разбор метаданных
# ====================================================================
# Получение прямых зависимостей пакетов Rust (Cargo) по HTTP.

USER_AGENT = "cargo-dep-visualizer/0.2 (educational-project)"

TIMEOUT_SECONDS = 15

HTTP_NOT_FOUND = 404

SHORT_NAME_ONE = 1

SHORT_NAME_TWO = 2

SHORT_NAME_THREE = 3

class RepoError(RuntimeError):
    """Ошибка обращения к репозиторию Cargo или разбора метаданных."""

    def __init__(self, code, message):
        """Сохраняет код и текст ошибки репозитория."""
        super().__init__(f"{code}: {message}")
        self.code = code

def is_sparse_repository(base_url):
    """Определяет, указывает ли URL на sparse-индекс Cargo."""
    parsed = urlparse(base_url)
    host = (parsed.hostname or "").lower()
    path = parsed.path.rstrip("/").lower()
    return host.startswith("index.") or path.endswith("/index")

def sparse_index_path(package_name):
    """Вычисляет путь к файлу пакета в sparse-индексе Cargo."""
    lower = package_name.lower()
    length = len(lower)
    if length == SHORT_NAME_ONE:
        return f"1/{lower}"
    if length == SHORT_NAME_TWO:
        return f"2/{lower}"
    if length == SHORT_NAME_THREE:
        return f"3/{lower[0]}/{lower}"
    return f"{lower[:2]}/{lower[2:4]}/{lower}"

def build_api_url(base_url, package_name, version):
    """Формирует URL запроса зависимостей для HTTP API crates.io."""
    clean = base_url.rstrip("/")
    pkg = quote(package_name, safe="")
    ver = quote(version, safe="")
    if clean.endswith("/api/v1/crates"):
        return f"{clean}/{pkg}/{ver}/dependencies"
    return f"{clean}/api/v1/crates/{pkg}/{ver}/dependencies"

def extract_error_detail(exc):
    """Извлекает текстовую причину из JSON-тела ошибки HTTP."""
    try:
        raw = exc.read().decode("utf-8", errors="replace")
        data = json.loads(raw)
    except (OSError, ValueError, AttributeError):
        return ""
    errors = data.get("errors") if isinstance(data, dict) else None
    if isinstance(errors, list) and errors and isinstance(errors[0], dict):
        return str(errors[0].get("detail") or "").strip()
    return ""

def raise_http_error(exc, url):
    """Преобразует HTTPError в исключение RepoError с кодом."""
    detail = extract_error_detail(exc)
    if exc.code == HTTP_NOT_FOUND:
        msg = "Пакет или версия не найдены"
        if detail:
            msg = f"{msg}: {detail}"
        raise RepoError("E11", msg) from exc
    raise RepoError("E12", f"Ошибка HTTP {exc.code} ({url})") from exc

def http_get_text(url):
    """Выполняет HTTP GET-запрос и возвращает декодированный текст."""
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    request = Request(url, headers=headers, method="GET")
    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset, errors="replace")
    except HTTPError as exc:
        raise_http_error(exc, url)
    except (URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise RepoError("E12", f"Ошибка сети: {reason}") from exc

def extract_dep_entry(item):
    """Извлекает имя и версию для обязательной обычной зависимости."""
    if not isinstance(item, dict):
        raise RepoError("E13", "Запись зависимости не является объектом")
    kind = item.get("kind") or "normal"
    if kind != "normal" or bool(item.get("optional", False)):
        return None
    name = item.get("crate_id") or item.get("package") or item.get("name")
    if not isinstance(name, str) or not name.strip():
        raise RepoError("E13", "В метаданных не указано имя зависимости")
    req = str(item.get("req") or "*").strip()
    return name.strip(), req

def collect_dependencies(raw_items):
    """Собирает уникальные прямые зависимости в алфавитном порядке."""
    if not isinstance(raw_items, list):
        raise RepoError("E13", "Поле зависимостей должно быть списком")
    collected = {}
    for item in raw_items:
        entry = extract_dep_entry(item)
        if entry is not None and entry[0] not in collected:
            collected[entry[0]] = entry[1]
    return sorted(collected.items(), key=lambda pair: pair[0])

def fetch_from_api(base_url, package_name, version):
    """Получает прямые зависимости через совместимый с crates.io API."""
    url = build_api_url(base_url, package_name, version)
    body = http_get_text(url)
    try:
        data = json.loads(body)
    except ValueError as exc:
        raise RepoError("E13", "Ответ сервера не является JSON") from exc
    if isinstance(data, dict) and "errors" in data:
        raise RepoError("E11", "Пакет или версия не найдены")
    if not isinstance(data, dict) or "dependencies" not in data:
        raise RepoError("E13", "В JSON отсутствует поле dependencies")
    return collect_dependencies(data["dependencies"])

def parse_sparse_version(body, package_name, version):
    """Ищет JSON-строку заданной версии пакета в sparse-индексе."""
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except ValueError as exc:
            msg = "Повреждённая строка JSON в sparse-индексе"
            raise RepoError("E13", msg) from exc
        if isinstance(record, dict) and record.get("vers") == version:
            return record
    msg = f"Версия {version} пакета {package_name} не найдена"
    raise RepoError("E11", msg)

def fetch_from_sparse(base_url, package_name, version):
    """Получает прямые зависимости из sparse-индекса Cargo."""
    clean = base_url.rstrip("/")
    url = f"{clean}/{sparse_index_path(package_name)}"
    body = http_get_text(url)
    record = parse_sparse_version(body, package_name, version)
    if "deps" not in record:
        raise RepoError("E13", "В записи индекса отсутствует поле deps")
    return collect_dependencies(record["deps"])

def fetch_direct_dependencies(repository, package_name, version):
    """Возвращает отсортированный список прямых зависимостей пакета."""
    if is_sparse_repository(repository):
        return fetch_from_sparse(repository, package_name, version)
    return fetch_from_api(repository, package_name, version)


if __name__ == "__main__":
    sys.exit(main())
