from __future__ import annotations

import json
import tempfile
import unittest
from collections import defaultdict
from pathlib import Path
from typing import Any

from pydantic import ConfigDict

from backend.vnext.contracts.base import FrozenContract
from backend.vnext.contracts.common import RuntimeRole
from backend.vnext.contracts.control import (
    ModelPortfolioManifest,
    ModelSlot,
)
from backend.vnext.model_runtime import (
    AllProvidersFailed,
    CircuitBreaker,
    ModelCall,
    PortfolioRouteError,
    ProviderEndpoint,
    ProviderTimeout,
    ReplaySequenceError,
    RetryPolicy,
    StructuredModelAdapter,
    TransportResponse,
    select_independent_verifier,
    select_precision_verifier_pair,
)
from backend.vnext.replay.store import RecordedReplayStore


class Answer(FrozenContract):
    answer: str
    confidence: int


class ScriptedTransport:
    def __init__(self, scripts: dict[str, list[Any]]):
        self.scripts = {
            provider: list(events)
            for provider, events in scripts.items()
        }
        self.requests: list[tuple[ProviderEndpoint, dict[str, Any]]] = []
        self.calls_by_provider: defaultdict[str, int] = defaultdict(int)

    def post(
        self,
        endpoint: ProviderEndpoint,
        payload: dict[str, Any],
    ) -> TransportResponse:
        self.requests.append(
            (
                endpoint,
                json.loads(json.dumps(payload)),
            )
        )
        self.calls_by_provider[endpoint.provider] += 1
        event = self.scripts[endpoint.provider].pop(0)
        if isinstance(event, Exception):
            raise event
        return event


def _endpoint(
    provider: str,
    *,
    family: str | None = None,
    api_key: str | None = None,
) -> ProviderEndpoint:
    return ProviderEndpoint(
        provider=provider,
        base_url=f"https://{provider}.example/v1",
        model_revision=f"{provider}-model-20260701",
        model_family=family or provider,
        api_key=api_key,
    )


def _success(
    payload: str,
    *,
    usage: dict[str, int] | None = None,
) -> TransportResponse:
    response: dict[str, Any] = {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {"content": payload},
            }
        ]
    }
    if usage is not None:
        response["usage"] = usage
    return TransportResponse(
        status_code=200,
        headers={},
        payload=response,
    )


def _error(
    status: int,
    *,
    code: str,
    message: str,
    headers: dict[str, str] | None = None,
) -> TransportResponse:
    return TransportResponse(
        status_code=status,
        headers=headers or {},
        payload={
            "error": {
                "code": code,
                "message": message,
            }
        },
    )


def _call(user_prompt: str = "Return the answer.") -> ModelCall:
    return ModelCall(
        owner_id="tenant-a",
        run_id=f"run_{'a' * 32}",
        stage_key="claim-extraction",
        role=RuntimeRole.CLAIM_ATOMIZER,
        system_prompt="Use only supplied courseware evidence.",
        user_prompt=user_prompt,
        random_seed=7,
    )


def _slot(
    name: str,
    *,
    provider: str,
    family: str,
    group: str | None,
    calibrated: bool,
) -> ModelSlot:
    return ModelSlot(
        slot=name,
        provider=provider,
        model_revision=f"{provider}-model-20260701",
        model_family=family,
        independence_group=group,
        independence_calibrated=calibrated,
        context_limit=128000,
        structured_output=True,
        region="cn",
        price_input_microunits_per_million=1,
        price_output_microunits_per_million=1,
    )


class VNextStructuredModelAdapterTests(unittest.TestCase):
    def test_valid_structured_output_is_locally_validated_and_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            replay_store = RecordedReplayStore(Path(tmp) / "replay")
            transport = ScriptedTransport(
                {
                    "primary": [
                        _success(
                            '{"answer":"grounded","confidence":4}',
                            usage={
                                "prompt_tokens": 20,
                                "completion_tokens": 8,
                            },
                        )
                    ]
                }
            )
            adapter = StructuredModelAdapter(
                [_endpoint("primary", api_key="top-secret-key")],
                transport=transport,
                replay_store=replay_store,
            )

            result = adapter.invoke(_call(), Answer)

            self.assertEqual(result.value.answer, "grounded")
            self.assertEqual(result.usage, (
                ("completion_tokens", 8.0),
                ("prompt_tokens", 20.0),
            ))
            self.assertFalse(result.repaired)
            self.assertFalse(result.used_fallback)
            self.assertEqual(len(result.interaction_ids), 1)
            request = transport.requests[0][1]
            self.assertEqual(
                request["response_format"]["type"],
                "json_schema",
            )
            self.assertTrue(
                request["response_format"]["json_schema"]["strict"]
            )
            self.assertFalse(
                request["response_format"]["json_schema"]["schema"][
                    "additionalProperties"
                ]
            )
            replayed = replay_store.load(
                owner_id="tenant-a",
                interaction_id=result.interaction_ids[0],
            )
            serialized = json.dumps(
                {
                    "request": replayed.request,
                    "manifest": replayed.manifest.model_dump(
                        mode="json"
                    ),
                },
                sort_keys=True,
            )
            self.assertNotIn("top-secret-key", serialized)
            self.assertNotIn("Authorization", serialized)

    def test_invalid_output_gets_exactly_one_targeted_schema_repair(self):
        transport = ScriptedTransport(
            {
                "primary": [
                    _success('{"answer":"missing confidence"}'),
                    _success(
                        "```json\n"
                        '{"answer":"fixed","confidence":5}'
                        "\n```"
                    ),
                ]
            }
        )
        adapter = StructuredModelAdapter(
            [_endpoint("primary")],
            transport=transport,
        )

        result = adapter.invoke(_call(), Answer)

        self.assertTrue(result.repaired)
        self.assertEqual(result.value.answer, "fixed")
        self.assertEqual(transport.calls_by_provider["primary"], 2)
        repair_messages = transport.requests[1][1]["messages"]
        self.assertEqual(len(repair_messages), 3)
        self.assertIn(
            "schema_validation_errors=",
            repair_messages[-1]["content"],
        )

    def test_schema_repair_failure_falls_back_without_a_second_repair(self):
        transport = ScriptedTransport(
            {
                "primary": [
                    _success('{"answer":"bad"}'),
                    _success('{"confidence":2}'),
                ],
                "fallback": [
                    _success('{"answer":"fallback","confidence":3}')
                ],
            }
        )
        adapter = StructuredModelAdapter(
            [_endpoint("primary"), _endpoint("fallback")],
            transport=transport,
        )

        result = adapter.invoke(_call(), Answer)

        self.assertTrue(result.used_fallback)
        self.assertFalse(result.repaired)
        self.assertEqual(result.value.answer, "fallback")
        self.assertEqual(transport.calls_by_provider["primary"], 2)
        self.assertEqual(transport.calls_by_provider["fallback"], 1)

    def test_retryable_429_and_timeout_honor_budget_and_retry_after(self):
        sleeps: list[float] = []
        transport = ScriptedTransport(
            {
                "primary": [
                    _error(
                        429,
                        code="rate_limit_exceeded",
                        message="slow down",
                        headers={"Retry-After": "3"},
                    ),
                    ProviderTimeout("timeout"),
                    _success('{"answer":"eventual","confidence":4}'),
                ]
            }
        )
        adapter = StructuredModelAdapter(
            [_endpoint("primary")],
            transport=transport,
            retry_policy=RetryPolicy(
                max_retries=2,
                base_delay_seconds=2,
                max_delay_seconds=8,
            ),
            sleep=sleeps.append,
            random_value=lambda: 0.5,
        )

        result = adapter.invoke(_call(), Answer)

        self.assertEqual(result.value.answer, "eventual")
        self.assertEqual(result.transport_attempts, 3)
        self.assertEqual(transport.calls_by_provider["primary"], 3)
        self.assertEqual(sleeps, [3.0, 2.0])

    def test_insufficient_quota_opens_circuit_and_uses_fallback(self):
        breaker = CircuitBreaker()
        primary = _endpoint("primary")
        fallback = _endpoint("fallback")
        transport = ScriptedTransport(
            {
                "primary": [
                    _error(
                        429,
                        code="insufficient_quota",
                        message="billing quota exhausted",
                    )
                ],
                "fallback": [
                    _success('{"answer":"fallback","confidence":4}'),
                    _success('{"answer":"again","confidence":4}'),
                ],
            }
        )
        adapter = StructuredModelAdapter(
            [primary, fallback],
            transport=transport,
            circuit_breaker=breaker,
        )

        first = adapter.invoke(_call(), Answer)
        second = adapter.invoke(
            _call("Return the answer again."),
            Answer,
        )

        self.assertTrue(first.used_fallback)
        self.assertTrue(second.used_fallback)
        self.assertTrue(breaker.is_open(primary))
        self.assertEqual(transport.calls_by_provider["primary"], 1)
        self.assertEqual(transport.calls_by_provider["fallback"], 2)

    def test_retry_exhaustion_surfaces_explicit_failures(self):
        transport = ScriptedTransport(
            {
                "primary": [
                    _error(
                        503,
                        code="service_unavailable",
                        message="unavailable",
                    ),
                    _error(
                        503,
                        code="service_unavailable",
                        message="unavailable",
                    ),
                    _error(
                        503,
                        code="service_unavailable",
                        message="unavailable",
                    ),
                ]
            }
        )
        adapter = StructuredModelAdapter(
            [_endpoint("primary")],
            transport=transport,
            retry_policy=RetryPolicy(max_retries=2),
            sleep=lambda _: None,
        )

        with self.assertRaises(AllProvidersFailed) as raised:
            adapter.invoke(_call(), Answer)

        self.assertEqual(len(raised.exception.failures), 1)
        failure = raised.exception.failures[0]
        self.assertEqual(failure.code, "service_unavailable")
        self.assertTrue(failure.retryable)
        self.assertEqual(failure.attempts, 3)

    def test_recorded_response_replay_never_calls_transport(self):
        with tempfile.TemporaryDirectory() as tmp:
            replay_store = RecordedReplayStore(Path(tmp) / "replay")
            live_transport = ScriptedTransport(
                {
                    "primary": [
                        _success('{"answer":"recorded","confidence":5}')
                    ]
                }
            )
            live_adapter = StructuredModelAdapter(
                [_endpoint("primary")],
                transport=live_transport,
                replay_store=replay_store,
            )
            live = live_adapter.invoke(_call(), Answer)
            replay_transport = ScriptedTransport({"primary": []})
            replay_adapter = StructuredModelAdapter(
                [_endpoint("primary")],
                transport=replay_transport,
                replay_store=replay_store,
            )

            replayed = replay_adapter.invoke(
                _call(),
                Answer,
                replay_interaction_id=live.interaction_ids[-1],
            )

            self.assertTrue(replayed.replayed)
            self.assertEqual(replayed.value, live.value)
            self.assertEqual(replay_transport.requests, [])

    def test_recorded_schema_repair_sequence_replays_without_transport(self):
        with tempfile.TemporaryDirectory() as tmp:
            replay_store = RecordedReplayStore(Path(tmp) / "replay")
            live_transport = ScriptedTransport(
                {
                    "primary": [
                        _success('{"answer":"missing confidence"}'),
                        _success(
                            '{"answer":"repaired","confidence":5}'
                        ),
                    ]
                }
            )
            live_adapter = StructuredModelAdapter(
                [_endpoint("primary")],
                transport=live_transport,
                replay_store=replay_store,
            )
            live = live_adapter.invoke(_call(), Answer)
            replay_transport = ScriptedTransport({"primary": []})
            replay_adapter = StructuredModelAdapter(
                [_endpoint("primary")],
                transport=replay_transport,
                replay_store=replay_store,
            )

            replayed = replay_adapter.replay_sequence(
                _call(),
                Answer,
                live.interaction_ids,
            )

            self.assertTrue(replayed.replayed)
            self.assertTrue(replayed.repaired)
            self.assertEqual(replayed.value, live.value)
            self.assertEqual(replayed.interaction_ids, live.interaction_ids)
            self.assertEqual(replay_transport.requests, [])
            with self.assertRaises(ReplaySequenceError):
                replay_adapter.replay_sequence(
                    _call(),
                    Answer,
                    tuple(reversed(live.interaction_ids)),
                )

    def test_recorded_repair_failure_and_fallback_replay_full_sequence(self):
        with tempfile.TemporaryDirectory() as tmp:
            replay_store = RecordedReplayStore(Path(tmp) / "replay")
            live_transport = ScriptedTransport(
                {
                    "primary": [
                        _success('{"answer":"bad"}'),
                        _success('{"confidence":2}'),
                    ],
                    "fallback": [
                        _success(
                            '{"answer":"fallback","confidence":3}'
                        )
                    ],
                }
            )
            endpoints = (
                _endpoint("primary"),
                _endpoint("fallback"),
            )
            live_adapter = StructuredModelAdapter(
                endpoints,
                transport=live_transport,
                replay_store=replay_store,
            )
            live = live_adapter.invoke(_call(), Answer)
            replay_transport = ScriptedTransport(
                {"primary": [], "fallback": []}
            )
            replay_adapter = StructuredModelAdapter(
                endpoints,
                transport=replay_transport,
                replay_store=replay_store,
            )

            replayed = replay_adapter.replay_sequence(
                _call(),
                Answer,
                live.interaction_ids,
            )

            self.assertTrue(replayed.replayed)
            self.assertTrue(replayed.used_fallback)
            self.assertFalse(replayed.repaired)
            self.assertEqual(replayed.value, live.value)
            self.assertEqual(len(replayed.interaction_ids), 3)
            self.assertEqual(replay_transport.requests, [])


class VNextModelPortfolioRouterTests(unittest.TestCase):
    def test_standard_router_skips_same_family_verifier(self):
        portfolio = ModelPortfolioManifest(
            slots=(
                _slot(
                    "claim_extractor",
                    provider="provider-a",
                    family="family-a",
                    group="group-a",
                    calibrated=False,
                ),
                _slot(
                    "verifier_a",
                    provider="provider-b",
                    family="family-a",
                    group="group-b",
                    calibrated=False,
                ),
                _slot(
                    "verifier_b",
                    provider="provider-c",
                    family="family-c",
                    group="group-c",
                    calibrated=False,
                ),
            )
        )

        selected = select_independent_verifier(
            portfolio,
            proposer_slot="claim_extractor",
        )

        self.assertEqual(selected.slot, "verifier_b")

    def test_precision_router_requires_two_calibrated_independent_votes(self):
        valid = ModelPortfolioManifest(
            slots=(
                _slot(
                    "verifier_a",
                    provider="provider-a",
                    family="family-a",
                    group="group-a",
                    calibrated=True,
                ),
                _slot(
                    "verifier_b",
                    provider="provider-b",
                    family="family-b",
                    group="group-b",
                    calibrated=True,
                ),
            )
        )
        invalid = ModelPortfolioManifest(
            slots=(
                _slot(
                    "verifier_a",
                    provider="provider-a",
                    family="family-a",
                    group="shared",
                    calibrated=True,
                ),
                _slot(
                    "verifier_b",
                    provider="provider-b",
                    family="family-b",
                    group="shared",
                    calibrated=True,
                ),
            )
        )

        pair = select_precision_verifier_pair(valid)
        self.assertEqual(
            tuple(item.slot for item in pair),
            ("verifier_a", "verifier_b"),
        )
        with self.assertRaises(PortfolioRouteError):
            select_precision_verifier_pair(invalid)


if __name__ == "__main__":
    unittest.main()
