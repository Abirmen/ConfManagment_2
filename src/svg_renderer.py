"""Встроенный рендеринг графа зависимостей в формат SVG (этап 5)."""

from html import escape

from load_order import kahn_waves


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