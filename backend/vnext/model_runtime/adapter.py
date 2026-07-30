from __future__ import annotations

import json
import math
import random
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, Generic, Protocol, TypeVar
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ValidationError

from backend.vnext.artifacts.canonical import payload_digest
from backend.vnext.contracts.common import RuntimeRole
from backend.vnext.replay.store import RecordedReplayStore


OutputT = TypeVar("OutputT", bound=BaseModel)
Sleep = Callable[[float], None]
RandomValue = Callable[[], float]
Now = Callable[[], datetime]

_CIRCUIT_ERROR_CODES = frozenset(
    {
        "authentication_error",
        "billing_hard_limit_reached",
        "insufficient_balance",
        "insufficient_quota",
        "invalid_api_key",
        "model_not_found",
        "permission_denied",
    }
)
_CIRCUIT_ERROR_MARKERS = (
    "api key",
    "authentication",
    "balance",
    "billing",
    "forbidden",
    "insufficient",
    "model not found",
    "quota exhausted",
    "unauthorized",
)
_JSON_FENCE = re.compile(
    r"^\s*```(?:json)?\s*(.*?)\s*```\s*$",
    re.IGNORECASE | re.DOTALL,
)


class ModelRuntimeError(RuntimeError):
    pass


class ProviderTimeout(ModelRuntimeError):
    pass


class ProviderTransportError(ModelRuntimeError):
    pass


class CircuitOpenError(ModelRuntimeError):
    pass


class ModelRefusalError(ModelRuntimeError):
    pass


class ReplaySequenceError(ModelRuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ProviderFailure:
    provider: str
    model_revision: str
    code: str
    retryable: bool
    circuit_opened: bool
    attempts: int


class AllProvidersFailed(ModelRuntimeError):
    def __init__(self, failures: Sequence[ProviderFailure]):
        self.failures = tuple(failures)
        summary = ", ".join(
            f"{item.provider}/{item.model_revision}:{item.code}"
            for item in self.failures
        )
        super().__init__(
            "all structured model providers failed"
            + (f": {summary}" if summary else "")
        )


@dataclass(frozen=True, slots=True)
class ProviderEndpoint:
    provider: str
    base_url: str
    model_revision: str
    model_family: str
    api_key: str | None = field(default=None, repr=False)
    timeout_seconds: float = 90.0

    def __post_init__(self) -> None:
        if not self.provider.strip():
            raise ValueError("provider name must not be empty")
        if not self.model_revision.strip():
            raise ValueError("model revision must not be empty")
        if not self.model_family.strip():
            raise ValueError("model family must not be empty")
        parsed = urlsplit(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("provider base_url must be an absolute HTTP URL")
        if (
            isinstance(self.timeout_seconds, bool)
            or not math.isfinite(self.timeout_seconds)
            or self.timeout_seconds <= 0
        ):
            raise ValueError("provider timeout_seconds must be positive")

    @property
    def chat_completions_url(self) -> str:
        normalized = self.base_url.rstrip("/")
        if normalized.endswith("/chat/completions"):
            return normalized
        return normalized + "/chat/completions"

    @property
    def circuit_key(self) -> str:
        return "\0".join(
            (self.provider, self.base_url, self.model_revision)
        )


@dataclass(frozen=True, slots=True)
class TransportResponse:
    status_code: int
    headers: Mapping[str, str]
    payload: Any


class ChatTransport(Protocol):
    def post(
        self,
        endpoint: ProviderEndpoint,
        payload: Mapping[str, Any],
    ) -> TransportResponse: ...


class HttpxChatTransport:
    """Small synchronous OpenAI-compatible HTTP transport."""

    def __init__(self, client: httpx.Client | None = None):
        self._client = client or httpx.Client()
        self._owns_client = client is None

    def post(
        self,
        endpoint: ProviderEndpoint,
        payload: Mapping[str, Any],
    ) -> TransportResponse:
        headers = {"Content-Type": "application/json"}
        if endpoint.api_key:
            headers["Authorization"] = f"Bearer {endpoint.api_key}"
        try:
            response = self._client.post(
                endpoint.chat_completions_url,
                headers=headers,
                json=payload,
                timeout=endpoint.timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise ProviderTimeout("provider request timed out") from exc
        except httpx.TransportError as exc:
            raise ProviderTransportError(
                f"provider transport failed: {type(exc).__name__}"
            ) from exc
        try:
            response_payload: Any = response.json()
        except ValueError:
            response_payload = {
                "non_json_body": response.text[:4096],
            }
        return TransportResponse(
            status_code=response.status_code,
            headers=dict(response.headers),
            payload=response_payload,
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()


class _RecordedSequenceTransport:
    def __init__(self, interactions: Sequence[Any]):
        self._interactions = tuple(interactions)
        self._index = 0

    def post(
        self,
        endpoint: ProviderEndpoint,
        payload: Mapping[str, Any],
    ) -> TransportResponse:
        if self._index >= len(self._interactions):
            raise ReplaySequenceError(
                "recorded interaction sequence was exhausted"
            )
        recorded = self._interactions[self._index]
        self._index += 1
        manifest = recorded.manifest
        if (
            manifest.provider != endpoint.provider
            or manifest.model_revision != endpoint.model_revision
        ):
            raise ReplaySequenceError(
                "recorded interaction provider order does not match replay"
            )
        if payload_digest(payload) != manifest.request_digest:
            raise ReplaySequenceError(
                "recorded interaction request does not match replay"
            )
        metadata = {
            item.key: item.value for item in manifest.provider_metadata
        }
        status_text = metadata.get("http_status")
        if status_text is None:
            transport_code = (
                recorded.response.get("transport_error")
                if isinstance(recorded.response, Mapping)
                else None
            )
            if transport_code == "timeout":
                raise ProviderTimeout("recorded provider timeout")
            if transport_code == "transport_error":
                raise ProviderTransportError(
                    "recorded provider transport error"
                )
            raise ReplaySequenceError(
                "recorded interaction has no HTTP status"
            )
        try:
            status_code = int(status_text)
        except ValueError as exc:
            raise ReplaySequenceError(
                "recorded interaction HTTP status is invalid"
            ) from exc
        return TransportResponse(
            status_code=status_code,
            headers={},
            payload=recorded.response,
        )

    def ensure_consumed(self) -> None:
        if self._index != len(self._interactions):
            raise ReplaySequenceError(
                "recorded interaction sequence contains unused responses"
            )


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_retries: int = 2
    base_delay_seconds: float = 0.5
    max_delay_seconds: float = 30.0
    max_retry_after_seconds: float = 120.0

    def __post_init__(self) -> None:
        if self.max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        for name, value in (
            ("base_delay_seconds", self.base_delay_seconds),
            ("max_delay_seconds", self.max_delay_seconds),
            ("max_retry_after_seconds", self.max_retry_after_seconds),
        ):
            if (
                isinstance(value, bool)
                or not math.isfinite(value)
                or value < 0
            ):
                raise ValueError(f"{name} must be finite and non-negative")


class CircuitBreaker:
    """Process-local breaker for account, endpoint, and model-wide faults."""

    def __init__(self):
        self._reasons: dict[str, str] = {}

    def ensure_available(self, endpoint: ProviderEndpoint) -> None:
        reason = self._reasons.get(endpoint.circuit_key)
        if reason is not None:
            raise CircuitOpenError(
                f"provider circuit is open: {reason}"
            )

    def open(self, endpoint: ProviderEndpoint, reason: str) -> None:
        self._reasons[endpoint.circuit_key] = reason

    def is_open(self, endpoint: ProviderEndpoint) -> bool:
        return endpoint.circuit_key in self._reasons

    def reason(self, endpoint: ProviderEndpoint) -> str | None:
        return self._reasons.get(endpoint.circuit_key)

    def reset(self, endpoint: ProviderEndpoint) -> None:
        self._reasons.pop(endpoint.circuit_key, None)


@dataclass(frozen=True, slots=True)
class ModelCall:
    owner_id: str
    run_id: str
    stage_key: str
    role: RuntimeRole
    system_prompt: str
    user_prompt: str
    temperature: float = 0.0
    max_output_tokens: int = 4096
    random_seed: int | None = None

    def __post_init__(self) -> None:
        if not self.owner_id:
            raise ValueError("model call owner_id must not be empty")
        if not self.system_prompt.strip() or not self.user_prompt.strip():
            raise ValueError("model prompts must not be empty")
        if (
            isinstance(self.temperature, bool)
            or not math.isfinite(self.temperature)
            or self.temperature < 0
            or self.temperature > 2
        ):
            raise ValueError("temperature must be between 0 and 2")
        if self.max_output_tokens < 1:
            raise ValueError("max_output_tokens must be positive")


@dataclass(frozen=True, slots=True)
class StructuredCallResult(Generic[OutputT]):
    value: OutputT
    provider: str
    model_revision: str
    interaction_ids: tuple[str, ...]
    transport_attempts: int
    repaired: bool
    used_fallback: bool
    replayed: bool
    usage: tuple[tuple[str, float], ...] = ()


@dataclass(frozen=True, slots=True)
class _HTTPClassification:
    code: str
    retryable: bool
    opens_circuit: bool


class _EndpointFailed(Exception):
    def __init__(
        self,
        failure: ProviderFailure,
        interaction_ids: Sequence[str],
    ):
        self.failure = failure
        self.interaction_ids = tuple(interaction_ids)
        super().__init__(failure.code)


class _OutputInvalid(ValueError):
    def __init__(self, code: str, details: str, content: str):
        self.code = code
        self.details = details
        self.content = content
        super().__init__(code)


class StructuredModelAdapter:
    def __init__(
        self,
        endpoints: Sequence[ProviderEndpoint],
        *,
        transport: ChatTransport | None = None,
        replay_store: RecordedReplayStore | None = None,
        retry_policy: RetryPolicy = RetryPolicy(),
        circuit_breaker: CircuitBreaker | None = None,
        sleep: Sleep = time.sleep,
        random_value: RandomValue = random.random,
        now: Now = lambda: datetime.now(UTC),
    ):
        if not endpoints:
            raise ValueError("at least one provider endpoint is required")
        self.endpoints = tuple(endpoints)
        self.transport = transport or HttpxChatTransport()
        self.replay_store = replay_store
        self.retry_policy = retry_policy
        self.circuit_breaker = circuit_breaker or CircuitBreaker()
        self.sleep = sleep
        self.random_value = random_value
        self.now = now

    def invoke(
        self,
        call: ModelCall,
        output_model: type[OutputT],
        *,
        replay_interaction_id: str | None = None,
    ) -> StructuredCallResult[OutputT]:
        if not issubclass(output_model, BaseModel):
            raise TypeError("structured output must be a Pydantic model")
        if replay_interaction_id is not None:
            return self._invoke_replay(
                call,
                output_model,
                replay_interaction_id,
            )

        failures: list[ProviderFailure] = []
        prior_interactions: list[str] = []
        for endpoint_index, endpoint in enumerate(self.endpoints):
            if self.circuit_breaker.is_open(endpoint):
                failures.append(
                    ProviderFailure(
                        provider=endpoint.provider,
                        model_revision=endpoint.model_revision,
                        code="circuit_open",
                        retryable=False,
                        circuit_opened=True,
                        attempts=0,
                    )
                )
                continue
            request = self._request_payload(
                call,
                output_model,
                model_revision=endpoint.model_revision,
            )
            try:
                (
                    value,
                    interaction_ids,
                    attempts,
                    repaired,
                    usage,
                ) = self._invoke_endpoint(
                    call,
                    endpoint,
                    request,
                    output_model,
                )
            except _EndpointFailed as exc:
                failures.append(exc.failure)
                prior_interactions.extend(exc.interaction_ids)
                continue
            return StructuredCallResult(
                value=value,
                provider=endpoint.provider,
                model_revision=endpoint.model_revision,
                interaction_ids=tuple(
                    (*prior_interactions, *interaction_ids)
                ),
                transport_attempts=attempts
                + sum(item.attempts for item in failures),
                repaired=repaired,
                used_fallback=endpoint_index > 0,
                replayed=False,
                usage=usage,
            )
        raise AllProvidersFailed(failures)

    def replay_sequence(
        self,
        call: ModelCall,
        output_model: type[OutputT],
        interaction_ids: Sequence[str],
    ) -> StructuredCallResult[OutputT]:
        if self.replay_store is None:
            raise ValueError(
                "recorded replay requires a RecordedReplayStore"
            )
        if not interaction_ids:
            raise ValueError(
                "recorded replay sequence requires interaction IDs"
            )
        if len(interaction_ids) != len(set(interaction_ids)):
            raise ValueError(
                "recorded replay interaction IDs must be unique"
            )
        recorded = tuple(
            self.replay_store.load(
                owner_id=call.owner_id,
                interaction_id=interaction_id,
            )
            for interaction_id in interaction_ids
        )
        for item in recorded:
            manifest = item.manifest
            if (
                manifest.run_id != call.run_id
                or manifest.stage_key != call.stage_key
                or manifest.role is not call.role
            ):
                raise ValueError(
                    "recorded interaction context does not match model call"
                )

        endpoint_keys: set[tuple[str, str]] = set()
        endpoints: list[ProviderEndpoint] = []
        for item in recorded:
            manifest = item.manifest
            key = (manifest.provider, manifest.model_revision)
            if key in endpoint_keys:
                continue
            endpoint_keys.add(key)
            endpoints.append(
                ProviderEndpoint(
                    provider=manifest.provider,
                    base_url="https://recorded.invalid/v1",
                    model_revision=manifest.model_revision,
                    model_family=f"recorded:{manifest.provider}",
                )
            )

        transport = _RecordedSequenceTransport(recorded)
        adapter = StructuredModelAdapter(
            endpoints,
            transport=transport,
            retry_policy=self.retry_policy,
            circuit_breaker=CircuitBreaker(),
            sleep=lambda _: None,
            random_value=self.random_value,
            now=self.now,
        )
        result = adapter.invoke(call, output_model)
        transport.ensure_consumed()
        return StructuredCallResult(
            value=result.value,
            provider=result.provider,
            model_revision=result.model_revision,
            interaction_ids=tuple(interaction_ids),
            transport_attempts=result.transport_attempts,
            repaired=result.repaired,
            used_fallback=result.used_fallback,
            replayed=True,
            usage=result.usage,
        )

    def _invoke_endpoint(
        self,
        call: ModelCall,
        endpoint: ProviderEndpoint,
        request: Mapping[str, Any],
        output_model: type[OutputT],
    ) -> tuple[
        OutputT,
        tuple[str, ...],
        int,
        bool,
        tuple[tuple[str, float], ...],
    ]:
        interaction_ids: list[str] = []
        attempts = 0
        try:
            response, recorded_ids, used_attempts = self._send_with_retries(
                call,
                endpoint,
                request,
                phase="initial",
            )
        except _EndpointFailed:
            raise
        interaction_ids.extend(recorded_ids)
        attempts += used_attempts
        try:
            value = self._parse_response(response, output_model)
        except ModelRefusalError:
            raise
        except _OutputInvalid as invalid:
            repair_request = self._repair_payload(
                request,
                output_model=output_model,
                invalid=invalid,
            )
            try:
                (
                    repair_response,
                    repair_ids,
                    repair_attempts,
                ) = self._send_with_retries(
                    call,
                    endpoint,
                    repair_request,
                    phase="schema_repair",
                )
            except _EndpointFailed as exc:
                raise _EndpointFailed(
                    ProviderFailure(
                        provider=exc.failure.provider,
                        model_revision=exc.failure.model_revision,
                        code=exc.failure.code,
                        retryable=exc.failure.retryable,
                        circuit_opened=exc.failure.circuit_opened,
                        attempts=attempts + exc.failure.attempts,
                    ),
                    (*interaction_ids, *exc.interaction_ids),
                ) from exc
            interaction_ids.extend(repair_ids)
            attempts += repair_attempts
            try:
                value = self._parse_response(
                    repair_response,
                    output_model,
                )
            except ModelRefusalError:
                raise
            except _OutputInvalid as repair_invalid:
                raise _EndpointFailed(
                    ProviderFailure(
                        provider=endpoint.provider,
                        model_revision=endpoint.model_revision,
                        code=(
                            "schema_repair_failed:"
                            + repair_invalid.code
                        ),
                        retryable=False,
                        circuit_opened=False,
                        attempts=attempts,
                    ),
                    interaction_ids,
                ) from repair_invalid
            return (
                value,
                tuple(interaction_ids),
                attempts,
                True,
                self._usage(repair_response.payload),
            )
        return (
            value,
            tuple(interaction_ids),
            attempts,
            False,
            self._usage(response.payload),
        )

    def _send_with_retries(
        self,
        call: ModelCall,
        endpoint: ProviderEndpoint,
        request: Mapping[str, Any],
        *,
        phase: str,
    ) -> tuple[TransportResponse, tuple[str, ...], int]:
        interaction_ids: list[str] = []
        attempt_limit = self.retry_policy.max_retries + 1
        for attempt in range(1, attempt_limit + 1):
            try:
                self.circuit_breaker.ensure_available(endpoint)
            except CircuitOpenError as exc:
                raise _EndpointFailed(
                    ProviderFailure(
                        provider=endpoint.provider,
                        model_revision=endpoint.model_revision,
                        code="circuit_open",
                        retryable=False,
                        circuit_opened=True,
                        attempts=attempt - 1,
                    ),
                    interaction_ids,
                ) from exc
            try:
                response = self.transport.post(endpoint, request)
            except (ProviderTimeout, ProviderTransportError) as exc:
                code = (
                    "timeout"
                    if isinstance(exc, ProviderTimeout)
                    else "transport_error"
                )
                recorded = self._record_interaction(
                    call,
                    endpoint,
                    request,
                    {"transport_error": code},
                    phase=phase,
                    attempt=attempt,
                    http_status=None,
                )
                if recorded is not None:
                    interaction_ids.append(recorded)
                if attempt >= attempt_limit:
                    raise _EndpointFailed(
                        ProviderFailure(
                            provider=endpoint.provider,
                            model_revision=endpoint.model_revision,
                            code=f"{code}_retry_exhausted",
                            retryable=True,
                            circuit_opened=False,
                            attempts=attempt,
                        ),
                        interaction_ids,
                    ) from exc
                self.sleep(self._retry_delay(None, attempt))
                continue

            recorded = self._record_interaction(
                call,
                endpoint,
                request,
                response.payload,
                phase=phase,
                attempt=attempt,
                http_status=response.status_code,
            )
            if recorded is not None:
                interaction_ids.append(recorded)
            if 200 <= response.status_code < 300:
                return response, tuple(interaction_ids), attempt

            classification = self._classify_http_error(response)
            if classification.opens_circuit:
                self.circuit_breaker.open(
                    endpoint,
                    classification.code,
                )
            if (
                classification.retryable
                and attempt < attempt_limit
                and not classification.opens_circuit
            ):
                self.sleep(self._retry_delay(response, attempt))
                continue
            raise _EndpointFailed(
                ProviderFailure(
                    provider=endpoint.provider,
                    model_revision=endpoint.model_revision,
                    code=classification.code,
                    retryable=classification.retryable,
                    circuit_opened=classification.opens_circuit,
                    attempts=attempt,
                ),
                interaction_ids,
            )
        raise AssertionError("retry loop terminated unexpectedly")

    def _invoke_replay(
        self,
        call: ModelCall,
        output_model: type[OutputT],
        interaction_id: str,
    ) -> StructuredCallResult[OutputT]:
        if self.replay_store is None:
            raise ValueError(
                "recorded replay requires a RecordedReplayStore"
            )
        recorded = self.replay_store.load(
            owner_id=call.owner_id,
            interaction_id=interaction_id,
        )
        manifest = recorded.manifest
        if (
            manifest.run_id != call.run_id
            or manifest.stage_key != call.stage_key
            or manifest.role is not call.role
        ):
            raise ValueError(
                "recorded interaction context does not match model call"
            )
        expected_request = self._request_payload(
            call,
            output_model,
            model_revision=manifest.model_revision,
        )
        replayed = self.replay_store.replay(
            owner_id=call.owner_id,
            interaction_id=interaction_id,
            expected_request=expected_request,
        )
        response = TransportResponse(
            status_code=self._metadata_int(
                manifest=manifest,
                key="http_status",
                default=200,
            ),
            headers={},
            payload=replayed.response,
        )
        if not 200 <= response.status_code < 300:
            raise ValueError(
                "recorded interaction is not a successful model response"
            )
        value = self._parse_response(response, output_model)
        return StructuredCallResult(
            value=value,
            provider=manifest.provider,
            model_revision=manifest.model_revision,
            interaction_ids=(interaction_id,),
            transport_attempts=0,
            repaired=False,
            used_fallback=False,
            replayed=True,
            usage=self._usage(response.payload),
        )

    def _record_interaction(
        self,
        call: ModelCall,
        endpoint: ProviderEndpoint,
        request: Mapping[str, Any],
        response: Any,
        *,
        phase: str,
        attempt: int,
        http_status: int | None,
    ) -> str | None:
        if self.replay_store is None:
            return None
        metadata: dict[str, Any] = {
            "attempt": attempt,
            "phase": phase,
        }
        if http_status is not None:
            metadata["http_status"] = http_status
        interaction = self.replay_store.record(
            owner_id=call.owner_id,
            run_id=call.run_id,
            stage_key=call.stage_key,
            role=call.role,
            provider=endpoint.provider,
            model_revision=endpoint.model_revision,
            request=request,
            response=response,
            provider_metadata=metadata,
        )
        return interaction.interaction_id

    @staticmethod
    def _request_payload(
        call: ModelCall,
        output_model: type[BaseModel],
        *,
        model_revision: str,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model_revision,
            "messages": [
                {
                    "role": "system",
                    "content": call.system_prompt,
                },
                {
                    "role": "user",
                    "content": call.user_prompt,
                },
            ],
            "temperature": call.temperature,
            "max_tokens": call.max_output_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": output_model.__name__,
                    "strict": True,
                    "schema": output_model.model_json_schema(
                        mode="validation"
                    ),
                },
            },
        }
        if call.random_seed is not None:
            payload["seed"] = call.random_seed
        return payload

    @staticmethod
    def _repair_payload(
        request: Mapping[str, Any],
        *,
        output_model: type[BaseModel],
        invalid: _OutputInvalid,
    ) -> dict[str, Any]:
        repaired = json.loads(json.dumps(request))
        messages = list(repaired["messages"])
        messages.append(
            {
                "role": "user",
                "content": (
                    "The previous structured response failed local "
                    "validation. Return only one JSON value matching the "
                    f"{output_model.__name__} schema. "
                    f"schema_validation_errors={invalid.details[:1800]}\n"
                    f"invalid_response={invalid.content[:8000]}"
                ),
            }
        )
        repaired["messages"] = messages
        return repaired

    @classmethod
    def _parse_response(
        cls,
        response: TransportResponse,
        output_model: type[OutputT],
    ) -> OutputT:
        payload = response.payload
        if not isinstance(payload, Mapping):
            raise _OutputInvalid(
                "response_not_object",
                "provider response must be an object",
                repr(payload)[:8000],
            )
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise _OutputInvalid(
                "missing_choices",
                "provider response has no choices",
                json.dumps(payload, ensure_ascii=True)[:8000],
            )
        choice = choices[0]
        if not isinstance(choice, Mapping):
            raise _OutputInvalid(
                "invalid_choice",
                "first provider choice is not an object",
                repr(choice)[:8000],
            )
        finish_reason = choice.get("finish_reason")
        if finish_reason == "content_filter":
            raise ModelRefusalError("provider content filter refused output")
        message = choice.get("message")
        if not isinstance(message, Mapping):
            raise _OutputInvalid(
                "missing_message",
                "provider choice has no message",
                repr(choice)[:8000],
            )
        if message.get("refusal"):
            raise ModelRefusalError("provider refused structured output")
        content = cls._message_content(message.get("content"))
        if not content.strip():
            raise _OutputInvalid(
                "empty_content",
                "provider returned empty content",
                "",
            )
        if finish_reason not in {None, "stop"}:
            raise _OutputInvalid(
                "incomplete_output",
                f"finish_reason={finish_reason!r}",
                content,
            )
        try:
            parsed = cls._load_json_value(content)
        except ValueError as exc:
            raise _OutputInvalid(
                "invalid_json",
                str(exc),
                content,
            ) from exc
        try:
            return output_model.model_validate(parsed)
        except ValidationError as exc:
            errors = exc.errors(
                include_url=False,
                include_context=False,
                include_input=False,
            )
            raise _OutputInvalid(
                "schema_validation_error",
                json.dumps(errors, ensure_ascii=True),
                content,
            ) from exc

    @staticmethod
    def _message_content(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if not isinstance(item, Mapping):
                    continue
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
            return "".join(parts)
        return ""

    @staticmethod
    def _load_json_value(content: str) -> Any:
        cleaned = content.lstrip("\ufeff").strip()
        fence = _JSON_FENCE.fullmatch(cleaned)
        if fence:
            cleaned = fence.group(1).strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as direct_error:
            decoder = json.JSONDecoder()
            starts = [
                index
                for index in (
                    cleaned.find("{"),
                    cleaned.find("["),
                )
                if index >= 0
            ]
            if not starts:
                raise ValueError(str(direct_error)) from direct_error
            try:
                value, end = decoder.raw_decode(
                    cleaned,
                    min(starts),
                )
            except json.JSONDecodeError as exc:
                raise ValueError(str(exc)) from exc
            if cleaned[end:].strip():
                raise ValueError(
                    "non-whitespace content follows the JSON value"
                )
            return value

    @staticmethod
    def _classify_http_error(
        response: TransportResponse,
    ) -> _HTTPClassification:
        error_code = ""
        message = ""
        if isinstance(response.payload, Mapping):
            error = response.payload.get("error")
            if isinstance(error, Mapping):
                raw_code = error.get("code") or error.get("type")
                if isinstance(raw_code, str):
                    error_code = raw_code.casefold()
                raw_message = error.get("message")
                if isinstance(raw_message, str):
                    message = raw_message.casefold()
            elif isinstance(error, str):
                message = error.casefold()
        opens_circuit = (
            response.status_code in {401, 402, 403}
            or error_code in _CIRCUIT_ERROR_CODES
            or any(
                marker in f"{error_code} {message}"
                for marker in _CIRCUIT_ERROR_MARKERS
            )
        )
        retryable = (
            response.status_code == 429
            or response.status_code >= 500
        ) and not opens_circuit
        code = error_code or f"http_{response.status_code}"
        return _HTTPClassification(
            code=code,
            retryable=retryable,
            opens_circuit=opens_circuit,
        )

    def _retry_delay(
        self,
        response: TransportResponse | None,
        attempt: int,
    ) -> float:
        try:
            exponential_cap = min(
                self.retry_policy.max_delay_seconds,
                self.retry_policy.base_delay_seconds
                * (2 ** max(attempt - 1, 0)),
            )
        except OverflowError:
            exponential_cap = self.retry_policy.max_delay_seconds
        random_value = self.random_value()
        if not math.isfinite(random_value):
            random_value = 0.5
        jitter = min(max(random_value, 0.0), 1.0) * exponential_cap
        retry_after = self._retry_after_seconds(response)
        return max(jitter, retry_after or 0.0)

    def _retry_after_seconds(
        self,
        response: TransportResponse | None,
    ) -> float | None:
        if response is None:
            return None
        raw = next(
            (
                value
                for key, value in response.headers.items()
                if key.casefold() == "retry-after"
            ),
            None,
        )
        if raw is None:
            return None
        try:
            delay = float(raw)
        except (TypeError, ValueError):
            try:
                target = parsedate_to_datetime(str(raw))
                if target.tzinfo is None:
                    target = target.replace(tzinfo=UTC)
                delay = (target - self.now()).total_seconds()
            except (TypeError, ValueError, OverflowError):
                return None
        return min(
            max(delay, 0.0),
            self.retry_policy.max_retry_after_seconds,
        )

    @staticmethod
    def _usage(payload: Any) -> tuple[tuple[str, float], ...]:
        if not isinstance(payload, Mapping):
            return ()
        usage = payload.get("usage")
        if not isinstance(usage, Mapping):
            return ()
        numeric = (
            (str(key), float(value))
            for key, value in usage.items()
            if (
                isinstance(key, str)
                and isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
            )
        )
        return tuple(sorted(numeric))

    @staticmethod
    def _metadata_int(
        *,
        manifest: Any,
        key: str,
        default: int,
    ) -> int:
        for item in manifest.provider_metadata:
            if item.key == key:
                try:
                    return int(item.value)
                except ValueError:
                    return default
        return default
