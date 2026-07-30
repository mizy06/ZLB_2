from __future__ import annotations

import hashlib
import re
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile

import pypdfium2
from pypdf import PdfReader

from backend.vnext.contracts.inventory import RawSourceManifest
from backend.vnext.contracts.source import SourceObservationIR


RAW_INSPECTOR_POLICY_VERSION = "raw-source-manifest-v1"
_PPTX_SLIDE = re.compile(r"^ppt/slides/slide[0-9]+\.xml$")
_PPTX_NOTES = re.compile(r"^ppt/notesSlides/notesSlide[0-9]+\.xml$")
_PRESENTATION_NS = (
    "http://schemas.openxmlformats.org/presentationml/2006/main"
)
_DRAWING_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
_PPTX_SHAPE_TAGS = frozenset(
    {
        f"{{{_PRESENTATION_NS}}}sp",
        f"{{{_PRESENTATION_NS}}}pic",
        f"{{{_PRESENTATION_NS}}}graphicFrame",
        f"{{{_PRESENTATION_NS}}}grpSp",
        f"{{{_PRESENTATION_NS}}}cxnSp",
    }
)


def _source_hash(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return "sha256:" + hasher.hexdigest()


def _outline_count(items) -> int:
    count = 0
    for item in items:
        if isinstance(item, list):
            count += _outline_count(item)
        else:
            count += 1
    return count


def _pdf_counts(path: Path) -> dict[str, int | None]:
    reader = PdfReader(str(path))
    native_pages = len(reader.pages)
    native_outline = _outline_count(reader.outline)
    rendered_pages: int | None
    try:
        rendered_pages = len(pypdfium2.PdfDocument(str(path)))
    except Exception:
        rendered_pages = None
    return {
        "native_page_count": native_pages,
        "rendered_page_count": rendered_pages,
        "native_object_count": None,
        "native_outline_count": native_outline,
        "hidden_page_count": 0,
        "notes_count": 0,
        "alt_text_count": 0,
        "off_slide_object_count": 0,
        "package_entry_count": None,
    }


def _pptx_shape_is_off_slide(
    shape: ElementTree.Element,
    *,
    slide_width: int,
    slide_height: int,
) -> bool:
    transform = next(
        shape.iter(f"{{{_DRAWING_NS}}}xfrm"),
        None,
    )
    if transform is None:
        return False
    offset = transform.find(f"{{{_DRAWING_NS}}}off")
    extent = transform.find(f"{{{_DRAWING_NS}}}ext")
    if offset is None or extent is None:
        return False
    try:
        x = int(offset.attrib["x"])
        y = int(offset.attrib["y"])
        width = int(extent.attrib["cx"])
        height = int(extent.attrib["cy"])
    except (KeyError, ValueError):
        return False
    return (
        x < 0
        or y < 0
        or x + width > slide_width
        or y + height > slide_height
    )


def _pptx_counts(path: Path) -> dict[str, int | None]:
    with ZipFile(path) as package:
        names = tuple(package.namelist())
        slide_names = tuple(name for name in names if _PPTX_SLIDE.match(name))
        notes_names = tuple(name for name in names if _PPTX_NOTES.match(name))
        presentation_root = (
            ElementTree.fromstring(package.read("ppt/presentation.xml"))
            if "ppt/presentation.xml" in names
            else None
        )
        slide_width: int | None = None
        slide_height: int | None = None
        if presentation_root is not None:
            slide_size = presentation_root.find(
                f".//{{{_PRESENTATION_NS}}}sldSz"
            )
            if slide_size is not None:
                try:
                    slide_width = int(slide_size.attrib["cx"])
                    slide_height = int(slide_size.attrib["cy"])
                except (KeyError, ValueError):
                    slide_width = None
                    slide_height = None
        native_objects = 0
        hidden_slide_roots = 0
        alt_text = 0
        off_slide_objects = 0
        for name in slide_names:
            root = ElementTree.fromstring(package.read(name))
            hidden_slide_roots += int(
                root.attrib.get("show", "").casefold()
                in {"0", "false", "off", "no"}
            )
            shapes = tuple(
                element
                for element in root.iter()
                if element.tag in _PPTX_SHAPE_TAGS
            )
            native_objects += len(shapes)
            alt_text += sum(
                1
                for element in root.iter(
                    f"{{{_PRESENTATION_NS}}}cNvPr"
                )
                if any(
                    element.attrib.get(attribute, "").strip()
                    for attribute in ("descr", "title")
                )
            )
            if slide_width is not None and slide_height is not None:
                off_slide_objects += sum(
                    _pptx_shape_is_off_slide(
                        shape,
                        slide_width=slide_width,
                        slide_height=slide_height,
                    )
                    for shape in shapes
                )
        hidden_presentation_ids = (
            sum(
                element.attrib.get("show", "").casefold()
                in {"0", "false", "off", "no"}
                for element in presentation_root.iter(
                    f"{{{_PRESENTATION_NS}}}sldId"
                )
            )
            if presentation_root is not None
            else 0
        )
        notes_count = 0
        for name in notes_names:
            root = ElementTree.fromstring(package.read(name))
            if any(
                (element.text or "").strip()
                for element in root.iter(f"{{{_DRAWING_NS}}}t")
            ):
                notes_count += 1
        return {
            "native_page_count": len(slide_names),
            "rendered_page_count": None,
            "native_object_count": native_objects,
            "native_outline_count": None,
            "hidden_page_count": max(
                hidden_slide_roots,
                hidden_presentation_ids,
            ),
            "notes_count": notes_count,
            "alt_text_count": alt_text,
            "off_slide_object_count": off_slide_objects,
            "package_entry_count": len(names),
        }


def _docx_counts(path: Path) -> dict[str, int | None]:
    with ZipFile(path) as package:
        names = tuple(package.namelist())
        document = package.read("word/document.xml")
        native_objects = (
            document.count(b"<w:p>")
            + document.count(b"<w:tbl>")
            + document.count(b"<w:drawing>")
        )
        alt_text = len(
            re.findall(
                rb"<wp:docPr\b[^>]*(?:descr|title)=\"[^\"]+\"",
                document,
            )
        )
        return {
            "native_page_count": None,
            "rendered_page_count": None,
            "native_object_count": native_objects,
            "native_outline_count": None,
            "hidden_page_count": 0,
            "notes_count": 0,
            "alt_text_count": alt_text,
            "off_slide_object_count": 0,
            "package_entry_count": len(names),
        }


def _parser_off_slide_object_count(source: SourceObservationIR) -> int:
    count = 0
    for page in source.pages:
        for item in page.native_objects:
            bbox = item.bbox
            if bbox is None:
                continue
            if (
                bbox.x < 0
                or bbox.y < 0
                or bbox.x + bbox.width > page.dimensions.width
                or bbox.y + bbox.height > page.dimensions.height
            ):
                count += 1
    return count


def inspect_raw_source(
    path: Path,
    source: SourceObservationIR,
) -> RawSourceManifest:
    suffix = path.suffix.casefold()
    unresolved: list[str] = []
    if suffix == ".pdf":
        native = _pdf_counts(path)
        if native["rendered_page_count"] is None:
            unresolved.append("pdf_render_count_unavailable")
    elif suffix == ".pptx":
        native = _pptx_counts(path)
        unresolved.append("pptx_render_count_unavailable")
    elif suffix == ".docx":
        native = _docx_counts(path)
        unresolved.append("native_pagination_unavailable")
    else:
        native = {
            "native_page_count": None,
            "rendered_page_count": None,
            "native_object_count": None,
            "native_outline_count": None,
            "hidden_page_count": 0,
            "notes_count": 0,
            "alt_text_count": 0,
            "off_slide_object_count": 0,
            "package_entry_count": None,
        }
        unresolved.append("native_pagination_unavailable")

    parser_objects = (
        sum(len(page.native_objects) for page in source.pages)
        if suffix == ".pptx"
        else sum(
            len(page.blocks)
            + len(page.native_objects)
            + sum(
                len(obj.table.cells)
                for obj in page.native_objects
                if obj.table is not None
            )
            for page in source.pages
        )
    )
    mismatches: list[str] = []
    if _source_hash(path) != source.source_hash:
        mismatches.append("source_hash_mismatch")
    native_pages = native["native_page_count"]
    rendered_pages = native["rendered_page_count"]
    if native_pages is not None and native_pages != len(source.pages):
        mismatches.append("native_parser_page_count_mismatch")
    if rendered_pages is not None and rendered_pages != len(source.pages):
        mismatches.append("render_parser_page_count_mismatch")
    if (
        native_pages is not None
        and rendered_pages is not None
        and native_pages != rendered_pages
    ):
        mismatches.append("native_render_page_count_mismatch")
    native_objects = native["native_object_count"]
    if native_objects is not None and native_objects > parser_objects:
        mismatches.append("native_parser_object_count_mismatch")
    native_outline = native["native_outline_count"]
    if native_outline is not None and native_outline > len(source.outline_entries):
        mismatches.append("native_parser_outline_count_mismatch")
    parser_hidden_pages = 0
    parser_notes = 0
    parser_alt_text = 0
    parser_off_slide_objects = _parser_off_slide_object_count(source)
    if int(native["hidden_page_count"] or 0) != parser_hidden_pages:
        mismatches.append("native_parser_hidden_page_state_mismatch")
    if int(native["notes_count"] or 0) != parser_notes:
        mismatches.append("native_parser_notes_count_mismatch")
    if int(native["alt_text_count"] or 0) != parser_alt_text:
        mismatches.append("native_parser_alt_text_count_mismatch")
    if (
        int(native["off_slide_object_count"] or 0)
        != parser_off_slide_objects
    ):
        mismatches.append("native_parser_off_slide_object_count_mismatch")

    return RawSourceManifest(
        source_hash=source.source_hash,
        source_format=suffix.removeprefix(".") or "unknown",
        inspector_policy_version=RAW_INSPECTOR_POLICY_VERSION,
        parser_major=source.parser_manifest.parser_major,
        native_page_count=native_pages,
        rendered_page_count=rendered_pages,
        parser_page_count=len(source.pages),
        native_object_count=native_objects,
        parser_object_count=parser_objects,
        native_outline_count=native_outline,
        parser_outline_count=len(source.outline_entries),
        hidden_page_count=int(native["hidden_page_count"] or 0),
        parser_hidden_page_count=parser_hidden_pages,
        notes_count=int(native["notes_count"] or 0),
        parser_notes_count=parser_notes,
        alt_text_count=int(native["alt_text_count"] or 0),
        parser_alt_text_count=parser_alt_text,
        off_slide_object_count=int(
            native["off_slide_object_count"] or 0
        ),
        parser_off_slide_object_count=parser_off_slide_objects,
        package_entry_count=native["package_entry_count"],
        unresolved_checks=tuple(sorted(set(unresolved))),
        mismatch_codes=tuple(sorted(set(mismatches))),
    )
