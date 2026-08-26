from __future__ import annotations

import hashlib
import mimetypes
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader
from pptx import Presentation

from .config import Settings


class UploadValidationError(ValueError):
    pass


class UploadTooLargeError(UploadValidationError):
    pass


@dataclass(frozen=True)
class UploadInspection:
    suffix: str
    size_bytes: int
    page_count: int | None
    detected_type: str


OOXML_MARKERS = {
    ".pptx": "ppt/presentation.xml",
    ".docx": "word/document.xml",
}
LEGACY_OFFICE_TARGETS = {
    ".ppt": ".pptx",
    ".doc": ".docx",
}
LEGACY_OFFICE_SUFFIXES = frozenset(LEGACY_OFFICE_TARGETS)
OLE_COMPOUND_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
IMAGE_FORMATS = {
    ".png": "PNG",
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".webp": "WEBP",
}
SUPPORTED_UPLOAD_SUFFIXES = {
    ".pdf",
    ".pptx",
    ".ppt",
    ".docx",
    ".doc",
    ".txt",
    ".md",
    ".markdown",
    *IMAGE_FORMATS,
}


def copy_upload_limited(
    source: BinaryIO,
    target: Path,
    limit: int,
) -> tuple[int, str]:
    total = 0
    digest = hashlib.sha256()
    try:
        with target.open("xb") as handle:
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > limit:
                    raise UploadTooLargeError("上传文件大小超过限制。")
                digest.update(chunk)
                handle.write(chunk)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return total, digest.hexdigest()


def _validate_declared_type(
    suffix: str,
    content_type: str,
) -> None:
    if not content_type or content_type == "application/octet-stream":
        return
    expected, _ = mimetypes.guess_type(f"file{suffix}")
    aliases = {
        ".md": {"text/plain", "text/markdown"},
        ".markdown": {"text/plain", "text/markdown"},
        ".txt": {"text/plain"},
        ".pdf": {"application/pdf"},
        ".pptx": {
            "application/vnd.openxmlformats-officedocument."
            "presentationml.presentation"
        },
        ".ppt": {
            "application/vnd.ms-powerpoint",
            "application/mspowerpoint",
            "application/powerpoint",
            "application/x-mspowerpoint",
        },
        ".docx": {
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        },
        ".doc": {
            "application/msword",
            "application/doc",
            "application/vnd.ms-word",
            "application/x-msword",
        },
        ".png": {"image/png"},
        ".jpg": {"image/jpeg", "image/jpg"},
        ".jpeg": {"image/jpeg", "image/jpg"},
        ".webp": {"image/webp"},
    }
    accepted = aliases.get(suffix, set())
    if expected:
        accepted.add(expected)
    if accepted and content_type.split(";", 1)[0].strip() not in accepted:
        raise UploadValidationError("文件声明类型与扩展名不一致。")


def _inspect_zip(
    path: Path,
    suffix: str,
    config: Settings,
) -> int | None:
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            names = {info.filename for info in infos}
            if "[Content_Types].xml" not in names:
                raise UploadValidationError("OOXML 文件缺少格式签名。")
            marker = OOXML_MARKERS[suffix]
            if marker not in names:
                raise UploadValidationError("文件内容与扩展格式不一致。")
            total_uncompressed = sum(info.file_size for info in infos)
            total_compressed = sum(info.compress_size for info in infos)
            if total_uncompressed > config.max_zip_uncompressed_bytes:
                raise UploadValidationError("压缩文件解压后大小超过限制。")
            ratio = total_uncompressed / max(total_compressed, 1)
            if ratio > config.max_zip_compression_ratio:
                raise UploadValidationError("压缩文件的解压比例异常。")
            if suffix == ".pptx":
                slide_names = [
                    name
                    for name in names
                    if name.startswith("ppt/slides/slide")
                    and name.endswith(".xml")
                    and "/_rels/" not in name
                ]
                return len(slide_names)
            return None
    except zipfile.BadZipFile as exc:
        raise UploadValidationError("OOXML 文件格式损坏。") from exc


def _inspect_image(
    path: Path,
    suffix: str,
    max_pixels: int,
) -> None:
    try:
        with Image.open(path) as image:
            detected_format = (image.format or "").upper()
            width, height = image.size
            if width * height > max_pixels:
                raise UploadValidationError("图片像素总量超过限制。")
            image.verify()
    except UploadValidationError:
        raise
    except (
        Image.DecompressionBombError,
        OSError,
        SyntaxError,
        UnidentifiedImageError,
        ValueError,
    ) as exc:
        raise UploadValidationError("图片文件格式损坏或无法读取。") from exc
    if detected_format != IMAGE_FORMATS[suffix]:
        raise UploadValidationError("图片内容与扩展格式不一致。")
    if width <= 0 or height <= 0:
        raise UploadValidationError("图片尺寸无效。")


def validate_upload_path(
    path: Path,
    *,
    filename: str,
    content_type: str,
    settings: Settings,
) -> UploadInspection:
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_UPLOAD_SUFFIXES:
        raise UploadValidationError("不支持的文件格式。")
    size = path.stat().st_size
    if size <= 0:
        raise UploadValidationError("上传文件为空。")
    if size > settings.max_upload_bytes:
        raise UploadTooLargeError("上传文件大小超过限制。")
    _validate_declared_type(suffix, content_type)

    with path.open("rb") as handle:
        header = handle.read(8)
    page_count: int | None = None
    if suffix == ".pdf":
        if not header.startswith(b"%PDF-"):
            raise UploadValidationError("PDF 文件签名与扩展名不一致。")
        try:
            page_count = len(PdfReader(path).pages)
        except Exception as exc:
            raise UploadValidationError("PDF 文件格式损坏或无法读取。") from exc
    elif suffix in OOXML_MARKERS:
        if not header.startswith(b"PK"):
            raise UploadValidationError("OOXML 文件签名与扩展名不一致。")
        page_count = _inspect_zip(path, suffix, settings)
        if suffix == ".pptx":
            try:
                page_count = len(Presentation(path).slides)
            except Exception as exc:
                raise UploadValidationError(
                    "PPTX 文件格式损坏或无法读取。"
                ) from exc
    elif suffix in LEGACY_OFFICE_SUFFIXES:
        is_ole = header.startswith(OLE_COMPOUND_MAGIC)
        is_rtf_doc = suffix == ".doc" and header.lstrip().startswith(b"{\\rtf")
        if not is_ole and not is_rtf_doc:
            raise UploadValidationError("旧版 Office 文件签名与扩展名不一致。")
    elif suffix in IMAGE_FORMATS:
        _inspect_image(path, suffix, settings.max_image_pixels)
    else:
        content = path.read_bytes()
        if b"\x00" in content:
            raise UploadValidationError("文本文件包含二进制内容。")
        try:
            content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise UploadValidationError("文本文件必须使用 UTF-8 编码。") from exc

    if (
        page_count is not None
        and page_count > settings.max_document_pages
    ):
        raise UploadValidationError(
            f"文档共 {page_count} 页/幻灯片，超过 "
            f"{settings.max_document_pages} 页限制。"
        )
    return UploadInspection(
        suffix=suffix,
        size_bytes=size,
        page_count=page_count,
        detected_type=suffix[1:],
    )


def convert_legacy_office(
    path: Path,
    *,
    timeout_seconds: float = 120,
) -> Path:
    suffix = path.suffix.lower()
    target_suffix = LEGACY_OFFICE_TARGETS.get(suffix)
    if target_suffix is None:
        return path

    soffice = shutil.which("libreoffice") or shutil.which("soffice")
    if not soffice:
        raise UploadValidationError("服务缺少旧版 Office 文件转换组件。")

    target = path.with_suffix(target_suffix)
    target.unlink(missing_ok=True)
    profile_dir = Path(tempfile.mkdtemp(prefix="zlb-office-", dir="/tmp"))
    try:
        try:
            completed = subprocess.run(
                [
                    soffice,
                    f"-env:UserInstallation={profile_dir.as_uri()}",
                    "--headless",
                    "--nologo",
                    "--nodefault",
                    "--nofirststartwizard",
                    "--nolockcheck",
                    "--convert-to",
                    target_suffix.lstrip("."),
                    "--outdir",
                    str(path.parent),
                    str(path),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise UploadValidationError("旧版 Office 文件转换超时。") from exc
        except OSError as exc:
            raise UploadValidationError("旧版 Office 文件转换组件启动失败。") from exc
    finally:
        shutil.rmtree(profile_dir, ignore_errors=True)

    if completed.returncode != 0 or not target.is_file() or target.stat().st_size <= 0:
        target.unlink(missing_ok=True)
        raise UploadValidationError("旧版 Office 文件转换失败或文件已损坏。")
    return target
