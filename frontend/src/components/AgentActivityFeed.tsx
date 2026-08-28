import {
  AlertCircle,
  Check,
  ChevronRight,
  CircleSlash2,
  LoaderCircle,
  Radio,
  Square,
} from "lucide-react";
import { useMemo, useState } from "react";

import type { LiveModelCall, LiveStageStep } from "../jobStream";
import type { Job } from "../types";

type ActionStatus = "running" | "completed" | "failed" | "cancelled";

export type StreamConnectionState =
  | "idle"
  | "connecting"
  | "live"
  | "reconnecting"
  | "closed";

type ActionItem = {
  id: string;
  title: string;
  summary: string;
  detail: string;
  meta: string;
  status: ActionStatus;
  startedAt: string;
};

const stageLabels: Record<string, string> = {
  queued: "等待任务",
  starting: "启动 Agent",
  model_check: "检查模型",
  render: "渲染幻灯片",
  render_cache: "读取渲染缓存",
  encode: "编码图片",
  upload: "准备图片上下文",
  editorial_draft: "生成初稿",
  editorial_review: "执行并行审阅",
  editorial_revision: "修订结构",
  parse: "解析课程材料",
  ledger: "建立内容账本",
  themes: "提炼全局主题",
  branch_plan: "规划知识分支",
  branches: "构建分支子图",
  merge_audit: "合并并审计覆盖",
  normalize: "归一化候选节点",
  verify: "校验父子关系",
  solve: "求解主树拓扑",
  finalize: "生成最终图版本",
  complete: "完成",
};

const roleLabels: Record<string, string> = {
  global_editor: "主编 Agent",
  global_editor_draft: "主编 Agent",
  content_omission: "内容覆盖 Agent",
  pruning: "结构精简 Agent",
  multilevel_structure: "层级结构 Agent",
};

const connectionLabels: Record<StreamConnectionState, string> = {
  idle: "等待",
  connecting: "连接中",
  live: "实时",
  reconnecting: "重连中",
  closed: "已结束",
};

function labelRole(role: string): string {
  const match = Object.entries(roleLabels).find(([prefix]) =>
    role.startsWith(prefix),
  );
  return match?.[1] || role || "模型调用";
}

function ActionStatusIcon({ status }: { status: ActionStatus }) {
  if (status === "running") {
    return <LoaderCircle className="spin" size={14} />;
  }
  if (status === "completed") {
    return <Check size={14} />;
  }
  if (status === "cancelled") {
    return <CircleSlash2 size={14} />;
  }
  return <AlertCircle size={14} />;
}

function ActionRow({ action }: { action: ActionItem }) {
  const [expanded, setExpanded] = useState(false);
  const hasDetail = Boolean(action.detail);

  return (
    <div className={`agent-action-row ${action.status}`}>
      <button
        type="button"
        className="agent-action-trigger"
        onClick={() => hasDetail && setExpanded((current) => !current)}
        aria-expanded={hasDetail ? expanded : undefined}
      >
        <span className="agent-action-status">
          <ActionStatusIcon status={action.status} />
        </span>
        <span className="agent-action-copy">
          <strong>{action.title}</strong>
          <span>{action.summary}</span>
        </span>
        <code>{action.meta}</code>
        {hasDetail && (
          <ChevronRight
            className={expanded ? "expanded" : ""}
            size={14}
          />
        )}
      </button>
      {expanded && hasDetail && (
        <div className="agent-action-detail">
          <pre>{action.detail}</pre>
        </div>
      )}
    </div>
  );
}

function stageAction(step: LiveStageStep): ActionItem {
  return {
    id: step.id,
    title: stageLabels[step.stage] || step.stage,
    summary: step.message || "Agent 正在处理",
    detail: step.message,
    meta:
      step.progress === null || step.progress === undefined
        ? "pipeline"
        : `${step.progress}%`,
    status: step.status,
    startedAt: step.startedAt,
  };
}

function modelAction(call: LiveModelCall): ActionItem {
  return {
    id: `model:${call.callId}`,
    title: labelRole(call.role),
    summary:
      call.status === "running"
        ? "正在生成"
        : call.status === "completed"
          ? "生成完成"
          : call.message || "调用失败",
    detail: call.output || call.message,
    meta:
      call.roundNumber > 0
        ? `第 ${call.roundNumber} 轮 · ${call.model}`
        : call.model,
    status: call.status,
    startedAt: call.startedAt,
  };
}

export function AgentActivityFeed({
  job,
  calls,
  steps,
  connectionState,
  onCancel,
}: {
  job: Job;
  calls: LiveModelCall[];
  steps: LiveStageStep[];
  connectionState: StreamConnectionState;
  onCancel?: () => void;
}) {
  const actions = useMemo(() => {
    const merged = [...steps.map(stageAction), ...calls.map(modelAction)];
    if (merged.length === 0) {
      merged.push({
        id: `current:${job.stage}`,
        title: stageLabels[job.stage] || job.stage,
        summary: job.message,
        detail: job.message,
        meta: `${job.progress}%`,
        status:
          job.status === "failed"
            ? "failed"
            : job.status === "cancelled"
              ? "cancelled"
              : job.status === "completed"
                ? "completed"
                : "running",
        startedAt: "",
      });
    }
    return merged.sort((left, right) =>
      left.startedAt.localeCompare(right.startedAt),
    );
  }, [calls, job, steps]);

  const completed = actions.filter(
    (action) => action.status === "completed",
  ).length;

  return (
    <section className="agent-activity" aria-label="Agent 实时动作">
      <header className="agent-activity-header">
        <div>
          <span className={`activity-connection ${connectionState}`}>
            <Radio size={12} />
            {connectionLabels[connectionState]}
          </span>
          <strong>
            {job.status === "completed"
              ? "Agent 已完成思维导图"
              : job.status === "failed"
                ? "Agent 运行失败"
                : job.status === "cancelled"
                  ? "Agent 已停止"
                  : "Agent 正在构建思维导图"}
          </strong>
          <span>{job.message}</span>
        </div>
        <div className="agent-activity-progress">
          <span>
            {completed}/{actions.length}
          </span>
          <strong>{job.progress}%</strong>
        </div>
      </header>
      <div className="agent-activity-track">
        <span style={{ width: `${job.progress}%` }} />
      </div>
      <div className="agent-action-list">
        {actions.map((action) => (
          <ActionRow action={action} key={action.id} />
        ))}
      </div>
      {onCancel && (job.status === "queued" || job.status === "running") && (
        <button type="button" className="activity-cancel" onClick={onCancel}>
          <Square size={12} fill="currentColor" />
          停止运行
        </button>
      )}
    </section>
  );
}
