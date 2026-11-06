"""Визуализатор графа зависимостей Cargo (вариант 2, этап 5).

Точка входа CLI: параметры задаются аргументами командной строки.
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from html import escape
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TEST_REPO = PROJECT_ROOT / "tests" / "test_repo5.txt"
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
        help="Версия пакета (по умолчанию: последняя стабильная; "
             "в тестовом режиме: 1.0.0)",
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
        default=True,
        help="Выводить ASCII-дерево зависимостей (включено по умолчанию)",
    )


def add_report_arguments(parser):
    """Добавляет аргументы фильтра и дополнительных отчётов."""
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


def build_arg_parser():
    """Создаёт парсер аргументов командной строки."""
    parser = argparse.ArgumentParser(
        description="Визуализатор графа зависимостей Cargo (вариант 2)"
    )
    add_source_arguments(parser)
    add_output_arguments(parser)
    add_report_arguments(parser)
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


# ====================================================================
# Зависимости Cargo: HTTP-клиент, SemVer, источник графа
# ====================================================================
# Получение зависимостей и разрешение версий пакетов Rust (Cargo).

USER_AGENT = "cargo-dep-visualizer/0.5 (educational-project)"

TIMEOUT_SECONDS = 15

HTTP_NOT_FOUND = 404

LEN_ONE = 1

LEN_TWO = 2

LEN_THREE = 3

SINGLE_PART = 1

TWO_PARTS = 2

FULL_PARTS = 3

SEMVER_RE = re.compile(
    r"^([0-9]+)\.([0-9]+)\.([0-9]+)"
    r"(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$"
)

COMP_RE = re.compile(r"^(\^|~|>=|<=|>|<|=)?\s*([0-9]+(?:\.[0-9xX*]+)*)")

class RepoError(RuntimeError):
    """Ошибка обращения к репозиторию Cargo или тестовому файлу."""

    def __init__(self, code, message):
        """Сохраняет код и описание ошибки репозитория."""
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
    if length == LEN_ONE:
        return f"1/{lower}"
    if length == LEN_TWO:
        return f"2/{lower}"
    if length == LEN_THREE:
        return f"3/{lower[0]}/{lower}"
    return f"{lower[:2]}/{lower[2:4]}/{lower}"

def crate_api_prefix(base_url):
    """Возвращает базовый префикс `/api/v1/crates` для реестра."""
    clean = base_url.rstrip("/")
    if clean.endswith("/api/v1/crates"):
        return clean
    return f"{clean}/api/v1/crates"

def build_api_url(base_url, package_name, version):
    """Формирует URL запроса зависимостей конкретной версии пакета."""
    prefix = crate_api_prefix(base_url)
    pkg = quote(package_name, safe="")
    ver = quote(version, safe="")
    return f"{prefix}/{pkg}/{ver}/dependencies"

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

def resolve_dep_name(item):
    """Извлекает непустое имя пакета из словаря зависимости."""
    for field in ("crate_id", "package", "name"):
        val = item.get(field)
        if isinstance(val, str) and val.strip():
            return val.strip()
    raise RepoError("E13", "В метаданных не указано имя зависимости")

def extract_dep_entry(item):
    """Извлекает имя и требование к версии для обычной зависимости."""
    if not isinstance(item, dict):
        raise RepoError("E13", "Запись зависимости не является объектом")
    kind = item.get("kind") or "normal"
    if kind != "normal" or bool(item.get("optional", False)):
        return None
    name = resolve_dep_name(item)
    req = str(item.get("req") or "*").strip()
    return name, req

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

def load_sparse_records(base_url, package_name):
    """Загружает все записи версий пакета из sparse-индекса Cargo."""
    clean = base_url.rstrip("/")
    url = f"{clean}/{sparse_index_path(package_name)}"
    body = http_get_text(url)
    records = []
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except ValueError as exc:
            msg = "Повреждённая строка JSON в sparse-индексе"
            raise RepoError("E13", msg) from exc
        if isinstance(record, dict):
            records.append(record)
    return records

def fetch_from_sparse(base_url, package_name, version):
    """Получает прямые зависимости конкретной версии из sparse-индекса."""
    for record in load_sparse_records(base_url, package_name):
        if record.get("vers") == version:
            if "deps" not in record:
                raise RepoError("E13", "В записи индекса нет поля deps")
            return collect_dependencies(record["deps"])
    msg = f"Версия {version} пакета {package_name} не найдена"
    raise RepoError("E11", msg)

def fetch_direct_dependencies(repository, package_name, version):
    """Возвращает отсортированный список прямых зависимостей пакета."""
    if is_sparse_repository(repository):
        return fetch_from_sparse(repository, package_name, version)
    return fetch_from_api(repository, package_name, version)

def parse_semver(version_str):
    """Разбирает строку SemVer в кортеж (major, minor, patch, pre)."""
    match = SEMVER_RE.fullmatch(version_str.strip())
    if not match:
        return None
    major, minor, patch, pre = match.groups()
    return int(major), int(minor), int(patch), pre or ""

def caret_upper_bound(nums):
    """Вычисляет верхнюю границу диапазона для оператора '^' в Cargo."""
    padded = (list(nums) + [0, 0, 0])[:FULL_PARTS]
    major, minor, patch = padded[0], padded[1], padded[2]
    if major:
        return (major + 1, 0, 0)
    if len(nums) == SINGLE_PART:
        return (1, 0, 0)
    if minor:
        return (0, minor + 1, 0)
    if len(nums) == TWO_PARTS:
        return (0, 1, 0)
    return (0, 0, patch + 1)

def tilde_upper_bound(nums):
    """Вычисляет верхнюю границу диапазона для оператора '~' в Cargo."""
    padded = (list(nums) + [0, 0, 0])[:FULL_PARTS]
    if len(nums) == SINGLE_PART:
        return (padded[0] + 1, 0, 0)
    return (padded[0], padded[1] + 1, 0)

def normalize_op(op, parts_count):
    """Уточняет оператор '=' для сокращённой записи версии."""
    if op == "=" and parts_count < FULL_PARTS:
        return "~" if parts_count == TWO_PARTS else "^"
    return op

def apply_comparator_op(op, ver_tuple, target, nums):
    """Применяет оператор сравнения SemVer к кортежу версии."""
    if op == "^":
        return target <= ver_tuple < caret_upper_bound(nums)
    if op == "~":
        return target <= ver_tuple < tilde_upper_bound(nums)
    ops = {
        ">=": ver_tuple >= target,
        "<=": ver_tuple <= target,
        ">": ver_tuple > target,
        "<": ver_tuple < target,
        "=": ver_tuple == target,
    }
    return ops.get(op, True)

def check_comparator(ver_tuple, token):
    """Проверяет соответствие версии одному SemVer-компаратору."""
    clean = token.strip()
    if not clean or clean == "*":
        return True
    match = COMP_RE.match(clean)
    if not match:
        return True
    raw_op = match.group(1) if match.group(1) else "^"
    nums = [int(p) for p in match.group(2).split(".") if p.isdigit()]
    if not nums:
        return True
    padded = (nums + [0, 0, 0])[:FULL_PARTS]
    target = (padded[0], padded[1], padded[2])
    op = normalize_op(raw_op, len(nums))
    return apply_comparator_op(op, ver_tuple, target, nums)

def matches_version_req(version_str, req_str):
    """Проверяет, удовлетворяет ли стабильная версия строке Cargo req."""
    parsed = parse_semver(version_str)
    if parsed is None or parsed[3]:
        return False
    ver_tuple = parsed[:FULL_PARTS]
    parts = [part.strip() for part in req_str.split(",") if part.strip()]
    return all(check_comparator(ver_tuple, part) for part in parts)

def extract_api_version_nums(versions):
    """Отбирает номера активных версий из списка API crates.io."""
    result = []
    for item in versions:
        if not isinstance(item, dict) or item.get("yanked", False):
            continue
        num = item.get("num")
        if num:
            result.append(str(num))
    return result

def fetch_available_versions(repository, package_name):
    """Возвращает список доступных не-отозванных версий пакета."""
    if is_sparse_repository(repository):
        records = load_sparse_records(repository, package_name)
        return [
            str(r["vers"])
            for r in records
            if r.get("vers") and not r.get("yanked", False)
        ]
    url = f"{crate_api_prefix(repository)}/{quote(package_name, safe='')}"
    body = http_get_text(url)
    try:
        data = json.loads(body)
    except ValueError as exc:
        raise RepoError("E13", "Ответ со списком версий не JSON") from exc
    versions = data.get("versions") if isinstance(data, dict) else None
    if not isinstance(versions, list):
        raise RepoError("E13", "В ответе реестра отсутствует поле versions")
    return extract_api_version_nums(versions)

def collect_stable_versions(versions):
    """Возвращает список стабильных версий в виде пар (кортеж, строка)."""
    stable = []
    for ver in versions:
        parsed = parse_semver(ver)
        if parsed and not parsed[3]:
            stable.append((parsed[:FULL_PARTS], ver))
    return stable

def select_best_version(versions, version_req):
    """Выбирает наибольшую подходящую SemVer-версию из списка."""
    stable = collect_stable_versions(versions)
    candidates = [
        item for item in stable if matches_version_req(item[1], version_req)
    ]
    pool = candidates if candidates else stable
    if pool:
        pool.sort(key=lambda item: item[0], reverse=True)
        return pool[0][1]
    raise RepoError("E11", f"Нет подходящей версии для '{version_req}'")

class CargoGraphSource:
    """Кэширующий поставщик соседей графа для пакетов Cargo."""

    def __init__(self, repository, root_package, root_version=None):
        """Инициализирует кэши версий и прямых зависимостей."""
        self.repository = repository
        if root_version is None:
            available = fetch_available_versions(repository, root_package)
            root_version = select_best_version(available, "*")
        self.resolved = {root_package: root_version}
        self.versions_cache = {}
        self.deps_cache = {}

    def resolve_req(self, package_name, version_req):
        """Сопоставляет требование версии конкретному номеру релиза."""
        if package_name in self.resolved:
            return self.resolved[package_name]
        if package_name not in self.versions_cache:
            self.versions_cache[package_name] = fetch_available_versions(
                self.repository, package_name
            )
        chosen = select_best_version(
            self.versions_cache[package_name], version_req
        )
        self.resolved[package_name] = chosen
        return chosen

    def neighbors(self, package_name):
        """Возвращает имена прямых зависимостей выбранной версии пакета."""
        version = self.resolved[package_name]
        key = (package_name, version)
        if key not in self.deps_cache:
            self.deps_cache[key] = fetch_direct_dependencies(
                self.repository, package_name, version
            )
        deps = self.deps_cache[key]
        result = []
        for dep_name, version_req in deps:
            self.resolve_req(dep_name, version_req)
            result.append(dep_name)
        return result


# ====================================================================
# Построение транзитивного графа зависимостей
# ====================================================================
# Построение транзитивного графа зависимостей (DFS без рекурсии).

TEST_PKG_RE = re.compile(r"^[A-Z]+$")

TEST_VERSION_RE = re.compile(
    r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)

STATE_NEW = 0

STATE_ACTIVE = 1

STATE_DONE = 2

class TestRepository(dict):
    """Словарь тестового репозитория, хранящий ещё и версии пакетов."""

    def __init__(self):
        """Создаёт пустой репозиторий с отдельной картой версий."""
        super().__init__()
        self.versions = {}

def split_name_version(token, line_no, role):
    """Разбирает запись вида 'A' или 'A@1.2.3' на имя и версию."""
    name, _, version = token.partition("@")
    name, version = name.strip(), version.strip()
    if role == "package":
        if not TEST_PKG_RE.fullmatch(name):
            msg = f"Строка {line_no}: имя '{name}' не из заглавных букв A-Z"
            raise RepoError("E15", msg)
    elif not TEST_PKG_RE.fullmatch(name):
        msg = f"Строка {line_no}: зависимость '{name}' не из букв A-Z"
        raise RepoError("E15", msg)
    if version and not TEST_VERSION_RE.fullmatch(version):
        msg = f"Строка {line_no}: неверная версия '{version}'"
        raise RepoError("E15", msg)
    return name, version or None

def parse_test_line(raw_line, line_no):
    """Разбирает одну строку файла тестового репозитория."""
    if ":" not in raw_line:
        msg = f"Строка {line_no}: ожидается формат 'A: B, C'"
        raise RepoError("E15", msg)
    left, right = raw_line.split(":", 1)
    pkg, pkg_version = split_name_version(left, line_no, "package")
    deps = []
    dep_versions = {}
    if right.strip():
        for part in right.split(","):
            dep, dep_version = split_name_version(part, line_no, "dependency")
            if dep not in deps:
                deps.append(dep)
            if dep_version and dep not in dep_versions:
                dep_versions[dep] = dep_version
    return pkg, deps, pkg_version, dep_versions

def load_test_repository(path):
    """Читает описание графа и версий пакетов из тестового файла."""
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise RepoError("E15", f"Ошибка чтения репозитория: {exc}") from exc
    repo = TestRepository()
    for line_no, raw in enumerate(content.splitlines(), start=1):
        clean = raw.split("#", 1)[0].strip()
        if not clean:
            continue
        pkg, deps, pkg_version, dep_versions = parse_test_line(clean, line_no)
        if pkg in repo:
            raise RepoError("E15", f"Строка {line_no}: повтор пакета '{pkg}'")
        repo[pkg] = deps
        for dep, dep_version in dep_versions.items():
            repo.versions.setdefault(dep, dep_version)
        if pkg_version:
            repo.versions[pkg] = pkg_version
    return repo

def is_filtered(name, substring):
    """Проверяет, исключается ли пакет заданной подстрокой."""
    return bool(substring) and substring in name

def push_neighbor(state, stack, cycles, node, dep, get_neighbors):
    """Обрабатывает переход по ребру (node -> dep) в итеративном DFS."""
    dep_state = state.get(dep, STATE_NEW)
    if dep_state == STATE_ACTIVE:
        edge = (node, dep)
        if edge not in cycles:
            cycles.append(edge)
    elif dep_state == STATE_NEW:
        state[dep] = STATE_ACTIVE
        stack.append((dep, iter(get_neighbors(dep))))

def build_graph_dfs(root, filter_substring, get_neighbors):
    """Строит транзитивный граф алгоритмом DFS без рекурсии."""
    if is_filtered(root, filter_substring):
        return {}, []
    graph = {}
    cycles = []
    state = {root: STATE_ACTIVE}
    stack = [(root, iter(get_neighbors(root)))]
    while stack:
        node, iterator = stack[-1]
        graph.setdefault(node, [])
        try:
            dep = next(iterator)
        except StopIteration:
            state[node] = STATE_DONE
            stack.pop()
            continue
        if is_filtered(dep, filter_substring):
            continue
        if dep not in graph[node]:
            graph[node].append(dep)
        push_neighbor(state, stack, cycles, node, dep, get_neighbors)
    return graph, cycles

def format_graph_report(root, graph, cycles):
    """Форматирует текстовое представление графа зависимостей."""
    if not graph:
        return (
            f"Граф зависимостей для {root}: пуст "
            "(корневой пакет отфильтрован)"
        )
    lines = [f"Граф зависимостей (корень: {root}):"]
    ordered = [root] + sorted(k for k in graph if k != root)
    for node in ordered:
        deps = graph[node]
        rhs = ", ".join(deps) if deps else "нет зависимостей"
        lines.append(f"  {node} -> {rhs}")
    if cycles:
        pairs = ", ".join(f"{src} -> {dst}" for src, dst in cycles)
        lines.append(f"Обнаружены циклические зависимости: {pairs}")
    return "\n".join(lines)


# ====================================================================
# Порядок загрузки зависимостей
# ====================================================================
# Вычисление порядка загрузки зависимостей (этап 4).

def build_dependency_counts(graph, excluded):
    """Строит таблицы остаточных зависимостей и обратных связей."""
    remaining = {node: set() for node in graph}
    dependents = {node: [] for node in graph}
    for node, deps in graph.items():
        for dep in deps:
            if dep in graph and (node, dep) not in excluded:
                if dep not in remaining[node]:
                    remaining[node].add(dep)
                    dependents[dep].append(node)
    return remaining, dependents

def kahn_waves(graph, excluded_edges=()):
    """Вычисляет топологический порядок волновым алгоритмом Кана."""
    excluded = set(excluded_edges)
    remaining, dependents = build_dependency_counts(graph, excluded)
    ready = sorted(node for node, deps in remaining.items() if not deps)
    order = []
    while ready:
        next_wave = []
        for node in ready:
            order.append(node)
            for parent in dependents[node]:
                remaining[parent].discard(node)
                if not remaining[parent]:
                    next_wave.append(parent)
        ready = sorted(next_wave)
    visited = set(order)
    blocked = sorted(node for node in graph if node not in visited)
    return order, blocked

def compute_load_order(graph, cycles=()):
    """Возвращает порядок загрузки и сведения о циклах для графа."""
    strict_order, blocked = kahn_waves(graph)
    if not blocked:
        return {
            "has_cycle": False,
            "order": strict_order,
            "blocked": [],
            "approx_order": strict_order,
        }
    approx_order, still_blocked = kahn_waves(graph, cycles)
    if still_blocked:
        approx_order = []
    return {
        "has_cycle": True,
        "order": strict_order,
        "blocked": blocked,
        "approx_order": approx_order,
    }

def format_node_label(node, versions):
    """Форматирует имя пакета с версией (если версия известна)."""
    if versions and node in versions:
        return f"{node} ({versions[node]})"
    return node

def append_numbered_list(lines, items, versions):
    """Добавляет нумерованный список пакетов в выходной отчёт."""
    for index, node in enumerate(items, start=1):
        label = format_node_label(node, versions)
        lines.append(f"  {index}. {label}")

def format_cycle_order(root, result, cycles, versions):
    """Форматирует отчёт о порядке загрузки при наличии циклов."""
    lines = [
        f"Порядок загрузки зависимостей (корень: {root}):",
        "Внимание: строгий топологический порядок не существует "
        "из-за циклов.",
        "Заблокированные циклом пакеты: " + ", ".join(result["blocked"]),
    ]
    if cycles:
        pairs = ", ".join(f"{src} -> {dst}" for src, dst in cycles)
        lines.append(f"Циклические рёбра: {pairs}")
    before = ", ".join(result["order"]) if result["order"] else "нет"
    lines.append(f"Доступны к загрузке до цикла: {before}")
    if result["approx_order"]:
        lines.append(
            "Приближённый порядок (после разрыва обратных рёбер DFS):"
        )
        append_numbered_list(lines, result["approx_order"], versions)
    return "\n".join(lines)

def format_load_order_report(root, graph, cycles=(), versions=None):
    """Форматирует итоговый вывод порядка загрузки зависимостей."""
    if not graph:
        return (
            f"Порядок загрузки зависимостей для {root}: пуст "
            "(корневой пакет отфильтрован)"
        )
    result = compute_load_order(graph, cycles)
    if result["has_cycle"]:
        return format_cycle_order(root, result, cycles, versions)
    lines = [f"Порядок загрузки зависимостей (корень: {root}):"]
    append_numbered_list(lines, result["order"], versions)
    return "\n".join(lines)


# ====================================================================
# Встроенная отрисовка SVG
# ====================================================================
# Встроенный рендеринг графа зависимостей в формат SVG (этап 5).

BYPASS_Y_OFFSET = 30

ALIGN_X_TOLERANCE = 10

def assign_layers(graph, cycles=()):
    """Распределяет вершины графа по уровням иерархии сверху вниз."""
    cycle_set = set(cycles)
    topo_order, _ = kahn_waves(graph, cycle_set)
    layers = {node: 0 for node in graph}
    for src in reversed(topo_order):
        for dst in graph.get(src, ()):
            if dst in layers and (src, dst) not in cycle_set:
                layers[dst] = max(layers[dst], layers[src] + 1)
    return layers

def group_rows(root, graph, layers):
    """Группирует узлы по горизонтальным слоям в порядке уровней."""
    by_level = {}
    for node in graph:
        level = layers.get(node, 0)
        by_level.setdefault(level, []).append(node)
    rows = []
    for level in sorted(by_level):
        nodes = sorted(by_level[level])
        if root in nodes:
            nodes.remove(root)
            nodes.insert(0, root)
        rows.append(nodes)
    return rows

def measure_box_size(graph, versions):
    """Вычисляет единый размер прямоугольника узла."""
    max_chars = max((len(name) for name in graph), default=8)
    if versions:
        ver_chars = max((len(v) + 1 for v in versions.values()), default=0)
        max_chars = max(max_chars, ver_chars)
    box_w = max(140, min(280, max_chars * 8 + 36))
    box_h = 52 if versions else 40
    return box_w, box_h

def compute_layout(root, graph, cycles, versions):
    """Рассчитывает координаты узлов и габариты SVG-холста."""
    layers = assign_layers(graph, cycles)
    rows = group_rows(root, graph, layers)
    box_w, box_h = measure_box_size(graph, versions)
    h_gap, v_gap = 40, 72
    pad_x, pad_y = 48, 40
    extra_right = 64 if cycles else 0
    max_cols = max((len(row) for row in rows), default=1)
    inner_w = max_cols * box_w + (max_cols - 1) * h_gap
    width = max(360, inner_w + 2 * pad_x + extra_right)
    total_h = len(rows) * box_h + (len(rows) - 1) * v_gap + 2 * pad_y
    height = max(140, total_h)
    positions = {}
    for row_idx, row in enumerate(rows):
        row_w = len(row) * box_w + (len(row) - 1) * h_gap
        start_x = (width - extra_right - row_w) / 2
        pos_y = pad_y + row_idx * (box_h + v_gap)
        for col_idx, node in enumerate(row):
            pos_x = start_x + col_idx * (box_w + h_gap)
            positions[node] = (pos_x, pos_y, box_w, box_h)
    return positions, int(width), int(height)

def svg_defs():
    """Возвращает описание маркеров стрелок для SVG."""
    return (
        "  <defs>\n"
        '    <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" '
        'markerWidth="7" markerHeight="7" orient="auto">\n'
        '      <path d="M 0 1 L 10 5 L 0 9 z" fill="#475569"/>\n'
        "    </marker>\n"
        '    <marker id="arrow-cycle" viewBox="0 0 10 10" refX="9" '
        'refY="5" markerWidth="7" markerHeight="7" orient="auto">\n'
        '      <path d="M 0 1 L 10 5 L 0 9 z" fill="#dc2626"/>\n'
        "    </marker>\n"
        "  </defs>"
    )

def render_cycle_path(src_box, dst_box, is_self_loop):
    """Формирует SVG-путь для петли или обратного ребра цикла."""
    sx, sy, sw, sh = src_box
    if is_self_loop:
        x0 = sx + sw
        y1, y2 = sy + sh * 0.32, sy + sh * 0.72
        path = (
            f"M {x0:.1f} {y1:.1f} "
            f"C {x0 + 44:.1f} {y1 - 14:.1f}, "
            f"{x0 + 44:.1f} {y2 + 14:.1f}, {x0:.1f} {y2:.1f}"
        )
    else:
        dx, dy, dw, dh = dst_box
        x1, y1 = sx + sw, sy + sh / 2
        x2, y2 = dx + dw, dy + dh / 2
        arc_x = max(x1, x2) + 46
        path = (
            f"M {x1:.1f} {y1:.1f} "
            f"C {arc_x:.1f} {y1:.1f}, {arc_x:.1f} {y2:.1f}, "
            f"{x2:.1f} {y2:.1f}"
        )
    return (
        f'    <path d="{path}" fill="none" stroke="#dc2626" '
        'stroke-width="1.8" stroke-dasharray="6,4" '
        'marker-end="url(#arrow-cycle)"/>'
    )

def render_edge_svg(src, dst, positions, cycle_set):
    """Формирует SVG-элемент направленного ребра между двумя узлами."""
    src_box, dst_box = positions[src], positions[dst]
    sx, sy, sw, sh = src_box
    dx, dy, dw, dh = dst_box
    if (src, dst) in cycle_set or dy <= sy:
        return render_cycle_path(src_box, dst_box, src == dst)
    x1, y1 = sx + sw / 2, sy + sh
    x2, y2 = dx + dw / 2, dy
    if y2 - y1 > sh + BYPASS_Y_OFFSET and abs(x1 - x2) < ALIGN_X_TOLERANCE:
        ctrl_x = x1 + sw * 0.65
        path = (
            f"M {x1:.1f} {y1:.1f} "
            f"C {ctrl_x:.1f} {y1 + 28:.1f}, "
            f"{ctrl_x:.1f} {y2 - 28:.1f}, {x2:.1f} {y2:.1f}"
        )
    else:
        mid_y = (y1 + y2) / 2
        path = (
            f"M {x1:.1f} {y1:.1f} "
            f"C {x1:.1f} {mid_y:.1f}, {x2:.1f} {mid_y:.1f}, "
            f"{x2:.1f} {y2:.1f}"
        )
    return (
        f'    <path d="{path}" fill="none" stroke="#475569" '
        'stroke-width="1.6" marker-end="url(#arrow)"/>'
    )

def svg_text_line(cx, pos_y, size, color, text, bold=False):
    """Формирует SVG-элемент одной строки текста внутри узла."""
    weight = ' font-weight="600"' if bold else ""
    font = "Segoe UI, Arial, sans-serif"
    return (
        f'      <text x="{cx:.1f}" y="{pos_y:.1f}" '
        f'text-anchor="middle" font-family="{font}" '
        f'font-size="{size}"{weight} fill="{color}">'
        f"{escape(text)}</text>"
    )

def render_node_svg(node, box, is_root, version):
    """Формирует SVG-группу прямоугольника и подписи для одного пакета."""
    pos_x, pos_y, box_w, box_h = box
    fill = "#dbeafe" if is_root else "#f8fafc"
    stroke = "#2563eb" if is_root else "#64748b"
    cx = pos_x + box_w / 2
    lines = [
        "    <g>",
        f'      <rect x="{pos_x:.1f}" y="{pos_y:.1f}" width="{box_w}" '
        f'height="{box_h}" rx="8" ry="8" fill="{fill}" '
        f'stroke="{stroke}" stroke-width="1.6"/>',
    ]
    if version:
        ver_label = f"v{version}"
        lines.append(
            svg_text_line(cx, pos_y + 22, 13, "#0f172a", node, True)
        )
        lines.append(
            svg_text_line(cx, pos_y + 39, 11, "#475569", ver_label)
        )
    else:
        lines.append(
            svg_text_line(cx, pos_y + 25, 14, "#0f172a", node, True)
        )
    lines.append("    </g>")
    return "\n".join(lines)

def render_empty_svg(root):
    """Возвращает корректный минимальный SVG для пустого графа."""
    title = escape(f"Пустой граф ({root} отфильтрован)")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<svg xmlns="http://www.w3.org/2000/svg" width="380" height="100" '
        'viewBox="0 0 380 100">\n'
        '  <rect width="100%" height="100%" fill="#ffffff"/>\n'
        '  <rect x="20" y="20" width="340" height="60" rx="8" ry="8" '
        'fill="#f8fafc" stroke="#94a3b8" stroke-dasharray="5,4"/>\n'
        '  <text x="190" y="55" text-anchor="middle" '
        'font-family="Segoe UI, Arial, sans-serif" font-size="13" '
        f'fill="#475569">{title}</text>\n'
        "</svg>\n"
    )

def render_builtin_svg(root, graph, cycles=(), versions=None):
    """Генерирует полное SVG-изображение графа зависимостей."""
    if not graph:
        return render_empty_svg(root)
    positions, width, height = compute_layout(root, graph, cycles, versions)
    cycle_set = set(cycles)
    ordered = [root] + sorted(n for n in graph if n != root)
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
        f'height="{height}" viewBox="0 0 {width} {height}">',
        f"  <title>Граф зависимостей: {escape(root)}</title>",
        '  <rect width="100%" height="100%" fill="#ffffff"/>',
        svg_defs(),
        '  <g id="edges">',
    ]
    for src in ordered:
        for dst in graph[src]:
            if dst in positions:
                parts.append(render_edge_svg(src, dst, positions, cycle_set))
    parts.append("  </g>")
    parts.append('  <g id="nodes">')
    for node in ordered:
        ver = versions.get(node) if versions else None
        is_root = node == root
        parts.append(render_node_svg(node, positions[node], is_root, ver))
    parts.append("  </g>")
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


# ====================================================================
# D2, SVG и ASCII-дерево
# ====================================================================
# Формирование диаграмм D2, экспорт в SVG и вывод ASCII-дерева (этап 5).

def escape_d2(value):
    """Экранирует спецсимволы строки для литералов языка D2."""
    return value.replace("\\", "\\\\").replace('"', '\\"')

def format_d2_label(node, versions):
    """Формирует текстовую подпись узла для диаграммы D2."""
    if versions and node in versions:
        return f"{node} ({versions[node]})"
    return node

def format_tree_label(node, versions):
    """Формирует подпись узла для вывода в формате ASCII-дерева."""
    if versions and node in versions:
        return f"{node} v{versions[node]}"
    return node

def build_d2_edges(ordered, graph, cycle_set):
    """Формирует список строковых описаний рёбер на языке D2."""
    edges = []
    for src in ordered:
        for dst in graph[src]:
            s_key, d_key = f'"{escape_d2(src)}"', f'"{escape_d2(dst)}"'
            if (src, dst) in cycle_set:
                edges.append(
                    f'{s_key} -> {d_key}: "cycle" '
                    '{style.stroke: "#dc2626"; style.stroke-dash: 4}'
                )
            else:
                edges.append(f"{s_key} -> {d_key}")
    return edges

def generate_d2(root, graph, cycles=(), versions=None):
    """Формирует текстовое описание графа зависимостей на языке D2."""
    if not graph:
        return f"# Граф зависимостей для {root} пуст\n"
    lines = ["direction: down", ""]
    ordered = [root] + sorted(n for n in graph if n != root)
    for node in ordered:
        key = f'"{escape_d2(node)}"'
        label = escape_d2(format_d2_label(node, versions))
        if node == root:
            lines.append(f'{key}: "{label}" {{style.fill: "#dbeafe"}}')
        else:
            lines.append(f'{key}: "{label}"')
    edges = build_d2_edges(ordered, graph, set(cycles))
    if edges:
        lines.append("")
        lines.extend(edges)
    return "\n".join(lines) + "\n"

def push_tree_children(stack, children, prefix, path_set):
    """Помещает дочерние узлы в стек обхода ASCII-дерева."""
    total = len(children)
    for idx in range(total - 1, -1, -1):
        is_last = idx == total - 1
        branch = "└── " if is_last else "├── "
        next_prefix = prefix + ("    " if is_last else "│   ")
        stack.append((children[idx], prefix + branch, next_prefix, path_set))

def format_ascii_tree(root, graph, versions=None):
    """Строит ASCII-дерево зависимостей итеративным обходом без рекурсии."""
    if not graph:
        return f"{root} (корневой пакет отфильтрован)"
    lines = [format_tree_label(root, versions)]
    expanded = {root}
    stack = []
    push_tree_children(stack, graph[root], "", {root})
    while stack:
        node, line_prefix, next_prefix, path_set = stack.pop()
        label = format_tree_label(node, versions)
        if node in path_set:
            lines.append(f"{line_prefix}{label} [цикл]")
            continue
        deps = graph.get(node, [])
        if deps and node in expanded:
            lines.append(f"{line_prefix}{label} (*)")
            continue
        lines.append(f"{line_prefix}{label}")
        if deps:
            expanded.add(node)
            push_tree_children(stack, deps, next_prefix, path_set | {node})
    return "\n".join(lines)

def try_external_d2(d2_text, out_path):
    """Пробует сгенерировать SVG с помощью установленной утилиты d2."""
    d2_bin = shutil.which("d2")
    if not d2_bin:
        return False
    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            d2_file = Path(tmp_dir) / "diagram.d2"
            d2_file.write_text(d2_text, encoding="utf-8")
            proc = subprocess.run(
                [d2_bin, str(d2_file), str(out_path)],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            return proc.returncode == EXIT_OK and out_path.is_file()
    except OSError:
        return False

def save_svg_graph(d2_text, out_path, root, graph, cycles=(), versions=None):
    """Сохраняет граф в SVG (через утилиту d2 или встроенный рендерер)."""
    target = Path(out_path)
    try:
        if try_external_d2(d2_text, target):
            return target
        svg_text = render_builtin_svg(root, graph, cycles, versions)
        target.write_text(svg_text, encoding="utf-8")
    except OSError as exc:
        raise RepoError("E16", f"Не удалось записать SVG: {exc}") from exc
    return target


if __name__ == "__main__":
    sys.exit(main())
