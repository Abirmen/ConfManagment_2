"""Вычисление порядка загрузки зависимостей (этап 4)."""


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