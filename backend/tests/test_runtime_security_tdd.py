from __future__ import annotations

import asyncio
import tempfile
import unittest
import zipfile
from pathlib import Path

from pypdf import PdfWriter

from backend.app.auth import (
    AuthConfigurationError,
    AuthenticationError,
    authenticate_token,
)
from backend.app.config import Settings
from backend.app.job_runtime import JobRuntime, monotonic_progress
from backend.app.upload_validation import (
    UploadValidationError,
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


class AuthenticationTDDTests(unittest.TestCase):
    def test_production_without_secret_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            configured = settings(
                Path(temp_dir),
                environment="production",
                api_access_token="",
            )
            with self.assertRaises(AuthConfigurationError):
                authenticate_token(configured, "")

    def test_production_rejects_wrong_token_and_returns_stable_principal(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            configured = settings(
                Path(temp_dir),
                environment="production",
                api_access_token="correct-token",
            )
            with self.assertRaises(AuthenticationError):
                authenticate_token(configured, "wrong-token")
            first = authenticate_token(configured, "correct-token")
            second = authenticate_token(configured, "correct-token")

        self.assertEqual(first.id, second.id)
        self.assertNotIn("correct-token", first.id)

    def test_development_without_secret_is_local_only_principal(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            configured = settings(
                Path(temp_dir),
                environment="development",
                api_access_token="",
            )
            principal = authenticate_token(configured, "")
        self.assertEqual(principal.id, "local-development")


class UploadValidationTDDTests(unittest.TestCase):
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
