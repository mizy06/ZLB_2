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


def chunk_document(
    document: ParsedDocument,
    max_chars: int = 1800,
    overlap_chars: int = 240,
) -> list[Chunk]:
    groups: list[list[SourceBlock]] = []
    current: list[SourceBlock] = []
    current_chars = 0

    for block in document.blocks:
        expanded = _split_long_text(block.text, max_chars)
        for text in expanded:
            piece = block.model_copy(update={"text": text})
            if current and current_chars + len(text) > max_chars:
                groups.append(current)
                overlap_text = "\n".join(item.text for item in current)[-overlap_chars:]
                current = (
                    [SourceBlock(text=f"[上文衔接]\n{overlap_text}", heading=block.heading)]
                    if overlap_text
                    else []
                )
                current_chars = len(overlap_text)
            current.append(piece)
            current_chars += len(text)
    if current:
        groups.append(current)

    chunks: list[Chunk] = []
    for index, blocks in enumerate(groups):
        text = "\n\n".join(block.text for block in blocks).strip()
        page_start, page_end = _location(blocks, "page")
        slide_start, slide_end = _location(blocks, "slide")
        heading = next((block.heading for block in reversed(blocks) if block.heading), None)
        digest = hashlib.sha1(
            f"{document.document_id}:{index}:{text}".encode("utf-8")
        ).hexdigest()[:10]
        chunks.append(
            Chunk(
                id=f"chunk_{digest}",
                index=index,
                text=text,
                heading=heading,
                page_start=page_start,
                page_end=page_end,
                slide_start=slide_start,
                slide_end=slide_end,
            )
        )
    return chunks
