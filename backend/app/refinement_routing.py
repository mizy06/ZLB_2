from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
from typing import Any, Literal

from PIL import Image
from pydantic import BaseModel, Field, field_validator

from .config import PROJECT_ROOT, settings
from .document_parser import parse_document
from .export_service import render_mindmap_png
from .mindmap_engine.visuals import RENDER_TYPES, render_documents
from .model_provider import OpenAICompatibleClient
from .qwen_provider import QwenClient
from .architecture_schemas import MindMapResult


RefinementRoute = Literal["guidance_only", "new_graph", "merge_graph"]
_MAX_ATTACHMENT_PREVIEW_PAGES = 8
_MAX_ATTACHMENT_TEXT_CHARS = 24_000
_MAX_IMAGE_EDGE = 1280

REFINEMENT_ROUTER_PROMPT = """你是课程思维导图二次输入的路由编辑。

你会看到当前思维导图渲染图、用户本轮文字，以及可能附带的新文件的预览图片或可提取文本。
你的唯一工作是判断本轮应走哪条路线：

1. guidance_only：用户只是在指导如何修改当前图。例如纯文字修改意见、标注当前图的截图、
   配色/结构/措辞要求，或用于解释修改位置的图片。即使有附件，也不能因为“上传了文件”
   就把它当成新课件。
2. new_graph：用户明确要重新生成一张独立的新图，或明确要求只按新资料生成。新一轮不能
   携带旧图 JSON。
3. merge_graph：用户明确希望把当前图与新资料共同整合、扩展或合并为更大的图。只有在用户
   的意图和新资料语义都支持“合并当前产物与新内容”时才选择它。

硬性规则：
- 必须依据用户表达、附件实际内容和当前图之间的语义关系判断；绝不能根据是否上传附件、
  附件数量、文件扩展名、文件名、页数或任何机械特征决定路线。
- 截图、批注图、样式参考图通常是 guidance_only，除非用户和图片内容明确表明它们是待纳入
  的新课程知识。
- merge_graph 不表示强行扩大导图。后续主编会检查新旧资料的真实联系；若没有联系，不应硬加。
- 信息不足或意图模糊时，保守选择 guidance_only。
- 只输出符合 JSON Schema 的对象，不要解释思考过程或输出 Markdown。
"""


class RefinementRoutingDecision(BaseModel):
    route: RefinementRoute
    rationale: str = Field(min_length=2, max_length=800)

    @field_validator("rationale")
    @classmethod
    def normalize_rationale(cls, value: str) -> str:
        return value.strip()


def completed_graph_asset(result: MindMapResult) -> dict[str, Any]:
    """Represent a prior output as a labelled completed asset for merge runs."""

    return {
        "asset_type": "completed_mindmap_json",
        "status": "completed",
        "graph_version": result.graph_version,
        "run_id": result.run_id,
        "graph_json": result.model_dump(mode="json"),
        "merge_policy": (
            "将此资产作为已完成的旧导图产物，用于识别与新资料的真实关系。"
            "不要把它当作新课件的事实来源；若新旧资料不存在真实语义联系，不要强行合并。"
        ),
    }


def _image_data_url(path: Path) -> str:
    with Image.open(path) as source:
        image = source.convert("RGB")
        image.thumbnail(
            (_MAX_IMAGE_EDGE, _MAX_IMAGE_EDGE),
            Image.Resampling.LANCZOS,
        )
        from io import BytesIO

        output = BytesIO()
        image.save(output, format="JPEG", quality=82, optimize=True)
    return (
        "data:image/jpeg;base64,"
        + base64.b64encode(output.getvalue()).decode("ascii")
    )


def _attachment_text_context(
    paths: list[Path],
    filenames: list[str],
) -> str:
    sections: list[str] = []
    remaining = _MAX_ATTACHMENT_TEXT_CHARS
    for path, filename in zip(paths, filenames, strict=True):
        if remaining <= 0:
            break
        try:
            document = parse_document(path, filename)
        except Exception:
            continue
        text = "\n".join(
            block.text.strip()
            for block in document.blocks
            if block.text.strip()
        )
        if not text:
            continue
        excerpt = text[:remaining]
        sections.append(
            f"[attachment: {filename}]\n{excerpt}\n[/attachment: {filename}]"
        )
        remaining -= len(excerpt)
    return "\n\n".join(sections)


def _render_attachment_preview_paths(
    paths: list[Path],
    filenames: list[str],
) -> list[Path]:
    visual_pairs = [
        (path, filename)
        for path, filename in zip(paths, filenames, strict=True)
        if path.suffix.lower() in RENDER_TYPES
    ]
    if not visual_pairs:
        return []
    rendered = render_documents(
        [path for path, _ in visual_pairs],
        [filename for _, filename in visual_pairs],
        settings.mindmap_data_dir,
        settings.asset_public_base_url,
        settings.asset_access_token,
        max_pages=_MAX_ATTACHMENT_PREVIEW_PAGES,
    )
    return [
        settings.mindmap_data_dir
        / "assets"
        / page.render_id
        / page.filename
        for page in rendered.pages[:_MAX_ATTACHMENT_PREVIEW_PAGES]
    ]


async def classify_refinement(
    *,
    current_result: MindMapResult,
    instruction: str,
    attachment_paths: list[Path] | None = None,
    attachment_filenames: list[str] | None = None,
    model: str,
    client: OpenAICompatibleClient | None = None,
) -> RefinementRoutingDecision:
    paths = list(attachment_paths or [])
    filenames = list(attachment_filenames or [path.name for path in paths])
    if len(paths) != len(filenames):
        raise ValueError("二次输入文件路径与文件名数量不一致。")

    current_png, preview_paths, attachment_text = await asyncio.gather(
        asyncio.to_thread(render_mindmap_png, current_result),
        asyncio.to_thread(_render_attachment_preview_paths, paths, filenames),
        asyncio.to_thread(_attachment_text_context, paths, filenames),
    )
    images = [
        (
            "current_mindmap",
            "data:image/png;base64,"
            + base64.b64encode(current_png).decode("ascii"),
        )
    ]
    for index, path in enumerate(preview_paths, start=1):
        images.append(
            (
                f"attachment_preview_{index:02d}",
                await asyncio.to_thread(_image_data_url, path),
            )
        )

    payload = {
        "user_instruction": instruction,
        "attachment_names": filenames,
        "attachment_text_context": attachment_text,
        "output_schema": RefinementRoutingDecision.model_json_schema(),
    }
    runtime_client = client or QwenClient(settings)
    response = await runtime_client.complete_multi_image_json(
        model=model,
        system_prompt=REFINEMENT_ROUTER_PROMPT,
        user_prompt=json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        images=images,
        max_tokens=900,
        max_completion_tokens=1500,
        max_attempts=1,
        thinking_budget=512,
        timeout_seconds=120,
    )
    return RefinementRoutingDecision.model_validate(response)


def materialize_guidance_images(
    *,
    task_id: str,
    graph_version: int,
    current_result: MindMapResult,
    attachment_paths: list[Path],
    attachment_filenames: list[str],
) -> list[Path]:
    """Persist only visual context needed by the direct main-editor patch."""

    graph_path = (
        PROJECT_ROOT
        / "backend"
        / "uploads"
        / f"{task_id}_v{graph_version}_refinement_map.png"
    )
    graph_path.write_bytes(render_mindmap_png(current_result))
    rendered_paths = _render_attachment_preview_paths(
        attachment_paths,
        attachment_filenames,
    )
    return [graph_path, *rendered_paths]
