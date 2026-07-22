import cytoscape, { type Core } from "cytoscape";
import { Download, Maximize2, Minus, Plus, RotateCcw } from "lucide-react";
import { useEffect, useRef } from "react";

import type { AnalysisResult } from "../types";

type GraphCanvasProps = {
  result: AnalysisResult;
  selectedNodeId: string | null;
  showCrossLinks: boolean;
  onSelectNode: (id: string | null) => void;
};

const palette: Record<string, string> = {
  root_topic: "#1d4ed8",
  branch_topic: "#0f766e",
  concept: "#2563eb",
  method: "#0e7490",
  principle: "#7c3aed",
  process: "#c2410c",
  step: "#b45309",
  formula: "#be123c",
  example: "#64748b",
  warning: "#b91c1c",
  system: "#0369a1",
  visual_knowledge: "#047857",
  table: "#475569",
};

const layoutOptions = (rootId: string) =>
  ({
    name: "breadthfirst",
    animate: false,
    directed: true,
    roots: `#${rootId}`,
    fit: true,
    padding: 54,
    spacingFactor: 1.22,
    avoidOverlap: true,
    maximal: true,
  }) as const;

export function GraphCanvas({
  result,
  selectedNodeId,
  showCrossLinks,
  onSelectNode,
}: GraphCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const graphRef = useRef<Core | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    const graph = cytoscape({
      container: containerRef.current,
      elements: [
        ...result.nodes.map((node) => {
          const isRoot = node.id === result.root_id;
          const isBranch = node.role === "branch_topic";
          return {
            data: {
              id: node.id,
              label: node.name,
              role: node.role,
              confidence: node.confidence,
              color: palette[node.role] || palette.concept,
              width: isRoot ? 124 : isBranch ? 110 : 92,
              height: isRoot ? 52 : 42,
              risk: node.risk_score,
            },
            classes: [
              isRoot ? "root-node" : "",
              node.status === "needs_review" ? "needs-review" : "",
            ]
              .filter(Boolean)
              .join(" "),
          };
        }),
        ...result.tree_edges.map((edge) => ({
          data: {
            id: edge.id,
            source: edge.source,
            target: edge.target,
            label: edge.provisional ? "待确认" : "",
            score: edge.score,
          },
          classes: edge.provisional ? "provisional" : "tree-edge",
        })),
        ...result.cross_links.map((edge) => ({
          data: {
            id: edge.id,
            source: edge.source,
            target: edge.target,
            label: edge.relation,
            score: edge.score,
          },
          classes: "cross-link",
        })),
      ],
      style: [
        {
          selector: "node",
          style: {
            width: "data(width)",
            height: "data(height)",
            shape: "round-rectangle",
            "background-color": "#ffffff",
            "border-width": 2,
            "border-color": "data(color)",
            "overlay-opacity": 0,
            label: "data(label)",
            color: "#172033",
            "font-family": "Inter, Noto Sans SC, sans-serif",
            "font-size": 11,
            "font-weight": 600,
            "text-wrap": "wrap",
            "text-max-width": "84px",
            "text-valign": "center",
            "text-halign": "center",
          },
        },
        {
          selector: "node.root-node",
          style: {
            "background-color": "#1d4ed8",
            "border-color": "#1d4ed8",
            color: "#ffffff",
            "font-size": 12,
            "text-max-width": "112px",
          },
        },
        {
          selector: "node.needs-review",
          style: {
            "border-style": "dashed",
            "border-color": "#d97706",
          },
        },
        {
          selector: "node:selected",
          style: {
            "border-width": 4,
            "border-color": "#f59e0b",
            "background-color": "#fffbeb",
            color: "#172033",
          },
        },
        {
          selector: "edge.tree-edge",
          style: {
            width: 1.8,
            "line-color": "#9aa9ba",
            "target-arrow-color": "#9aa9ba",
            "target-arrow-shape": "triangle",
            "curve-style": "taxi",
            "taxi-direction": "downward",
            "taxi-turn": 20,
          },
        },
        {
          selector: "edge.provisional",
          style: {
            width: 2,
            "line-color": "#d97706",
            "target-arrow-color": "#d97706",
            "target-arrow-shape": "triangle",
            "line-style": "dashed",
            "curve-style": "taxi",
            label: "data(label)",
            color: "#92400e",
            "font-size": 8,
          },
        },
        {
          selector: "edge.cross-link",
          style: {
            display: showCrossLinks ? "element" : "none",
            width: 1.2,
            "line-color": "#7c3aed",
            "target-arrow-color": "#7c3aed",
            "target-arrow-shape": "vee",
            "line-style": "dashed",
            "curve-style": "bezier",
            label: "data(label)",
            color: "#6d28d9",
            "font-size": 8,
            "text-background-color": "#ffffff",
            "text-background-opacity": 0.9,
            "text-background-padding": "2px",
            "text-rotation": "autorotate",
          },
        },
      ],
      layout: layoutOptions(result.root_id),
      minZoom: 0.25,
      maxZoom: 2.4,
    });
    graph.on("tap", "node", (event) => onSelectNode(event.target.id()));
    graph.on("tap", (event) => {
      if (event.target === graph) onSelectNode(null);
    });
    graphRef.current = graph;
    return () => {
      graph.destroy();
      graphRef.current = null;
    };
  }, [result, showCrossLinks, onSelectNode]);

  useEffect(() => {
    const graph = graphRef.current;
    if (!graph) return;
    graph.elements().unselect();
    if (selectedNodeId) graph.getElementById(selectedNodeId).select();
  }, [selectedNodeId]);

  return (
    <div className="graph-shell">
      <div ref={containerRef} className="graph-canvas" aria-label="课程思维导图" />
      <div className="graph-controls" aria-label="导图缩放工具">
        <button
          type="button"
          title="放大"
          aria-label="放大"
          onClick={() => graphRef.current?.zoom(graphRef.current.zoom() * 1.2)}
        >
          <Plus size={16} />
        </button>
        <button
          type="button"
          title="缩小"
          aria-label="缩小"
          onClick={() => graphRef.current?.zoom(graphRef.current.zoom() / 1.2)}
        >
          <Minus size={16} />
        </button>
        <button
          type="button"
          title="重新布局"
          aria-label="重新布局"
          onClick={() =>
            graphRef.current?.layout(layoutOptions(result.root_id)).run()
          }
        >
          <RotateCcw size={16} />
        </button>
        <button
          type="button"
          title="适应画布"
          aria-label="适应画布"
          onClick={() => graphRef.current?.fit(undefined, 54)}
        >
          <Maximize2 size={16} />
        </button>
        <a
          href={`/api/jobs/${result.task_id}/export.png`}
          download
          title="保存 PNG"
          aria-label="保存 PNG"
        >
          <Download size={16} />
        </a>
      </div>
    </div>
  );
}
