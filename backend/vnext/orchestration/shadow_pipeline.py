from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from backend.vnext.artifacts.local_store import LocalArtifactStore
from backend.vnext.canonical_graph import (
    build_canonical_explicit_graph,
    build_relation_assessment_ledger,
    build_relation_proposal_ledger,
)
from backend.vnext.claims import (
    atomize_source_claims,
    audit_claim_omissions,
)
from backend.vnext.contracts.artifacts import ArtifactEnvelope
from backend.vnext.contracts.claims import ClaimLedger, OmissionAudit
from backend.vnext.contracts.common import (
    ArtifactProducerRef,
    RuntimeRole,
)
from backend.vnext.contracts.graph import (
    CanonicalExplicitGraph,
    RelationAssessmentLedger,
    RelationProposalLedger,
)
from backend.vnext.contracts.projection import DiagnosticProjection
from backend.vnext.contracts.regions import ReplanRequest
from backend.vnext.projection import build_diagnostic_projection
from backend.vnext.regions import (
    RegionPlanningResult,
    audit_regions_bottom_up,
    plan_explicit_regions,
)

from .source_shadow import SourceShadowResult, run_source_shadow


@dataclass(frozen=True, slots=True)
class ShadowPipelineResult:
    source: SourceShadowResult
    planning: RegionPlanningResult
    claim_ledger: ClaimLedger
    claim_ledger_envelope: ArtifactEnvelope
    omission_audit: OmissionAudit
    omission_audit_envelope: ArtifactEnvelope
    replan_requests: tuple[ReplanRequest, ...]
    replan_envelopes: tuple[ArtifactEnvelope, ...]
    relation_proposal_ledger: RelationProposalLedger
    relation_proposal_envelope: ArtifactEnvelope
    relation_assessment_ledger: RelationAssessmentLedger
    relation_assessment_envelope: ArtifactEnvelope
    canonical_graph: CanonicalExplicitGraph
    canonical_graph_envelope: ArtifactEnvelope
    projection: DiagnosticProjection
    projection_envelope: ArtifactEnvelope


def _producer(
    producer_id: str,
    role: RuntimeRole,
) -> ArtifactProducerRef:
    return ArtifactProducerRef(
        producer_id=producer_id,
        producer_version="1.0.0",
        role=role,
    )


def run_shadow_pipeline(
    path: Path,
    *,
    owner_id: str,
    store: LocalArtifactStore,
) -> ShadowPipelineResult:
    """Run the explicit-only S1-S3 pipeline without touching legacy state."""

    source = run_source_shadow(path, owner_id=owner_id, store=store)
    source_ref = store.ref(source.source_envelope)
    inventory_ref = store.ref(source.inventory_envelope)
    planning = plan_explicit_regions(
        source.source_observation,
        source.source_inventory,
        owner_id=owner_id,
        source_ref=source_ref,
        inventory_ref=inventory_ref,
        store=store,
    )
    ledger = atomize_source_claims(
        source.source_observation,
        document_ir_ref=source_ref,
        region_plan_refs=planning.accepted_plan_refs,
        source_to_leaf_region=planning.source_to_leaf_region,
    )
    ledger_envelope = store.put(
        owner_id=owner_id,
        role=RuntimeRole.CLAIM_ATOMIZER,
        payload=ledger,
        producer=_producer(
            "vnext-source-claim-atomizer",
            RuntimeRole.CLAIM_ATOMIZER,
        ),
        input_refs=(source_ref, *planning.accepted_plan_refs),
    )
    ledger_ref = store.ref(ledger_envelope)
    omission_audit = audit_claim_omissions(
        source.source_inventory,
        ledger,
        source_inventory_ref=inventory_ref,
        claim_ledger_ref=ledger_ref,
        structurally_accounted_source_ids=(
            planning.structurally_accounted_source_ids
        ),
        forced_unresolved_source_ids=planning.unresolved_source_ids,
    )
    omission_envelope = store.put(
        owner_id=owner_id,
        role=RuntimeRole.OMISSION_AUDITOR,
        payload=omission_audit,
        producer=_producer(
            "vnext-source-omission-auditor",
            RuntimeRole.OMISSION_AUDITOR,
        ),
        input_refs=(inventory_ref, ledger_ref),
    )
    omission_ref = store.ref(omission_envelope)
    replan_requests = audit_regions_bottom_up(
        planning,
        source.source_inventory,
        omission_audit,
    )
    replan_envelopes: list[ArtifactEnvelope] = []
    for request in replan_requests:
        region_ref = planning.plan_ref_by_region.get(
            request.affected_region_id
        )
        input_refs = (
            (omission_ref, region_ref)
            if region_ref is not None
            else (omission_ref,)
        )
        replan_envelopes.append(
            store.put(
                owner_id=owner_id,
                role=RuntimeRole.BOTTOM_UP_REGION_AUDITOR,
                payload=request,
                producer=_producer(
                    "vnext-bottom-up-region-auditor",
                    RuntimeRole.BOTTOM_UP_REGION_AUDITOR,
                ),
                input_refs=input_refs,
            )
        )
    replan_refs = tuple(store.ref(item) for item in replan_envelopes)
    relation_proposal_ledger = build_relation_proposal_ledger(
        ledger,
        planning,
        source_observation_ref=source_ref,
        claim_ledger_ref=ledger_ref,
        replan_requests=replan_requests,
        additional_input_refs=(omission_ref, *replan_refs),
    )
    relation_proposal_envelope = store.put(
        owner_id=owner_id,
        role=RuntimeRole.RELATION_PROPOSER,
        payload=relation_proposal_ledger,
        producer=_producer(
            "vnext-explicit-relation-proposer",
            RuntimeRole.RELATION_PROPOSER,
        ),
        input_refs=(
            source_ref,
            ledger_ref,
            *planning.accepted_plan_refs,
            omission_ref,
            *replan_refs,
        ),
    )
    relation_proposal_ref = store.ref(relation_proposal_envelope)
    relation_assessment_ledger = build_relation_assessment_ledger(
        relation_proposal_ledger,
    )
    relation_assessment_envelope = store.put(
        owner_id=owner_id,
        role=RuntimeRole.RELATION_VERIFIER_A,
        payload=relation_assessment_ledger,
        producer=_producer(
            "vnext-explicit-relation-verifier-a",
            RuntimeRole.RELATION_VERIFIER_A,
        ),
        input_refs=(relation_proposal_ref,),
    )
    relation_assessment_ref = store.ref(relation_assessment_envelope)
    canonical = build_canonical_explicit_graph(
        ledger,
        planning,
        source_observation_ref=source_ref,
        claim_ledger_ref=ledger_ref,
        relation_assessment_ledger=relation_assessment_ledger,
        replan_requests=replan_requests,
        additional_input_refs=(omission_ref, *replan_refs),
    )
    canonical_envelope = store.put(
        owner_id=owner_id,
        role=RuntimeRole.CANONICALIZER,
        payload=canonical,
        producer=_producer(
            "vnext-explicit-canonicalizer",
            RuntimeRole.CANONICALIZER,
        ),
        input_refs=(
            source_ref,
            ledger_ref,
            *planning.accepted_plan_refs,
            omission_ref,
            *replan_refs,
            relation_proposal_ref,
            relation_assessment_ref,
        ),
    )
    canonical_ref = store.ref(canonical_envelope)
    projection = build_diagnostic_projection(
        canonical,
        canonical_graph_ref=canonical_ref,
    )
    projection_envelope = store.put(
        owner_id=owner_id,
        role=RuntimeRole.PROJECTION_PLANNER,
        payload=projection,
        producer=_producer(
            "vnext-diagnostic-projection-planner",
            RuntimeRole.PROJECTION_PLANNER,
        ),
        input_refs=(canonical_ref,),
    )
    return ShadowPipelineResult(
        source=source,
        planning=planning,
        claim_ledger=ledger,
        claim_ledger_envelope=ledger_envelope,
        omission_audit=omission_audit,
        omission_audit_envelope=omission_envelope,
        replan_requests=replan_requests,
        replan_envelopes=tuple(replan_envelopes),
        relation_proposal_ledger=relation_proposal_ledger,
        relation_proposal_envelope=relation_proposal_envelope,
        relation_assessment_ledger=relation_assessment_ledger,
        relation_assessment_envelope=relation_assessment_envelope,
        canonical_graph=canonical,
        canonical_graph_envelope=canonical_envelope,
        projection=projection,
        projection_envelope=projection_envelope,
    )
