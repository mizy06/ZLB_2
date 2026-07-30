from __future__ import annotations

import asyncio
import json
import unittest
from types import SimpleNamespace
from typing import Any

import httpx

from backend.app.model_provider import (
    ModelProviderError,
    OpenAICompatibleClient,
)
from backend.app.qwen_provider import QwenClient


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        qwen_api_key="secret-api-key",
        qwen_base_url="https://qwen.invalid/compatible-mode/v1",
        qwen_temperature=0.1,
        provider_max_attempts=3,
        provider_retry_delay_cap_seconds=30,
        provider_circuit_cooldown_seconds=120,
        provider_concurrency=2,
        provider_timeout_seconds=180,
        provider_retry_base_seconds=0,
    )


def _chat_response() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {"content": '{"ok": true}'},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 321,
                "completion_tokens": 4321,
                "total_tokens": 4642,
                "completion_tokens_details": {
                    "reasoning_tokens": 4096,
                },
                "provider_note": "PRIVATE-SOURCE-TEXT",
            },
        },
        request=httpx.Request(
            "POST",
            "https://qwen.invalid/compatible-mode/v1/chat/completions",
        ),
    )


def _length_limited_chat_response() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {"content": '{"ok": true}'},
                    "finish_reason": "length",
                }
            ],
            "usage": {
                "completion_tokens": 8500,
                "total_tokens": 8600,
            },
        },
        request=httpx.Request(
            "POST",
            "https://qwen.invalid/compatible-mode/v1/chat/completions",
        ),
    )


def _chat_response_with_finish_reason(
    finish_reason: str | None,
    *,
    include_field: bool = True,
) -> httpx.Response:
    choice: dict[str, Any] = {
        "message": {"content": '{"ok": true}'},
    }
    if include_field:
        choice["finish_reason"] = finish_reason
    return httpx.Response(
        200,
        json={"choices": [choice]},
        request=httpx.Request(
            "POST",
            "https://qwen.invalid/compatible-mode/v1/chat/completions",
        ),
    )


class _CapturingHttpClient:
    def __init__(self, response: httpx.Response | None = None) -> None:
        self.response = response or _chat_response()
        self.calls: list[dict[str, Any]] = []

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        self.calls.append({"url": url, **kwargs})
        return self.response


class _LeakyTimeoutHttpClient:
    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        del kwargs
        raise httpx.ReadTimeout(
            "PRIVATE-SOURCE-TEXT secret-api-key",
            request=httpx.Request("POST", url),
        )


class _SlowHttpClient:
    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        del url, kwargs
        await asyncio.sleep(1)
        return _chat_response()


class QwenProviderPolicyTDDTests(unittest.IsolatedAsyncioTestCase):
    def test_explicit_total_completion_budget_replaces_max_tokens(self) -> None:
        client = QwenClient(_settings())

        payload = client._chat_payload(
            model="qwen3.8-max-preview",
            messages=[{"role": "user", "content": "test"}],
            max_tokens=4000,
            max_completion_tokens=8500,
            json_mode=True,
            reasoning_effort="low",
        )

        self.assertEqual(payload["reasoning_effort"], "low")
        self.assertEqual(payload["max_completion_tokens"], 8500)
        self.assertNotIn("max_tokens", payload)

    def test_explicit_thinking_budget_is_serialized_without_reasoning_effort(
        self,
    ) -> None:
        client = QwenClient(_settings())

        payload = client._chat_payload(
            model="qwen3.8-max-preview",
            messages=[{"role": "user", "content": "test"}],
            max_tokens=2400,
            max_completion_tokens=3424,
            json_mode=True,
            thinking_budget=1024,
        )

        self.assertEqual(payload["thinking_budget"], 1024)
        self.assertNotIn("reasoning_effort", payload)

    def test_thinking_budget_and_reasoning_effort_are_mutually_exclusive(
        self,
    ) -> None:
        client = QwenClient(_settings())

        with self.assertRaisesRegex(ValueError, "mutually exclusive"):
            client._chat_payload(
                model="qwen3.8-max-preview",
                messages=[{"role": "user", "content": "test"}],
                max_tokens=2400,
                max_completion_tokens=3424,
                json_mode=True,
                reasoning_effort="low",
                thinking_budget=1024,
            )

    def test_ordinary_model_payload_keeps_existing_default_fields(self) -> None:
        client = OpenAICompatibleClient(
            settings=_settings(),
            api_key="ordinary-key",
            base_url="https://ordinary.invalid/v1",
            provider_name="ordinary",
            api_key_env_name="ORDINARY_API_KEY",
            temperature=0.2,
        )

        payload = client._chat_payload(
            model="ordinary-model",
            messages=[{"role": "user", "content": "test"}],
            max_tokens=512,
            json_mode=True,
        )

        self.assertEqual(payload["max_tokens"], 512)
        self.assertEqual(payload["temperature"], 0.2)
        self.assertNotIn("max_completion_tokens", payload)
        self.assertNotIn("reasoning_effort", payload)
        self.assertNotIn("thinking_budget", payload)

    async def test_complete_json_applies_timeout_and_records_safe_usage(
        self,
    ) -> None:
        system_prompt = "PRIVATE-SYSTEM-PROMPT"
        user_prompt = "PRIVATE-SOURCE-TEXT"
        records: list[dict[str, Any]] = []
        http_client = _CapturingHttpClient()
        client = QwenClient(_settings())
        client._injected_http_client = http_client
        client.attempt_recorder = records.append

        result = await client.complete_json(
            model="qwen3.8-max-preview",
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=4000,
            max_completion_tokens=8500,
            max_attempts=1,
            reasoning_effort="low",
            timeout_seconds=90,
        )

        self.assertEqual(result, {"ok": True})
        self.assertEqual(len(http_client.calls), 1)
        request = http_client.calls[0]
        self.assertEqual(request["timeout"], 90)
        self.assertEqual(request["json"]["max_completion_tokens"], 8500)
        self.assertNotIn("max_tokens", request["json"])

        self.assertEqual(len(records), 1)
        details = records[0]["details"]
        policy = details["request_policy"]
        self.assertEqual(policy["max_completion_tokens"], 8500)
        self.assertEqual(policy["timeout_seconds"], 90)
        self.assertEqual(policy["reasoning_effort"], "low")
        self.assertEqual(policy["message_count"], 2)
        self.assertEqual(
            policy["prompt_chars"],
            len(system_prompt) + len(user_prompt),
        )
        self.assertEqual(details["finish_reason"], "stop")
        self.assertEqual(details["usage"]["prompt_tokens"], 321)
        self.assertEqual(
            details["usage"]["completion_tokens_details"][
                "reasoning_tokens"
            ],
            4096,
        )
        self.assertNotIn("provider_note", details["usage"])

        serialized_record = json.dumps(records[0], ensure_ascii=False)
        for forbidden in (
            system_prompt,
            user_prompt,
            "secret-api-key",
            "messages",
            "Authorization",
            '{"ok": true}',
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, serialized_record)

    async def test_complete_json_records_explicit_thinking_budget(self) -> None:
        records: list[dict[str, Any]] = []
        http_client = _CapturingHttpClient()
        client = QwenClient(_settings())
        client._injected_http_client = http_client
        client.attempt_recorder = records.append

        result = await client.complete_json(
            model="qwen3.8-max-preview",
            system_prompt="system",
            user_prompt="user",
            max_tokens=2400,
            max_completion_tokens=3424,
            max_attempts=1,
            thinking_budget=1024,
            timeout_seconds=90,
        )

        self.assertEqual(result, {"ok": True})
        request = http_client.calls[0]
        self.assertEqual(request["json"]["thinking_budget"], 1024)
        self.assertNotIn("reasoning_effort", request["json"])
        self.assertEqual(
            records[0]["details"]["request_policy"]["thinking_budget"],
            1024,
        )

    async def test_ordinary_call_does_not_add_a_request_timeout_override(
        self,
    ) -> None:
        http_client = _CapturingHttpClient()
        client = OpenAICompatibleClient(
            settings=_settings(),
            api_key="ordinary-key",
            base_url="https://ordinary.invalid/v1",
            provider_name="ordinary",
            api_key_env_name="ORDINARY_API_KEY",
            temperature=0.2,
            http_client=http_client,
        )

        await client.complete_json(
            model="ordinary-model",
            system_prompt="system",
            user_prompt="user",
            max_tokens=512,
        )

        request = http_client.calls[0]
        self.assertNotIn("timeout", request)
        self.assertEqual(request["json"]["max_tokens"], 512)
        self.assertNotIn("max_completion_tokens", request["json"])

    async def test_length_finish_reason_is_not_accepted_as_complete_json(self):
        client = QwenClient(_settings())
        client._injected_http_client = _CapturingHttpClient(
            _length_limited_chat_response()
        )

        with self.assertRaisesRegex(ModelProviderError, "截断"):
            await client.complete_json(
                model="qwen3.8-max-preview",
                system_prompt="system",
                user_prompt="user",
                max_tokens=4000,
                max_completion_tokens=8500,
                max_attempts=1,
                reasoning_effort="low",
                timeout_seconds=90,
            )

    async def test_content_filter_finish_reason_is_not_accepted_as_complete_json(
        self,
    ):
        client = QwenClient(_settings())
        client._injected_http_client = _CapturingHttpClient(
            _chat_response_with_finish_reason("content_filter")
        )

        with self.assertRaisesRegex(ModelProviderError, "未正常结束"):
            await client.complete_json(
                model="qwen3.8-max-preview",
                system_prompt="system",
                user_prompt="user",
                max_attempts=1,
            )

    async def test_missing_or_null_finish_reason_remains_compatible(self):
        for label, response in (
            (
                "missing",
                _chat_response_with_finish_reason(
                    None,
                    include_field=False,
                ),
            ),
            ("null", _chat_response_with_finish_reason(None)),
        ):
            with self.subTest(label=label):
                client = QwenClient(_settings())
                client._injected_http_client = _CapturingHttpClient(response)
                result = await client.complete_json(
                    model="qwen3.8-max-preview",
                    system_prompt="system",
                    user_prompt="user",
                    max_attempts=1,
                )
                self.assertEqual(result, {"ok": True})

    async def test_http_error_text_is_not_exposed_or_persisted(self):
        secret = "PRIVATE-SOURCE-TEXT secret-api-key"
        response = httpx.Response(
            400,
            json={
                "error": {
                    "message": secret,
                    "code": "InvalidParameter",
                }
            },
            request=httpx.Request(
                "POST",
                "https://qwen.invalid/compatible-mode/v1/chat/completions",
            ),
        )
        records: list[dict[str, Any]] = []
        client = QwenClient(_settings())
        client._injected_http_client = _CapturingHttpClient(response)
        client.attempt_recorder = records.append

        with self.assertRaises(ModelProviderError) as raised:
            await client.complete_json(
                model="qwen3.8-max-preview",
                system_prompt="PRIVATE-SYSTEM-PROMPT",
                user_prompt="PRIVATE-SOURCE-TEXT",
                max_attempts=1,
                timeout_seconds=45,
            )

        self.assertNotIn(secret, str(raised.exception))
        self.assertIn("HTTP 400", str(raised.exception))
        self.assertIn("InvalidParameter", str(raised.exception))
        serialized = json.dumps(records, ensure_ascii=False)
        self.assertNotIn(secret, serialized)
        self.assertNotIn("PRIVATE-SYSTEM-PROMPT", serialized)
        self.assertEqual(
            records[0]["details"]["error_code"],
            "InvalidParameter",
        )

    async def test_unsafe_http_error_code_is_not_exposed_or_persisted(self):
        secret = "PRIVATE-SOURCE-TEXT secret-api-key"
        response = httpx.Response(
            500,
            json={
                "error": {
                    "message": secret,
                    "code": f"unsafe code {secret}",
                }
            },
            request=httpx.Request(
                "POST",
                "https://qwen.invalid/compatible-mode/v1/chat/completions",
            ),
        )
        records: list[dict[str, Any]] = []
        client = QwenClient(_settings())
        client._injected_http_client = _CapturingHttpClient(response)
        client.attempt_recorder = records.append

        with self.assertRaises(ModelProviderError) as raised:
            await client.complete_json(
                model="qwen3.8-max-preview",
                system_prompt="PRIVATE-SYSTEM-PROMPT",
                user_prompt="PRIVATE-SOURCE-TEXT",
                max_attempts=1,
            )

        self.assertIn("HTTP 500", str(raised.exception))
        serialized = json.dumps(records, ensure_ascii=False)
        self.assertNotIn(secret, serialized)
        self.assertNotIn("error_code", records[0]["details"])

    async def test_timeout_telemetry_does_not_persist_provider_error_text(
        self,
    ) -> None:
        records: list[dict[str, Any]] = []
        client = OpenAICompatibleClient(
            settings=_settings(),
            api_key="secret-api-key",
            base_url="https://timeout.invalid/v1",
            provider_name="timeout",
            api_key_env_name="TIMEOUT_API_KEY",
            temperature=0.2,
            http_client=_LeakyTimeoutHttpClient(),
            attempt_recorder=records.append,
        )

        with self.assertRaises(ModelProviderError):
            await client.complete_json(
                model="ordinary-model",
                system_prompt="PRIVATE-SYSTEM-PROMPT",
                user_prompt="PRIVATE-SOURCE-TEXT",
                max_attempts=1,
                timeout_seconds=45,
            )

        self.assertEqual(len(records), 1)
        serialized_record = json.dumps(records[0], ensure_ascii=False)
        self.assertNotIn("PRIVATE-SOURCE-TEXT", serialized_record)
        self.assertNotIn("PRIVATE-SYSTEM-PROMPT", serialized_record)
        self.assertNotIn("secret-api-key", serialized_record)
        self.assertEqual(
            records[0]["details"]["request_policy"]["timeout_seconds"],
            45,
        )

    async def test_explicit_timeout_is_an_absolute_request_deadline(
        self,
    ) -> None:
        records: list[dict[str, Any]] = []
        client = OpenAICompatibleClient(
            settings=_settings(),
            api_key="secret-api-key",
            base_url="https://timeout.invalid/v1",
            provider_name="timeout",
            api_key_env_name="TIMEOUT_API_KEY",
            temperature=0.2,
            http_client=_SlowHttpClient(),
            attempt_recorder=records.append,
        )
        loop = asyncio.get_running_loop()
        started = loop.time()

        with self.assertRaises(ModelProviderError):
            await client.complete_json(
                model="ordinary-model",
                system_prompt="system",
                user_prompt="user",
                max_attempts=1,
                timeout_seconds=0.02,
            )

        self.assertLess(loop.time() - started, 0.5)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["status"], "retryable_error")
        self.assertEqual(records[0]["details"]["error_type"], "timeout")


if __name__ == "__main__":
    unittest.main()
