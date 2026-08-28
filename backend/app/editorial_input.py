from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .document_parser import TEXT_TYPES, parse_document
from .mindmap_engine.visuals import IMAGE_TYPES
from .schemas import ParsedDocument, SourceBlock


VISUAL_TYPES = frozenset({".pdf", ".pptx", ".docx", *IMAGE_TYPES})
INPUT_KINDS = Literal["visual", "text"]
INPUT_MODES = Literal["visual", "text", "mixed"]


def classify_input(path: Path) -> INPUT_KINDS:
    suffix = path.suffix.lower()
    if suffix in VISUAL_TYPES:
        return "visual"
    if suffix in TEXT_TYPES:
        return "text"
    raise ValueError(
        f"不支持的 editorial 输入格式：{path.name}。"
        "支持 PDF、PPTX、DOCX、TXT、MD 和 Markdown。"
    )


def classify_inputs(paths: list[Path]) -> INPUT_MODES:
    if not paths:
        raise ValueError("未提供任何 editorial 输入。")
    kinds = {classify_input(path) for path in paths}
    if kinds == {"visual"}:
        return "visual"
    if kinds == {"text"}:
        return "text"
    return "mixed"


@dataclass(frozen=True)
class EditorialSource:
    path: Path
    filename: str
    kind: INPUT_KINDS
    parsed: ParsedDocument | None
    warning: str = ""


@dataclass(frozen=True)
class EditorialInputBundle:
    sources: list[EditorialSource]
    input_mode: INPUT_MODES
    document: ParsedDocument
    document_manifest: list[dict]
    text_context: str
    warnings: list[str]

    @property
    def visual_sources(self) -> list[EditorialSource]:
        return [source for source in self.sources if source.kind == "visual"]

    @property
    def text_sources(self) -> list[EditorialSource]:
        return [source for source in self.sources if source.kind == "text"]

    @property
    def has_text_context(self) -> bool:
        return bool(self.text_context.strip())


def _document_block_count(document: ParsedDocument | None) -> int:
    return len(document.blocks) if document is not None else 0


def _page_count(document: ParsedDocument | None) -> int | None:
    if document is None:
        return None
    metadata = document.parse_metadata
    for key in ("pdf_page_count", "ppt_slide_count"):
        value = metadata.get(key)
        if isinstance(value, int) and value > 0:
            return value
    return None


def _source_boundary(filename: str, text: str) -> str:
    return f"[document: {filename}]\n{text.strip()}\n[/document: {filename}]"


def _combined_document(
    sources: list[EditorialSource],
    *,
    text_blocks: list[SourceBlock],
    document_manifest: list[dict],
) -> ParsedDocument:
    digest = hashlib.sha256(
        "::".join(
            f"{source.filename}:{source.path.stat().st_size}:{source.path.stat().st_mtime_ns}"
            for source in sources
        ).encode("utf-8")
    ).hexdigest()[:16]
    first_title = next(
        (
            source.parsed.title
            for source in sources
            if source.parsed is not None and source.parsed.title
        ),
        Path(sources[0].filename).stem,
    )
    return ParsedDocument(
        document_id=f"editorial_{digest}",
        filename=" & ".join(source.filename for source in sources[:2])
        + (f" 等{len(sources)}份文档" if len(sources) > 2 else ""),
        file_type="bundle",
        title=first_title,
        blocks=text_blocks,
        parse_metadata={
            "multi_document": len(sources) > 1,
            "input_mode": (
                "mixed"
                if len({source.kind for source in sources}) > 1
                else sources[0].kind
            ),
            "documents": document_manifest,
        },
        warnings=[
            source.warning
            for source in sources
            if source.warning
        ],
    )


def build_editorial_input_bundle(
    paths: list[Path],
    filenames: list[str] | None = None,
) -> EditorialInputBundle:
    if not paths:
        raise ValueError("未提供任何 editorial 输入。")
    resolved_filenames = filenames or [path.name for path in paths]
    if len(resolved_filenames) != len(paths):
        raise ValueError("输入路径与原始文件名数量不一致。")

    sources: list[EditorialSource] = []
    warnings: list[str] = []
    text_blocks: list[SourceBlock] = []
    manifest: list[dict] = []
    block_cursor = 0

    for index, (path, filename) in enumerate(
        zip(paths, resolved_filenames, strict=True),
        start=1,
    ):
        kind = classify_input(path)
        parsed: ParsedDocument | None = None
        warning = ""
        try:
            parsed = parse_document(path, filename)
        except Exception as exc:
            warning = (
                f"[document_degraded:parse] {filename} 文本解析失败，"
                f"将继续使用可用视觉页面：{exc}"
            )
            warnings.append(warning)

        block_start = block_cursor + 1
        if parsed is not None:
            for block in parsed.blocks:
                text_blocks.append(
                    SourceBlock(
                        text=block.text,
                        page=block.page,
                        slide=block.slide,
                        heading=(
                            f"[document: {filename}] "
                            f"{block.heading}"
                            if block.heading
                            else f"[document: {filename}]"
                        ),
                    )
                )
            block_cursor += len(parsed.blocks)

        page_count = _page_count(parsed)
        manifest.append(
            {
                "index": index,
                "filename": filename,
                "file_type": path.suffix.lower().lstrip("."),
                "input_kind": kind,
                "document_id": parsed.document_id if parsed else "",
                "page_count": page_count or 0,
                "block_count": _document_block_count(parsed),
                "block_start": block_start if parsed and parsed.blocks else None,
                "block_end": block_cursor if parsed and parsed.blocks else None,
                "text_available": bool(parsed and parsed.blocks),
                "parse_warning": warning,
            }
        )
        sources.append(
            EditorialSource(
                path=path,
                filename=filename,
                kind=kind,
                parsed=parsed,
                warning=warning,
            )
        )

    text_context = "\n\n".join(
        _source_boundary(
            source.filename,
            "\n\n".join(
                block.text
                for block in (source.parsed.blocks if source.parsed else [])
                if block.text.strip()
            ),
        )
        for source in sources
        if source.parsed is not None and source.parsed.blocks
    )
    if not text_context and not any(
        source.kind == "visual" for source in sources
    ):
        raise ValueError("输入文档没有可用文本，且没有可渲染的视觉内容。")

    input_mode = classify_inputs(paths)
    document = _combined_document(
        sources,
        text_blocks=text_blocks,
        document_manifest=manifest,
    )
    return EditorialInputBundle(
        sources=sources,
        input_mode=input_mode,
        document=document,
        document_manifest=manifest,
        text_context=text_context,
        warnings=list(dict.fromkeys(warnings)),
    )
