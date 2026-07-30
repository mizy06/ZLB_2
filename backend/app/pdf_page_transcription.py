from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field, field_validator, model_validator

from .agents import RoleRuntime
from .model_provider import ModelProviderError, model_call_scope
from .mindmap_engine.schemas import RenderResponse, RenderedPage
from .pdf_math_geometry import _candidate_issues
from .schemas import ParsedDocument, SourceBlock


PAGE_TRANSCRIPTION_SCHEMA_VERSION = "page-extraction-v1"
PAGE_TRANSCRIPTION_ROLE = "pdf_page_transcriber"
PAGE_TRANSCRIPTION_TIMEOUT_SECONDS = 120.0
PAGE_TRANSCRIPTION_MAX_OUTPUT_TOKENS = 9000
PDF_TRANSCRIPTION_DEGRADED = "[pdf_transcription_degraded:page_failure]"
_PRIVATE_USE_OR_REPLACEMENT = re.compile(r"[\ue000-\uf8ff\ufffd]")
_MARKDOWN_FENCE = re.compile(r"```")

PDF_PAGE_TRANSCRIPTION_PROMPT = """你是 PDF 单页视觉转录器。只依据当前页面图像转录，不解释、不总结、不推导、不补全看不清的内容。

只输出一个 JSON 对象：
{
  "page": 1,
  "complete": true,
  "confidence": 0.0,
  "blocks": [
    {
      "kind": "heading|paragraph|formula|table|list|caption|other",
      "text": "逐字转录；公式块使用单行 Unicode canonical 形式",
      "latex": "仅公式块填写 LaTeX，其余为空字符串",
      "bbox": [x, y, width, height],
      "confidence": 0.0
    }
  ]
}

规则：
1. bbox 使用 0..1 的归一化页面坐标 [x, y, width, height]，必须完整位于页面内。
2. blocks 按视觉阅读顺序输出；忽略纯页码、模板角标和无知识装饰。
3. 公式必须同时输出 text 与 latex。text 保留负号、上下标、分式、单位和关系符，使用 ^ 表示上标、_ 表示下标。
4. 不得把负指数误写为正指数，不得遗漏公式中的负号、指数、下标、分母、微分项或单位。
5. 无法确认的字符不要猜；将 complete 设为 false，并降低对应 block 和页面 confidence。
6. 不要输出 Markdown 代码块或 JSON 之外的文字。"""

PDF_PAGE_TRANSCRIPTION_PROMPT_SHA256 = hashlib.sha256(
    PDF_PAGE_TRANSCRIPTION_PROMPT.encode("utf-8")
).hexdigest()


class CheckpointStore(Protocol):
    def load_checkpoint(self, run_id: str, stage: str) -> Any | None: ...

    def checkpoint(self, run_id: str, stage: str, payload: Any) -> None: ...


class PageTranscriptionBlock(BaseModel):
    kind: Literal[
        "heading",
        "paragraph",
        "formula",
        "table",
        "list",
        "caption",
        "other",
    ]
    text: str
    latex: str = ""
    bbox: list[float]
    confidence: float = Field(ge=0, le=1)

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("transcription block text must not be empty")
        return text

    @field_validator("latex")
    @classmethod
    def normalize_latex(cls, value: str) -> str:
        return value.strip()

    @field_validator("bbox")
    @classmethod
    def validate_bbox(cls, value: list[float]) -> list[float]:
        if len(value) != 4:
            raise ValueError("bbox must contain four values")
        if any(not isinstance(item, (int, float)) for item in value):
            raise ValueError("bbox values must be numeric")
        x, y, width, height = (float(item) for item in value)
        if x < 0 or y < 0 or width <= 0 or height <= 0:
            raise ValueError("bbox must have non-negative origin and positive size")
        if x + width > 1 + 1e-9 or y + height > 1 + 1e-9:
            raise ValueError("bbox must fit inside the normalized page")
        return [x, y, width, height]

    @model_validator(mode="after")
    def validate_formula_contract(self):
        if self.kind == "formula" and not self.latex:
            raise ValueError("formula blocks require latex")
        if self.kind != "formula" and self.latex:
            raise ValueError("non-formula blocks must not contain latex")
        return self


class PageExtraction(BaseModel):
    page: int = Field(ge=1)
    complete: bool
    confidence: float = Field(ge=0, le=1)
    blocks: list[PageTranscriptionBlock] = Field(default_factory=list)


class PdfPageTranscriptionResult(BaseModel):
    document: ParsedDocument
    extractions: list[PageExtraction] = Field(default_factory=list)
    complete: bool = False
    accepted_pages: list[int] = Field(default_factory=list)
    failed_pages: list[int] = Field(default_factory=list)
    reused_pages: list[int] = Field(default_factory=list)
    called_pages: list[int] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def page_extraction_issues(
    extraction: PageExtraction,
    *,
    expected_page: int,
    min_confidence: float,
) -> tuple[str, ...]:
    issues: list[str] = []
    if extraction.page != expected_page:
        issues.append("page_mismatch")
    if not extraction.complete:
        issues.append("page_marked_incomplete")
    if extraction.confidence < min_confidence:
        issues.append("page_confidence_below_threshold")
    if not extraction.blocks:
        issues.append("page_has_no_blocks")

    for index, block in enumerate(extraction.blocks):
        prefix = f"block_{index}"
        if block.confidence < min_confidence:
            issues.append(f"{prefix}:confidence_below_threshold")
        if _PRIVATE_USE_OR_REPLACEMENT.search(
            f"{block.text}\n{block.latex}"
        ):
            issues.append(f"{prefix}:residual_private_use_glyph")
        if _MARKDOWN_FENCE.search(f"{block.text}\n{block.latex}"):
            issues.append(f"{prefix}:markdown_fence")
        if block.kind != "formula":
            continue
        for formula_issue in _candidate_issues(block.text):
            issues.append(f"{prefix}:{formula_issue}")
        if block.latex.count("{") != block.latex.count("}"):
            issues.append(f"{prefix}:unbalanced_latex_braces")

    return tuple(dict.fromkeys(issues))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _data_url(path: Path) -> str:
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _input_hash(
    *,
    source_sha256: str,
    page: RenderedPage,
    image_sha256: str,
    prompt_version: str,
    provider: str,
    model: str,
) -> str:
    payload = json.dumps(
        {
            "source_sha256": source_sha256,
            "page": page.page,
            "image_sha256": image_sha256,
            "prompt_version": prompt_version,
            "schema_version": PAGE_TRANSCRIPTION_SCHEMA_VERSION,
            "provider": provider,
            "model": model,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _checkpoint_stage(page_number: int) -> str:
    return f"page_transcription:{page_number:04d}"


def _cached_extraction(
    checkpoint: Any,
    *,
    input_hash: str,
    expected_page: int,
    min_confidence: float,
) -> PageExtraction | None:
    if not isinstance(checkpoint, dict):
        return None
    if checkpoint.get("status") != "accepted":
        return None
    if checkpoint.get("input_hash") != input_hash:
        return None
    try:
        extraction = PageExtraction.model_validate(
            checkpoint.get("extraction")
        )
    except ValueError:
        return None
    if page_extraction_issues(
        extraction,
        expected_page=expected_page,
        min_confidence=min_confidence,
    ):
        return None
    return extraction


def _page_source_block(
    extraction: PageExtraction,
    heading: str | None,
) -> tuple[SourceBlock, str | None]:
    ordered = sorted(
        extraction.blocks,
        key=lambda block: (
            round(block.bbox[1], 6),
            round(block.bbox[0], 6),
        ),
    )
    parts: list[str] = []
    current_heading = heading
    for block in ordered:
        if block.kind == "heading":
            current_heading = block.text
        parts.append(block.text)
    return (
        SourceBlock(
            text="\n\n".join(parts),
            page=extraction.page,
            heading=current_heading,
        ),
        current_heading,
    )


async def transcribe_pdf_pages(
    *,
    document: ParsedDocument,
    rendered: RenderResponse,
    runtime: RoleRuntime,
    data_root: Path,
    checkpoint_store: CheckpointStore,
    run_id: str,
    source_sha256: str,
    prompt_version: str,
    render_dpi: int,
    min_confidence: float,
    concurrency: int,
    max_page_attempts: int,
) -> PdfPageTranscriptionResult:
    expected_page_count = int(
        document.parse_metadata.get("pdf_page_count")
        or len(rendered.pages)
    )
    expected_pages = set(range(1, expected_page_count + 1))
    rendered_by_page = {page.page: page for page in rendered.pages}
    missing_render_pages = sorted(expected_pages - rendered_by_page.keys())
    warnings: list[str] = []

    if not runtime.available or not runtime.client:
        reason = runtime.unavailable_reason or "视觉模型不可用"
        warning = (
            f"{PDF_TRANSCRIPTION_DEGRADED} "
            f"单页 PDF 转录未执行：{reason}"
        )
        return PdfPageTranscriptionResult(
            document=document.model_copy(
                update={
                    "blocks": [],
                    "warnings": list(
                        dict.fromkeys([*document.warnings, warning])
                    ),
                    "parse_metadata": {
                        **document.parse_metadata,
                        "pdf_page_transcription": {
                            "schema_version": PAGE_TRANSCRIPTION_SCHEMA_VERSION,
                            "prompt_version": prompt_version,
                            "provider": runtime.provider,
                            "model": runtime.model,
                            "render_id": rendered.render_id,
                            "render_dpi": render_dpi,
                            "complete": False,
                            "accepted_pages": [],
                            "failed_pages": sorted(expected_pages),
                            "reused_pages": [],
                            "called_pages": [],
                            "pages": [],
                        },
                    },
                }
            ),
            failed_pages=sorted(expected_pages),
            warnings=[warning],
        )

    render_dir = data_root / "assets" / rendered.render_id
    semaphore = asyncio.Semaphore(max(int(concurrency), 1))
    page_attempt_limit = max(int(max_page_attempts), 1)

    async def transcribe_one(
        page: RenderedPage,
    ) -> tuple[PageExtraction | None, bool, bool, list[str]]:
        source = render_dir / page.filename
        if not source.is_file():
            return (
                None,
                False,
                False,
                [f"第 {page.page} 页渲染图片不存在。"],
            )
        image_sha256 = await asyncio.to_thread(_sha256_file, source)
        input_hash = _input_hash(
            source_sha256=source_sha256,
            page=page,
            image_sha256=image_sha256,
            prompt_version=prompt_version,
            provider=runtime.provider,
            model=runtime.model,
        )
        stage = _checkpoint_stage(page.page)
        checkpoint = await asyncio.to_thread(
            checkpoint_store.load_checkpoint,
            run_id,
            stage,
        )
        cached = _cached_extraction(
            checkpoint,
            input_hash=input_hash,
            expected_page=page.page,
            min_confidence=min_confidence,
        )
        if cached is not None:
            return cached, True, False, []

        last_issues: list[str] = []
        async with semaphore:
            for attempt in range(1, page_attempt_limit + 1):
                try:
                    with model_call_scope(
                        role=PAGE_TRANSCRIPTION_ROLE,
                        input_unit_ids=(f"page:{page.page}",),
                        stage="page_transcription",
                    ):
                        payload = (
                            await runtime.client.complete_multimodal_json(
                                model=runtime.model,
                                system_prompt=PDF_PAGE_TRANSCRIPTION_PROMPT,
                                user_prompt=(
                                    f"转录第 {page.page} 页。"
                                    f"页面像素尺寸：{page.width}×{page.height}。"
                                    f"这是本页第 {attempt} 次独立尝试。"
                                ),
                                image_data_url=await asyncio.to_thread(
                                    _data_url,
                                    source,
                                ),
                                max_tokens=PAGE_TRANSCRIPTION_MAX_OUTPUT_TOKENS,
                                max_attempts=1,
                                timeout_seconds=(
                                    PAGE_TRANSCRIPTION_TIMEOUT_SECONDS
                                ),
                            )
                        )
                    extraction = PageExtraction.model_validate(payload)
                    issues = page_extraction_issues(
                        extraction,
                        expected_page=page.page,
                        min_confidence=min_confidence,
                    )
                    if issues:
                        last_issues = list(issues)
                        continue
                    await asyncio.to_thread(
                        checkpoint_store.checkpoint,
                        run_id,
                        stage,
                        {
                            "schema_version": (
                                PAGE_TRANSCRIPTION_SCHEMA_VERSION
                            ),
                            "status": "accepted",
                            "input_hash": input_hash,
                            "image_sha256": image_sha256,
                            "provider": runtime.provider,
                            "model": runtime.model,
                            "prompt_version": prompt_version,
                            "attempt": attempt,
                            "extraction": extraction.model_dump(mode="json"),
                        },
                    )
                    return extraction, False, True, []
                except (ModelProviderError, ValueError) as exc:
                    last_issues = [type(exc).__name__]

        await asyncio.to_thread(
            checkpoint_store.checkpoint,
            run_id,
            stage,
            {
                "schema_version": PAGE_TRANSCRIPTION_SCHEMA_VERSION,
                "status": "failed",
                "input_hash": input_hash,
                "image_sha256": image_sha256,
                "provider": runtime.provider,
                "model": runtime.model,
                "prompt_version": prompt_version,
                "attempts": page_attempt_limit,
                "issues": last_issues,
            },
        )
        detail = "、".join(last_issues) or "unknown"
        return (
            None,
            False,
            True,
            [f"第 {page.page} 页单页转录未通过质量门：{detail}"],
        )

    page_results = await asyncio.gather(
        *(
            transcribe_one(rendered_by_page[page_number])
            for page_number in sorted(rendered_by_page)
        )
    )

    extractions: list[PageExtraction] = []
    reused_pages: list[int] = []
    called_pages: list[int] = []
    for page_number, (
        extraction,
        reused,
        called,
        page_warnings,
    ) in zip(sorted(rendered_by_page), page_results):
        warnings.extend(page_warnings)
        if reused:
            reused_pages.append(page_number)
        if called:
            called_pages.append(page_number)
        if extraction is not None:
            extractions.append(extraction)

    accepted_pages = sorted(item.page for item in extractions)
    failed_pages = sorted(
        expected_pages - set(accepted_pages)
    )
    failed_pages = sorted(set(failed_pages) | set(missing_render_pages))
    if missing_render_pages:
        warnings.append(
            "以下页面没有渲染结果，未进入模型输入："
            + "、".join(str(page) for page in missing_render_pages)
        )
    complete = not failed_pages and len(accepted_pages) == expected_page_count
    if not complete:
        warnings.append(
            f"{PDF_TRANSCRIPTION_DEGRADED} "
            f"计划转录 {expected_page_count} 页，成功 {len(accepted_pages)} 页，"
            f"失败或缺失 {len(failed_pages)} 页。"
        )

    source_blocks: list[SourceBlock] = []
    current_heading: str | None = None
    for extraction in sorted(extractions, key=lambda item: item.page):
        block, current_heading = _page_source_block(
            extraction,
            current_heading,
        )
        source_blocks.append(block)

    transcription_metadata = {
        "schema_version": PAGE_TRANSCRIPTION_SCHEMA_VERSION,
        "prompt_version": prompt_version,
        "provider": runtime.provider,
        "model": runtime.model,
        "render_id": rendered.render_id,
        "render_dpi": render_dpi,
        "source_sha256": source_sha256,
        "complete": complete,
        "accepted_pages": accepted_pages,
        "failed_pages": failed_pages,
        "reused_pages": reused_pages,
        "called_pages": called_pages,
        "pages": [
            extraction.model_dump(mode="json")
            for extraction in sorted(
                extractions,
                key=lambda item: item.page,
            )
        ],
    }
    updated_document = document.model_copy(
        update={
            "blocks": source_blocks,
            "warnings": list(
                dict.fromkeys([*document.warnings, *warnings])
            ),
            "parse_metadata": {
                **document.parse_metadata,
                "pdf_page_transcription": transcription_metadata,
            },
        }
    )
    return PdfPageTranscriptionResult(
        document=updated_document,
        extractions=sorted(extractions, key=lambda item: item.page),
        complete=complete,
        accepted_pages=accepted_pages,
        failed_pages=failed_pages,
        reused_pages=reused_pages,
        called_pages=called_pages,
        warnings=list(dict.fromkeys(warnings)),
    )
