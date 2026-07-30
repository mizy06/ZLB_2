import {
  Check,
  GitPullRequestArrow,
  LoaderCircle,
  ShieldAlert,
  Trash2,
} from "lucide-react";
import { useMemo, useState } from "react";

import { reviewSupportsAction } from "../reviewActions";
import type { AnalysisResult, ReviewResolution } from "../types";

type ReviewQueueProps = {
  result: AnalysisResult;
  busyReviewId: string | null;
  onResolve: (reviewId: string, resolution: ReviewResolution) => void;
  onSelectNode: (nodeId: string) => void;
};

const typeLabels: Record<string, string> = {
  root_choice: "根主题",
  abstract_parent: "抽象父节点",
  competing_parent: "父节点竞争",
  cross_link: "跨链",
  uncovered_content: "未覆盖内容",
};

export function ReviewQueue({
  result,
  busyReviewId,
  onResolve,
  onSelectNode,
}: ReviewQueueProps) {
  const pending = result.review_items.filter((item) => item.status === "pending");
  const nodeNames = useMemo(
    () => new Map(result.nodes.map((node) => [node.id, node.name])),
    [result.nodes],
  );
  const [selectedParents, setSelectedParents] = useState<Record<string, string>>({});
  const [renameLabels, setRenameLabels] = useState<Record<string, string>>({});

  if (pending.length === 0) {
    return (
      <div className="review-empty">
        <Check size={24} />
        <h3>没有待处理项</h3>
        <p>当前图版本的高风险决策已处理完毕。</p>
      </div>
    );
  }

  return (
    <div className="review-view">
      <header>
        <div>
          <span className="eyebrow">Human in the loop</span>
          <h2>待复核决策</h2>
        </div>
        <strong>{pending.length}</strong>
      </header>
      <div className="review-list">
        {pending.map((review) => {
          const subjects = review.subject_ids
            .map((id) => ({ id, name: nodeNames.get(id) }))
            .filter((item) => item.name);
          const parentOptions = review.alternatives
            .map((item) => ({
              id: String(item.parent_id || ""),
              score: Number(item.score || 0),
            }))
            .filter((item) => item.id && nodeNames.has(item.id));
          const selectedParent =
            selectedParents[review.id] || parentOptions[0]?.id || "";
          const subjectId =
            review.subject_id || subjects[0]?.id || "";
          const renameLabel = renameLabels[review.id] || "";
          const busy = busyReviewId === review.id;

          return (
            <article key={review.id} className="review-item">
              <div className="review-title">
                <span>{typeLabels[review.type] || review.type}</span>
                <strong>风险 {Math.round(review.risk_score * 100)}%</strong>
              </div>
              <p>{review.reason}</p>
              <div className="review-subjects">
                {subjects.map((subject) => (
                  <button
                    type="button"
                    key={subject.id}
                    onClick={() => onSelectNode(subject.id)}
                  >
                    {subject.name}
                  </button>
                ))}
              </div>

              {review.type === "competing_parent" && parentOptions.length > 0 && (
                <label className="review-parent-field">
                  <span>直接父节点</span>
                  <select
                    value={selectedParent}
                    onChange={(event) =>
                      setSelectedParents((current) => ({
                        ...current,
                        [review.id]: event.target.value,
                      }))
                    }
                  >
                    {parentOptions.map((option) => (
                      <option key={option.id} value={option.id}>
                        {nodeNames.get(option.id)} · {Math.round(option.score * 100)}%
                      </option>
                    ))}
                  </select>
                </label>
              )}

              {subjectId && reviewSupportsAction(review.type, "rename") && (
                <label className="review-parent-field">
                  <span>修正节点名称</span>
                  <input
                    value={renameLabel}
                    placeholder={nodeNames.get(subjectId) || "新名称"}
                    onChange={(event) =>
                      setRenameLabels((current) => ({
                        ...current,
                        [review.id]: event.target.value,
                      }))
                    }
                  />
                </label>
              )}

              {review.model_votes.length > 0 && (
                <div className="review-votes">
                  {review.model_votes.map((vote, index) => (
                    <span key={`${vote.actor}-${index}`}>
                      {vote.actor}: {vote.classification} {Math.round(vote.score * 100)}%
                    </span>
                  ))}
                </div>
              )}

              <div className="review-actions">
                <button
                  type="button"
                  className="primary"
                  disabled={busy}
                  onClick={() => onResolve(review.id, { action: "keep" })}
                >
                  {busy ? <LoaderCircle className="spin" size={15} /> : <Check size={15} />}
                  保留
                </button>
                {reviewSupportsAction(review.type, "change_parent") &&
                  selectedParent && (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() =>
                      onResolve(review.id, {
                        action: "change_parent",
                        parent_id: selectedParent,
                      })
                    }
                  >
                    <GitPullRequestArrow size={15} />
                    改父
                  </button>
                )}
                {reviewSupportsAction(review.type, "rename") &&
                  renameLabel.trim() && (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() =>
                      onResolve(review.id, {
                        action: "rename",
                        label: renameLabel.trim(),
                      })
                    }
                  >
                    修正名称
                  </button>
                )}
                {reviewSupportsAction(review.type, "delete") && (
                  <button
                    type="button"
                    className="danger"
                    disabled={busy}
                    onClick={() => onResolve(review.id, { action: "delete" })}
                  >
                    <Trash2 size={15} />
                    删除
                  </button>
                )}
                {reviewSupportsAction(review.type, "accept_root") && (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() =>
                      onResolve(review.id, {
                        action: "accept_root",
                        parent_id: result.root_id,
                      })
                    }
                  >
                    确认当前根主题
                  </button>
                )}
              </div>
              {review.evidence_unit_ids.length === 0 && (
                <div className="review-warning">
                  <ShieldAlert size={14} />
                  缺少直接证据定位
                </div>
              )}
            </article>
          );
        })}
      </div>
    </div>
  );
}
