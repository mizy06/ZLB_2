from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator, model_validator

from .base import FrozenContract
from .common import ArtifactRef, OwnerId, Sha256Digest
from .control import RunId
from .quality import PilotGateDecision


ReleaseId = Annotated[
    str,
    StringConstraints(pattern=r"^release_[0-9a-f]{32}$"),
]
CanaryDecisionId = Annotated[
    str,
    StringConstraints(pattern=r"^canary_decision_[0-9a-f]{32}$"),
]
RollbackId = Annotated[
    str,
    StringConstraints(pattern=r"^rollback_[0-9a-f]{32}$"),
]
ReleaseEventId = Annotated[
    str,
    StringConstraints(pattern=r"^release_event_[0-9a-f]{32}$"),
]


class CanaryStage(StrEnum):
    SHADOW = "shadow"
    ALLOWLIST = "allowlist"
    PERCENT_1 = "percent_1"
    PERCENT_5 = "percent_5"
    PERCENT_20 = "percent_20"
    PERCENT_50 = "percent_50"
    DEFAULT = "default"


class CanaryDecision(StrEnum):
    HOLD = "hold"
    ADVANCE = "advance"
    ROLLBACK = "rollback"


class ReleaseEventType(StrEnum):
    CANARY_DECISION = "canary_decision"
    ROLLBACK = "rollback"


class CanaryStageRule(FrozenContract):
    stage: CanaryStage
    next_stage: CanaryStage
    traffic_percent: int = Field(ge=0, le=100)
    minimum_cumulative_samples: int = Field(ge=0)


class CanaryPolicy(FrozenContract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    policy_version: Annotated[
        str,
        StringConstraints(min_length=1, max_length=128),
    ]
    stage_rules: tuple[CanaryStageRule, ...]
    require_pilot_pass: bool = True
    require_public_api_approval: bool = True
    require_diagnostic_ux: bool = True
    require_rollback_drill: bool = True
    require_blind_set_expansion: bool = True
    require_disaster_recovery_for_default: bool = True

    @model_validator(mode="after")
    def validate_rules(self) -> "CanaryPolicy":
        stages = [item.stage for item in self.stage_rules]
        if len(stages) != len(set(stages)):
            raise ValueError("canary policy stages must be unique")
        if stages != sorted(stages, key=_stage_order):
            raise ValueError(
                "canary stage rules must use deterministic stage order"
            )
        for rule in self.stage_rules:
            if _stage_order(rule.next_stage) != _stage_order(rule.stage) + 1:
                raise ValueError(
                    "canary rules must advance exactly one stage"
                )
        return self


class ReleaseReadinessEvidence(FrozenContract):
    release_id: ReleaseId
    owner_id: OwnerId
    run_id: RunId
    candidate_projection_ref: ArtifactRef
    pilot_report_digest: Sha256Digest
    pilot_gate_decision: PilotGateDecision
    public_api_approved: bool
    diagnostic_ux_passed: bool
    rollback_drill_passed: bool
    blind_set_expanded: bool
    disaster_recovery_passed: bool
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("release evidence timestamp requires timezone")
        return value

    @model_validator(mode="after")
    def validate_owner(self) -> "ReleaseReadinessEvidence":
        if self.candidate_projection_ref.owner_id != self.owner_id:
            raise ValueError(
                "release candidate artifact must remain owner-scoped"
            )
        if self.candidate_projection_ref.artifact_type.value != (
            "diagnostic_projection"
        ):
            raise ValueError(
                "release candidate must reference a projection artifact"
            )
        return self


class CanaryObservation(FrozenContract):
    release_id: ReleaseId
    stage: CanaryStage
    cumulative_samples: int = Field(ge=0)
    severe_errors: int = Field(ge=0)
    gate_bypasses: int = Field(ge=0)
    cross_owner_reads: int = Field(ge=0)
    rollback_failures: int = Field(ge=0)
    quality_failed_public_results: int = Field(ge=0)
    observed_at: datetime

    @field_validator("observed_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("canary observation timestamp requires timezone")
        return value


class CanaryTransitionDecision(FrozenContract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    decision_id: CanaryDecisionId
    release_id: ReleaseId
    from_stage: CanaryStage
    to_stage: CanaryStage
    decision: CanaryDecision
    policy_digest: Sha256Digest
    evidence_digest: Sha256Digest
    observation_digest: Sha256Digest
    reason_codes: tuple[
        Annotated[str, StringConstraints(min_length=1, max_length=128)],
        ...,
    ]
    decided_at: datetime

    @field_validator("decided_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("canary decision timestamp requires timezone")
        return value

    @model_validator(mode="after")
    def validate_transition(self) -> "CanaryTransitionDecision":
        if len(self.reason_codes) != len(set(self.reason_codes)):
            raise ValueError("canary reason codes must be unique")
        if self.reason_codes != tuple(sorted(self.reason_codes)):
            raise ValueError(
                "canary reason codes must use deterministic order"
            )
        if self.decision is CanaryDecision.ADVANCE:
            if _stage_order(self.to_stage) != (
                _stage_order(self.from_stage) + 1
            ):
                raise ValueError(
                    "advance decision must move exactly one stage"
                )
        elif self.to_stage is not self.from_stage:
            raise ValueError(
                "hold and rollback decisions retain the current stage"
            )
        return self


class RollbackRecord(FrozenContract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    rollback_id: RollbackId
    release_id: ReleaseId
    owner_id: OwnerId
    from_artifact_ref: ArtifactRef
    restored_artifact_ref: ArtifactRef
    pointer_key: Annotated[
        str,
        StringConstraints(min_length=1, max_length=256),
    ]
    pointer_version: int = Field(ge=1)
    reason_codes: tuple[
        Annotated[str, StringConstraints(min_length=1, max_length=128)],
        ...,
    ] = Field(min_length=1)
    rolled_back_at: datetime

    @field_validator("rolled_back_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("rollback timestamp requires timezone")
        return value

    @model_validator(mode="after")
    def validate_rollback(self) -> "RollbackRecord":
        if (
            self.from_artifact_ref.owner_id != self.owner_id
            or self.restored_artifact_ref.owner_id != self.owner_id
        ):
            raise ValueError("rollback artifacts must remain owner-scoped")
        if self.from_artifact_ref == self.restored_artifact_ref:
            raise ValueError(
                "rollback must restore a different artifact reference"
            )
        if len(self.reason_codes) != len(set(self.reason_codes)):
            raise ValueError("rollback reason codes must be unique")
        if self.reason_codes != tuple(sorted(self.reason_codes)):
            raise ValueError(
                "rollback reason codes must use deterministic order"
            )
        return self


class ReleasePointerSnapshot(FrozenContract):
    pointer_key: Annotated[
        str,
        StringConstraints(min_length=1, max_length=256),
    ]
    artifact_ref: ArtifactRef
    version: int = Field(ge=1)
    updated_at: datetime

    @field_validator("updated_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("release pointer timestamp requires timezone")
        return value


class ReleaseEvent(FrozenContract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    event_id: ReleaseEventId
    owner_id: OwnerId
    release_id: ReleaseId
    sequence: int = Field(ge=1)
    event_type: ReleaseEventType
    previous_event_digest: Sha256Digest | None = None
    event_digest: Sha256Digest
    decision: CanaryTransitionDecision | None = None
    rollback: RollbackRecord | None = None
    pointer_before: ReleasePointerSnapshot | None = None
    pointer_after: ReleasePointerSnapshot | None = None
    recorded_at: datetime

    @field_validator("recorded_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("release event timestamp requires timezone")
        return value

    @model_validator(mode="after")
    def validate_event(self) -> "ReleaseEvent":
        if self.sequence == 1:
            if self.previous_event_digest is not None:
                raise ValueError(
                    "first release event cannot reference a predecessor"
                )
        elif self.previous_event_digest is None:
            raise ValueError(
                "release event after sequence 1 requires predecessor digest"
            )
        for pointer in (self.pointer_before, self.pointer_after):
            if (
                pointer is not None
                and pointer.artifact_ref.owner_id != self.owner_id
            ):
                raise ValueError(
                    "release event pointers must remain owner-scoped"
                )
        if self.event_type is ReleaseEventType.CANARY_DECISION:
            self._validate_decision_event()
        else:
            self._validate_rollback_event()
        return self

    def _validate_decision_event(self) -> None:
        if self.decision is None or self.rollback is not None:
            raise ValueError(
                "canary decision event requires only a decision"
            )
        if self.decision.release_id != self.release_id:
            raise ValueError(
                "release event decision references another release"
            )
        if self.recorded_at != self.decision.decided_at:
            raise ValueError(
                "decision event timestamp must match the decision"
            )
        if self.decision.decision is not CanaryDecision.ADVANCE:
            if (
                self.pointer_before is not None
                or self.pointer_after is not None
            ):
                raise ValueError(
                    "blocked decision event cannot change a pointer"
                )
            return
        if self.pointer_after is None:
            raise ValueError(
                "advance decision event requires the resulting pointer"
            )
        if self.pointer_before is None:
            if self.pointer_after.version != 1:
                raise ValueError(
                    "new release pointer must start at version 1"
                )
            return
        if (
            self.pointer_before.pointer_key
            != self.pointer_after.pointer_key
        ):
            raise ValueError(
                "release pointer snapshots must use the same key"
            )
        if self.pointer_after.version != self.pointer_before.version + 1:
            raise ValueError(
                "release pointer version must increment exactly once"
            )

    def _validate_rollback_event(self) -> None:
        if self.rollback is None or self.decision is not None:
            raise ValueError("rollback event requires only a rollback record")
        if (
            self.rollback.owner_id != self.owner_id
            or self.rollback.release_id != self.release_id
        ):
            raise ValueError(
                "release event rollback owner or release mismatch"
            )
        if self.recorded_at != self.rollback.rolled_back_at:
            raise ValueError(
                "rollback event timestamp must match the rollback record"
            )
        if self.pointer_before is None or self.pointer_after is None:
            raise ValueError(
                "rollback event requires pointer snapshots"
            )
        if (
            self.pointer_before.pointer_key
            != self.rollback.pointer_key
            or self.pointer_after.pointer_key
            != self.rollback.pointer_key
        ):
            raise ValueError(
                "rollback pointer snapshots must match the rollback key"
            )
        if (
            self.pointer_before.artifact_ref
            != self.rollback.from_artifact_ref
            or self.pointer_after.artifact_ref
            != self.rollback.restored_artifact_ref
        ):
            raise ValueError(
                "rollback pointer snapshots must match rollback artifacts"
            )
        if self.pointer_after.version != self.rollback.pointer_version:
            raise ValueError(
                "rollback event pointer version mismatch"
            )
        if self.pointer_after.version != self.pointer_before.version + 1:
            raise ValueError(
                "rollback pointer version must increment exactly once"
            )


def _stage_order(stage: CanaryStage) -> int:
    return (
        CanaryStage.SHADOW,
        CanaryStage.ALLOWLIST,
        CanaryStage.PERCENT_1,
        CanaryStage.PERCENT_5,
        CanaryStage.PERCENT_20,
        CanaryStage.PERCENT_50,
        CanaryStage.DEFAULT,
    ).index(stage)
