"""Построение графа зависимостей Cargo (вариант 2, этап 3).

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


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TEST_REPO = PROJECT_ROOT / "tests" / "test_repo.txt"
DEFAULT_PACKAGE = "serde_derive"
DEFAULT_REPOSITORY = "https://crates.io"
DEFAULT_TEST_PACKAGE = "A"
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
        description="Визуализатор графа зависимостей Cargo (вариант 2, этап 3)"
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
    output = args.output
    if output is None:
        output = "graph.svg"
    return {
        "package_name": package,
        "repository": repository,
        "test_mode": test_mode,
        "package_version": args.package_version,
        "output_file": output,
        "ascii_tree": args.ascii_tree,
        "filter_substring": args.filter_substring,
    }


def validate_options(options):
    """Проверяет значения всех параметров перед запуском."""
    test_mode = options["test_mode"]
    validate_package_name(options["package_name"], test_mode)
    if options["package_version"] is None and not test_mode:
        raise ConfigError("E07", "Для реестра Cargo укажите версию (1.2.3)")
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
    return build_graph_dfs(
        root, options["filter_substring"], lambda pkg: repo_map.get(pkg, [])
    )


def build_from_cargo_repo(options):
    """Строит транзитивный граф зависимостей из репозитория Cargo."""
    source = CargoGraphSource(
        options["repository"],
        options["package_name"],
        options["package_version"],
    )
    return build_graph_dfs(
        options["package_name"],
        options["filter_substring"],
        source.neighbors,
    )


def run_stage_three(options):
    """Выполняет построение графа и выводит результат анализа."""
    if options["test_mode"]:
        graph, cycles = build_from_test_repo(options)
    else:
        graph, cycles = build_from_cargo_repo(options)
    print(format_graph_report(options["package_name"], graph, cycles))


def configure_console():
    """Переключает потоки вывода в UTF-8, чтобы русский текст не падал."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def main(argv=None):
    """Точка входа CLI для построения графа зависимостей (этап 3)."""
    configure_console()
    args = build_arg_parser().parse_args(argv)
    try:
        options = validate_options(resolve_options(args))
        run_stage_three(options)
    except (ConfigError, RepoError) as exc:
        print(f"Ошибка {exc}", file=sys.stderr)
        return EXIT_ERROR
    return EXIT_OK


# ====================================================================
# Зависимости Cargo: HTTP-клиент, SemVer, источник графа
# ====================================================================
# Получение зависимостей и разрешение версий пакетов Rust (Cargo).

USER_AGENT = "cargo-dep-visualizer/0.3 (educational-project)"

TIMEOUT_SECONDS = 15

SEMVER_RE = re.compile(
    r"^([0-9]+)\.([0-9]+)\.([0-9]+)"
    r"(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$"
)

COMP_RE = re.compile(r"^(\^|~|>=|<=|>|<|=)?\s*([0-9]+(?:\.[0-9xX*]+)*)")

HTTP_NOT_FOUND = 404

SHORT_NAME_ONE = 1

SHORT_NAME_TWO = 2

SHORT_NAME_THREE = 3

SINGLE_PART = 1

MAJOR_MINOR_PARTS = 2

VERSION_PARTS = 3

class RepoError(RuntimeError):
    """Ошибка обращения к репозиторию Cargo или тестовому файлу."""

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

def extract_dep_entry(item):
    """Извлекает имя и требование к версии для обычной зависимости."""
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

def parse_json_body(body, message):
    """Разбирает JSON-ответ и сообщает об ошибке формата."""
    try:
        return json.loads(body)
    except ValueError as exc:
        raise RepoError("E13", message) from exc

def fetch_from_api(base_url, package_name, version):
    """Получает прямые зависимости через совместимый с crates.io API."""
    url = build_api_url(base_url, package_name, version)
    body = http_get_text(url)
    data = parse_json_body(body, "Ответ сервера не является JSON")
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
    padded = (list(nums) + [0, 0, 0])[:VERSION_PARTS]
    major, minor, patch = padded[0], padded[1], padded[2]
    if major:
        return (major + 1, 0, 0)
    if len(nums) == SINGLE_PART:
        return (1, 0, 0)
    if minor:
        return (0, minor + 1, 0)
    if len(nums) == MAJOR_MINOR_PARTS:
        return (0, 1, 0)
    return (0, 0, patch + 1)

def tilde_upper_bound(nums):
    """Вычисляет верхнюю границу диапазона для оператора '~' в Cargo."""
    padded = (list(nums) + [0, 0, 0])[:VERSION_PARTS]
    if len(nums) == SINGLE_PART:
        return (padded[0] + 1, 0, 0)
    return (padded[0], padded[1] + 1, 0)

def parse_comparator(clean):
    """Разбирает оператор и числовые части компаратора."""
    match = COMP_RE.match(clean)
    if not match:
        return "", []
    op = match.group(1) or "^"
    raw_parts = match.group(2).split(".")
    nums = [int(part) for part in raw_parts if part.isdigit()]
    return op, nums

def normalize_operator(op, num_parts):
    """Уточняет оператор '=' для неполной SemVer-версии."""
    if num_parts < VERSION_PARTS and op == "=":
        if num_parts == MAJOR_MINOR_PARTS:
            return "~"
        return "^"
    return op

def compare_operator(ver_tuple, target, op):
    """Сравнивает версии выбранным оператором."""
    comparisons = {
        ">=": ver_tuple >= target,
        "<=": ver_tuple <= target,
        ">": ver_tuple > target,
        "<": ver_tuple < target,
        "=": ver_tuple == target,
    }
    return comparisons.get(op, True)

def check_comparator(ver_tuple, token):
    """Проверяет соответствие версии одному SemVer-компаратору."""
    clean = token.strip()
    if not clean or clean == "*":
        return True
    op, nums = parse_comparator(clean)
    if not nums:
        return True
    padded = (nums + [0, 0, 0])[:VERSION_PARTS]
    target = (padded[0], padded[1], padded[2])
    op = normalize_operator(op, len(nums))
    if op == "^":
        upper = caret_upper_bound(padded[: len(nums)])
        return target <= ver_tuple < upper
    if op == "~":
        return target <= ver_tuple < tilde_upper_bound(nums)
    return compare_operator(ver_tuple, target, op)

def matches_version_req(version_str, req_str):
    """Проверяет, удовлетворяет ли стабильная версия строке Cargo req."""
    parsed = parse_semver(version_str)
    if parsed is None or parsed[3]:
        return False
    ver_tuple = parsed[:3]
    parts = [part.strip() for part in req_str.split(",") if part.strip()]
    return all(check_comparator(ver_tuple, part) for part in parts)

def versions_from_sparse(repository, package_name):
    """Возвращает версии пакета из sparse-индекса."""
    records = load_sparse_records(repository, package_name)
    return [
        str(record["vers"])
        for record in records
        if record.get("vers") and not record.get("yanked", False)
    ]

def versions_from_api(repository, package_name):
    """Возвращает версии пакета из HTTP API реестра."""
    base = crate_api_prefix(repository)
    quoted_name = quote(package_name, safe="")
    body = http_get_text(f"{base}/{quoted_name}")
    data = parse_json_body(body, "Ответ со списком версий не JSON")
    versions = data.get("versions") if isinstance(data, dict) else None
    if not isinstance(versions, list):
        raise RepoError("E13", "В ответе реестра отсутствует поле versions")
    return [
        str(item["num"])
        for item in versions
        if isinstance(item, dict)
        and item.get("num")
        and not item.get("yanked", False)
    ]

def fetch_available_versions(repository, package_name):
    """Возвращает список доступных не-отозванных версий пакета."""
    if is_sparse_repository(repository):
        return versions_from_sparse(repository, package_name)
    return versions_from_api(repository, package_name)

def select_best_version(versions, version_req):
    """Выбирает наибольшую подходящую SemVer-версию из списка."""
    candidates = []
    for ver in versions:
        parsed = parse_semver(ver)
        if parsed and matches_version_req(ver, version_req):
            candidates.append((parsed[:3], ver))
    if candidates:
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]
    fallback = [
        (parse_semver(v)[:3], v)
        for v in versions
        if parse_semver(v) and not parse_semver(v)[3]
    ]
    if fallback:
        fallback.sort(key=lambda item: item[0], reverse=True)
        return fallback[0][1]
    raise RepoError("E11", f"Нет подходящей версии для '{version_req}'")

class CargoGraphSource:
    """Кэширующий поставщик соседей графа для пакетов Cargo."""

    def __init__(self, repository, root_package, root_version):
        """Сохраняет репозиторий, корневой пакет и кэши версий."""
        self.repository = repository
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

WHITE = 0

GRAY = 1

BLACK = 2

def parse_test_line(raw_line, line_no):
    """Разбирает одну строку файла тестового репозитория."""
    if ":" not in raw_line:
        msg = f"Строка {line_no}: ожидается формат 'A: B, C'"
        raise RepoError("E15", msg)
    left, right = raw_line.split(":", 1)
    pkg = left.strip()
    if not TEST_PKG_RE.fullmatch(pkg):
        msg = f"Строка {line_no}: имя '{pkg}' не из заглавных букв A-Z"
        raise RepoError("E15", msg)
    if not right.strip():
        return pkg, []
    deps = []
    for part in right.split(","):
        dep = part.strip()
        if not TEST_PKG_RE.fullmatch(dep):
            msg = f"Строка {line_no}: зависимость '{dep}' не из букв A-Z"
            raise RepoError("E15", msg)
        if dep not in deps:
            deps.append(dep)
    return pkg, deps

def load_test_repository(path):
    """Читает описание графа тестового репозитория из файла."""
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise RepoError("E15", f"Ошибка чтения репозитория: {exc}") from exc
    repo = {}
    for line_no, raw in enumerate(content.splitlines(), start=1):
        clean = raw.split("#", 1)[0].strip()
        if not clean:
            continue
        pkg, deps = parse_test_line(clean, line_no)
        if pkg in repo:
            raise RepoError("E15", f"Строка {line_no}: повтор пакета '{pkg}'")
        repo[pkg] = deps
    return repo

def is_filtered(name, substring):
    """Проверяет, исключается ли пакет заданной подстрокой."""
    return bool(substring) and substring in name

def push_neighbor(state, stack, cycles, node, dep, get_neighbors):
    """Обрабатывает переход по ребру (node -> dep) в итеративном DFS."""
    dep_state = state.get(dep, WHITE)
    if dep_state == GRAY:
        edge = (node, dep)
        if edge not in cycles:
            cycles.append(edge)
    elif dep_state == WHITE:
        state[dep] = GRAY
        stack.append((dep, iter(get_neighbors(dep))))

def build_graph_dfs(root, filter_substring, get_neighbors):
    """Строит транзитивный граф алгоритмом DFS без рекурсии."""
    if is_filtered(root, filter_substring):
        return {}, []
    graph = {}
    cycles = []
    state = {root: GRAY}
    stack = [(root, iter(get_neighbors(root)))]
    while stack:
        node, iterator = stack[-1]
        graph.setdefault(node, [])
        try:
            dep = next(iterator)
        except StopIteration:
            state[node] = BLACK
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


if __name__ == "__main__":
    sys.exit(main())
