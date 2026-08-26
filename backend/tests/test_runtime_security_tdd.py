from __future__ import annotations

import asyncio
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from pypdf import PdfWriter

from backend.app.auth import workbench_principal
from backend.app.config import Settings
from backend.app.job_runtime import JobRuntime, monotonic_progress
from backend.app.upload_validation import (
    OLE_COMPOUND_MAGIC,
    UploadValidationError,
    convert_legacy_office,
    validate_upload_path,
)


def settings(root: Path, **updates) -> Settings:
    base = Settings(
        qwen_api_key="",
        qwen_base_url="https://provider.invalid/v1",
        qwen_model="qwen3.8-max-preview",
        qwen_temperature=0.1,
        qwen_secret_source="none",
        qwen_secret_error="",
        workspace_name="test",
        workspace_id="",
        vision_max_pages=24,
        external_engine_token="",
        asset_public_base_url="",
        asset_access_token="",
        mindmap_data_dir=root,
        blackboard_path=root / "blackboard.sqlite3",
    )
    return base.__class__(**{**base.__dict__, **updates})


class JobRuntimeTDDTests(unittest.IsolatedAsyncioTestCase):
    async def test_global_job_limit_serializes_workers(self):
        runtime = JobRuntime(max_concurrent=1)
        first_started = asyncio.Event()
        release_first = asyncio.Event()
        second_started = asyncio.Event()

        async def first() -> None:
            first_started.set()
            await release_first.wait()

        async def second() -> None:
            second_started.set()

        runtime.submit("first", first)
        runtime.submit("second", second)
        await asyncio.wait_for(first_started.wait(), timeout=1)
        await asyncio.sleep(0)
        self.assertFalse(second_started.is_set())

        release_first.set()
        await runtime.wait("first")
        await asyncio.wait_for(second_started.wait(), timeout=1)
        await runtime.wait("second")

    async def test_cancel_awaits_worker_cleanup(self):
        runtime = JobRuntime(max_concurrent=1)
        started = asyncio.Event()
        cleaned = asyncio.Event()

        async def worker() -> None:
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaned.set()

        runtime.submit("task", worker)
        await asyncio.wait_for(started.wait(), timeout=1)
        self.assertTrue(await runtime.cancel("task"))
        self.assertTrue(cleaned.is_set())
        self.assertFalse(runtime.has_task("task"))

    def test_progress_is_monotonic_and_bounded(self):
        self.assertEqual(monotonic_progress(42, 3), 42)
        self.assertEqual(monotonic_progress(42, 88), 88)
        self.assertEqual(monotonic_progress(98, 120), 100)
        self.assertEqual(monotonic_progress(0, -4), 0)


class PublicWorkbenchTDDTests(unittest.TestCase):
    def test_production_uses_configured_public_owner(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            configured = settings(
                Path(temp_dir),
                environment="production",
                workbench_owner_id="legacy-owner",
            )
            principal = workbench_principal(configured)

        self.assertEqual(principal.id, "legacy-owner")

    def test_public_owner_is_stable_without_credentials(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            configured = settings(
                Path(temp_dir),
                environment="production",
                workbench_owner_id="public-workbench",
            )
            first = workbench_principal(configured)
            second = workbench_principal(configured)

        self.assertEqual(first.id, second.id)
        self.assertEqual(first.id, "public-workbench")


class UploadValidationTDDTests(unittest.TestCase):
    def test_legacy_ppt_and_doc_signatures_are_accepted_for_conversion(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ppt = root / "lesson.ppt"
            ppt.write_bytes(OLE_COMPOUND_MAGIC + b"legacy-powerpoint")
            doc = root / "lesson.doc"
            doc.write_bytes(b"{\\rtf1\\ansi legacy word}")

            ppt_inspection = validate_upload_path(
                ppt,
                filename=ppt.name,
                content_type="application/vnd.ms-powerpoint",
                settings=settings(root),
            )
            doc_inspection = validate_upload_path(
                doc,
                filename=doc.name,
                content_type="application/msword",
                settings=settings(root),
            )

        self.assertEqual(ppt_inspection.suffix, ".ppt")
        self.assertEqual(doc_inspection.suffix, ".doc")

    def test_spoofed_legacy_office_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "spoofed.doc"
            source.write_bytes(b"plain text pretending to be word")
            with self.assertRaisesRegex(UploadValidationError, "签名"):
                validate_upload_path(
                    source,
                    filename=source.name,
                    content_type="application/msword",
                    settings=settings(root),
                )

    def test_legacy_office_conversion_uses_isolated_headless_profile(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "lesson.ppt"
            source.write_bytes(OLE_COMPOUND_MAGIC + b"legacy-powerpoint")
            captured: list[str] = []

            def fake_run(args, **_kwargs):
                captured.extend(args)
                source.with_suffix(".pptx").write_bytes(b"converted")
                return subprocess.CompletedProcess(args, 0)

            with (
                patch(
                    "backend.app.upload_validation.shutil.which",
                    return_value="/usr/bin/libreoffice",
                ),
                patch(
                    "backend.app.upload_validation.subprocess.run",
                    side_effect=fake_run,
                ),
            ):
                converted = convert_legacy_office(source)

        self.assertEqual(converted.suffix, ".pptx")
        self.assertIn("--headless", captured)
        self.assertTrue(
            any(arg.startswith("-env:UserInstallation=file://") for arg in captured)
        )

    def test_extension_spoofing_is_rejected_by_magic(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "spoofed.pdf"
            source.write_bytes(b"PK\x03\x04not-a-pdf")
            with self.assertRaisesRegex(UploadValidationError, "签名|格式"):
                validate_upload_path(
                    source,
                    filename=source.name,
                    content_type="application/pdf",
                    settings=settings(root),
                )

    def test_byte_and_page_limits_are_enforced(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            text = root / "large.txt"
            text.write_bytes(b"a" * 33)
            with self.assertRaisesRegex(UploadValidationError, "大小"):
                validate_upload_path(
                    text,
                    filename=text.name,
                    content_type="text/plain",
                    settings=settings(root, max_upload_bytes=32),
                )

            pdf = root / "two-pages.pdf"
            writer = PdfWriter()
            writer.add_blank_page(width=100, height=100)
            writer.add_blank_page(width=100, height=100)
            with pdf.open("wb") as handle:
                writer.write(handle)
            with self.assertRaisesRegex(UploadValidationError, "页"):
                validate_upload_path(
                    pdf,
                    filename=pdf.name,
                    content_type="application/pdf",
                    settings=settings(root, max_document_pages=1),
                )

    def test_zip_bomb_ratio_is_rejected_before_parser(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            pptx = root / "bomb.pptx"
            with zipfile.ZipFile(
                pptx,
                "w",
                compression=zipfile.ZIP_DEFLATED,
            ) as archive:
                archive.writestr("[Content_Types].xml", "<Types />")
                archive.writestr("ppt/presentation.xml", "<presentation />")
                archive.writestr(
                    "ppt/slides/slide1.xml",
                    b"0" * 100_000,
                )
            with self.assertRaisesRegex(
                UploadValidationError,
                "压缩|解压",
            ):
                validate_upload_path(
                    pptx,
                    filename=pptx.name,
                    content_type=(
                        "application/vnd.openxmlformats-officedocument."
                        "presentationml.presentation"
                    ),
                    settings=settings(
                        root,
                        max_zip_compression_ratio=2,
                    ),
                )


if __name__ == "__main__":
    unittest.main()
