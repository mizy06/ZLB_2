from __future__ import annotations

import os
import unittest
from dataclasses import replace
from unittest.mock import patch

import httpx
from fastapi import HTTPException

from backend.app import main
from backend.app.agent_prompts import THEME_SYNTHESIZER_PROMPT_SHA256
from backend.app.config import (
    DEFAULT_QWEN_BASE_URL,
    DEFAULT_QWEN_MODEL,
    DEFAULT_QWEN_VISION_MODEL,
    load_settings,
    production_qwen_configuration_issues,
    validate_production_qwen_configuration,
)
from backend.app.model_provider import (
    HARD_RETRY_DELAY_CAP_SECONDS,
    OpenAICompatibleClient,
)
from backend.app.pdf_page_knowledge import (
    PAGE_KNOWLEDGE_SCHEMA_VERSION,
    PDF_PAGE_KNOWLEDGE_PROMPT_SHA256,
)
from backend.app.pdf_page_transcription import (
    PAGE_TRANSCRIPTION_SCHEMA_VERSION,
    PDF_PAGE_TRANSCRIPTION_PROMPT_SHA256,
)


class _SequencedAsyncClient:
    def __init__(self, responses: list[httpx.Response]):
        self.responses = list(responses)
        self.calls = 0

    async def post(self, *_args, **_kwargs) -> httpx.Response:
        response = self.responses[self.calls]
        self.calls += 1
        return response


def _provider_response(
    status_code: int,
    payload: dict,
    *,
    retry_after: str | None = None,
) -> httpx.Response:
    headers = {"Retry-After": retry_after} if retry_after else None
    return httpx.Response(
        status_code,
        json=payload,
        headers=headers,
        request=httpx.Request(
            "POST",
            "https://provider.invalid/v1/chat/completions",
        ),
    )


def _chat_success() -> httpx.Response:
    return _provider_response(
        200,
        {"choices": [{"message": {"content": '{"ok": true}'}}]},
    )


class ProductionRouteTDDTests(unittest.IsolatedAsyncioTestCase):
    def test_default_qwen_configuration_uses_standard_formal_endpoint(self):
        with patch.dict(
            os.environ,
            {"QWEN_API_KEY": "test-key"},
            clear=True,
        ):
            loaded = load_settings()

        self.assertEqual(loaded.qwen_base_url, DEFAULT_QWEN_BASE_URL)
        self.assertEqual(loaded.qwen_model, DEFAULT_QWEN_MODEL)
        self.assertEqual(
            loaded.qwen_vision_model,
            DEFAULT_QWEN_VISION_MODEL,
        )

    def test_production_rejects_token_plan_and_preview_contract(self):
        configured = replace(
            main.settings,
            environment="production",
            qwen_api_key="sk-sp-test-token-plan-key",
            qwen_base_url=(
                "https://token-plan.cn-beijing.maas.aliyuncs.com/"
                "compatible-mode/v1"
            ),
            qwen_model="qwen3.8-max-preview",
            qwen_vision_model="qwen3.8-max-preview",
        )

        self.assertEqual(
            production_qwen_configuration_issues(configured),
            (
                "token_plan_key",
                "token_plan_endpoint",
                "text_preview_model",
                "vision_preview_model",
            ),
        )
        with self.assertRaisesRegex(
            RuntimeError,
            "token_plan_key.*token_plan_endpoint",
        ):
            validate_production_qwen_configuration(configured)

    def test_explicit_cn_token_plan_preview_profile_is_exactly_scoped(self):
        configured = replace(
            main.settings,
            environment="production",
            qwen_api_key="sk-sp-approved-token-plan-key",
            qwen_base_url=(
                "https://token-plan.cn-beijing.maas.aliyuncs.com/"
                "compatible-mode/v1"
            ),
            qwen_model="qwen3.8-max-preview",
            qwen_vision_model="qwen3.8-max-preview",
            qwen_production_profile="approved_cn_token_plan_preview",
        )

        self.assertEqual(
            production_qwen_configuration_issues(configured),
            (),
        )
        validate_production_qwen_configuration(configured)

        cases = (
            (
                replace(
                    configured,
                    qwen_api_key="sk-standard-key",
                ),
                ("approved_profile_key_mismatch",),
            ),
            (
                replace(
                    configured,
                    qwen_base_url=(
                        "https://token-plan.ap-southeast-1."
                        "maas.aliyuncs.com/compatible-mode/v1"
                    ),
                ),
                ("approved_profile_endpoint_mismatch",),
            ),
            (
                replace(
                    configured,
                    qwen_model="qwen3.7-max",
                ),
                ("approved_profile_text_model_mismatch",),
            ),
            (
                replace(
                    configured,
                    qwen_vision_model="qwen3.7-plus",
                ),
                ("approved_profile_vision_model_mismatch",),
            ),
        )
        for rejected, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(
                    production_qwen_configuration_issues(rejected),
                    expected,
                )

    def test_production_classifies_all_official_plan_endpoints(self):
        plan_endpoints = (
            (
                "https://coding.dashscope.aliyuncs.com/v1",
                "token_plan_endpoint",
            ),
            (
                "https://coding-intl.dashscope.aliyuncs.com/v1",
                "token_plan_endpoint",
            ),
            (
                "https://token-plan.cn-beijing.maas.aliyuncs.com/"
                "compatible-mode/v1",
                "token_plan_endpoint",
            ),
            (
                "https://token-plan.ap-southeast-1.maas.aliyuncs.com/"
                "compatible-mode/v1",
                "token_plan_endpoint",
            ),
        )

        for endpoint, issue in plan_endpoints:
            with self.subTest(endpoint=endpoint):
                configured = replace(
                    main.settings,
                    environment="production",
                    qwen_api_key="sk-standard-pay-as-you-go-key",
                    qwen_base_url=endpoint,
                    qwen_model="qwen3.7-max",
                    qwen_vision_model="qwen3.7-plus",
                )
                self.assertEqual(
                    production_qwen_configuration_issues(configured),
                    (issue,),
                )

    def test_production_accepts_standard_qwen_text_and_vision_models(self):
        configured = replace(
            main.settings,
            environment="production",
            qwen_api_key="sk-standard-pay-as-you-go-key",
            qwen_base_url=DEFAULT_QWEN_BASE_URL,
            qwen_model="qwen3.7-max",
            qwen_vision_model="qwen3.7-plus",
        )

        self.assertEqual(
            production_qwen_configuration_issues(configured),
            (),
        )
        validate_production_qwen_configuration(configured)

    def test_qwen_production_profile_is_loaded_from_environment(self):
        with patch.dict(
            os.environ,
            {
                "QWEN_API_KEY": "sk-sp-approved-token-plan-key",
                "MINDMAP_QWEN_PRODUCTION_PROFILE": (
                    "approved_cn_token_plan_preview"
                ),
            },
            clear=True,
        ):
            loaded = load_settings()

        self.assertEqual(
            loaded.qwen_production_profile,
            "approved_cn_token_plan_preview",
        )

    def test_production_accepts_official_standard_and_workspace_endpoints(self):
        accepted_endpoints = (
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
            "https://dashscope-us.aliyuncs.com/compatible-mode/v1",
            "https://cn-hongkong.dashscope.aliyuncs.com/compatible-mode/v1",
            (
                "https://llm-workspace.cn-beijing.maas.aliyuncs.com/"
                "compatible-mode/v1"
            ),
            (
                "https://llm-workspace.ap-southeast-1.maas.aliyuncs.com/"
                "compatible-mode/v1"
            ),
            (
                "https://ws-r1lp2twiz8lj5t79.cn-beijing."
                "maas.aliyuncs.com/compatible-mode/v1"
            ),
            (
                "https://llm-workspace.ap-northeast-1.maas.aliyuncs.com/"
                "compatible-mode/v1"
            ),
            (
                "https://llm-workspace.eu-central-1.maas.aliyuncs.com/"
                "compatible-mode/v1"
            ),
        )

        for endpoint in accepted_endpoints:
            with self.subTest(endpoint=endpoint):
                configured = replace(
                    main.settings,
                    environment="production",
                    qwen_api_key="sk-ws-standard-workspace-key",
                    qwen_base_url=endpoint,
                    qwen_model="qwen3.7-max",
                    qwen_vision_model="qwen3.7-plus",
                )
                self.assertEqual(
                    production_qwen_configuration_issues(configured),
                    (),
                )
                validate_production_qwen_configuration(configured)

    def test_production_rejects_unapproved_and_malformed_endpoints(self):
        cases = (
            (
                "https://provider.example/compatible-mode/v1",
                ("unapproved_endpoint",),
            ),
            (
                "https://ws-other.cn-beijing.maas.aliyuncs.com/"
                "compatible-mode/v1",
                ("unapproved_endpoint",),
            ),
            (
                "https://trial.cn-beijing.maas.aliyuncs.com/"
                "compatible-mode/v1",
                ("trial_endpoint",),
            ),
            (
                "https://dashscope.aliyuncs.com/v1",
                ("invalid_endpoint",),
            ),
            (
                "https://dashscope.aliyuncs.com:8443/compatible-mode/v1",
                ("invalid_endpoint",),
            ),
            (
                "https://dashscope.aliyuncs.com/compatible-mode/v1"
                "?token=forbidden",
                ("invalid_endpoint",),
            ),
            (
                "https://dashscope.aliyuncs.com/compatible-mode/v1"
                "#fragment",
                ("invalid_endpoint",),
            ),
        )

        for endpoint, expected in cases:
            with self.subTest(endpoint=endpoint):
                configured = replace(
                    main.settings,
                    environment="production",
                    qwen_api_key="sk-ws-standard-workspace-key",
                    qwen_base_url=endpoint,
                    qwen_model="qwen3.7-max",
                    qwen_vision_model="qwen3.7-plus",
                )
                self.assertEqual(
                    production_qwen_configuration_issues(configured),
                    expected,
                )
                with self.assertRaises(RuntimeError):
                    validate_production_qwen_configuration(configured)

    def test_production_rejects_text_only_qwen_as_vision_model(self):
        configured = replace(
            main.settings,
            environment="production",
            qwen_api_key="sk-standard-pay-as-you-go-key",
            qwen_base_url=DEFAULT_QWEN_BASE_URL,
            qwen_model="qwen3.7-max",
            qwen_vision_model="qwen3.7-max",
        )

        self.assertEqual(
            production_qwen_configuration_issues(configured),
            ("vision_model_not_multimodal",),
        )

    def test_model_route_accepts_formal_qwen_families_only(self):
        for model in ("qwen3.7-max", "qwen3-vl-plus"):
            with self.subTest(model=model):
                main._require_qwen_model("qwen", model)

        with self.assertRaises(HTTPException) as raised:
            main._require_qwen_model("qwen", "deepseek-v4")
        self.assertEqual(raised.exception.status_code, 400)

    def test_generation_contract_versions_default_to_current_pipeline(self):
        with patch.dict(
            os.environ,
            {
                "QWEN_API_KEY": "test-key",
            },
            clear=True,
        ):
            loaded = load_settings()

        self.assertEqual(
            loaded.parser_version,
            "parser-v9-direct-visual-only",
        )
        self.assertEqual(
            loaded.prompt_version,
            "cplus-prompts-v13-direct-visual-only",
        )
        self.assertEqual(
            loaded.theme_prompt_version,
            "theme-synthesizer-v4-semantic-partition",
        )
        self.assertEqual(
            loaded.pdf_page_knowledge_prompt_version,
            "cplus-prompts-v13-direct-visual-only",
        )
        self.assertEqual(
            loaded.pdf_page_transcription_prompt_version,
            "cplus-prompts-v8-page-knowledge",
        )

    def test_run_manifest_records_sanitized_models_and_runtime_versions(self):
        configured = replace(
            main.settings,
            qwen_base_url=(
                "https://user:secret@provider.example/v1/?token=hidden"
            ),
            qwen_vision_model="qwen3.8-max-preview",
            qwen_production_profile="approved_cn_token_plan_preview",
            pdf_transcription_mode="vision_nodes_strict",
            pdf_page_extraction_mode="direct",
            pdf_transcription_dpi=192,
            pdf_transcription_concurrency=8,
            pdf_transcription_max_attempts=2,
            pdf_transcription_min_confidence=0.85,
        )
        versions = {
            "python": "3.12.11",
            "pypdf": "6.1.0",
            "pdfplumber": "0.11.10",
            "pdfminer.six": "20250506",
            "pylatexenc": "2.11",
            "poppler": "25.06.0",
        }
        with (
            patch.object(main, "settings", configured),
            patch.object(main, "_runtime_versions", return_value=versions),
        ):
            manifest = main._run_manifest(
                source_sha256="abc123",
                source_size=42,
                filename="fixture.pdf",
                provider="qwen",
                model="qwen3.8-max",
                page_count=92,
            )

        self.assertEqual(manifest["text_model"], "qwen3.8-max")
        self.assertEqual(manifest["vision_model"], "qwen3.8-max-preview")
        self.assertEqual(
            manifest["qwen_production_profile"],
            "approved_cn_token_plan_preview",
        )
        self.assertEqual(
            manifest["provider_endpoint"],
            "https://provider.example/v1",
        )
        self.assertNotIn("secret", str(manifest))
        self.assertNotIn("hidden", str(manifest))
        self.assertEqual(manifest["runtime_versions"], versions)
        self.assertEqual(
            manifest["prompt_versions"],
            {
                "pipeline": configured.prompt_version,
                "theme": {
                    "version": configured.theme_prompt_version,
                    "sha256": THEME_SYNTHESIZER_PROMPT_SHA256,
                },
                "pdf_page_knowledge": {
                    "version": (
                        configured.pdf_page_knowledge_prompt_version
                    ),
                    "sha256": PDF_PAGE_KNOWLEDGE_PROMPT_SHA256,
                },
                "pdf_page_transcription": {
                    "version": (
                        configured.pdf_page_transcription_prompt_version
                    ),
                    "sha256": PDF_PAGE_TRANSCRIPTION_PROMPT_SHA256,
                },
            },
        )
        transcription = manifest["pdf_page_transcription"]
        self.assertEqual(transcription["mode"], "vision_nodes_strict")
        self.assertEqual(
            transcription["prompt_version"],
            configured.pdf_page_knowledge_prompt_version,
        )
        self.assertEqual(
            transcription["prompt_sha256"],
            PDF_PAGE_KNOWLEDGE_PROMPT_SHA256,
        )
        self.assertEqual(
            transcription["extraction_profile"],
            "direct",
        )
        self.assertIsNone(transcription["layout_schema_version"])
        self.assertIsNone(transcription["layout_node_schema_version"])
        self.assertEqual(
            transcription["schema_version"],
            PAGE_KNOWLEDGE_SCHEMA_VERSION,
        )
        self.assertEqual(
            transcription["output_contract"],
            "PageKnowledgeExtraction",
        )
        self.assertEqual(
            transcription["source_mode"],
            "direct_visual_only",
        )
        self.assertFalse(transcription["text_intermediate_built"])
        self.assertEqual(transcription["render_dpi"], 192)
        self.assertEqual(transcription["min_confidence"], 0.85)

    def test_poppler_version_is_unavailable_without_pdftoppm(self):
        with patch.object(main.shutil, "which", return_value=None):
            self.assertEqual(main._poppler_version(), "unavailable")

    def test_retry_delay_cap_is_loaded_from_environment(self):
        with patch.dict(
            os.environ,
            {
                "QWEN_API_KEY": "test-key",
                "MINDMAP_PROVIDER_RETRY_DELAY_CAP_SECONDS": "7.5",
            },
        ):
            loaded = load_settings()

        self.assertEqual(
            loaded.provider_retry_delay_cap_seconds,
            7.5,
        )

    async def test_disabled_api_documentation_paths_do_not_fall_through_to_spa(
        self,
    ):
        production = replace(main.settings, environment="production")
        with patch.object(main, "settings", production):
            for path in (
                "docs",
                "docs/",
                "redoc",
                "redoc/",
                "openapi.json",
            ):
                with self.subTest(path=path):
                    with self.assertRaises(HTTPException) as raised:
                        await main.frontend(path)
                    self.assertEqual(raised.exception.status_code, 404)

    async def test_production_workbench_requires_local_account(self):
        with patch.dict(
            os.environ,
            {
                "MINDMAP_ENV": "production",
                "MINDMAP_WORKBENCH_OWNER_ID": "legacy-owner",
                "QWEN_API_KEY": "test-key",
            },
            clear=True,
        ):
            configured = load_settings()

        with patch.object(main, "settings", configured):
            payload = await main.health()

        self.assertTrue(payload["auth_required"])
        self.assertTrue(payload["auth_configured"])
        self.assertEqual(configured.workbench_owner_id, "legacy-owner")

    async def test_session_routes_are_removed(self):
        session_routes = [
            route
            for route in main.app.routes
            if getattr(route, "path", "") == "/api/session"
        ]

        self.assertEqual(session_routes, [])

    async def test_retry_after_delay_obeys_configured_and_hard_caps(self):
        async def exercise(configured_cap: float) -> list[float]:
            sleeps: list[float] = []
            fake = _SequencedAsyncClient(
                [
                    _provider_response(
                        429,
                        {"error": {"message": "rate limited"}},
                        retry_after="86400",
                    ),
                    _chat_success(),
                ]
            )

            async def fake_sleep(delay: float) -> None:
                sleeps.append(delay)

            client = OpenAICompatibleClient(
                settings=replace(
                    main.settings,
                    provider_max_attempts=2,
                ),
                api_key="test-key",
                base_url="https://provider.invalid/v1",
                provider_name=f"retry-cap-{configured_cap}",
                api_key_env_name="TEST_KEY",
                temperature=0.1,
                http_client=fake,
                retry_sleep=fake_sleep,
                retry_delay_cap_seconds=configured_cap,
            )
            payload = await client.complete_json(
                model="test-model",
                system_prompt="system",
                user_prompt="user",
            )
            self.assertEqual(payload, {"ok": True})
            self.assertEqual(fake.calls, 2)
            return sleeps

        self.assertEqual(await exercise(1.25), [1.25])
        self.assertEqual(
            await exercise(HARD_RETRY_DELAY_CAP_SECONDS * 100),
            [HARD_RETRY_DELAY_CAP_SECONDS],
        )


if __name__ == "__main__":
    unittest.main()
