"""Построение транзитивного графа зависимостей (DFS без рекурсии)."""

import re

from cargo_repo import RepoError


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