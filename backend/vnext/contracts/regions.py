from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from .base import FrozenContract
from .common import (
    ArtifactProducerRef,
    ArtifactRef,
    ArtifactType,
    RegionId,
    RequestId,
    RuntimeRole,
    Sha256Digest,
    SourceId,
    require_artifact_type,
)
from .evidence import EvidenceNamespace, EvidenceRef, require_evidence_namespace


class RegionProposalAction(StrEnum):
    SPLIT = "SPLIT"
    STOP = "STOP"
    UNRESOLVED = "UNRESOLVED"


class RegionPlanStatus(StrEnum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    UNRESOLVED = "unresolved"
    SUPERSEDED = "superseded"


class SplitDecision(StrEnum):
    ACCEPT_SPLIT = "ACCEPT_SPLIT"
    REJECT_SPLIT = "REJECT_SPLIT"
    UNRESOLVED = "UNRESOLVED"


class ReplanAction(StrEnum):
    RESPLIT = "RESPLIT"
    MERGE_SIBLINGS = "MERGE_SIBLINGS"
    MOVE_BOUNDARY = "MOVE_BOUNDARY"
    RENAME_REGION = "RENAME_REGION"
    MARK_UNRESOLVED = "MARK_UNRESOLVED"


class ReplanStatus(StrEnum):
    OPEN = "open"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    RESOLVED = "resolved"
    SUPERSEDED = "superseded"


class SourceAssignmentDisposition(StrEnum):
    PRIMARY_REGION = "primary_region"
    SECONDARY_CROSS_CUTTING = "secondary_cross_cutting"
    EXPLICITLY_NONCLAIM = "explicitly_nonclaim"
    UNRESOLVED = "unresolved"


class SplitEvidenceMode(StrEnum):
    OUTLINE = "outline"
    TITLE = "title"
    COURSEWARE_DIRECT = "courseware_direct"
    SEMANTIC = "semantic"
    NODE_COUNT = "node_count"
    TOKEN_COUNT = "token_count"
    PAGE_CAPACITY = "page_capacity"


class GateAssessment(FrozenContract):
    passed: bool
    rationale: Annotated[
        str,
        StringConstraints(min_length=1, max_length=4096),
    ]
    evidence_refs: tuple[EvidenceRef, ...] = ()


class SplitProposal(FrozenContract):
    child_region_ids: tuple[RegionId, ...]
    rationale: Annotated[
        str,
        StringConstraints(min_length=1, max_length=4096),
    ]
    evidence_modes: tuple[SplitEvidenceMode, ...]
    evidence_refs: tuple[EvidenceRef, ...]


class StopProposal(FrozenContract):
    single_instructional_intent: bool
    no_unhandled_stable_subheading: bool
    claims_have_comparable_granularity: bool
    inventory_reconciled: bool
    further_split_would_fragment_or_duplicate: bool
    no_high_importance_omission: bool
    no_mixed_theme_evidence: bool
    safety_limit_reached: bool = False
    rationale: Annotated[
        str,
        StringConstraints(min_length=1, max_length=4096),
    ]
    evidence_refs: tuple[EvidenceRef, ...]


class RegionPlan(FrozenContract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    region_id: RegionId
    plan_version: int = Field(ge=1)
    parent_region_id: RegionId | None = None
    ancestor_path: tuple[RegionId, ...] = ()
    theme_label: Annotated[
        str,
        StringConstraints(min_length=1, max_length=512),
    ]
    theme_definition: Annotated[
        str,
        StringConstraints(min_length=1, max_length=4096),
    ]
    primary_source_memberships: tuple[SourceId, ...]
    secondary_source_memberships: tuple[SourceId, ...] = ()
    explicitly_excluded_source_ids: tuple[SourceId, ...] = ()
    unresolved_source_ids: tuple[SourceId, ...] = ()
    boundary_context_refs: tuple[EvidenceRef, ...] = ()
    child_region_ids: tuple[RegionId, ...] = ()
    proposed_action: RegionProposalAction
    split_proposal: SplitProposal | None = None
    stop_proposal: StopProposal | None = None
    split_certificate_ref: ArtifactRef | None = None
    decision_verifier: ArtifactProducerRef | None = None
    evidence_refs: tuple[EvidenceRef, ...]
    planner_attempt: int = Field(ge=1)
    planner: Literal[
        "global_structure_planner",
        "recursive_region_planner",
    ]
    status: RegionPlanStatus
    supersedes: ArtifactRef | None = None

    @model_validator(mode="after")
    def validate_region_plan(self) -> "RegionPlan":
        require_artifact_type(
            self.supersedes,
            ArtifactType.REGION_PLAN,
            field_name="supersedes",
        )
        if self.parent_region_id is None:
            if self.ancestor_path:
                raise ValueError("root region cannot have an ancestor path")
            if self.planner != "global_structure_planner":
                raise ValueError(
                    "only the global planner may propose a root region"
                )
        else:
            if not self.ancestor_path:
                raise ValueError("child region requires an ancestor path")
            if self.ancestor_path[-1] != self.parent_region_id:
                raise ValueError(
                    "ancestor_path must end at parent_region_id"
                )
            if self.region_id in self.ancestor_path:
                raise ValueError("region cannot be its own ancestor")
        membership_sets = {
            "primary": set(self.primary_source_memberships),
            "secondary": set(self.secondary_source_memberships),
            "excluded": set(self.explicitly_excluded_source_ids),
            "unresolved": set(self.unresolved_source_ids),
        }
        names = tuple(membership_sets)
        for index, left in enumerate(names):
            for right in names[index + 1 :]:
                overlap = membership_sets[left] & membership_sets[right]
                if overlap:
                    raise ValueError(
                        f"region source memberships overlap between "
                        f"{left} and {right}: "
                        + ", ".join(sorted(overlap))
                    )
        if self.proposed_action is RegionProposalAction.SPLIT:
            if self.split_proposal is None or self.stop_proposal is not None:
                raise ValueError(
                    "SPLIT requires split_proposal and forbids stop_proposal"
                )
            if self.child_region_ids != self.split_proposal.child_region_ids:
                raise ValueError(
                    "child_region_ids must match split_proposal"
                )
            if (
                self.split_certificate_ref
                and self.split_certificate_ref.artifact_type.value
                != "region_split_certificate"
            ):
                raise ValueError(
                    "split_certificate_ref must reference "
                    "RegionSplitCertificate"
                )
            if (
                self.status is RegionPlanStatus.ACCEPTED
                and self.split_certificate_ref is None
            ):
                raise ValueError(
                    "accepted split requires RegionSplitCertificate"
                )
            if self.decision_verifier is not None:
                raise ValueError(
                    "split verification belongs to the split certificate"
                )
        elif self.proposed_action is RegionProposalAction.STOP:
            if self.stop_proposal is None or self.split_proposal is not None:
                raise ValueError(
                    "STOP requires stop_proposal and forbids split_proposal"
                )
            if self.child_region_ids:
                raise ValueError("STOP region cannot declare child regions")
            if self.split_certificate_ref is not None:
                raise ValueError(
                    "STOP region cannot reference a split certificate"
                )
            if self.status is RegionPlanStatus.ACCEPTED:
                stop_checks = (
                    self.stop_proposal.single_instructional_intent,
                    self.stop_proposal.no_unhandled_stable_subheading,
                    self.stop_proposal.claims_have_comparable_granularity,
                    self.stop_proposal.inventory_reconciled,
                    (
                        self.stop_proposal
                        .further_split_would_fragment_or_duplicate
                    ),
                    self.stop_proposal.no_high_importance_omission,
                    self.stop_proposal.no_mixed_theme_evidence,
                )
                if not all(stop_checks):
                    raise ValueError(
                        "accepted STOP does not satisfy the semantic gate"
                    )
                if self.decision_verifier is None:
                    raise ValueError(
                        "accepted STOP requires an independent verifier"
                    )
                if self.decision_verifier.role is not (
                    RuntimeRole.REGION_DECISION_VERIFIER
                ):
                    raise ValueError(
                        "STOP verifier must use region_decision_verifier role"
                    )
        else:
            if self.split_proposal is not None or self.stop_proposal is not None:
                raise ValueError(
                    "UNRESOLVED cannot carry split or stop proposal"
                )
            if self.child_region_ids:
                raise ValueError(
                    "UNRESOLVED region cannot declare accepted children"
                )
            if self.split_certificate_ref is not None:
                raise ValueError(
                    "UNRESOLVED region cannot reference a split certificate"
                )
            if self.status is RegionPlanStatus.ACCEPTED:
                raise ValueError("UNRESOLVED region cannot be accepted")
        proposal_evidence = (
            self.split_proposal.evidence_refs
            if self.split_proposal
            else (
                self.stop_proposal.evidence_refs
                if self.stop_proposal
                else ()
            )
        )
        require_evidence_namespace(
            self.evidence_refs
            + self.boundary_context_refs
            + proposal_evidence,
            frozenset(
                {EvidenceNamespace.COURSEWARE, EvidenceNamespace.HUMAN}
            ),
            field_name="RegionPlan evidence",
        )
        return self


class RegionChildLabel(FrozenContract):
    child_region_id: RegionId
    label: Annotated[
        str,
        StringConstraints(min_length=1, max_length=512),
    ]
    label_self_contained: bool
    has_independent_source_support: bool
    source_support_refs: tuple[EvidenceRef, ...]


class RegionSourceAssignment(FrozenContract):
    source_id: SourceId
    disposition: SourceAssignmentDisposition
    region_ids: tuple[RegionId, ...] = ()
    rationale: Annotated[
        str,
        StringConstraints(min_length=1, max_length=2048),
    ]

    @model_validator(mode="after")
    def validate_regions(self) -> "RegionSourceAssignment":
        requires_region = self.disposition in {
            SourceAssignmentDisposition.PRIMARY_REGION,
            SourceAssignmentDisposition.SECONDARY_CROSS_CUTTING,
        }
        if requires_region and not self.region_ids:
            raise ValueError(
                f"{self.disposition.value} assignment requires region IDs"
            )
        if not requires_region and self.region_ids:
            raise ValueError(
                f"{self.disposition.value} assignment cannot target a region"
            )
        if (
            self.disposition
            is SourceAssignmentDisposition.PRIMARY_REGION
            and len(self.region_ids) != 1
        ):
            raise ValueError(
                "primary source assignment requires exactly one region"
            )
        return self


class RegionSplitCertificate(FrozenContract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    parent_region_id: RegionId
    parent_common_concept: Annotated[
        str,
        StringConstraints(min_length=1, max_length=1024),
    ]
    parent_common_concept_supported: bool
    child_region_ids: tuple[RegionId, ...]
    child_labels: tuple[RegionChildLabel, ...]
    source_assignment_map: tuple[RegionSourceAssignment, ...]
    boundary_evidence: tuple[EvidenceRef, ...]
    sibling_separation: GateAssessment
    within_region_cohesion: GateAssessment
    sibling_granularity_comparable: bool
    boundaries_explainable: bool
    inventory_reconciled: bool
    residual_source_ids: tuple[SourceId, ...] = ()
    cross_cutting_source_ids: tuple[SourceId, ...] = ()
    uses_capacity_as_semantic_evidence: bool = False
    decision: SplitDecision
    verifier: ArtifactProducerRef
    supersedes: ArtifactRef | None = None

    @model_validator(mode="after")
    def validate_certificate_shape(self) -> "RegionSplitCertificate":
        if self.verifier.role is not (
            RuntimeRole.REGION_DECISION_VERIFIER
        ):
            raise ValueError(
                "split verifier must use region_decision_verifier role"
            )
        require_artifact_type(
            self.supersedes,
            ArtifactType.REGION_SPLIT_CERTIFICATE,
            field_name="supersedes",
        )
        child_ids = set(self.child_region_ids)
        label_ids = {item.child_region_id for item in self.child_labels}
        if len(child_ids) != len(self.child_region_ids):
            raise ValueError("split child region IDs must be unique")
        if child_ids != label_ids:
            raise ValueError(
                "child_labels must cover exactly the split child regions"
            )
        assignment_ids = [
            item.source_id for item in self.source_assignment_map
        ]
        if len(assignment_ids) != len(set(assignment_ids)):
            raise ValueError("source assignment map contains duplicates")
        for assignment in self.source_assignment_map:
            unknown_regions = set(assignment.region_ids) - child_ids
            if unknown_regions:
                raise ValueError(
                    "source assignment targets regions outside this split: "
                    + ", ".join(sorted(unknown_regions))
                )
        primary_regions = {
            region_id
            for assignment in self.source_assignment_map
            if assignment.disposition
            is SourceAssignmentDisposition.PRIMARY_REGION
            for region_id in assignment.region_ids
        }
        if child_ids - primary_regions:
            raise ValueError(
                "every child region requires primary source support"
            )
        unresolved_assignments = {
            assignment.source_id
            for assignment in self.source_assignment_map
            if assignment.disposition
            is SourceAssignmentDisposition.UNRESOLVED
        }
        if set(self.residual_source_ids) != unresolved_assignments:
            raise ValueError(
                "residual_source_ids must match unresolved assignments"
            )
        cross_cutting_assignments = {
            assignment.source_id
            for assignment in self.source_assignment_map
            if assignment.disposition
            is SourceAssignmentDisposition.SECONDARY_CROSS_CUTTING
        }
        if set(self.cross_cutting_source_ids) != cross_cutting_assignments:
            raise ValueError(
                "cross_cutting_source_ids must match secondary assignments"
            )
        require_evidence_namespace(
            self.boundary_evidence
            + self.sibling_separation.evidence_refs
            + self.within_region_cohesion.evidence_refs
            + tuple(
                ref
                for child in self.child_labels
                for ref in child.source_support_refs
            ),
            frozenset(
                {EvidenceNamespace.COURSEWARE, EvidenceNamespace.HUMAN}
            ),
            field_name="split certificate evidence",
        )
        if self.decision is SplitDecision.ACCEPT_SPLIT:
            accepted_checks = (
                len(self.child_region_ids) >= 2,
                self.parent_common_concept_supported,
                all(
                    child.label_self_contained
                    and child.has_independent_source_support
                    and child.source_support_refs
                    for child in self.child_labels
                ),
                bool(self.boundary_evidence),
                self.sibling_separation.passed,
                self.within_region_cohesion.passed,
                self.sibling_granularity_comparable,
                self.boundaries_explainable,
                self.inventory_reconciled,
                not self.uses_capacity_as_semantic_evidence,
            )
            if not all(accepted_checks):
                raise ValueError(
                    "ACCEPT_SPLIT certificate does not satisfy split gate"
                )
        return self


class BoundaryError(FrozenContract):
    source_id: SourceId
    current_region_id: RegionId
    expected_region_id: RegionId | None = None
    reason: Annotated[
        str,
        StringConstraints(min_length=1, max_length=2048),
    ]


class DuplicateMembership(FrozenContract):
    source_id: SourceId
    region_ids: tuple[RegionId, ...]

    @model_validator(mode="after")
    def require_duplicate(self) -> "DuplicateMembership":
        if len(set(self.region_ids)) < 2:
            raise ValueError(
                "duplicate membership requires at least two regions"
            )
        return self


class InvalidParentRelation(FrozenContract):
    parent_region_id: RegionId
    child_region_id: RegionId
    evidence_refs: tuple[EvidenceRef, ...]
    reason: Annotated[
        str,
        StringConstraints(min_length=1, max_length=2048),
    ]


class ReplanRequest(FrozenContract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    request_id: RequestId
    affected_region_id: RegionId
    minimum_replan_ancestor_id: RegionId
    omitted_source_ids: tuple[SourceId, ...] = ()
    mixed_theme_evidence: tuple[EvidenceRef, ...] = ()
    boundary_errors: tuple[BoundaryError, ...] = ()
    duplicate_memberships: tuple[DuplicateMembership, ...] = ()
    invalid_parent_relations: tuple[InvalidParentRelation, ...] = ()
    requested_action: ReplanAction
    evidence_refs: tuple[EvidenceRef, ...]
    requester: Literal["bottom_up_region_auditor"] = (
        "bottom_up_region_auditor"
    )
    status: ReplanStatus = ReplanStatus.OPEN
    closure_digest: Sha256Digest | None = None
    resolved_tree_revision: int | None = Field(default=None, ge=1)
    supersedes: ArtifactRef | None = None

    @model_validator(mode="after")
    def require_auditable_reason(self) -> "ReplanRequest":
        require_artifact_type(
            self.supersedes,
            ArtifactType.REPLAN_REQUEST,
            field_name="supersedes",
        )
        closed_statuses = {
            ReplanStatus.REJECTED,
            ReplanStatus.RESOLVED,
            ReplanStatus.SUPERSEDED,
        }
        if self.status in closed_statuses:
            if (
                self.closure_digest is None
                or self.resolved_tree_revision is None
            ):
                raise ValueError(
                    "closed replan requires a new closure digest and "
                    "resolved TreeRevision"
                )
        elif (
            self.closure_digest is not None
            or self.resolved_tree_revision is not None
        ):
            raise ValueError(
                "open or accepted replan cannot claim closure"
            )
        if not any(
            (
                self.omitted_source_ids,
                self.mixed_theme_evidence,
                self.boundary_errors,
                self.duplicate_memberships,
                self.invalid_parent_relations,
            )
        ):
            raise ValueError(
                "ReplanRequest requires omission, boundary, duplicate, "
                "mixed-theme, or invalid-parent evidence"
            )
        nested_relation_evidence = tuple(
            ref
            for relation in self.invalid_parent_relations
            for ref in relation.evidence_refs
        )
        require_evidence_namespace(
            self.evidence_refs
            + self.mixed_theme_evidence
            + nested_relation_evidence,
            frozenset(
                {EvidenceNamespace.COURSEWARE, EvidenceNamespace.HUMAN}
            ),
            field_name="ReplanRequest evidence",
        )
        return self
