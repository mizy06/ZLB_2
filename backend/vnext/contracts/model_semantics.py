from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from .base import FrozenContract
from .claims import ClaimType, InstructionalRole
from .common import SourceId
from .regions import RegionProposalAction


CLAIM_PROPOSAL_BATCH_SCHEMA_ID = (
    "urn:zlb:vnext:schema:claim-proposal-batch:1.0.0"
)
REGION_PLANNER_PROPOSAL_SCHEMA_ID = (
    "urn:zlb:vnext:schema:region-planner-proposal:1.0.0"
)
REGION_DECISION_VERIFICATION_SCHEMA_ID = (
    "urn:zlb:vnext:schema:region-decision-verification:1.0.0"
)


class ClaimProposal(FrozenContract):
    source_id: SourceId
    source_quote: Annotated[
        str,
        StringConstraints(min_length=1, max_length=8192),
    ]
    claim_type: ClaimType
    instructional_role: InstructionalRole
    predicate: Annotated[
        str,
        StringConstraints(min_length=1, max_length=512),
    ]


class ClaimProposalBatch(FrozenContract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    proposals: tuple[ClaimProposal, ...] = Field(
        default=(),
        max_length=256,
    )
    unresolved_source_ids: tuple[SourceId, ...] = Field(
        default=(),
        max_length=256,
    )

    @model_validator(mode="after")
    def validate_partition(self) -> "ClaimProposalBatch":
        proposal_keys = [
            (
                item.source_id,
                item.source_quote,
                item.claim_type.value,
                item.predicate,
            )
            for item in self.proposals
        ]
        if len(proposal_keys) != len(set(proposal_keys)):
            raise ValueError("claim proposals must be unique")
        if len(self.unresolved_source_ids) != len(
            set(self.unresolved_source_ids)
        ):
            raise ValueError("unresolved source IDs must be unique")
        overlap = {
            item.source_id for item in self.proposals
        } & set(self.unresolved_source_ids)
        if overlap:
            raise ValueError(
                "a source cannot be both proposed and unresolved: "
                + ", ".join(sorted(overlap))
            )
        return self


class RegionVerificationVerdict(StrEnum):
    ACCEPT = "accept"
    REJECT = "reject"
    UNRESOLVED = "unresolved"


class RegionStopSemanticAssessment(FrozenContract):
    single_instructional_intent: bool
    claims_have_comparable_granularity: bool
    further_split_would_fragment_or_duplicate: bool
    no_mixed_theme_evidence: bool


class RegionSplitSemanticAssessment(FrozenContract):
    parent_common_concept_supported: bool
    child_labels_self_contained: bool
    sibling_separation: bool
    within_region_cohesion: bool
    sibling_granularity_comparable: bool
    boundaries_explainable: bool


class RegionPlannerProposal(FrozenContract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    anchor_source_id: SourceId
    anchor_quote: Annotated[
        str,
        StringConstraints(min_length=1, max_length=512),
    ]
    action: RegionProposalAction
    child_anchor_source_ids: tuple[SourceId, ...] = Field(
        default=(),
        max_length=64,
    )
    stop_assessment: RegionStopSemanticAssessment | None = None
    rationale: Annotated[
        str,
        StringConstraints(min_length=1, max_length=4096),
    ]

    @model_validator(mode="after")
    def validate_shape(self) -> "RegionPlannerProposal":
        if len(self.child_anchor_source_ids) != len(
            set(self.child_anchor_source_ids)
        ):
            raise ValueError("region proposal child anchors must be unique")
        if self.action is RegionProposalAction.SPLIT:
            if len(self.child_anchor_source_ids) < 2:
                raise ValueError(
                    "SPLIT proposal requires at least two child anchors"
                )
            if self.stop_assessment is not None:
                raise ValueError(
                    "SPLIT proposal cannot include stop assessment"
                )
        elif self.action is RegionProposalAction.STOP:
            if self.child_anchor_source_ids:
                raise ValueError(
                    "STOP proposal cannot include child anchors"
                )
            if self.stop_assessment is None:
                raise ValueError(
                    "STOP proposal requires stop assessment"
                )
        else:
            if self.child_anchor_source_ids:
                raise ValueError(
                    "UNRESOLVED proposal cannot include child anchors"
                )
            if self.stop_assessment is not None:
                raise ValueError(
                    "UNRESOLVED proposal cannot include stop assessment"
                )
        return self


class RegionDecisionVerification(FrozenContract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    anchor_source_id: SourceId
    action: RegionProposalAction
    verdict: RegionVerificationVerdict
    supporting_source_ids: tuple[SourceId, ...] = Field(
        min_length=1,
        max_length=256,
    )
    split_assessment: RegionSplitSemanticAssessment | None = None
    stop_assessment: RegionStopSemanticAssessment | None = None
    rationale: Annotated[
        str,
        StringConstraints(min_length=1, max_length=4096),
    ]

    @model_validator(mode="after")
    def validate_shape(self) -> "RegionDecisionVerification":
        if len(self.supporting_source_ids) != len(
            set(self.supporting_source_ids)
        ):
            raise ValueError(
                "region verification supporting sources must be unique"
            )
        if self.action is RegionProposalAction.SPLIT:
            if (
                self.split_assessment is None
                or self.stop_assessment is not None
            ):
                raise ValueError(
                    "SPLIT verification requires only split assessment"
                )
            checks = tuple(
                self.split_assessment.model_dump(mode="python").values()
            )
        elif self.action is RegionProposalAction.STOP:
            if (
                self.stop_assessment is None
                or self.split_assessment is not None
            ):
                raise ValueError(
                    "STOP verification requires only stop assessment"
                )
            checks = tuple(
                self.stop_assessment.model_dump(mode="python").values()
            )
        else:
            raise ValueError(
                "UNRESOLVED planner proposals are not independently verified"
            )
        if self.verdict is RegionVerificationVerdict.ACCEPT:
            if not all(checks):
                raise ValueError(
                    "accepted region verification requires all checks"
                )
        elif self.verdict is RegionVerificationVerdict.REJECT:
            if all(checks):
                raise ValueError(
                    "rejected region verification requires a failed check"
                )
        return self
