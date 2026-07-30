from __future__ import annotations

import asyncio
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi import FastAPI
from PIL import Image

import backend.app.mindmap_engine.router as router_module
from backend.app import config as config_module
from backend.app.config import Settings


def configured_settings(root: Path, **updates) -> Settings:
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
        external_engine_token="engine-secret",
        asset_public_base_url="",
        asset_access_token="asset-secret",
        mindmap_data_dir=root,
        blackboard_path=root / "blackboard.sqlite3",
    )
    return base.__class__(**{**base.__dict__, **updates})


def image_bytes(format_name: str = "PNG") -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (8, 6), "white").save(output, format=format_name)
    return output.getvalue()


class EngineVisualUploadTDDTests(unittest.IsolatedAsyncioTestCase):
    async def _request_render(
        self,
        configured: Settings,
        *,
        filename: str,
        content: bytes,
        content_type: str,
        authenticated: bool = True,
    ) -> httpx.Response:
        app = FastAPI()
        app.include_router(router_module.router)
        transport = httpx.ASGITransport(
            app=app,
            raise_app_exceptions=False,
        )
        headers = (
            {"X-Engine-Token": configured.external_engine_token}
            if authenticated
            else {}
        )
        with patch.object(router_module, "settings", configured):
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://engine.test",
            ) as client:
                return await client.post(
                    "/v1/mindmap/visuals/render",
                    files={
                        "file": (
                            filename,
                            content,
                            content_type,
                        )
                    },
                    headers=headers,
                )

    def assert_upload_directory_clean(self, configured: Settings) -> None:
        upload_dir = configured.mindmap_data_dir / "uploads"
        self.assertFalse(
            upload_dir.exists() and any(upload_dir.iterdir()),
            "请求结束后不应保留视觉上传临时文件",
        )

    async def test_oversized_upload_returns_413_before_render_and_cleans_temp(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            configured = configured_settings(
                Path(temp_dir),
                max_upload_bytes=32,
            )
            with patch.object(router_module, "render_document") as render:
                response = await self._request_render(
                    configured,
                    filename="large.png",
                    content=b"\x89PNG\r\n\x1a\n" + b"x" * 64,
                    content_type="image/png",
                )

            self.assertEqual(response.status_code, 413)
            render.assert_not_called()
            self.assert_upload_directory_clean(configured)

    async def test_spoofed_or_corrupt_supported_files_return_422_not_500(self):
        cases = [
            (
                "spoofed.png",
                image_bytes("JPEG"),
                "image/png",
            ),
            (
                "broken.png",
                b"\x89PNG\r\n\x1a\ntruncated",
                "image/png",
            ),
            (
                "broken.jpg",
                b"\xff\xd8\xff\xe0truncated",
                "image/jpeg",
            ),
            (
                "broken.pdf",
                b"%PDF-1.7\ntruncated",
                "application/pdf",
            ),
            (
                "broken.pptx",
                b"PK\x03\x04truncated",
                (
                    "application/vnd.openxmlformats-officedocument."
                    "presentationml.presentation"
                ),
            ),
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            configured = configured_settings(Path(temp_dir))
            with patch.object(router_module, "render_document") as render:
                for filename, content, content_type in cases:
                    with self.subTest(filename=filename):
                        response = await self._request_render(
                            configured,
                            filename=filename,
                            content=content,
                            content_type=content_type,
                        )
                        self.assertEqual(response.status_code, 422)
                        self.assert_upload_directory_clean(configured)

            render.assert_not_called()

    async def test_copy_and_validation_are_offloaded_from_event_loop(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            configured = configured_settings(Path(temp_dir))
            original_to_thread = asyncio.to_thread
            with patch(
                "asyncio.to_thread",
                wraps=original_to_thread,
            ) as to_thread:
                response = await self._request_render(
                    configured,
                    filename="small.png",
                    content=image_bytes(),
                    content_type="image/png",
                )

            self.assertEqual(response.status_code, 200)
            offloaded_names = [
                call.args[0].__name__
                for call in to_thread.await_args_list
                if call.args and hasattr(call.args[0], "__name__")
            ]
            self.assertIn("copy_upload_limited", offloaded_names)
            self.assertIn("validate_upload_path", offloaded_names)
            self.assert_upload_directory_clean(configured)

    async def test_valid_small_image_still_renders(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            configured = configured_settings(Path(temp_dir))
            response = await self._request_render(
                configured,
                filename="small.png",
                content=image_bytes(),
                content_type="image/png",
            )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["filename"], "small.png")
            self.assertEqual(len(payload["pages"]), 1)
            self.assertEqual(payload["pages"][0]["width"], 8)
            self.assertEqual(payload["pages"][0]["height"], 6)
            self.assert_upload_directory_clean(configured)

    async def test_image_pixel_budget_rejects_before_render(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            configured = configured_settings(Path(temp_dir))
            object.__setattr__(configured, "max_image_pixels", 32)
            with patch.object(
                router_module,
                "render_document",
                wraps=router_module.render_document,
            ) as render:
                response = await self._request_render(
                    configured,
                    filename="too-many-pixels.png",
                    content=image_bytes(),
                    content_type="image/png",
                )

            self.assertEqual(response.status_code, 422)
            render.assert_not_called()
            self.assert_upload_directory_clean(configured)

    async def test_engine_token_authentication_is_still_required(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            configured = configured_settings(Path(temp_dir))
            with patch.object(router_module, "render_document") as render:
                response = await self._request_render(
                    configured,
                    filename="small.png",
                    content=image_bytes(),
                    content_type="image/png",
                    authenticated=False,
                )

            self.assertEqual(response.status_code, 401)
            render.assert_not_called()
            self.assert_upload_directory_clean(configured)


class ImagePixelBudgetConfigurationTDDTests(unittest.TestCase):
    def test_image_pixel_budget_is_loaded_from_environment(self):
        with (
            patch.dict(
                os.environ,
                {"MINDMAP_MAX_IMAGE_PIXELS": "123"},
                clear=False,
            ),
            patch.object(
                config_module,
                "_load_qwen_secret",
                return_value=("", "none", ""),
            ),
        ):
            configured = config_module.load_settings()

        self.assertEqual(configured.max_image_pixels, 123)


if __name__ == "__main__":
    unittest.main()
