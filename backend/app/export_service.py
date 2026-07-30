from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .architecture_schemas import MindMapResult
from .mindmap_layout import (
    LayoutResult,
    NodeSize,
    compute_mindmap_layout,
    find_spacing_violations,
    plan_raster_size,
)


FONT_CANDIDATES = [
    Path("C:/Windows/Fonts/msyh.ttc"),
    Path("C:/Windows/Fonts/simhei.ttf"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
]
MAX_PNG_PIXELS = 16_000_000
MAX_PNG_DIMENSION = 8_192


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


def _cubic_curve(
    start: tuple[float, float],
    end: tuple[float, float],
    steps: int = 24,
) -> list[tuple[int, int]]:
    control_x = (start[0] + end[0]) / 2
    first = (control_x, start[1])
    second = (control_x, end[1])
    points: list[tuple[int, int]] = []
    for index in range(steps + 1):
        t = index / steps
        inverse = 1 - t
        x = (
            inverse**3 * start[0]
            + 3 * inverse**2 * t * first[0]
            + 3 * inverse * t**2 * second[0]
            + t**3 * end[0]
        )
        y = (
            inverse**3 * start[1]
            + 3 * inverse**2 * t * first[1]
            + 3 * inverse * t**2 * second[1]
            + t**3 * end[1]
        )
        points.append((round(x), round(y)))
    return points


def build_mindmap_layout(
    result: MindMapResult,
) -> tuple[LayoutResult, dict[str, str]]:
    """Measure final PNG boxes once and feed them to the shared layout."""

    label_font = _font(16)
    labels: dict[str, str] = {}
    sizes: dict[str, NodeSize] = {}
    for node in result.nodes:
        is_root = node.id == result.root_id
        is_branch = node.role == "branch_topic"
        width = 230 if is_root else 190 if is_branch else 180
        label = _wrap_label(
            node.name,
            label_font,
            width - 24,
            # Root labels may legally contain up to 80 characters. The layout
            # already grows from measured line count, so truncating them at
            # four lines creates a false "generation was cut off" symptom.
            max_lines=8 if is_root else 5 if is_branch else 6,
        )
        line_count = max(label.count("\n") + 1, 1)
        height = max(
            72 if is_root else 58,
            24 + line_count * 19 + (0 if is_root else 14),
        )
        labels[node.id] = label
        sizes[node.id] = NodeSize(width=width, height=height)

    layout = compute_mindmap_layout(
        node_ids=[node.id for node in result.nodes],
        edges=[(edge.source, edge.target) for edge in result.tree_edges],
        root_id=result.root_id,
        sizes=sizes,
    )
    violations = find_spacing_violations(layout, minimum_gap=24)
    if violations:
        sample = ", ".join(
            f"{left}/{right}" for left, right in violations[:3]
        )
        raise RuntimeError(f"mind-map layout spacing invariant failed: {sample}")
    return layout, labels


def render_mindmap_png(result: MindMapResult) -> bytes:
    layout, labels = build_mindmap_layout(result)
    raster = plan_raster_size(
        canvas_width=layout.canvas_width,
        canvas_height=layout.canvas_height,
        max_pixels=MAX_PNG_PIXELS,
        max_dimension=MAX_PNG_DIMENSION,
    )
    scale = raster.scale
    title_font = _font(max(1, round(28 * scale)))
    label_font = _font(max(1, round(16 * scale)))
    meta_font = _font(max(1, round(11 * scale)))
    node_by_id = {node.id: node for node in result.nodes}

    def scaled_point(node_id: str) -> tuple[float, float]:
        point = layout.positions[node_id]
        return point.x * scale, point.y * scale

    image = Image.new("RGB", (raster.width, raster.height), "#f8fafc")
    draw = ImageDraw.Draw(image)
    title = _wrap_label(
        result.document.title,
        _font(28),
        max(layout.canvas_width - 160, 300),
        max_lines=2,
    )
    draw.multiline_text(
        (raster.width / 2, 32 * scale),
        title,
        fill="#172033",
        font=title_font,
        anchor="ma",
        align="center",
        spacing=max(1, round(4 * scale)),
    )

    for edge in result.tree_edges:
        if edge.source not in layout.positions or edge.target not in layout.positions:
            continue
        source = scaled_point(edge.source)
        target = scaled_point(edge.target)
        target_node = node_by_id[edge.target]
        color = (
            "#d97706"
            if edge.provisional
            else "#0f766e"
            if target_node.role == "branch_topic"
            else "#7aa2d8"
        )
        draw.line(
            _cubic_curve(source, target),
            fill=color,
            width=max(1, round((4 if edge.provisional else 3) * scale)),
        )

    for node_id in layout.positions:
        center_x, center_y = scaled_point(node_id)
        node = node_by_id[node_id]
        is_root = node_id == result.root_id
        is_branch = node.role == "branch_topic"
        size = layout.sizes[node_id]
        width = size.width * scale
        height = size.height * scale
        left = center_x - width / 2
        top = center_y - height / 2
        right = center_x + width / 2
        bottom = center_y + height / 2
        fill = "#1d4ed8" if is_root else "#ecfdf5" if is_branch else "#ffffff"
        outline = "#1d4ed8" if is_root else "#0f766e" if is_branch else "#2563eb"
        text_color = "#ffffff" if is_root else "#172033"
        draw.rounded_rectangle(
            (left, top, right, bottom),
            radius=max(1, round(10 * scale)),
            fill=fill,
            outline=outline,
            width=max(1, round((3 if is_root else 2) * scale)),
        )
        draw.multiline_text(
            (center_x, center_y - 4 * scale),
            labels[node_id],
            fill=text_color,
            font=label_font,
            anchor="mm",
            align="center",
            spacing=max(1, round(3 * scale)),
        )
        if not is_root:
            draw.text(
                (center_x, bottom - 6 * scale),
                f"{node.confidence:.0%}",
                fill="#64748b",
                font=meta_font,
                anchor="ms",
            )

    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()
