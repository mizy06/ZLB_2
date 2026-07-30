from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import httpx
from fastapi import FastAPI

import backend.app.mindmap_engine.router as router_module
from backend.app.auth import create_session_value
from backend.app.config import Settings
from backend.app.mindmap_engine.visuals import _asset_url


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
        external_engine_token="",
        asset_public_base_url="",
        asset_access_token="",
        mindmap_data_dir=root,
        blackboard_path=root / "blackboard.sqlite3",
        environment="production",
        api_access_token="api-secret",
    )
    return base.__class__(**{**base.__dict__, **updates})


class AssetUrlSecurityTDDTests(unittest.TestCase):
    def test_persisted_asset_url_never_contains_access_token(self):
        secret = "long-lived/asset secret"
        url = _asset_url(
            "render123",
            "page 1.png",
            "https://mindmap.example.test",
            secret,
        )

        parsed = urlsplit(url)
        self.assertEqual(parsed.path, "/v1/mindmap/assets/render123/page%201.png")
        self.assertEqual(parse_qs(parsed.query), {})
        self.assertNotIn(secret, url)
        self.assertNotIn("token=", url)


class AssetRouteAuthenticationTDDTests(unittest.IsolatedAsyncioTestCase):
    async def _request_asset(
        self,
        configured: Settings,
        *,
        headers: dict[str, str] | None = None,
        cookies: dict[str, str] | None = None,
        query: str = "",
    ) -> httpx.Response:
        render_dir = configured.mindmap_data_dir / "assets" / "render123"
        render_dir.mkdir(parents=True, exist_ok=True)
        (render_dir / "page.png").write_bytes(b"asset-bytes")

        app = FastAPI()
        app.include_router(router_module.router)
        transport = httpx.ASGITransport(app=app)
        with patch.object(router_module, "settings", configured):
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://mindmap.test",
                cookies=cookies,
            ) as client:
                return await client.get(
                    f"/v1/mindmap/assets/render123/page.png{query}",
                    headers=headers,
                )

    async def test_production_without_asset_token_or_session_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            response = await self._request_asset(
                configured_settings(Path(temp_dir)),
            )

        self.assertEqual(response.status_code, 401)

    async def test_production_without_any_asset_auth_configuration_returns_503(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            response = await self._request_asset(
                configured_settings(
                    Path(temp_dir),
                    api_access_token="",
                ),
            )

        self.assertEqual(response.status_code, 503)

    async def test_invalid_api_session_never_grants_asset_access(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            configured = configured_settings(Path(temp_dir))
            response = await self._request_asset(
                configured,
                cookies={
                    configured.session_cookie_name: "forged-session",
                },
            )

        self.assertEqual(response.status_code, 401)

    async def test_valid_same_origin_api_session_can_read_asset(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            configured = configured_settings(Path(temp_dir))
            session_value = create_session_value(configured)
            response = await self._request_asset(
                configured,
                cookies={
                    configured.session_cookie_name: session_value,
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"asset-bytes")

    async def test_asset_token_still_works_in_bearer_header(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            configured = configured_settings(
                Path(temp_dir),
                asset_access_token="asset-secret",
            )
            response = await self._request_asset(
                configured,
                headers={"Authorization": "Bearer asset-secret"},
            )

        self.assertEqual(response.status_code, 200)

    async def test_asset_token_still_works_in_engine_header(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            configured = configured_settings(
                Path(temp_dir),
                asset_access_token="asset-secret",
            )
            response = await self._request_asset(
                configured,
                headers={"X-Engine-Token": "asset-secret"},
            )

        self.assertEqual(response.status_code, 200)

    async def test_query_string_token_is_not_an_authentication_channel(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            configured = configured_settings(
                Path(temp_dir),
                asset_access_token="asset-secret",
            )
            response = await self._request_asset(
                configured,
                query="?token=asset-secret",
            )

        self.assertEqual(response.status_code, 401)
