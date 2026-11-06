"""Получение зависимостей и разрешение версий пакетов Rust (Cargo)."""

import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen


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

    def __init__(self, repository, root_package, root_version):
        """Инициализирует кэши версий и прямых зависимостей."""
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