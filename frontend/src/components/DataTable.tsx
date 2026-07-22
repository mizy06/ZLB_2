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
        node.role.toLowerCase().includes(normalized) ||
        node.origin.toLowerCase().includes(normalized),
    );
  }, [query, result.nodes]);

  const parentNames = new Map(result.nodes.map((node) => [node.id, node.name]));

  return (
    <div className="table-view">
      <label className="search-field">
        <Search size={16} />
        <span className="sr-only">搜索节点</span>
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="搜索名称、角色、来源或定义"
        />
      </label>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>节点</th>
              <th>角色</th>
              <th>父节点</th>
              <th>深度</th>
              <th>证据</th>
              <th>风险</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((node) => (
              <tr key={node.id} onClick={() => onSelectNode(node.id)}>
                <td>
                  <strong>{node.name}</strong>
                  <small>{node.definition || "未检出明确定义"}</small>
                </td>
                <td>
                  <span className="type-label">{node.role}</span>
                </td>
                <td>{node.parent_id ? parentNames.get(node.parent_id) : "根节点"}</td>
                <td>{node.depth}</td>
                <td>{node.evidence.length + node.support_unit_ids.length}</td>
                <td>
                  <span className={node.risk_score > 0 ? "risk-value" : ""}>
                    {Math.round(node.risk_score * 100)}%
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
