from __future__ import annotations

import unittest

from pydantic import ValidationError

from backend.vnext.claims import evaluate_omission_audit
from backend.vnext.contracts.claims import (
    AuditorAttempt,
    OmissionAudit,
    OmissionReason,
)
from backend.vnext.contracts.common import ArtifactType, RuntimeRole
from backend.vnext.contracts.evidence import EvidenceNamespace, EvidenceRef
from backend.vnext.contracts.inventory import (
    HumanMustHaveRef,
    InventoryEntry,
    InventoryEntryKind,
    InventoryImportance,
    RawSourceManifest,
    SourceInventory,
)
from backend.vnext.contracts.regions import (
    BoundaryError,
    GateAssessment,
    RegionChildLabel,
    RegionPlan,
    RegionPlanStatus,
    RegionProposalAction,
    RegionSourceAssignment,
    RegionSplitCertificate,
    ReplanAction,
    ReplanRequest,
    SourceAssignmentDisposition,
    SplitDecision,
    SplitEvidenceMode,
    SplitProposal,
    StopProposal,
)
from backend.vnext.regions import (
    evaluate_split_certificate,
    evaluate_stop_proposal,
    validate_replan_scope,
)

from backend.tests.vnext_test_support import (
    artifact_producer,
    artifact_ref,
    courseware_evidence,
    digest,
    region_id,
    source_id,
)


def _split_certificate(
    *,
    decision: SplitDecision = SplitDecision.ACCEPT_SPLIT,
    uses_capacity: bool = False,
) -> RegionSplitCertificate:
    child_a = region_id("2")
    child_b = region_id("3")
    evidence_a = courseware_evidence("2")
    evidence_b = courseware_evidence("3")
    return RegionSplitCertificate(
        parent_region_id=region_id("1"),
        parent_common_concept="Carbonyl chemistry",
        parent_common_concept_supported=True,
        child_region_ids=(child_a, child_b),
        child_labels=(
            RegionChildLabel(
                child_region_id=child_a,
                label="Preparation",
                label_self_contained=True,
                has_independent_source_support=True,
                source_support_refs=(evidence_a,),
            ),
            RegionChildLabel(
                child_region_id=child_b,
                label="Nucleophilic addition",
                label_self_contained=True,
                has_independent_source_support=True,
                source_support_refs=(evidence_b,),
            ),
        ),
        source_assignment_map=(
            RegionSourceAssignment(
                source_id=source_id("block", "2"),
                disposition=SourceAssignmentDisposition.PRIMARY_REGION,
                region_ids=(child_a,),
                rationale="Preparation heading",
            ),
            RegionSourceAssignment(
                source_id=source_id("block", "3"),
                disposition=SourceAssignmentDisposition.PRIMARY_REGION,
                region_ids=(child_b,),
                rationale="Addition heading",
            ),
        ),
        boundary_evidence=(evidence_a, evidence_b),
        sibling_separation=GateAssessment(
            passed=True,
            rationale="Distinct instructional topics",
            evidence_refs=(evidence_a, evidence_b),
        ),
        within_region_cohesion=GateAssessment(
            passed=True,
            rationale="Each child follows one source heading",
            evidence_refs=(evidence_a, evidence_b),
        ),
        sibling_granularity_comparable=True,
        boundaries_explainable=True,
        inventory_reconciled=True,
        uses_capacity_as_semantic_evidence=uses_capacity,
        decision=decision,
        verifier=artifact_producer(
            "9",
            RuntimeRole.REGION_DECISION_VERIFIER,
        ),
    )


def _stop_proposal(**updates) -> StopProposal:
    values = {
        "single_instructional_intent": True,
        "no_unhandled_stable_subheading": True,
        "claims_have_comparable_granularity": True,
        "inventory_reconciled": True,
        "further_split_would_fragment_or_duplicate": True,
        "no_high_importance_omission": True,
        "no_mixed_theme_evidence": True,
        "rationale": "One coherent leaf topic",
        "evidence_refs": (courseware_evidence("1"),),
    }
    values.update(updates)
    return StopProposal(**values)


class VNextRegionGateTests(unittest.TestCase):
    def test_valid_semantic_split_passes(self):
        result = evaluate_split_certificate(
            _split_certificate(),
            evidence_modes=(
                SplitEvidenceMode.OUTLINE,
                SplitEvidenceMode.COURSEWARE_DIRECT,
            ),
        )

        self.assertTrue(result.accepted)
        self.assertEqual(result.decision, "ACCEPT_SPLIT")

    def test_capacity_semantics_cannot_pass_split(self):
        result = evaluate_split_certificate(
            _split_certificate(
                decision=SplitDecision.REJECT_SPLIT,
                uses_capacity=True,
            ),
            evidence_modes=(SplitEvidenceMode.PAGE_CAPACITY,),
        )

        self.assertFalse(result.accepted)
        self.assertIn(
            "capacity_used_as_semantic_evidence",
            result.reason_codes,
        )

    def test_safety_limit_cannot_turn_mixed_region_into_stop(self):
        result = evaluate_stop_proposal(
            _stop_proposal(
                single_instructional_intent=False,
                no_mixed_theme_evidence=False,
                safety_limit_reached=True,
            )
        )

        self.assertFalse(result.accepted)
        self.assertEqual(result.decision, "UNRESOLVED")
        self.assertIn(
            "safety_limit_is_not_semantic_stop_evidence",
            result.reason_codes,
        )

    def test_accepted_split_plan_requires_verifier_certificate(self):
        with self.assertRaisesRegex(
            ValidationError,
            "RegionSplitCertificate",
        ):
            RegionPlan(
                region_id=region_id("1"),
                plan_version=1,
                theme_label="Root",
                theme_definition="Document root",
                primary_source_memberships=(source_id("page", "1"),),
                child_region_ids=(region_id("2"), region_id("3")),
                proposed_action=RegionProposalAction.SPLIT,
                split_proposal=SplitProposal(
                    child_region_ids=(region_id("2"), region_id("3")),
                    rationale="Explicit source headings",
                    evidence_modes=(SplitEvidenceMode.OUTLINE,),
                    evidence_refs=(
                        courseware_evidence("1", kind="page"),
                    ),
                ),
                evidence_refs=(
                    courseware_evidence("1", kind="page"),
                ),
                planner_attempt=1,
                planner="global_structure_planner",
                status=RegionPlanStatus.ACCEPTED,
            )

    def test_accepted_stop_requires_independent_verifier(self):
        with self.assertRaisesRegex(
            ValidationError,
            "independent verifier",
        ):
            RegionPlan(
                region_id=region_id("3"),
                plan_version=1,
                parent_region_id=region_id("2"),
                ancestor_path=(region_id("1"), region_id("2")),
                theme_label="Leaf",
                theme_definition="One source-grounded topic",
                primary_source_memberships=(source_id("block", "3"),),
                proposed_action=RegionProposalAction.STOP,
                stop_proposal=_stop_proposal(),
                evidence_refs=(courseware_evidence("3"),),
                planner_attempt=1,
                planner="recursive_region_planner",
                status=RegionPlanStatus.ACCEPTED,
            )

    def test_replan_must_target_affected_ancestor_path(self):
        plan = RegionPlan(
            region_id=region_id("3"),
            plan_version=1,
            parent_region_id=region_id("2"),
            ancestor_path=(region_id("1"), region_id("2")),
            theme_label="Leaf",
            theme_definition="One source-grounded topic",
            primary_source_memberships=(source_id("block", "3"),),
            proposed_action=RegionProposalAction.STOP,
            stop_proposal=_stop_proposal(),
            evidence_refs=(courseware_evidence("3"),),
            planner_attempt=1,
            planner="recursive_region_planner",
            status=RegionPlanStatus.PROPOSED,
        )
        legal = ReplanRequest(
            request_id=f"replan_{'1' * 32}",
            affected_region_id=region_id("3"),
            minimum_replan_ancestor_id=region_id("2"),
            boundary_errors=(
                BoundaryError(
                    source_id=source_id("block", "3"),
                    current_region_id=region_id("3"),
                    reason="boundary mismatch",
                ),
            ),
            requested_action=ReplanAction.MOVE_BOUNDARY,
            evidence_refs=(courseware_evidence("3"),),
        )
        illegal = legal.model_copy(
            update={"minimum_replan_ancestor_id": region_id("9")}
        )

        validate_replan_scope(legal, affected_region=plan)
        with self.assertRaisesRegex(ValueError, "outside"):
            validate_replan_scope(illegal, affected_region=plan)


class VNextOmissionGateTests(unittest.TestCase):
    def _inventory(self) -> SourceInventory:
        source = source_id("page", "1")
        return SourceInventory(
            inventory_id=f"inventory_{'1' * 32}",
            document_ir_ref=artifact_ref(
                ArtifactType.SOURCE_OBSERVATION_IR,
                "1",
            ),
            raw_manifest=RawSourceManifest(
                source_hash=digest("a"),
                source_format="md",
                inspector_policy_version="test-raw-manifest-v1",
                parser_major=1,
                parser_page_count=1,
                parser_object_count=1,
                parser_outline_count=0,
                unresolved_checks=("native_pagination_unavailable",),
            ),
            page_entries=(
                InventoryEntry(
                    inventory_entry_id=f"inventory_entry_{'1' * 32}",
                    source_id=source,
                    source_kind=InventoryEntryKind.PAGE,
                    importance=InventoryImportance.MUST_HAVE,
                    evidence_refs=(
                        courseware_evidence("1", kind="page"),
                    ),
                ),
            ),
            human_must_have_refs=(
                HumanMustHaveRef(
                    human_ref=EvidenceRef(
                        namespace=EvidenceNamespace.HUMAN,
                        ref_id="human:gold:page-1",
                    ),
                    source_ids=(source,),
                    rationale="Gold page must be accounted",
                ),
            ),
            inventory_policy_version="inventory-v1",
        )

    def test_high_importance_omission_blocks_claim_gate(self):
        inventory = self._inventory()
        source = inventory.page_entries[0].source_id
        audit = OmissionAudit(
            audit_id=f"omission_audit_{'1' * 32}",
            source_inventory_ref=artifact_ref(
                ArtifactType.SOURCE_INVENTORY,
                "2",
            ),
            claim_ledger_ref=artifact_ref(
                ArtifactType.CLAIM_LEDGER,
                "3",
            ),
            accounted_source_ids=(),
            omitted_source_ids=(source,),
            explicitly_nonclaim_source_ids=(),
            unresolved_source_ids=(),
            high_importance_omitted_source_ids=(source,),
            must_have_recall=0,
            omission_reasons=(
                OmissionReason(
                    source_id=source,
                    reason_code="claim_missing",
                    explanation="Must-have source was not atomized",
                    evidence_refs=(
                        courseware_evidence("1", kind="page"),
                    ),
                ),
            ),
            auditor_attempts=(
                AuditorAttempt(
                    attempt=1,
                    producer=artifact_producer(
                        "8",
                        RuntimeRole.OMISSION_AUDITOR,
                    ),
                    input_digest=digest("8"),
                    outcome="omission_found",
                ),
            ),
        )

        result = evaluate_omission_audit(inventory, audit)

        self.assertFalse(result.accepted)
        self.assertIn(
            "high_importance_source_omitted",
            result.reason_codes,
        )
        self.assertIn(
            "must_have_source_not_accounted",
            result.reason_codes,
        )

    def test_complete_inventory_accounting_passes(self):
        inventory = self._inventory()
        source = inventory.page_entries[0].source_id
        audit = OmissionAudit(
            audit_id=f"omission_audit_{'2' * 32}",
            source_inventory_ref=artifact_ref(
                ArtifactType.SOURCE_INVENTORY,
                "2",
            ),
            claim_ledger_ref=artifact_ref(
                ArtifactType.CLAIM_LEDGER,
                "3",
            ),
            accounted_source_ids=(source,),
            omitted_source_ids=(),
            explicitly_nonclaim_source_ids=(),
            unresolved_source_ids=(),
            must_have_recall=1,
            auditor_attempts=(
                AuditorAttempt(
                    attempt=1,
                    producer=artifact_producer(
                        "9",
                        RuntimeRole.OMISSION_AUDITOR,
                    ),
                    input_digest=digest("9"),
                    outcome="pass",
                ),
            ),
        )

        self.assertTrue(
            evaluate_omission_audit(inventory, audit).accepted
        )


if __name__ == "__main__":
    unittest.main()
