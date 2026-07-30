from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime

from backend.vnext.artifacts.canonical import payload_digest
from backend.vnext.contracts.control import (
    PublicationStatus,
    RunManifest,
)
from backend.vnext.contracts.quality import PilotGateDecision
from backend.vnext.contracts.release import (
    CanaryDecision,
    CanaryObservation,
    CanaryPolicy,
    CanaryStage,
    CanaryStageRule,
    CanaryTransitionDecision,
    ReleaseEvent,
    ReleaseReadinessEvidence,
    RollbackRecord,
)

from .control_store import PointerRecord, SQLiteControlStore


CANARY_POINTER_KEY = "vnext:canary:projection"
PUBLISHED_POINTER_KEY = "vnext:published:projection"


class ReleaseGateBlocked(RuntimeError):
    def __init__(
        self,
        decision: CanaryTransitionDecision,
        event: ReleaseEvent,
    ):
        self.decision = decision
        self.event = event
        super().__init__(
            f"release transition {decision.decision.value}: "
            + ", ".join(decision.reason_codes)
        )


@dataclass(frozen=True, slots=True)
class ReleasePointerChange:
    decision: CanaryTransitionDecision
    pointer: PointerRecord
    event: ReleaseEvent


def default_canary_policy() -> CanaryPolicy:
    return CanaryPolicy(
        policy_version="public-canary-2026-07-29-v1",
        stage_rules=(
            CanaryStageRule(
                stage=CanaryStage.SHADOW,
                next_stage=CanaryStage.ALLOWLIST,
                traffic_percent=0,
                minimum_cumulative_samples=0,
            ),
            CanaryStageRule(
                stage=CanaryStage.ALLOWLIST,
                next_stage=CanaryStage.PERCENT_1,
                traffic_percent=1,
                minimum_cumulative_samples=50,
            ),
            CanaryStageRule(
                stage=CanaryStage.PERCENT_1,
                next_stage=CanaryStage.PERCENT_5,
                traffic_percent=5,
                minimum_cumulative_samples=100,
            ),
            CanaryStageRule(
                stage=CanaryStage.PERCENT_5,
                next_stage=CanaryStage.PERCENT_20,
                traffic_percent=20,
                minimum_cumulative_samples=200,
            ),
            CanaryStageRule(
                stage=CanaryStage.PERCENT_20,
                next_stage=CanaryStage.PERCENT_50,
                traffic_percent=50,
                minimum_cumulative_samples=300,
            ),
            CanaryStageRule(
                stage=CanaryStage.PERCENT_50,
                next_stage=CanaryStage.DEFAULT,
                traffic_percent=100,
                minimum_cumulative_samples=300,
            ),
        ),
    )


def evaluate_canary_transition(
    policy: CanaryPolicy,
    evidence: ReleaseReadinessEvidence,
    observation: CanaryObservation,
    *,
    decided_at: datetime | None = None,
) -> CanaryTransitionDecision:
    if observation.release_id != evidence.release_id:
        raise ValueError("canary observation references another release")
    timestamp = decided_at or datetime.now(UTC)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("decided_at must include a timezone")
    rule = next(
        (
            item
            for item in policy.stage_rules
            if item.stage is observation.stage
        ),
        None,
    )
    reasons: set[str] = set()
    safety_failures = {
        "severe_errors": observation.severe_errors,
        "gate_bypasses": observation.gate_bypasses,
        "cross_owner_reads": observation.cross_owner_reads,
        "rollback_failures": observation.rollback_failures,
        "quality_failed_public_results": (
            observation.quality_failed_public_results
        ),
    }
    reasons.update(
        f"safety_violation:{name}"
        for name, value in safety_failures.items()
        if value > 0
    )
    if reasons:
        decision = CanaryDecision.ROLLBACK
        to_stage = observation.stage
    else:
        reasons.update(_readiness_failures(policy, evidence, observation))
        if rule is None:
            reasons.add("no_further_canary_stage")
            decision = CanaryDecision.HOLD
            to_stage = observation.stage
        elif (
            observation.cumulative_samples
            < rule.minimum_cumulative_samples
        ):
            reasons.add(
                "cumulative_samples_below_minimum:"
                f"{observation.cumulative_samples}/"
                f"{rule.minimum_cumulative_samples}"
            )
            decision = CanaryDecision.HOLD
            to_stage = observation.stage
        elif reasons:
            decision = CanaryDecision.HOLD
            to_stage = observation.stage
        else:
            decision = CanaryDecision.ADVANCE
            to_stage = rule.next_stage
            reasons.add(f"advance_to:{to_stage.value}")

    decision_digest = hashlib.sha256(
        (
            "zlb-vnext-canary-decision-v1\0"
            + payload_digest(policy)
            + "\0"
            + payload_digest(evidence)
            + "\0"
            + payload_digest(observation)
            + "\0"
            + decision.value
        ).encode("utf-8")
    ).hexdigest()
    return CanaryTransitionDecision(
        decision_id="canary_decision_" + decision_digest[:32],
        release_id=evidence.release_id,
        from_stage=observation.stage,
        to_stage=to_stage,
        decision=decision,
        policy_digest=payload_digest(policy),
        evidence_digest=payload_digest(evidence),
        observation_digest=payload_digest(observation),
        reason_codes=tuple(sorted(reasons)),
        decided_at=timestamp,
    )


def _trusted_input_hold(
    policy: CanaryPolicy,
    evidence: ReleaseReadinessEvidence,
    observation: CanaryObservation,
    reason_codes: tuple[str, ...],
    *,
    decided_at: datetime | None = None,
) -> CanaryTransitionDecision:
    timestamp = decided_at or datetime.now(UTC)
    reasons = tuple(sorted(set(reason_codes)))
    decision_digest = hashlib.sha256(
        (
            "zlb-vnext-canary-trusted-input-hold-v1\0"
            + payload_digest(policy)
            + "\0"
            + payload_digest(evidence)
            + "\0"
            + payload_digest(observation)
            + "\0"
            + "\0".join(reasons)
        ).encode("utf-8")
    ).hexdigest()
    return CanaryTransitionDecision(
        decision_id="canary_decision_" + decision_digest[:32],
        release_id=evidence.release_id,
        from_stage=observation.stage,
        to_stage=observation.stage,
        decision=CanaryDecision.HOLD,
        policy_digest=payload_digest(policy),
        evidence_digest=payload_digest(evidence),
        observation_digest=payload_digest(observation),
        reason_codes=reasons,
        decided_at=timestamp,
    )


class ReleaseGovernor:
    def __init__(
        self,
        control_store: SQLiteControlStore,
        *,
        policy: CanaryPolicy | None = None,
    ):
        self.control_store = control_store
        self.policy = policy or default_canary_policy()

    def activate_candidate(
        self,
        manifest: RunManifest,
        evidence: ReleaseReadinessEvidence,
        observation: CanaryObservation,
        *,
        expected_pointer_version: int | None,
        expected_release_sequence: int | None,
    ) -> ReleasePointerChange:
        (
            trusted_manifest,
            trusted_evidence,
            trusted_observation,
            trust_failures,
        ) = self._trusted_inputs(manifest, evidence, observation)
        if trust_failures:
            self._block_untrusted_transition(
                evidence,
                observation,
                trust_failures,
                expected_release_sequence=expected_release_sequence,
            )
        assert trusted_manifest is not None
        assert trusted_evidence is not None
        assert trusted_observation is not None
        self._validate_manifest(trusted_manifest, trusted_evidence)
        if trusted_manifest.publication_status is not (
            PublicationStatus.RELEASE_CANDIDATE
        ):
            raise ValueError(
                "canary activation requires release_candidate manifest"
            )
        decision = evaluate_canary_transition(
            self.policy,
            trusted_evidence,
            trusted_observation,
        )
        if (
            decision.decision is not CanaryDecision.ADVANCE
            or decision.to_stage is not CanaryStage.ALLOWLIST
        ):
            event = self.control_store.append_release_decision(
                owner_id=evidence.owner_id,
                decision=decision,
                expected_release_sequence=expected_release_sequence,
            )
            raise ReleaseGateBlocked(
                self._recorded_decision(event),
                event,
            )
        pointer, event = (
            self.control_store.publish_pointer_with_release_decision(
                trusted_manifest,
                decision,
                pointer_key=CANARY_POINTER_KEY,
                artifact_ref=trusted_evidence.candidate_projection_ref,
                expected_pointer_version=expected_pointer_version,
                expected_release_sequence=expected_release_sequence,
            )
        )
        return ReleasePointerChange(
            decision=self._recorded_decision(event),
            pointer=pointer,
            event=event,
        )

    def promote_default(
        self,
        manifest: RunManifest,
        evidence: ReleaseReadinessEvidence,
        observation: CanaryObservation,
        *,
        expected_pointer_version: int | None,
        expected_release_sequence: int | None,
    ) -> ReleasePointerChange:
        (
            trusted_manifest,
            trusted_evidence,
            trusted_observation,
            trust_failures,
        ) = self._trusted_inputs(manifest, evidence, observation)
        if trust_failures:
            self._block_untrusted_transition(
                evidence,
                observation,
                trust_failures,
                expected_release_sequence=expected_release_sequence,
            )
        assert trusted_manifest is not None
        assert trusted_evidence is not None
        assert trusted_observation is not None
        self._validate_manifest(trusted_manifest, trusted_evidence)
        if trusted_manifest.publication_status is not (
            PublicationStatus.PUBLISHED
        ):
            raise ValueError(
                "default promotion requires published manifest"
            )
        decision = evaluate_canary_transition(
            self.policy,
            trusted_evidence,
            trusted_observation,
        )
        if (
            decision.decision is not CanaryDecision.ADVANCE
            or decision.to_stage is not CanaryStage.DEFAULT
        ):
            event = self.control_store.append_release_decision(
                owner_id=evidence.owner_id,
                decision=decision,
                expected_release_sequence=expected_release_sequence,
            )
            raise ReleaseGateBlocked(
                self._recorded_decision(event),
                event,
            )
        pointer, event = (
            self.control_store.publish_pointer_with_release_decision(
                trusted_manifest,
                decision,
                pointer_key=PUBLISHED_POINTER_KEY,
                artifact_ref=trusted_evidence.candidate_projection_ref,
                expected_pointer_version=expected_pointer_version,
                expected_release_sequence=expected_release_sequence,
            )
        )
        return ReleasePointerChange(
            decision=self._recorded_decision(event),
            pointer=pointer,
            event=event,
        )

    def rollback_candidate(
        self,
        evidence: ReleaseReadinessEvidence,
        *,
        expected_canary_pointer_version: int,
        expected_release_sequence: int | None,
        reason_codes: tuple[str, ...],
        rolled_back_at: datetime | None = None,
    ) -> RollbackRecord:
        if not reason_codes:
            raise ValueError("rollback requires reason codes")
        trusted_evidence = (
            self.control_store.load_release_readiness_evidence(
                owner_id=evidence.owner_id,
                release_id=evidence.release_id,
            )
        )
        if trusted_evidence is None or trusted_evidence != evidence:
            raise ValueError(
                "rollback requires trusted release readiness evidence"
            )
        timestamp = rolled_back_at or datetime.now(UTC)
        _, rollback, _ = (
            self.control_store.rollback_pointer_with_release_event(
                owner_id=evidence.owner_id,
                release_id=evidence.release_id,
                candidate_artifact_ref=(
                    trusted_evidence.candidate_projection_ref
                ),
                pointer_key=CANARY_POINTER_KEY,
                stable_pointer_key=PUBLISHED_POINTER_KEY,
                expected_pointer_version=(
                    expected_canary_pointer_version
                ),
                expected_release_sequence=expected_release_sequence,
                reason_codes=reason_codes,
                rolled_back_at=timestamp,
            )
        )
        return rollback

    def _trusted_inputs(
        self,
        manifest: RunManifest,
        evidence: ReleaseReadinessEvidence,
        observation: CanaryObservation,
    ) -> tuple[
        RunManifest | None,
        ReleaseReadinessEvidence | None,
        CanaryObservation | None,
        tuple[str, ...],
    ]:
        failures: list[str] = []
        trusted_evidence = (
            self.control_store.load_release_readiness_evidence(
                owner_id=evidence.owner_id,
                release_id=evidence.release_id,
            )
        )
        if trusted_evidence is None:
            failures.append("trusted_release_evidence_missing")
        elif trusted_evidence != evidence:
            failures.append("trusted_release_evidence_mismatch")
        trusted_observation = self.control_store.load_canary_observation(
            owner_id=evidence.owner_id,
            release_id=evidence.release_id,
            stage=observation.stage,
            observation_digest=payload_digest(observation),
        )
        if trusted_observation is None:
            failures.append("trusted_canary_observation_missing")
        elif trusted_observation != observation:
            failures.append("trusted_canary_observation_mismatch")
        trusted_manifest = self.control_store.load_run(
            evidence.run_id,
            owner_id=evidence.owner_id,
        )
        if trusted_manifest is None:
            failures.append("trusted_run_manifest_missing")
        elif trusted_manifest != manifest:
            failures.append("trusted_run_manifest_mismatch")
        return (
            trusted_manifest,
            trusted_evidence,
            trusted_observation,
            tuple(sorted(failures)),
        )

    def _block_untrusted_transition(
        self,
        evidence: ReleaseReadinessEvidence,
        observation: CanaryObservation,
        reason_codes: tuple[str, ...],
        *,
        expected_release_sequence: int | None,
    ) -> None:
        decision = _trusted_input_hold(
            self.policy,
            evidence,
            observation,
            reason_codes,
        )
        event = self.control_store.append_release_decision(
            owner_id=evidence.owner_id,
            decision=decision,
            expected_release_sequence=expected_release_sequence,
        )
        raise ReleaseGateBlocked(
            self._recorded_decision(event),
            event,
        )

    @staticmethod
    def _validate_manifest(
        manifest: RunManifest,
        evidence: ReleaseReadinessEvidence,
    ) -> None:
        if (
            manifest.owner_id != evidence.owner_id
            or manifest.run_id != evidence.run_id
        ):
            raise ValueError(
                "release evidence does not match run manifest"
            )

    @staticmethod
    def _recorded_decision(
        event: ReleaseEvent,
    ) -> CanaryTransitionDecision:
        if event.decision is None:
            raise RuntimeError(
                "release decision event has no recorded decision"
            )
        return event.decision


def _readiness_failures(
    policy: CanaryPolicy,
    evidence: ReleaseReadinessEvidence,
    observation: CanaryObservation,
) -> set[str]:
    failures: set[str] = set()
    if (
        policy.require_pilot_pass
        and evidence.pilot_gate_decision is not PilotGateDecision.PASS
    ):
        failures.add("pilot_gate_not_passed")
    if (
        policy.require_public_api_approval
        and not evidence.public_api_approved
    ):
        failures.add("public_api_not_approved")
    if (
        policy.require_diagnostic_ux
        and not evidence.diagnostic_ux_passed
    ):
        failures.add("diagnostic_ux_not_passed")
    if (
        policy.require_rollback_drill
        and not evidence.rollback_drill_passed
    ):
        failures.add("rollback_drill_not_passed")
    if (
        policy.require_blind_set_expansion
        and not evidence.blind_set_expanded
    ):
        failures.add("blind_set_not_expanded")
    if (
        observation.stage is CanaryStage.PERCENT_50
        and policy.require_disaster_recovery_for_default
        and not evidence.disaster_recovery_passed
    ):
        failures.add("disaster_recovery_not_passed")
    return failures
