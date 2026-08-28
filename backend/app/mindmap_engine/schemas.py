from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


NodeOrigin = Literal["explicit", "abstractive", "synthesized_root", "structural"]
ParentClassification = Literal[
    "direct_parent",
    "ancestor_only",
    "sibling",
    "cross_link",
    "unrelated",
    "uncertain",
]
CrossLinkRelation = Literal[
    "depends_on",
    "causes",
    "precedes",
    "contrasts_with",
    "used_for",
]


class EvidenceRef(BaseModel):
    unit_id: str | None = None
    chunk_id: str | None = None
    excerpt: str = ""
    page: int | None = None
    slide: int | None = None
    bbox: list[float] | None = None
    asset_id: str | None = None

    @field_validator("bbox")
    @classmethod
    def validate_bbox(cls, value: list[float] | None) -> list[float] | None:
        if value is None:
            return value
        if len(value) != 4:
            raise ValueError("bbox must contain [x, y, width, height]")
        return value


class NodeCandidateIn(BaseModel):
    temp_id: str
    name: str
    type: str = "concept"
    role: str | None = None
    definition: str = ""
    aliases: list[str] = Field(default_factory=list)
    origin: NodeOrigin = "explicit"
    branch_id: str | None = None
    confidence: float = Field(default=0.5, ge=0, le=1)
    optional: bool = False
    activation_score: float | None = Field(default=None, ge=0, le=1)
    activation_cost: float = Field(default=0, ge=0, le=1)
    is_root_candidate: bool = False
    evidence: list[EvidenceRef] = Field(default_factory=list)
    support_unit_ids: list[str] = Field(default_factory=list)
    media_asset_ids: list[str] = Field(default_factory=list)


class ParentCandidateIn(BaseModel):
    parent: str
    child: str
    score: float = Field(default=0.5, ge=0, le=1)
    classification: ParentClassification = "direct_parent"
    section_prior: float = Field(default=0, ge=0, le=1)
    semantic_score: float = Field(default=0, ge=0, le=1)
    reranker_score: float = Field(default=0, ge=0, le=1)
    verifier_score: float = Field(default=0, ge=0, le=1)
    evidence_support: float = Field(default=0, ge=0, le=1)
    granularity_fit: float = Field(default=0, ge=0, le=1)
    sibling_coherence: float = Field(default=0, ge=0, le=1)
    skipped_level_penalty: float = Field(default=0, ge=0, le=1)
    role_conflict_penalty: float = Field(default=0, ge=0, le=1)
    provisional: bool = False
    evidence: list[EvidenceRef] = Field(default_factory=list)


class CrossLinkCandidateIn(BaseModel):
    source: str
    target: str
    relation: CrossLinkRelation
    score: float = Field(default=0.5, ge=0, le=1)
    evidence: list[EvidenceRef] = Field(default_factory=list)


class NormalizeRequest(BaseModel):
    document_id: str
    document_title: str
    nodes: list[NodeCandidateIn]
    parent_candidates: list[ParentCandidateIn] = Field(default_factory=list)
    cross_links: list[CrossLinkCandidateIn] = Field(default_factory=list)
    max_parents_per_node: int = Field(default=8, ge=2, le=32)


class NormalizedNode(BaseModel):
    id: str
    temp_ids: list[str]
    name: str
    type: str
    role: str
    definition: str
    aliases: list[str]
    origin: NodeOrigin
    branch_id: str | None = None
    confidence: float
    optional: bool
    activation_score: float
    activation_cost: float
    is_root_candidate: bool
    evidence: list[EvidenceRef]
    explicit_evidence_unit_ids: list[str] = Field(default_factory=list)
    support_unit_ids: list[str]
    media_asset_ids: list[str]


class NormalizedParentCandidate(BaseModel):
    parent_id: str
    child_id: str
    score: float
    classification: ParentClassification
    provisional: bool = False
    evidence: list[EvidenceRef] = Field(default_factory=list)


class NormalizedCrossLinkCandidate(BaseModel):
    source_id: str
    target_id: str
    relation: CrossLinkRelation
    score: float
    evidence: list[EvidenceRef] = Field(default_factory=list)


class NormalizedGraph(BaseModel):
    document_id: str
    document_title: str
    nodes: list[NormalizedNode]
    parent_candidates: list[NormalizedParentCandidate]
    cross_links: list[NormalizedCrossLinkCandidate]
    warnings: list[str] = Field(default_factory=list)


class SolveRequest(BaseModel):
    graph: NormalizedGraph
    mode: Literal["standard", "precision"] = "standard"
    max_depth: int = Field(default=6, ge=2, le=12)
    time_limit_seconds: float = Field(default=5, gt=0, le=60)


class TreeEdge(BaseModel):
    id: str
    source: str
    target: str
    score: float
    provisional: bool = False
    evidence: list[EvidenceRef] = Field(default_factory=list)


class CrossLink(BaseModel):
    id: str
    source: str
    target: str
    relation: CrossLinkRelation
    score: float
    evidence: list[EvidenceRef] = Field(default_factory=list)


class ReviewItem(BaseModel):
    id: str
    type: Literal[
        "root_choice",
        "abstract_parent",
        "competing_parent",
        "cross_link",
        "uncovered_content",
    ]
    risk_score: float = Field(ge=0, le=1)
    subject_ids: list[str]
    reason: str
    alternatives: list[dict] = Field(default_factory=list)


class EngineQualityReport(BaseModel):
    node_count: int
    tree_edge_count: int
    cross_link_count: int
    root_count: int
    orphan_count: int
    conflict_count: int
    provisional_edge_count: int
    evidence_coverage: float
    topology_valid: bool
    warnings: list[str] = Field(default_factory=list)


class SolveResponse(BaseModel):
    document_id: str
    root_id: str
    nodes: list[NormalizedNode]
    tree_edges: list[TreeEdge]
    cross_links: list[CrossLink]
    review_items: list[ReviewItem]
    quality: EngineQualityReport
    solver_status: str
    warnings: list[str] = Field(default_factory=list)


class ValidateRequest(BaseModel):
    document_id: str
    nodes: list[NormalizedNode]
    tree_edges: list[TreeEdge]
    cross_links: list[CrossLink] = Field(default_factory=list)


class AssembleRequest(NormalizeRequest):
    mode: Literal["standard", "precision"] = "standard"
    max_depth: int = Field(default=6, ge=2, le=12)
    time_limit_seconds: float = Field(default=5, gt=0, le=60)


class VisualAsset(BaseModel):
    asset_id: str
    render_id: str
    filename: str
    url: str
    source_page: int | None = None
    source_slide: int | None = None
    bbox: list[float] | None = None
    width: int | None = None
    height: int | None = None
    visual_kind: str
    status: Literal["ready", "needs_render", "metadata_only"] = "ready"
    ocr_text: str = ""
    sha1: str = ""


class RenderedPage(BaseModel):
    asset_id: str
    render_id: str
    filename: str
    url: str
    page: int
    width: int = 0
    height: int = 0


class RenderResponse(BaseModel):
    render_id: str = ""
    filename: str = ""
    pages: list[RenderedPage] = Field(default_factory=list)
    native_visuals: list[VisualAsset] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class VisualRegion(BaseModel):
    page: int = Field(ge=1)
    bbox: list[float]
    visual_kind: str = "diagram"
    ocr_text: str = ""
    summary: str = ""
    knowledge_claims: list[str] = Field(default_factory=list)

    @field_validator("bbox")
    @classmethod
    def validate_region_bbox(cls, value: list[float]) -> list[float]:
        if len(value) != 4:
            raise ValueError("bbox must contain [x, y, width, height]")
        if any(item < 0 or item > 1 for item in value):
            raise ValueError("bbox values must be normalized to 0..1")
        return value


class CropRequest(BaseModel):
    render_id: str
    regions: list[VisualRegion]


class VisualUnit(BaseModel):
    asset: VisualAsset
    summary: str = ""
    knowledge_claims: list[str] = Field(default_factory=list)
