"""Построение транзитивного графа зависимостей (DFS без рекурсии)."""

import re

from cargo_repo import RepoError


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
