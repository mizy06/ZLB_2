from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace

import httpx

from backend.app.model_provider import (
    ModelProviderError,
    OpenAICompatibleClient,
)


class _StreamContext:
    def __init__(self, response: httpx.Response):
        self.response = response

    async def __aenter__(self) -> httpx.Response:
        return self.response

    async def __aexit__(self, *_args) -> None:
        await self.response.aclose()


class _StreamingHTTPClient:
    def __init__(self, body: str):
        self.body = body
        self.requests: list[dict] = []

    def stream(self, method: str, url: str, **kwargs) -> _StreamContext:
        self.requests.append(
            {
                "method": method,
                "url": url,
                **kwargs,
            }
        )
        request = httpx.Request(method, url)
        return _StreamContext(
            httpx.Response(
                200,
                request=request,
                headers={"Content-Type": "text/event-stream"},
                content=self.body.encode("utf-8"),
            )
        )


class _DelayedStream(httpx.AsyncByteStream):
    def __init__(self, chunks: list[tuple[float, str]]):
        self.chunks = chunks

    async def __aiter__(self):
        for delay, chunk in self.chunks:
            await asyncio.sleep(delay)
            yield chunk.encode("utf-8")


class _DelayedStreamingHTTPClient:
    def __init__(self, chunks: list[tuple[float, str]]):
        self.chunks = chunks
        self.requests: list[dict] = []

    def stream(self, method: str, url: str, **kwargs) -> _StreamContext:
        self.requests.append(
            {
                "method": method,
                "url": url,
                **kwargs,
            }
        )
        request = httpx.Request(method, url)
        return _StreamContext(
            httpx.Response(
                200,
                request=request,
                headers={"Content-Type": "text/event-stream"},
                stream=_DelayedStream(self.chunks),
            )
        )


def _client(body: str) -> tuple[OpenAICompatibleClient, _StreamingHTTPClient]:
    http_client = _StreamingHTTPClient(body)
    settings = SimpleNamespace(
        provider_max_attempts=1,
        provider_retry_delay_cap_seconds=30,
        provider_timeout_seconds=30,
        provider_concurrency=2,
        provider_circuit_cooldown_seconds=30,
        provider_retry_base_seconds=0,
    )
    client = OpenAICompatibleClient(
        settings=settings,
        api_key="test-key",
        base_url="https://example.test/v1",
        provider_name="Qwen",
        api_key_env_name="QWEN_API_KEY",
        temperature=0.1,
        http_client=http_client,
    )
    return client, http_client


class ModelStreamingTests(unittest.IsolatedAsyncioTestCase):
    async def test_chat_completion_streams_deltas_and_parses_final_json(self):
        client, http_client = _client(
            'data: {"choices":[{"delta":{"content":"{\\\"value\\\":"},'
            '"finish_reason":null}]}\n\n'
            'data: {"choices":[{"delta":{"content":"1}"},'
            '"finish_reason":"stop"}]}\n\n'
            "data: [DONE]\n\n"
        )
        deltas: list[str] = []

        result = await client.complete_json(
            model="qwen3.8-max-preview",
            system_prompt="system",
            user_prompt="user",
            stream_callback=deltas.append,
        )

        self.assertEqual(result, {"value": 1})
        self.assertEqual(deltas, ['{"value":', "1}"])
        self.assertTrue(http_client.requests[0]["json"]["stream"])

    async def test_chat_stream_adds_oss_resolution_header(self):
        client, http_client = _client(
            'data: {"choices":[{"delta":{"content":"{\\\"value\\\":1}"},'
            '"finish_reason":"stop"}]}\n\n'
        )

        result = await client.complete_multi_image_json(
            model="qwen3.8-flash",
            system_prompt="system",
            user_prompt="user",
            images=[
                (
                    "slide_0001",
                    "oss://dashscope-instant/session/slide_0001.jpg",
                )
            ],
            stream_callback=lambda _delta: None,
        )

        self.assertEqual(result, {"value": 1})
        self.assertEqual(
            http_client.requests[0]["headers"][
                "X-DashScope-OssResourceResolve"
            ],
            "enable",
        )

    async def test_stream_timeout_resets_after_each_json_event(self):
        http_client = _DelayedStreamingHTTPClient(
            [
                (
                    0.06,
                    'data: {"choices":[{"delta":{"content":"{\\\"value\\\":"},'
                    '"finish_reason":null}]}\n\n',
                ),
                (
                    0.06,
                    'data: {"choices":[{"delta":{"content":"1}"},'
                    '"finish_reason":"stop"}]}\n\n',
                ),
            ]
        )
        client, _ = _client("")
        client._injected_http_client = http_client

        result = await client.complete_json(
            model="qwen3.8-flash",
            system_prompt="system",
            user_prompt="user",
            timeout_seconds=0.1,
            stream_callback=lambda _delta: None,
        )

        self.assertEqual(result, {"value": 1})

    async def test_stream_fails_after_event_idle_timeout(self):
        records: list[dict] = []
        http_client = _DelayedStreamingHTTPClient(
            [
                (
                    0,
                    'data: {"choices":[{"delta":{"content":"{\\\"value\\\":"},'
                    '"finish_reason":null}]}\n\n',
                ),
                (
                    0.12,
                    'data: {"choices":[{"delta":{"content":"1}"},'
                    '"finish_reason":"stop"}]}\n\n',
                ),
            ]
        )
        client, _ = _client("")
        client._injected_http_client = http_client
        client.attempt_recorder = records.append

        with self.assertRaisesRegex(
            ModelProviderError,
            "连续 0.03 秒未收到流式事件",
        ):
            await client.complete_json(
                model="qwen3.8-flash",
                system_prompt="system",
                user_prompt="user",
                timeout_seconds=0.03,
                stream_callback=lambda _delta: None,
            )

        self.assertEqual(records[0]["status"], "retryable_error")
        self.assertEqual(
            records[0]["details"]["error_type"],
            "stream_idle_timeout",
        )
        self.assertEqual(records[0]["details"]["stream_event_count"], 1)

    async def test_responses_api_streams_output_text_and_keeps_response_id(self):
        final_output = (
            '{"type":"response.completed","response":'
            '{"id":"resp_123","status":"completed",'
            '"output":[{"content":[{"type":"output_text",'
            '"text":"{\\\"answer\\\":\\\"ok\\\"}"}]}],'
            '"usage":{"output_tokens":5}}}'
        )
        client, http_client = _client(
            'data: {"type":"response.created","response":'
            '{"id":"resp_123","status":"in_progress"}}\n\n'
            'data: {"type":"response.output_text.delta",'
            '"delta":"{\\\"answer\\\":"}\n\n'
            'data: {"type":"response.output_text.delta",'
            '"delta":"\\\"ok\\\"}"}\n\n'
            f"data: {final_output}\n\n"
        )
        deltas: list[str] = []

        result = await client.complete_response_json(
            model="qwen3.8-max-preview",
            system_prompt="system",
            user_prompt="user",
            stream_callback=deltas.append,
        )

        self.assertEqual(result.payload, {"answer": "ok"})
        self.assertEqual(result.response_id, "resp_123")
        self.assertEqual(result.usage, {"output_tokens": 5})
        self.assertEqual(deltas, ['{"answer":', '"ok"}'])
        self.assertTrue(http_client.requests[0]["json"]["stream"])
