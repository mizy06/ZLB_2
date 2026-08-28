from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
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


def _incomplete_length_limited_chat_response() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {"content": '{"ok":'},
                    "finish_reason": "length",
                }
            ],
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


def _responses_response(
    *,
    response_id: str = "resp_test_123",
    status: str = "completed",
    text: str = '{"ok": true}',
) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": response_id,
            "object": "response",
            "status": status,
            "output": [
                {
                    "type": "reasoning",
                    "content": [],
                },
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "output_text",
                            "text": text,
                        }
                    ],
                },
            ],
            "usage": {
                "input_tokens": 1400,
                "output_tokens": 120,
                "total_tokens": 1520,
                "input_tokens_details": {
                    "cached_tokens": 1100,
                },
            },
        },
        request=httpx.Request(
            "POST",
            "https://qwen.invalid/compatible-mode/v1/responses",
        ),
    )


class _CapturingHttpClient:
    def __init__(self, response: httpx.Response | None = None) -> None:
        self.response = response or _chat_response()
        self.calls: list[dict[str, Any]] = []

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        self.calls.append({"url": url, **kwargs})
        return self.response


class _TemporaryUploadHttpClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        self.calls.append({"method": "get", "url": url, **kwargs})
        return httpx.Response(
            200,
            json={
                "data": {
                    "upload_host": (
                        "https://bucket.oss-cn-beijing.aliyuncs.com"
                    ),
                    "upload_dir": "temporary/session-123",
                    "oss_access_key_id": "temporary-access-id",
                    "signature": "temporary-signature",
                    "policy": "temporary-policy",
                    "x_oss_object_acl": "private",
                    "x_oss_forbid_overwrite": "true",
                }
            },
            request=httpx.Request("GET", url),
        )

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        self.calls.append({"method": "post", "url": url, **kwargs})
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
        )


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
    async def test_responses_initial_image_call_uses_session_cache_and_oss(
        self,
    ) -> None:
        records: list[dict[str, Any]] = []
        http_client = _CapturingHttpClient(_responses_response())
        client = QwenClient(_settings())
        client._injected_http_client = http_client
        client.attempt_recorder = records.append

        result = await client.complete_response_json(
            model="qwen3.7-plus",
            system_prompt="PRIVATE-SYSTEM-PROMPT",
            user_prompt="PRIVATE-SOURCE-TEXT",
            images=[
                ("slide_0001", "oss://temporary/slide_0001.jpg"),
                ("slide_0002", "oss://temporary/slide_0002.jpg"),
            ],
            session_cache=True,
            max_attempts=1,
            reasoning_effort="low",
            max_output_tokens=24_000,
            timeout_seconds=90,
        )

        self.assertEqual(result.payload, {"ok": True})
        self.assertEqual(result.response_id, "resp_test_123")
        self.assertEqual(
            result.usage["input_tokens_details"]["cached_tokens"],
            1100,
        )
        request = http_client.calls[0]
        self.assertTrue(request["url"].endswith("/responses"))
        self.assertEqual(
            request["headers"]["x-dashscope-session-cache"],
            "enable",
        )
        self.assertEqual(
            request["headers"]["X-DashScope-OssResourceResolve"],
            "enable",
        )
        self.assertTrue(request["json"]["store"])
        self.assertNotIn("previous_response_id", request["json"])
        self.assertEqual(
            request["json"]["reasoning"],
            {"effort": "low"},
        )
        self.assertEqual(request["json"]["max_output_tokens"], 24_000)
        response_input = request["json"]["input"]
        self.assertEqual(len(response_input), 2)
        image_blocks = response_input[0]["content"]
        self.assertEqual(
            [block["type"] for block in image_blocks[:4]],
            [
                "input_text",
                "input_image",
                "input_text",
                "input_image",
            ],
        )
        self.assertEqual(len(records), 1)
        policy = records[0]["details"]["request_policy"]
        self.assertEqual(policy["image_count"], 2)
        self.assertFalse(policy["previous_response_id_present"])
        self.assertTrue(policy["session_cache_enabled"])
        self.assertEqual(policy["max_output_tokens"], 24_000)
        self.assertEqual(
            records[0]["details"]["usage"]["input_tokens_details"][
                "cached_tokens"
            ],
            1100,
        )
        serialized = json.dumps(records, ensure_ascii=False)
        self.assertNotIn("PRIVATE-SYSTEM-PROMPT", serialized)
        self.assertNotIn("PRIVATE-SOURCE-TEXT", serialized)
        self.assertNotIn("oss://temporary", serialized)

    async def test_responses_follow_up_sends_only_previous_response_id(
        self,
    ) -> None:
        http_client = _CapturingHttpClient(
            _responses_response(response_id="resp_follow_up")
        )
        client = QwenClient(_settings())
        client._injected_http_client = http_client

        result = await client.complete_response_json(
            model="qwen3.7-plus",
            system_prompt="review instructions",
            user_prompt="review current graph",
            previous_response_id="resp_test_123",
            session_cache=True,
            max_attempts=1,
            reasoning_effort="minimal",
        )

        self.assertEqual(result.response_id, "resp_follow_up")
        request = http_client.calls[0]
        self.assertEqual(
            request["json"]["previous_response_id"],
            "resp_test_123",
        )
        self.assertEqual(request["json"]["input"], "review current graph")
        self.assertNotIn(
            "X-DashScope-OssResourceResolve",
            request["headers"],
        )

    async def test_responses_reject_inline_image_data(self) -> None:
        client = QwenClient(_settings())

        with self.assertRaisesRegex(ValueError, "stable URLs"):
            await client.complete_response_json(
                model="qwen3.7-plus",
                system_prompt="system",
                user_prompt="user",
                images=[
                    (
                        "slide_0001",
                        "data:image/jpeg;base64,PRIVATE",
                    )
                ],
                session_cache=True,
            )

    async def test_qwen_temporary_upload_reuses_one_policy_for_all_files(
        self,
    ) -> None:
        http_client = _TemporaryUploadHttpClient()
        client = QwenClient(_settings())
        client._injected_http_client = http_client

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "slide_0001.jpg"
            second = root / "slide_0002.jpg"
            first.write_bytes(b"first-image")
            second.write_bytes(b"second-image")

            urls = await client.upload_temporary_files(
                model="qwen3.7-plus",
                files=[
                    ("slide_0001", first),
                    ("slide_0002", second),
                ],
                concurrency=2,
                timeout_seconds=90,
            )

        self.assertEqual(
            urls,
            [
                (
                    "slide_0001",
                    "oss://temporary/session-123/slide_0001.jpg",
                ),
                (
                    "slide_0002",
                    "oss://temporary/session-123/slide_0002.jpg",
                ),
            ],
        )
        policy_calls = [
            call for call in http_client.calls if call["method"] == "get"
        ]
        upload_calls = [
            call for call in http_client.calls if call["method"] == "post"
        ]
        self.assertEqual(len(policy_calls), 1)
        self.assertEqual(
            policy_calls[0]["params"],
            {"action": "getPolicy", "model": "qwen3.7-plus"},
        )
        self.assertEqual(len(upload_calls), 2)
        self.assertEqual(
            {
                call["data"]["key"]
                for call in upload_calls
            },
            {
                "temporary/session-123/slide_0001.jpg",
                "temporary/session-123/slide_0002.jpg",
            },
        )

    def test_qwen_temporary_upload_rejects_untrusted_host(self) -> None:
        with self.assertRaisesRegex(ModelProviderError, "unsafe host"):
            QwenClient._validated_upload_policy(
                {
                    "data": {
                        "upload_host": "https://attacker.example/upload",
                        "upload_dir": "temporary/session-123",
                        "oss_access_key_id": "temporary-access-id",
                        "signature": "temporary-signature",
                        "policy": "temporary-policy",
                        "x_oss_object_acl": "private",
                        "x_oss_forbid_overwrite": "true",
                    }
                }
            )

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

    def test_qwen_omits_disabled_thinking_budget(self) -> None:
        client = QwenClient(_settings())

        payload = client._chat_payload(
            model="qwen3.8-max",
            messages=[{"role": "user", "content": "test"}],
            max_tokens=2400,
            max_completion_tokens=2400,
            json_mode=True,
            thinking_budget=0,
        )

        self.assertNotIn("thinking_budget", payload)

    def test_non_qwen_keeps_explicit_disabled_thinking_budget(self) -> None:
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
            max_tokens=2400,
            max_completion_tokens=2400,
            json_mode=True,
            thinking_budget=0,
        )

        self.assertEqual(payload["thinking_budget"], 0)

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

    async def test_complete_json_can_opt_in_to_salvage_complete_length_output(
        self,
    ):
        client = QwenClient(_settings())
        client._injected_http_client = _CapturingHttpClient(
            _length_limited_chat_response()
        )

        result = await client.complete_json(
            model="qwen3.8-max-preview",
            system_prompt="system",
            user_prompt="user",
            max_attempts=1,
            accept_complete_json_on_length=True,
        )

        self.assertEqual(result, {"ok": True})

    async def test_length_salvage_still_rejects_incomplete_json(self):
        client = QwenClient(_settings())
        client._injected_http_client = _CapturingHttpClient(
            _incomplete_length_limited_chat_response()
        )

        with self.assertRaisesRegex(ModelProviderError, "截断"):
            await client.complete_json(
                model="qwen3.8-max-preview",
                system_prompt="system",
                user_prompt="user",
                max_attempts=1,
                accept_complete_json_on_length=True,
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
