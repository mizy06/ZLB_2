from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator, model_validator

from .base import FrozenContract
from .common import (
    ArtifactRef,
    OwnerId,
    SemVer,
    Sha256Digest,
)
from .projection import OverlayMode


MediaBundleId = Annotated[
    str,
    StringConstraints(pattern=r"^media_bundle_[0-9a-f]{32}$"),
]
RenderBundleId = Annotated[
    str,
    StringConstraints(pattern=r"^render_bundle_[0-9a-f]{32}$"),
]
PresentationNodeId = Annotated[
    str,
    StringConstraints(min_length=3, max_length=256),
]


class PresentationMedium(StrEnum):
    WEB = "web"
    MOBILE = "mobile"
    PNG = "png"
    PDF = "pdf"
    JSON = "json"


class RenderedFileKind(StrEnum):
    WEB_HTML = "web_html"
    PNG_TILE = "png_tile"
    PDF = "pdf"
    JSON = "json"


class MediaNodeIdentity(FrozenContract):
    node_id: PresentationNodeId
    label: Annotated[
        str,
        StringConstraints(min_length=1, max_length=512),
    ]
    status: Annotated[
        str,
        StringConstraints(min_length=1, max_length=64),
    ]
    source_order: int = Field(ge=0)


class MediaParentIdentity(FrozenContract):
    child_id: PresentationNodeId
    parent_id: PresentationNodeId
    selected_edge_id: Annotated[
        str,
        StringConstraints(min_length=1, max_length=128),
    ]
    alternate_edge_ids: tuple[str, ...] = ()
    suppressed_edge_ids: tuple[str, ...] = ()


class MediaViewEdgeIdentity(FrozenContract):
    edge_id: Annotated[
        str,
        StringConstraints(min_length=1, max_length=128),
    ]
    source_id: PresentationNodeId
    target_id: PresentationNodeId


class MediaCrossLinkIdentity(FrozenContract):
    relation_id: Annotated[
        str,
        StringConstraints(min_length=1, max_length=128),
    ]
    source_id: PresentationNodeId
    target_id: PresentationNodeId
    semantic_relation: Annotated[
        str,
        StringConstraints(min_length=1, max_length=64),
    ]


class AccessibilityProfile(FrozenContract):
    normal_node_font_size: float = Field(ge=0)
    chapter_font_size: float = Field(ge=0)
    body_font_size: float = Field(ge=0)
    line_height: float = Field(ge=1)
    text_contrast_ratio: float = Field(ge=1)
    non_text_contrast_ratio: float = Field(ge=1)
    minimum_target_size: int = Field(ge=0)
    text_zoom_percent: int = Field(ge=100)
    reflow_width_css_px: int | None = Field(default=None, ge=1)
    dom_outline_present: bool
    keyboard_navigation: bool
    long_description_present: bool


class MediaProjectionContract(FrozenContract):
    medium: PresentationMedium
    semantic_fingerprint: Sha256Digest
    nodes: tuple[MediaNodeIdentity, ...]
    parents: tuple[MediaParentIdentity, ...]
    view_edges: tuple[MediaViewEdgeIdentity, ...] = ()
    cross_links: tuple[MediaCrossLinkIdentity, ...] = ()
    hidden_ids: tuple[PresentationNodeId, ...] = ()
    overlay_mode: OverlayMode
    overlay_enabled: bool
    render_mode: Literal[
        "canvas_dom_sync",
        "outline_detail",
        "paged_tiles",
        "bookmarked_pages",
        "structured_json",
    ]
    geometry_profile: Annotated[
        str,
        StringConstraints(min_length=1, max_length=128),
    ]
    graphical_node_limit: int = Field(ge=0)
    paginated: bool
    page_or_tile_count: int = Field(ge=1)
    accessibility: AccessibilityProfile | None = None
    long_description: Annotated[
        str,
        StringConstraints(min_length=1, max_length=8192),
    ] | None = None

    @model_validator(mode="after")
    def validate_medium_contract(self) -> "MediaProjectionContract":
        node_ids = [item.node_id for item in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("presentation node IDs must be unique")
        if [item.source_order for item in self.nodes] != list(
            range(len(self.nodes))
        ):
            raise ValueError(
                "presentation source_order must be contiguous"
            )
        parent_children = [item.child_id for item in self.parents]
        if len(parent_children) != len(set(parent_children)):
            raise ValueError(
                "presentation may expose only one parent per child"
            )
        known = set(node_ids)
        if any(
            item.child_id not in known or item.parent_id not in known
            for item in self.parents
        ):
            raise ValueError(
                "presentation parent identities require visible nodes"
            )
        if any(
            item.source_id not in known or item.target_id not in known
            for item in self.view_edges
        ):
            raise ValueError(
                "presentation view edges require visible nodes"
            )
        cross_link_ids = [
            item.relation_id for item in self.cross_links
        ]
        if len(cross_link_ids) != len(set(cross_link_ids)):
            raise ValueError(
                "presentation cross-link IDs must be unique"
            )
        if any(
            item.source_id not in known or item.target_id not in known
            for item in self.cross_links
        ):
            raise ValueError(
                "presentation cross-links require visible nodes"
            )
        if self.medium is PresentationMedium.JSON:
            if self.render_mode != "structured_json":
                raise ValueError("JSON medium requires structured_json mode")
            if self.accessibility is not None or self.long_description:
                raise ValueError(
                    "JSON medium cannot claim visual accessibility"
                )
            if self.graphical_node_limit != 0:
                raise ValueError(
                    "JSON medium cannot declare a graphical node limit"
                )
            return self
        if self.accessibility is None:
            raise ValueError(
                "visual presentation medium requires accessibility profile"
            )
        if self.medium is PresentationMedium.WEB:
            self._require_accessibility(
                normal=14,
                chapter=18,
                body=16,
                target=24,
                reflow=320,
            )
            if self.render_mode != "canvas_dom_sync":
                raise ValueError("web medium requires canvas_dom_sync")
            if not (
                self.accessibility.dom_outline_present
                and self.accessibility.keyboard_navigation
                and self.accessibility.long_description_present
                and self.long_description
            ):
                raise ValueError(
                    "web medium requires synchronized accessible DOM"
                )
        elif self.medium is PresentationMedium.MOBILE:
            self._require_accessibility(
                normal=14,
                chapter=18,
                body=16,
                target=44,
                reflow=320,
            )
            if self.render_mode != "outline_detail":
                raise ValueError("mobile medium requires outline_detail")
            if self.graphical_node_limit > 18:
                raise ValueError(
                    "mobile graphical mode cannot exceed 18 nodes"
                )
            if not (
                self.accessibility.dom_outline_present
                and self.accessibility.keyboard_navigation
                and self.long_description
            ):
                raise ValueError(
                    "mobile medium requires accessible outline and detail"
                )
        elif self.medium is PresentationMedium.PNG:
            self._require_accessibility(
                normal=16,
                chapter=18,
                body=16,
                target=0,
                reflow=None,
            )
            if self.render_mode != "paged_tiles":
                raise ValueError("PNG medium requires paged_tiles")
            if len(self.nodes) > 32 and not self.paginated:
                raise ValueError(
                    "large PNG export must use paginated tiles"
                )
        elif self.medium is PresentationMedium.PDF:
            self._require_accessibility(
                normal=10.5,
                chapter=12,
                body=10.5,
                target=0,
                reflow=None,
            )
            if self.render_mode != "bookmarked_pages":
                raise ValueError("PDF medium requires bookmarked_pages")
            if not self.paginated:
                raise ValueError("PDF export must be paginated")
        return self

    def _require_accessibility(
        self,
        *,
        normal: float,
        chapter: float,
        body: float,
        target: int,
        reflow: int | None,
    ) -> None:
        assert self.accessibility is not None
        profile = self.accessibility
        if profile.normal_node_font_size < normal:
            raise ValueError("normal node font size is below medium gate")
        if profile.chapter_font_size < chapter:
            raise ValueError("chapter font size is below medium gate")
        if profile.body_font_size < body:
            raise ValueError("body font size is below medium gate")
        if profile.line_height < 1.4:
            raise ValueError("line height must be at least 1.4")
        if profile.text_contrast_ratio < 4.5:
            raise ValueError("text contrast ratio must be at least 4.5")
        if profile.non_text_contrast_ratio < 3:
            raise ValueError(
                "non-text contrast ratio must be at least 3"
            )
        if profile.minimum_target_size < target:
            raise ValueError("target size is below medium gate")
        if profile.text_zoom_percent < 200:
            raise ValueError("visual medium must support 200% text zoom")
        if reflow is not None and (
            profile.reflow_width_css_px is None
            or profile.reflow_width_css_px > reflow
        ):
            raise ValueError(
                "interactive medium must reflow at 320 CSS px"
            )


class ProjectionMediaBundle(FrozenContract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    media_bundle_id: MediaBundleId
    canonical_graph_ref: ArtifactRef
    projection_ref: ArtifactRef
    semantic_fingerprint: Sha256Digest
    media: tuple[MediaProjectionContract, ...]
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("media bundle timestamp requires timezone")
        return value

    @model_validator(mode="after")
    def validate_consistency(self) -> "ProjectionMediaBundle":
        if (
            self.canonical_graph_ref.owner_id
            != self.projection_ref.owner_id
        ):
            raise ValueError(
                "media bundle artifacts must remain owner-scoped"
            )
        if self.projection_ref.artifact_type.value != (
            "diagnostic_projection"
        ):
            raise ValueError(
                "media bundle projection_ref must reference projection"
            )
        observed = [item.medium for item in self.media]
        expected = list(PresentationMedium)
        if observed != expected:
            raise ValueError(
                "media bundle must contain web, mobile, png, pdf, json "
                "in deterministic order"
            )
        first = self.media[0]
        for item in self.media:
            if item.semantic_fingerprint != self.semantic_fingerprint:
                raise ValueError(
                    "media semantic fingerprint does not match bundle"
                )
            if (
                item.nodes != first.nodes
                or item.parents != first.parents
                or item.view_edges != first.view_edges
                or item.cross_links != first.cross_links
                or item.hidden_ids != first.hidden_ids
                or item.overlay_mode is not first.overlay_mode
                or item.overlay_enabled != first.overlay_enabled
            ):
                raise ValueError(
                    "all media must preserve identical projection semantics"
                )
        return self


class RenderedMediaFile(FrozenContract):
    kind: RenderedFileKind
    relative_path: Annotated[
        str,
        StringConstraints(min_length=1, max_length=256),
    ]
    media_type: Literal[
        "text/html",
        "image/png",
        "application/pdf",
        "application/json",
    ]
    payload_digest: Sha256Digest
    byte_size: int = Field(gt=0)
    semantic_fingerprint: Sha256Digest
    page_or_tile_index: int | None = Field(default=None, ge=1)
    logical_page_count: int = Field(default=1, ge=1)
    pixel_width: int | None = Field(default=None, ge=1)
    pixel_height: int | None = Field(default=None, ge=1)
    node_ids: tuple[PresentationNodeId, ...] = ()

    @model_validator(mode="after")
    def validate_file(self) -> "RenderedMediaFile":
        path = PurePosixPath(self.relative_path)
        if (
            path.is_absolute()
            or ".." in path.parts
            or "." in path.parts
            or str(path) != self.relative_path
        ):
            raise ValueError(
                "rendered file path must be a normalized relative path"
            )
        expected_media = {
            RenderedFileKind.WEB_HTML: "text/html",
            RenderedFileKind.PNG_TILE: "image/png",
            RenderedFileKind.PDF: "application/pdf",
            RenderedFileKind.JSON: "application/json",
        }[self.kind]
        if self.media_type != expected_media:
            raise ValueError(
                "rendered file kind and media_type must agree"
            )
        if self.kind is RenderedFileKind.WEB_HTML:
            if self.relative_path != "web/index.html":
                raise ValueError("web renderer must write web/index.html")
        elif self.kind is RenderedFileKind.PNG_TILE:
            if (
                self.page_or_tile_index is None
                or self.relative_path
                != f"png/tile-{self.page_or_tile_index:04d}.png"
                or self.pixel_width is None
                or self.pixel_height is None
            ):
                raise ValueError(
                    "PNG tile requires an indexed path and dimensions"
                )
        elif self.kind is RenderedFileKind.PDF:
            if self.relative_path != "pdf/mind-map.pdf":
                raise ValueError("PDF renderer must write pdf/mind-map.pdf")
        elif self.relative_path != "json/mind-map.json":
            raise ValueError("JSON renderer must write json/mind-map.json")
        if self.kind is not RenderedFileKind.PNG_TILE and (
            self.page_or_tile_index is not None
            or self.pixel_width is not None
            or self.pixel_height is not None
        ):
            raise ValueError(
                "only PNG tiles may declare tile indexes or dimensions"
            )
        if (
            self.kind is not RenderedFileKind.PDF
            and self.logical_page_count != 1
        ):
            raise ValueError(
                "only PDF may contain multiple logical pages"
            )
        if len(self.node_ids) != len(set(self.node_ids)):
            raise ValueError("rendered file node IDs must be unique")
        return self


class RenderedPresentationBundle(FrozenContract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    render_bundle_id: RenderBundleId
    owner_id: OwnerId
    media_bundle_id: MediaBundleId
    media_bundle_digest: Sha256Digest
    canonical_graph_ref: ArtifactRef
    projection_ref: ArtifactRef
    semantic_fingerprint: Sha256Digest
    semantic_node_ids: tuple[PresentationNodeId, ...]
    renderer_version: SemVer
    font_family: Annotated[
        str,
        StringConstraints(min_length=1, max_length=256),
    ]
    font_digest: Sha256Digest
    files: tuple[RenderedMediaFile, ...] = Field(min_length=4)
    created_at: datetime
    publication_enabled: Literal[False] = False

    @field_validator("created_at")
    @classmethod
    def require_render_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("render bundle timestamp requires timezone")
        return value

    @model_validator(mode="after")
    def validate_render_bundle(self) -> "RenderedPresentationBundle":
        if (
            self.canonical_graph_ref.owner_id != self.owner_id
            or self.projection_ref.owner_id != self.owner_id
        ):
            raise ValueError(
                "render bundle artifacts must remain owner-scoped"
            )
        if self.projection_ref.artifact_type.value != (
            "diagnostic_projection"
        ):
            raise ValueError(
                "render bundle projection_ref must reference projection"
            )
        if len(self.semantic_node_ids) != len(
            set(self.semantic_node_ids)
        ):
            raise ValueError("semantic node IDs must be unique")
        paths = [item.relative_path for item in self.files]
        if len(paths) != len(set(paths)):
            raise ValueError("rendered file paths must be unique")
        if any(
            item.semantic_fingerprint != self.semantic_fingerprint
            for item in self.files
        ):
            raise ValueError(
                "rendered files must preserve one semantic fingerprint"
            )
        kinds = [item.kind for item in self.files]
        kind_order = {
            RenderedFileKind.WEB_HTML: 0,
            RenderedFileKind.PNG_TILE: 1,
            RenderedFileKind.PDF: 2,
            RenderedFileKind.JSON: 3,
        }
        if self.files != tuple(
            sorted(
                self.files,
                key=lambda item: (
                    kind_order[item.kind],
                    item.page_or_tile_index or 0,
                ),
            )
        ):
            raise ValueError(
                "rendered files must use deterministic medium order"
            )
        for singleton in (
            RenderedFileKind.WEB_HTML,
            RenderedFileKind.PDF,
            RenderedFileKind.JSON,
        ):
            if kinds.count(singleton) != 1:
                raise ValueError(
                    f"render bundle requires one {singleton.value} file"
                )
        png_files = [
            item
            for item in self.files
            if item.kind is RenderedFileKind.PNG_TILE
        ]
        if not png_files:
            raise ValueError("render bundle requires at least one PNG tile")
        if [item.page_or_tile_index for item in png_files] != list(
            range(1, len(png_files) + 1)
        ):
            raise ValueError(
                "PNG tile indexes must be contiguous and deterministic"
            )
        full_set = set(self.semantic_node_ids)
        for item in self.files:
            node_set = set(item.node_ids)
            if not node_set <= full_set:
                raise ValueError(
                    "rendered file references an unknown semantic node"
                )
            if item.kind in {
                RenderedFileKind.WEB_HTML,
                RenderedFileKind.PDF,
                RenderedFileKind.JSON,
            } and item.node_ids != self.semantic_node_ids:
                raise ValueError(
                    "HTML, PDF, and JSON must retain all semantic nodes"
                )
        png_union = {
            node_id for item in png_files for node_id in item.node_ids
        }
        if png_union != full_set:
            raise ValueError(
                "PNG tiles must collectively retain all semantic nodes"
            )
        return self
