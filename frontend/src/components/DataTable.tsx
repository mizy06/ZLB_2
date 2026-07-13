import { Search } from "lucide-react";
import { useMemo, useState } from "react";

import type { AnalysisResult } from "../types";

type DataTableProps = {
  result: AnalysisResult;
  onSelectNode: (id: string) => void;
};

export function DataTable({ result, onSelectNode }: DataTableProps) {
  const [query, setQuery] = useState("");
  const rows = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) return result.nodes;
    return result.nodes.filter(
      (node) =>
        node.name.toLowerCase().includes(normalized) ||
        node.definition.toLowerCase().includes(normalized) ||
        node.type.toLowerCase().includes(normalized),
    );
  }, [query, result.nodes]);

  return (
    <div className="table-view">
      <label className="search-field">
        <Search size={16} />
        <span className="sr-only">搜索节点</span>
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="搜索名称、类型或定义"
        />
      </label>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>知识点</th>
              <th>类型</th>
              <th>定义</th>
              <th>证据</th>
              <th>置信度</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((node) => (
              <tr key={node.id} onClick={() => onSelectNode(node.id)}>
                <td>
                  <strong>{node.name}</strong>
                </td>
                <td>
                  <span className="type-label">{node.type}</span>
                </td>
                <td>{node.definition || "未检出明确定义"}</td>
                <td>{node.evidence.length}</td>
                <td>{Math.round(node.confidence * 100)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
