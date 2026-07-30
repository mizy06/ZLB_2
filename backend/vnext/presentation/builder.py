from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from backend.vnext.artifacts.canonical import (
    canonical_json_bytes,
    payload_digest,
)
from backend.vnext.contracts.common import ArtifactRef
from backend.vnext.contracts.graph import (
    CanonicalExplicitGraph,
    CanonicalStatus,
    HierarchyDirectness,
)
from backend.vnext.contracts.presentation import (
    AccessibilityProfile,
    MediaCrossLinkIdentity,
    MediaNodeIdentity,
    MediaParentIdentity,
    MediaProjectionContract,
    MediaViewEdgeIdentity,
    PresentationMedium,
    ProjectionMediaBundle,
)
from backend.vnext.contracts.projection import (
    DiagnosticProjection,
    ProjectionQualityStatus,
)
from backend.vnext.projection.validation import (
    validate_projection_against_graph,
)

from .pagination import plan_pdf_pages, plan_png_tiles


class PresentationBlocked(ValueError):
    pass


def build_projection_media_bundle(
    graph: CanonicalExplicitGraph,
    projection: DiagnosticProjection,
    *,
    canonical_graph_ref: ArtifactRef,
    projection_ref: ArtifactRef,
    created_at: datetime | None = None,
) -> ProjectionMediaBundle:
    validate_projection_against_graph(projection, graph)
    if projection.quality_status is not ProjectionQualityStatus.PASSED:
        raise PresentationBlocked(
            "publishable media requires a quality-passed projection"
        )
    if canonical_graph_ref != projection.canonical_graph_ref:
        raise ValueError(
            "media canonical graph ref must match projection graph ref"
        )
    if projection_ref.artifact_type.value != "diagnostic_projection":
        raise ValueError("projection_ref must reference a projection")
    if projection_ref.payload_digest != payload_digest(projection):
        raise ValueError(
            "projection_ref digest does not match projection payload"
        )
    timestamp = created_at or datetime.now(UTC)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("created_at must include a timezone")

    concept_by_id = {
        concept.concept_id: concept for concept in graph.concepts
    }
    aggregation_by_id = {
        item.view_node_id: item for item in projection.aggregation_map
    }
    nodes: list[MediaNodeIdentity] = []
    for source_order, node_id in enumerate(projection.included_ids):
        concept = concept_by_id.get(node_id)
        aggregation = aggregation_by_id.get(node_id)
        if concept is not None:
            label = concept.canonical_name
            status = concept.status.value
        elif aggregation is not None:
            label = aggregation.label
            status = "view_aggregation"
        else:
            raise ValueError(
                f"projection includes unknown presentation node {node_id}"
            )
        nodes.append(
            MediaNodeIdentity(
                node_id=node_id,
                label=label,
                status=status,
                source_order=source_order,
            )
        )

    relation_by_id = {
        relation.relation_id: relation for relation in graph.relations
    }
    parents: list[MediaParentIdentity] = []
    for selection in projection.parent_selections:
        relation = relation_by_id[selection.selected_parent_edge_id]
        parents.append(
            MediaParentIdentity(
                child_id=selection.child_concept_id,
                parent_id=relation.source_id,
                selected_edge_id=selection.selected_parent_edge_id,
                alternate_edge_ids=selection.alternate_parent_edge_ids,
                suppressed_edge_ids=(
                    selection.suppressed_canonical_edge_ids
                ),
            )
        )
    view_edges = tuple(
        MediaViewEdgeIdentity(
            edge_id=edge.edge_id,
            source_id=edge.source_view_id,
            target_id=edge.target_id,
        )
        for edge in projection.view_contains_edges
    )
    included = set(projection.included_ids)
    cross_links = tuple(
        MediaCrossLinkIdentity(
            relation_id=relation.relation_id,
            source_id=relation.source_id,
            target_id=relation.target_id,
            semantic_relation=relation.semantic_relation.value,
        )
        for relation in graph.relations
        if (
            relation.status is CanonicalStatus.ACCEPTED
            and relation.hierarchy_directness
            is HierarchyDirectness.NON_HIERARCHICAL
            and relation.source_id in included
            and relation.target_id in included
        )
    )
    semantic_payload = {
        "hidden_ids": projection.hidden_ids,
        "nodes": [item.model_dump(mode="json") for item in nodes],
        "overlay_enabled": projection.overlay_state.enabled,
        "overlay_mode": projection.overlay_state.mode.value,
        "parents": [item.model_dump(mode="json") for item in parents],
        "cross_links": [
            item.model_dump(mode="json") for item in cross_links
        ],
        "view_edges": [
            item.model_dump(mode="json") for item in view_edges
        ],
    }
    semantic_fingerprint = payload_digest(semantic_payload)
    long_description = _long_description(nodes, parents)
    png_tiles = plan_png_tiles(
        tuple(nodes),
        tuple(parents),
        view_edges,
    )
    pdf_pages = plan_pdf_pages(
        tuple(nodes),
        tuple(parents),
        view_edges,
        graph,
    )
    shared = {
        "semantic_fingerprint": semantic_fingerprint,
        "nodes": tuple(nodes),
        "parents": tuple(parents),
        "view_edges": view_edges,
        "cross_links": cross_links,
        "hidden_ids": projection.hidden_ids,
        "overlay_mode": projection.overlay_state.mode,
        "overlay_enabled": projection.overlay_state.enabled,
    }
    media = (
        MediaProjectionContract(
            medium=PresentationMedium.WEB,
            **shared,
            render_mode="canvas_dom_sync",
            geometry_profile="web-source-order-single-side-v1",
            graphical_node_limit=48,
            paginated=False,
            page_or_tile_count=1,
            accessibility=_interactive_accessibility(target=24),
            long_description=long_description,
        ),
        MediaProjectionContract(
            medium=PresentationMedium.MOBILE,
            **shared,
            render_mode="outline_detail",
            geometry_profile="mobile-outline-detail-v1",
            graphical_node_limit=18,
            paginated=False,
            page_or_tile_count=1,
            accessibility=_interactive_accessibility(target=44),
            long_description=long_description,
        ),
        MediaProjectionContract(
            medium=PresentationMedium.PNG,
            **shared,
            render_mode="paged_tiles",
            geometry_profile="png-overview-or-tiles-v1",
            graphical_node_limit=32,
            paginated=len(png_tiles) > 1,
            page_or_tile_count=len(png_tiles),
            accessibility=_static_accessibility(
                normal=16,
                chapter=20,
                body=16,
            ),
            long_description=long_description,
        ),
        MediaProjectionContract(
            medium=PresentationMedium.PDF,
            **shared,
            render_mode="bookmarked_pages",
            geometry_profile="pdf-overview-section-pages-v1",
            graphical_node_limit=48,
            paginated=True,
            page_or_tile_count=len(pdf_pages),
            accessibility=_static_accessibility(
                normal=10.5,
                chapter=14,
                body=10.5,
            ),
            long_description=long_description,
        ),
        MediaProjectionContract(
            medium=PresentationMedium.JSON,
            **shared,
            render_mode="structured_json",
            geometry_profile="json-semantic-contract-v1",
            graphical_node_limit=0,
            paginated=False,
            page_or_tile_count=1,
            accessibility=None,
            long_description=None,
        ),
    )
    bundle_digest = hashlib.sha256(
        b"zlb-vnext-media-bundle-v1\0"
        + canonical_json_bytes(
            {
                "canonical_digest": canonical_graph_ref.payload_digest,
                "projection_digest": projection_ref.payload_digest,
                "semantic_fingerprint": semantic_fingerprint,
            }
        )
    ).hexdigest()
    return ProjectionMediaBundle(
        media_bundle_id="media_bundle_" + bundle_digest[:32],
        canonical_graph_ref=canonical_graph_ref,
        projection_ref=projection_ref,
        semantic_fingerprint=semantic_fingerprint,
        media=media,
        created_at=timestamp,
    )


def _interactive_accessibility(*, target: int) -> AccessibilityProfile:
    return AccessibilityProfile(
        normal_node_font_size=14,
        chapter_font_size=18,
        body_font_size=16,
        line_height=1.4,
        text_contrast_ratio=4.5,
        non_text_contrast_ratio=3,
        minimum_target_size=target,
        text_zoom_percent=200,
        reflow_width_css_px=320,
        dom_outline_present=True,
        keyboard_navigation=True,
        long_description_present=True,
    )


def _static_accessibility(
    *,
    normal: float,
    chapter: float,
    body: float,
) -> AccessibilityProfile:
    return AccessibilityProfile(
        normal_node_font_size=normal,
        chapter_font_size=chapter,
        body_font_size=body,
        line_height=1.4,
        text_contrast_ratio=4.5,
        non_text_contrast_ratio=3,
        minimum_target_size=0,
        text_zoom_percent=200,
        reflow_width_css_px=None,
        dom_outline_present=False,
        keyboard_navigation=False,
        long_description_present=True,
    )


def _long_description(
    nodes: list[MediaNodeIdentity],
    parents: list[MediaParentIdentity],
) -> str:
    child_ids = {item.child_id for item in parents}
    roots = [item for item in nodes if item.node_id not in child_ids]
    root_label = roots[0].label if len(roots) == 1 else "Unresolved root"
    return (
        f"{root_label}. {len(nodes)} visible nodes and "
        f"{len(parents)} selected hierarchy edges. "
        "Node order follows the frozen projection source order."
    )
