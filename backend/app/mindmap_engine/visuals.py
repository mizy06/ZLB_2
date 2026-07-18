from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path
from urllib.parse import quote

from PIL import Image
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

from .schemas import (
    CropRequest,
    RenderResponse,
    RenderedPage,
    VisualAsset,
    VisualUnit,
)


IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".webp"}
RENDER_TYPES = IMAGE_TYPES | {".pdf", ".pptx"}


def _sha1(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _asset_url(
    render_id: str,
    filename: str,
    public_base_url: str,
    asset_token: str,
) -> str:
    path = f"/v1/mindmap/assets/{render_id}/{quote(filename)}"
    url = f"{public_base_url.rstrip('/')}{path}" if public_base_url else path
    if asset_token:
        separator = "&" if "?" in url else "?"
        url = f"{url}{separator}token={quote(asset_token)}"
    return url


def _run_command(command: list[str], timeout: int = 300) -> None:
    executable = Path(command[0])
    if executable.suffix.lower() in {".cmd", ".bat"}:
        command = [os.environ.get("COMSPEC", "cmd.exe"), "/c", *command]
    subprocess.run(
        command,
        check=True,
        timeout=timeout,
        capture_output=True,
        text=True,
    )


def _find_command(*names: str) -> str | None:
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    return None


def _render_pdf(
    pdf_path: Path,
    render_dir: Path,
    public_base_url: str,
    asset_token: str,
    render_id: str,
) -> list[RenderedPage]:
    pdftoppm = _find_command("pdftoppm")
    if not pdftoppm:
        raise RuntimeError("未找到 pdftoppm，无法渲染 PDF 页面。")

    prefix = render_dir / "page"
    _run_command(
        [
            pdftoppm,
            "-png",
            "-r",
            "144",
            str(pdf_path),
            str(prefix),
        ]
    )
    generated = sorted(render_dir.glob("page-*.png"))
    pages: list[RenderedPage] = []
    for index, source in enumerate(generated, start=1):
        filename = f"page_{index:04d}.png"
        target = render_dir / filename
        source.replace(target)
        with Image.open(target) as image:
            width, height = image.size
        pages.append(
            RenderedPage(
                asset_id=f"page_{index:04d}",
                render_id=render_id,
                filename=filename,
                url=_asset_url(
                    render_id,
                    filename,
                    public_base_url,
                    asset_token,
                ),
                page=index,
                width=width,
                height=height,
            )
        )
    if not pages:
        raise RuntimeError("pdftoppm 没有生成页面图片。")
    return pages


def _render_pptx(
    pptx_path: Path,
    render_dir: Path,
    public_base_url: str,
    asset_token: str,
    render_id: str,
) -> list[RenderedPage]:
    soffice = _find_command("soffice", "libreoffice")
    if not soffice:
        raise RuntimeError("未找到 LibreOffice，无法渲染 PPTX 幻灯片。")

    _run_command(
        [
            soffice,
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(render_dir),
            str(pptx_path),
        ]
    )
    pdf_path = render_dir / f"{pptx_path.stem}.pdf"
    if not pdf_path.exists():
        pdf_candidates = list(render_dir.glob("*.pdf"))
        if not pdf_candidates:
            raise RuntimeError("LibreOffice 没有生成 PPTX 对应 PDF。")
        pdf_path = pdf_candidates[0]
    try:
        return _render_pdf(
            pdf_path,
            render_dir,
            public_base_url,
            asset_token,
            render_id,
        )
    finally:
        pdf_path.unlink(missing_ok=True)


def _normalized_bbox(shape, slide_width: int, slide_height: int) -> list[float]:
    return [
        round(shape.left / slide_width, 6),
        round(shape.top / slide_height, 6),
        round(shape.width / slide_width, 6),
        round(shape.height / slide_height, 6),
    ]


def _crop_image(
    source: Path,
    bbox: list[float],
    target: Path,
    padding_ratio: float = 0.005,
) -> tuple[int, int]:
    with Image.open(source) as image:
        width, height = image.size
        x, y, box_width, box_height = bbox
        pad_x = width * padding_ratio
        pad_y = height * padding_ratio
        left = max(int(x * width - pad_x), 0)
        top = max(int(y * height - pad_y), 0)
        right = min(int((x + box_width) * width + pad_x), width)
        bottom = min(int((y + box_height) * height + pad_y), height)
        if right - left < 4 or bottom - top < 4:
            raise ValueError("裁剪区域过小。")
        cropped = image.crop((left, top, right, bottom)).convert("RGB")
        cropped.save(target, format="PNG")
        return cropped.size


def _table_text(shape) -> str:
    rows: list[str] = []
    for row in shape.table.rows:
        values = [cell.text.strip() for cell in row.cells]
        if any(values):
            rows.append(" | ".join(values))
    return "\n".join(rows)


def _chart_text(shape) -> str:
    chart = shape.chart
    parts: list[str] = []
    if chart.has_title and chart.chart_title.has_text_frame:
        title = chart.chart_title.text_frame.text.strip()
        if title:
            parts.append(title)
    series_names = [
        str(series.name)
        for series in chart.series
        if getattr(series, "name", None)
    ]
    if series_names:
        parts.append("系列：" + "、".join(series_names))
    return "\n".join(parts)


def _extract_pptx_visuals(
    pptx_path: Path,
    render_dir: Path,
    pages: list[RenderedPage],
    public_base_url: str,
    asset_token: str,
    render_id: str,
) -> tuple[list[VisualAsset], list[str]]:
    presentation = Presentation(str(pptx_path))
    slide_width = presentation.slide_width
    slide_height = presentation.slide_height
    page_by_number = {
        page.page: render_dir / page.filename
        for page in pages
    }
    assets: list[VisualAsset] = []
    warnings: list[str] = []

    for slide_number, slide in enumerate(presentation.slides, start=1):
        for shape in slide.shapes:
            bbox = _normalized_bbox(shape, slide_width, slide_height)
            shape_id = getattr(shape, "shape_id", len(assets) + 1)
            base_name = f"slide_{slide_number:04d}_shape_{shape_id}"
            ocr_text = ""
            visual_kind: str | None = None
            filename = ""
            status: str = "ready"
            width: int | None = None
            height: int | None = None

            if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                extension = shape.image.ext or "png"
                filename = f"{base_name}.{extension}"
                target = render_dir / filename
                target.write_bytes(shape.image.blob)
                try:
                    with Image.open(target) as image:
                        width, height = image.size
                except Exception:
                    width = height = None
                visual_kind = "picture"
            elif getattr(shape, "has_chart", False):
                visual_kind = "chart"
                ocr_text = _chart_text(shape)
            elif getattr(shape, "has_table", False):
                visual_kind = "table"
                ocr_text = _table_text(shape)
            elif shape.shape_type == MSO_SHAPE_TYPE.GROUP:
                visual_kind = "group_diagram"
            else:
                continue

            if not filename:
                page_path = page_by_number.get(slide_number)
                if page_path and page_path.exists():
                    filename = f"{base_name}.png"
                    target = render_dir / filename
                    try:
                        width, height = _crop_image(page_path, bbox, target)
                    except ValueError:
                        continue
                else:
                    status = "needs_render"
                    warnings.append(
                        f"幻灯片 {slide_number} 的 {visual_kind} 缺少渲染页，已保留坐标元数据。"
                    )

            target_path = render_dir / filename if filename else None
            sha1 = _sha1(target_path) if target_path and target_path.exists() else ""
            asset_id = f"native_{slide_number:04d}_{shape_id}"
            assets.append(
                VisualAsset(
                    asset_id=asset_id,
                    render_id=render_id,
                    filename=filename,
                    url=(
                        _asset_url(
                            render_id,
                            filename,
                            public_base_url,
                            asset_token,
                        )
                        if filename
                        else ""
                    ),
                    source_slide=slide_number,
                    bbox=bbox,
                    width=width,
                    height=height,
                    visual_kind=visual_kind,
                    status=status,
                    ocr_text=ocr_text,
                    sha1=sha1,
                )
            )
    return assets, warnings


def render_document(
    source_path: Path,
    original_filename: str,
    data_root: Path,
    public_base_url: str = "",
    asset_token: str = "",
) -> RenderResponse:
    suffix = source_path.suffix.lower()
    if suffix not in RENDER_TYPES:
        raise ValueError("视觉渲染仅支持 PDF、PPTX、PNG、JPG、JPEG 或 WEBP。")

    render_id = uuid.uuid4().hex[:16]
    render_dir = data_root / "assets" / render_id
    render_dir.mkdir(parents=True, exist_ok=False)
    warnings: list[str] = []
    pages: list[RenderedPage] = []

    if suffix == ".pdf":
        try:
            pages = _render_pdf(
                source_path,
                render_dir,
                public_base_url,
                asset_token,
                render_id,
            )
        except Exception as exc:
            warnings.append(f"PDF 页面渲染失败：{exc}")
    elif suffix == ".pptx":
        try:
            pages = _render_pptx(
                source_path,
                render_dir,
                public_base_url,
                asset_token,
                render_id,
            )
        except Exception as exc:
            warnings.append(f"PPTX 整页渲染不可用：{exc}")
    else:
        filename = f"page_0001{suffix}"
        target = render_dir / filename
        shutil.copy2(source_path, target)
        with Image.open(target) as image:
            width, height = image.size
        pages = [
            RenderedPage(
                asset_id="page_0001",
                render_id=render_id,
                filename=filename,
                url=_asset_url(
                    render_id,
                    filename,
                    public_base_url,
                    asset_token,
                ),
                page=1,
                width=width,
                height=height,
            )
        ]

    native_visuals: list[VisualAsset] = []
    if suffix == ".pptx":
        extracted, extraction_warnings = _extract_pptx_visuals(
            source_path,
            render_dir,
            pages,
            public_base_url,
            asset_token,
            render_id,
        )
        native_visuals.extend(extracted)
        warnings.extend(extraction_warnings)

    response = RenderResponse(
        render_id=render_id,
        filename=original_filename,
        pages=pages,
        native_visuals=native_visuals,
        warnings=list(dict.fromkeys(warnings)),
    )
    manifest = {
        **response.model_dump(mode="json"),
        "source_type": suffix.lstrip("."),
    }
    (render_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return response


def crop_regions(
    request: CropRequest,
    data_root: Path,
    public_base_url: str = "",
    asset_token: str = "",
) -> list[VisualUnit]:
    render_dir = data_root / "assets" / request.render_id
    manifest_path = render_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError("视觉渲染任务不存在。")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    pages = {
        int(page["page"]): render_dir / page["filename"]
        for page in manifest.get("pages", [])
    }
    source_type = manifest.get("source_type", "")

    results: list[VisualUnit] = []
    for index, region in enumerate(request.regions, start=1):
        source = pages.get(region.page)
        if not source or not source.exists():
            raise FileNotFoundError(f"第 {region.page} 页的渲染图片不存在。")
        filename = f"crop_{index:04d}.png"
        target = render_dir / filename
        width, height = _crop_image(source, region.bbox, target)
        asset_id = f"crop_{index:04d}"
        asset = VisualAsset(
            asset_id=asset_id,
            render_id=request.render_id,
            filename=filename,
            url=_asset_url(
                request.render_id,
                filename,
                public_base_url,
                asset_token,
            ),
            source_page=region.page if source_type != "pptx" else None,
            source_slide=region.page if source_type == "pptx" else None,
            bbox=region.bbox,
            width=width,
            height=height,
            visual_kind=region.visual_kind,
            status="ready",
            ocr_text=region.ocr_text,
            sha1=_sha1(target),
        )
        results.append(
            VisualUnit(
                asset=asset,
                summary=region.summary,
                knowledge_claims=region.knowledge_claims,
            )
        )
    return results


def resolve_asset_path(data_root: Path, render_id: str, filename: str) -> Path:
    if not render_id.isalnum():
        raise FileNotFoundError("非法视觉任务 ID。")
    if Path(filename).name != filename:
        raise FileNotFoundError("非法资产文件名。")
    render_dir = (data_root / "assets" / render_id).resolve()
    target = (render_dir / filename).resolve()
    if target.parent != render_dir or not target.is_file():
        raise FileNotFoundError("视觉资产不存在。")
    return target
