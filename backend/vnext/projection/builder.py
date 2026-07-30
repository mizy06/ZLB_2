from __future__ import annotations

import hashlib

from backend.vnext.artifacts.canonical import (
    canonical_json_bytes,
    payload_digest,
)
from backend.vnext.contracts.common import ArtifactRef, StringValue
from backend.vnext.contracts.graph import (
    CanonicalExplicitGraph,
    CanonicalStatus,
    EvidenceAuthority,
    HierarchyDirectness,
    SemanticRelation,
)
from backend.vnext.contracts.projection import (
    DiagnosticProjection,
    LayoutProfile,
    ProjectionAggregation,
    ProjectionDiagnostic,
    ProjectionParentSelection,
    ProjectionPurpose,
    ProjectionQualityStatus,
)

from .validation import (
    compute_projection_hash,
    validate_projection_against_graph,
)


_HIERARCHY_RELATIONS = frozenset(
    {
        SemanticRelation.TOPIC_CONTAINS,
        SemanticRelation.IS_A,
        SemanticRelation.PART_OF,
        SemanticRelation.STAGE_OF,
        SemanticRelation.EXAMPLE_OF,
    }
)
VIEW_PARENT_POLICY_VERSION = "view-parent-policy-v1"


def _parent_semantic_priority(relation, purpose: ProjectionPurpose):
    authority_rank = {
        EvidenceAuthority.OUTLINE_STRUCTURAL: 0,
        EvidenceAuthority.COURSEWARE_DIRECT: 1,
    }.get(relation.evidence_authority, 2)
    purpose_rank = (
        0
        if purpose in {
            ProjectionPurpose.OVERVIEW,
            ProjectionPurpose.SECTION_FOCUS,
            ProjectionPurpose.EXPORT,
        }
        else 1
    )
    region_support_rank = 0 if relation.region_plan_ref is not None else 1
    return purpose_rank, authority_rank, region_support_rank


def _parent_total_order(relation, purpose: ProjectionPurpose):
    plan_id = (
        relation.region_plan_ref.artifact_id
        if relation.region_plan_ref is not None
        else ""
    )
    return (
        *_parent_semantic_priority(relation, purpose),
        plan_id,
        relation.source_id,
        relation.relation_id,
    )


def _stable_id(prefix: str, value: object) -> str:
    digest = hashlib.sha256(
        b"zlb-vnext-projection-id-v1\0" + canonical_json_bytes(value)
    ).hexdigest()
    return prefix + digest[:32]


def _layout_profile(
    purpose: ProjectionPurpose,
    *,
    medium: str,
    node_budget: int,
) -> LayoutProfile:
    direction = "outline"
    if medium == "web":
        direction = "source_order_single_side"
    elif medium in {"png", "pdf"}:
        direction = "paged"
    return LayoutProfile(
        profile_id=f"{purpose.value}-{medium}-v1",
        medium=medium,
        direction=direction,
        node_budget=node_budget,
        parameters=(
            StringValue(key="semantic_parent_source", value="canonical_only"),
            StringValue(key="root_fallback", value="disabled"),
        ),
    )


def build_diagnostic_projection(
    graph: CanonicalExplicitGraph,
    *,
    canonical_graph_ref: ArtifactRef,
    purpose: ProjectionPurpose = ProjectionPurpose.OVERVIEW,
    medium: str = "web",
    node_budget: int = 32,
) -> DiagnosticProjection:
    """Project a single display parent without changing canonical semantics."""

    graph_digest = payload_digest(graph)
    if canonical_graph_ref.payload_digest != graph_digest:
        raise ValueError(
            "canonical graph reference digest does not match graph payload"
        )
    accepted_ids = [
        concept.concept_id
        for concept in graph.concepts
        if concept.status is CanonicalStatus.ACCEPTED
    ]
    diagnostic_mode = purpose in {
        ProjectionPurpose.REVIEW,
        ProjectionPurpose.DIAGNOSTIC,
    }
    candidate_ids = (
        [concept.concept_id for concept in graph.concepts]
        if diagnostic_mode
        else accepted_ids
    )
    included_canonical: list[str]
    aggregations: list[ProjectionAggregation] = []
    included_view_ids: list[str] = []
    if len(candidate_ids) <= node_budget:
        included_canonical = list(candidate_ids)
    elif node_budget == 1:
        included_canonical = [candidate_ids[0]]
    else:
        included_canonical = list(candidate_ids[: node_budget - 1])
        hidden_accepted = tuple(
            concept_id
            for concept_id in accepted_ids
            if concept_id not in included_canonical
        )
        if hidden_accepted:
            view_id = (
                "view:more-concepts-"
                + hashlib.sha256(
                    canonical_json_bytes(hidden_accepted)
                ).hexdigest()[:16]
            )
            aggregations.append(
                ProjectionAggregation(
                    view_node_id=view_id,
                    label=f"More concepts ({len(hidden_accepted)})",
                    member_concept_ids=hidden_accepted,
                )
            )
            included_view_ids.append(view_id)

    included_set = set(included_canonical)
    hidden_ids = tuple(
        concept.concept_id
        for concept in graph.concepts
        if concept.concept_id not in included_set
    )
    accepted_direct_relations = tuple(
        relation
        for relation in graph.relations
        if relation.status is CanonicalStatus.ACCEPTED
        and relation.hierarchy_directness is HierarchyDirectness.DIRECT
        and relation.semantic_relation in _HIERARCHY_RELATIONS
    )
    incoming: dict[str, list] = {}
    for relation in accepted_direct_relations:
        incoming.setdefault(relation.target_id, []).append(relation)
    parent_selections: list[ProjectionParentSelection] = []
    diagnostics: list[ProjectionDiagnostic] = []
    ambiguous_parent_ids: list[str] = []
    for child_id in included_canonical:
        candidates = incoming.get(child_id, [])
        visible = sorted(
            (
                relation
                for relation in candidates
                if relation.source_id in included_set
            ),
            key=lambda relation: _parent_total_order(relation, purpose),
        )
        suppressed = sorted(
            (
                relation
                for relation in candidates
                if relation.source_id not in included_set
            ),
            key=lambda relation: _parent_total_order(relation, purpose),
        )
        if not visible:
            if suppressed:
                diagnostics.append(
                    ProjectionDiagnostic(
                        code="parent_hidden_by_projection_budget",
                        severity="warning",
                        message=(
                            "All accepted canonical parents are hidden by "
                            "the current projection budget."
                        ),
                        affected_ids=(child_id,),
                    )
                )
            continue
        selected = visible[0]
        selected_priority = _parent_semantic_priority(selected, purpose)
        tied = tuple(
            relation
            for relation in visible[1:]
            if _parent_semantic_priority(relation, purpose)
            == selected_priority
        )
        if tied:
            ambiguous_parent_ids.append(child_id)
        alternate_ids = tuple(
            relation.relation_id for relation in visible[1:]
        )
        suppressed_ids = tuple(
            relation.relation_id for relation in suppressed
        )
        parent_selections.append(
            ProjectionParentSelection(
                child_concept_id=child_id,
                selected_parent_edge_id=selected.relation_id,
                alternate_parent_edge_ids=alternate_ids,
                suppressed_canonical_edge_ids=suppressed_ids,
                policy_version=VIEW_PARENT_POLICY_VERSION,
                selection_reason=(
                    "stable_id_tiebreak_requires_review"
                    if tied
                    else "semantic_priority"
                ),
            )
        )
        if alternate_ids:
            diagnostics.append(
                ProjectionDiagnostic(
                    code="canonical_multi_parent_projected",
                    severity="info",
                    message=(
                        "The teaching view selected one accepted parent and "
                        "retained alternate canonical parents."
                    ),
                    affected_ids=(child_id, *alternate_ids),
                )
            )

    accepted_incoming = {
        relation.target_id for relation in accepted_direct_relations
    }
    canonical_roots = tuple(
        concept_id
        for concept_id in accepted_ids
        if concept_id not in accepted_incoming
    )
    blocking_parentless = tuple(
        item.item_id
        for item in graph.unresolved_items
        if "accepted_claim_without_accepted_parent" in item.reason_codes
    )
    blocking_replans = tuple(
        item.item_id
        for item in graph.unresolved_items
        if "open_replan_quarantined" in item.reason_codes
    )
    if blocking_replans:
        quality_status = ProjectionQualityStatus.BLOCKED_SEMANTIC
        diagnostics.append(
            ProjectionDiagnostic(
                code="open_replan_quarantined",
                severity="blocking",
                message=(
                    "A structural correction remains open for this subtree; "
                    "the teaching view is quarantined."
                ),
                affected_ids=blocking_replans,
            )
        )
    elif blocking_parentless:
        quality_status = ProjectionQualityStatus.BLOCKED_SEMANTIC
        diagnostics.append(
            ProjectionDiagnostic(
                code="accepted_claim_parent_unresolved",
                severity="blocking",
                message=(
                    "Accepted claims remain parentless in the canonical "
                    "graph; they were not promoted to display roots."
                ),
                affected_ids=blocking_parentless,
            )
        )
    elif not accepted_ids:
        quality_status = ProjectionQualityStatus.BLOCKED_SEMANTIC
        diagnostics.append(
            ProjectionDiagnostic(
                code="no_accepted_canonical_concepts",
                severity="blocking",
                message="No accepted source-grounded concepts are available.",
            )
        )
    elif len(canonical_roots) != 1:
        quality_status = ProjectionQualityStatus.BLOCKED_SEMANTIC
        diagnostics.append(
            ProjectionDiagnostic(
                code="canonical_root_unresolved",
                severity="blocking",
                message=(
                    "The accepted canonical hierarchy does not have exactly "
                    "one displayable root; no root fallback was applied."
                ),
                affected_ids=canonical_roots,
            )
        )
    elif ambiguous_parent_ids:
        quality_status = ProjectionQualityStatus.REVIEW_REQUIRED
        diagnostics.append(
            ProjectionDiagnostic(
                code="view_parent_tie_requires_review",
                severity="warning",
                message=(
                    "Multiple accepted parents have equal product priority; "
                    "the stable tie-break is diagnostic only."
                ),
                affected_ids=tuple(sorted(ambiguous_parent_ids)),
            )
        )
    elif graph.unresolved_items:
        quality_status = ProjectionQualityStatus.REVIEW_REQUIRED
        diagnostics.append(
            ProjectionDiagnostic(
                code="canonical_items_require_review",
                severity="warning",
                message=(
                    "Canonical construction retained unresolved audit items."
                ),
                affected_ids=tuple(
                    item.item_id for item in graph.unresolved_items[:32]
                ),
            )
        )
    else:
        quality_status = ProjectionQualityStatus.PASSED

    selected_ids = tuple(
        selection.selected_parent_edge_id
        for selection in parent_selections
    )
    alternate_ids = tuple(
        edge_id
        for selection in parent_selections
        for edge_id in selection.alternate_parent_edge_ids
    )
    suppressed_ids = tuple(
        edge_id
        for selection in parent_selections
        for edge_id in selection.suppressed_canonical_edge_ids
    )
    projection = DiagnosticProjection(
        projection_id=_stable_id(
            "projection_",
            {
                "canonical_hash": graph_digest,
                "medium": medium,
                "node_budget": node_budget,
                "purpose": purpose.value,
            },
        ),
        canonical_graph_ref=canonical_graph_ref,
        canonical_hash=graph_digest,
        purpose=purpose,
        included_ids=tuple(
            [*included_canonical, *included_view_ids]
        ),
        hidden_ids=hidden_ids,
        aggregation_map=tuple(aggregations),
        parent_selections=tuple(parent_selections),
        projection_parent_edge_ids=selected_ids,
        suppressed_canonical_edge_ids=suppressed_ids,
        alternate_parent_edge_ids=alternate_ids,
        layout_profile=_layout_profile(
            purpose,
            medium=medium,
            node_budget=node_budget,
        ),
        quality_status=quality_status,
        diagnostics=tuple(diagnostics),
    )
    projection = projection.model_copy(
        update={"projection_hash": compute_projection_hash(projection)}
    )
    validate_projection_against_graph(projection, graph)
    return projection
