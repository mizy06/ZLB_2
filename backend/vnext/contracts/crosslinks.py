from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from .base import FrozenContract
from .common import (
    ArtifactProducerRef,
    ArtifactRef,
    ClaimId,
    ConceptId,
    OwnerId,
)
from .evidence import (
    EvidenceNamespace,
    EvidenceRef,
    require_evidence_namespace,
)
from .graph import SemanticRelation, VerifierDecision


CrossLinkLedgerId = Annotated[
    str,
    StringConstraints(pattern=r"^cross_link_ledger_[0-9a-f]{32}$"),
]
CrossLinkResolutionLedgerId = Annotated[
    str,
    StringConstraints(
        pattern=r"^cross_link_resolution_ledger_[0-9a-f]{32}$"
    ),
]
CrossLinkProposalId = Annotated[
    str,
    StringConstraints(pattern=r"^cross_link_[0-9a-f]{32}$"),
]

_HIERARCHY_RELATIONS = frozenset(
    {
        SemanticRelation.TOPIC_CONTAINS,
        SemanticRelation.IS_A,
        SemanticRelation.PART_OF,
        SemanticRelation.STAGE_OF,
        SemanticRelation.EXAMPLE_OF,
    }
)


class CrossLinkRisk(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class CrossLinkResolutionStatus(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    ABSTAINED = "abstained"
    NEEDS_REVIEW = "needs_review"


class CrossLinkProposal(FrozenContract):
    proposal_id: CrossLinkProposalId
    source_id: ConceptId
    target_id: ConceptId
    semantic_relation: SemanticRelation
    source_claim_ids: tuple[ClaimId, ...] = ()
    courseware_evidence_refs: tuple[EvidenceRef, ...] = ()
    external_evidence_refs: tuple[EvidenceRef, ...] = ()
    risk: CrossLinkRisk
    reason_codes: tuple[
        Annotated[str, StringConstraints(min_length=1, max_length=128)],
        ...,
    ]

    @model_validator(mode="after")
    def validate_proposal(self) -> "CrossLinkProposal":
        if self.source_id == self.target_id:
            raise ValueError("cross-link proposal cannot be a self-loop")
        if self.semantic_relation in _HIERARCHY_RELATIONS:
            raise ValueError(
                "cross-link proposal cannot use a hierarchy relation"
            )
        require_evidence_namespace(
            self.courseware_evidence_refs,
            frozenset(
                {EvidenceNamespace.COURSEWARE, EvidenceNamespace.HUMAN}
            ),
            field_name="cross-link courseware evidence",
        )
        require_evidence_namespace(
            self.external_evidence_refs,
            frozenset({EvidenceNamespace.EXTERNAL}),
            field_name="cross-link external evidence",
        )
        if len(self.reason_codes) != len(set(self.reason_codes)):
            raise ValueError(
                "cross-link proposal reason codes must be unique"
            )
        if self.reason_codes != tuple(sorted(self.reason_codes)):
            raise ValueError(
                "cross-link proposal reason codes must use "
                "deterministic order"
            )
        return self


class CrossLinkProposalLedger(FrozenContract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    ledger_id: CrossLinkLedgerId
    owner_id: OwnerId
    canonical_graph_ref: ArtifactRef
    proposer: ArtifactProducerRef
    proposals: tuple[CrossLinkProposal, ...] = ()

    @model_validator(mode="after")
    def validate_ledger(self) -> "CrossLinkProposalLedger":
        if self.canonical_graph_ref.owner_id != self.owner_id:
            raise ValueError(
                "cross-link proposal ledger must remain owner-scoped"
            )
        if self.canonical_graph_ref.artifact_type.value != (
            "canonical_explicit_graph"
        ):
            raise ValueError(
                "cross-link proposal ledger requires canonical graph"
            )
        proposal_ids = [item.proposal_id for item in self.proposals]
        if len(proposal_ids) != len(set(proposal_ids)):
            raise ValueError("cross-link proposal IDs must be unique")
        if proposal_ids != sorted(proposal_ids):
            raise ValueError(
                "cross-link proposals must use deterministic ID order"
            )
        return self


class CrossLinkResolution(FrozenContract):
    proposal_id: CrossLinkProposalId
    status: CrossLinkResolutionStatus
    direction_verified: bool
    verifier_decisions: tuple[VerifierDecision, ...] = ()
    reason_codes: tuple[
        Annotated[str, StringConstraints(min_length=1, max_length=128)],
        ...,
    ]

    @model_validator(mode="after")
    def validate_resolution(self) -> "CrossLinkResolution":
        if len(self.reason_codes) != len(set(self.reason_codes)):
            raise ValueError(
                "cross-link resolution reason codes must be unique"
            )
        if self.reason_codes != tuple(sorted(self.reason_codes)):
            raise ValueError(
                "cross-link resolution reason codes must use "
                "deterministic order"
            )
        if self.status is CrossLinkResolutionStatus.ACCEPTED:
            if not self.direction_verified:
                raise ValueError(
                    "accepted cross-link requires verified direction"
                )
            if not self.verifier_decisions or not all(
                decision.supports_relation
                for decision in self.verifier_decisions
            ):
                raise ValueError(
                    "accepted cross-link requires supporting verifier votes"
                )
        elif not self.reason_codes:
            raise ValueError(
                "non-accepted cross-link resolution requires reason codes"
            )
        return self


class CrossLinkResolutionLedger(FrozenContract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    ledger_id: CrossLinkResolutionLedgerId
    owner_id: OwnerId
    proposal_ledger_id: CrossLinkLedgerId
    canonical_graph_ref: ArtifactRef
    precision_mode: bool = False
    resolutions: tuple[CrossLinkResolution, ...] = ()

    @model_validator(mode="after")
    def validate_ledger(self) -> "CrossLinkResolutionLedger":
        if self.canonical_graph_ref.owner_id != self.owner_id:
            raise ValueError(
                "cross-link resolution ledger must remain owner-scoped"
            )
        resolution_ids = [
            item.proposal_id for item in self.resolutions
        ]
        if len(resolution_ids) != len(set(resolution_ids)):
            raise ValueError(
                "cross-link resolutions must be unique per proposal"
            )
        if resolution_ids != sorted(resolution_ids):
            raise ValueError(
                "cross-link resolutions must use deterministic order"
            )
        return self
