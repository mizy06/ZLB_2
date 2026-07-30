from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from backend.tests.vnext_test_support import digest
from backend.vnext.contracts.common import (
    ArtifactProducerRef,
    ArtifactRef,
    ArtifactType,
    RuntimeRole,
    StringValue,
)
from backend.vnext.contracts.control import (
    DeclaredRunManifest,
    EvidenceMode,
    ExecutionStatus,
    PublicationStatus,
    QualityStatus,
    RunBudget,
    RunManifest,
    RunProfile,
)
from backend.vnext.contracts.quality import PilotGateDecision
from backend.vnext.contracts.release import (
    CanaryDecision,
    CanaryObservation,
    CanaryStage,
    ReleaseEventType,
    ReleaseReadinessEvidence,
)
from backend.vnext.orchestration.control_store import (
    CompareAndSwapConflict,
    ReleaseEventIntegrityError,
    SQLiteControlStore,
)
from backend.vnext.orchestration.release import (
    CANARY_POINTER_KEY,
    PUBLISHED_POINTER_KEY,
    ReleaseGateBlocked,
    ReleaseGovernor,
    default_canary_policy,
    evaluate_canary_transition,
)


NOW = datetime(2026, 7, 29, 14, 0, tzinfo=UTC)
RUN_ID = f"run_{'1' * 32}"
RELEASE_ID = f"release_{'2' * 32}"
READINESS_RECORDER = ArtifactProducerRef(
    producer_id="test-release-evidence-aggregator",
    producer_version="1.0.0",
    role=RuntimeRole.RELEASE_EVIDENCE_AGGREGATOR,
)
OBSERVATION_RECORDER = ArtifactProducerRef(
    producer_id="test-canary-observation-aggregator",
    producer_version="1.0.0",
    role=RuntimeRole.CANARY_OBSERVATION_AGGREGATOR,
)


def _projection_ref(digit: str) -> ArtifactRef:
    return ArtifactRef(
        owner_id="owner-a",
        artifact_id=f"art_{digit * 32}",
        artifact_type=ArtifactType.DIAGNOSTIC_PROJECTION,
        payload_digest=digest(digit),
    )


def _manifest(
    publication_status: PublicationStatus,
) -> RunManifest:
    return RunManifest(
        manifest_id=f"run_manifest_{'3' * 32}",
        run_id=RUN_ID,
        revision=1,
        owner_id="owner-a",
        declared=DeclaredRunManifest(
            source_hash=digest("1"),
            profile=RunProfile.STANDARD,
            evidence_mode=EvidenceMode.SOURCE_ONLY,
            no_egress=True,
            budget=RunBudget(
                max_wall_seconds=600,
                max_model_calls=0,
                max_search_queries=0,
                max_search_fetches=0,
                max_cost_microunits=0,
                vlm_concurrency=0,
                text_concurrency=1,
                search_concurrency=0,
            ),
            code_revision="test",
            dependency_digest=digest("2"),
            parser_policy_digest=digest("3"),
            renderer_policy_digest=digest("4"),
            prompt_policy_digest=digest("5"),
            tool_policy_digest=digest("6"),
            search_policy_digest=digest("7"),
            schema_digests=(
                StringValue(key="test", value=digest("8")),
            ),
            random_seed=0,
        ),
        execution_status=ExecutionStatus.SUCCEEDED,
        quality_status=QualityStatus.PASSED,
        publication_status=publication_status,
        created_at=NOW,
        updated_at=NOW,
    )


def _evidence(
    candidate: ArtifactRef,
    *,
    pilot: PilotGateDecision = PilotGateDecision.PASS,
    api: bool = True,
    ux: bool = True,
    rollback: bool = True,
    blind: bool = True,
    disaster_recovery: bool = True,
) -> ReleaseReadinessEvidence:
    return ReleaseReadinessEvidence(
        release_id=RELEASE_ID,
        owner_id="owner-a",
        run_id=RUN_ID,
        candidate_projection_ref=candidate,
        pilot_report_digest=digest("9"),
        pilot_gate_decision=pilot,
        public_api_approved=api,
        diagnostic_ux_passed=ux,
        rollback_drill_passed=rollback,
        blind_set_expanded=blind,
        disaster_recovery_passed=disaster_recovery,
        created_at=NOW,
    )


def _observation(
    stage: CanaryStage,
    samples: int,
    **violations: int,
) -> CanaryObservation:
    return CanaryObservation(
        release_id=RELEASE_ID,
        stage=stage,
        cumulative_samples=samples,
        severe_errors=violations.get("severe_errors", 0),
        gate_bypasses=violations.get("gate_bypasses", 0),
        cross_owner_reads=violations.get("cross_owner_reads", 0),
        rollback_failures=violations.get("rollback_failures", 0),
        quality_failed_public_results=violations.get(
            "quality_failed_public_results",
            0,
        ),
        observed_at=NOW,
    )


def _trust(
    control: SQLiteControlStore,
    manifest: RunManifest,
    evidence: ReleaseReadinessEvidence,
    observation: CanaryObservation,
) -> None:
    if control.load_run(
        manifest.run_id,
        owner_id=manifest.owner_id,
    ) is None:
        try:
            control.create_run(manifest)
        except sqlite3.IntegrityError:
            pass
    control.record_release_readiness_evidence(
        evidence,
        recorder=READINESS_RECORDER,
    )
    control.record_canary_observation(
        observation,
        owner_id=evidence.owner_id,
        recorder=OBSERVATION_RECORDER,
    )


def _activate(
    governor: ReleaseGovernor,
    manifest: RunManifest,
    evidence: ReleaseReadinessEvidence,
    observation: CanaryObservation,
    **kwargs,
):
    _trust(governor.control_store, manifest, evidence, observation)
    return governor.activate_candidate(
        manifest,
        evidence,
        observation,
        **kwargs,
    )


def _promote(
    governor: ReleaseGovernor,
    manifest: RunManifest,
    evidence: ReleaseReadinessEvidence,
    observation: CanaryObservation,
    **kwargs,
):
    _trust(governor.control_store, manifest, evidence, observation)
    return governor.promote_default(
        manifest,
        evidence,
        observation,
        **kwargs,
    )


class VNextCanaryDecisionTests(unittest.TestCase):
    def test_readiness_gaps_hold_and_safety_incidents_rollback(self):
        policy = default_canary_policy()
        candidate = _projection_ref("a")

        held = evaluate_canary_transition(
            policy,
            _evidence(candidate, pilot=PilotGateDecision.INCOMPLETE),
            _observation(CanaryStage.SHADOW, 0),
            decided_at=NOW,
        )
        rolled_back = evaluate_canary_transition(
            policy,
            _evidence(candidate),
            _observation(
                CanaryStage.PERCENT_5,
                250,
                cross_owner_reads=1,
            ),
            decided_at=NOW,
        )

        self.assertEqual(held.decision, CanaryDecision.HOLD)
        self.assertIn("pilot_gate_not_passed", held.reason_codes)
        self.assertEqual(
            rolled_back.decision,
            CanaryDecision.ROLLBACK,
        )
        self.assertEqual(
            rolled_back.to_stage,
            CanaryStage.PERCENT_5,
        )
        self.assertIn(
            "safety_violation:cross_owner_reads",
            rolled_back.reason_codes,
        )

    def test_cumulative_sample_thresholds_gate_each_public_step(self):
        policy = default_canary_policy()
        evidence = _evidence(_projection_ref("a"))
        cases = (
            (CanaryStage.ALLOWLIST, 49, CanaryDecision.HOLD),
            (CanaryStage.ALLOWLIST, 50, CanaryDecision.ADVANCE),
            (CanaryStage.PERCENT_1, 99, CanaryDecision.HOLD),
            (CanaryStage.PERCENT_1, 100, CanaryDecision.ADVANCE),
            (CanaryStage.PERCENT_5, 199, CanaryDecision.HOLD),
            (CanaryStage.PERCENT_5, 200, CanaryDecision.ADVANCE),
            (CanaryStage.PERCENT_20, 299, CanaryDecision.HOLD),
            (CanaryStage.PERCENT_20, 300, CanaryDecision.ADVANCE),
        )

        for stage, samples, expected in cases:
            with self.subTest(stage=stage, samples=samples):
                decision = evaluate_canary_transition(
                    policy,
                    evidence,
                    _observation(stage, samples),
                    decided_at=NOW,
                )
                self.assertEqual(decision.decision, expected)

    def test_default_promotion_requires_disaster_recovery_evidence(self):
        policy = default_canary_policy()
        candidate = _projection_ref("a")

        decision = evaluate_canary_transition(
            policy,
            _evidence(candidate, disaster_recovery=False),
            _observation(CanaryStage.PERCENT_50, 300),
            decided_at=NOW,
        )

        self.assertEqual(decision.decision, CanaryDecision.HOLD)
        self.assertIn(
            "disaster_recovery_not_passed",
            decision.reason_codes,
        )


class VNextReleasePointerTests(unittest.TestCase):
    def test_candidate_activation_and_rollback_use_pointer_cas(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = SQLiteControlStore(Path(tmp) / "control.sqlite3")
            governor = ReleaseGovernor(control)
            stable = _projection_ref("b")
            candidate = _projection_ref("a")
            control.compare_and_swap_pointer(
                owner_id="owner-a",
                pointer_key=PUBLISHED_POINTER_KEY,
                artifact_ref=stable,
                expected_version=None,
                now=NOW,
            )

            activation = _activate(
                governor,
                _manifest(PublicationStatus.RELEASE_CANDIDATE),
                _evidence(candidate),
                _observation(CanaryStage.SHADOW, 0),
                expected_pointer_version=None,
                expected_release_sequence=None,
            )

            self.assertEqual(
                activation.decision.to_stage,
                CanaryStage.ALLOWLIST,
            )
            self.assertEqual(
                control.load_pointer(
                    owner_id="owner-a",
                    pointer_key=CANARY_POINTER_KEY,
                ).artifact_ref,
                candidate,
            )
            rollback = governor.rollback_candidate(
                _evidence(candidate),
                expected_canary_pointer_version=activation.pointer.version,
                expected_release_sequence=activation.event.sequence,
                reason_codes=("canary_serious_error",),
                rolled_back_at=NOW,
            )
            retry = governor.rollback_candidate(
                _evidence(candidate),
                expected_canary_pointer_version=activation.pointer.version,
                expected_release_sequence=activation.event.sequence,
                reason_codes=("canary_serious_error",),
                rolled_back_at=NOW,
            )
            self.assertEqual(rollback.restored_artifact_ref, stable)
            self.assertEqual(retry, rollback)
            self.assertEqual(
                control.load_pointer(
                    owner_id="owner-a",
                    pointer_key=CANARY_POINTER_KEY,
                ).artifact_ref,
                stable,
            )
            events = control.list_release_events(
                owner_id="owner-a",
                release_id=RELEASE_ID,
            )
            self.assertEqual(
                tuple(item.sequence for item in events),
                (1, 2),
            )
            self.assertEqual(
                events[1].previous_event_digest,
                events[0].event_digest,
            )
            self.assertEqual(events[1].rollback, rollback)
            self.assertIn(
                candidate.artifact_id,
                control.referenced_artifact_ids(owner_id="owner-a"),
            )
            with self.assertRaises(CompareAndSwapConflict):
                control.compare_and_swap_pointer(
                    owner_id="owner-a",
                    pointer_key=CANARY_POINTER_KEY,
                    artifact_ref=candidate,
                    expected_version=activation.pointer.version,
                    now=NOW,
                )

    def test_governor_refuses_activation_when_readiness_is_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            governor = ReleaseGovernor(
                SQLiteControlStore(Path(tmp) / "control.sqlite3")
            )
            candidate = _projection_ref("a")

            with self.assertRaises(ReleaseGateBlocked) as raised:
                _activate(
                    governor,
                    _manifest(PublicationStatus.RELEASE_CANDIDATE),
                    _evidence(
                        candidate,
                        pilot=PilotGateDecision.INCOMPLETE,
                    ),
                    _observation(CanaryStage.SHADOW, 0),
                    expected_pointer_version=None,
                    expected_release_sequence=None,
                )

            self.assertEqual(
                raised.exception.decision.decision,
                CanaryDecision.HOLD,
            )
            self.assertEqual(
                raised.exception.event.decision,
                raised.exception.decision,
            )
            self.assertIsNone(
                governor.control_store.load_pointer(
                    owner_id="owner-a",
                    pointer_key=CANARY_POINTER_KEY,
                )
            )
            self.assertEqual(
                governor.control_store.list_release_events(
                    owner_id="owner-a",
                    release_id=RELEASE_ID,
                ),
                (raised.exception.event,),
            )

    def test_only_final_stage_can_replace_published_pointer(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = SQLiteControlStore(Path(tmp) / "control.sqlite3")
            governor = ReleaseGovernor(control)
            stable = _projection_ref("b")
            candidate = _projection_ref("a")
            stable_pointer = control.compare_and_swap_pointer(
                owner_id="owner-a",
                pointer_key=PUBLISHED_POINTER_KEY,
                artifact_ref=stable,
                expected_version=None,
                now=NOW,
            )

            promoted = _promote(
                governor,
                _manifest(PublicationStatus.PUBLISHED),
                _evidence(candidate),
                _observation(CanaryStage.PERCENT_50, 300),
                expected_pointer_version=stable_pointer.version,
                expected_release_sequence=None,
            )

            self.assertEqual(
                promoted.decision.to_stage,
                CanaryStage.DEFAULT,
            )
            self.assertEqual(promoted.pointer.artifact_ref, candidate)
            self.assertEqual(promoted.pointer.version, 2)
            self.assertEqual(promoted.event.pointer_after.version, 2)


class VNextReleaseEventStoreTests(unittest.TestCase):
    def test_blocked_decision_is_append_only_owner_scoped_and_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = SQLiteControlStore(Path(tmp) / "control.sqlite3")
            governor = ReleaseGovernor(control)
            candidate = _projection_ref("a")
            manifest = _manifest(PublicationStatus.RELEASE_CANDIDATE)
            evidence = _evidence(
                candidate,
                pilot=PilotGateDecision.INCOMPLETE,
            )
            observation = _observation(CanaryStage.SHADOW, 0)

            with self.assertRaises(ReleaseGateBlocked) as first:
                _activate(
                    governor,
                    manifest,
                    evidence,
                    observation,
                    expected_pointer_version=None,
                    expected_release_sequence=None,
                )
            with self.assertRaises(ReleaseGateBlocked) as retry:
                _activate(
                    governor,
                    manifest,
                    evidence,
                    observation,
                    expected_pointer_version=None,
                    expected_release_sequence=None,
                )

            self.assertEqual(first.exception.event, retry.exception.event)
            self.assertEqual(
                retry.exception.decision,
                retry.exception.event.decision,
            )
            event = first.exception.event
            self.assertEqual(event.sequence, 1)
            self.assertEqual(event.event_type, ReleaseEventType.CANARY_DECISION)
            self.assertIsNone(event.previous_event_digest)
            self.assertIsNone(event.pointer_before)
            self.assertIsNone(event.pointer_after)
            self.assertEqual(
                control.list_release_events(
                    owner_id="owner-a",
                    release_id=RELEASE_ID,
                ),
                (event,),
            )
            self.assertEqual(
                control.list_release_events(
                    owner_id="owner-b",
                    release_id=RELEASE_ID,
                ),
                (),
            )

            with sqlite3.connect(control.path) as connection:
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(
                        """
                        UPDATE release_events
                        SET event_json = event_json
                        WHERE event_id = ?
                        """,
                        (event.event_id,),
                    )

    def test_stale_release_sequence_is_rejected_without_partial_append(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = SQLiteControlStore(Path(tmp) / "control.sqlite3")
            governor = ReleaseGovernor(control)
            candidate = _projection_ref("a")
            manifest = _manifest(PublicationStatus.RELEASE_CANDIDATE)
            evidence = _evidence(
                candidate,
                pilot=PilotGateDecision.INCOMPLETE,
            )

            with self.assertRaises(ReleaseGateBlocked):
                _activate(
                    governor,
                    manifest,
                    evidence,
                    _observation(CanaryStage.SHADOW, 0),
                    expected_pointer_version=None,
                    expected_release_sequence=None,
                )
            with self.assertRaisesRegex(
                CompareAndSwapConflict,
                "release event sequence",
            ):
                _activate(
                    governor,
                    manifest,
                    evidence,
                    _observation(CanaryStage.SHADOW, 1),
                    expected_pointer_version=None,
                    expected_release_sequence=None,
                )

            self.assertEqual(
                len(
                    control.list_release_events(
                        owner_id="owner-a",
                        release_id=RELEASE_ID,
                    )
                ),
                1,
            )

    def test_two_writers_cannot_claim_the_same_release_sequence(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "control.sqlite3"
            SQLiteControlStore(path)
            barrier = threading.Barrier(2)

            def record(samples: int) -> str:
                governor = ReleaseGovernor(SQLiteControlStore(path))
                barrier.wait()
                try:
                    _activate(
                        governor,
                        _manifest(
                            PublicationStatus.RELEASE_CANDIDATE
                        ),
                        _evidence(
                            _projection_ref("a"),
                            pilot=PilotGateDecision.INCOMPLETE,
                        ),
                        _observation(CanaryStage.SHADOW, samples),
                        expected_pointer_version=None,
                        expected_release_sequence=None,
                    )
                except ReleaseGateBlocked:
                    return "recorded"
                except CompareAndSwapConflict:
                    return "stale"
                raise AssertionError("blocked release unexpectedly advanced")

            with ThreadPoolExecutor(max_workers=2) as executor:
                results = tuple(
                    executor.map(record, (0, 1))
                )

            self.assertCountEqual(results, ("recorded", "stale"))
            events = SQLiteControlStore(path).list_release_events(
                owner_id="owner-a",
                release_id=RELEASE_ID,
            )
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].sequence, 1)

    def test_pointer_and_event_roll_back_together_when_append_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "control.sqlite3"
            control = SQLiteControlStore(path)
            governor = ReleaseGovernor(control)
            candidate = _projection_ref("a")
            with sqlite3.connect(path) as connection:
                connection.execute(
                    """
                    CREATE TRIGGER fail_release_event_insert
                    BEFORE INSERT ON release_events
                    BEGIN
                        SELECT RAISE(ABORT, 'injected release event failure');
                    END
                    """
                )

            with self.assertRaises(sqlite3.IntegrityError):
                _activate(
                    governor,
                    _manifest(PublicationStatus.RELEASE_CANDIDATE),
                    _evidence(candidate),
                    _observation(CanaryStage.SHADOW, 0),
                    expected_pointer_version=None,
                    expected_release_sequence=None,
                )

            self.assertIsNone(
                control.load_pointer(
                    owner_id="owner-a",
                    pointer_key=CANARY_POINTER_KEY,
                )
            )
            self.assertEqual(
                control.list_release_events(
                    owner_id="owner-a",
                    release_id=RELEASE_ID,
                ),
                (),
            )

    def test_rollback_pointer_and_event_are_one_transaction(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "control.sqlite3"
            control = SQLiteControlStore(path)
            governor = ReleaseGovernor(control)
            stable = _projection_ref("b")
            candidate = _projection_ref("a")
            control.compare_and_swap_pointer(
                owner_id="owner-a",
                pointer_key=PUBLISHED_POINTER_KEY,
                artifact_ref=stable,
                expected_version=None,
                now=NOW,
            )
            activation = _activate(
                governor,
                _manifest(PublicationStatus.RELEASE_CANDIDATE),
                _evidence(candidate),
                _observation(CanaryStage.SHADOW, 0),
                expected_pointer_version=None,
                expected_release_sequence=None,
            )
            with sqlite3.connect(path) as connection:
                connection.execute(
                    """
                    CREATE TRIGGER fail_rollback_event_insert
                    BEFORE INSERT ON release_events
                    WHEN NEW.event_type = 'rollback'
                    BEGIN
                        SELECT RAISE(ABORT, 'injected rollback event failure');
                    END
                    """
                )

            with self.assertRaises(sqlite3.IntegrityError):
                governor.rollback_candidate(
                    _evidence(candidate),
                    expected_canary_pointer_version=(
                        activation.pointer.version
                    ),
                    expected_release_sequence=activation.event.sequence,
                    reason_codes=("canary_serious_error",),
                    rolled_back_at=NOW,
                )

            self.assertEqual(
                control.load_pointer(
                    owner_id="owner-a",
                    pointer_key=CANARY_POINTER_KEY,
                ).artifact_ref,
                candidate,
            )
            self.assertEqual(
                control.list_release_events(
                    owner_id="owner-a",
                    release_id=RELEASE_ID,
                ),
                (activation.event,),
            )

    def test_release_event_hash_chain_detects_out_of_band_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "control.sqlite3"
            control = SQLiteControlStore(path)
            governor = ReleaseGovernor(control)
            with self.assertRaises(ReleaseGateBlocked) as raised:
                _activate(
                    governor,
                    _manifest(PublicationStatus.RELEASE_CANDIDATE),
                    _evidence(
                        _projection_ref("a"),
                        pilot=PilotGateDecision.INCOMPLETE,
                    ),
                    _observation(CanaryStage.SHADOW, 0),
                    expected_pointer_version=None,
                    expected_release_sequence=None,
                )
            event = raised.exception.event

            with sqlite3.connect(path) as connection:
                connection.execute(
                    "DROP TRIGGER release_events_no_update"
                )
                row = connection.execute(
                    """
                    SELECT event_json FROM release_events
                    WHERE event_id = ?
                    """,
                    (event.event_id,),
                ).fetchone()
                payload = json.loads(row[0])
                payload["decision"]["reason_codes"] = ["tampered"]
                connection.execute(
                    """
                    UPDATE release_events SET event_json = ?
                    WHERE event_id = ?
                    """,
                    (
                        json.dumps(
                            payload,
                            ensure_ascii=True,
                            separators=(",", ":"),
                            sort_keys=True,
                        ),
                        event.event_id,
                    ),
                )

            with self.assertRaisesRegex(
                ReleaseEventIntegrityError,
                "digest",
            ):
                control.list_release_events(
                    owner_id="owner-a",
                    release_id=RELEASE_ID,
                )


if __name__ == "__main__":
    unittest.main()
