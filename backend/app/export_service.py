from __future__ import annotations

from collections import defaultdict
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .architecture_schemas import MindMapResult


FONT_CANDIDATES = [
    Path("C:/Windows/Fonts/msyh.ttc"),
    Path("C:/Windows/Fonts/simhei.ttf"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
]


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in FONT_CANDIDATES:
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def _wrap_label(
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    max_width: int,
    max_lines: int = 3,
) -> str:
    lines: list[str] = []
    current = ""
    for character in text.strip():
        candidate = f"{current}{character}"
        if current and font.getlength(candidate) > max_width:
            lines.append(current)
            current = character
            if len(lines) == max_lines - 1:
                break
        else:
            current = candidate
    if current and len(lines) < max_lines:
        remaining = len("".join(lines)) + len(current)
        if remaining < len(text.strip()):
            current = f"{current[:-1]}…" if len(current) > 1 else "…"
        lines.append(current)
    return "\n".join(lines)


def render_mindmap_png(result: MindMapResult) -> bytes:
    layers: dict[int, list] = defaultdict(list)
    for node in result.nodes:
        layers[node.depth].append(node)
    for nodes in layers.values():
        nodes.sort(key=lambda node: (node.role, node.name, node.id))

    max_depth = max(layers, default=0)
    max_layer_size = max((len(nodes) for nodes in layers.values()), default=1)
    node_width = 176
    node_height = 68
    horizontal_gap = 28
    layer_gap = 150
    canvas_width = min(
        max(1200, max_layer_size * (node_width + horizontal_gap) + 120),
        8000,
    )
    canvas_height = max(720, (max_depth + 1) * layer_gap + 170)

    image = Image.new("RGB", (canvas_width, canvas_height), "#f8fafc")
    draw = ImageDraw.Draw(image)
    title_font = _font(28)
    label_font = _font(18)
    meta_font = _font(13)
    draw.text(
        (canvas_width // 2, 38),
        result.document.title,
        fill="#172033",
        font=title_font,
        anchor="ma",
    )

    positions: dict[str, tuple[int, int]] = {}
    for depth, nodes in layers.items():
        count = max(len(nodes), 1)
        usable_width = canvas_width - 100
        for index, node in enumerate(nodes):
            center_x = int(50 + usable_width * (index + 0.5) / count)
            center_y = 115 + depth * layer_gap
            positions[node.id] = (center_x, center_y)

    for edge in result.tree_edges:
        source = positions.get(edge.source)
        target = positions.get(edge.target)
        if not source or not target:
            continue
        middle_y = (source[1] + target[1]) // 2
        color = "#d97706" if edge.provisional else "#94a3b8"
        draw.line(
            [
                (source[0], source[1] + node_height // 2),
                (source[0], middle_y),
                (target[0], middle_y),
                (target[0], target[1] - node_height // 2),
            ],
            fill=color,
            width=3 if edge.provisional else 2,
            joint="curve",
        )

    node_by_id = {node.id: node for node in result.nodes}
    for node_id, (center_x, center_y) in positions.items():
        node = node_by_id[node_id]
        is_root = node_id == result.root_id
        is_branch = node.role == "branch_topic"
        width = 210 if is_root else node_width
        left = center_x - width // 2
        top = center_y - node_height // 2
        right = center_x + width // 2
        bottom = center_y + node_height // 2
        fill = "#1d4ed8" if is_root else "#ecfdf5" if is_branch else "#ffffff"
        outline = "#1d4ed8" if is_root else "#0f766e" if is_branch else "#2563eb"
        text_color = "#ffffff" if is_root else "#172033"
        draw.rounded_rectangle(
            (left, top, right, bottom),
            radius=10,
            fill=fill,
            outline=outline,
            width=3 if is_root else 2,
        )
        label = _wrap_label(node.name, label_font, width - 24)
        draw.multiline_text(
            (center_x, center_y - 4),
            label,
            fill=text_color,
            font=label_font,
            anchor="mm",
            align="center",
            spacing=3,
        )
        if not is_root:
            draw.text(
                (center_x, bottom - 6),
                f"{node.confidence:.0%}",
                fill="#64748b",
                font=meta_font,
                anchor="ms",
            )

    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()
