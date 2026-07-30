from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator, model_validator

from .base import FrozenContract
from .common import (
    ArtifactRef,
    OwnerId,
    RegionId,
)
from .control import RunId
from .evidence import EvidenceRef


ReviewId = Annotated[
    str,
    StringConstraints(pattern=r"^review_[0-9a-f]{32}$"),
]
ReviewOptionId = Annotated[
    str,
    StringConstraints(pattern=r"^review_option_[0-9a-f]{32}$"),
]
ReviewDecisionId = Annotated[
    str,
    StringConstraints(pattern=r"^review_decision_[0-9a-f]{32}$"),
]
ReplayPlanId = Annotated[
    str,
    StringConstraints(pattern=r"^replay_plan_[0-9a-f]{32}$"),
]
HumanActor = Annotated[
    str,
    StringConstraints(pattern=r"^human:[A-Za-z0-9._:@-]{1,128}$"),
]
ReviewSubjectId = Annotated[
    str,
    StringConstraints(min_length=1, max_length=256),
]


class ReviewKind(StrEnum):
    ROOT = "root"
    REGION_STRUCTURE = "region_structure"
    PARENT_COMPETITION = "parent_competition"
    CROSS_BRANCH = "cross_branch"
    LABEL_GRANULARITY = "label_granularity"
    MERGE_SPLIT = "merge_split"
    VISUAL = "visual"
    CROSS_LINK = "cross_link"
    OMISSION = "omission"
    SOURCE_CORRECTION = "source_correction"


class ReviewAction(StrEnum):
    CONFIRM_CURRENT = "confirm_current"
    CHANGE_PARENT = "change_parent"
    NO_SUITABLE_PARENT = "no_suitable_parent"
    REJECT_CONCEPT = "reject_concept"
    RENAME_CONCEPT = "rename_concept"
    MERGE_CONCEPTS = "merge_concepts"
    SPLIT_CONCEPT = "split_concept"
    RECROP_VISUAL = "recrop_visual"
    CONFIRM_ROOT = "confirm_root"
    REQUEST_REGION_REPLAN = "request_region_replan"
    ACCEPT_CROSS_LINK = "accept_cross_link"
    REJECT_CROSS_LINK = "reject_cross_link"
    APPLY_SOURCE_CORRECTION = "apply_source_correction"


class ReviewStatus(StrEnum):
    PENDING = "pending"
    RESOLVED = "resolved"
    SUPERSEDED = "superseded"
    CANCELLED = "cancelled"


class ReplayStage(StrEnum):
    SOURCE_OBSERVATION = "source_observation"
    SOURCE_INVENTORY = "source_inventory"
    REGION_PLANNING = "region_planning"
    CLAIM_LEDGER = "claim_ledger"
    OMISSION_AUDIT = "omission_audit"
    CANONICAL_GRAPH = "canonical_graph"
    CROSS_LINKS = "cross_links"
    PROJECTION = "projection"
    EXPORTS = "exports"
    QUALITY = "quality"


class ReviewOption(FrozenContract):
    option_id: ReviewOptionId
    action: ReviewAction
    label: Annotated[
        str,
        StringConstraints(min_length=1, max_length=256),
    ]
    target_ids: tuple[ReviewSubjectId, ...] = ()

    @model_validator(mode="after")
    def validate_targets(self) -> "ReviewOption":
        if len(self.target_ids) != len(set(self.target_ids)):
            raise ValueError("review option target IDs must be unique")
        if self.target_ids != tuple(sorted(self.target_ids)):
            raise ValueError(
                "review option target IDs must use deterministic order"
            )
        return self


class ReviewTask(FrozenContract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    review_id: ReviewId
    owner_id: OwnerId
    run_id: RunId
    revision: int = Field(ge=1)
    review_kind: ReviewKind
    question: Annotated[
        str,
        StringConstraints(min_length=1, max_length=1024),
    ]
    subject_ids: tuple[ReviewSubjectId, ...] = Field(min_length=1)
    evidence_refs: tuple[EvidenceRef, ...] = Field(
        default=(),
        max_length=2,
    )
    options: tuple[ReviewOption, ...] = Field(
        min_length=2,
        max_length=3,
    )
    base_artifact_ref: ArtifactRef
    minimum_replan_region_id: RegionId | None = None
    status: ReviewStatus = ReviewStatus.PENDING
    resolution_decision_id: ReviewDecisionId | None = None
    created_at: datetime
    updated_at: datetime
    supersedes_revision: int | None = Field(default=None, ge=1)

    @field_validator("created_at", "updated_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("review timestamps require timezone")
        return value

    @model_validator(mode="after")
    def validate_task(self) -> "ReviewTask":
        if self.base_artifact_ref.owner_id != self.owner_id:
            raise ValueError("review base artifact must remain owner-scoped")
        if self.updated_at < self.created_at:
            raise ValueError("review updated_at cannot precede created_at")
        if len(self.subject_ids) != len(set(self.subject_ids)):
            raise ValueError("review subject IDs must be unique")
        if self.subject_ids != tuple(sorted(self.subject_ids)):
            raise ValueError(
                "review subject IDs must use deterministic order"
            )
        option_ids = [item.option_id for item in self.options]
        if len(option_ids) != len(set(option_ids)):
            raise ValueError("review option IDs must be unique")
        if option_ids != sorted(option_ids):
            raise ValueError(
                "review options must use deterministic option_id order"
            )
        for evidence in self.evidence_refs:
            if (
                evidence.artifact_ref
                and evidence.artifact_ref.owner_id != self.owner_id
            ):
                raise ValueError(
                    "review evidence artifacts must remain owner-scoped"
                )
        if self.revision == 1 and self.supersedes_revision is not None:
            raise ValueError(
                "initial review revision cannot supersede a revision"
            )
        if self.revision > 1 and self.supersedes_revision != (
            self.revision - 1
        ):
            raise ValueError(
                "review revisions must supersede the immediately prior "
                "revision"
            )
        if self.status is ReviewStatus.RESOLVED:
            if self.resolution_decision_id is None:
                raise ValueError(
                    "resolved review requires resolution_decision_id"
                )
        elif self.resolution_decision_id is not None:
            raise ValueError(
                "only resolved review may reference a resolution decision"
            )
        return self


class ReviewDecision(FrozenContract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    decision_id: ReviewDecisionId
    review_id: ReviewId
    owner_id: OwnerId
    run_id: RunId
    expected_review_revision: int = Field(ge=1)
    selected_option_id: ReviewOptionId
    action: ReviewAction
    target_ids: tuple[ReviewSubjectId, ...] = ()
    actor: HumanActor
    rationale: Annotated[
        str,
        StringConstraints(min_length=1, max_length=2048),
    ]
    evidence_refs: tuple[EvidenceRef, ...] = Field(
        default=(),
        max_length=2,
    )
    created_at: datetime
    supersedes: ReviewDecisionId | None = None

    @field_validator("created_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("review decision timestamp requires timezone")
        return value

    @model_validator(mode="after")
    def validate_decision(self) -> "ReviewDecision":
        if len(self.target_ids) != len(set(self.target_ids)):
            raise ValueError("review decision target IDs must be unique")
        if self.target_ids != tuple(sorted(self.target_ids)):
            raise ValueError(
                "review decision target IDs must use deterministic order"
            )
        for evidence in self.evidence_refs:
            if (
                evidence.artifact_ref
                and evidence.artifact_ref.owner_id != self.owner_id
            ):
                raise ValueError(
                    "decision evidence artifacts must remain owner-scoped"
                )
        if self.supersedes == self.decision_id:
            raise ValueError("review decision cannot supersede itself")
        return self


class AffectedReplayPlan(FrozenContract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    replay_plan_id: ReplayPlanId
    owner_id: OwnerId
    run_id: RunId
    review_id: ReviewId
    decision_id: ReviewDecisionId
    base_artifact_refs: tuple[ArtifactRef, ...] = Field(min_length=1)
    affected_concept_ids: tuple[ReviewSubjectId, ...] = ()
    affected_relation_ids: tuple[ReviewSubjectId, ...] = ()
    affected_source_ids: tuple[ReviewSubjectId, ...] = ()
    invalidated_stages: tuple[ReplayStage, ...] = Field(min_length=1)
    minimum_replan_region_id: RegionId | None = None
    preserve_human_decision_ids: tuple[ReviewDecisionId, ...]
    reason_codes: tuple[
        Annotated[str, StringConstraints(min_length=1, max_length=128)],
        ...,
    ]
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("replay plan timestamp requires timezone")
        return value

    @model_validator(mode="after")
    def validate_plan(self) -> "AffectedReplayPlan":
        if any(
            ref.owner_id != self.owner_id
            for ref in self.base_artifact_refs
        ):
            raise ValueError("replay plan artifacts must remain owner-scoped")
        for field_name, values in (
            ("affected_concept_ids", self.affected_concept_ids),
            ("affected_relation_ids", self.affected_relation_ids),
            ("affected_source_ids", self.affected_source_ids),
            (
                "preserve_human_decision_ids",
                self.preserve_human_decision_ids,
            ),
            ("reason_codes", self.reason_codes),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"{field_name} must not contain duplicates")
            if values != tuple(sorted(values)):
                raise ValueError(
                    f"{field_name} must use deterministic order"
                )
        if len(self.invalidated_stages) != len(
            set(self.invalidated_stages)
        ):
            raise ValueError("invalidated stages must be unique")
        if self.invalidated_stages != tuple(
            sorted(self.invalidated_stages, key=str)
        ):
            raise ValueError(
                "invalidated stages must use deterministic order"
            )
        return self
