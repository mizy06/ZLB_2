from __future__ import annotations

import asyncio
import inspect
import json
import math
import re
import threading
import time
import uuid
import weakref
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, Awaitable, Callable, Sequence

import httpx

from .config import Settings
from .schemas import Chunk, ChunkExtraction


SYSTEM_PROMPT = """你是课程知识图谱抽取器。你的任务不是自由改写课程，而是提出可审计的候选节点与候选关系。

只输出一个 JSON 对象，格式：
{
  "nodes": [
    {
      "temp_id": "n1",
      "name": "简洁、唯一的知识点名称",
      "type": "concept|method|principle|process|formula|example|person|system",
      "definition": "仅依据原文的简短定义",
      "aliases": [],
      "confidence": 0.0
    }
  ],
  "edges": [
    {
      "source": "节点名称",
      "predicate": "is_a|part_of|depends_on|causes|used_for|includes|contrasts_with|related_to",
      "target": "节点名称",
      "confidence": 0.0
    }
  ]
}

规则：
1. 只抽取对理解课程有意义的知识点，不抽取“本章”“案例”等空泛词。
2. 所有节点和关系必须能由给定文本支持。
3. 关系的 source 和 target 必须对应 nodes 中的名称。
4. 不要输出 Markdown 代码块，不要解释。"""


class ModelProviderError(RuntimeError):
    pass


AttemptRecorder = Callable[[dict[str, Any]], Any | Awaitable[Any]]
ModelStreamCallback = Callable[[str], Any | Awaitable[Any]]
StreamEventHandler = Callable[[dict[str, Any]], Awaitable[None]]

DEFAULT_RETRY_DELAY_CAP_SECONDS = 30.0
HARD_RETRY_DELAY_CAP_SECONDS = 300.0
SAFE_PROVIDER_ERROR_CODE = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}"
)
SAFE_FINISH_REASONS = {
    "stop",
    "length",
    "content_filter",
    "tool_calls",
    "function_call",
}
SAFE_RESPONSE_STATUSES = {
    "completed",
    "failed",
    "in_progress",
    "incomplete",
    "queued",
    "cancelled",
}
RESPONSE_REASONING_EFFORTS = {
    "none",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
}


@dataclass(frozen=True)
class ModelCallContext:
    run_id: str
    recorder: AttemptRecorder
    role: str = "pipeline"
    branch_id: str | None = None
    input_unit_ids: tuple[str, ...] = ()
    stage: str = ""


@dataclass(frozen=True)
class StoredResponseJSON:
    payload: dict[str, Any]
    response_id: str
    status: str
    usage: dict[str, Any]


_MODEL_CALL_CONTEXT: ContextVar[ModelCallContext | None] = ContextVar(
    "model_call_context",
    default=None,
)


@contextmanager
def model_call_context(context: ModelCallContext):
    token = _MODEL_CALL_CONTEXT.set(context)
    try:
        yield context
    finally:
        _MODEL_CALL_CONTEXT.reset(token)


@contextmanager
def model_call_scope(
    *,
    role: str | None = None,
    branch_id: str | None = None,
    input_unit_ids: tuple[str, ...] | list[str] | None = None,
    stage: str | None = None,
):
    current = _MODEL_CALL_CONTEXT.get()
    if current is None:
        yield None
        return
    nested = ModelCallContext(
        run_id=current.run_id,
        recorder=current.recorder,
        role=role if role is not None else current.role,
        branch_id=(
            branch_id if branch_id is not None else current.branch_id
        ),
        input_unit_ids=(
            tuple(input_unit_ids)
            if input_unit_ids is not None
            else current.input_unit_ids
        ),
        stage=stage if stage is not None else current.stage,
    )
    token = _MODEL_CALL_CONTEXT.set(nested)
    try:
        yield nested
    finally:
        _MODEL_CALL_CONTEXT.reset(token)


def set_model_call_stage(stage: str) -> None:
    context = _MODEL_CALL_CONTEXT.get()
    if context is not None:
        _MODEL_CALL_CONTEXT.set(
            ModelCallContext(
                run_id=context.run_id,
                recorder=context.recorder,
                role=context.role,
                branch_id=context.branch_id,
                input_unit_ids=context.input_unit_ids,
                stage=stage,
            )
        )


@dataclass
class _CircuitState:
    open_until: float = 0
    reason: str = ""


class OpenAICompatibleClient:
    supports_multimodal = False
    _shared_clients: dict[tuple[str, str, float], httpx.AsyncClient] = {}
    _shared_clients_lock = threading.Lock()
    _circuit_states: dict[tuple[str, str], _CircuitState] = {}
    _circuit_states_lock = threading.Lock()
    _limiters: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
    _limiters_lock = threading.Lock()

    def __init__(
        self,
        settings: Settings,
        api_key: str,
        base_url: str,
        provider_name: str,
        api_key_env_name: str,
        temperature: float,
        *,
        http_client: Any | None = None,
        max_attempts: int | None = None,
        retry_sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        retry_delay_cap_seconds: float | None = None,
        attempt_recorder: AttemptRecorder | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ):
        self.settings = settings
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.provider_name = provider_name
        self.api_key_env_name = api_key_env_name
        self.temperature = temperature
        self.max_attempts = max(
            int(max_attempts or settings.provider_max_attempts),
            1,
        )
        self.retry_sleep = retry_sleep
        configured_retry_cap = (
            retry_delay_cap_seconds
            if retry_delay_cap_seconds is not None
            else getattr(
                settings,
                "provider_retry_delay_cap_seconds",
                DEFAULT_RETRY_DELAY_CAP_SECONDS,
            )
        )
        try:
            parsed_retry_cap = float(configured_retry_cap)
        except (TypeError, ValueError):
            parsed_retry_cap = DEFAULT_RETRY_DELAY_CAP_SECONDS
        if not math.isfinite(parsed_retry_cap):
            parsed_retry_cap = DEFAULT_RETRY_DELAY_CAP_SECONDS
        self.retry_delay_cap_seconds = min(
            max(parsed_retry_cap, 0),
            HARD_RETRY_DELAY_CAP_SECONDS,
        )
        self.attempt_recorder = attempt_recorder
        self.monotonic = monotonic
        self._injected_http_client = http_client

    @property
    def _circuit_key(self) -> tuple[str, str]:
        return self.provider_name, self.base_url

    def _circuit_state(self) -> _CircuitState:
        with self._circuit_states_lock:
            return self._circuit_states.setdefault(
                self._circuit_key,
                _CircuitState(),
            )

    def _open_circuit(self, reason: str) -> None:
        state = self._circuit_state()
        state.reason = " ".join(reason.split())[:200]
        state.open_until = (
            self.monotonic()
            + self.settings.provider_circuit_cooldown_seconds
        )

    def _close_circuit(self) -> None:
        state = self._circuit_state()
        state.reason = ""
        state.open_until = 0

    def _ensure_circuit_closed(self) -> None:
        state = self._circuit_state()
        now = self.monotonic()
        if state.open_until <= now:
            if state.open_until:
                self._close_circuit()
            return
        remaining = max(int(state.open_until - now), 1)
        detail = f"：{state.reason}" if state.reason else ""
        raise ModelProviderError(
            f"{self.provider_name} 调用已熔断，约 {remaining} 秒后重试{detail}"
        )

    def _http_client(self) -> Any:
        if self._injected_http_client is not None:
            return self._injected_http_client
        key = (
            self.base_url,
            self.api_key,
            self.settings.provider_timeout_seconds,
        )
        with self._shared_clients_lock:
            client = self._shared_clients.get(key)
            if client is None or client.is_closed:
                limits = httpx.Limits(
                    max_connections=max(
                        self.settings.provider_concurrency * 2,
                        8,
                    ),
                    max_keepalive_connections=max(
                        self.settings.provider_concurrency,
                        4,
                    ),
                )
                client = httpx.AsyncClient(
                    timeout=self.settings.provider_timeout_seconds,
                    limits=limits,
                    http2=False,
                )
                self._shared_clients[key] = client
        return client

    def _limiter(self) -> asyncio.Semaphore:
        loop = asyncio.get_running_loop()
        with self._limiters_lock:
            by_limit = self._limiters.setdefault(loop, {})
            limit = max(self.settings.provider_concurrency, 1)
            limiter = by_limit.get(limit)
            if limiter is None:
                limiter = asyncio.Semaphore(limit)
                by_limit[limit] = limiter
        return limiter

    @classmethod
    async def close_shared_clients(cls) -> None:
        with cls._shared_clients_lock:
            clients = list(cls._shared_clients.values())
            cls._shared_clients.clear()
        for client in clients:
            await client.aclose()

    async def list_models(self) -> list[str]:
        if not self.api_key:
            return []
        response = await self._request(
            "get",
            f"{self.base_url}/models",
            model="",
            operation="model_list",
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        try:
            payload = response.json()
        except ValueError as exc:
            raise ModelProviderError(
                f"{self.provider_name} 模型列表不是有效 JSON"
            ) from exc
        return [
            item["id"]
            for item in payload.get("data", [])
            if item.get("id")
        ]

    async def check_model(self, model: str) -> tuple[bool, str]:
        if not self.api_key:
            return False, f"未配置 {self.api_key_env_name}"
        try:
            models = await self.list_models()
        except ModelProviderError as exc:
            return False, str(exc)
        if model in models:
            return True, f"{self.provider_name} 模型与密钥可用"
        return False, f"{self.provider_name} 账号的模型列表中没有 {model}"

    async def extract(self, chunk: Chunk, model: str) -> ChunkExtraction:
        user_prompt = (
            f"章节：{chunk.heading or '未标注'}\n"
            f"位置：第 {chunk.index + 1} 个文本块\n\n"
            f"原文：\n{chunk.text}"
        )
        content = await self._chat(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=6000,
            json_mode=True,
        )
        return ChunkExtraction.model_validate(self._parse_json(content))

    async def complete_json(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 6000,
        max_completion_tokens: int | None = None,
        max_attempts: int | None = None,
        reasoning_effort: str | None = None,
        thinking_budget: int | None = None,
        timeout_seconds: float | None = None,
        enable_search: bool = False,
        accept_complete_json_on_length: bool = False,
        stream_callback: ModelStreamCallback | None = None,
    ) -> dict[str, Any]:
        content = await self._chat(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=max_tokens,
            max_completion_tokens=max_completion_tokens,
            json_mode=True,
            max_attempts=max_attempts,
            reasoning_effort=reasoning_effort,
            thinking_budget=thinking_budget,
            timeout_seconds=timeout_seconds,
            enable_search=enable_search,
            accept_complete_json_on_length=accept_complete_json_on_length,
            stream_callback=stream_callback,
        )
        return self._parse_json(content)

    async def complete_multimodal_json(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        image_data_url: str,
        max_tokens: int = 5000,
        max_completion_tokens: int | None = None,
        max_attempts: int | None = None,
        reasoning_effort: str | None = None,
        thinking_budget: int | None = None,
        timeout_seconds: float | None = None,
        accept_complete_json_on_length: bool = False,
        stream_callback: ModelStreamCallback | None = None,
    ) -> dict[str, Any]:
        content = await self._chat(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": image_data_url},
                        },
                    ],
                },
            ],
            max_tokens=max_tokens,
            max_completion_tokens=max_completion_tokens,
            json_mode=True,
            max_attempts=max_attempts,
            reasoning_effort=reasoning_effort,
            thinking_budget=thinking_budget,
            timeout_seconds=timeout_seconds,
            accept_complete_json_on_length=accept_complete_json_on_length,
            stream_callback=stream_callback,
        )
        return self._parse_json(content)

    async def complete_multi_image_json(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        images: Sequence[tuple[str, str]],
        cache_static_images: bool = False,
        use_response_format: bool = True,
        max_tokens: int = 5000,
        max_completion_tokens: int | None = None,
        max_attempts: int | None = None,
        reasoning_effort: str | None = None,
        thinking_budget: int | None = None,
        timeout_seconds: float | None = None,
        accept_complete_json_on_length: bool = False,
        stream_callback: ModelStreamCallback | None = None,
    ) -> dict[str, Any]:
        if not images:
            raise ValueError("multi-image completion requires at least one image")
        user_content: list[dict[str, Any]] = []
        if not cache_static_images:
            user_content.append({"type": "text", "text": user_prompt})
        for vision_id, image_data_url in images:
            label = str(vision_id).strip()
            if not label:
                raise ValueError("multi-image completion requires image labels")
            user_content.extend(
                [
                    {
                        "type": "text",
                        "text": f"vision_id={label}",
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": image_data_url},
                    },
                ]
            )
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt}
        ]
        if cache_static_images:
            user_content.append(
                {
                    "type": "text",
                    "text": (
                        "以上是按 vision_id 顺序排列的原始幻灯片，"
                        "后续动态审稿请求均以这组图片为准。"
                    ),
                }
            )
            messages.extend(
                [
                    {"role": "user", "content": user_content},
                    {"role": "user", "content": user_prompt},
                ]
            )
        else:
            messages.append({"role": "user", "content": user_content})
        content = await self._chat(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            max_completion_tokens=max_completion_tokens,
            json_mode=use_response_format,
            max_attempts=max_attempts,
            reasoning_effort=reasoning_effort,
            thinking_budget=thinking_budget,
            timeout_seconds=timeout_seconds,
            accept_complete_json_on_length=accept_complete_json_on_length,
            stream_callback=stream_callback,
        )
        return self._parse_json(content)

    async def complete_response_json(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        images: Sequence[tuple[str, str]] = (),
        previous_response_id: str | None = None,
        session_cache: bool = False,
        max_attempts: int | None = None,
        reasoning_effort: str | None = None,
        max_output_tokens: int | None = None,
        timeout_seconds: float | None = None,
        accept_complete_json_on_length: bool = False,
        stream_callback: ModelStreamCallback | None = None,
    ) -> StoredResponseJSON:
        if not self.api_key:
            raise ModelProviderError(f"未配置 {self.api_key_env_name}")
        if session_cache and self.provider_name.casefold() != "qwen":
            raise ValueError("session cache is only supported for Qwen")
        if reasoning_effort not in RESPONSE_REASONING_EFFORTS | {None}:
            raise ValueError("unsupported Responses reasoning effort")

        image_content: list[dict[str, Any]] = []
        has_oss_resource = False
        for vision_id, image_url in images:
            label = str(vision_id).strip()
            resolved_url = str(image_url).strip()
            if not label or not resolved_url:
                raise ValueError("Responses images require labels and URLs")
            if resolved_url.casefold().startswith("data:"):
                raise ValueError(
                    "Responses image context requires stable URLs, not data URIs"
                )
            has_oss_resource = (
                has_oss_resource
                or resolved_url.casefold().startswith("oss://")
            )
            image_content.extend(
                [
                    {
                        "type": "input_text",
                        "text": f"vision_id={label}",
                    },
                    {
                        "type": "input_image",
                        "image_url": resolved_url,
                    },
                ]
            )

        if images:
            image_content.append(
                {
                    "type": "input_text",
                    "text": (
                        "以上是按 vision_id 顺序排列的原始幻灯片。"
                        "后续任务必须继续以这些原图为事实依据。"
                    ),
                }
            )
            response_input: str | list[dict[str, Any]] = [
                {
                    "role": "user",
                    "content": image_content,
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": user_prompt,
                        }
                    ],
                },
            ]
        else:
            response_input = user_prompt

        payload: dict[str, Any] = {
            "model": model,
            "instructions": system_prompt,
            "input": response_input,
            "store": True,
            "temperature": self.temperature,
        }
        if previous_response_id:
            payload["previous_response_id"] = previous_response_id
        if reasoning_effort is not None:
            payload["reasoning"] = {"effort": reasoning_effort}
        if max_output_tokens is not None:
            parsed_max_output_tokens = int(max_output_tokens)
            if (
                parsed_max_output_tokens < 16
                or parsed_max_output_tokens != max_output_tokens
            ):
                raise ValueError(
                    "max_output_tokens must be an integer of at least 16"
                )
            payload["max_output_tokens"] = parsed_max_output_tokens

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if session_cache:
            headers["x-dashscope-session-cache"] = "enable"
        if has_oss_resource:
            headers["X-DashScope-OssResourceResolve"] = "enable"

        request_timeout = self._normalize_timeout(timeout_seconds)
        if stream_callback is not None:
            return await self._complete_response_json_stream(
                model=model,
                payload=payload,
                headers=headers,
                image_count=len(images),
                prompt_chars=len(system_prompt) + len(user_prompt),
                session_cache=session_cache,
                max_attempts=max_attempts,
                request_timeout=request_timeout,
                accept_complete_json_on_length=(
                    accept_complete_json_on_length
                ),
                stream_callback=stream_callback,
            )
        request_kwargs: dict[str, Any] = {}
        if request_timeout is not None:
            request_kwargs["timeout"] = request_timeout
        response = await self._request(
            "post",
            f"{self.base_url}/responses",
            model=model,
            operation="response_completion",
            headers=headers,
            json=payload,
            max_attempts=max_attempts,
            telemetry=self._responses_request_telemetry(
                payload=payload,
                image_count=len(images),
                prompt_chars=len(system_prompt) + len(user_prompt),
                session_cache=session_cache,
                timeout_seconds=request_timeout,
            ),
            total_timeout_seconds=request_timeout,
            **request_kwargs,
        )
        try:
            response_payload = response.json()
        except ValueError as exc:
            raise ModelProviderError(
                f"{self.provider_name} Responses 响应不是有效 JSON"
            ) from exc
        if not isinstance(response_payload, dict):
            raise ModelProviderError(
                f"{self.provider_name} Responses 响应格式无效"
            )

        response_id = response_payload.get("id")
        status = response_payload.get("status")
        if not isinstance(response_id, str) or not response_id.strip():
            raise ModelProviderError(
                f"{self.provider_name} Responses 响应缺少 id"
            )
        if status not in SAFE_RESPONSE_STATUSES:
            raise ModelProviderError(
                f"{self.provider_name} Responses 响应缺少有效状态"
            )

        content = self._responses_output_text(response_payload)
        if status != "completed":
            if (
                status == "incomplete"
                and accept_complete_json_on_length
                and content
            ):
                parsed = self._parse_json(content)
            else:
                raise ModelProviderError(
                    f"{self.provider_name} Responses 响应未完成"
                )
        else:
            if not content:
                raise ModelProviderError(
                    f"{self.provider_name} Responses 返回了空输出"
                )
            parsed = self._parse_json(content)

        return StoredResponseJSON(
            payload=parsed,
            response_id=response_id,
            status=status,
            usage=self._numeric_usage(response_payload.get("usage")),
        )

    def _chat_payload(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        max_tokens: int,
        json_mode: bool,
        reasoning_effort: str | None = None,
        thinking_budget: int | None = None,
        max_completion_tokens: int | None = None,
        enable_search: bool = False,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": self.temperature,
        }
        if max_completion_tokens is None:
            payload["max_tokens"] = max_tokens
        else:
            completion_budget = int(max_completion_tokens)
            if completion_budget < 1:
                raise ValueError("max_completion_tokens must be positive")
            payload["max_completion_tokens"] = completion_budget
        if reasoning_effort and thinking_budget is not None:
            raise ValueError(
                "reasoning_effort and thinking_budget are mutually exclusive"
            )
        if reasoning_effort:
            payload["reasoning_effort"] = reasoning_effort
        if thinking_budget is not None:
            if isinstance(thinking_budget, bool):
                raise ValueError("thinking_budget must be a non-negative integer")
            parsed_thinking_budget = int(thinking_budget)
            if (
                parsed_thinking_budget < 0
                or parsed_thinking_budget != thinking_budget
            ):
                raise ValueError(
                    "thinking_budget must be a non-negative integer"
                )
            if not (
                self.provider_name.casefold() == "qwen"
                and parsed_thinking_budget == 0
            ):
                payload["thinking_budget"] = parsed_thinking_budget
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if enable_search:
            if self.provider_name.casefold() != "qwen":
                raise ValueError("enable_search is only supported for Qwen")
            payload["enable_search"] = True
        return payload

    async def _chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        max_tokens: int,
        json_mode: bool,
        max_attempts: int | None = None,
        reasoning_effort: str | None = None,
        thinking_budget: int | None = None,
        max_completion_tokens: int | None = None,
        timeout_seconds: float | None = None,
        enable_search: bool = False,
        accept_complete_json_on_length: bool = False,
        stream_callback: ModelStreamCallback | None = None,
    ) -> str:
        if not self.api_key:
            raise ModelProviderError(f"未配置 {self.api_key_env_name}")
        request_timeout = self._normalize_timeout(timeout_seconds)
        payload = self._chat_payload(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            json_mode=json_mode,
            reasoning_effort=reasoning_effort,
            thinking_budget=thinking_budget,
            max_completion_tokens=max_completion_tokens,
            enable_search=enable_search,
        )
        headers = self._chat_headers(messages)
        if stream_callback is not None:
            return await self._chat_stream(
                model=model,
                payload=payload,
                messages=messages,
                headers=headers,
                max_attempts=max_attempts,
                request_timeout=request_timeout,
                json_mode=json_mode,
                accept_complete_json_on_length=(
                    accept_complete_json_on_length
                ),
                stream_callback=stream_callback,
            )
        request_kwargs: dict[str, Any] = {}
        if request_timeout is not None:
            request_kwargs["timeout"] = request_timeout
        response = await self._request(
            "post",
            f"{self.base_url}/chat/completions",
            model=model,
            operation="chat_completion",
            headers=headers,
            json=payload,
            max_attempts=max_attempts,
            telemetry=self._chat_request_telemetry(
                payload=payload,
                messages=messages,
                timeout_seconds=request_timeout,
            ),
            total_timeout_seconds=request_timeout,
            **request_kwargs,
        )

        try:
            response_payload = response.json()
        except ValueError as exc:
            raise ModelProviderError(
                f"{self.provider_name} 响应不是有效 JSON"
            ) from exc
        try:
            choice = response_payload["choices"][0]
            finish_reason = choice.get("finish_reason")
            content = choice["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelProviderError(
                f"{self.provider_name} 响应中没有可解析的输出"
            ) from exc
        if finish_reason is not None and finish_reason != "stop":
            if finish_reason == "length":
                if (
                    json_mode
                    and accept_complete_json_on_length
                    and isinstance(content, str)
                ):
                    try:
                        self._parse_json(content)
                    except ModelProviderError:
                        pass
                    else:
                        return content
                raise ModelProviderError(
                    f"{self.provider_name} 响应因输出长度限制被截断"
                )
            raise ModelProviderError(
                f"{self.provider_name} 响应未正常结束"
            )
        if not isinstance(content, str) or not content.strip():
            raise ModelProviderError(f"{self.provider_name} 返回了空输出")
        return content

    async def _chat_stream(
        self,
        *,
        model: str,
        payload: dict[str, Any],
        messages: list[dict[str, Any]],
        headers: dict[str, str],
        max_attempts: int | None,
        request_timeout: float | None,
        json_mode: bool,
        accept_complete_json_on_length: bool,
        stream_callback: ModelStreamCallback,
    ) -> str:
        stream_payload = {**payload, "stream": True}
        content_parts: list[str] = []
        finish_reason: str | None = None

        async def handle_event(event: dict[str, Any]) -> None:
            nonlocal finish_reason
            error_message = self._stream_error_message(event)
            if error_message:
                raise ModelProviderError(error_message)
            choices = event.get("choices")
            if not isinstance(choices, list) or not choices:
                return
            choice = choices[0]
            if not isinstance(choice, dict):
                return
            candidate_finish_reason = choice.get("finish_reason")
            if isinstance(candidate_finish_reason, str):
                finish_reason = candidate_finish_reason
            delta = choice.get("delta")
            if not isinstance(delta, dict):
                return
            fragment = self._stream_delta_text(delta.get("content"))
            if not fragment:
                return
            content_parts.append(fragment)
            await self._emit_stream_delta(stream_callback, fragment)

        await self._stream_json_events(
            "post",
            f"{self.base_url}/chat/completions",
            model=model,
            operation="chat_completion_stream",
            headers=headers,
            json=stream_payload,
            max_attempts=max_attempts,
            telemetry=self._chat_request_telemetry(
                payload=stream_payload,
                messages=messages,
                timeout_seconds=request_timeout,
            ),
            event_idle_timeout_seconds=request_timeout,
            event_handler=handle_event,
            timeout=request_timeout,
        )
        content = "".join(content_parts)
        if finish_reason is not None and finish_reason != "stop":
            if finish_reason == "length":
                if json_mode and accept_complete_json_on_length and content:
                    try:
                        self._parse_json(content)
                    except ModelProviderError:
                        pass
                    else:
                        return content
                raise ModelProviderError(
                    f"{self.provider_name} 响应因输出长度限制被截断"
                )
            raise ModelProviderError(
                f"{self.provider_name} 响应未正常结束"
            )
        if not content.strip():
            raise ModelProviderError(f"{self.provider_name} 返回了空输出")
        return content

    async def _complete_response_json_stream(
        self,
        *,
        model: str,
        payload: dict[str, Any],
        headers: dict[str, str],
        image_count: int,
        prompt_chars: int,
        session_cache: bool,
        max_attempts: int | None,
        request_timeout: float | None,
        accept_complete_json_on_length: bool,
        stream_callback: ModelStreamCallback,
    ) -> StoredResponseJSON:
        stream_payload = {**payload, "stream": True}
        content_parts: list[str] = []
        response_payload: dict[str, Any] = {}
        response_id = ""
        status = ""

        async def handle_event(event: dict[str, Any]) -> None:
            nonlocal response_id, response_payload, status
            event_type = event.get("type")
            if event_type == "response.output_text.delta":
                delta = event.get("delta")
                if isinstance(delta, str) and delta:
                    content_parts.append(delta)
                    await self._emit_stream_delta(stream_callback, delta)
                return
            error_message = self._stream_error_message(event)
            if error_message:
                raise ModelProviderError(error_message)
            candidate = event.get("response")
            if not isinstance(candidate, dict):
                return
            candidate_id = candidate.get("id")
            candidate_status = candidate.get("status")
            if isinstance(candidate_id, str):
                response_id = candidate_id
            if isinstance(candidate_status, str):
                status = candidate_status
            if event_type in {
                "response.completed",
                "response.failed",
                "response.incomplete",
            }:
                response_payload = candidate

        await self._stream_json_events(
            "post",
            f"{self.base_url}/responses",
            model=model,
            operation="response_completion_stream",
            headers=headers,
            json=stream_payload,
            max_attempts=max_attempts,
            telemetry=self._responses_request_telemetry(
                payload=stream_payload,
                image_count=image_count,
                prompt_chars=prompt_chars,
                session_cache=session_cache,
                timeout_seconds=request_timeout,
            ),
            event_idle_timeout_seconds=request_timeout,
            event_handler=handle_event,
            timeout=request_timeout,
        )

        if response_payload:
            response_id = str(response_payload.get("id") or response_id)
            status = str(response_payload.get("status") or status)
        if not response_id.strip():
            raise ModelProviderError(
                f"{self.provider_name} Responses 响应缺少 id"
            )
        if status not in SAFE_RESPONSE_STATUSES:
            raise ModelProviderError(
                f"{self.provider_name} Responses 响应缺少有效状态"
            )
        content = "".join(content_parts)
        if not content:
            content = self._responses_output_text(response_payload)
        if status != "completed":
            if (
                status == "incomplete"
                and accept_complete_json_on_length
                and content
            ):
                parsed = self._parse_json(content)
            else:
                raise ModelProviderError(
                    f"{self.provider_name} Responses 响应未完成"
                )
        else:
            if not content:
                raise ModelProviderError(
                    f"{self.provider_name} Responses 返回了空输出"
                )
            parsed = self._parse_json(content)
        return StoredResponseJSON(
            payload=parsed,
            response_id=response_id,
            status=status,
            usage=self._numeric_usage(response_payload.get("usage")),
        )

    async def _stream_json_events(
        self,
        method: str,
        url: str,
        *,
        model: str,
        operation: str,
        event_handler: StreamEventHandler,
        max_attempts: int | None = None,
        telemetry: dict[str, Any] | None = None,
        event_idle_timeout_seconds: float | None = None,
        **kwargs: Any,
    ) -> None:
        self._ensure_circuit_closed()
        safe_telemetry = dict(telemetry or {})
        event_idle_timeout = self._normalize_timeout(
            event_idle_timeout_seconds
            if event_idle_timeout_seconds is not None
            else self.settings.provider_timeout_seconds
        )
        safe_telemetry["timeout_mode"] = "stream_event_idle"
        safe_telemetry["stream_event_idle_timeout_seconds"] = (
            event_idle_timeout
        )
        attempt_limit = (
            self.max_attempts
            if max_attempts is None
            else max(int(max_attempts), 1)
        )
        logical_call_id = uuid.uuid4().hex[:16]
        last_error = ""
        for attempt in range(1, attempt_limit + 1):
            started = self.monotonic()
            response: httpx.Response | None = None
            event_count = 0
            try:
                async with self._limiter():
                    async with self._http_client().stream(
                        method,
                        url,
                        **kwargs,
                    ) as response:
                        if not response.is_error:
                            stream_done = object()

                            async def parsed_events():
                                data_lines: list[str] = []

                                def parse_event() -> (
                                    dict[str, Any] | object | None
                                ):
                                    if not data_lines:
                                        return None
                                    raw = "\n".join(data_lines)
                                    data_lines.clear()
                                    if raw.strip() == "[DONE]":
                                        return stream_done
                                    try:
                                        payload = json.loads(raw)
                                    except ValueError as exc:
                                        raise ModelProviderError(
                                            f"{self.provider_name} 流式响应"
                                            "包含无效 JSON"
                                        ) from exc
                                    if not isinstance(payload, dict):
                                        raise ModelProviderError(
                                            f"{self.provider_name} 流式响应"
                                            "事件格式无效"
                                        )
                                    return payload

                                async for line in response.aiter_lines():
                                    if line == "":
                                        payload = parse_event()
                                        if payload is stream_done:
                                            yield stream_done
                                            return
                                        if payload is not None:
                                            yield payload
                                    elif line.startswith("data:"):
                                        data_lines.append(
                                            line[5:].lstrip(" ")
                                        )
                                payload = parse_event()
                                if payload is not None:
                                    yield payload

                            events = parsed_events().__aiter__()
                            while True:
                                try:
                                    async with asyncio.timeout(
                                        event_idle_timeout
                                    ):
                                        payload = await anext(events)
                                except StopAsyncIteration:
                                    break
                                if payload is stream_done:
                                    break
                                if not isinstance(payload, dict):
                                    raise ModelProviderError(
                                        f"{self.provider_name} 流式响应"
                                        "事件格式无效"
                                    )
                                event_count += 1
                                await event_handler(payload)
                        else:
                            await response.aread()
            except TimeoutError as exc:
                last_error = (
                    f"{self.provider_name} 连续 "
                    f"{event_idle_timeout:g} 秒未收到流式事件"
                )
                await self._record_attempt(
                    logical_call_id=logical_call_id,
                    attempt=attempt,
                    model=model,
                    operation=operation,
                    status="retryable_error",
                    latency_ms=self._latency_ms(started),
                    max_attempts=attempt_limit,
                    details={
                        **safe_telemetry,
                        "error_type": "stream_idle_timeout",
                        "stream_event_count": event_count,
                    },
                )
                raise ModelProviderError(last_error) from exc
            except httpx.TimeoutException as exc:
                last_error = f"{self.provider_name} 请求超时"
                await self._record_attempt(
                    logical_call_id=logical_call_id,
                    attempt=attempt,
                    model=model,
                    operation=operation,
                    status="retryable_error",
                    latency_ms=self._latency_ms(started),
                    max_attempts=attempt_limit,
                    details={
                        **safe_telemetry,
                        "error_type": "timeout",
                        "stream_event_count": event_count,
                    },
                )
                if event_count or attempt >= attempt_limit:
                    raise ModelProviderError(last_error) from exc
                await self.retry_sleep(self._backoff(attempt))
                continue
            except httpx.HTTPError as exc:
                error_type = exc.__class__.__name__
                last_error = (
                    f"{self.provider_name} 传输失败"
                    f"（{error_type}）"
                )
                await self._record_attempt(
                    logical_call_id=logical_call_id,
                    attempt=attempt,
                    model=model,
                    operation=operation,
                    status="transport_error",
                    latency_ms=self._latency_ms(started),
                    max_attempts=attempt_limit,
                    details={
                        **safe_telemetry,
                        "error_type": error_type,
                        "stream_event_count": event_count,
                    },
                )
                raise ModelProviderError(last_error) from exc
            except ModelProviderError as exc:
                await self._record_attempt(
                    logical_call_id=logical_call_id,
                    attempt=attempt,
                    model=model,
                    operation=operation,
                    status="permanent_error",
                    latency_ms=self._latency_ms(started),
                    max_attempts=attempt_limit,
                    details={
                        **safe_telemetry,
                        "error_type": "stream_event",
                        "stream_event_count": event_count,
                    },
                )
                raise

            if response is not None and not response.is_error:
                self._close_circuit()
                await self._record_attempt(
                    logical_call_id=logical_call_id,
                    attempt=attempt,
                    model=model,
                    operation=operation,
                    status="success",
                    latency_ms=self._latency_ms(started),
                    max_attempts=attempt_limit,
                    details={
                        **safe_telemetry,
                        "status_code": response.status_code,
                        "stream_event_count": event_count,
                    },
                )
                return
            if response is None:
                last_error = f"{self.provider_name} 流式请求没有响应"
                break

            (
                last_error,
                provider_error_context,
                error_code,
            ) = self._http_error_details(response)
            retryable = self._is_retryable(response)
            permanent = self._is_permanent(
                response,
                provider_error_context,
            )
            error_details: dict[str, Any] = {
                **safe_telemetry,
                "status_code": response.status_code,
                "stream_event_count": event_count,
            }
            if error_code is not None:
                error_details["error_code"] = error_code
            await self._record_attempt(
                logical_call_id=logical_call_id,
                attempt=attempt,
                model=model,
                operation=operation,
                status=(
                    "retryable_error"
                    if retryable and not permanent
                    else "permanent_error"
                ),
                latency_ms=self._latency_ms(started),
                max_attempts=attempt_limit,
                details=error_details,
            )
            if permanent:
                if self._should_open_circuit(
                    response,
                    provider_error_context,
                ):
                    self._open_circuit(last_error)
                raise ModelProviderError(last_error)
            if not retryable or attempt >= attempt_limit:
                break
            await self.retry_sleep(self._retry_delay(response, attempt))

        raise ModelProviderError(
            f"{self.provider_name} 请求失败（已尝试 "
            f"{attempt_limit} 次）：{last_error or '未知错误'}"
        )

    def _chat_headers(
        self,
        messages: Sequence[dict[str, Any]],
    ) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if self.provider_name.casefold() != "qwen":
            return headers
        for message in messages:
            content = message.get("content")
            if not isinstance(content, list):
                continue
            for item in content:
                if not isinstance(item, dict):
                    continue
                image = item.get("image_url")
                if not isinstance(image, dict):
                    continue
                url = image.get("url")
                if isinstance(url, str) and url.casefold().startswith(
                    "oss://"
                ):
                    headers["X-DashScope-OssResourceResolve"] = "enable"
                    return headers
        return headers

    def _stream_error_message(self, payload: dict[str, Any]) -> str:
        error = payload.get("error")
        event_type = payload.get("type")
        if not error and event_type != "error":
            return ""
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str) and message.strip():
                return f"{self.provider_name} 流式响应失败：{message.strip()}"
        if isinstance(error, str) and error.strip():
            return f"{self.provider_name} 流式响应失败：{error.strip()}"
        return f"{self.provider_name} 流式响应失败"

    @staticmethod
    async def _emit_stream_delta(
        callback: ModelStreamCallback,
        delta: str,
    ) -> None:
        outcome = callback(delta)
        if inspect.isawaitable(outcome):
            await outcome

    @staticmethod
    def _stream_delta_text(value: Any) -> str:
        if isinstance(value, str):
            return value
        if not isinstance(value, list):
            return ""
        parts: list[str] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            if isinstance(text, str):
                parts.append(text)
        return "".join(parts)

    async def _request(
        self,
        method: str,
        url: str,
        *,
        model: str,
        operation: str,
        max_attempts: int | None = None,
        telemetry: dict[str, Any] | None = None,
        total_timeout_seconds: float | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        self._ensure_circuit_closed()
        safe_telemetry = dict(telemetry or {})
        absolute_timeout = self._normalize_timeout(
            total_timeout_seconds
            if total_timeout_seconds is not None
            else self.settings.provider_timeout_seconds
        )
        attempt_limit = (
            self.max_attempts
            if max_attempts is None
            else max(int(max_attempts), 1)
        )
        logical_call_id = uuid.uuid4().hex[:16]
        last_error = ""
        for attempt in range(1, attempt_limit + 1):
            started = self.monotonic()
            response: httpx.Response | None = None
            try:
                async with asyncio.timeout(absolute_timeout):
                    async with self._limiter():
                        response = await getattr(
                            self._http_client(),
                            method,
                        )(
                            url,
                            **kwargs,
                        )
            except (httpx.TimeoutException, TimeoutError) as exc:
                last_error = f"{self.provider_name} 请求超时"
                await self._record_attempt(
                    logical_call_id=logical_call_id,
                    attempt=attempt,
                    model=model,
                    operation=operation,
                    status="retryable_error",
                    latency_ms=self._latency_ms(started),
                    max_attempts=attempt_limit,
                    details={
                        **safe_telemetry,
                        "error_type": "timeout",
                    },
                )
                if attempt >= attempt_limit:
                    break
                await self.retry_sleep(self._backoff(attempt))
                continue
            except httpx.HTTPError as exc:
                error_type = exc.__class__.__name__
                last_error = (
                    f"{self.provider_name} 传输失败"
                    f"（{error_type}）"
                )
                await self._record_attempt(
                    logical_call_id=logical_call_id,
                    attempt=attempt,
                    model=model,
                    operation=operation,
                    status="transport_error",
                    latency_ms=self._latency_ms(started),
                    max_attempts=attempt_limit,
                    details={
                        **safe_telemetry,
                        "error_type": error_type,
                    },
                )
                raise ModelProviderError(last_error) from exc

            if not response.is_error:
                self._close_circuit()
                await self._record_attempt(
                    logical_call_id=logical_call_id,
                    attempt=attempt,
                    model=model,
                    operation=operation,
                    status="success",
                    latency_ms=self._latency_ms(started),
                    max_attempts=attempt_limit,
                    details={
                        **safe_telemetry,
                        **self._response_telemetry(response),
                        "status_code": response.status_code,
                    },
                )
                return response

            (
                last_error,
                provider_error_context,
                error_code,
            ) = self._http_error_details(response)
            retryable = self._is_retryable(response)
            permanent = self._is_permanent(
                response,
                provider_error_context,
            )
            error_details: dict[str, Any] = {
                **safe_telemetry,
                "status_code": response.status_code,
            }
            if error_code is not None:
                error_details["error_code"] = error_code
            await self._record_attempt(
                logical_call_id=logical_call_id,
                attempt=attempt,
                model=model,
                operation=operation,
                status=(
                    "retryable_error"
                    if retryable and not permanent
                    else "permanent_error"
                ),
                latency_ms=self._latency_ms(started),
                max_attempts=attempt_limit,
                details=error_details,
            )
            if permanent:
                if self._should_open_circuit(
                    response,
                    provider_error_context,
                ):
                    self._open_circuit(last_error)
                raise ModelProviderError(last_error)
            if not retryable or attempt >= attempt_limit:
                break
            await self.retry_sleep(
                self._retry_delay(response, attempt)
            )

        raise ModelProviderError(
            f"{self.provider_name} 请求失败（已尝试 "
            f"{attempt_limit} 次）：{last_error or '未知错误'}"
        )

    @staticmethod
    def _normalize_timeout(
        timeout_seconds: float | None,
    ) -> float | None:
        if timeout_seconds is None:
            return None
        if isinstance(timeout_seconds, bool):
            raise ValueError("timeout_seconds must be a positive number")
        try:
            parsed = float(timeout_seconds)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "timeout_seconds must be a positive number"
            ) from exc
        if not math.isfinite(parsed) or parsed <= 0:
            raise ValueError("timeout_seconds must be a positive number")
        return parsed

    def _chat_request_telemetry(
        self,
        *,
        payload: dict[str, Any],
        messages: list[dict[str, Any]],
        timeout_seconds: float | None,
    ) -> dict[str, Any]:
        prompt_chars = 0
        image_count = 0
        for message in messages:
            content = message.get("content")
            if isinstance(content, str):
                prompt_chars += len(content)
                continue
            if not isinstance(content, list):
                continue
            for item in content:
                if not isinstance(item, dict):
                    continue
                if item.get("type") == "text":
                    text = item.get("text")
                    if isinstance(text, str):
                        prompt_chars += len(text)
                elif item.get("type") == "image_url":
                    image_count += 1

        request_policy: dict[str, Any] = {
            "message_count": len(messages),
            "prompt_chars": prompt_chars,
            "image_count": image_count,
            "timeout_seconds": (
                timeout_seconds
                if timeout_seconds is not None
                else float(self.settings.provider_timeout_seconds)
            ),
        }
        for field in ("max_tokens", "max_completion_tokens"):
            value = payload.get(field)
            if self._is_finite_number(value):
                request_policy[field] = value
        reasoning_effort = payload.get("reasoning_effort")
        if reasoning_effort in {"low", "medium", "high", "xhigh"}:
            request_policy["reasoning_effort"] = reasoning_effort
        thinking_budget = payload.get("thinking_budget")
        if self._is_finite_number(thinking_budget):
            request_policy["thinking_budget"] = thinking_budget
        return {"request_policy": request_policy}

    def _responses_request_telemetry(
        self,
        *,
        payload: dict[str, Any],
        image_count: int,
        prompt_chars: int,
        session_cache: bool,
        timeout_seconds: float | None,
    ) -> dict[str, Any]:
        reasoning = payload.get("reasoning")
        reasoning_effort = (
            reasoning.get("effort")
            if isinstance(reasoning, dict)
            else None
        )
        request_policy: dict[str, Any] = {
            "prompt_chars": prompt_chars,
            "image_count": image_count,
            "previous_response_id_present": bool(
                payload.get("previous_response_id")
            ),
            "session_cache_enabled": session_cache,
            "store": payload.get("store") is True,
            "timeout_seconds": (
                timeout_seconds
                if timeout_seconds is not None
                else float(self.settings.provider_timeout_seconds)
            ),
        }
        if reasoning_effort in RESPONSE_REASONING_EFFORTS:
            request_policy["reasoning_effort"] = reasoning_effort
        max_output_tokens = payload.get("max_output_tokens")
        if self._is_finite_number(max_output_tokens):
            request_policy["max_output_tokens"] = max_output_tokens
        return {"request_policy": request_policy}

    @classmethod
    def _response_telemetry(
        cls,
        response: httpx.Response,
    ) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError:
            return {}
        if not isinstance(payload, dict):
            return {}

        telemetry: dict[str, Any] = {}
        usage = cls._numeric_usage(payload.get("usage"))
        if usage:
            telemetry["usage"] = usage

        response_status = payload.get("status")
        if response_status in SAFE_RESPONSE_STATUSES:
            telemetry["response_status"] = response_status

        choices = payload.get("choices")
        if isinstance(choices, list) and choices:
            first_choice = choices[0]
            if isinstance(first_choice, dict):
                finish_reason = first_choice.get("finish_reason")
                if (
                    isinstance(finish_reason, str)
                    and finish_reason in SAFE_FINISH_REASONS
                ):
                    telemetry["finish_reason"] = finish_reason
        return telemetry

    @classmethod
    def _numeric_usage(cls, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {}
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            if not (
                isinstance(key, str)
                and re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,63}", key)
            ):
                continue
            if cls._is_finite_number(item):
                sanitized[key] = item
                continue
            nested = cls._numeric_usage(item)
            if nested:
                sanitized[key] = nested
        return sanitized

    @staticmethod
    def _responses_output_text(payload: dict[str, Any]) -> str:
        direct = payload.get("output_text")
        if isinstance(direct, str) and direct.strip():
            return direct

        parts: list[str] = []
        output = payload.get("output")
        if not isinstance(output, list):
            return ""
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if isinstance(content, str):
                parts.append(content)
                continue
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") != "output_text":
                    continue
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts).strip()

    @staticmethod
    def _is_finite_number(value: Any) -> bool:
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
        )

    def _latency_ms(self, started: float) -> int:
        return max(int((self.monotonic() - started) * 1000), 0)

    def _backoff(self, attempt: int) -> float:
        try:
            delay = self.settings.provider_retry_base_seconds * (
                2 ** max(attempt - 1, 0)
            )
        except OverflowError:
            delay = self.retry_delay_cap_seconds
        return self._bounded_retry_delay(delay)

    def _bounded_retry_delay(self, delay: float) -> float:
        if not math.isfinite(delay):
            return self.retry_delay_cap_seconds
        return min(max(delay, 0), self.retry_delay_cap_seconds)

    def _retry_delay(
        self,
        response: httpx.Response,
        attempt: int,
    ) -> float:
        retry_after = response.headers.get("Retry-After", "").strip()
        if retry_after:
            try:
                return self._bounded_retry_delay(float(retry_after))
            except ValueError:
                try:
                    retry_at = parsedate_to_datetime(retry_after)
                    if retry_at.tzinfo is None:
                        retry_at = retry_at.replace(tzinfo=UTC)
                    return self._bounded_retry_delay(
                        (retry_at - datetime.now(UTC)).total_seconds(),
                    )
                except (TypeError, ValueError, OverflowError):
                    pass
        return self._backoff(attempt)

    @staticmethod
    def _is_retryable(response: httpx.Response) -> bool:
        return response.status_code == 429 or response.status_code >= 500

    @staticmethod
    def _is_permanent(response: httpx.Response, message: str) -> bool:
        normalized = message.casefold()
        balance_markers = (
            "balance",
            "insufficient",
            "quota exhausted",
            "billing",
            "余额",
            "额度不足",
            "欠费",
        )
        if any(marker in normalized for marker in balance_markers):
            return True
        return 400 <= response.status_code < 500 and response.status_code != 429

    @staticmethod
    def _should_open_circuit(
        response: httpx.Response,
        message: str,
    ) -> bool:
        """Only account/endpoint-wide failures should block unrelated calls."""

        normalized = message.casefold()
        account_markers = (
            "api key",
            "unauthorized",
            "forbidden",
            "authentication",
            "balance",
            "insufficient",
            "quota exhausted",
            "billing",
            "鉴权",
            "密钥",
            "余额",
            "额度不足",
            "欠费",
        )
        return response.status_code in {401, 402, 403} or any(
            marker in normalized for marker in account_markers
        )

    async def _record_attempt(
        self,
        *,
        logical_call_id: str,
        attempt: int,
        model: str,
        operation: str,
        status: str,
        latency_ms: int,
        max_attempts: int,
        details: dict[str, Any],
    ) -> None:
        context = _MODEL_CALL_CONTEXT.get()
        record = {
            "run_id": context.run_id if context else "",
            "item_id": f"{logical_call_id}:attempt-{attempt}",
            "branch_id": context.branch_id if context else None,
            "provider": self.provider_name,
            "model": model,
            "role": (
                context.stage
                if context and context.stage
                else context.role
                if context
                else operation
            ),
            "status": status,
            "latency_ms": latency_ms,
            "input_unit_ids": (
                list(context.input_unit_ids)
                if context
                else []
            ),
            "details": {
                **details,
                "attempt": attempt,
                "max_attempts": max_attempts,
                "operation": operation,
            },
            # These convenience fields keep recorders and tests simple.
            "attempt": attempt,
            "operation": operation,
        }
        recorders: list[AttemptRecorder] = []
        if self.attempt_recorder:
            recorders.append(self.attempt_recorder)
        if context and context.recorder is not self.attempt_recorder:
            recorders.append(context.recorder)
        for recorder in recorders:
            outcome = recorder(record)
            if inspect.isawaitable(outcome):
                await outcome

    def _http_error_details(
        self,
        response: httpx.Response,
    ) -> tuple[str, str, str | None]:
        provider_message = ""
        error_code: str | None = None
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                message = error.get("message")
                if isinstance(message, str):
                    provider_message = message
                code = error.get("code")
                if (
                    isinstance(code, str)
                    and SAFE_PROVIDER_ERROR_CODE.fullmatch(code)
                ):
                    error_code = code
            elif isinstance(error, str):
                provider_message = error

        safe_message = (
            f"{self.provider_name} 返回 HTTP {response.status_code}"
        )
        if error_code is not None:
            safe_message += f"（code={error_code}）"
        classification_context = " ".join(
            item
            for item in (error_code or "", provider_message)
            if item
        )
        return safe_message, classification_context, error_code

    def _parse_json(self, content: str) -> dict[str, Any]:
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip())
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start >= 0 and end > start:
                try:
                    return json.loads(cleaned[start : end + 1])
                except json.JSONDecodeError as exc:
                    raise ModelProviderError(
                        f"{self.provider_name} 没有返回有效 JSON"
                    ) from exc
            raise ModelProviderError(f"{self.provider_name} 没有返回 JSON 对象")
