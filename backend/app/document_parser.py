from __future__ import annotations

import hashlib
from pathlib import Path

from docx import Document
from pptx import Presentation
from pypdf import PdfReader

from .schemas import ParsedDocument, SourceBlock


TEXT_TYPES = {".txt", ".md", ".markdown"}
SUPPORTED_TYPES = TEXT_TYPES | {".pdf", ".pptx", ".docx"}


def _document_id(path: Path) -> str:
    digest = hashlib.sha1(path.read_bytes()).hexdigest()[:12]
    return f"doc_{digest}"


def _parse_pdf(path: Path) -> list[SourceBlock]:
    reader = PdfReader(str(path))
    blocks: list[SourceBlock] = []
    for page_number, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if text:
            blocks.append(SourceBlock(text=text, page=page_number))
    return blocks


def _parse_pptx(path: Path) -> list[SourceBlock]:
    presentation = Presentation(str(path))
    blocks: list[SourceBlock] = []
    for slide_number, slide in enumerate(presentation.slides, start=1):
        texts: list[str] = []
        title: str | None = None
        if slide.shapes.title and slide.shapes.title.has_text_frame:
            title = slide.shapes.title.text.strip() or None
        for shape in slide.shapes:
            if getattr(shape, "has_text_frame", False):
                text = shape.text.strip()
                if text and text not in texts:
                    texts.append(text)
            if getattr(shape, "has_table", False):
                for row in shape.table.rows:
                    values = [cell.text.strip() for cell in row.cells]
                    if any(values):
                        texts.append(" | ".join(values))
        combined = "\n".join(texts).strip()
        if combined:
            blocks.append(
                SourceBlock(text=combined, slide=slide_number, heading=title)
            )
    return blocks


def _parse_docx(path: Path) -> list[SourceBlock]:
    document = Document(str(path))
    blocks: list[SourceBlock] = []
    current_heading: str | None = None
    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        if not text:
            continue
        if paragraph.style and paragraph.style.name.startswith("Heading"):
            current_heading = text
        blocks.append(SourceBlock(text=text, heading=current_heading))
    for table in document.tables:
        for row in table.rows:
            values = [cell.text.strip() for cell in row.cells]
            if any(values):
                blocks.append(
                    SourceBlock(
                        text=" | ".join(values),
                        heading=current_heading,
                    )
                )
    return blocks


def _parse_text(path: Path) -> list[SourceBlock]:
    text = path.read_text(encoding="utf-8", errors="replace")
    blocks: list[SourceBlock] = []
    current_heading: str | None = None
    for raw_block in text.replace("\r\n", "\n").split("\n\n"):
        block = raw_block.strip()
        if not block:
            continue
        first_line = block.splitlines()[0].strip()
        if first_line.startswith("#"):
            current_heading = first_line.lstrip("#").strip()
        blocks.append(SourceBlock(text=block, heading=current_heading))
    return blocks


def parse_document(path: Path, original_filename: str | None = None) -> ParsedDocument:
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_TYPES:
        raise ValueError(
            f"暂不支持 {suffix or '未知'} 文件，请上传 PDF、PPTX、DOCX、TXT 或 MD。"
        )

    if suffix == ".pdf":
        blocks = _parse_pdf(path)
    elif suffix == ".pptx":
        blocks = _parse_pptx(path)
    elif suffix == ".docx":
        blocks = _parse_docx(path)
    else:
        blocks = _parse_text(path)

    if not blocks:
        raise ValueError("没有从文档中解析出可用文本。扫描版 PDF 需要先接入 OCR。")

    filename = original_filename or path.name
    title = next((block.heading for block in blocks if block.heading), None)
    if not title:
        title = Path(filename).stem

    return ParsedDocument(
        document_id=_document_id(path),
        filename=filename,
        file_type=suffix.lstrip("."),
        title=title,
        blocks=blocks,
    )
