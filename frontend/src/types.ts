export type Evidence = {
  chunk_id: string;
  excerpt: string;
  page?: number | null;
  slide?: number | null;
};

export type Chunk = {
  id: string;
  index: number;
  text: string;
  heading?: string | null;
  page_start?: number | null;
  page_end?: number | null;
  slide_start?: number | null;
  slide_end?: number | null;
};

export type KnowledgeNode = {
  id: string;
  name: string;
  type: string;
  definition: string;
  aliases: string[];
  confidence: number;
  evidence: Evidence[];
  source_chunks: string[];
};

export type KnowledgeEdge = {
  id: string;
  source: string;
  predicate: string;
  target: string;
  confidence: number;
  evidence: Evidence[];
};

export type AnalysisResult = {
  task_id: string;
  document: {
    document_id: string;
    filename: string;
    file_type: string;
    title: string;
  };
  chunks: Chunk[];
  nodes: KnowledgeNode[];
  edges: KnowledgeEdge[];
  quality: {
    node_count: number;
    edge_count: number;
    isolated_node_count: number;
    evidence_coverage: number;
    warnings: string[];
  };
  extraction_mode: "bailian" | "deepseek" | "heuristic" | "mixed";
  provider: "bailian" | "deepseek" | "heuristic";
  model?: string | null;
  warnings: string[];
};

export type Job = {
  id: string;
  status: "queued" | "running" | "completed" | "failed";
  stage: string;
  progress: number;
  message: string;
  result?: AnalysisResult | null;
  error?: string | null;
};

export type Health = {
  status: string;
  workspace: {
    name: string;
    id_suffix: string;
    key_configured: boolean;
  };
  default_model: string;
  providers: {
    bailian: { configured: boolean; default_model: string };
    deepseek: { configured: boolean; default_model: string };
  };
  supported_extensions: string[];
};
