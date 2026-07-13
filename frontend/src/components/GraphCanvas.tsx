import cytoscape, { type Core } from "cytoscape";
import { Maximize2, Minus, Plus, RotateCcw } from "lucide-react";
import { useEffect, useRef } from "react";

import type { AnalysisResult } from "../types";

type GraphCanvasProps = {
  result: AnalysisResult;
  selectedNodeId: string | null;
  onSelectNode: (id: string | null) => void;
};

const palette: Record<string, string> = {
  concept: "#2563eb",
  method: "#0f766e",
  principle: "#7c3aed",
  process: "#c2410c",
  formula: "#be123c",
  example: "#64748b",
  system: "#0369a1",
  person: "#a16207",
};

export function GraphCanvas({
  result,
  selectedNodeId,
  onSelectNode,
}: GraphCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const graphRef = useRef<Core | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    const graph = cytoscape({
      container: containerRef.current,
      elements: [
        ...result.nodes.map((node) => ({
          data: {
            id: node.id,
            label: node.name,
            type: node.type,
            confidence: node.confidence,
            color: palette[node.type] || palette.concept,
          },
        })),
        ...result.edges.map((edge) => ({
          data: {
            id: edge.id,
            source: edge.source,
            target: edge.target,
            label: edge.predicate,
            confidence: edge.confidence,
          },
        })),
      ],
      style: [
        {
          selector: "node",
          style: {
            width: 48,
            height: 48,
            "background-color": "data(color)",
            "border-width": 3,
            "border-color": "#ffffff",
            "overlay-opacity": 0,
            label: "data(label)",
            color: "#172033",
            "font-family": "Inter, Noto Sans SC, sans-serif",
            "font-size": 12,
            "font-weight": 600,
            "text-wrap": "wrap",
            "text-max-width": "100px",
            "text-valign": "bottom",
            "text-margin-y": 10,
          },
        },
        {
          selector: "node:selected",
          style: {
            "border-width": 5,
            "border-color": "#f59e0b",
          },
        },
        {
          selector: "edge",
          style: {
            width: 1.5,
            "line-color": "#a8b4c5",
            "target-arrow-color": "#a8b4c5",
            "target-arrow-shape": "triangle",
            "curve-style": "bezier",
            label: "data(label)",
            color: "#667085",
            "font-size": 9,
            "text-background-color": "#f8fafc",
            "text-background-opacity": 0.9,
            "text-background-padding": "3px",
            "text-rotation": "autorotate",
          },
        },
      ],
      layout: {
        name: "cose",
        animate: false,
        fit: true,
        padding: 60,
        nodeRepulsion: () => 7800,
        idealEdgeLength: () => 115,
      },
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
  }, [result, onSelectNode]);

  useEffect(() => {
    const graph = graphRef.current;
    if (!graph) return;
    graph.elements().unselect();
    if (selectedNodeId) graph.getElementById(selectedNodeId).select();
  }, [selectedNodeId]);

  return (
    <div className="graph-shell">
      <div ref={containerRef} className="graph-canvas" aria-label="知识关系图" />
      <div className="graph-controls" aria-label="图谱缩放工具">
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
            graphRef.current
              ?.layout({ name: "cose", animate: true, padding: 60 })
              .run()
          }
        >
          <RotateCcw size={16} />
        </button>
        <button
          type="button"
          title="适应画布"
          aria-label="适应画布"
          onClick={() => graphRef.current?.fit(undefined, 60)}
        >
          <Maximize2 size={16} />
        </button>
      </div>
    </div>
  );
}
