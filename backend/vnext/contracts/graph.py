from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from .base import FrozenContract
from .common import (
    ArtifactProducerRef,
    ArtifactRef,
    ArtifactType,
    ClaimId,
    ConceptId,
    DecisionEvent,
    RelationId,
    RuntimeRole,
    Sha256Digest,
    StringValue,
    require_artifact_type,
)
from .evidence import EvidenceNamespace, EvidenceRef, require_evidence_namespace


GraphId = Annotated[
    str,
    StringConstraints(pattern=r"^graph_[0-9a-f]{32}$"),
]


class CanonicalStatus(StrEnum):
    CANDIDATE = "candidate"
    ACCEPTED = "accepted"
    CONFLICTED = "conflicted"
    ABSTAINED = "abstained"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class SemanticKind(StrEnum):
    TOPIC = "topic"
    CONCEPT = "concept"
    REACTION_FAMILY = "reaction_family"
    REACTION = "reaction"
    MECHANISM = "mechanism"
    METHOD = "method"
    PROPERTY = "property"
    CONDITION = "condition"
    RESULT = "result"
    FORMULA = "formula"
    EXAMPLE = "example"
    EXCEPTION = "exception"


class PedagogicalRole(StrEnum):
    DEFINITION = "definition"
    PRINCIPLE = "principle"
    PROCEDURE = "procedure"
    COMPARISON = "comparison"
    APPLICATION = "application"
    EXERCISE = "exercise"


class ConceptOrigin(StrEnum):
    EXPLICIT = "explicit"
    OUTLINE_ANCHOR = "outline_anchor"
    PLANNER_INDUCED_REGION = "planner_induced_region"
    EXTERNAL_REFERENCE = "external_reference"


class SemanticRelation(StrEnum):
    TOPIC_CONTAINS = "topic_contains"
    IS_A = "is_a"
    PART_OF = "part_of"
    STAGE_OF = "stage_of"
    EXAMPLE_OF = "example_of"
    PREREQUISITE = "prerequisite"
    CAUSES = "causes"
    PRECEDES = "precedes"
    CONTRASTS = "contrasts"
    REACTS_WITH = "reacts_with"
    REVIEW_OF = "review_of"
    DEPENDS_ON = "depends_on"
    USED_FOR = "used_for"
    CONDITION_FOR = "condition_for"
    MECHANISM_OF = "mechanism_of"
    TRANSFORMS_TO = "transforms_to"


class HierarchyDirectness(StrEnum):
    DIRECT = "direct"
    ANCESTOR_ONLY = "ancestor_only"
    NON_HIERARCHICAL = "non_hierarchical"
    UNCERTAIN = "uncertain"


class EvidenceAuthority(StrEnum):
    COURSEWARE_DIRECT = "courseware_direct"
    OUTLINE_STRUCTURAL = "outline_structural"
    COURSEWARE_AGGREGATE = "courseware_aggregate"
    EXTERNAL_ONLY = "external_only"
    RETRIEVAL_ONLY = "retrieval_only"


class VerifierClassification(StrEnum):
    DIRECT = "direct"
    ANCESTOR_ONLY = "ancestor_only"
    SIBLING = "sibling"
    SEMANTIC_LINK = "semantic_link"
    UNRELATED = "unrelated"
    INSUFFICIENT = "insufficient"


class ConfidenceComponent(FrozenContract):
    name: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    score: float = Field(ge=0, le=1)
    policy_version: Annotated[
        str,
        StringConstraints(min_length=1, max_length=128),
    ]


class VerifierDecision(FrozenContract):
    verifier: ArtifactProducerRef
    classification: VerifierClassification
    supports_relation: bool
    courseware_evidence_refs: tuple[EvidenceRef, ...] = ()
    outline_evidence_refs: tuple[EvidenceRef, ...] = ()
    reason_codes: tuple[
        Annotated[str, StringConstraints(min_length=1, max_length=128)],
        ...,
    ]

    @model_validator(mode="after")
    def validate_evidence(self) -> "VerifierDecision":
        if self.verifier.role not in {
            RuntimeRole.RELATION_VERIFIER_A,
            RuntimeRole.RELATION_VERIFIER_B,
            RuntimeRole.ARBITER,
        }:
            raise ValueError(
                "relation decision requires verifier or arbiter role"
            )
        require_evidence_namespace(
            self.courseware_evidence_refs + self.outline_evidence_refs,
            frozenset(
                {EvidenceNamespace.COURSEWARE, EvidenceNamespace.HUMAN}
            ),
            field_name="verifier evidence",
        )
        if self.supports_relation and not (
            self.courseware_evidence_refs or self.outline_evidence_refs
        ):
            raise ValueError(
                "supporting verifier decision requires relationship evidence"
            )
        return self


class CanonicalConcept(FrozenContract):
    concept_id: ConceptId
    canonical_name: Annotated[
        str,
        StringConstraints(min_length=1, max_length=512),
    ]
    aliases: tuple[str, ...] = ()
    semantic_kind: SemanticKind
    pedagogical_role: PedagogicalRole
    origin: ConceptOrigin
    scope: Annotated[
        str,
        StringConstraints(min_length=1, max_length=256),
    ]
    source_claim_ids: tuple[ClaimId, ...] = ()
    source_evidence_refs: tuple[EvidenceRef, ...] = ()
    external_ref_ids: tuple[EvidenceRef, ...] = ()
    status: CanonicalStatus
    confidence_components: tuple[ConfidenceComponent, ...] = ()
    decision_history: tuple[DecisionEvent, ...] = ()
    supersedes: ConceptId | None = None

    @model_validator(mode="after")
    def validate_concept(self) -> "CanonicalConcept":
        require_evidence_namespace(
            self.source_evidence_refs,
            frozenset(
                {EvidenceNamespace.COURSEWARE, EvidenceNamespace.HUMAN}
            ),
            field_name="concept source_evidence_refs",
        )
        require_evidence_namespace(
            self.external_ref_ids,
            frozenset({EvidenceNamespace.EXTERNAL}),
            field_name="concept external_ref_ids",
        )
        if self.status is CanonicalStatus.ACCEPTED:
            if self.origin not in {
                ConceptOrigin.EXPLICIT,
                ConceptOrigin.OUTLINE_ANCHOR,
            }:
                raise ValueError(
                    "CanonicalExplicitGraph v0 only accepts explicit "
                    "or outline-anchor concepts"
                )
            if not self.source_claim_ids and not self.source_evidence_refs:
                raise ValueError(
                    "accepted concept requires courseware claim or evidence"
                )
        if self.supersedes == self.concept_id:
            raise ValueError("concept cannot supersede itself")
        return self


class CanonicalRelation(FrozenContract):
    relation_id: RelationId
    source_id: ConceptId
    target_id: ConceptId
    semantic_relation: SemanticRelation
    hierarchy_directness: HierarchyDirectness
    evidence_authority: EvidenceAuthority
    source_claim_ids: tuple[ClaimId, ...] = ()
    edge_evidence_refs: tuple[EvidenceRef, ...] = ()
    external_evidence_refs: tuple[EvidenceRef, ...] = ()
    region_plan_ref: ArtifactRef | None = None
    verifier_decisions: tuple[VerifierDecision, ...] = ()
    status: CanonicalStatus
    rejection_reasons: tuple[
        Annotated[str, StringConstraints(min_length=1, max_length=256)],
        ...,
    ] = ()
    decision_history: tuple[DecisionEvent, ...] = ()
    supersedes: RelationId | None = None

    @model_validator(mode="after")
    def validate_relation(self) -> "CanonicalRelation":
        if self.source_id == self.target_id:
            raise ValueError("canonical relation cannot be a self-loop")
        require_evidence_namespace(
            self.edge_evidence_refs,
            frozenset(
                {EvidenceNamespace.COURSEWARE, EvidenceNamespace.HUMAN}
            ),
            field_name="edge_evidence_refs",
        )
        require_evidence_namespace(
            self.external_evidence_refs,
            frozenset({EvidenceNamespace.EXTERNAL}),
            field_name="external_evidence_refs",
        )
        hierarchy_relations = {
            SemanticRelation.TOPIC_CONTAINS,
            SemanticRelation.IS_A,
            SemanticRelation.PART_OF,
            SemanticRelation.STAGE_OF,
            SemanticRelation.EXAMPLE_OF,
        }
        is_hierarchy = self.semantic_relation in hierarchy_relations
        if is_hierarchy and self.hierarchy_directness is (
            HierarchyDirectness.NON_HIERARCHICAL
        ):
            raise ValueError(
                "hierarchy relation cannot be marked non_hierarchical"
            )
        if not is_hierarchy and self.hierarchy_directness is not (
            HierarchyDirectness.NON_HIERARCHICAL
        ):
            raise ValueError(
                "semantic link must be marked non_hierarchical"
            )
        if self.status is CanonicalStatus.ACCEPTED:
            if self.evidence_authority not in {
                EvidenceAuthority.COURSEWARE_DIRECT,
                EvidenceAuthority.OUTLINE_STRUCTURAL,
            }:
                raise ValueError(
                    "CanonicalExplicitGraph v0 rejects aggregate, external, "
                    "and retrieval-only accepted relations"
                )
            if not self.edge_evidence_refs:
                raise ValueError(
                    "accepted relation requires relation-level evidence"
                )
            if not self.verifier_decisions or not all(
                decision.supports_relation
                for decision in self.verifier_decisions
            ):
                raise ValueError(
                    "accepted relation requires supporting verifier decisions"
                )
            if (
                self.evidence_authority
                is EvidenceAuthority.OUTLINE_STRUCTURAL
                and self.semantic_relation
                is not SemanticRelation.TOPIC_CONTAINS
            ):
                raise ValueError(
                    "outline evidence can only certify topic_contains"
                )
            if (
                self.evidence_authority
                is EvidenceAuthority.OUTLINE_STRUCTURAL
                and self.region_plan_ref is None
            ):
                raise ValueError(
                    "outline structural relation requires RegionPlan support"
                )
        if (
            self.region_plan_ref
            and self.region_plan_ref.artifact_type.value != "region_plan"
        ):
            raise ValueError(
                "region_plan_ref must reference a RegionPlan artifact"
            )
        if self.status in {
            CanonicalStatus.REJECTED,
            CanonicalStatus.CONFLICTED,
            CanonicalStatus.ABSTAINED,
        } and not self.rejection_reasons:
            raise ValueError(
                "non-accepted terminal relation requires reason codes"
            )
        if self.supersedes == self.relation_id:
            raise ValueError("relation cannot supersede itself")
        return self


class GraphAuditItem(FrozenContract):
    item_type: Literal["concept", "relation", "claim", "region"]
    item_id: Annotated[
        str,
        StringConstraints(min_length=1, max_length=128),
    ]
    reason_codes: tuple[
        Annotated[str, StringConstraints(min_length=1, max_length=128)],
        ...,
    ]
    evidence_refs: tuple[EvidenceRef, ...] = ()


class CanonicalBuildManifest(FrozenContract):
    builder: ArtifactProducerRef
    policy_digest: Sha256Digest
    input_digests: tuple[Sha256Digest, ...]
    parameters: tuple[StringValue, ...] = ()

    @model_validator(mode="after")
    def require_canonicalizer(self) -> "CanonicalBuildManifest":
        if self.builder.role is not RuntimeRole.CANONICALIZER:
            raise ValueError(
                "canonical graph builder must use canonicalizer role"
            )
        return self


class CanonicalExplicitGraph(FrozenContract):
    schema_version: Literal["0.1.0"] = "0.1.0"
    graph_id: GraphId
    source_observation_ref: ArtifactRef
    claim_ledger_ref: ArtifactRef
    region_plan_refs: tuple[ArtifactRef, ...]
    concepts: tuple[CanonicalConcept, ...]
    relations: tuple[CanonicalRelation, ...]
    unresolved_items: tuple[GraphAuditItem, ...] = ()
    rejected_items: tuple[GraphAuditItem, ...] = ()
    decision_log: tuple[DecisionEvent, ...] = ()
    build_manifest: CanonicalBuildManifest
    supersedes: ArtifactRef | None = None

    @model_validator(mode="after")
    def validate_graph(self) -> "CanonicalExplicitGraph":
        require_artifact_type(
            self.supersedes,
            ArtifactType.CANONICAL_EXPLICIT_GRAPH,
            field_name="supersedes",
        )
        if (
            self.source_observation_ref.artifact_type.value
            != "source_observation_ir"
        ):
            raise ValueError(
                "source_observation_ref must reference SourceObservationIR"
            )
        if self.claim_ledger_ref.artifact_type.value != "claim_ledger":
            raise ValueError(
                "claim_ledger_ref must reference ClaimLedger"
            )
        if any(
            ref.artifact_type.value != "region_plan"
            for ref in self.region_plan_refs
        ):
            raise ValueError("region_plan_refs may only reference RegionPlan")
        owners = {
            self.source_observation_ref.owner_id,
            self.claim_ledger_ref.owner_id,
            *(ref.owner_id for ref in self.region_plan_refs),
        }
        if self.supersedes:
            owners.add(self.supersedes.owner_id)
        if len(owners) != 1:
            raise ValueError(
                "CanonicalExplicitGraph references must remain owner-scoped"
            )
        concept_by_id = {item.concept_id: item for item in self.concepts}
        relation_by_id = {item.relation_id: item for item in self.relations}
        if len(concept_by_id) != len(self.concepts):
            raise ValueError("canonical concept IDs must be unique")
        if len(relation_by_id) != len(self.relations):
            raise ValueError("canonical relation IDs must be unique")
        accepted_concepts = {
            concept_id
            for concept_id, concept in concept_by_id.items()
            if concept.status is CanonicalStatus.ACCEPTED
        }
        for relation in self.relations:
            if (
                relation.source_id not in concept_by_id
                or relation.target_id not in concept_by_id
            ):
                raise ValueError(
                    "canonical relation references an unknown concept"
                )
            if relation.status is CanonicalStatus.ACCEPTED and (
                relation.source_id not in accepted_concepts
                or relation.target_id not in accepted_concepts
            ):
                raise ValueError(
                    "accepted relation requires accepted endpoint concepts"
                )
            if (
                relation.region_plan_ref
                and relation.region_plan_ref not in self.region_plan_refs
            ):
                raise ValueError(
                    "relation RegionPlan support must be declared by graph"
                )
            if relation.supersedes:
                previous = relation_by_id.get(relation.supersedes)
                if previous is None:
                    raise ValueError(
                        "superseding relation must retain the old relation"
                    )
                if previous.status is CanonicalStatus.ACCEPTED:
                    raise ValueError(
                        "accepted relation cannot be silently replaced "
                        "without a new decision state"
                    )
                old_hashes = {
                    ref.content_digest
                    for ref in previous.edge_evidence_refs
                    if ref.content_digest
                }
                new_hashes = {
                    ref.content_digest
                    for ref in relation.edge_evidence_refs
                    if ref.content_digest
                }
                if relation.status is CanonicalStatus.ACCEPTED and not (
                    new_hashes - old_hashes
                ):
                    raise ValueError(
                        "reopening a rejected relation requires novel "
                        "courseware evidence content"
                    )
        self._validate_hierarchy_acyclic()
        return self

    def _validate_hierarchy_acyclic(self) -> None:
        hierarchy_relations = {
            SemanticRelation.TOPIC_CONTAINS,
            SemanticRelation.IS_A,
            SemanticRelation.PART_OF,
            SemanticRelation.STAGE_OF,
            SemanticRelation.EXAMPLE_OF,
        }
        adjacency: dict[str, set[str]] = {}
        for relation in self.relations:
            if (
                relation.status is CanonicalStatus.ACCEPTED
                and relation.semantic_relation in hierarchy_relations
                and relation.hierarchy_directness
                is HierarchyDirectness.DIRECT
            ):
                adjacency.setdefault(relation.source_id, set()).add(
                    relation.target_id
                )
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node_id: str) -> None:
            if node_id in visiting:
                raise ValueError("accepted canonical hierarchy must be acyclic")
            if node_id in visited:
                return
            visiting.add(node_id)
            for target_id in adjacency.get(node_id, ()):
                visit(target_id)
            visiting.remove(node_id)
            visited.add(node_id)

        for concept_id in adjacency:
            visit(concept_id)
