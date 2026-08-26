import {
  BookOpenText,
  FileText,
  GitCommitHorizontal,
  Image,
  Link2,
  ShieldCheck,
  X,
} from "lucide-react";

import { isRenderableNodeMedia } from "../mindmapMedia";
import type { AnalysisResult } from "../types";

type InspectorProps = {
  result: AnalysisResult;
  nodeId: string | null;
  onClose: () => void;
};

const originLabels: Record<string, string> = {
  explicit: "显式知识",
  abstractive: "归纳父节点",
  synthesized_root: "综合根主题",
  structural: "结构节点",
};

export function Inspector({ result, nodeId, onClose }: InspectorProps) {
  const node = result.nodes.find((item) => item.id === nodeId);
  if (!node) {
    return (
      <aside className="inspector inspector-empty">
        <BookOpenText size={22} />
        <h3>节点证据</h3>
        <p>选择节点后显示来源、父边校验和决策记录。</p>
      </aside>
    );
  }

  const parentEdge = result.tree_edges.find((edge) => edge.target === node.id);
  const childEdges = result.tree_edges.filter((edge) => edge.source === node.id);
  const crossLinks = result.cross_links.filter(
    (edge) => edge.source === node.id || edge.target === node.id,
  );
  const nodeNames = new Map(result.nodes.map((item) => [item.id, item.name]));
  const decisions = result.decision_records.filter(
    (item) => item.subject_id === node.id || item.subject_id === parentEdge?.id,
  );
  const assets = result.assets.filter((asset) =>
    node.media_asset_ids.includes(asset.asset_id)
    && isRenderableNodeMedia(asset),
  );

  return (
    <aside className="inspector">
      <div className="inspector-head">
        <div>
          <span className="eyebrow">{node.role}</span>
          <h3>{node.name}</h3>
        </div>
        <button type="button" onClick={onClose} title="关闭" aria-label="关闭">
          <X size={17} />
        </button>
      </div>

      <div className="node-meta-grid">
        <div>
          <span>来源</span>
          <strong>{originLabels[node.origin] || node.origin}</strong>
        </div>
        <div>
          <span>深度</span>
          <strong>{node.depth}</strong>
        </div>
        <div>
          <span>置信度</span>
          <strong>{Math.round(node.confidence * 100)}%</strong>
        </div>
        <div>
          <span>风险</span>
          <strong>{Math.round(node.risk_score * 100)}%</strong>
        </div>
      </div>

      <section className="inspector-section">
        <h4>
          <BookOpenText size={15} /> 定义
        </h4>
        <p>{node.definition || "未检出明确的定义句。"}</p>
      </section>

      {(parentEdge || childEdges.length > 0 || crossLinks.length > 0) && (
        <section className="inspector-section">
          <h4>
            <Link2 size={15} /> 结构关系
          </h4>
          <div className="relation-list">
            {parentEdge && (
              <div className="relation-item">
                <span>{nodeNames.get(parentEdge.source)}</span>
                <b>{parentEdge.provisional ? "待确认父边" : "直接父节点"}</b>
                <span>{node.name}</span>
              </div>
            )}
            {childEdges.slice(0, 8).map((edge) => (
              <div key={edge.id} className="relation-item">
                <span>{node.name}</span>
                <b>子节点</b>
                <span>{nodeNames.get(edge.target)}</span>
              </div>
            ))}
            {crossLinks.map((edge) => (
              <div key={edge.id} className="relation-item cross">
                <span>{nodeNames.get(edge.source)}</span>
                <b>{edge.relation}</b>
                <span>{nodeNames.get(edge.target)}</span>
              </div>
            ))}
          </div>
        </section>
      )}

      {parentEdge && parentEdge.verifier_votes.length > 0 && (
        <section className="inspector-section">
          <h4>
            <ShieldCheck size={15} /> 父边校验
          </h4>
          <div className="vote-list">
            {parentEdge.verifier_votes.map((vote, index) => (
              <div key={`${vote.actor}-${index}`} className="vote-item">
                <div>
                  <strong>{vote.actor}</strong>
                  <span>{Math.round(vote.score * 100)}%</span>
                </div>
                <b>{vote.classification}</b>
                <p>{vote.reason}</p>
              </div>
            ))}
          </div>
        </section>
      )}

      {assets.length > 0 && (
        <section className="inspector-section">
          <h4>
            <Image size={15} /> 视觉证据
          </h4>
          <div className="asset-list">
            {assets.map((asset) => (
              <figure key={asset.asset_id}>
                {asset.url ? <img src={asset.url} alt={node.name} /> : null}
                <figcaption>{asset.visual_kind}</figcaption>
              </figure>
            ))}
          </div>
        </section>
      )}

      <section className="inspector-section">
        <h4>
          <FileText size={15} /> 原文证据
        </h4>
        <div className="evidence-list">
          {node.evidence.map((evidence, index) => (
            <blockquote key={`${evidence.unit_id || evidence.chunk_id}-${index}`}>
              <span>
                {evidence.slide
                  ? `第 ${evidence.slide} 页幻灯片`
                  : evidence.page
                    ? `PDF 第 ${evidence.page} 页`
                    : `单元 ${(evidence.unit_id || evidence.chunk_id || "").slice(-6)}`}
              </span>
              {evidence.excerpt || "聚合支持证据"}
            </blockquote>
          ))}
          {node.evidence.length === 0 && node.support_unit_ids.length > 0 && (
            <blockquote>
              <span>聚合支持</span>
              {node.support_unit_ids.join("、")}
            </blockquote>
          )}
        </div>
      </section>

      {decisions.length > 0 && (
        <section className="inspector-section">
          <h4>
            <GitCommitHorizontal size={15} /> 决策历史
          </h4>
          <div className="decision-list">
            {decisions.map((decision) => (
              <div key={decision.id}>
                <strong>{decision.decision}</strong>
                <span>{decision.actor_version}</span>
              </div>
            ))}
          </div>
        </section>
      )}
    </aside>
  );
}
