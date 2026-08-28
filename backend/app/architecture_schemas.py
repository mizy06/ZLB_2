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
EditorialReviewerRole = Literal[
    "content_omission",
    "pruning",
    "multilevel_structure",
]


class MindMapLoopRound(BaseModel):
    editor_model: str = Field(
        min_length=1,
        max_length=160,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/+-]*$",
    )
    content_omission_model: str | None = Field(
        default=None,
        min_length=1,
        max_length=160,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/+-]*$",
    )
    pruning_model: str | None = Field(
        default=None,
        min_length=1,
        max_length=160,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/+-]*$",
    )
    multilevel_structure_model: str | None = Field(
        default=None,
        min_length=1,
        max_length=160,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/+-]*$",
    )

    def reviewer_models(self) -> list[tuple[EditorialReviewerRole, str]]:
        selected: list[tuple[EditorialReviewerRole, str]] = []
        if self.content_omission_model:
            selected.append(("content_omission", self.content_omission_model))
        if self.pruning_model:
            selected.append(("pruning", self.pruning_model))
        if self.multilevel_structure_model:
            selected.append(
                ("multilevel_structure", self.multilevel_structure_model)
            )
        return selected

    def all_models(self) -> list[str]:
        return [
            self.editor_model,
            *(model for _, model in self.reviewer_models()),
        ]


class MindMapLoopConfig(BaseModel):
    rounds: list[MindMapLoopRound] = Field(min_length=1, max_length=6)

    def all_models(self) -> list[str]:
        return list(
            dict.fromkeys(
                model
                for round_config in self.rounds
                for model in round_config.all_models()
            )
        )


def default_mindmap_loop(model: str) -> MindMapLoopConfig:
    return MindMapLoopConfig(
        rounds=[
            MindMapLoopRound(
                editor_model=model,
                content_omission_model=model,
                pruning_model=model,
                multilevel_structure_model=model,
            )
        ]
    )
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


class TerminalGoldGate(BaseModel):
    name_teaches_novice: bool
    no_further_bullet_decomposition: bool
    minimum_knowledge_atom: bool

    @model_validator(mode="after")
    def validate_terminal_identity(self) -> "TerminalGoldGate":
        if not self.name_teaches_novice:
            raise ValueError(
                "terminal node name must teach a novice without context"
            )
        if not (
            self.no_further_bullet_decomposition
            or self.minimum_knowledge_atom
        ):
            raise ValueError(
                "terminal node requires an OR decomposition stop condition"
            )
        return self


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
    subject_id: str = ""
    subject_type: Literal["node", "tree_edge", "root", "cross_link"] = "node"
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
    structural_gate_passed: bool = False
    publish_gate_passed: bool = False
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
        "qwen",
        "deepseek",
        # Retained so graph versions created before the provider migration load.
        "kimi",
        "heuristic",
        "mixed",
    ] = "heuristic"
    model_selection: ModelSelection
    degraded_components: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    solver_status: str = ""
    run_manifest: dict = Field(default_factory=dict)


class JobView(BaseModel):
    id: str
    status: Literal["queued", "running", "completed", "failed", "cancelled"]
    stage: str
    progress: int
    message: str = ""
    mode: RunMode = "standard"
    loop_config: MindMapLoopConfig | None = None
    result: MindMapResult | None = None
    error: str | None = None
    context_tokens: int = Field(default=0, ge=0)
    max_context_tokens: int = Field(default=1_000_000, ge=1)
    context_usage: float = Field(default=0.0, ge=0.0)


class JobInteractionView(BaseModel):
    id: str
    kind: Literal["initial", "revision"]
    instruction: str = Field(default="", max_length=8000)
    created_at: str
    base_graph_version: int = Field(default=0, ge=0)
    result_graph_version: int | None = Field(default=None, ge=1)
    status: Literal["queued", "running", "completed", "failed", "cancelled"]
    error: str | None = None


class JobRefinementRequest(BaseModel):
    instruction: str = Field(min_length=1, max_length=8000)
    expected_graph_version: int = Field(ge=1)

    @model_validator(mode="after")
    def strip_instruction(self):
        self.instruction = self.instruction.strip()
        if not self.instruction:
            raise ValueError("instruction cannot be blank")
        return self


class HistoryItem(BaseModel):
    task_id: str
    title: str
    filename: str
    file_type: str
    mode: RunMode
    extraction_mode: Literal["qwen", "deepseek", "kimi", "heuristic", "mixed"]
    graph_version: int
    node_count: int
    review_count: int
    quality_gate_passed: bool
    created_at: str
    updated_at: str
    status: Literal[
        "queued",
        "running",
        "completed",
        "failed",
        "cancelled",
    ] = "completed"
    stage: str = "complete"
    progress: int = 100
    error: str | None = None


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
    expected_graph_version: int = Field(ge=1)

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
