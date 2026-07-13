from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SourceBlock(BaseModel):
    text: str
    page: int | None = None
    slide: int | None = None
    heading: str | None = None


class ParsedDocument(BaseModel):
    document_id: str
    filename: str
    file_type: str
    title: str
    blocks: list[SourceBlock]


class Evidence(BaseModel):
    chunk_id: str
    excerpt: str
    page: int | None = None
    slide: int | None = None


class Chunk(BaseModel):
    id: str
    index: int
    text: str
    heading: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    slide_start: int | None = None
    slide_end: int | None = None


class NodeCandidate(BaseModel):
    temp_id: str
    name: str
    type: str = "concept"
    definition: str = ""
    aliases: list[str] = Field(default_factory=list)
    confidence: float = 0.5
    evidence: list[Evidence] = Field(default_factory=list)


class EdgeCandidate(BaseModel):
    source: str
    predicate: str
    target: str
    confidence: float = 0.5
    evidence: list[Evidence] = Field(default_factory=list)


class ChunkExtraction(BaseModel):
    nodes: list[NodeCandidate] = Field(default_factory=list)
    edges: list[EdgeCandidate] = Field(default_factory=list)


class KnowledgeNode(BaseModel):
    id: str
    name: str
    type: str
    definition: str
    aliases: list[str] = Field(default_factory=list)
    confidence: float
    evidence: list[Evidence] = Field(default_factory=list)
    source_chunks: list[str] = Field(default_factory=list)


class KnowledgeEdge(BaseModel):
    id: str
    source: str
    predicate: str
    target: str
    confidence: float
    evidence: list[Evidence] = Field(default_factory=list)


class QualityReport(BaseModel):
    node_count: int
    edge_count: int
    isolated_node_count: int
    evidence_coverage: float
    warnings: list[str] = Field(default_factory=list)


class AnalysisResult(BaseModel):
    task_id: str
    document: ParsedDocument
    chunks: list[Chunk]
    nodes: list[KnowledgeNode]
    edges: list[KnowledgeEdge]
    quality: QualityReport
    extraction_mode: Literal["bailian", "deepseek", "heuristic", "mixed"]
    provider: Literal["bailian", "deepseek", "heuristic"]
    model: str | None = None
    warnings: list[str] = Field(default_factory=list)


class JobView(BaseModel):
    id: str
    status: Literal["queued", "running", "completed", "failed"]
    stage: str
    progress: int
    message: str = ""
    result: AnalysisResult | None = None
    error: str | None = None
