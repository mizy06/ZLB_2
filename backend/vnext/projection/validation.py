from __future__ import annotations

from backend.vnext.artifacts.canonical import payload_digest
from backend.vnext.contracts.graph import (
    CanonicalExplicitGraph,
    CanonicalStatus,
    HierarchyDirectness,
)
from backend.vnext.contracts.projection import DiagnosticProjection


def compute_projection_hash(projection: DiagnosticProjection) -> str:
    payload = projection.model_dump(
        mode="json",
        exclude={"projection_hash"},
    )
    return payload_digest(payload)


def validate_projection_against_graph(
    projection: DiagnosticProjection,
    graph: CanonicalExplicitGraph,
) -> None:
    expected_hash = payload_digest(graph)
    if projection.canonical_hash != expected_hash:
        raise ValueError("projection canonical_hash does not match graph")
    if projection.canonical_graph_ref.payload_digest != expected_hash:
        raise ValueError(
            "projection graph reference digest does not match graph"
        )
    concepts = {item.concept_id: item for item in graph.concepts}
    relations = {item.relation_id: item for item in graph.relations}
    canonical_included = {
        item for item in projection.included_ids if not item.startswith("view:")
    }
    unknown = canonical_included - concepts.keys()
    if unknown:
        raise ValueError(
            "projection includes unknown canonical concepts: "
            + ", ".join(sorted(unknown))
        )
    unknown_hidden = set(projection.hidden_ids) - concepts.keys()
    if unknown_hidden:
        raise ValueError(
            "projection hides unknown canonical concepts: "
            + ", ".join(sorted(unknown_hidden))
        )
    known_projection_concepts = canonical_included | set(
        projection.hidden_ids
    )
    for aggregation in projection.aggregation_map:
        unknown_members = (
            set(aggregation.member_concept_ids) - concepts.keys()
        )
        if unknown_members:
            raise ValueError(
                "projection aggregation references unknown concepts: "
                + ", ".join(sorted(unknown_members))
            )
        if not set(aggregation.member_concept_ids) <= (
            known_projection_concepts
        ):
            raise ValueError(
                "aggregation members must be included or explicitly hidden"
            )
    for selection in projection.parent_selections:
        relation = relations.get(selection.selected_parent_edge_id)
        if relation is None:
            raise ValueError("projection selected an unknown parent edge")
        if relation.status is not CanonicalStatus.ACCEPTED:
            raise ValueError(
                "projection parent must be an accepted canonical edge"
            )
        if relation.hierarchy_directness is not HierarchyDirectness.DIRECT:
            raise ValueError(
                "projection parent must be a direct canonical hierarchy edge"
            )
        if relation.target_id != selection.child_concept_id:
            raise ValueError(
                "projection parent edge does not target selected child"
            )
        if relation.source_id not in canonical_included:
            raise ValueError(
                "projection parent source must be included in the view"
            )
        if selection.child_concept_id not in canonical_included:
            raise ValueError(
                "projection parent child must be included in the view"
            )
        for edge_id in (
            *selection.alternate_parent_edge_ids,
            *selection.suppressed_canonical_edge_ids,
        ):
            alternate = relations.get(edge_id)
            if alternate is None:
                raise ValueError(
                    "projection references an unknown canonical edge"
                )
            if alternate.status is not CanonicalStatus.ACCEPTED:
                raise ValueError(
                    "alternate and suppressed edges must remain accepted"
                )
            if alternate.target_id != selection.child_concept_id:
                raise ValueError(
                    "alternate or suppressed edge targets another child"
                )
    if projection.projection_hash and (
        projection.projection_hash != compute_projection_hash(projection)
    ):
        raise ValueError("projection_hash does not match projection payload")
