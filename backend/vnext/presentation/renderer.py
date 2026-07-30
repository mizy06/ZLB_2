from __future__ import annotations

import hashlib
import html
import json
import os
import re
import secrets
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from urllib.parse import quote

from PIL import Image, ImageDraw, ImageFont, PngImagePlugin
from pypdf import PdfReader, PdfWriter

from backend.vnext.artifacts.canonical import (
    canonical_json_bytes,
    payload_digest,
)
from backend.vnext.contracts.graph import CanonicalExplicitGraph
from backend.vnext.contracts.presentation import (
    MediaNodeIdentity,
    MediaProjectionContract,
    PresentationMedium,
    ProjectionMediaBundle,
    RenderedFileKind,
    RenderedMediaFile,
    RenderedPresentationBundle,
)
from backend.vnext.contracts.projection import DiagnosticProjection
from backend.vnext.projection.validation import (
    validate_projection_against_graph,
)

from .pagination import (
    PdfPagePlan,
    plan_pdf_pages,
    plan_png_tiles,
    presentation_tree,
)
from .builder import build_projection_media_bundle


RENDERER_VERSION = "1.0.0"
_DEFAULT_FONT_CANDIDATES = (
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
)
_BACKGROUND = "#f5f7fa"
_TEXT = "#172033"
_MUTED = "#526173"
_ROOT = "#174ea6"
_CHAPTER = "#087f5b"
_ACCENTS = ("#2563eb", "#c2410c", "#7c3aed", "#0e7490")


class PresentationRenderError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class FontFace:
    path: Path
    family: str
    digest: str


@dataclass(frozen=True, slots=True)
class _StaticPage:
    image: Image.Image
    node_ids: tuple[str, ...]
    link_rects: tuple[tuple[str, tuple[int, int, int, int]], ...] = ()


class PresentationRenderStore:
    """Owner-scoped, atomic, immutable output store for shadow render files."""

    def __init__(self, root: Path):
        self.root = root

    def render(
        self,
        graph: CanonicalExplicitGraph,
        projection: DiagnosticProjection,
        media_bundle: ProjectionMediaBundle,
        *,
        owner_id: str,
        font_path: Path | None = None,
        created_at: datetime | None = None,
    ) -> RenderedPresentationBundle:
        validate_projection_against_graph(projection, graph)
        if media_bundle.canonical_graph_ref != projection.canonical_graph_ref:
            raise PresentationRenderError(
                "media bundle does not reference the projection graph"
            )
        if media_bundle.projection_ref.payload_digest != payload_digest(
            projection
        ):
            raise PresentationRenderError(
                "media bundle projection digest does not match payload"
            )
        if (
            media_bundle.canonical_graph_ref.owner_id != owner_id
            or media_bundle.projection_ref.owner_id != owner_id
        ):
            raise PermissionError(
                "render inputs must remain in the requested owner scope"
            )
        expected_bundle = build_projection_media_bundle(
            graph,
            projection,
            canonical_graph_ref=media_bundle.canonical_graph_ref,
            projection_ref=media_bundle.projection_ref,
            created_at=media_bundle.created_at,
        )
        if (
            expected_bundle.semantic_fingerprint
            != media_bundle.semantic_fingerprint
            or expected_bundle.media != media_bundle.media
        ):
            raise PresentationRenderError(
                "media bundle semantics do not match graph and projection"
            )
        timestamp = created_at or datetime.now(UTC)
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("created_at must include a timezone")
        font = _resolve_font(font_path)
        web = _medium(media_bundle, PresentationMedium.WEB)
        _require_font_coverage(font, tuple(item.label for item in web.nodes))

        render_bundle_id = "render_bundle_" + secrets.token_hex(16)
        owner_scope = _owner_scope(owner_id)
        renders = self.root / "owners" / owner_scope / "renders"
        target = renders / render_bundle_id
        pending = renders / (
            f".pending-{render_bundle_id}-{secrets.token_hex(8)}"
        )
        renders.mkdir(parents=True, exist_ok=True)
        pending.mkdir(exist_ok=False)
        try:
            files = self._write_files(
                pending,
                graph=graph,
                projection=projection,
                media_bundle=media_bundle,
                font=font,
            )
            bundle = RenderedPresentationBundle(
                render_bundle_id=render_bundle_id,
                owner_id=owner_id,
                media_bundle_id=media_bundle.media_bundle_id,
                media_bundle_digest=payload_digest(media_bundle),
                canonical_graph_ref=media_bundle.canonical_graph_ref,
                projection_ref=media_bundle.projection_ref,
                semantic_fingerprint=media_bundle.semantic_fingerprint,
                semantic_node_ids=tuple(
                    item.node_id for item in web.nodes
                ),
                renderer_version=RENDERER_VERSION,
                font_family=font.family,
                font_digest=font.digest,
                files=files,
                created_at=timestamp,
            )
            _write_bytes(
                pending / "render-manifest.json",
                (
                    json.dumps(
                        bundle.model_dump(mode="json"),
                        ensure_ascii=False,
                        indent=2,
                        sort_keys=True,
                    )
                    + "\n"
                ).encode("utf-8"),
            )
            _fsync_tree(pending)
            pending.rename(target)
            _fsync_directory(renders)
            return bundle
        except Exception:
            shutil.rmtree(pending, ignore_errors=True)
            raise

    def load(
        self,
        *,
        owner_id: str,
        render_bundle_id: str,
        verify_files: bool = True,
    ) -> RenderedPresentationBundle:
        directory = self.directory(
            owner_id=owner_id,
            render_bundle_id=render_bundle_id,
        )
        bundle = RenderedPresentationBundle.model_validate_json(
            (directory / "render-manifest.json").read_bytes()
        )
        if (
            bundle.owner_id != owner_id
            or bundle.render_bundle_id != render_bundle_id
        ):
            raise PermissionError("render manifest owner or ID mismatch")
        if verify_files:
            for item in bundle.files:
                path = directory / item.relative_path
                data = path.read_bytes()
                if len(data) != item.byte_size:
                    raise PresentationRenderError(
                        f"rendered file size mismatch: {item.relative_path}"
                    )
                if _bytes_digest(data) != item.payload_digest:
                    raise PresentationRenderError(
                        f"rendered file digest mismatch: {item.relative_path}"
                    )
        return bundle

    def directory(
        self,
        *,
        owner_id: str,
        render_bundle_id: str,
    ) -> Path:
        if re.fullmatch(
            r"render_bundle_[0-9a-f]{32}",
            render_bundle_id,
        ) is None:
            raise ValueError("invalid render bundle ID")
        return (
            self.root
            / "owners"
            / _owner_scope(owner_id)
            / "renders"
            / render_bundle_id
        )

    def _write_files(
        self,
        pending: Path,
        *,
        graph: CanonicalExplicitGraph,
        projection: DiagnosticProjection,
        media_bundle: ProjectionMediaBundle,
        font: FontFace,
    ) -> tuple[RenderedMediaFile, ...]:
        web = _medium(media_bundle, PresentationMedium.WEB)
        html_bytes = _render_html(web, media_bundle, graph)
        json_bytes = _render_json(graph, projection, media_bundle)
        png_contract = _medium(media_bundle, PresentationMedium.PNG)
        png_groups = plan_png_tiles(
            png_contract.nodes,
            png_contract.parents,
            png_contract.view_edges,
        )
        if len(png_groups) != png_contract.page_or_tile_count:
            raise PresentationRenderError(
                "PNG pagination no longer matches the media contract"
            )
        pdf_contract = _medium(media_bundle, PresentationMedium.PDF)
        pdf_plans = plan_pdf_pages(
            pdf_contract.nodes,
            pdf_contract.parents,
            pdf_contract.view_edges,
            graph,
        )
        if len(pdf_plans) != pdf_contract.page_or_tile_count:
            raise PresentationRenderError(
                "PDF pagination no longer matches the media contract"
            )

        records: list[RenderedMediaFile] = []
        _write_bytes(pending / "web" / "index.html", html_bytes)
        records.append(
            _file_record(
                kind=RenderedFileKind.WEB_HTML,
                relative_path="web/index.html",
                media_type="text/html",
                data=html_bytes,
                fingerprint=media_bundle.semantic_fingerprint,
                node_ids=tuple(item.node_id for item in web.nodes),
            )
        )

        for index, node_ids in enumerate(png_groups, start=1):
            png_bytes, width, height = _render_png_tile(
                png_contract,
                node_ids=node_ids,
                tile_index=index,
                tile_count=len(png_groups),
                font=font,
            )
            relative_path = f"png/tile-{index:04d}.png"
            _write_bytes(pending / relative_path, png_bytes)
            records.append(
                _file_record(
                    kind=RenderedFileKind.PNG_TILE,
                    relative_path=relative_path,
                    media_type="image/png",
                    data=png_bytes,
                    fingerprint=media_bundle.semantic_fingerprint,
                    node_ids=node_ids,
                    page_or_tile_index=index,
                    pixel_width=width,
                    pixel_height=height,
                )
            )

        pdf_bytes = _render_pdf(
            pdf_contract,
            graph=graph,
            projection=projection,
            page_plans=pdf_plans,
            font=font,
            fingerprint=media_bundle.semantic_fingerprint,
        )
        _write_bytes(pending / "pdf" / "mind-map.pdf", pdf_bytes)
        records.append(
            _file_record(
                kind=RenderedFileKind.PDF,
                relative_path="pdf/mind-map.pdf",
                media_type="application/pdf",
                data=pdf_bytes,
                fingerprint=media_bundle.semantic_fingerprint,
                node_ids=tuple(
                    item.node_id for item in pdf_contract.nodes
                ),
                logical_page_count=len(pdf_plans),
            )
        )

        _write_bytes(pending / "json" / "mind-map.json", json_bytes)
        records.append(
            _file_record(
                kind=RenderedFileKind.JSON,
                relative_path="json/mind-map.json",
                media_type="application/json",
                data=json_bytes,
                fingerprint=media_bundle.semantic_fingerprint,
                node_ids=tuple(
                    item.node_id
                    for item in _medium(
                        media_bundle,
                        PresentationMedium.JSON,
                    ).nodes
                ),
            )
        )
        return tuple(records)


def _medium(
    bundle: ProjectionMediaBundle,
    medium: PresentationMedium,
) -> MediaProjectionContract:
    return next(item for item in bundle.media if item.medium is medium)


def _resolve_font(font_path: Path | None) -> FontFace:
    candidates = (
        (font_path,)
        if font_path is not None
        else (
            *(
                (Path(os.environ["VNEXT_PRESENTATION_FONT"]),)
                if os.environ.get("VNEXT_PRESENTATION_FONT")
                else ()
            ),
            *_DEFAULT_FONT_CANDIDATES,
        )
    )
    selected = next(
        (path.resolve() for path in candidates if path and path.is_file()),
        None,
    )
    if selected is None:
        raise PresentationRenderError(
            "no presentation font is available"
        )
    try:
        face = ImageFont.truetype(str(selected), size=16)
    except OSError as exc:
        raise PresentationRenderError(
            f"presentation font cannot be loaded: {selected}"
        ) from exc
    family, style = face.getname()
    return FontFace(
        path=selected,
        family=f"{family} {style}".strip(),
        digest=_file_digest(selected),
    )


def _require_font_coverage(
    font: FontFace,
    labels: tuple[str, ...],
) -> None:
    face = ImageFont.truetype(str(font.path), size=24)
    missing_mask = bytes(face.getmask("\uffff"))
    missing = sorted(
        {
            character
            for label in labels
            for character in label
            if not character.isspace()
            and ord(character) > 127
            and bytes(face.getmask(character)) == missing_mask
        }
    )
    if missing:
        sample = "".join(missing[:12])
        raise PresentationRenderError(
            "presentation font is missing required glyphs: " + sample
        )


def _render_html(
    media: MediaProjectionContract,
    bundle: ProjectionMediaBundle,
    graph: CanonicalExplicitGraph,
) -> bytes:
    root_id, parent_by_child, children = presentation_tree(
        media.nodes,
        media.parents,
        media.view_edges,
    )
    label_by_id = {item.node_id: item.label for item in media.nodes}
    status_by_id = {item.node_id: item.status for item in media.nodes}
    order_by_id = {item.node_id: item.source_order for item in media.nodes}
    depth_by_id = _depths(root_id, children)
    canvas_nodes = []
    cursor_y = 52
    for node in media.nodes:
        lines = _wrap_by_units(node.label, 30)
        height = max(58, 24 + len(lines) * 20)
        depth = min(depth_by_id[node.node_id], 8)
        canvas_nodes.append(
            {
                "id": node.node_id,
                "label": node.label,
                "lines": lines,
                "status": node.status,
                "order": node.source_order,
                "depth": depth_by_id[node.node_id],
                "x": 56 + depth * 174,
                "y": cursor_y,
                "width": 300 if node.node_id == root_id else 276,
                "height": height,
                "isRoot": node.node_id == root_id,
                "isChapter": parent_by_child.get(node.node_id) == root_id,
            }
        )
        cursor_y += height + 24
    canvas_width = max(
        1360,
        max(item["x"] + item["width"] + 80 for item in canvas_nodes),
    )
    canvas_height = max(680, cursor_y + 20)
    parent_edges = [
        {"source": parent_id, "target": child_id}
        for child_id, parent_id in parent_by_child.items()
    ]
    chapters = list(children[root_id])
    concept_by_id = {
        concept.concept_id: concept for concept in graph.concepts
    }
    evidence_by_id = {
        node.node_id: [
            evidence.ref_id
            for evidence in concept_by_id[node.node_id].source_evidence_refs
        ]
        if node.node_id in concept_by_id
        else []
        for node in media.nodes
    }
    outline = _outline_html(
        root_id,
        children,
        label_by_id,
        status_by_id,
        depth_by_id,
    )
    data = {
        "fingerprint": bundle.semantic_fingerprint,
        "rootId": root_id,
        "nodes": canvas_nodes,
        "edges": parent_edges,
        "crossLinks": [
            item.model_dump(mode="json") for item in media.cross_links
        ],
        "children": children,
        "parents": parent_by_child,
        "order": order_by_id,
        "evidence": evidence_by_id,
        "hiddenIds": media.hidden_ids,
        "overlay": {
            "mode": media.overlay_mode.value,
            "enabled": media.overlay_enabled,
        },
    }
    serialized = json.dumps(
        data,
        ensure_ascii=False,
        separators=(",", ":"),
    ).replace("<", "\\u003c")
    chapter_buttons = "".join(
        (
            '<button type="button" class="chapter-link" '
            f'data-node-id="{html.escape(node_id, quote=True)}">'
            f"{html.escape(label_by_id[node_id])}</button>"
        )
        for node_id in chapters
    )
    title = html.escape(label_by_id[root_id])
    description = html.escape(media.long_description or title)
    document = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src 'self' data:">
<title>{title}</title>
<style>
:root {{
  color-scheme: light;
  font-family: "Noto Sans CJK SC", "Noto Sans SC", Inter, Arial, sans-serif;
  color: #172033;
  background: #f5f7fa;
  letter-spacing: 0;
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; min-width: 320px; background: #f5f7fa; font-size: 16px; line-height: 1.5; }}
header {{ padding: 18px 24px 12px; background: #ffffff; border-bottom: 1px solid #d7dee8; }}
h1 {{ margin: 0; font-size: 24px; line-height: 1.25; letter-spacing: 0; }}
.status {{ margin-top: 4px; color: #526173; font-size: 14px; }}
.chapters {{ display: flex; gap: 8px; overflow-x: auto; padding: 10px 24px; background: #eef2f6; border-bottom: 1px solid #d7dee8; }}
.chapter-link {{ min-height: 36px; padding: 6px 10px; border: 1px solid #087f5b; border-radius: 6px; color: #075e45; background: #ffffff; font: inherit; font-size: 14px; cursor: pointer; white-space: nowrap; }}
.chapter-link:focus-visible, .tree-node:focus-visible {{ outline: 3px solid #c2410c; outline-offset: 2px; }}
.cross-toggle {{ display: inline-flex; align-items: center; gap: 7px; min-height: 36px; padding: 6px 10px; color: #172033; white-space: nowrap; }}
.cross-toggle input {{ width: 20px; height: 20px; accent-color: #c2410c; }}
.workspace {{ display: grid; grid-template-columns: minmax(0, 1fr) 340px; min-height: calc(100vh - 126px); }}
.map-pane {{ overflow: auto; background: #ffffff; }}
canvas {{ display: block; width: {canvas_width}px; height: {canvas_height}px; }}
.side-pane {{ border-left: 1px solid #d7dee8; background: #f8fafc; overflow: auto; }}
.detail {{ padding: 18px; border-bottom: 1px solid #d7dee8; min-height: 150px; }}
.detail h2 {{ margin: 0 0 8px; font-size: 18px; line-height: 1.35; }}
.detail p {{ margin: 4px 0; color: #526173; overflow-wrap: anywhere; }}
.detail ul {{ margin: 8px 0 0; padding-left: 20px; overflow-wrap: anywhere; color: #526173; }}
.outline {{ padding: 12px 10px 24px; }}
.tree-list {{ list-style: none; margin: 0; padding: 0; }}
.tree-list .tree-list {{ padding-left: 16px; }}
.tree-node {{ width: 100%; min-height: 32px; padding: 5px 8px; border: 0; border-radius: 4px; text-align: left; color: #172033; background: transparent; font: inherit; cursor: pointer; }}
.tree-node[aria-selected="true"] {{ color: #ffffff; background: #174ea6; }}
.tree-node[data-level="1"] {{ font-size: 18px; font-weight: 700; }}
.tree-node[data-level="2"] {{ font-size: 16px; font-weight: 650; }}
.long-description {{ position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0,0,0,0); white-space: nowrap; border: 0; }}
@media (max-width: 600px) {{
  header {{ padding: 14px 16px 10px; }}
  h1 {{ font-size: 22px; }}
  .chapters {{ padding: 8px 16px; }}
  .chapter-link {{ min-height: 44px; }}
  .cross-toggle {{ min-height: 44px; }}
  .workspace {{ display: block; min-height: 0; }}
  .map-pane {{ display: none; }}
  .side-pane {{ border-left: 0; }}
  .detail {{ position: sticky; top: 0; z-index: 2; background: #ffffff; }}
  .tree-node {{ min-height: 44px; }}
  .outline {{ padding-inline: 8px; }}
}}
@media (max-width: 320px) {{
  header, .detail {{ padding-inline: 12px; }}
  .chapters {{ padding-inline: 12px; }}
  .tree-list .tree-list {{ padding-left: 10px; }}
}}
</style>
</head>
<body data-semantic-fingerprint="{bundle.semantic_fingerprint}">
<header>
  <h1>{title}</h1>
  <div class="status">Projection {html.escape(media.overlay_mode.value)} · {len(media.nodes)} nodes</div>
</header>
<nav class="chapters" aria-label="一级章节">{chapter_buttons}<label class="cross-toggle"><input id="cross-links" type="checkbox">跨链</label></nav>
<main class="workspace">
  <section class="map-pane" aria-label="思维导图画布" aria-describedby="map-description">
    <canvas id="mindmap" width="{canvas_width}" height="{canvas_height}"></canvas>
    <p id="map-description" class="long-description">{description}</p>
  </section>
  <aside class="side-pane" aria-label="结构大纲与节点详情">
    <section class="detail" aria-live="polite">
      <h2 id="detail-label">{title}</h2>
      <p id="detail-status">{html.escape(status_by_id[root_id])}</p>
      <p id="detail-id">{html.escape(root_id)}</p>
      <ul id="detail-evidence"></ul>
    </section>
    <nav class="outline" aria-label="同步结构大纲">
      <ul class="tree-list" role="tree">{outline}</ul>
    </nav>
  </aside>
</main>
<script>
"use strict";
const model = {serialized};
const canvas = document.getElementById("mindmap");
const context = canvas.getContext("2d");
const nodeById = new Map(model.nodes.map((node) => [node.id, node]));
let selectedId = model.rootId;
let showCrossLinks = false;

function nodeColor(node) {{
  if (node.isRoot) return ["#174ea6", "#ffffff", "#174ea6"];
  if (node.isChapter) return ["#e8f7f1", "#075e45", "#087f5b"];
  const accents = ["#2563eb", "#c2410c", "#7c3aed", "#0e7490"];
  return ["#ffffff", "#172033", accents[node.order % accents.length]];
}}

function draw() {{
  context.clearRect(0, 0, canvas.width, canvas.height);
  context.fillStyle = "#ffffff";
  context.fillRect(0, 0, canvas.width, canvas.height);
  context.lineWidth = 2;
  context.strokeStyle = "#92a3b8";
  for (const edge of model.edges) {{
    const source = nodeById.get(edge.source);
    const target = nodeById.get(edge.target);
    if (!source || !target) continue;
    context.beginPath();
    context.moveTo(source.x + source.width, source.y + source.height / 2);
    const middle = (source.x + source.width + target.x) / 2;
    context.bezierCurveTo(middle, source.y + source.height / 2, middle, target.y + target.height / 2, target.x, target.y + target.height / 2);
    context.stroke();
  }}
  if (showCrossLinks) {{
    context.save();
    context.setLineDash([10, 8]);
    context.strokeStyle = "#c2410c";
    for (const edge of model.crossLinks) {{
      const source = nodeById.get(edge.source_id);
      const target = nodeById.get(edge.target_id);
      if (!source || !target) continue;
      context.beginPath();
      context.moveTo(source.x + source.width / 2, source.y + source.height);
      context.lineTo(target.x + target.width / 2, target.y);
      context.stroke();
    }}
    context.restore();
  }}
  for (const node of model.nodes) {{
    const [fill, text, border] = nodeColor(node);
    context.fillStyle = fill;
    context.strokeStyle = node.id === selectedId ? "#c2410c" : border;
    context.lineWidth = node.id === selectedId ? 4 : 2;
    context.beginPath();
    context.roundRect(node.x, node.y, node.width, node.height, 6);
    context.fill();
    context.stroke();
    context.fillStyle = text;
    context.font = `${{node.isRoot ? 20 : node.isChapter ? 18 : 14}}px "Noto Sans CJK SC", "Noto Sans SC", Arial, sans-serif`;
    context.textBaseline = "middle";
    context.textAlign = "left";
    const lineHeight = node.isRoot ? 24 : 20;
    const firstY = node.y + node.height / 2 - ((node.lines.length - 1) * lineHeight) / 2;
    node.lines.forEach((line, index) => context.fillText(line, node.x + 14, firstY + index * lineHeight));
  }}
}}

function selectNode(nodeId, focus = false) {{
  const node = nodeById.get(nodeId);
  if (!node) return;
  selectedId = nodeId;
  document.getElementById("detail-label").textContent = node.label;
  document.getElementById("detail-status").textContent = node.status;
  document.getElementById("detail-id").textContent = node.id;
  const evidenceList = document.getElementById("detail-evidence");
  evidenceList.replaceChildren(...(model.evidence[node.id] || []).map((value) => {{
    const item = document.createElement("li");
    item.textContent = value;
    return item;
  }}));
  document.querySelectorAll(".tree-node").forEach((button) => button.setAttribute("aria-selected", String(button.dataset.nodeId === nodeId)));
  draw();
  if (focus) document.querySelector(`.tree-node[data-node-id="${{CSS.escape(nodeId)}}"]`)?.focus();
}}

const treeButtons = Array.from(document.querySelectorAll(".tree-node"));
treeButtons.forEach((button, index) => {{
  button.addEventListener("click", () => selectNode(button.dataset.nodeId));
  button.addEventListener("keydown", (event) => {{
    let targetId = null;
    if (event.key === "ArrowDown") targetId = treeButtons[Math.min(index + 1, treeButtons.length - 1)]?.dataset.nodeId;
    if (event.key === "ArrowUp") targetId = treeButtons[Math.max(index - 1, 0)]?.dataset.nodeId;
    if (event.key === "ArrowLeft") targetId = model.parents[button.dataset.nodeId];
    if (event.key === "ArrowRight") targetId = model.children[button.dataset.nodeId]?.[0];
    if (targetId) {{
      event.preventDefault();
      selectNode(targetId, true);
    }}
  }});
}});
document.querySelectorAll(".chapter-link").forEach((button) => button.addEventListener("click", () => selectNode(button.dataset.nodeId, true)));
document.getElementById("cross-links").addEventListener("change", (event) => {{
  showCrossLinks = event.target.checked;
  draw();
}});
canvas.addEventListener("click", (event) => {{
  const rect = canvas.getBoundingClientRect();
  const x = (event.clientX - rect.left) * canvas.width / rect.width;
  const y = (event.clientY - rect.top) * canvas.height / rect.height;
  const hit = model.nodes.find((node) => x >= node.x && x <= node.x + node.width && y >= node.y && y <= node.y + node.height);
  if (hit) selectNode(hit.id, true);
}});
selectNode(model.rootId);
</script>
</body>
</html>
"""
    return document.encode("utf-8")


def _outline_html(
    node_id: str,
    children: dict[str, tuple[str, ...]],
    labels: dict[str, str],
    statuses: dict[str, str],
    depths: dict[str, int],
) -> str:
    button = (
        '<button type="button" class="tree-node" role="treeitem" '
        f'data-node-id="{html.escape(node_id, quote=True)}" '
        f'data-level="{depths[node_id] + 1}" '
        f'aria-level="{depths[node_id] + 1}" '
        f'aria-selected="{"true" if depths[node_id] == 0 else "false"}" '
        f'aria-label="{html.escape(labels[node_id], quote=True)}; '
        f'{html.escape(statuses[node_id], quote=True)}">'
        f"{html.escape(labels[node_id])}</button>"
    )
    child_html = ""
    if children[node_id]:
        child_html = (
            '<ul class="tree-list" role="group">'
            + "".join(
                _outline_html(
                    child_id,
                    children,
                    labels,
                    statuses,
                    depths,
                )
                for child_id in children[node_id]
            )
            + "</ul>"
        )
    return f"<li>{button}{child_html}</li>"


def _render_json(
    graph: CanonicalExplicitGraph,
    projection: DiagnosticProjection,
    bundle: ProjectionMediaBundle,
) -> bytes:
    audit = {
        "graph_decision_log": graph.decision_log,
        "rejected_items": graph.rejected_items,
        "unresolved_items": graph.unresolved_items,
        "concept_decisions": {
            concept.concept_id: concept.decision_history
            for concept in graph.concepts
            if concept.decision_history
        },
        "relation_decisions": {
            relation.relation_id: relation.decision_history
            for relation in graph.relations
            if relation.decision_history
        },
    }
    payload = {
        "schema_version": "1.0.0",
        "semantic_fingerprint": bundle.semantic_fingerprint,
        "canonical_graph": graph,
        "projection": projection,
        "overlay": projection.overlay_state,
        "quality_report": {
            "status": projection.quality_status.value,
            "diagnostics": projection.diagnostics,
        },
        "audit_records": audit,
        "media_contract": bundle,
    }
    return canonical_json_bytes(payload)


def _render_png_tile(
    media: MediaProjectionContract,
    *,
    node_ids: tuple[str, ...],
    tile_index: int,
    tile_count: int,
    font: FontFace,
) -> tuple[bytes, int, int]:
    page = _render_node_page(
        media,
        node_ids=node_ids,
        title=f"Mind map {tile_index}/{tile_count}",
        font=font,
        normal_size=16,
        chapter_size=20,
        root_size=24,
    )
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text(
        "semantic_fingerprint",
        media.semantic_fingerprint,
    )
    metadata.add_text("node_ids", json.dumps(node_ids))
    metadata.add_text("hidden_ids", json.dumps(media.hidden_ids))
    metadata.add_text(
        "overlay_state",
        json.dumps(
            {
                "enabled": media.overlay_enabled,
                "mode": media.overlay_mode.value,
            },
            sort_keys=True,
        ),
    )
    output = BytesIO()
    page.image.save(
        output,
        format="PNG",
        optimize=True,
        pnginfo=metadata,
    )
    return output.getvalue(), page.image.width, page.image.height


def _render_pdf(
    media: MediaProjectionContract,
    *,
    graph: CanonicalExplicitGraph,
    projection: DiagnosticProjection,
    page_plans: tuple[PdfPagePlan, ...],
    font: FontFace,
    fingerprint: str,
) -> bytes:
    pages: list[_StaticPage] = []
    for plan in page_plans:
        if plan.kind == "sources":
            pages.append(
                _render_sources_page(
                    plan,
                    projection=projection,
                    font=font,
                )
            )
        else:
            pages.append(
                _render_node_page(
                    media,
                    node_ids=plan.node_ids,
                    title=plan.title,
                    font=font,
                    normal_size=22,
                    chapter_size=26,
                    root_size=30,
                )
            )
    raster_pdf = BytesIO()
    pages[0].image.save(
        raster_pdf,
        format="PDF",
        save_all=True,
        append_images=[page.image for page in pages[1:]],
        resolution=144.0,
        title="Mind map projection",
        subject=fingerprint,
    )
    reader = PdfReader(BytesIO(raster_pdf.getvalue()))
    writer = PdfWriter()
    writer.append_pages_from_reader(reader)
    writer.add_metadata(
        {
            "/Title": "Mind map projection",
            "/SemanticFingerprint": fingerprint,
            "/RendererVersion": RENDERER_VERSION,
            "/OverlayMode": media.overlay_mode.value,
            "/HiddenNodeCount": str(len(media.hidden_ids)),
        }
    )
    bookmark_by_title: dict[str, object] = {}
    for page_index, plan in enumerate(page_plans):
        parent = (
            bookmark_by_title.get(plan.bookmark_parent_title)
            if plan.bookmark_parent_title
            else None
        )
        bookmark = writer.add_outline_item(
            plan.title,
            page_index,
            parent=parent,
        )
        bookmark_by_title.setdefault(plan.title, bookmark)
        if plan.bookmark_parent_title:
            bookmark_by_title.setdefault(
                plan.bookmark_parent_title,
                bookmark,
            )
        page = pages[page_index]
        pdf_width = float(writer.pages[page_index].mediabox.width)
        pdf_height = float(writer.pages[page_index].mediabox.height)
        scale_x = pdf_width / page.image.width
        scale_y = pdf_height / page.image.height
        for evidence_ref, rect in page.link_rects:
            left, top, right, bottom = rect
            writer.add_uri(
                page_index,
                "urn:zlb:vnext:evidence:"
                + quote(evidence_ref, safe=""),
                (
                    left * scale_x,
                    pdf_height - bottom * scale_y,
                    right * scale_x,
                    pdf_height - top * scale_y,
                ),
            )
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _render_node_page(
    media: MediaProjectionContract,
    *,
    node_ids: tuple[str, ...],
    title: str,
    font: FontFace,
    normal_size: int,
    chapter_size: int,
    root_size: int,
) -> _StaticPage:
    root_id, parent_by_child, _ = presentation_tree(
        media.nodes,
        media.parents,
        media.view_edges,
    )
    node_by_id = {item.node_id: item for item in media.nodes}
    depth_by_id = _parent_depths(root_id, parent_by_child, node_by_id)
    chapter_ids = {
        child_id
        for child_id, parent_id in parent_by_child.items()
        if parent_id == root_id
    }
    regular = ImageFont.truetype(str(font.path), normal_size)
    chapter = ImageFont.truetype(str(font.path), chapter_size)
    root_font = ImageFont.truetype(str(font.path), root_size)
    title_font = ImageFont.truetype(str(font.path), max(root_size, 26))
    meta_font = ImageFont.truetype(
        str(font.path),
        max(12, normal_size - 3),
    )
    width = 1800
    box_width = 680
    cursor_y = 110
    boxes: dict[str, tuple[int, int, int, int]] = {}
    wrapped: dict[str, tuple[str, ...]] = {}
    for node_id in node_ids:
        node = node_by_id[node_id]
        face = (
            root_font
            if node_id == root_id
            else chapter
            if node_id in chapter_ids
            else regular
        )
        lines = _wrap_text(node.label, face, box_width - 40)
        line_height = max(face.getbbox("Ag")[3] + 7, normal_size + 6)
        height = max(66, 30 + line_height * len(lines))
        x = 72 + min(depth_by_id[node_id], 9) * 94
        boxes[node_id] = (x, cursor_y, x + box_width, cursor_y + height)
        wrapped[node_id] = lines
        cursor_y += height + 26
    height = max(900, cursor_y + 54)
    image = Image.new("RGB", (width, height), _BACKGROUND)
    draw = ImageDraw.Draw(image)
    draw.text(
        (72, 34),
        title,
        fill=_TEXT,
        font=title_font,
    )
    included = set(node_ids)
    for child_id, parent_id in parent_by_child.items():
        if child_id not in included or parent_id not in included:
            continue
        parent_box = boxes[parent_id]
        child_box = boxes[child_id]
        start = (parent_box[2], (parent_box[1] + parent_box[3]) // 2)
        end = (child_box[0], (child_box[1] + child_box[3]) // 2)
        middle = (start[0] + end[0]) // 2
        draw.line(
            (start, (middle, start[1]), (middle, end[1]), end),
            fill="#92a3b8",
            width=3,
            joint="curve",
        )
    for cross_link in media.cross_links:
        if (
            cross_link.source_id not in included
            or cross_link.target_id not in included
        ):
            continue
        source_box = boxes[cross_link.source_id]
        target_box = boxes[cross_link.target_id]
        _draw_dashed_line(
            draw,
            (
                (source_box[0] + source_box[2]) // 2,
                source_box[3],
            ),
            (
                (target_box[0] + target_box[2]) // 2,
                target_box[1],
            ),
            fill="#c2410c",
            width=2,
        )
    for node_id in node_ids:
        node = node_by_id[node_id]
        box = boxes[node_id]
        is_root = node_id == root_id
        is_chapter = node_id in chapter_ids
        face = root_font if is_root else chapter if is_chapter else regular
        fill = _ROOT if is_root else "#e8f7f1" if is_chapter else "#ffffff"
        text_color = "#ffffff" if is_root else _TEXT
        border = (
            _ROOT
            if is_root
            else _CHAPTER
            if is_chapter
            else _ACCENTS[node.source_order % len(_ACCENTS)]
        )
        draw.rounded_rectangle(
            box,
            radius=6,
            fill=fill,
            outline=border,
            width=3 if is_root else 2,
        )
        line_height = max(face.getbbox("Ag")[3] + 7, normal_size + 6)
        total = line_height * len(wrapped[node_id])
        text_y = (box[1] + box[3] - total) // 2
        for line in wrapped[node_id]:
            draw.text(
                (box[0] + 20, text_y),
                line,
                fill=text_color,
                font=face,
            )
            text_y += line_height
        if not is_root:
            draw.text(
                (box[2] - 12, box[3] - 8),
                node.status,
                fill=_MUTED,
                font=meta_font,
                anchor="rs",
            )
    return _StaticPage(image=image, node_ids=node_ids)


def _render_sources_page(
    plan: PdfPagePlan,
    *,
    projection: DiagnosticProjection,
    font: FontFace,
) -> _StaticPage:
    width = 1600
    line_height = 38
    diagnostics = tuple(
        f"{item.severity}: {item.code} - {item.message}"
        for item in projection.diagnostics[:4]
    )
    row_count = max(1, len(plan.evidence_ref_ids)) + len(diagnostics)
    height = max(1100, 220 + row_count * line_height)
    image = Image.new("RGB", (width, height), "#ffffff")
    draw = ImageDraw.Draw(image)
    title_font = ImageFont.truetype(str(font.path), 32)
    body_font = ImageFont.truetype(str(font.path), 22)
    meta_font = ImageFont.truetype(str(font.path), 18)
    draw.text((72, 42), plan.title, fill=_TEXT, font=title_font)
    cursor = 112
    for diagnostic in diagnostics:
        for line in _wrap_text(diagnostic, body_font, width - 144):
            draw.text((72, cursor), line, fill="#9a3412", font=body_font)
            cursor += line_height
    if diagnostics:
        cursor += 12
    link_rects: list[tuple[str, tuple[int, int, int, int]]] = []
    if not plan.evidence_ref_ids:
        draw.text(
            (72, cursor),
            "No source links were emitted for this projection.",
            fill=_MUTED,
            font=body_font,
        )
    for index, evidence_ref in enumerate(plan.evidence_ref_ids, start=1):
        label = f"{index}. {evidence_ref}"
        top = cursor
        draw.text((72, cursor), label, fill="#174ea6", font=body_font)
        cursor += line_height
        draw.text(
            (94, cursor - 6),
            "Courseware evidence reference",
            fill=_MUTED,
            font=meta_font,
        )
        link_rects.append(
            (evidence_ref, (68, top - 4, width - 72, cursor + 4))
        )
        cursor += 12
    return _StaticPage(
        image=image,
        node_ids=(),
        link_rects=tuple(link_rects),
    )


def _depths(
    root_id: str,
    children: dict[str, tuple[str, ...]],
) -> dict[str, int]:
    result = {root_id: 0}
    stack = [root_id]
    while stack:
        parent_id = stack.pop()
        for child_id in children[parent_id]:
            result[child_id] = result[parent_id] + 1
            stack.append(child_id)
    return result


def _parent_depths(
    root_id: str,
    parent_by_child: dict[str, str],
    node_by_id: dict[str, MediaNodeIdentity],
) -> dict[str, int]:
    depths = {root_id: 0}
    for node_id in node_by_id:
        if node_id in depths:
            continue
        chain: list[str] = []
        cursor = node_id
        while cursor not in depths:
            chain.append(cursor)
            cursor = parent_by_child[cursor]
        depth = depths[cursor]
        for value in reversed(chain):
            depth += 1
            depths[value] = depth
    return depths


def _wrap_by_units(text: str, units: int) -> tuple[str, ...]:
    normalized = " ".join(text.split())
    if not normalized:
        return ("",)
    lines: list[str] = []
    cursor = ""
    used = 0
    for character in normalized:
        weight = 1 if ord(character) > 127 else 0.55
        if cursor and used + weight > units:
            lines.append(cursor)
            cursor = character
            used = weight
        else:
            cursor += character
            used += weight
    if cursor:
        lines.append(cursor)
    return tuple(lines)


def _draw_dashed_line(
    draw: ImageDraw.ImageDraw,
    start: tuple[int, int],
    end: tuple[int, int],
    *,
    fill: str,
    width: int,
    dash: int = 12,
    gap: int = 8,
) -> None:
    delta_x = end[0] - start[0]
    delta_y = end[1] - start[1]
    distance = max((delta_x**2 + delta_y**2) ** 0.5, 1)
    cursor = 0.0
    while cursor < distance:
        segment_end = min(cursor + dash, distance)
        begin_ratio = cursor / distance
        end_ratio = segment_end / distance
        draw.line(
            (
                (
                    round(start[0] + delta_x * begin_ratio),
                    round(start[1] + delta_y * begin_ratio),
                ),
                (
                    round(start[0] + delta_x * end_ratio),
                    round(start[1] + delta_y * end_ratio),
                ),
            ),
            fill=fill,
            width=width,
        )
        cursor += dash + gap


def _wrap_text(
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
) -> tuple[str, ...]:
    normalized = " ".join(text.split())
    if not normalized:
        return ("",)
    lines: list[str] = []
    current = ""
    for character in normalized:
        candidate = current + character
        if current and font.getlength(candidate) > max_width:
            lines.append(current)
            current = character
        else:
            current = candidate
    if current:
        lines.append(current)
    return tuple(lines)


def _file_record(
    *,
    kind: RenderedFileKind,
    relative_path: str,
    media_type: str,
    data: bytes,
    fingerprint: str,
    node_ids: tuple[str, ...],
    page_or_tile_index: int | None = None,
    logical_page_count: int = 1,
    pixel_width: int | None = None,
    pixel_height: int | None = None,
) -> RenderedMediaFile:
    return RenderedMediaFile(
        kind=kind,
        relative_path=relative_path,
        media_type=media_type,
        payload_digest=_bytes_digest(data),
        byte_size=len(data),
        semantic_fingerprint=fingerprint,
        page_or_tile_index=page_or_tile_index,
        logical_page_count=logical_page_count,
        pixel_width=pixel_width,
        pixel_height=pixel_height,
        node_ids=node_ids,
    )


def _owner_scope(owner_id: str) -> str:
    return hashlib.sha256(
        ("zlb-vnext-render-owner-v1\0" + owner_id).encode("utf-8")
    ).hexdigest()


def _bytes_digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _file_digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return "sha256:" + hasher.hexdigest()


def _write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _fsync_tree(root: Path) -> None:
    directories = sorted(
        (path for path in root.rglob("*") if path.is_dir()),
        key=lambda item: len(item.parts),
        reverse=True,
    )
    for directory in directories:
        _fsync_directory(directory)
    _fsync_directory(root)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
