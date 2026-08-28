from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Literal

from PIL import Image
from pydantic import BaseModel, Field, field_validator, model_validator

from .architecture_schemas import (
    ContentUnit,
    CoverageSummary,
    MindMapNode,
    MindMapQualityReport,
    MindMapResult,
    MindMapTreeEdge,
    ModelSelection,
    RunMode,
)
from .blackboard import SQLiteBlackboard
from .config import settings
from .human_loop import build_human_guidance, human_guidance_text
from .mindmap_engine.schemas import (
    EvidenceRef,
    RenderResponse,
    VisualAsset,
)
from .mindmap_engine.visuals import render_document
from .model_provider import (
    ModelCallContext,
    OpenAICompatibleClient,
    model_call_context,
)
from .qwen_provider import QwenClient
from .schemas import ParsedDocument


PIPELINE_MODE = "single_shot_ppt_vision"
ProgressCallback = Callable[[str, int, str], Awaitable[None]]
RenderFunction = Callable[..., RenderResponse]

SYSTEM_PROMPT = """你是课程 PPT 思维导图生成器。
你会在同一条用户消息中收到整份 PPT 的全部幻灯片图片，图片按 vision_id=slide_0001、
slide_0002 的顺序排列。请只根据这些图片，一次性直接生成最终思维导图树。

硬性要求：
1. 必须综合全部幻灯片，不能只总结开头或结尾。
2. 只输出符合给定 JSON Schema 的 JSON 对象，不要输出 Markdown 或解释。
3. nodes 中必须恰有一个 parent_id 为 null 且 role 为 root 的根节点。
4. 其他节点必须引用 nodes 中存在的 parent_id，整棵树必须连通且无环。
5. 每个节点都要列出真实支撑它的 source_slides，页码从 1 开始。
6. 节点名称应简洁可读，definition 应说明知识含义，不要把幻灯片标题机械复制成目录。
7. 若用户消息包含“人类指导”，仅在不违反来源忠实、证据和树约束的前提下，
   用它调整受众、重点、命名、组织和取舍；它及 previous_graph 都不是课程证据。
8. 这是一次性最终输出，不要提出后续步骤，也不要输出候选节点或候选父边。"""

EXPERIMENT_WARNING = (
    "实验模式：整份 PPT 通过一次多图模型调用直接生成；"
    "未执行分支抽取、独立父边验证或拓扑求解器。"
)


class SingleShotNode(BaseModel):
    id: str = Field(min_length=1, max_length=96)
    name: str = Field(min_length=1, max_length=96)
    role: Literal[
        "root",
        "topic",
        "concept",
        "definition",
        "principle",
        "formula",
        "step",
        "example",
        "warning",
        "visual",
    ]
    definition: str = Field(min_length=1, max_length=800)
    parent_id: str | None
    source_slides: list[int] = Field(min_length=1, max_length=150)
    confidence: float = Field(default=0.8, ge=0, le=1)

    @field_validator("id", "name", "definition")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("source_slides")
    @classmethod
    def normalize_source_slides(cls, value: list[int]) -> list[int]:
        if any(slide < 1 for slide in value):
            raise ValueError("source_slides must contain positive slide numbers")
        return sorted(set(value))


class SingleShotMindMap(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    nodes: list[SingleShotNode] = Field(min_length=1, max_length=160)

    @field_validator("title")
    @classmethod
    def strip_title(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_tree(self) -> "SingleShotMindMap":
        node_by_id = {node.id: node for node in self.nodes}
        if len(node_by_id) != len(self.nodes):
            raise ValueError("node IDs must be unique")
        roots = [node for node in self.nodes if node.parent_id is None]
        if len(roots) != 1 or roots[0].role != "root":
            raise ValueError("mindmap must contain exactly one root node")
        root_id = roots[0].id
        for node in self.nodes:
            if node.id == root_id:
                continue
            if not node.parent_id or node.parent_id not in node_by_id:
                raise ValueError(f"node {node.id} has an unknown parent")
            if node.parent_id == node.id:
                raise ValueError(f"node {node.id} cannot parent itself")
            seen = {node.id}
            cursor = node
            while cursor.parent_id is not None:
                if cursor.parent_id in seen:
                    raise ValueError("mindmap tree contains a cycle")
                seen.add(cursor.parent_id)
                cursor = node_by_id[cursor.parent_id]
            if cursor.id != root_id:
                raise ValueError(f"node {node.id} is disconnected from root")
        return self


def single_shot_ppt_enabled() -> bool:
    return os.getenv("MINDMAP_PIPELINE_MODE", "").strip().casefold() == PIPELINE_MODE


def _bounded_int(
    name: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, min(value, maximum))


def _document_shell(
    file_path: Path,
    filename: str,
    slide_count: int,
) -> ParsedDocument:
    hasher = hashlib.sha256()
    with file_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    digest = hasher.hexdigest()
    return ParsedDocument(
        document_id=f"doc_{digest[:20]}",
        filename=filename,
        file_type="pptx",
        title=Path(filename).stem,
        blocks=[],
        parse_metadata={
            "ppt_slide_count": slide_count,
            "ppt_input_mode": PIPELINE_MODE,
            "ppt_text_extraction_performed": False,
            "model_call_count": 1,
        },
    )


def _page_assets(rendered: RenderResponse) -> list[VisualAsset]:
    return [
        VisualAsset(
            asset_id=page.asset_id,
            render_id=page.render_id,
            filename=page.filename,
            url=page.url,
            source_slide=page.page,
            width=page.width,
            height=page.height,
            visual_kind="full_slide",
            status="ready",
        )
        for page in rendered.pages
    ]


def _prepare_slide_image_files(
    rendered: RenderResponse,
    data_root: Path,
    *,
    env_prefix: str = "MINDMAP_SINGLE_SHOT",
    max_edge: int | None = None,
    jpeg_quality: int | None = None,
) -> list[tuple[str, Path]]:
    default_max_edge = 1280 if env_prefix == "MINDMAP_EDITORIAL" else 1600
    if max_edge is None:
        max_edge = _bounded_int(
            f"{env_prefix}_IMAGE_MAX_EDGE",
            default_max_edge,
            minimum=640,
            maximum=4096,
        )
    else:
        max_edge = max(640, min(int(max_edge), 4096))
    if jpeg_quality is None:
        jpeg_quality = _bounded_int(
            f"{env_prefix}_JPEG_QUALITY",
            82,
            minimum=50,
            maximum=95,
        )
    else:
        jpeg_quality = max(50, min(int(jpeg_quality), 95))

    profile = env_prefix.casefold().replace("mindmap_", "")
    output_dir = (
        data_root
        / "assets"
        / rendered.render_id
        / f"{profile}_{max_edge}_q{jpeg_quality}"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    prepared: list[tuple[str, Path]] = []
    for page in sorted(rendered.pages, key=lambda item: item.page):
        page_path = data_root / "assets" / page.render_id / page.filename
        if not page_path.is_file():
            raise RuntimeError(f"找不到第 {page.page} 张幻灯片渲染图。")
        target = output_dir / f"slide_{page.page:04d}.jpg"
        if not target.is_file():
            with Image.open(page_path) as source:
                image = source.convert("RGB")
                image.thumbnail(
                    (max_edge, max_edge),
                    Image.Resampling.LANCZOS,
                )
                image.save(
                    target,
                    format="JPEG",
                    quality=jpeg_quality,
                    optimize=True,
                )
        prepared.append((f"slide_{page.page:04d}", target))
    return prepared


def _encode_slide_images(
    rendered: RenderResponse,
    data_root: Path,
    *,
    env_prefix: str = "MINDMAP_SINGLE_SHOT",
    max_edge: int | None = None,
) -> list[tuple[str, str]]:
    max_request_mib = _bounded_int(
        f"{env_prefix}_MAX_REQUEST_MIB",
        96,
        minimum=8,
        maximum=512,
    )
    max_request_bytes = max_request_mib * 1024 * 1024
    encoded: list[tuple[str, str]] = []
    payload_bytes = 0
    prepared = _prepare_slide_image_files(
        rendered,
        data_root,
        env_prefix=env_prefix,
        max_edge=max_edge,
    )
    for label, image_path in prepared:
        image_bytes = image_path.read_bytes()
        image_data_url = (
            "data:image/jpeg;base64,"
            + base64.b64encode(image_bytes).decode("ascii")
        )
        payload_bytes += len(image_data_url)
        if payload_bytes > max_request_bytes:
            raise RuntimeError(
                "整份 PPT 的单次视觉请求超过实验上限 "
                f"{max_request_mib} MiB；未丢弃任何幻灯片，也未调用模型。"
            )
        encoded.append((label, image_data_url))
    return encoded


def _content_units(
    document: ParsedDocument,
    rendered: RenderResponse,
    covered_slides: set[int],
) -> list[ContentUnit]:
    return [
        ContentUnit(
            id=f"slide_{page.page:04d}",
            document_id=document.document_id,
            kind="visual",
            importance=1,
            status="covered" if page.page in covered_slides else "uncovered",
            text=f"幻灯片 {page.page}",
            evidence_excerpt=f"整页视觉依据：幻灯片 {page.page}",
            slide=page.page,
            asset_id=page.asset_id,
            visual_kind="full_slide",
            visual_action="decompose",
            summary=f"整页视觉输入 slide_{page.page:04d}",
            knowledge_score=1,
        )
        for page in sorted(rendered.pages, key=lambda item: item.page)
    ]


def _depths(output: SingleShotMindMap) -> dict[str, int]:
    node_by_id = {node.id: node for node in output.nodes}
    depths: dict[str, int] = {}
    for node in output.nodes:
        depth = 0
        cursor = node
        while cursor.parent_id is not None:
            depth += 1
            cursor = node_by_id[cursor.parent_id]
        depths[node.id] = depth
    return depths


def _result_from_output(
    *,
    task_id: str,
    run_id: str,
    mode: RunMode,
    document: ParsedDocument,
    rendered: RenderResponse,
    output: SingleShotMindMap,
    model: str,
    run_manifest: dict,
) -> MindMapResult:
    slide_count = len(rendered.pages)
    invalid_slides = sorted(
        {
            slide
            for node in output.nodes
            for slide in node.source_slides
            if slide > slide_count
        }
    )
    if invalid_slides:
        raise ValueError(
            "模型引用了不存在的幻灯片页码："
            + "、".join(str(slide) for slide in invalid_slides)
        )

    root = next(node for node in output.nodes if node.parent_id is None)
    covered_slides = {
        slide
        for node in output.nodes
        if node.id != root.id
        for slide in node.source_slides
    }
    if len(output.nodes) == 1:
        covered_slides.update(root.source_slides)
    page_by_number = {page.page: page for page in rendered.pages}
    canonical_id = {
        node.id: (
            f"node_{index:04d}_"
            + hashlib.sha1(
                f"{document.document_id}:{node.id}".encode("utf-8")
            ).hexdigest()[:10]
        )
        for index, node in enumerate(output.nodes, start=1)
    }
    depths = _depths(output)

    nodes: list[MindMapNode] = []
    for node in output.nodes:
        resolved_role = (
            "branch_topic" if depths[node.id] == 1 else node.role
        )
        support_unit_ids = [
            f"slide_{slide:04d}" for slide in node.source_slides
        ]
        evidence = [
            EvidenceRef(
                unit_id=f"slide_{slide:04d}",
                excerpt=f"整页视觉依据：幻灯片 {slide}",
                slide=slide,
                asset_id=page_by_number[slide].asset_id,
            )
            for slide in node.source_slides
        ]
        nodes.append(
            MindMapNode(
                id=canonical_id[node.id],
                temp_ids=[node.id],
                name=node.name,
                type=node.role,
                role=resolved_role,
                definition=node.definition,
                aliases=[],
                origin=(
                    "synthesized_root"
                    if node.id == root.id
                    else "explicit"
                ),
                branch_id=None,
                confidence=node.confidence,
                optional=False,
                activation_score=node.confidence,
                activation_cost=round(1 - node.confidence, 4),
                is_root_candidate=node.id == root.id,
                evidence=evidence,
                explicit_evidence_unit_ids=support_unit_ids,
                support_unit_ids=support_unit_ids,
                # Full-slide renders remain evidence and gallery assets. They
                # must not become screenshot backgrounds on mind-map nodes.
                media_asset_ids=[],
                depth=depths[node.id],
                parent_id=(
                    canonical_id[node.parent_id]
                    if node.parent_id is not None
                    else None
                ),
                status="accepted",
                risk_score=0,
            )
        )

    tree_edges = [
        MindMapTreeEdge(
            id=f"edge_{canonical_id[node.parent_id]}_{canonical_id[node.id]}",
            source=canonical_id[node.parent_id],
            target=canonical_id[node.id],
            score=node.confidence,
            provisional=False,
            evidence=next(
                item.evidence
                for item in nodes
                if item.id == canonical_id[node.id]
            ),
            classification="direct_parent",
            verifier_votes=[],
        )
        for node in output.nodes
        if node.parent_id is not None
    ]
    coverage = (
        len(covered_slides) / slide_count
        if slide_count
        else 0
    )
    uncovered = [
        f"slide_{slide:04d}"
        for slide in range(1, slide_count + 1)
        if slide not in covered_slides
    ]
    warnings = [EXPERIMENT_WARNING, *rendered.warnings]
    if uncovered:
        warnings.append(
            "模型最终树未显式引用以下幻灯片："
            + "、".join(item.removeprefix("slide_") for item in uncovered)
        )
    average_edge_score = (
        sum(edge.score for edge in tree_edges) / len(tree_edges)
        if tree_edges
        else 1
    )
    quality = MindMapQualityReport(
        node_count=len(nodes),
        tree_edge_count=len(tree_edges),
        cross_link_count=0,
        root_count=1,
        orphan_count=0,
        conflict_count=0,
        provisional_edge_count=0,
        evidence_coverage=round(coverage, 4),
        topology_valid=True,
        warnings=warnings,
        weighted_content_coverage=round(coverage, 4),
        direct_parent_confidence=round(average_edge_score, 4),
        abstraction_support_rate=1,
        review_item_count=0,
        structural_gate_passed=True,
        publish_gate_passed=False,
        quality_gate_passed=False,
        coverage=CoverageSummary(
            total_units=slide_count,
            covered_units=len(covered_slides),
            weighted_coverage=round(coverage, 4),
            uncovered_unit_ids=uncovered,
            branch_coverage={},
        ),
    )
    document = document.model_copy(update={"title": output.title})
    content_units = _content_units(document, rendered, covered_slides)
    return MindMapResult(
        task_id=task_id,
        run_id=run_id,
        graph_version=0,
        document=document,
        chunks=[],
        content_units=content_units,
        root_id=canonical_id[root.id],
        nodes=nodes,
        tree_edges=tree_edges,
        cross_links=[],
        assets=[*_page_assets(rendered), *rendered.native_visuals],
        quality_report=quality,
        review_items=[],
        decision_records=[],
        mode=mode,
        extraction_mode="qwen",
        model_selection=ModelSelection(
            generator_provider="qwen",
            generator_model=model,
            verifier_provider="none",
            verifier_model=None,
            vision_provider="qwen",
            vision_model=model,
        ),
        degraded_components=["single_shot_no_independent_verifier"],
        warnings=warnings,
        solver_status="SINGLE_SHOT_MODEL_TREE",
        run_manifest=run_manifest,
    )


def _user_prompt(
    filename: str,
    slide_count: int,
    human_guidance: dict | None = None,
) -> str:
    schema = json.dumps(
        SingleShotMindMap.model_json_schema(),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return (
        f"文件名：{filename}\n"
        f"幻灯片总数：{slide_count}\n"
        "后续图片按 vision_id=slide_0001 到最后一页排列。"
        "source_slides 必须使用 vision_id 对应的数字页码。"
        "请直接输出最终思维导图。\n"
        f"JSON Schema：{schema}"
        + human_guidance_text(human_guidance)
    )


async def run_single_shot_ppt_pipeline(
    *,
    task_id: str,
    file_path: Path,
    filename: str,
    model: str,
    provider: str,
    mode: RunMode,
    use_ai: bool,
    progress: ProgressCallback,
    blackboard: SQLiteBlackboard,
    client: OpenAICompatibleClient | None = None,
    render: RenderFunction = render_document,
    user_instruction: str = "",
    previous_result: MindMapResult | None = None,
    completed_graph_asset: dict | None = None,
) -> MindMapResult:
    del model
    if file_path.suffix.lower() != ".pptx":
        raise ValueError("单次视觉实验容器仅支持 PPTX 文件。")
    if provider != "qwen":
        raise ValueError("单次视觉实验仅支持 Qwen 多模态模型。")
    if not use_ai:
        raise ValueError("单次视觉实验必须启用 AI。")

    human_guidance = build_human_guidance(
        user_instruction,
        previous_result,
        completed_graph_asset,
    )
    run_manifest = {
        **(blackboard.load_run_manifest(task_id) or {}),
        "pipeline_mode": PIPELINE_MODE,
        "model_call_budget": 1,
        "hierarchical_generation": False,
        "independent_verification": False,
    }
    run_id = blackboard.start_run(
        run_id=f"run_{uuid.uuid4().hex[:16]}",
        task_id=task_id,
        mode=mode,
        manifest=run_manifest,
    )

    await progress("render", 15, "正在渲染整份 PPT 的全部幻灯片")
    render_dpi = _bounded_int(
        "MINDMAP_SINGLE_SHOT_RENDER_DPI",
        120,
        minimum=96,
        maximum=240,
    )
    rendered = await asyncio.to_thread(
        render,
        file_path,
        filename,
        settings.mindmap_data_dir,
        settings.asset_public_base_url,
        settings.asset_access_token,
        max_pages=None,
        pdf_dpi=render_dpi,
    )
    if not rendered.pages:
        raise RuntimeError("PPTX 没有成功渲染出任何幻灯片。")
    document = _document_shell(file_path, filename, len(rendered.pages))
    blackboard.update_run(
        run_id,
        document_id=document.document_id,
        stage="render",
    )
    blackboard.checkpoint(
        run_id,
        "single_shot_render",
        {
            "document": document,
            "rendered": rendered,
            "render_dpi": render_dpi,
        },
    )

    await progress("encode", 40, "正在打包全部幻灯片为一次视觉请求")
    images = await asyncio.to_thread(
        _encode_slide_images,
        rendered,
        settings.mindmap_data_dir,
    )
    vision_model = (
        os.getenv("MINDMAP_SINGLE_SHOT_MODEL", "").strip()
        or settings.qwen_vision_model
    )
    output_tokens = _bounded_int(
        "MINDMAP_SINGLE_SHOT_MAX_OUTPUT_TOKENS",
        12000,
        minimum=2000,
        maximum=32000,
    )
    thinking_budget = _bounded_int(
        "MINDMAP_SINGLE_SHOT_THINKING_BUDGET",
        4096,
        minimum=0,
        maximum=16000,
    )
    timeout_seconds = _bounded_int(
        "MINDMAP_SINGLE_SHOT_TIMEOUT_SECONDS",
        300,
        minimum=30,
        maximum=900,
    )
    runtime_client = client or QwenClient(settings)

    await progress("single_shot", 55, "正在进行唯一一次整份 PPT 视觉生成")
    with model_call_context(
        ModelCallContext(
            run_id=run_id,
            recorder=blackboard.record_model_call,
            role="single_shot_ppt_vision",
            input_unit_ids=tuple(label for label, _ in images),
            stage="single_shot",
        )
    ):
        payload = await runtime_client.complete_multi_image_json(
            model=vision_model,
            system_prompt=SYSTEM_PROMPT,
            user_prompt=_user_prompt(
                filename,
                len(images),
                human_guidance,
            ),
            images=images,
            max_tokens=output_tokens,
            max_completion_tokens=output_tokens + thinking_budget,
            max_attempts=1,
            thinking_budget=thinking_budget,
            timeout_seconds=timeout_seconds,
        )
    blackboard.checkpoint(run_id, "single_shot_raw_output", payload)
    output = SingleShotMindMap.model_validate(payload)
    blackboard.checkpoint(run_id, "single_shot_output", output)

    await progress("finalize", 90, "正在校验并保存模型直接输出的思维导图")
    result = _result_from_output(
        task_id=task_id,
        run_id=run_id,
        mode=mode,
        document=document,
        rendered=rendered,
        output=output,
        model=vision_model,
        run_manifest=run_manifest,
    )
    blackboard.save_content_units(run_id, result.content_units)
    blackboard.save_node_claims(run_id, result.nodes)
    version = blackboard.save_graph_version(run_id, result)
    result = result.model_copy(update={"graph_version": version})
    blackboard.update_run(
        run_id,
        status="completed",
        stage="complete",
        degraded_components=result.degraded_components,
    )
    await progress("complete", 100, "单次视觉思维导图已生成")
    return result
