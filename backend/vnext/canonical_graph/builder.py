from __future__ import annotations

import hashlib
import re
from collections import defaultdict

from backend.vnext.artifacts.canonical import (
    canonical_json_bytes,
    payload_digest,
)
from backend.vnext.contracts.claims import (
    ClaimLedger,
    ClaimPublicationStatus,
    ClaimRecord,
    ClaimType,
    InstructionalRole,
    SourceEntailmentStatus,
)
from backend.vnext.contracts.common import (
    ArtifactProducerRef,
    ArtifactRef,
    RuntimeRole,
    StringValue,
)
from backend.vnext.contracts.evidence import EvidenceRef
from backend.vnext.contracts.graph import (
    CanonicalBuildManifest,
    CanonicalConcept,
    CanonicalExplicitGraph,
    CanonicalRelation,
    CanonicalStatus,
    ConceptOrigin,
    ConfidenceComponent,
    EvidenceAuthority,
    GraphAuditItem,
    HierarchyDirectness,
    PedagogicalRole,
    RelationAssessmentLedger,
    RelationProposalLedger,
    SemanticKind,
    SemanticRelation,
    VerifierClassification,
    VerifierDecision,
)
from backend.vnext.contracts.regions import (
    RegionPlanStatus,
    ReplanRequest,
    ReplanStatus,
)
from backend.vnext.regions.planner import RegionPlanningResult


CANONICAL_POLICY_VERSION = "canonical-explicit-v0"

_CANONICALIZER = ArtifactProducerRef(
    producer_id="vnext-explicit-canonicalizer",
    producer_version="1.0.0",
    role=RuntimeRole.CANONICALIZER,
)
_RELATION_PROPOSER = ArtifactProducerRef(
    producer_id="vnext-explicit-relation-proposer",
    producer_version="1.0.0",
    role=RuntimeRole.RELATION_PROPOSER,
)
_RELATION_VERIFIER = ArtifactProducerRef(
    producer_id="vnext-explicit-relation-verifier-a",
    producer_version="1.0.0",
    role=RuntimeRole.RELATION_VERIFIER_A,
)


def _stable_id(prefix: str, value: object) -> str:
    digest = hashlib.sha256(
        b"zlb-vnext-canonical-id-v1\0" + canonical_json_bytes(value)
    ).hexdigest()
    return prefix + digest[:32]


def _normalized(text: str) -> str:
    return " ".join(text.split()).strip()


def _structural_key(text: str) -> str:
    value = re.sub(r"^#{1,6}\s+", "", _normalized(text))
    return value.casefold()


def _unique_evidence(
    evidence_refs: list[EvidenceRef],
) -> tuple[EvidenceRef, ...]:
    unique: dict[tuple[str, str], EvidenceRef] = {}
    for evidence in evidence_refs:
        unique[(evidence.namespace.value, evidence.ref_id)] = evidence
    return tuple(unique.values())


def _semantic_kind(claim_type: ClaimType) -> SemanticKind:
    return {
        ClaimType.DEFINITION: SemanticKind.CONCEPT,
        ClaimType.PROPERTY: SemanticKind.PROPERTY,
        ClaimType.MECHANISM: SemanticKind.MECHANISM,
        ClaimType.REACTION: SemanticKind.REACTION,
        ClaimType.CONDITION: SemanticKind.CONDITION,
        ClaimType.COMPARISON: SemanticKind.CONCEPT,
        ClaimType.EXAMPLE: SemanticKind.EXAMPLE,
        ClaimType.EXCEPTION: SemanticKind.EXCEPTION,
        ClaimType.PROCEDURE: SemanticKind.METHOD,
        ClaimType.WARNING: SemanticKind.CONDITION,
        ClaimType.SUMMARY: SemanticKind.CONCEPT,
        ClaimType.INSTRUCTION: SemanticKind.METHOD,
        ClaimType.STRUCTURAL_FACT: SemanticKind.TOPIC,
    }[claim_type]


def _pedagogical_role(role: InstructionalRole) -> PedagogicalRole:
    return {
        InstructionalRole.DEFINITION: PedagogicalRole.DEFINITION,
        InstructionalRole.PRINCIPLE: PedagogicalRole.PRINCIPLE,
        InstructionalRole.PROCEDURE: PedagogicalRole.PROCEDURE,
        InstructionalRole.COMPARISON: PedagogicalRole.COMPARISON,
        InstructionalRole.APPLICATION: PedagogicalRole.APPLICATION,
        InstructionalRole.EXERCISE: PedagogicalRole.EXERCISE,
        InstructionalRole.REVIEW: PedagogicalRole.PRINCIPLE,
        InstructionalRole.EXAMPLE: PedagogicalRole.APPLICATION,
        InstructionalRole.WARNING: PedagogicalRole.PRINCIPLE,
        InstructionalRole.OTHER: PedagogicalRole.PRINCIPLE,
    }[role]


def _accepted_claim(claim: ClaimRecord) -> bool:
    return (
        claim.publication_status is ClaimPublicationStatus.CORE
        and claim.source_entailment_status
        in {
            SourceEntailmentStatus.ENTAILED,
            SourceEntailmentStatus.PARTIAL,
        }
    )


def _relation_candidate(
    *,
    parent_concept_id: str,
    child_concept_id: str,
    region_plan_ref: ArtifactRef,
    evidence_refs: tuple[EvidenceRef, ...],
    source_claim_ids: tuple[str, ...],
    locator: object,
) -> CanonicalRelation:
    return CanonicalRelation(
        relation_id=_stable_id("relation_", locator),
        source_id=parent_concept_id,
        target_id=child_concept_id,
        semantic_relation=SemanticRelation.TOPIC_CONTAINS,
        hierarchy_directness=HierarchyDirectness.DIRECT,
        evidence_authority=EvidenceAuthority.OUTLINE_STRUCTURAL,
        source_claim_ids=source_claim_ids,
        edge_evidence_refs=evidence_refs,
        region_plan_ref=region_plan_ref,
        verifier_decisions=(),
        status=CanonicalStatus.CANDIDATE,
    )


def _build_candidate_graph(
    ledger: ClaimLedger,
    planning: RegionPlanningResult,
    *,
    source_observation_ref: ArtifactRef,
    claim_ledger_ref: ArtifactRef,
    replan_requests: tuple[ReplanRequest, ...] = (),
    additional_input_refs: tuple[ArtifactRef, ...] = (),
) -> CanonicalExplicitGraph:
    """Assemble concepts and unverified explicit relation proposals."""

    accepted_plans = tuple(
        plan
        for plan in planning.final_plans
        if plan.status is RegionPlanStatus.ACCEPTED
    )
    plan_by_region = {plan.region_id: plan for plan in accepted_plans}
    structural_claims: dict[str, list[ClaimRecord]] = defaultdict(list)
    for claim in ledger.claims:
        if claim.claim_type is ClaimType.STRUCTURAL_FACT:
            structural_claims[
                _structural_key(claim.normalized_text)
            ].append(claim)

    concepts: list[CanonicalConcept] = []
    unresolved_items: list[GraphAuditItem] = []
    region_concept_ids: dict[str, str] = {}
    for plan in accepted_plans:
        matching_claims = structural_claims.get(
            _structural_key(plan.theme_label),
            [],
        )
        concept_id = _stable_id(
            "concept_",
            {
                "kind": "region",
                "region_id": plan.region_id,
            },
        )
        region_concept_ids[plan.region_id] = concept_id
        concepts.append(
            CanonicalConcept(
                concept_id=concept_id,
                canonical_name=plan.theme_label,
                semantic_kind=SemanticKind.TOPIC,
                pedagogical_role=PedagogicalRole.PRINCIPLE,
                origin=ConceptOrigin.OUTLINE_ANCHOR,
                scope=plan.region_id,
                source_claim_ids=tuple(
                    sorted(claim.claim_id for claim in matching_claims)
                ),
                source_evidence_refs=plan.evidence_refs,
                status=CanonicalStatus.ACCEPTED,
                confidence_components=(
                    ConfidenceComponent(
                        name="explicit_outline_anchor",
                        score=1,
                        policy_version=CANONICAL_POLICY_VERSION,
                    ),
                ),
            )
        )

    grouped_claims: dict[
        tuple[str, SemanticKind, PedagogicalRole],
        list[ClaimRecord],
    ] = defaultdict(list)
    for claim in ledger.claims:
        if claim.claim_type is ClaimType.STRUCTURAL_FACT:
            if not any(
                _structural_key(plan.theme_label)
                == _structural_key(claim.normalized_text)
                for plan in accepted_plans
            ):
                unresolved_items.append(
                    GraphAuditItem(
                        item_type="claim",
                        item_id=claim.claim_id,
                        reason_codes=(
                            "structural_claim_without_accepted_region",
                        ),
                        evidence_refs=claim.source_evidence_refs,
                    )
                )
            continue
        if claim.claim_type is ClaimType.INSTRUCTION:
            unresolved_items.append(
                GraphAuditItem(
                    item_type="claim",
                    item_id=claim.claim_id,
                    reason_codes=("instruction_not_core_concept",),
                    evidence_refs=claim.source_evidence_refs,
                )
            )
            continue
        name = _normalized(claim.normalized_text)
        if len(name) > 512:
            unresolved_items.append(
                GraphAuditItem(
                    item_type="claim",
                    item_id=claim.claim_id,
                    reason_codes=("canonical_label_too_long",),
                    evidence_refs=claim.source_evidence_refs,
                )
            )
            continue
        grouped_claims[
            (
                name.casefold(),
                _semantic_kind(claim.claim_type),
                _pedagogical_role(claim.instructional_role),
            )
        ].append(claim)

    claim_to_concept: dict[str, str] = {}
    concept_claims: dict[str, tuple[ClaimRecord, ...]] = {}
    for (normalized_name, semantic_kind, role), claims in sorted(
        grouped_claims.items(),
        key=lambda item: item[0],
    ):
        ordered_claims = tuple(sorted(claims, key=lambda item: item.claim_id))
        concept_id = _stable_id(
            "concept_",
            {
                "claim_ids": [claim.claim_id for claim in ordered_claims],
                "kind": semantic_kind.value,
                "name": normalized_name,
                "role": role.value,
            },
        )
        for claim in ordered_claims:
            claim_to_concept[claim.claim_id] = concept_id
        concept_claims[concept_id] = ordered_claims
        accepted = any(_accepted_claim(claim) for claim in ordered_claims)
        evidence = _unique_evidence(
            [
                evidence
                for claim in ordered_claims
                for evidence in claim.source_evidence_refs
            ]
        )
        regions = sorted({claim.leaf_region_id for claim in ordered_claims})
        canonical_name = _normalized(ordered_claims[0].normalized_text)
        aliases = tuple(
            sorted(
                {
                    _normalized(claim.source_text)
                    for claim in ordered_claims
                    if _normalized(claim.source_text) != canonical_name
                }
            )
        )
        concepts.append(
            CanonicalConcept(
                concept_id=concept_id,
                canonical_name=canonical_name,
                aliases=aliases,
                semantic_kind=semantic_kind,
                pedagogical_role=role,
                origin=ConceptOrigin.EXPLICIT,
                scope=regions[0] if len(regions) == 1 else "cross_region",
                source_claim_ids=tuple(
                    claim.claim_id for claim in ordered_claims
                ),
                source_evidence_refs=evidence,
                status=(
                    CanonicalStatus.ACCEPTED
                    if accepted
                    else CanonicalStatus.ABSTAINED
                ),
                confidence_components=(
                    ConfidenceComponent(
                        name="source_entailment",
                        score=(
                            1
                            if all(
                                claim.source_entailment_status
                                is SourceEntailmentStatus.ENTAILED
                                for claim in ordered_claims
                            )
                            else 0.5
                        ),
                        policy_version=CANONICAL_POLICY_VERSION,
                    ),
                ),
            )
        )
        if not accepted:
            unresolved_items.append(
                GraphAuditItem(
                    item_type="concept",
                    item_id=concept_id,
                    reason_codes=("claim_not_core_publishable",),
                    evidence_refs=evidence,
                )
            )

    relation_inputs: dict[
        tuple[str, str, str],
        dict[str, object],
    ] = {}

    def add_relation(
        *,
        parent_concept_id: str,
        child_concept_id: str,
        plan_ref: ArtifactRef,
        evidence_refs: tuple[EvidenceRef, ...],
        source_claim_ids: tuple[str, ...],
        reason: str,
    ) -> None:
        key = (
            parent_concept_id,
            child_concept_id,
            plan_ref.artifact_id,
        )
        current = relation_inputs.setdefault(
            key,
            {
                "evidence": [],
                "claim_ids": set(),
                "reason": reason,
            },
        )
        current["evidence"].extend(evidence_refs)
        current["claim_ids"].update(source_claim_ids)

    for plan in accepted_plans:
        if plan.parent_region_id is None:
            continue
        parent_concept_id = region_concept_ids.get(plan.parent_region_id)
        child_concept_id = region_concept_ids.get(plan.region_id)
        parent_plan = plan_by_region.get(plan.parent_region_id)
        parent_ref = planning.plan_ref_by_region.get(plan.parent_region_id)
        if (
            parent_concept_id is None
            or child_concept_id is None
            or parent_plan is None
            or parent_ref is None
        ):
            unresolved_items.append(
                GraphAuditItem(
                    item_type="region",
                    item_id=plan.region_id,
                    reason_codes=("accepted_region_parent_unavailable",),
                    evidence_refs=plan.evidence_refs,
                )
            )
            continue
        child_claim_ids = tuple(
            claim.claim_id
            for claim in structural_claims.get(
                _structural_key(plan.theme_label),
                [],
            )
        )
        add_relation(
            parent_concept_id=parent_concept_id,
            child_concept_id=child_concept_id,
            plan_ref=parent_ref,
            evidence_refs=_unique_evidence(
                [*parent_plan.evidence_refs, *plan.evidence_refs]
            ),
            source_claim_ids=child_claim_ids,
            reason="accepted_region_parent",
        )

    for concept_id, claims in concept_claims.items():
        concept = next(
            item for item in concepts if item.concept_id == concept_id
        )
        if concept.status is not CanonicalStatus.ACCEPTED:
            continue
        parent_region_ids = {claim.leaf_region_id for claim in claims}
        claim_evidence_ids = {
            evidence.ref_id
            for claim in claims
            for evidence in claim.source_evidence_refs
        }
        for plan in accepted_plans:
            if claim_evidence_ids & set(plan.secondary_source_memberships):
                parent_region_ids.add(plan.region_id)
        attached = False
        for region_id in sorted(parent_region_ids):
            parent_concept_id = region_concept_ids.get(region_id)
            plan = plan_by_region.get(region_id)
            plan_ref = planning.plan_ref_by_region.get(region_id)
            if parent_concept_id is None or plan is None or plan_ref is None:
                continue
            evidence = _unique_evidence(
                [
                    *plan.evidence_refs,
                    *(
                        evidence
                        for claim in claims
                        for evidence in claim.source_evidence_refs
                    ),
                ]
            )
            add_relation(
                parent_concept_id=parent_concept_id,
                child_concept_id=concept_id,
                plan_ref=plan_ref,
                evidence_refs=evidence,
                source_claim_ids=tuple(
                    claim.claim_id for claim in claims
                ),
                reason="leaf_claim_region_membership",
            )
            attached = True
        if not attached:
            unresolved_items.append(
                GraphAuditItem(
                    item_type="concept",
                    item_id=concept_id,
                    reason_codes=("accepted_claim_without_accepted_parent",),
                    evidence_refs=concept.source_evidence_refs,
                )
            )

    relations = tuple(
        _relation_candidate(
            parent_concept_id=parent_id,
            child_concept_id=child_id,
            region_plan_ref=next(
                ref
                for ref in planning.accepted_plan_refs
                if ref.artifact_id == plan_artifact_id
            ),
            evidence_refs=_unique_evidence(data["evidence"]),
            source_claim_ids=tuple(sorted(data["claim_ids"])),
            locator={
                "child": child_id,
                "parent": parent_id,
                "plan": plan_artifact_id,
                "reason": data["reason"],
            },
        )
        for (parent_id, child_id, plan_artifact_id), data in sorted(
            relation_inputs.items()
        )
    )
    for plan in planning.final_plans:
        if plan.status is RegionPlanStatus.ACCEPTED:
            continue
        unresolved_items.append(
            GraphAuditItem(
                item_type="region",
                item_id=plan.region_id,
                reason_codes=("region_not_accepted",),
                evidence_refs=plan.evidence_refs,
            )
        )
    for request in replan_requests:
        closed = (
            request.status
            in {
                ReplanStatus.REJECTED,
                ReplanStatus.RESOLVED,
                ReplanStatus.SUPERSEDED,
            }
            and request.closure_digest is not None
            and request.resolved_tree_revision is not None
        )
        if closed:
            continue
        unresolved_items.append(
            GraphAuditItem(
                item_type="region",
                item_id=request.affected_region_id,
                reason_codes=("open_replan_quarantined",),
                evidence_refs=request.evidence_refs,
            )
        )

    input_refs = (
        source_observation_ref,
        claim_ledger_ref,
        *planning.accepted_plan_refs,
        *additional_input_refs,
    )
    policy_digest = payload_digest(
        {
            "accepted_origins": ["explicit", "outline_anchor"],
            "accepted_relation_authorities": [
                "courseware_direct",
                "outline_structural",
            ],
            "policy": CANONICAL_POLICY_VERSION,
        }
    )
    return CanonicalExplicitGraph(
        graph_id=_stable_id(
            "graph_",
            {
                "input_digests": [ref.payload_digest for ref in input_refs],
                "policy": policy_digest,
            },
        ),
        source_observation_ref=source_observation_ref,
        claim_ledger_ref=claim_ledger_ref,
        region_plan_refs=planning.accepted_plan_refs,
        concepts=tuple(concepts),
        relations=relations,
        unresolved_items=tuple(unresolved_items),
        build_manifest=CanonicalBuildManifest(
            builder=_CANONICALIZER,
            policy_digest=policy_digest,
            input_digests=tuple(
                ref.payload_digest for ref in input_refs
            ),
            parameters=(
                StringValue(key="region_mode", value="explicit_only"),
                StringValue(key="root_fallback", value="disabled"),
                StringValue(key="external_core_edges", value="disabled"),
            ),
        ),
    )


def build_relation_proposal_ledger(
    ledger: ClaimLedger,
    planning: RegionPlanningResult,
    *,
    source_observation_ref: ArtifactRef,
    claim_ledger_ref: ArtifactRef,
    replan_requests: tuple[ReplanRequest, ...] = (),
    additional_input_refs: tuple[ArtifactRef, ...] = (),
) -> RelationProposalLedger:
    candidate = _build_candidate_graph(
        ledger,
        planning,
        source_observation_ref=source_observation_ref,
        claim_ledger_ref=claim_ledger_ref,
        replan_requests=replan_requests,
        additional_input_refs=additional_input_refs,
    )
    candidate_digest = payload_digest(candidate)
    return RelationProposalLedger(
        owner_id=source_observation_ref.owner_id,
        candidate_graph_digest=candidate_digest,
        proposer=_RELATION_PROPOSER,
        policy_digest=payload_digest(
            {
                "policy": "explicit-relation-proposal-v1",
                "candidate_graph_digest": candidate_digest,
            }
        ),
        proposed_relations=candidate.relations,
    )


def build_relation_assessment_ledger(
    proposal_ledger: RelationProposalLedger,
) -> RelationAssessmentLedger:
    accepted_relations: list[CanonicalRelation] = []
    for relation in proposal_ledger.proposed_relations:
        evidence_kwargs = (
            {"outline_evidence_refs": relation.edge_evidence_refs}
            if relation.evidence_authority
            is EvidenceAuthority.OUTLINE_STRUCTURAL
            else {"courseware_evidence_refs": relation.edge_evidence_refs}
        )
        decision = VerifierDecision(
            verifier=_RELATION_VERIFIER,
            classification=VerifierClassification.DIRECT,
            supports_relation=True,
            reason_codes=("explicit_region_membership",),
            **evidence_kwargs,
        )
        accepted_relations.append(
            CanonicalRelation.model_validate(
                {
                    **relation.model_dump(mode="python"),
                    "verifier_decisions": (decision,),
                    "status": CanonicalStatus.ACCEPTED,
                }
            )
        )
    return RelationAssessmentLedger(
        owner_id=proposal_ledger.owner_id,
        candidate_graph_digest=proposal_ledger.candidate_graph_digest,
        proposer=proposal_ledger.proposer,
        verifier=_RELATION_VERIFIER,
        policy_digest=payload_digest(
            {
                "policy": "explicit-relation-assessment-v1",
                "candidate_graph_digest": (
                    proposal_ledger.candidate_graph_digest
                ),
                "proposal_policy_digest": proposal_ledger.policy_digest,
            }
        ),
        accepted_relations=tuple(accepted_relations),
    )


def build_canonical_explicit_graph(
    ledger: ClaimLedger,
    planning: RegionPlanningResult,
    *,
    source_observation_ref: ArtifactRef,
    claim_ledger_ref: ArtifactRef,
    relation_assessment_ledger: RelationAssessmentLedger,
    replan_requests: tuple[ReplanRequest, ...] = (),
    additional_input_refs: tuple[ArtifactRef, ...] = (),
) -> CanonicalExplicitGraph:
    candidate = _build_candidate_graph(
        ledger,
        planning,
        source_observation_ref=source_observation_ref,
        claim_ledger_ref=claim_ledger_ref,
        replan_requests=replan_requests,
        additional_input_refs=additional_input_refs,
    )
    if (
        relation_assessment_ledger.owner_id
        != source_observation_ref.owner_id
    ):
        raise ValueError("relation assessment ledger owner mismatch")
    if relation_assessment_ledger.candidate_graph_digest != payload_digest(
        candidate
    ):
        raise ValueError(
            "relation assessment ledger references another candidate graph"
        )
    candidates = {
        relation.relation_id: relation for relation in candidate.relations
    }
    accepted = {
        relation.relation_id: relation
        for relation in relation_assessment_ledger.accepted_relations
    }
    if set(candidates) != set(accepted):
        raise ValueError(
            "relation assessment ledger must cover every proposal exactly"
        )
    for relation_id, assessed in accepted.items():
        proposal = candidates[relation_id]
        comparable = assessed.model_dump(
            mode="python",
            exclude={"status", "verifier_decisions"},
        )
        expected = proposal.model_dump(
            mode="python",
            exclude={"status", "verifier_decisions"},
        )
        if comparable != expected:
            raise ValueError(
                "relation assessment cannot rewrite proposal semantics"
            )
    ledger_digest = payload_digest(relation_assessment_ledger)
    return CanonicalExplicitGraph(
        graph_id=_stable_id(
            "graph_",
            {
                "candidate_graph_digest": payload_digest(candidate),
                "relation_ledger_digest": ledger_digest,
            },
        ),
        source_observation_ref=candidate.source_observation_ref,
        claim_ledger_ref=candidate.claim_ledger_ref,
        region_plan_refs=candidate.region_plan_refs,
        concepts=candidate.concepts,
        relations=tuple(
            accepted[relation_id] for relation_id in sorted(accepted)
        ),
        unresolved_items=candidate.unresolved_items,
        rejected_items=candidate.rejected_items,
        decision_log=candidate.decision_log,
        build_manifest=candidate.build_manifest.model_copy(
            update={
                "input_digests": (
                    *candidate.build_manifest.input_digests,
                    ledger_digest,
                ),
                "parameters": (
                    *candidate.build_manifest.parameters,
                    StringValue(
                        key="relation_assessment_policy",
                        value="explicit-relation-assessment-v1",
                    ),
                ),
            }
        ),
    )
