from __future__ import annotations

from dataclasses import dataclass

from backend.vnext.contracts.regions import (
    RegionPlan,
    RegionSplitCertificate,
    ReplanRequest,
    SourceAssignmentDisposition,
    SplitDecision,
    SplitEvidenceMode,
    StopProposal,
)


@dataclass(frozen=True, slots=True)
class GateResult:
    accepted: bool
    decision: str
    reason_codes: tuple[str, ...]


_CAPACITY_MODES = frozenset(
    {
        SplitEvidenceMode.NODE_COUNT,
        SplitEvidenceMode.TOKEN_COUNT,
        SplitEvidenceMode.PAGE_CAPACITY,
    }
)


def evaluate_split_certificate(
    certificate: RegionSplitCertificate,
    *,
    evidence_modes: tuple[SplitEvidenceMode, ...],
) -> GateResult:
    reasons: list[str] = []
    if len(certificate.child_region_ids) < 2:
        reasons.append("fewer_than_two_children")
    if not certificate.parent_common_concept_supported:
        reasons.append("unsupported_parent_common_concept")
    if any(
        not child.label_self_contained for child in certificate.child_labels
    ):
        reasons.append("non_self_contained_child_label")
    if any(
        not child.has_independent_source_support
        or not child.source_support_refs
        for child in certificate.child_labels
    ):
        reasons.append("child_without_independent_source_support")
    if not certificate.sibling_separation.passed:
        reasons.append("sibling_separation_failed")
    if not certificate.within_region_cohesion.passed:
        reasons.append("within_region_cohesion_failed")
    if not certificate.sibling_granularity_comparable:
        reasons.append("incomparable_sibling_granularity")
    if not certificate.boundaries_explainable:
        reasons.append("unexplained_region_boundary")
    if not certificate.inventory_reconciled:
        reasons.append("source_inventory_not_reconciled")
    if certificate.residual_source_ids:
        assigned_unresolved = {
            assignment.source_id
            for assignment in certificate.source_assignment_map
            if assignment.disposition
            is SourceAssignmentDisposition.UNRESOLVED
        }
        if not set(certificate.residual_source_ids) <= assigned_unresolved:
            reasons.append("residual_source_not_marked_unresolved")
    if certificate.uses_capacity_as_semantic_evidence or (
        set(evidence_modes) and set(evidence_modes) <= _CAPACITY_MODES
    ):
        reasons.append("capacity_used_as_semantic_evidence")
    accepted = not reasons
    decision = (
        SplitDecision.ACCEPT_SPLIT.value
        if accepted
        else SplitDecision.REJECT_SPLIT.value
    )
    if certificate.decision.value != decision:
        reasons.append("certificate_decision_mismatch")
        accepted = False
        decision = SplitDecision.REJECT_SPLIT.value
    return GateResult(accepted, decision, tuple(reasons))


def evaluate_stop_proposal(proposal: StopProposal) -> GateResult:
    checks = (
        ("mixed_instructional_intent", proposal.single_instructional_intent),
        (
            "unhandled_stable_subheading",
            proposal.no_unhandled_stable_subheading,
        ),
        (
            "mixed_claim_granularity",
            proposal.claims_have_comparable_granularity,
        ),
        ("source_inventory_not_reconciled", proposal.inventory_reconciled),
        (
            "further_semantic_split_available",
            proposal.further_split_would_fragment_or_duplicate,
        ),
        (
            "high_importance_omission",
            proposal.no_high_importance_omission,
        ),
        ("mixed_theme_evidence", proposal.no_mixed_theme_evidence),
    )
    reasons = [reason for reason, passed in checks if not passed]
    if proposal.safety_limit_reached and reasons:
        reasons.append("safety_limit_is_not_semantic_stop_evidence")
    return GateResult(
        accepted=not reasons,
        decision="ACCEPT_STOP" if not reasons else "UNRESOLVED",
        reason_codes=tuple(reasons),
    )


def validate_replan_scope(
    request: ReplanRequest,
    *,
    affected_region: RegionPlan,
) -> None:
    if request.affected_region_id != affected_region.region_id:
        raise ValueError("request does not target the supplied affected region")
    legal_ancestors = {
        affected_region.region_id,
        *affected_region.ancestor_path,
    }
    if request.minimum_replan_ancestor_id not in legal_ancestors:
        raise ValueError(
            "minimum_replan_ancestor_id is outside the affected path"
        )
