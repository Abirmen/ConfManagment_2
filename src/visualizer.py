"""Формирование диаграмм D2, экспорт в SVG и вывод ASCII-дерева (этап 5)."""

import shutil
import subprocess
import tempfile
from pathlib import Path

from cargo_repo import RepoError
from svg_renderer import render_builtin_svg


EXIT_OK = 0


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