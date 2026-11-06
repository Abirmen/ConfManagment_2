"""Получение прямых зависимостей пакетов Rust (Cargo) по HTTP."""

import json
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen


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