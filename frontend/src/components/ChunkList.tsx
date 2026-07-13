import { FileText } from "lucide-react";

import type { Chunk } from "../types";

export function ChunkList({ chunks }: { chunks: Chunk[] }) {
  return (
    <div className="chunk-list">
      {chunks.map((chunk) => (
        <article key={chunk.id} className="chunk-item">
          <header>
            <div>
              <FileText size={15} />
              <strong>Chunk {chunk.index + 1}</strong>
            </div>
            <span>
              {chunk.slide_start
                ? `幻灯片 ${chunk.slide_start}${chunk.slide_end !== chunk.slide_start ? `–${chunk.slide_end}` : ""}`
                : chunk.page_start
                  ? `页面 ${chunk.page_start}${chunk.page_end !== chunk.page_start ? `–${chunk.page_end}` : ""}`
                  : `${chunk.text.length} 字`}
            </span>
          </header>
          {chunk.heading && <h4>{chunk.heading}</h4>}
          <p>{chunk.text}</p>
        </article>
      ))}
    </div>
  );
}
