export type Evidence = {
  unit_id?: string | null;
  chunk_id?: string | null;
  excerpt: string;
  page?: number | null;
  slide?: number | null;
  bbox?: number[] | null;
  asset_id?: string | null;
};

export type ModelProvider = "kimi";

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

export type ContentUnit = {
  id: string;
  document_id: string;
  kind: "text" | "visual";
  branch_hint?: string | null;
  importance: number;
  status: "uncovered" | "covered" | "merged" | "deferred" | "rejected";
  text: string;
  heading_path: string[];
  unit_role: string;
  evidence_excerpt: string;
  page?: number | null;
  slide?: number | null;
  bbox?: number[] | null;
  asset_id?: string | null;
  visual_kind?: string | null;
  visual_action:
    | "standalone_node"
    | "attach_as_media"
    | "decompose"
    | "ignore_decoration"
    | "unclassified";
  summary: string;
};

export type ModelVote = {
  actor: string;
  model?: string | null;
  classification: string;
  score: number;
  reason: string;
};

export type MindMapNode = {
  id: string;
  temp_ids: string[];
  name: string;
  type: string;
  role: string;
  definition: string;
  aliases: string[];
  origin: "explicit" | "abstractive" | "synthesized_root" | "structural";
  branch_id?: string | null;
  confidence: number;
  optional: boolean;
  activation_score: number;
  activation_cost: number;
  is_root_candidate: boolean;
  evidence: Evidence[];
  support_unit_ids: string[];
  media_asset_ids: string[];
  depth: number;
  parent_id?: string | null;
  status: "candidate" | "accepted" | "deferred" | "rejected" | "needs_review";
  risk_score: number;
};

export type MindMapTreeEdge = {
  id: string;
  source: string;
  target: string;
  score: number;
  provisional: boolean;
  evidence: Evidence[];
  classification: string;
  verifier_votes: ModelVote[];
};

export type MindMapCrossLink = {
  id: string;
  source: string;
  target: string;
  relation: string;
  score: number;
  evidence: Evidence[];
  verifier_votes: ModelVote[];
};

export type VisualAsset = {
  asset_id: string;
  render_id: string;
  filename: string;
  url: string;
  source_page?: number | null;
  source_slide?: number | null;
  bbox?: number[] | null;
  width?: number | null;
  height?: number | null;
  visual_kind: string;
  status: "ready" | "needs_render" | "metadata_only";
  ocr_text: string;
  sha1: string;
};

export type ReviewItem = {
  id: string;
  type:
    | "root_choice"
    | "abstract_parent"
    | "competing_parent"
    | "cross_link"
    | "uncovered_content";
  risk_score: number;
  subject_ids: string[];
  reason: string;
  alternatives: Array<Record<string, unknown>>;
  evidence_unit_ids: string[];
  model_votes: ModelVote[];
  local_subtree_preview: {
    nodes?: Array<{ id: string; name: string; role: string }>;
    tree_edges?: MindMapTreeEdge[];
  };
  status: "pending" | "resolved";
  resolution?: Record<string, unknown> | null;
};

export type DecisionRecord = {
  id: string;
  run_id: string;
  subject_type: string;
  subject_id: string;
  actor: "code" | "model" | "human";
  actor_version: string;
  prompt_version?: string | null;
  decision: string;
  reason_codes: string[];
  evidence_unit_ids: string[];
  timestamp: string;
};

export type AnalysisResult = {
  task_id: string;
  run_id: string;
  graph_version: number;
  document: {
    document_id: string;
    filename: string;
    file_type: string;
    title: string;
    blocks: Array<{
      text: string;
      page?: number | null;
      slide?: number | null;
      heading?: string | null;
    }>;
  };
  chunks: Chunk[];
  content_units: ContentUnit[];
  root_id: string;
  nodes: MindMapNode[];
  tree_edges: MindMapTreeEdge[];
  cross_links: MindMapCrossLink[];
  assets: VisualAsset[];
  quality_report: {
    node_count: number;
    tree_edge_count: number;
    cross_link_count: number;
    root_count: number;
    orphan_count: number;
    conflict_count: number;
    provisional_edge_count: number;
    evidence_coverage: number;
    topology_valid: boolean;
    weighted_content_coverage: number;
    direct_parent_confidence: number;
    abstraction_support_rate: number;
    review_item_count: number;
    quality_gate_passed: boolean;
    coverage: {
      total_units: number;
      covered_units: number;
      weighted_coverage: number;
      uncovered_unit_ids: string[];
      branch_coverage: Record<string, number>;
    };
    warnings: string[];
  };
  review_items: ReviewItem[];
  decision_records: DecisionRecord[];
  mode: "standard" | "precision";
  extraction_mode: "kimi" | "heuristic" | "mixed";
  model_selection: {
    generator_provider: string;
    generator_model?: string | null;
    verifier_provider: string;
    verifier_model?: string | null;
    vision_provider?: string | null;
    vision_model?: string | null;
    arbiter_provider?: string | null;
    arbiter_model?: string | null;
  };
  degraded_components: string[];
  warnings: string[];
  solver_status: string;
};

export type Job = {
  id: string;
  status: "queued" | "running" | "completed" | "failed";
  stage: string;
  progress: number;
  message: string;
  mode: "standard" | "precision";
  result?: AnalysisResult | null;
  error?: string | null;
};

export type HistoryItem = {
  task_id: string;
  title: string;
  filename: string;
  file_type: string;
  mode: "standard" | "precision";
  extraction_mode: "kimi" | "heuristic" | "mixed";
  graph_version: number;
  node_count: number;
  review_count: number;
  quality_gate_passed: boolean;
  created_at: string;
  updated_at: string;
};

export type Health = {
  status: string;
  workspace: {
    name: string;
    id_suffix: string;
    key_configured: boolean;
    secret_source: "environment" | "age" | "none";
    secret_error: string;
  };
  default_model: string;
  providers: {
    kimi: {
      configured: boolean;
      default_model: string;
      base_url: string;
    };
  };
  architecture: {
    name: string;
    blackboard: string;
    topology_solver: string;
    graph_validator: string;
    modes: string[];
  };
  supported_extensions: string[];
};

export type ReviewResolution = {
  action: "keep" | "delete" | "change_parent" | "rename" | "accept_root";
  parent_id?: string;
  label?: string;
  reason?: string;
};
