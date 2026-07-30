from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator, model_validator

from .base import FrozenContract
from .common import (
    ArtifactProducerRef,
    ArtifactRef,
    OwnerId,
    RuntimeRole,
    SchemaId,
    SemVer,
    Sha256Digest,
    SourceId,
    StringValue,
)


RunId = Annotated[
    str,
    StringConstraints(pattern=r"^run_[0-9a-f]{32}$"),
]
ManifestId = Annotated[
    str,
    StringConstraints(pattern=r"^run_manifest_[0-9a-f]{32}$"),
]
AttestationId = Annotated[
    str,
    StringConstraints(pattern=r"^attestation_[0-9a-f]{32}$"),
]
StageKey = Annotated[
    str,
    StringConstraints(pattern=r"^[a-z][a-z0-9._:-]{1,127}$"),
]


class ExecutionStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_RETRY = "waiting_retry"
    WAITING_REVIEW = "waiting_review"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class QualityStatus(StrEnum):
    UNASSESSED = "unassessed"
    BLOCKED_DOCUMENT = "blocked_document"
    BLOCKED_CLAIM = "blocked_claim"
    BLOCKED_SEMANTIC = "blocked_semantic"
    BLOCKED_EVIDENCE = "blocked_evidence"
    REVIEW_REQUIRED = "review_required"
    PASSED = "passed"


class PublicationStatus(StrEnum):
    DRAFT = "draft"
    RELEASE_CANDIDATE = "release_candidate"
    PUBLISHED = "published"
    SUPERSEDED = "superseded"
    WITHDRAWN = "withdrawn"


class RunProfile(StrEnum):
    STANDARD = "standard"
    PRECISION = "precision"


class EvidenceMode(StrEnum):
    SOURCE_ONLY = "source_only"
    GROUNDED_ASSIST = "grounded_assist"
    ENRICHED_OVERLAY = "enriched_overlay"


class ReplayMode(StrEnum):
    LIVE = "live"
    RECORDED_RESPONSE_REPLAY = "recorded_response_replay"
    DETERMINISTIC_REPLAY = "deterministic_replay"
    MIGRATION_REPLAY = "migration_replay"
    FULL_RECOMPUTE = "full_recompute"


class StageCommitStatus(StrEnum):
    RUNNING = "running"
    COMMITTED = "committed"
    REUSED = "reused"
    FAILED = "failed"
    CANCELLED = "cancelled"


class QualityGateDecision(StrEnum):
    PASS = "pass"
    BLOCK = "block"
    REVIEW = "review"


class RunBudget(FrozenContract):
    max_wall_seconds: int = Field(ge=1)
    max_model_calls: int = Field(ge=0)
    max_search_queries: int = Field(ge=0)
    max_search_fetches: int = Field(ge=0)
    max_cost_microunits: int = Field(ge=0)
    vlm_concurrency: int = Field(ge=0)
    text_concurrency: int = Field(ge=0)
    search_concurrency: int = Field(ge=0)


class ModelSlot(FrozenContract):
    slot: Literal[
        "vlm_reader",
        "claim_extractor",
        "global_structure_planner",
        "recursive_region_planner",
        "region_decision_verifier",
        "verifier_a",
        "verifier_b",
        "arbiter",
        "tool_researcher",
    ]
    provider: Annotated[
        str,
        StringConstraints(min_length=1, max_length=128),
    ]
    model_revision: Annotated[
        str,
        StringConstraints(min_length=1, max_length=256),
    ]
    model_family: Annotated[
        str,
        StringConstraints(min_length=1, max_length=128),
    ]
    independence_group: Annotated[
        str,
        StringConstraints(min_length=1, max_length=128),
    ] | None = None
    independence_calibrated: bool = False
    context_limit: int = Field(ge=1)
    structured_output: bool
    region: Annotated[
        str,
        StringConstraints(min_length=1, max_length=128),
    ]
    price_input_microunits_per_million: int = Field(ge=0)
    price_output_microunits_per_million: int = Field(ge=0)
    calibration_score: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def validate_independence(self) -> "ModelSlot":
        if self.independence_calibrated and not self.independence_group:
            raise ValueError(
                "calibrated independence requires an independence_group"
            )
        return self


class ModelPortfolioManifest(FrozenContract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    slots: tuple[ModelSlot, ...] = ()

    @model_validator(mode="after")
    def unique_slots(self) -> "ModelPortfolioManifest":
        names = [slot.slot for slot in self.slots]
        if len(names) != len(set(names)):
            raise ValueError("model portfolio slots must be unique")
        return self


class DeclaredRunManifest(FrozenContract):
    source_hash: Sha256Digest
    profile: RunProfile
    evidence_mode: EvidenceMode
    no_egress: bool
    budget: RunBudget
    code_revision: Annotated[
        str,
        StringConstraints(min_length=1, max_length=256),
    ]
    image_digest: Sha256Digest | None = None
    dependency_digest: Sha256Digest
    parser_policy_digest: Sha256Digest
    renderer_policy_digest: Sha256Digest
    prompt_policy_digest: Sha256Digest
    tool_policy_digest: Sha256Digest
    search_policy_digest: Sha256Digest
    schema_digests: tuple[StringValue, ...]
    model_portfolio: ModelPortfolioManifest = ModelPortfolioManifest()
    random_seed: int = Field(ge=0)

    @model_validator(mode="after")
    def enforce_source_only_egress(self) -> "DeclaredRunManifest":
        if self.evidence_mode is EvidenceMode.SOURCE_ONLY and not self.no_egress:
            raise ValueError("source_only runs must be declared no_egress")
        return self


class ObservedStage(FrozenContract):
    stage_key: StageKey
    artifact_refs: tuple[ArtifactRef, ...] = ()
    metrics: tuple[StringValue, ...] = ()
    reused: bool = False


class ObservedRunManifest(FrozenContract):
    replay_mode: ReplayMode = ReplayMode.LIVE
    stages: tuple[ObservedStage, ...] = ()
    model_call_count: int = Field(default=0, ge=0)
    search_query_count: int = Field(default=0, ge=0)
    search_fetch_count: int = Field(default=0, ge=0)
    cost_microunits: int = Field(default=0, ge=0)
    degraded_components: tuple[str, ...] = ()
    search_snapshot_refs: tuple[str, ...] = ()

    @model_validator(mode="after")
    def unique_stages(self) -> "ObservedRunManifest":
        keys = [stage.stage_key for stage in self.stages]
        if len(keys) != len(set(keys)):
            raise ValueError("observed stages must be unique")
        return self


class RunManifest(FrozenContract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    manifest_id: ManifestId
    run_id: RunId
    revision: int = Field(ge=1)
    owner_id: OwnerId
    declared: DeclaredRunManifest
    observed: ObservedRunManifest = ObservedRunManifest()
    execution_status: ExecutionStatus = ExecutionStatus.QUEUED
    quality_status: QualityStatus = QualityStatus.UNASSESSED
    publication_status: PublicationStatus = PublicationStatus.DRAFT
    created_at: datetime
    updated_at: datetime
    supersedes: ManifestId | None = None

    @field_validator("created_at", "updated_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("run manifest timestamps require timezone")
        return value

    @model_validator(mode="after")
    def validate_statuses(self) -> "RunManifest":
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot precede created_at")
        if self.revision == 1 and self.supersedes is not None:
            raise ValueError("initial manifest cannot supersede another")
        if self.revision > 1 and self.supersedes is None:
            raise ValueError("manifest revision requires supersedes")
        if self.publication_status in {
            PublicationStatus.RELEASE_CANDIDATE,
            PublicationStatus.PUBLISHED,
        } and (
            self.execution_status is not ExecutionStatus.SUCCEEDED
            or self.quality_status is not QualityStatus.PASSED
        ):
            raise ValueError(
                "release candidate and published states require succeeded "
                "execution and passed quality"
            )
        return self


class StageCommit(FrozenContract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    run_id: RunId
    owner_id: OwnerId
    stage_key: StageKey
    idempotency_key: Sha256Digest
    input_digest: Sha256Digest
    policy_digest: Sha256Digest
    output_ref: ArtifactRef | None = None
    attempt: int = Field(ge=1)
    lease_epoch: int = Field(ge=0)
    status: StageCommitStatus
    metrics: tuple[StringValue, ...] = ()
    failure_code: str | None = Field(default=None, max_length=128)
    created_at: datetime
    updated_at: datetime

    @field_validator("created_at", "updated_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("stage commit timestamps require timezone")
        return value

    @model_validator(mode="after")
    def validate_commit(self) -> "StageCommit":
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot precede created_at")
        if self.status in {
            StageCommitStatus.COMMITTED,
            StageCommitStatus.REUSED,
        } and self.output_ref is None:
            raise ValueError("successful stage commit requires output_ref")
        if self.output_ref and self.output_ref.owner_id != self.owner_id:
            raise ValueError("stage output must remain owner-scoped")
        if self.status is StageCommitStatus.FAILED and not self.failure_code:
            raise ValueError("failed stage commit requires failure_code")
        if (
            self.status is not StageCommitStatus.FAILED
            and self.failure_code is not None
        ):
            raise ValueError("failure_code is valid only for failed stages")
        return self


class QualityMetric(FrozenContract):
    name: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    value: float
    threshold: float | None = None
    passed: bool | None = None


class QualityAttestation(FrozenContract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    attestation_id: AttestationId
    owner_id: OwnerId
    artifact_ref: ArtifactRef
    evaluator: ArtifactProducerRef
    policy_digest: Sha256Digest
    metrics: tuple[QualityMetric, ...]
    gate_decision: QualityGateDecision
    created_at: datetime
    supersedes: AttestationId | None = None

    @field_validator("created_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("quality attestation timestamp requires timezone")
        return value

    @model_validator(mode="after")
    def validate_attestation(self) -> "QualityAttestation":
        if self.artifact_ref.owner_id != self.owner_id:
            raise ValueError("attestation must remain owner-scoped")
        if self.evaluator.role is not RuntimeRole.QUALITY_AUDITOR:
            raise ValueError("attestation evaluator must be quality_auditor")
        return self


class TaskBudgetSlice(FrozenContract):
    max_wall_seconds: int = Field(ge=1)
    max_calls: int = Field(ge=0)
    max_cost_microunits: int = Field(ge=0)


class TaskEnvelope(FrozenContract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    artifact_version: SemVer
    source_ids: tuple[SourceId, ...]
    role_policy: RuntimeRole
    budget_slice: TaskBudgetSlice
    output_schema: SchemaId
    expected_artifact_version: SemVer
    idempotency_key: Sha256Digest
