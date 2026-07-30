from __future__ import annotations

import hashlib
from dataclasses import dataclass

from backend.vnext.artifacts.canonical import (
    canonical_json_bytes,
    payload_digest,
)
from backend.vnext.contracts.common import (
    ArtifactRef,
    RuntimeRole,
    StringValue,
)
from backend.vnext.contracts.crosslinks import (
    CrossLinkProposal,
    CrossLinkProposalLedger,
    CrossLinkResolution,
    CrossLinkResolutionLedger,
    CrossLinkResolutionStatus,
    CrossLinkRisk,
)
from backend.vnext.contracts.evidence import EvidenceRef
from backend.vnext.contracts.graph import (
    CanonicalExplicitGraph,
    CanonicalRelation,
    CanonicalStatus,
    EvidenceAuthority,
    GraphAuditItem,
    HierarchyDirectness,
    VerifierClassification,
)
from backend.vnext.review import assert_human_decisions_preserved


CROSS_LINK_POLICY_VERSION = "cross-link-evidence-v1"


@dataclass(frozen=True, slots=True)
class CrossLinkBuildResult:
    graph: CanonicalExplicitGraph
    accepted_proposal_ids: tuple[str, ...]
    rejected_proposal_ids: tuple[str, ...]
    review_proposal_ids: tuple[str, ...]


def attach_verified_cross_links(
    graph: CanonicalExplicitGraph,
    *,
    graph_ref: ArtifactRef,
    proposals: CrossLinkProposalLedger,
    resolutions: CrossLinkResolutionLedger,
) -> CrossLinkBuildResult:
    graph_digest = payload_digest(graph)
    if graph_ref.payload_digest != graph_digest:
        raise ValueError(
            "cross-link graph reference digest does not match graph"
        )
    if graph_ref.artifact_type.value != "canonical_explicit_graph":
        raise ValueError("cross-link input must be a canonical graph")
    if (
        proposals.canonical_graph_ref != graph_ref
        or resolutions.canonical_graph_ref != graph_ref
    ):
        raise ValueError(
            "cross-link ledgers must reference the exact canonical graph"
        )
    if proposals.owner_id != resolutions.owner_id:
        raise ValueError("cross-link ledgers must remain owner-scoped")
    if resolutions.proposal_ledger_id != proposals.ledger_id:
        raise ValueError(
            "cross-link resolution ledger references another proposal ledger"
        )

    accepted_concepts = {
        concept.concept_id
        for concept in graph.concepts
        if concept.status is CanonicalStatus.ACCEPTED
    }
    resolution_by_id = {
        item.proposal_id: item for item in resolutions.resolutions
    }
    existing_keys = {
        (
            relation.source_id,
            relation.target_id,
            relation.semantic_relation,
        )
        for relation in graph.relations
        if relation.status is CanonicalStatus.ACCEPTED
    }
    accepted_relations: list[CanonicalRelation] = []
    rejected_items: list[GraphAuditItem] = list(graph.rejected_items)
    unresolved_items: list[GraphAuditItem] = list(graph.unresolved_items)
    accepted_ids: list[str] = []
    rejected_ids: list[str] = []
    review_ids: list[str] = []

    for proposal in proposals.proposals:
        resolution = resolution_by_id.get(proposal.proposal_id)
        if resolution is None:
            unresolved_items.append(
                _audit(proposal, "cross_link_resolution_missing")
            )
            review_ids.append(proposal.proposal_id)
            continue
        reasons = _acceptance_failures(
            proposal,
            resolution,
            accepted_concepts=accepted_concepts,
            precision_mode=resolutions.precision_mode,
        )
        relation_key = (
            proposal.source_id,
            proposal.target_id,
            proposal.semantic_relation,
        )
        if relation_key in existing_keys:
            reasons.add("duplicate_accepted_relation")
        if (
            resolution.status
            is not CrossLinkResolutionStatus.ACCEPTED
        ):
            reasons.update(resolution.reason_codes)
            if resolution.status is (
                CrossLinkResolutionStatus.NEEDS_REVIEW
            ):
                unresolved_items.append(_audit(proposal, *reasons))
                review_ids.append(proposal.proposal_id)
            else:
                rejected_items.append(_audit(proposal, *reasons))
                rejected_ids.append(proposal.proposal_id)
            continue
        if reasons:
            if reasons <= {
                "independent_relation_verifier_missing",
                "second_independent_verifier_missing",
            }:
                unresolved_items.append(_audit(proposal, *reasons))
                review_ids.append(proposal.proposal_id)
            else:
                rejected_items.append(_audit(proposal, *reasons))
                rejected_ids.append(proposal.proposal_id)
            continue

        evidence = _unique_evidence(
            (
                *proposal.courseware_evidence_refs,
                *(
                    evidence_ref
                    for vote in resolution.verifier_decisions
                    for evidence_ref in (
                        *vote.courseware_evidence_refs,
                        *vote.outline_evidence_refs,
                    )
                ),
            )
        )
        relation = CanonicalRelation(
            relation_id=_stable_relation_id(
                graph_digest,
                proposal,
            ),
            source_id=proposal.source_id,
            target_id=proposal.target_id,
            semantic_relation=proposal.semantic_relation,
            hierarchy_directness=HierarchyDirectness.NON_HIERARCHICAL,
            evidence_authority=EvidenceAuthority.COURSEWARE_DIRECT,
            source_claim_ids=proposal.source_claim_ids,
            edge_evidence_refs=evidence,
            external_evidence_refs=proposal.external_evidence_refs,
            verifier_decisions=resolution.verifier_decisions,
            status=CanonicalStatus.ACCEPTED,
        )
        accepted_relations.append(relation)
        accepted_ids.append(proposal.proposal_id)
        existing_keys.add(relation_key)

    unknown_resolutions = sorted(
        set(resolution_by_id)
        - {proposal.proposal_id for proposal in proposals.proposals}
    )
    if unknown_resolutions:
        raise ValueError(
            "cross-link resolutions reference unknown proposals: "
            + ", ".join(unknown_resolutions)
        )

    policy_digest = payload_digest(
        {
            "policy": CROSS_LINK_POLICY_VERSION,
            "precision_mode": resolutions.precision_mode,
            "proposal_digest": payload_digest(proposals),
            "resolution_digest": payload_digest(resolutions),
        }
    )
    enriched = CanonicalExplicitGraph(
        graph_id=_stable_graph_id(
            graph_digest,
            proposals,
            resolutions,
        ),
        source_observation_ref=graph.source_observation_ref,
        claim_ledger_ref=graph.claim_ledger_ref,
        region_plan_refs=graph.region_plan_refs,
        concepts=graph.concepts,
        relations=(
            *graph.relations,
            *tuple(
                sorted(
                    accepted_relations,
                    key=lambda item: item.relation_id,
                )
            ),
        ),
        unresolved_items=tuple(unresolved_items),
        rejected_items=tuple(rejected_items),
        decision_log=graph.decision_log,
        build_manifest=graph.build_manifest.model_copy(
            update={
                "policy_digest": policy_digest,
                "input_digests": (
                    *graph.build_manifest.input_digests,
                    payload_digest(proposals),
                    payload_digest(resolutions),
                ),
                "parameters": (
                    *graph.build_manifest.parameters,
                    StringValue(
                        key="cross_link_policy",
                        value=CROSS_LINK_POLICY_VERSION,
                    ),
                    StringValue(
                        key="cross_links_affect_hierarchy",
                        value="false",
                    ),
                ),
            }
        ),
        supersedes=graph_ref,
    )
    assert_human_decisions_preserved(graph, enriched)
    return CrossLinkBuildResult(
        graph=enriched,
        accepted_proposal_ids=tuple(sorted(accepted_ids)),
        rejected_proposal_ids=tuple(sorted(rejected_ids)),
        review_proposal_ids=tuple(sorted(review_ids)),
    )


def _acceptance_failures(
    proposal: CrossLinkProposal,
    resolution: CrossLinkResolution,
    *,
    accepted_concepts: set[str],
    precision_mode: bool,
) -> set[str]:
    reasons: set[str] = set()
    if (
        proposal.source_id not in accepted_concepts
        or proposal.target_id not in accepted_concepts
    ):
        reasons.add("cross_link_endpoint_not_accepted")
    if not proposal.courseware_evidence_refs:
        reasons.add("external_only_cross_link_forbidden")
    if not resolution.direction_verified:
        reasons.add("cross_link_direction_unverified")
    supporting_roles = {
        vote.verifier.role
        for vote in resolution.verifier_decisions
        if (
            vote.supports_relation
            and vote.classification
            is VerifierClassification.SEMANTIC_LINK
        )
    }
    if not supporting_roles & {
        RuntimeRole.RELATION_VERIFIER_A,
        RuntimeRole.RELATION_VERIFIER_B,
    }:
        reasons.add("independent_relation_verifier_missing")
    needs_two_votes = (
        precision_mode or proposal.risk is CrossLinkRisk.HIGH
    )
    if needs_two_votes and not {
        RuntimeRole.RELATION_VERIFIER_A,
        RuntimeRole.RELATION_VERIFIER_B,
    } <= supporting_roles:
        reasons.add("second_independent_verifier_missing")
    if any(
        vote.classification is not VerifierClassification.SEMANTIC_LINK
        for vote in resolution.verifier_decisions
    ):
        reasons.add("verifier_did_not_classify_semantic_link")
    return reasons


def _audit(
    proposal: CrossLinkProposal,
    *reason_codes: str,
) -> GraphAuditItem:
    reasons = tuple(
        sorted(set(reason_codes) or {"cross_link_not_accepted"})
    )
    return GraphAuditItem(
        item_type="relation",
        item_id=proposal.proposal_id,
        reason_codes=reasons,
        evidence_refs=proposal.courseware_evidence_refs,
    )


def _unique_evidence(
    evidence_refs: tuple[EvidenceRef, ...],
) -> tuple[EvidenceRef, ...]:
    unique = {
        (item.namespace.value, item.ref_id): item
        for item in evidence_refs
    }
    return tuple(unique[key] for key in sorted(unique))


def _stable_relation_id(
    graph_digest: str,
    proposal: CrossLinkProposal,
) -> str:
    digest = hashlib.sha256(
        b"zlb-vnext-cross-link-relation-v1\0"
        + canonical_json_bytes(
            {
                "graph_digest": graph_digest,
                "proposal_id": proposal.proposal_id,
                "relation": proposal.semantic_relation.value,
                "source": proposal.source_id,
                "target": proposal.target_id,
            }
        )
    ).hexdigest()
    return "relation_" + digest[:32]


def _stable_graph_id(
    graph_digest: str,
    proposals: CrossLinkProposalLedger,
    resolutions: CrossLinkResolutionLedger,
) -> str:
    digest = hashlib.sha256(
        b"zlb-vnext-cross-link-graph-v1\0"
        + canonical_json_bytes(
            {
                "graph_digest": graph_digest,
                "proposal_digest": payload_digest(proposals),
                "resolution_digest": payload_digest(resolutions),
            }
        )
    ).hexdigest()
    return "graph_" + digest[:32]
