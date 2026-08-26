from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app.config import (
    DEFAULT_QWEN_MODEL,
    DEFAULT_QWEN_VISION_MODEL,
    Settings,
    _load_qwen_secret,
    _parse_env_text,
    load_settings,
    qwen_model_supports_vision,
)
from backend.app.cplus_pipeline import build_role_runtimes
from backend.app.qwen_provider import QwenClient


def settings(api_key: str = "qwen-test-key") -> Settings:
    return Settings(
        qwen_api_key=api_key,
        qwen_base_url=(
            "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
        ),
        qwen_model="qwen3.8-max-preview",
        qwen_temperature=0.1,
        qwen_secret_source="test",
        qwen_secret_error="",
        workspace_name="test",
        workspace_id="",
        vision_max_pages=24,
        external_engine_token="",
        asset_public_base_url="",
        asset_access_token="",
        mindmap_data_dir=Path("."),
        blackboard_path=Path("blackboard.sqlite3"),
    )


class QwenConfigTests(unittest.IsolatedAsyncioTestCase):
    def test_parse_env_text_accepts_export_and_quotes(self):
        values = _parse_env_text(
            "# encrypted payload\nexport QWEN_API_KEY='secret-value'\n"
        )
        self.assertEqual(values["QWEN_API_KEY"], "secret-value")

    def test_qwen_age_decryption_sets_process_environment(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            age = root / "age"
            identity = root / "identity.txt"
            ciphertext = root / "qwen.age"
            for path in (age, identity, ciphertext):
                path.write_bytes(b"placeholder")

            completed = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=b"QWEN_API_KEY=decrypted-qwen-key\n",
                stderr=b"",
            )
            environment = {
                "QWEN_API_KEY": "",
                "AGE_EXECUTABLE": str(age),
                "QWEN_AGE_IDENTITY_FILE": str(identity),
                "QWEN_SECRETS_FILE": str(ciphertext),
            }
            with (
                patch.dict(os.environ, environment, clear=False),
                patch("backend.app.config.subprocess.run", return_value=completed),
            ):
                key, source, error = _load_qwen_secret()
                self.assertEqual(key, "decrypted-qwen-key")
                self.assertEqual(os.environ["QWEN_API_KEY"], key)
                self.assertEqual(source, "age")
                self.assertEqual(error, "")

    def test_qwen_payload_is_low_variance_and_multimodal(self):
        client = QwenClient(settings())
        payload = client._chat_payload(
            model="qwen3.8-max-preview",
            messages=[{"role": "user", "content": "test"}],
            max_tokens=512,
            json_mode=True,
            reasoning_effort="low",
        )
        self.assertTrue(client.supports_multimodal)
        self.assertEqual(payload["model"], "qwen3.8-max-preview")
        self.assertEqual(payload["temperature"], 0.1)
        self.assertEqual(payload["max_tokens"], 512)
        self.assertEqual(payload["reasoning_effort"], "low")
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertNotIn("enable_search", payload)

        search_payload = client._chat_payload(
            model="qwen3.7-max",
            messages=[{"role": "user", "content": "test"}],
            max_tokens=512,
            json_mode=True,
            enable_search=True,
        )
        self.assertTrue(search_payload["enable_search"])

    def test_vision_model_uses_multimodal_default_when_not_explicit(self):
        with patch.dict(
            os.environ,
            {
                "QWEN_API_KEY": "test-key",
                "QWEN_MODEL": "qwen3.7-max",
            },
            clear=True,
        ):
            configured = load_settings()

        self.assertEqual(configured.qwen_model, "qwen3.7-max")
        self.assertEqual(
            configured.qwen_vision_model,
            DEFAULT_QWEN_VISION_MODEL,
        )
        self.assertEqual(
            configured.pdf_transcription_mode,
            "vision_nodes_strict",
        )
        self.assertEqual(
            configured.pdf_page_extraction_mode,
            "direct",
        )
        self.assertEqual(configured.pdf_transcription_concurrency, 8)
        self.assertEqual(configured.pdf_transcription_max_attempts, 3)
        self.assertEqual(configured.provider_concurrency, 8)

    def test_qwen_vision_capability_matches_upstream_model_contract(self):
        for model in (
            "qwen3.7-plus",
            "qwen3.7-plus-2026-05-26",
            "qwen3-vl-plus",
            "qwen-vl-max",
        ):
            with self.subTest(model=model):
                self.assertTrue(qwen_model_supports_vision(model))

        for model in (
            "qwen3.7-max",
            "qwen3-coder-plus",
            "unknown-qwen-proxy",
        ):
            with self.subTest(model=model):
                self.assertFalse(qwen_model_supports_vision(model))

    def test_layout_nodes_profile_is_coerced_to_direct(self):
        with patch.dict(
            os.environ,
            {
                "QWEN_API_KEY": "test-key",
                "MINDMAP_PDF_PAGE_EXTRACTION_MODE": "layout_nodes",
            },
            clear=True,
        ):
            configured = load_settings()

        self.assertEqual(
            configured.pdf_page_extraction_mode,
            "direct",
        )

    def test_text_transcription_mode_is_coerced_to_visual_nodes(self):
        with patch.dict(
            os.environ,
            {
                "QWEN_API_KEY": "test-key",
                "MINDMAP_PDF_TRANSCRIPTION_MODE": "vision_strict",
            },
            clear=True,
        ):
            configured = load_settings()

        self.assertEqual(
            configured.pdf_transcription_mode,
            "vision_nodes_strict",
        )

    def test_direct_layout_fallback_profile_is_coerced_to_direct(self):
        with patch.dict(
            os.environ,
            {
                "QWEN_API_KEY": "test-key",
                "MINDMAP_PDF_PAGE_EXTRACTION_MODE": (
                    "direct_layout_fallback"
                ),
            },
            clear=True,
        ):
            configured = load_settings()

        self.assertEqual(
            configured.pdf_page_extraction_mode,
            "direct",
        )

    async def test_all_role_runtimes_use_qwen(self):
        generator, verifier, vision, second, arbiter, selection, _ = (
            await build_role_runtimes(
                provider="qwen",
                model=DEFAULT_QWEN_MODEL,
                mode="precision",
                use_ai=False,
            )
        )
        runtimes = [generator, verifier, vision, second, arbiter]
        self.assertTrue(all(runtime is not None for runtime in runtimes))
        self.assertTrue(all(runtime.provider == "qwen" for runtime in runtimes))
        self.assertTrue(
            all(
                runtime.model == DEFAULT_QWEN_MODEL
                for runtime in (generator, verifier, second, arbiter)
            )
        )
        self.assertEqual(vision.model, DEFAULT_QWEN_VISION_MODEL)
        self.assertEqual(selection.generator_provider, "qwen")
        self.assertEqual(selection.verifier_provider, "qwen")
        self.assertEqual(selection.vision_provider, "qwen")
        self.assertEqual(selection.vision_model, None)
        self.assertEqual(selection.arbiter_provider, "qwen")

    async def test_precision_text_roles_share_client_and_vision_is_preflighted(self):
        class FakeQwenClient:
            api_key = "qwen-test-key"

            def __init__(self):
                self.check_calls = 0

            async def check_model(self, model: str):
                self.check_calls += 1
                return True, f"{model} available"

        client = FakeQwenClient()
        with patch(
            "backend.app.cplus_pipeline._client",
            return_value=client,
        ):
            generator, verifier, vision, second, arbiter, _, _ = (
                await build_role_runtimes(
                    provider="qwen",
                    model=DEFAULT_QWEN_MODEL,
                    mode="precision",
                    use_ai=True,
                )
            )

        runtimes = [generator, verifier, vision, second, arbiter]
        self.assertEqual(client.check_calls, 2)
        self.assertTrue(
            all(runtime is not None and runtime.client is client for runtime in runtimes)
        )
        self.assertEqual(vision.model, DEFAULT_QWEN_VISION_MODEL)

    async def test_role_runtimes_reject_other_providers(self):
        with self.assertRaisesRegex(ValueError, "Unsupported provider"):
            await build_role_runtimes(
                provider="deepseek",
                model="deepseek-v4-pro",
                mode="standard",
                use_ai=False,
            )


if __name__ == "__main__":
    unittest.main()
