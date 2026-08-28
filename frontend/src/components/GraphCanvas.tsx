import cytoscape, { type Core } from "cytoscape";
import {
  AlertTriangle,
  Download,
  Maximize2,
  Minus,
  Plus,
  RotateCcw,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";

import {
  collapseMindMapToBudget,
  computeMindMapLayout,
  findMindMapSpacingViolations,
  mindMapLabelMaxLines,
  wrapMindMapLabel,
} from "../mindmapLayout";
import { isRenderableNodeMedia } from "../mindmapMedia";
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

const runMindMapLayout = (graph: Core, rootId: string) => {
  const nodes = graph.nodes();
  const nodeIds = new Set(nodes.map((node) => node.id()));
  const treeEdges: Array<{ source: string; target: string }> = [];
  graph.edges().forEach((edge) => {
    if (
      !edge.hasClass("cross-link") &&
      nodeIds.has(edge.source().id()) &&
      nodeIds.has(edge.target().id())
    ) {
      treeEdges.push({
        source: edge.source().id(),
        target: edge.target().id(),
      });
    }
  });
  const layout = computeMindMapLayout({
    nodes: nodes.map((node) => ({
      id: node.id(),
      width: Number(node.data("width")) || 180,
      height: Number(node.data("height")) || 58,
    })),
    edges: treeEdges,
    rootId,
  });
  const violations = findMindMapSpacingViolations(layout, 24);
  if (violations.length) {
    throw new Error(`布局安全间距校验失败：${violations.length} 对节点`);
  }

  graph.startBatch();
  nodes.forEach((node) => {
    node.position(layout.positions.get(node.id()) || { x: 0, y: 0 });
  });
  graph.endBatch();
  graph.fit(nodes, 64);
};

export function GraphCanvas({
  result,
  selectedNodeId,
  showCrossLinks,
  onSelectNode,
}: GraphCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const graphRef = useRef<Core | null>(null);
  const [renderError, setRenderError] = useState("");

  useEffect(() => {
    if (!containerRef.current) return;
    setRenderError("");
    let graph: Core | null = null;
    try {
      const assetById = new Map(
        result.assets.map((asset) => [asset.asset_id, asset]),
      );
      const visibility = collapseMindMapToBudget({
        nodeIds: result.nodes.map((node) => node.id),
        edges: result.tree_edges,
        rootId: result.root_id,
        maxVisible: 120,
      });
      const visibleNodeIds = new Set(visibility.visibleNodeIds);
      const visibleNodes = result.nodes.filter((node) =>
        visibleNodeIds.has(node.id),
      );
      const hiddenCounts = visibility.hiddenCounts;
      graph = cytoscape({
        container: containerRef.current,
        elements: [
        ...visibleNodes.map((node) => {
          const isRoot = node.id === result.root_id;
          const isBranch = node.role === "branch_topic";
          const mediaAsset = node.media_asset_ids
            .map((assetId) => assetById.get(assetId))
            .find(isRenderableNodeMedia);
          const hiddenCount = hiddenCounts.get(node.id) || 0;
          const label = hiddenCount ? `${node.name}  +${hiddenCount}` : node.name;
          const unitsPerLine = mediaAsset
            ? 13
            : isRoot
              ? 13
              : isBranch
                ? 11
                : 10;
          const maxLines = mindMapLabelMaxLines({
            isRoot,
            isBranch,
            hasMedia: Boolean(mediaAsset),
          });
          const displayLabel = wrapMindMapLabel(label, unitsPerLine, maxLines);
          const lineCount = displayLabel.split("\n").length;
          const width = mediaAsset ? 180 : isRoot ? 230 : isBranch ? 190 : 180;
          const height = mediaAsset
            ? 132
            : Math.max(
                isRoot ? 72 : 58,
                24 + lineCount * (isRoot ? 17 : 15) + (isRoot ? 0 : 14),
              );
          return {
            data: {
              id: node.id,
              label: displayLabel,
              fullLabel: node.name,
              role: node.role,
              depth: node.depth,
              confidence: node.confidence,
              color: palette[node.role] || palette.concept,
              width,
              height,
              textWidth: width - 18,
              imageUrl: mediaAsset?.url || "",
              risk: node.risk_score,
              hiddenCount,
            },
            classes: [
              isRoot ? "root-node" : "",
              node.status === "needs_review" ? "needs-review" : "",
              mediaAsset ? "has-media" : "",
              hiddenCount ? "collapsed" : "",
            ]
              .filter(Boolean)
              .join(" "),
          };
        }),
        ...result.tree_edges
          .filter(
            (edge) => visibleNodeIds.has(edge.source) && visibleNodeIds.has(edge.target),
          )
          .map((edge) => ({
          data: {
            id: edge.id,
            source: edge.source,
            target: edge.target,
            label: edge.provisional ? "待确认" : "",
            score: edge.score,
            color:
              palette[result.nodes.find((node) => node.id === edge.target)?.role || "concept"] ||
              palette.concept,
          },
          classes: edge.provisional ? "provisional" : "tree-edge",
        })),
        ...result.cross_links
          .filter(
            (edge) => visibleNodeIds.has(edge.source) && visibleNodeIds.has(edge.target),
          )
          .map((edge) => ({
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
            "text-max-width": "data(textWidth)",
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
            "text-max-width": "data(textWidth)",
          },
        },
        {
          selector: "node.has-media",
          style: {
            "background-image": "data(imageUrl)",
            "background-fit": "contain",
            "background-image-opacity": 1,
            "background-color": "#ffffff",
            color: "#172033",
            "text-valign": "bottom",
            "text-margin-y": -8,
            "text-background-color": "#ffffff",
            "text-background-opacity": 0.92,
            "text-background-padding": "3px",
          },
        },
        {
          selector: "node.collapsed",
          style: {
            "border-width": 3,
            "border-style": "double",
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
            "line-color": "data(color)",
            "line-opacity": 0.56,
            "target-arrow-shape": "none",
            "curve-style": "bezier",
          },
        },
        {
          selector: "edge.provisional",
          style: {
            width: 2,
            "line-color": "#d97706",
            "target-arrow-color": "#d97706",
            "target-arrow-shape": "none",
            "line-style": "dashed",
            "curve-style": "bezier",
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
        layout: { name: "preset" },
        minZoom: 0.03,
        maxZoom: 3.2,
      });
      runMindMapLayout(graph, result.root_id);
      graph.on("tap", "node", (event) => onSelectNode(event.target.id()));
      graph.on("tap", (event) => {
        if (event.target === graph) onSelectNode(null);
      });
    } catch (error) {
      graph?.destroy();
      setRenderError(
        error instanceof Error ? error.message : "导图画布初始化失败",
      );
      return;
    }
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
      {renderError && (
        <div className="graph-render-error" role="alert">
          <AlertTriangle size={26} />
          <strong>导图画布加载失败</strong>
          <span>结果已经保存，可切换到节点表或下载 JSON、PNG。</span>
          <small>{renderError}</small>
        </div>
      )}
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
            graphRef.current &&
            runMindMapLayout(graphRef.current, result.root_id)
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
