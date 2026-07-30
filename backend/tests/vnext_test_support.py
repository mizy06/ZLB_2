from __future__ import annotations

from backend.vnext.contracts.common import (
    ArtifactProducerRef,
    ArtifactRef,
    ArtifactType,
    ProducerRef,
    RuntimeRole,
)
from backend.vnext.contracts.evidence import EvidenceNamespace, EvidenceRef
from backend.vnext.contracts.graph import (
    CanonicalBuildManifest,
    CanonicalConcept,
    CanonicalExplicitGraph,
    CanonicalRelation,
    CanonicalStatus,
    ConceptOrigin,
    EvidenceAuthority,
    HierarchyDirectness,
    PedagogicalRole,
    SemanticKind,
    SemanticRelation,
    VerifierClassification,
    VerifierDecision,
)


def source_id(kind: str, digit: str) -> str:
    return f"src:{kind}:{digit * 64}"


def artifact_id(digit: str) -> str:
    return f"art_{digit * 32}"


def digest(digit: str) -> str:
    return f"sha256:{digit * 64}"


def region_id(digit: str) -> str:
    return f"reg_{digit * 32}"


def claim_id(digit: str) -> str:
    return f"claim_{digit * 32}"


def concept_id(digit: str) -> str:
    return f"concept_{digit * 32}"


def relation_id(digit: str) -> str:
    return f"relation_{digit * 32}"


def producer(digit: str = "1") -> ProducerRef:
    return ProducerRef(
        producer_id=f"test-producer-{digit}",
        producer_version="1.0.0",
    )


def artifact_producer(
    digit: str,
    role: RuntimeRole,
) -> ArtifactProducerRef:
    return ArtifactProducerRef(
        producer_id=f"test-producer-{digit}",
        producer_version="1.0.0",
        role=role,
    )


def artifact_ref(
    artifact_type: ArtifactType,
    digit: str,
    *,
    owner: str = "owner-a",
) -> ArtifactRef:
    return ArtifactRef(
        owner_id=owner,
        artifact_id=artifact_id(digit),
        artifact_type=artifact_type,
        payload_digest=digest(digit),
    )


def courseware_evidence(
    digit: str,
    *,
    kind: str = "block",
) -> EvidenceRef:
    return EvidenceRef(
        namespace=EvidenceNamespace.COURSEWARE,
        ref_id=source_id(kind, digit),
        content_digest=digest(digit),
    )


def external_evidence(digit: str) -> EvidenceRef:
    return EvidenceRef(
        namespace=EvidenceNamespace.EXTERNAL,
        ref_id=f"ext:snapshot:{digit * 32}",
        content_digest=digest(digit),
    )


def accepted_concept(digit: str, name: str) -> CanonicalConcept:
    return CanonicalConcept(
        concept_id=concept_id(digit),
        canonical_name=name,
        semantic_kind=SemanticKind.CONCEPT,
        pedagogical_role=PedagogicalRole.DEFINITION,
        origin=ConceptOrigin.EXPLICIT,
        scope="courseware",
        source_claim_ids=(claim_id(digit),),
        source_evidence_refs=(courseware_evidence(digit),),
        status=CanonicalStatus.ACCEPTED,
    )


def accepted_relation(
    digit: str,
    parent_digit: str,
    child_digit: str,
    *,
    relation: SemanticRelation = SemanticRelation.TOPIC_CONTAINS,
    authority: EvidenceAuthority = EvidenceAuthority.COURSEWARE_DIRECT,
    region_plan_ref: ArtifactRef | None = None,
) -> CanonicalRelation:
    evidence = courseware_evidence(digit)
    return CanonicalRelation(
        relation_id=relation_id(digit),
        source_id=concept_id(parent_digit),
        target_id=concept_id(child_digit),
        semantic_relation=relation,
        hierarchy_directness=HierarchyDirectness.DIRECT,
        evidence_authority=authority,
        source_claim_ids=(claim_id(child_digit),),
        edge_evidence_refs=(evidence,),
        region_plan_ref=region_plan_ref,
        verifier_decisions=(
            VerifierDecision(
                verifier=artifact_producer(
                    digit,
                    RuntimeRole.RELATION_VERIFIER_A,
                ),
                classification=VerifierClassification.DIRECT,
                supports_relation=True,
                courseware_evidence_refs=(evidence,),
                reason_codes=("courseware_direct",),
            ),
        ),
        status=CanonicalStatus.ACCEPTED,
    )


def graph(
    concepts: tuple[CanonicalConcept, ...],
    relations: tuple[CanonicalRelation, ...],
) -> CanonicalExplicitGraph:
    return CanonicalExplicitGraph(
        graph_id=f"graph_{'a' * 32}",
        source_observation_ref=artifact_ref(
            ArtifactType.SOURCE_OBSERVATION_IR,
            "1",
        ),
        claim_ledger_ref=artifact_ref(ArtifactType.CLAIM_LEDGER, "2"),
        region_plan_refs=(
            artifact_ref(ArtifactType.REGION_PLAN, "3"),
        ),
        concepts=concepts,
        relations=relations,
        build_manifest=CanonicalBuildManifest(
            builder=artifact_producer(
                "a",
                RuntimeRole.CANONICALIZER,
            ),
            policy_digest=digest("a"),
            input_digests=(digest("1"), digest("2"), digest("3")),
        ),
    )
