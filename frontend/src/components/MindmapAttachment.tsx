import {
  Download,
  Maximize2,
  Minus,
  Plus,
  RotateCcw,
  X,
} from "lucide-react";
import { useEffect, useState } from "react";

import type { AnalysisResult } from "../types";

const MIN_ZOOM = 0.5;
const MAX_ZOOM = 3;
const ZOOM_STEP = 0.25;

export function MindmapAttachment({ result }: { result: AnalysisResult }) {
  const [open, setOpen] = useState(false);
  const [zoom, setZoom] = useState(1);
  const [failed, setFailed] = useState(false);
  const imageUrl = `/api/jobs/${result.task_id}/export.png`;

  useEffect(() => {
    if (!open) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [open]);

  const openViewer = () => {
    setZoom(1);
    setOpen(true);
  };

  return (
    <>
      <figure className="mindmap-attachment">
        <button
          type="button"
          className="mindmap-thumbnail"
          onClick={openViewer}
          aria-label={`打开 ${result.document.title} 高清思维导图`}
        >
          {failed ? (
            <span className="mindmap-image-error">思维导图预览加载失败</span>
          ) : (
            <img
              src={imageUrl}
              alt={`${result.document.title} 思维导图预览`}
              loading="lazy"
              onError={() => setFailed(true)}
            />
          )}
          <span className="mindmap-thumbnail-action">
            <Maximize2 size={15} />
            查看高清图
          </span>
        </button>
        <figcaption>
          <span>
            <strong>{result.document.title}</strong>
            <small>
              {result.quality_report.node_count} 个节点 ·{" "}
              {Math.round(
                result.quality_report.weighted_content_coverage * 100,
              )}
              % 内容覆盖
            </small>
          </span>
          <a href={imageUrl} download aria-label="下载高清思维导图">
            <Download size={16} />
          </a>
        </figcaption>
      </figure>

      {open && (
        <div
          className="mindmap-viewer"
          role="dialog"
          aria-modal="true"
          aria-label={`${result.document.title} 高清思维导图`}
        >
          <header>
            <div>
              <strong>{result.document.title}</strong>
              <span>高清思维导图</span>
            </div>
            <div className="mindmap-viewer-tools">
              <button
                type="button"
                aria-label="缩小"
                title="缩小"
                onClick={() =>
                  setZoom((current) =>
                    Math.max(MIN_ZOOM, current - ZOOM_STEP),
                  )
                }
                disabled={zoom <= MIN_ZOOM}
              >
                <Minus size={17} />
              </button>
              <button
                type="button"
                aria-label="重置缩放"
                title="重置缩放"
                onClick={() => setZoom(1)}
              >
                <RotateCcw size={16} />
              </button>
              <button
                type="button"
                aria-label="放大"
                title="放大"
                onClick={() =>
                  setZoom((current) =>
                    Math.min(MAX_ZOOM, current + ZOOM_STEP),
                  )
                }
                disabled={zoom >= MAX_ZOOM}
              >
                <Plus size={17} />
              </button>
              <span>{Math.round(zoom * 100)}%</span>
              <a href={imageUrl} download aria-label="下载高清思维导图">
                <Download size={17} />
              </a>
              <button
                type="button"
                aria-label="关闭高清思维导图"
                title="关闭"
                onClick={() => setOpen(false)}
              >
                <X size={18} />
              </button>
            </div>
          </header>
          <div className="mindmap-viewer-scroll">
            <img
              src={imageUrl}
              alt={`${result.document.title} 高清思维导图`}
              style={{ width: `${zoom * 100}%` }}
            />
          </div>
        </div>
      )}
    </>
  );
}
