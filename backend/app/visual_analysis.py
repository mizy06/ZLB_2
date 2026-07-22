from __future__ import annotations

import asyncio
import base64
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

from .agent_prompts import VISUAL_ANALYZER_PROMPT
from .agents import RoleRuntime
from .architecture_schemas import ContentUnit
from .kimi_provider import ModelProviderError
from .mindmap_engine.schemas import (
    CropRequest,
    RenderResponse,
    VisualAsset,
    VisualRegion,
)
from .mindmap_engine.visuals import crop_regions


class VisualRegionDecision(BaseModel):
    page: int = Field(ge=1)
    bbox: list[float]
    visual_kind: str = "diagram"
    action: str
    ocr_text: str = ""
    summary: str = ""
    knowledge_claims: list[str] = Field(default_factory=list)

    @field_validator("bbox")
    @classmethod
    def validate_bbox(cls, value: list[float]) -> list[float]:
        if len(value) != 4:
            raise ValueError("bbox must contain four values")
        if any(item < 0 or item > 1 for item in value):
            raise ValueError("bbox values must be normalized to 0..1")
        if value[2] <= 0 or value[3] <= 0:
            raise ValueError("bbox width and height must be positive")
        return value

    @field_validator("action")
    @classmethod
    def validate_action(cls, value: str) -> str:
        allowed = {
            "standalone_node",
            "attach_as_media",
            "decompose",
            "ignore_decoration",
        }
        if value not in allowed:
            raise ValueError("unsupported visual action")
        return value


class VisualPageAnalysis(BaseModel):
    regions: list[VisualRegionDecision] = Field(default_factory=list)


def _data_url(path: Path) -> str:
    suffix = path.suffix.lower()
    mime = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(suffix, "image/png")
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


async def analyze_visual_pages(
    *,
    document_id: str,
    rendered: RenderResponse,
    text_units: list[ContentUnit],
    runtime: RoleRuntime,
    data_root: Path,
    max_pages: int,
    public_base_url: str = "",
    asset_token: str = "",
    concurrency: int = 3,
) -> tuple[list[VisualAsset], list[ContentUnit], bool, list[str]]:
    if not rendered.pages:
        return [], [], False, []
    if not runtime.available or not runtime.client:
        return (
            [],
            [],
            False,
            [
                "视觉模型不可用，已保留原生图片、图表和表格元数据。"
            ],
        )

    pages = rendered.pages[: max(max_pages, 0)]
    render_dir = data_root / "assets" / rendered.render_id
    semaphore = asyncio.Semaphore(max(concurrency, 1))
    warnings: list[str] = []

    async def analyze(page):
        source = render_dir / page.filename
        if not source.exists():
            return []
        async with semaphore:
            try:
                payload = await runtime.client.complete_multimodal_json(
                    model=runtime.model,
                    system_prompt=VISUAL_ANALYZER_PROMPT,
                    user_prompt=(
                        f"当前页码或幻灯片号：{page.page}。"
                        "请识别知识性视觉区域。"
                    ),
                    image_data_url=await asyncio.to_thread(_data_url, source),
                    max_tokens=5000,
                )
                analysis = VisualPageAnalysis.model_validate(payload)
                return [
                    item.model_copy(update={"page": page.page})
                    for item in analysis.regions
                ]
            except (ModelProviderError, ValueError) as exc:
                warnings.append(f"第 {page.page} 页视觉分析失败：{exc}")
                return []

    decisions = [
        item
        for page_decisions in await asyncio.gather(*(analyze(page) for page in pages))
        for item in page_decisions
        if item.action != "ignore_decoration"
    ]
    if not decisions:
        return [], [], True, warnings

    visual_regions = [
        VisualRegion(
            page=item.page,
            bbox=item.bbox,
            visual_kind=item.visual_kind,
            ocr_text=item.ocr_text,
            summary=item.summary,
            knowledge_claims=item.knowledge_claims,
        )
        for item in decisions
    ]
    cropped = await asyncio.to_thread(
        crop_regions,
        CropRequest(render_id=rendered.render_id, regions=visual_regions),
        data_root,
        public_base_url,
        asset_token,
    )
    text_by_page: dict[int, list[ContentUnit]] = {}
    for unit in text_units:
        location = unit.slide or unit.page
        if location:
            text_by_page.setdefault(location, []).append(unit)

    assets: list[VisualAsset] = []
    units: list[ContentUnit] = []
    for decision, visual in zip(decisions, cropped, strict=True):
        asset = visual.asset
        nearby = text_by_page.get(decision.page, [])
        assets.append(asset)
        units.append(
            ContentUnit(
                id=f"visual:{asset.asset_id}",
                document_id=document_id,
                kind="visual",
                branch_hint=nearby[0].branch_hint if nearby else None,
                importance=(
                    0.82
                    if decision.action in {"standalone_node", "decompose"}
                    else 0.58
                ),
                status=(
                    "merged"
                    if decision.action == "attach_as_media"
                    else "uncovered"
                ),
                evidence_excerpt=decision.ocr_text or decision.summary,
                page=asset.source_page,
                slide=asset.source_slide,
                bbox=asset.bbox,
                asset_id=asset.asset_id,
                visual_kind=asset.visual_kind,
                visual_action=decision.action,
                ocr_text=decision.ocr_text,
                summary=decision.summary,
                knowledge_claims=decision.knowledge_claims,
                nearby_text_ids=[unit.id for unit in nearby],
                perceptual_hash=asset.sha1,
                knowledge_score=(
                    0.86
                    if decision.action in {"standalone_node", "decompose"}
                    else 0.64
                ),
                decorative_score=0,
            )
        )
    return assets, units, True, warnings
