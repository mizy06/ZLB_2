from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from .base import FrozenContract
from .common import (
    ArtifactRef,
    ArtifactType,
    ConceptId,
    ProjectionId,
    RelationId,
    Sha256Digest,
    StringValue,
    require_artifact_type,
)


ViewNodeId = Annotated[
    str,
    StringConstraints(pattern=r"^view:[a-z0-9][a-z0-9._:-]{1,127}$"),
]
ViewEdgeId = Annotated[
    str,
    StringConstraints(pattern=r"^view_edge_[0-9a-f]{32}$"),
]


class ProjectionPurpose(StrEnum):
    OVERVIEW = "overview"
    SECTION_FOCUS = "section_focus"
    SEARCH = "search"
    REVIEW = "review"
    EXPORT = "export"
    DIAGNOSTIC = "diagnostic"


class ProjectionQualityStatus(StrEnum):
    UNASSESSED = "unassessed"
    BLOCKED_DOCUMENT = "blocked_document"
    BLOCKED_CLAIM = "blocked_claim"
    BLOCKED_SEMANTIC = "blocked_semantic"
    BLOCKED_EVIDENCE = "blocked_evidence"
    REVIEW_REQUIRED = "review_required"
    PASSED = "passed"


class OverlayMode(StrEnum):
    SOURCE_ONLY = "source_only"
    GROUNDED_ASSIST = "grounded_assist"
    ENRICHED_OVERLAY = "enriched_overlay"


class ProjectionAggregation(FrozenContract):
    view_node_id: ViewNodeId
    label: Annotated[
        str,
        StringConstraints(min_length=1, max_length=512),
    ]
    member_concept_ids: tuple[ConceptId, ...]

    @model_validator(mode="after")
    def require_members(self) -> "ProjectionAggregation":
        if not self.member_concept_ids:
            raise ValueError("view aggregation requires canonical members")
        return self


class ProjectionParentSelection(FrozenContract):
    child_concept_id: ConceptId
    selected_parent_edge_id: RelationId
    alternate_parent_edge_ids: tuple[RelationId, ...] = ()
    suppressed_canonical_edge_ids: tuple[RelationId, ...] = ()

    @model_validator(mode="after")
    def validate_edge_sets(self) -> "ProjectionParentSelection":
        selected = self.selected_parent_edge_id
        alternates = set(self.alternate_parent_edge_ids)
        suppressed = set(self.suppressed_canonical_edge_ids)
        if selected in alternates or selected in suppressed:
            raise ValueError(
                "selected projection parent cannot be alternate or suppressed"
            )
        if alternates & suppressed:
            raise ValueError(
                "alternate and suppressed parent edges must be disjoint"
            )
        return self


class ViewContainsEdge(FrozenContract):
    edge_id: ViewEdgeId
    source_view_id: ViewNodeId
    target_id: ConceptId | ViewNodeId


class ExpansionState(FrozenContract):
    node_id: ConceptId | ViewNodeId
    expanded: bool


class OverlayState(FrozenContract):
    mode: OverlayMode = OverlayMode.SOURCE_ONLY
    enabled: bool = False
    external_node_ids: tuple[
        Annotated[
            str,
            StringConstraints(
                pattern=r"^ext:[a-z0-9][A-Za-z0-9._:/-]{1,255}$"
            ),
        ],
        ...,
    ] = ()

    @model_validator(mode="after")
    def validate_overlay(self) -> "OverlayState":
        if self.mode is OverlayMode.SOURCE_ONLY and (
            self.enabled or self.external_node_ids
        ):
            raise ValueError("source_only projection cannot enable overlay")
        if not self.enabled and self.external_node_ids:
            raise ValueError(
                "disabled overlay cannot expose external node IDs"
            )
        return self


class LayoutProfile(FrozenContract):
    profile_id: Annotated[
        str,
        StringConstraints(min_length=1, max_length=128),
    ]
    medium: Literal["web", "mobile", "png", "pdf", "json"]
    direction: Literal["source_order_single_side", "outline", "paged"]
    node_budget: int = Field(ge=1)
    parameters: tuple[StringValue, ...] = ()


class ProjectionDiagnostic(FrozenContract):
    code: Annotated[
        str,
        StringConstraints(min_length=1, max_length=128),
    ]
    severity: Literal["info", "warning", "error", "blocking"]
    message: Annotated[
        str,
        StringConstraints(min_length=1, max_length=4096),
    ]
    affected_ids: tuple[
        Annotated[str, StringConstraints(min_length=1, max_length=128)],
        ...,
    ] = ()


class DiagnosticProjection(FrozenContract):
    schema_version: Literal["0.1.0"] = "0.1.0"
    projection_id: ProjectionId
    canonical_graph_ref: ArtifactRef
    canonical_hash: Sha256Digest
    purpose: ProjectionPurpose
    included_ids: tuple[ConceptId | ViewNodeId, ...]
    hidden_ids: tuple[ConceptId, ...] = ()
    aggregation_map: tuple[ProjectionAggregation, ...] = ()
    parent_selections: tuple[ProjectionParentSelection, ...] = ()
    projection_parent_edge_ids: tuple[RelationId, ...] = ()
    suppressed_canonical_edge_ids: tuple[RelationId, ...] = ()
    alternate_parent_edge_ids: tuple[RelationId, ...] = ()
    view_contains_edges: tuple[ViewContainsEdge, ...] = ()
    expansion_state: tuple[ExpansionState, ...] = ()
    filters: tuple[StringValue, ...] = ()
    overlay_state: OverlayState = OverlayState()
    layout_profile: LayoutProfile
    quality_status: ProjectionQualityStatus
    diagnostics: tuple[ProjectionDiagnostic, ...] = ()
    projection_hash: Sha256Digest | None = None
    supersedes: ArtifactRef | None = None

    @model_validator(mode="after")
    def validate_projection_shape(self) -> "DiagnosticProjection":
        require_artifact_type(
            self.supersedes,
            ArtifactType.DIAGNOSTIC_PROJECTION,
            field_name="supersedes",
        )
        if (
            self.canonical_graph_ref.artifact_type.value
            != "canonical_explicit_graph"
        ):
            raise ValueError(
                "canonical_graph_ref must reference CanonicalExplicitGraph"
            )
        if self.supersedes and self.supersedes.owner_id != (
            self.canonical_graph_ref.owner_id
        ):
            raise ValueError("projection supersedes must remain owner-scoped")
        included = set(self.included_ids)
        hidden = set(self.hidden_ids)
        if included & hidden:
            raise ValueError("included and hidden IDs must be disjoint")
        view_ids = {
            aggregation.view_node_id for aggregation in self.aggregation_map
        }
        if len(view_ids) != len(self.aggregation_map):
            raise ValueError("aggregation view node IDs must be unique")
        included_view_ids = {
            item for item in self.included_ids if item.startswith("view:")
        }
        if included_view_ids - view_ids:
            raise ValueError(
                "included view nodes require an aggregation_map entry"
            )
        selected = tuple(
            item.selected_parent_edge_id for item in self.parent_selections
        )
        selected_children = [
            item.child_concept_id for item in self.parent_selections
        ]
        if len(selected_children) != len(set(selected_children)):
            raise ValueError(
                "projection may select only one display parent per child"
            )
        alternates = tuple(
            edge_id
            for item in self.parent_selections
            for edge_id in item.alternate_parent_edge_ids
        )
        suppressed = tuple(
            edge_id
            for item in self.parent_selections
            for edge_id in item.suppressed_canonical_edge_ids
        )
        if tuple(self.projection_parent_edge_ids) != selected:
            raise ValueError(
                "projection_parent_edge_ids must match parent selections"
            )
        if tuple(self.alternate_parent_edge_ids) != alternates:
            raise ValueError(
                "alternate_parent_edge_ids must match parent selections"
            )
        if tuple(self.suppressed_canonical_edge_ids) != suppressed:
            raise ValueError(
                "suppressed edge IDs must match parent selections"
            )
        view_edge_ids = [edge.edge_id for edge in self.view_contains_edges]
        if len(view_edge_ids) != len(set(view_edge_ids)):
            raise ValueError("view_contains edge IDs must be unique")
        for edge in self.view_contains_edges:
            if edge.source_view_id not in included_view_ids:
                raise ValueError(
                    "view_contains source must be an included aggregation"
                )
            if edge.target_id not in included:
                raise ValueError(
                    "view_contains target must be included in projection"
                )
        for state in self.expansion_state:
            if state.node_id not in included:
                raise ValueError(
                    "expansion state can reference only included nodes"
                )
        blocking_states = {
            ProjectionQualityStatus.BLOCKED_DOCUMENT,
            ProjectionQualityStatus.BLOCKED_CLAIM,
            ProjectionQualityStatus.BLOCKED_SEMANTIC,
            ProjectionQualityStatus.BLOCKED_EVIDENCE,
        }
        if self.quality_status in blocking_states and not any(
            item.severity == "blocking" for item in self.diagnostics
        ):
            raise ValueError(
                "blocked projection requires a blocking diagnostic"
            )
        return self
