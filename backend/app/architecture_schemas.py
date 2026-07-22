from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from .mindmap_engine.schemas import (
    CrossLink,
    EngineQualityReport,
    EvidenceRef,
    NormalizedNode,
    ReviewItem,
    TreeEdge,
    VisualAsset,
)
from .schemas import Chunk, ParsedDocument


RunMode = Literal["standard", "precision"]
ContentUnitStatus = Literal[
    "uncovered",
    "covered",
    "merged",
    "deferred",
    "rejected",
]
CandidateStatus = Literal[
    "candidate",
    "accepted",
    "deferred",
    "rejected",
    "needs_review",
]
DecisionActor = Literal["code", "model", "human"]


class ContentUnit(BaseModel):
    id: str
    document_id: str
    kind: Literal["text", "visual"]
    branch_hint: str | None = None
    importance: float = Field(default=0.5, ge=0, le=1)
    status: ContentUnitStatus = "uncovered"
    text: str = ""
    heading_path: list[str] = Field(default_factory=list)
    unit_role: Literal[
        "definition",
        "principle",
        "step",
        "formula",
        "example",
        "warning",
        "other",
    ] = "other"
    evidence_excerpt: str = ""
    page: int | None = None
    slide: int | None = None
    bbox: list[float] | None = None
    asset_id: str | None = None
    visual_kind: str | None = None
    visual_action: Literal[
        "standalone_node",
        "attach_as_media",
        "decompose",
        "ignore_decoration",
        "unclassified",
    ] = "unclassified"
    ocr_text: str = ""
    summary: str = ""
    knowledge_claims: list[str] = Field(default_factory=list)
    nearby_text_ids: list[str] = Field(default_factory=list)
    perceptual_hash: str = ""
    knowledge_score: float = Field(default=0.5, ge=0, le=1)
    decorative_score: float = Field(default=0, ge=0, le=1)
    parent_asset_id: str | None = None


class BranchPlan(BaseModel):
    id: str
    label: str
    description: str = ""
    unit_ids: list[str]
    parent_branch_id: str | None = None
    depth: int = Field(default=1, ge=1, le=8)
    cohesion: float = Field(default=0.5, ge=0, le=1)
    coverage_budget: int = Field(default=24, ge=1, le=200)
    leaf: bool = True


class ModelVote(BaseModel):
    actor: str
    model: str | None = None
    classification: str
    score: float = Field(default=0.5, ge=0, le=1)
    reason: str = ""


class DecisionRecord(BaseModel):
    id: str
    run_id: str
    subject_type: Literal[
        "node",
        "tree_edge",
        "cross_link",
        "visual_asset",
        "root",
        "run",
    ]
    subject_id: str
    actor: DecisionActor
    actor_version: str
    prompt_version: str | None = None
    decision: str
    reason_codes: list[str] = Field(default_factory=list)
    evidence_unit_ids: list[str] = Field(default_factory=list)
    timestamp: str


class ReviewItemView(ReviewItem):
    evidence_unit_ids: list[str] = Field(default_factory=list)
    model_votes: list[ModelVote] = Field(default_factory=list)
    local_subtree_preview: dict = Field(default_factory=dict)
    status: Literal["pending", "resolved"] = "pending"
    resolution: dict | None = None


class MindMapNode(NormalizedNode):
    depth: int = Field(default=0, ge=0)
    parent_id: str | None = None
    status: CandidateStatus = "accepted"
    risk_score: float = Field(default=0, ge=0, le=1)


class MindMapTreeEdge(TreeEdge):
    classification: str = "direct_parent"
    verifier_votes: list[ModelVote] = Field(default_factory=list)


class MindMapCrossLink(CrossLink):
    verifier_votes: list[ModelVote] = Field(default_factory=list)


class CoverageSummary(BaseModel):
    total_units: int = 0
    covered_units: int = 0
    weighted_coverage: float = Field(default=0, ge=0, le=1)
    uncovered_unit_ids: list[str] = Field(default_factory=list)
    branch_coverage: dict[str, float] = Field(default_factory=dict)


class MindMapQualityReport(EngineQualityReport):
    weighted_content_coverage: float = Field(default=0, ge=0, le=1)
    direct_parent_confidence: float = Field(default=0, ge=0, le=1)
    abstraction_support_rate: float = Field(default=0, ge=0, le=1)
    review_item_count: int = 0
    quality_gate_passed: bool = False
    coverage: CoverageSummary = Field(default_factory=CoverageSummary)


class ModelSelection(BaseModel):
    generator_provider: str
    generator_model: str | None = None
    verifier_provider: str
    verifier_model: str | None = None
    vision_provider: str | None = None
    vision_model: str | None = None
    arbiter_provider: str | None = None
    arbiter_model: str | None = None


class MindMapResult(BaseModel):
    task_id: str
    run_id: str
    graph_version: int
    document: ParsedDocument
    chunks: list[Chunk]
    content_units: list[ContentUnit]
    root_id: str
    nodes: list[MindMapNode]
    tree_edges: list[MindMapTreeEdge]
    cross_links: list[MindMapCrossLink]
    assets: list[VisualAsset] = Field(default_factory=list)
    quality_report: MindMapQualityReport
    review_items: list[ReviewItemView] = Field(default_factory=list)
    decision_records: list[DecisionRecord] = Field(default_factory=list)
    mode: RunMode = "standard"
    extraction_mode: Literal[
        "kimi",
        "heuristic",
        "mixed",
    ] = "heuristic"
    model_selection: ModelSelection
    degraded_components: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    solver_status: str = ""


class JobView(BaseModel):
    id: str
    status: Literal["queued", "running", "completed", "failed"]
    stage: str
    progress: int
    message: str = ""
    mode: RunMode = "standard"
    result: MindMapResult | None = None
    error: str | None = None


class HistoryItem(BaseModel):
    task_id: str
    title: str
    filename: str
    file_type: str
    mode: RunMode
    extraction_mode: Literal["kimi", "heuristic", "mixed"]
    graph_version: int
    node_count: int
    review_count: int
    quality_gate_passed: bool
    created_at: str
    updated_at: str


class ReviewResolutionRequest(BaseModel):
    action: Literal[
        "keep",
        "delete",
        "change_parent",
        "rename",
        "accept_root",
    ]
    parent_id: str | None = None
    label: str | None = None
    reason: str = ""

    @model_validator(mode="after")
    def validate_action_fields(self):
        if self.action == "change_parent" and not self.parent_id:
            raise ValueError("change_parent requires parent_id")
        if self.action == "rename" and not (self.label or "").strip():
            raise ValueError("rename requires label")
        return self


class ReviewResolutionResponse(BaseModel):
    task_id: str
    review_id: str
    graph_version: int
    result: MindMapResult
