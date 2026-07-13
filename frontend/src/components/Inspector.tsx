import { BookOpenText, FileText, Link2, X } from "lucide-react";

import type { AnalysisResult } from "../types";

type InspectorProps = {
  result: AnalysisResult;
  nodeId: string | null;
  onClose: () => void;
};

export function Inspector({ result, nodeId, onClose }: InspectorProps) {
  const node = result.nodes.find((item) => item.id === nodeId);
  if (!node) {
    return (
      <aside className="inspector inspector-empty">
        <BookOpenText size={22} />
        <h3>节点证据</h3>
        <p>选择图中的知识点，查看定义、置信度与原文来源。</p>
      </aside>
    );
  }

  const related = result.edges.filter(
    (edge) => edge.source === node.id || edge.target === node.id,
  );
  const nodeNames = new Map(result.nodes.map((item) => [item.id, item.name]));

  return (
    <aside className="inspector">
      <div className="inspector-head">
        <div>
          <span className="eyebrow">{node.type}</span>
          <h3>{node.name}</h3>
        </div>
        <button type="button" onClick={onClose} title="关闭" aria-label="关闭">
          <X size={17} />
        </button>
      </div>

      <div className="confidence-row">
        <span>置信度</span>
        <strong>{Math.round(node.confidence * 100)}%</strong>
      </div>
      <div className="confidence-track">
        <span style={{ width: `${node.confidence * 100}%` }} />
      </div>

      <section className="inspector-section">
        <h4>
          <BookOpenText size={15} /> 定义
        </h4>
        <p>{node.definition || "原文中未检出明确的定义句。"}</p>
      </section>

      {related.length > 0 && (
        <section className="inspector-section">
          <h4>
            <Link2 size={15} /> 关系
          </h4>
          <div className="relation-list">
            {related.map((edge) => (
              <div key={edge.id} className="relation-item">
                <span>
                  {edge.source === node.id
                    ? node.name
                    : nodeNames.get(edge.source)}
                </span>
                <b>{edge.predicate}</b>
                <span>
                  {edge.target === node.id
                    ? node.name
                    : nodeNames.get(edge.target)}
                </span>
              </div>
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
            <blockquote key={`${evidence.chunk_id}-${index}`}>
              <span>
                {evidence.slide
                  ? `第 ${evidence.slide} 页幻灯片`
                  : evidence.page
                    ? `PDF 第 ${evidence.page} 页`
                    : `Chunk ${evidence.chunk_id.slice(-4)}`}
              </span>
              {evidence.excerpt}
            </blockquote>
          ))}
        </div>
      </section>
    </aside>
  );
}
