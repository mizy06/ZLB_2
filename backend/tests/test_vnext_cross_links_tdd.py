from __future__ import annotations

import unittest

from backend.tests.vnext_test_support import (
    accepted_concept,
    accepted_relation,
    artifact_producer,
    concept_id,
    courseware_evidence,
    external_evidence,
    graph,
)
from backend.vnext.artifacts.canonical import payload_digest
from backend.vnext.canonical_graph import attach_verified_cross_links
from backend.vnext.contracts.common import (
    ArtifactProducerRef,
    ArtifactRef,
    ArtifactType,
    RuntimeRole,
)
from backend.vnext.contracts.crosslinks import (
    CrossLinkProposal,
    CrossLinkProposalLedger,
    CrossLinkResolution,
    CrossLinkResolutionLedger,
    CrossLinkResolutionStatus,
    CrossLinkRisk,
)
from backend.vnext.contracts.evidence import EvidenceNamespace, EvidenceRef
from backend.vnext.contracts.graph import (
    CanonicalStatus,
    HierarchyDirectness,
    SemanticRelation,
    VerifierClassification,
    VerifierDecision,
)
from backend.vnext.projection import build_diagnostic_projection


def _graph():
    return graph(
        (
            accepted_concept("1", "Root"),
            accepted_concept("2", "Cause"),
            accepted_concept("3", "Effect"),
        ),
        (
            accepted_relation("a", "1", "2"),
            accepted_relation("b", "1", "3"),
        ),
    )


def _graph_ref(value) -> ArtifactRef:
    return ArtifactRef(
        owner_id="owner-a",
        artifact_id=f"art_{'9' * 32}",
        artifact_type=ArtifactType.CANONICAL_EXPLICIT_GRAPH,
        payload_digest=payload_digest(value),
    )


def _proposal(
    *,
    digit: str = "1",
    risk: CrossLinkRisk = CrossLinkRisk.LOW,
    courseware: tuple[EvidenceRef, ...] | None = None,
    external: tuple[EvidenceRef, ...] = (),
) -> CrossLinkProposal:
    if courseware is None:
        courseware = (courseware_evidence("d"),)
    return CrossLinkProposal(
        proposal_id=f"cross_link_{digit * 32}",
        source_id=concept_id("2"),
        target_id=concept_id("3"),
        semantic_relation=SemanticRelation.CAUSES,
        source_claim_ids=(),
        courseware_evidence_refs=courseware,
        external_evidence_refs=external,
        risk=risk,
        reason_codes=("explicit_causal_statement",),
    )


def _vote(
    role: RuntimeRole,
    *,
    classification: VerifierClassification = (
        VerifierClassification.SEMANTIC_LINK
    ),
    evidence: tuple[EvidenceRef, ...] | None = None,
) -> VerifierDecision:
    if evidence is None:
        evidence = (courseware_evidence("d"),)
    return VerifierDecision(
        verifier=artifact_producer(role.value[-1], role),
        classification=classification,
        supports_relation=True,
        courseware_evidence_refs=evidence,
        reason_codes=("direction_and_relation_supported",),
    )


def _ledgers(
    base_ref: ArtifactRef,
    proposal: CrossLinkProposal,
    resolution: CrossLinkResolution,
    *,
    precision: bool = False,
) -> tuple[CrossLinkProposalLedger, CrossLinkResolutionLedger]:
    proposal_ledger = CrossLinkProposalLedger(
        ledger_id=f"cross_link_ledger_{'4' * 32}",
        owner_id="owner-a",
        canonical_graph_ref=base_ref,
        proposer=ArtifactProducerRef(
            producer_id="vnext-cross-link-proposer",
            producer_version="1.0.0",
            role=RuntimeRole.CANONICALIZER,
        ),
        proposals=(proposal,),
    )
    resolution_ledger = CrossLinkResolutionLedger(
        ledger_id=f"cross_link_resolution_ledger_{'5' * 32}",
        owner_id="owner-a",
        proposal_ledger_id=proposal_ledger.ledger_id,
        canonical_graph_ref=base_ref,
        precision_mode=precision,
        resolutions=(resolution,),
    )
    return proposal_ledger, resolution_ledger


class VNextCrossLinkTests(unittest.TestCase):
    def test_verified_courseware_cross_link_never_changes_tree_parents(self):
        base = _graph()
        base_ref = _graph_ref(base)
        proposal = _proposal()
        resolution = CrossLinkResolution(
            proposal_id=proposal.proposal_id,
            status=CrossLinkResolutionStatus.ACCEPTED,
            direction_verified=True,
            verifier_decisions=(
                _vote(RuntimeRole.RELATION_VERIFIER_A),
            ),
            reason_codes=(),
        )
        proposal_ledger, resolution_ledger = _ledgers(
            base_ref,
            proposal,
            resolution,
        )
        base_projection = build_diagnostic_projection(
            base,
            canonical_graph_ref=base_ref,
        )

        result = attach_verified_cross_links(
            base,
            graph_ref=base_ref,
            proposals=proposal_ledger,
            resolutions=resolution_ledger,
        )
        enriched_ref = ArtifactRef(
            owner_id="owner-a",
            artifact_id=f"art_{'8' * 32}",
            artifact_type=ArtifactType.CANONICAL_EXPLICIT_GRAPH,
            payload_digest=payload_digest(result.graph),
        )
        enriched_projection = build_diagnostic_projection(
            result.graph,
            canonical_graph_ref=enriched_ref,
        )

        self.assertEqual(
            result.accepted_proposal_ids,
            (proposal.proposal_id,),
        )
        cross_link = result.graph.relations[-1]
        self.assertEqual(cross_link.status, CanonicalStatus.ACCEPTED)
        self.assertEqual(
            cross_link.hierarchy_directness,
            HierarchyDirectness.NON_HIERARCHICAL,
        )
        self.assertEqual(
            cross_link.semantic_relation,
            SemanticRelation.CAUSES,
        )
        self.assertEqual(
            enriched_projection.parent_selections,
            base_projection.parent_selections,
        )
        self.assertNotIn(
            cross_link.relation_id,
            enriched_projection.projection_parent_edge_ids,
        )

    def test_external_only_cross_link_is_rejected_from_canonical_core(self):
        base = _graph()
        base_ref = _graph_ref(base)
        human_vote_evidence = EvidenceRef(
            namespace=EvidenceNamespace.HUMAN,
            ref_id="human:review:cross-link-1",
        )
        proposal = _proposal(
            courseware=(),
            external=(external_evidence("e"),),
        )
        resolution = CrossLinkResolution(
            proposal_id=proposal.proposal_id,
            status=CrossLinkResolutionStatus.ACCEPTED,
            direction_verified=True,
            verifier_decisions=(
                _vote(
                    RuntimeRole.RELATION_VERIFIER_A,
                    evidence=(human_vote_evidence,),
                ),
            ),
            reason_codes=(),
        )
        proposal_ledger, resolution_ledger = _ledgers(
            base_ref,
            proposal,
            resolution,
        )

        result = attach_verified_cross_links(
            base,
            graph_ref=base_ref,
            proposals=proposal_ledger,
            resolutions=resolution_ledger,
        )

        self.assertEqual(result.accepted_proposal_ids, ())
        self.assertEqual(
            result.rejected_proposal_ids,
            (proposal.proposal_id,),
        )
        self.assertEqual(len(result.graph.relations), len(base.relations))
        finding = next(
            item
            for item in result.graph.rejected_items
            if item.item_id == proposal.proposal_id
        )
        self.assertIn(
            "external_only_cross_link_forbidden",
            finding.reason_codes,
        )

    def test_high_risk_cross_link_waits_for_second_independent_vote(self):
        base = _graph()
        base_ref = _graph_ref(base)
        proposal = _proposal(risk=CrossLinkRisk.HIGH)
        resolution = CrossLinkResolution(
            proposal_id=proposal.proposal_id,
            status=CrossLinkResolutionStatus.ACCEPTED,
            direction_verified=True,
            verifier_decisions=(
                _vote(RuntimeRole.RELATION_VERIFIER_A),
            ),
            reason_codes=(),
        )
        proposal_ledger, resolution_ledger = _ledgers(
            base_ref,
            proposal,
            resolution,
        )

        unresolved = attach_verified_cross_links(
            base,
            graph_ref=base_ref,
            proposals=proposal_ledger,
            resolutions=resolution_ledger,
        )

        self.assertEqual(unresolved.accepted_proposal_ids, ())
        self.assertEqual(
            unresolved.review_proposal_ids,
            (proposal.proposal_id,),
        )
        finding = next(
            item
            for item in unresolved.graph.unresolved_items
            if item.item_id == proposal.proposal_id
        )
        self.assertIn(
            "second_independent_verifier_missing",
            finding.reason_codes,
        )

        two_vote_resolution = resolution.model_copy(
            update={
                "verifier_decisions": (
                    _vote(RuntimeRole.RELATION_VERIFIER_A),
                    _vote(RuntimeRole.RELATION_VERIFIER_B),
                )
            }
        )
        proposal_ledger, two_vote_ledger = _ledgers(
            base_ref,
            proposal,
            two_vote_resolution,
        )
        accepted = attach_verified_cross_links(
            base,
            graph_ref=base_ref,
            proposals=proposal_ledger,
            resolutions=two_vote_ledger,
        )
        self.assertEqual(
            accepted.accepted_proposal_ids,
            (proposal.proposal_id,),
        )

    def test_non_semantic_link_vote_cannot_certify_cross_link(self):
        base = _graph()
        base_ref = _graph_ref(base)
        proposal = _proposal()
        resolution = CrossLinkResolution(
            proposal_id=proposal.proposal_id,
            status=CrossLinkResolutionStatus.ACCEPTED,
            direction_verified=True,
            verifier_decisions=(
                _vote(
                    RuntimeRole.RELATION_VERIFIER_A,
                    classification=VerifierClassification.DIRECT,
                ),
            ),
            reason_codes=(),
        )
        proposal_ledger, resolution_ledger = _ledgers(
            base_ref,
            proposal,
            resolution,
        )

        result = attach_verified_cross_links(
            base,
            graph_ref=base_ref,
            proposals=proposal_ledger,
            resolutions=resolution_ledger,
        )

        self.assertEqual(result.accepted_proposal_ids, ())
        finding = next(
            item
            for item in result.graph.rejected_items
            if item.item_id == proposal.proposal_id
        )
        self.assertIn(
            "verifier_did_not_classify_semantic_link",
            finding.reason_codes,
        )


if __name__ == "__main__":
    unittest.main()
