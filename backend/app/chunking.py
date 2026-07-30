from __future__ import annotations

import hashlib
import re

from .schemas import Chunk, ParsedDocument, SourceBlock


def _split_long_text(text: str, limit: int) -> list[str]:
    if len(text) <= limit:
        return [text]

    sentences = re.split(r"(?<=[。！？.!?；;])\s*", text)
    parts: list[str] = []
    current = ""
    for sentence in sentences:
        if not sentence:
            continue
        if len(current) + len(sentence) <= limit:
            current += sentence
            continue
        if current:
            parts.append(current.strip())
        if len(sentence) <= limit:
            current = sentence
        else:
            parts.extend(
                sentence[index : index + limit]
                for index in range(0, len(sentence), limit)
            )
            current = ""
    if current:
        parts.append(current.strip())
    return parts


def _location(blocks: list[SourceBlock], field: str) -> tuple[int | None, int | None]:
    values = [getattr(block, field) for block in blocks if getattr(block, field)]
    return (min(values), max(values)) if values else (None, None)


def _boundary_key(block: SourceBlock) -> tuple[int | None, int | None, str | None]:
    return (block.page, block.slide, block.heading)


def chunk_document(
    document: ParsedDocument,
    max_chars: int = 1800,
    overlap_chars: int = 240,
) -> list[Chunk]:
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    overlap_chars = max(0, min(overlap_chars, max_chars - 1))

    groups: list[tuple[list[SourceBlock], str]] = []
    current: list[SourceBlock] = []
    current_chars = 0
    context_before = ""
    boundary: tuple[int | None, int | None, str | None] | None = None

    def flush() -> str:
        nonlocal current, current_chars, context_before
        if not current:
            return ""
        real_text = "\n\n".join(item.text for item in current).strip()
        groups.append((current, context_before))
        overlap_text = real_text[-overlap_chars:] if overlap_chars else ""
        current = []
        current_chars = 0
        context_before = ""
        return overlap_text

    for block in document.blocks:
        block_boundary = _boundary_key(block)
        if current and block_boundary != boundary:
            flush()
        if block_boundary != boundary:
            context_before = ""
            boundary = block_boundary

        expanded = _split_long_text(block.text, max_chars)
        for text in expanded:
            piece = block.model_copy(update={"text": text})
            separator_chars = 2 if current else 0
            if current and current_chars + separator_chars + len(text) > max_chars:
                context_before = flush()
                separator_chars = 0
            current.append(piece)
            current_chars += separator_chars + len(text)
    if current:
        flush()

    chunks: list[Chunk] = []
    for index, (blocks, overlap_context) in enumerate(groups):
        text = "\n\n".join(block.text for block in blocks).strip()
        page_start, page_end = _location(blocks, "page")
        slide_start, slide_end = _location(blocks, "slide")
        heading = next((block.heading for block in blocks if block.heading), None)
        digest = hashlib.sha1(
            f"{document.document_id}:{index}:{text}".encode("utf-8")
        ).hexdigest()[:10]
        chunks.append(
            Chunk(
                id=f"chunk_{digest}",
                index=index,
                text=text,
                context_before=overlap_context,
                heading=heading,
                page_start=page_start,
                page_end=page_end,
                slide_start=slide_start,
                slide_end=slide_end,
            )
        )
    return chunks
