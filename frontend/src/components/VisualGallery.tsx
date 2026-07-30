import { FileImage, Images } from "lucide-react";
import { useMemo, useState } from "react";

import type { AnalysisResult } from "../types";

type VisualGalleryProps = {
  result: AnalysisResult;
  onSelectNode: (id: string) => void;
};

type VisualFilter = "knowledge" | "pages" | "all";

export function VisualGallery({ result, onSelectNode }: VisualGalleryProps) {
  const [filter, setFilter] = useState<VisualFilter>("knowledge");
  const nodeByAsset = useMemo(() => {
    const linked = new Map<string, { id: string; name: string }>();
    for (const node of result.nodes) {
      for (const assetId of node.media_asset_ids) {
        if (!linked.has(assetId)) linked.set(assetId, node);
      }
    }
    return linked;
  }, [result.nodes]);

  const assets = useMemo(
    () =>
      result.assets.filter((asset) => {
        if (filter === "pages") return asset.visual_kind === "full_page";
        if (filter === "knowledge") return asset.visual_kind !== "full_page";
        return true;
      }),
    [filter, result.assets],
  );

  const knowledgeCount = result.assets.filter(
    (asset) => asset.visual_kind !== "full_page",
  ).length;
  const pageCount = result.assets.length - knowledgeCount;

  return (
    <div className="visual-gallery">
      <header className="visual-gallery-head">
        <div>
          <Images size={18} />
          <strong>视觉证据</strong>
          <span>{assets.length} 张</span>
        </div>
        <div className="visual-filter" aria-label="视觉类型">
          <button
            type="button"
            className={filter === "knowledge" ? "active" : ""}
            onClick={() => setFilter("knowledge")}
          >
            知识图 {knowledgeCount}
          </button>
          <button
            type="button"
            className={filter === "pages" ? "active" : ""}
            onClick={() => setFilter("pages")}
          >
            原页 {pageCount}
          </button>
          <button
            type="button"
            className={filter === "all" ? "active" : ""}
            onClick={() => setFilter("all")}
          >
            全部
          </button>
        </div>
      </header>

      <div className="visual-grid">
        {assets.map((asset) => {
          const linkedNode = nodeByAsset.get(asset.asset_id);
          const location = asset.source_slide
            ? `幻灯片 ${asset.source_slide}`
            : asset.source_page
              ? `PDF 第 ${asset.source_page} 页`
              : "视觉证据";
          return (
            <figure className="visual-item" key={asset.asset_id}>
              <div className="visual-preview">
                {asset.url ? (
                  <img loading="lazy" src={asset.url} alt={linkedNode?.name || location} />
                ) : (
                  <FileImage size={28} />
                )}
              </div>
              <figcaption>
                <div>
                  <strong>{linkedNode?.name || location}</strong>
                  <span>{asset.visual_kind}</span>
                </div>
                {linkedNode && (
                  <button
                    type="button"
                    onClick={() => onSelectNode(linkedNode.id)}
                    title="在主树中打开绑定节点"
                  >
                    打开节点
                  </button>
                )}
              </figcaption>
            </figure>
          );
        })}
      </div>
    </div>
  );
}
