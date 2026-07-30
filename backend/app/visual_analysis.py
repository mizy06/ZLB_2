from __future__ import annotations

import asyncio
import base64
import math
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

from .agent_prompts import VISUAL_ANALYZER_PROMPT
from .agents import RoleRuntime, _structured_json_call_kwargs
from .architecture_schemas import ContentUnit, ContentUnitStatus
from .model_provider import ModelProviderError, model_call_scope
from .mindmap_engine.schemas import (
    CropRequest,
    RenderResponse,
    RenderedPage,
    VisualAsset,
    VisualRegion,
)
from .mindmap_engine.visuals import (
    crop_regions_best_effort,
    perceptual_hash_distance,
)

VISUAL_DEGRADED_PAGE_BUDGET = "[visual_degraded:page_budget]"
VISUAL_DEGRADED_PARTIAL_PAGE_ANALYSIS = (
    "[visual_degraded:partial_page_analysis]"
)


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
        if not all(math.isfinite(item) for item in value):
            raise ValueError("bbox values must be finite")
        if any(item < 0 or item > 1 for item in value):
            raise ValueError("bbox values must be normalized to 0..1")
        if value[2] <= 0 or value[3] <= 0:
            raise ValueError("bbox width and height must be positive")
        if value[0] + value[2] > 1 or value[1] + value[3] > 1:
            raise ValueError("bbox must fit entirely inside the normalized page")
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


def _select_visual_pages(
    pages: list[RenderedPage],
    max_pages: int,
) -> tuple[list[RenderedPage], list[str]]:
    if not pages:
        return [], []
    if max_pages <= 0:
        return [], [
            f"{VISUAL_DEGRADED_PAGE_BUDGET} "
            "视觉分析页数上限为 0，未调用视觉模型。"
        ]
    if len(pages) <= max_pages:
        return list(pages), []
    if max_pages == 1:
        selected = [pages[0]]
    else:
        last_index = len(pages) - 1
        indices = [
            round(position * last_index / (max_pages - 1))
            for position in range(max_pages)
        ]
        selected = [pages[index] for index in dict.fromkeys(indices)]
    page_labels = "、".join(str(page.page) for page in selected)
    warning = (
        f"{VISUAL_DEGRADED_PAGE_BUDGET} "
        f"文档共 {len(pages)} 页，视觉预算为 {max_pages} 页；"
        f"已按全篇分层分析第 {page_labels} 页，未分析 {len(pages) - len(selected)} 页。"
    )
    return selected, [warning]


def _bbox_iou(first: list[float], second: list[float]) -> float:
    first_left, first_top, first_width, first_height = first
    second_left, second_top, second_width, second_height = second
    intersection_width = max(
        0.0,
        min(first_left + first_width, second_left + second_width)
        - max(first_left, second_left),
    )
    intersection_height = max(
        0.0,
        min(first_top + first_height, second_top + second_height)
        - max(first_top, second_top),
    )
    intersection = intersection_width * intersection_height
    if intersection <= 0:
        return 0
    union = (
        first_width * first_height
        + second_width * second_height
        - intersection
    )
    return intersection / union if union > 0 else 0


def _suppress_overlapping_decisions(
    decisions: list[VisualRegionDecision],
    iou_threshold: float = 0.8,
) -> tuple[list[VisualRegionDecision], int]:
    kept: list[VisualRegionDecision] = []
    suppressed = 0
    for decision in decisions:
        duplicate = any(
            previous.page == decision.page
            and _bbox_iou(previous.bbox, decision.bbox) >= iou_threshold
            for previous in kept
        )
        if duplicate:
            suppressed += 1
        else:
            kept.append(decision)
    return kept, suppressed


def _decision_location(
    rendered: RenderResponse,
    page_number: int,
) -> tuple[int | None, int | None]:
    if Path(rendered.filename).suffix.lower() == ".pptx":
        return None, page_number
    return page_number, None


def _page_asset_id(
    rendered: RenderResponse,
    page_number: int,
) -> str | None:
    return next(
        (
            page.asset_id
            for page in rendered.pages
            if page.page == page_number
        ),
        None,
    )


def _decision_unit_id(
    rendered: RenderResponse,
    decision: VisualRegionDecision,
    decision_index: int,
) -> str:
    return (
        f"visual:decision:{rendered.render_id}:"
        f"{decision.page:04d}:{decision_index:04d}"
    )


def _decision_evidence(decision: VisualRegionDecision) -> str:
    return (
        decision.ocr_text
        or decision.summary
        or "；".join(decision.knowledge_claims)
    )[:240]


def _content_unit_from_decision(
    *,
    document_id: str,
    rendered: RenderResponse,
    decision: VisualRegionDecision,
    decision_index: int,
    nearby: list[ContentUnit],
    status: ContentUnitStatus,
    asset: VisualAsset | None = None,
    asset_id: str | None = None,
    parent_asset_id: str | None = None,
    perceptual_hash: str = "",
) -> ContentUnit:
    source_page, source_slide = _decision_location(rendered, decision.page)
    if asset:
        source_page = asset.source_page
        source_slide = asset.source_slide
    active = status == "uncovered"
    knowledge_bearing = decision.action in {"standalone_node", "decompose"}
    return ContentUnit(
        id=(
            f"visual:{asset.asset_id}"
            if asset
            else _decision_unit_id(rendered, decision, decision_index)
        ),
        document_id=document_id,
        kind="visual",
        branch_hint=nearby[0].branch_hint if nearby else None,
        importance=(
            (0.82 if knowledge_bearing else 0.58)
            if active
            else 0
        ),
        status=status,
        evidence_excerpt=_decision_evidence(decision),
        page=source_page,
        slide=source_slide,
        bbox=asset.bbox if asset else decision.bbox,
        asset_id=asset.asset_id if asset else asset_id,
        visual_kind=asset.visual_kind if asset else decision.visual_kind,
        visual_action=decision.action,
        ocr_text=decision.ocr_text,
        summary=decision.summary,
        knowledge_claims=decision.knowledge_claims,
        nearby_text_ids=[unit.id for unit in nearby],
        perceptual_hash=asset.sha1 if asset else perceptual_hash,
        knowledge_score=(
            (0.86 if knowledge_bearing else 0.64)
            if active
            else 0
        ),
        decorative_score=1 if decision.action == "ignore_decoration" else 0,
        parent_asset_id=parent_asset_id,
    )


def _matching_native_asset(
    decision: VisualRegionDecision,
    cropped_asset: VisualAsset,
    native_assets: list[VisualAsset],
) -> VisualAsset | None:
    if not cropped_asset.sha1.startswith("phash:"):
        return None
    for native in native_assets:
        if not native.sha1.startswith("phash:"):
            continue
        native_location = native.source_slide or native.source_page
        if native_location and native_location != decision.page:
            continue
        if (
            native.bbox
            and _bbox_iou(native.bbox, decision.bbox) < 0.5
        ):
            continue
        if perceptual_hash_distance(cropped_asset.sha1, native.sha1) <= 4:
            return native
    return None


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
    if not runtime.client.supports_multimodal:
        return (
            [],
            [],
            False,
            [
                f"{runtime.model} 不支持图片输入，已保留原生图片、图表和表格元数据。"
            ],
        )

    pages, selection_warnings = _select_visual_pages(rendered.pages, max_pages)
    render_dir = data_root / "assets" / rendered.render_id
    semaphore = asyncio.Semaphore(max(concurrency, 1))
    warnings: list[str] = list(selection_warnings)
    successful_pages = 0
    text_by_page: dict[int, list[ContentUnit]] = {}
    for unit in text_units:
        location = unit.slide or unit.page
        if location:
            text_by_page.setdefault(location, []).append(unit)

    async def analyze(page):
        nonlocal successful_pages
        source = render_dir / page.filename
        if not source.exists():
            warnings.append(f"第 {page.page} 页渲染图片不存在，已跳过视觉分析。")
            return []
        nearby = text_by_page.get(page.page, [])
        nearby_context = "\n".join(
            (unit.evidence_excerpt or unit.text).strip()
            for unit in nearby
            if (unit.evidence_excerpt or unit.text).strip()
        )[:2400]
        context_prompt = (
            f"\n同页文本证据（仅用于消歧，不得据此虚构视觉内容）：\n{nearby_context}"
            if nearby_context
            else ""
        )
        async with semaphore:
            try:
                with model_call_scope(
                    input_unit_ids=tuple(unit.id for unit in nearby)
                ):
                    answer_token_budget = 5000
                    payload = await runtime.client.complete_multimodal_json(
                        model=runtime.model,
                        system_prompt=VISUAL_ANALYZER_PROMPT,
                        user_prompt=(
                            f"当前页码或幻灯片号：{page.page}。"
                            "请识别知识性视觉区域。"
                            f"{context_prompt}"
                        ),
                        image_data_url=await asyncio.to_thread(
                            _data_url,
                            source,
                        ),
                        **_structured_json_call_kwargs(
                            runtime,
                            answer_token_budget,
                        ),
                    )
                analysis = VisualPageAnalysis.model_validate(payload)
                successful_pages += 1
                return [
                    item.model_copy(update={"page": page.page})
                    for item in analysis.regions
                ]
            except (ModelProviderError, ValueError) as exc:
                warnings.append(f"第 {page.page} 页视觉分析失败：{exc}")
                return []

    analyzed_decisions = [
        item
        for page_decisions in await asyncio.gather(*(analyze(page) for page in pages))
        for item in page_decisions
    ]
    analysis_complete = (
        len(pages) == len(rendered.pages)
        and successful_pages == len(pages)
    )
    if successful_pages < len(pages):
        warnings.append(
            f"{VISUAL_DEGRADED_PARTIAL_PAGE_ANALYSIS} "
            f"计划分析 {len(pages)} 页，成功 {successful_pages} 页，"
            f"失败或缺失 {len(pages) - successful_pages} 页。"
        )
    indexed_decisions = list(enumerate(analyzed_decisions, start=1))
    ignored_decisions = [
        (index, item)
        for index, item in indexed_decisions
        if item.action == "ignore_decoration"
    ]
    candidate_decisions = [
        (index, item)
        for index, item in indexed_decisions
        if item.action != "ignore_decoration"
    ]
    kept, suppressed_count = _suppress_overlapping_decisions(
        [item for _, item in candidate_decisions]
    )
    kept_ids = {id(item) for item in kept}
    candidate_decisions = [
        (index, item)
        for index, item in candidate_decisions
        if id(item) in kept_ids
    ]
    if suppressed_count:
        warnings.append(
            f"视觉区域 NMS 已抑制 {suppressed_count} 个高度重叠的重复框。"
        )
    units: list[ContentUnit] = []
    for decision_index, decision in ignored_decisions:
        nearby = text_by_page.get(decision.page, [])
        units.append(
            _content_unit_from_decision(
                document_id=document_id,
                rendered=rendered,
                decision=decision,
                decision_index=decision_index,
                nearby=nearby,
                status="rejected",
                parent_asset_id=_page_asset_id(rendered, decision.page),
            )
        )
    if not candidate_decisions:
        return [], units, analysis_complete, list(dict.fromkeys(warnings))

    visual_regions = [
        VisualRegion(
            page=item.page,
            bbox=item.bbox,
            visual_kind=item.visual_kind,
            ocr_text=item.ocr_text,
            summary=item.summary,
            knowledge_claims=item.knowledge_claims,
        )
        for _, item in candidate_decisions
    ]
    try:
        cropped, crop_warnings = await asyncio.to_thread(
            crop_regions_best_effort,
            CropRequest(render_id=rendered.render_id, regions=visual_regions),
            data_root,
            public_base_url,
            asset_token,
        )
        warnings.extend(crop_warnings)
    except (FileNotFoundError, OSError, ValueError) as exc:
        warnings.append(f"视觉裁剪批次失败：{exc}")
        for decision_index, decision in candidate_decisions:
            nearby = text_by_page.get(decision.page, [])
            units.append(
                _content_unit_from_decision(
                    document_id=document_id,
                    rendered=rendered,
                    decision=decision,
                    decision_index=decision_index,
                    nearby=nearby,
                    status="deferred",
                    parent_asset_id=_page_asset_id(rendered, decision.page),
                )
            )
        return [], units, analysis_complete, list(dict.fromkeys(warnings))

    assets: list[VisualAsset] = []
    seen_assets: list[VisualAsset] = []
    for (decision_index, decision), visual in zip(
        candidate_decisions,
        cropped,
        strict=True,
    ):
        nearby = text_by_page.get(decision.page, [])
        if visual is None:
            units.append(
                _content_unit_from_decision(
                    document_id=document_id,
                    rendered=rendered,
                    decision=decision,
                    decision_index=decision_index,
                    nearby=nearby,
                    status="deferred",
                    parent_asset_id=_page_asset_id(rendered, decision.page),
                )
            )
            continue
        asset = visual.asset
        native_match = _matching_native_asset(
            decision,
            asset,
            rendered.native_visuals,
        )
        if native_match:
            warnings.append(
                f"第 {decision.page} 页区域 {decision.bbox} 与原生视觉资产"
                f" {native_match.asset_id} 感知重复，已归并到原生资产。"
            )
            (render_dir / asset.filename).unlink(missing_ok=True)
            units.append(
                _content_unit_from_decision(
                    document_id=document_id,
                    rendered=rendered,
                    decision=decision,
                    decision_index=decision_index,
                    nearby=nearby,
                    status="uncovered",
                    asset=native_match,
                )
            )
            continue
        duplicate_asset = next(
            (
                previous
                for previous in seen_assets
                if asset.sha1
                and previous.sha1
                and perceptual_hash_distance(
                    asset.sha1,
                    previous.sha1,
                )
                <= 4
            ),
            None,
        )
        if duplicate_asset:
            duplicate_location = (
                duplicate_asset.source_slide
                or duplicate_asset.source_page
            )
            if duplicate_location == decision.page:
                warnings.append(
                    f"第 {decision.page} 页区域 {decision.bbox} 与同页已有视觉资产"
                    "感知重复，已跳过重复副本。"
                )
                (render_dir / asset.filename).unlink(missing_ok=True)
                continue
            warnings.append(
                f"第 {decision.page} 页区域 {decision.bbox} 与已有视觉资产感知重复，"
                f"已复用 {duplicate_asset.asset_id} 并保留出现位置。"
            )
            (render_dir / asset.filename).unlink(missing_ok=True)
            units.append(
                _content_unit_from_decision(
                    document_id=document_id,
                    rendered=rendered,
                    decision=decision,
                    decision_index=decision_index,
                    nearby=nearby,
                    status="rejected",
                    asset_id=duplicate_asset.asset_id,
                    parent_asset_id=duplicate_asset.asset_id,
                    perceptual_hash=duplicate_asset.sha1,
                )
            )
            continue
        if asset.sha1:
            seen_assets.append(asset)
        assets.append(asset)
        units.append(
            _content_unit_from_decision(
                document_id=document_id,
                rendered=rendered,
                decision=decision,
                decision_index=decision_index,
                nearby=nearby,
                status="uncovered",
                asset=asset,
                parent_asset_id=(
                    _page_asset_id(rendered, decision.page)
                    if decision.action == "decompose"
                    else None
                ),
            )
        )
    return assets, units, analysis_complete, list(dict.fromkeys(warnings))
