import {
  AlertCircle,
  CheckCircle2,
  LoaderCircle,
  Radio,
  SquareTerminal,
} from "lucide-react";

import type { LiveModelCall } from "../jobStream";
import type { Job } from "../types";

export type StreamConnectionState =
  | "idle"
  | "connecting"
  | "live"
  | "reconnecting"
  | "closed";

const roleLabel = (role: string) => {
  if (role.startsWith("global_editor_draft")) return "起稿主编";
  if (role.startsWith("global_editor")) return "主编";
  if (role.startsWith("content_omission")) return "内容遗漏";
  if (role.startsWith("pruning")) return "剪枝";
  if (role.startsWith("multilevel_structure")) return "多级结构";
  return role;
};

const connectionLabel: Record<StreamConnectionState, string> = {
  idle: "等待任务",
  connecting: "正在连接",
  live: "实时连接",
  reconnecting: "正在重连",
  closed: "输出已结束",
};

export function LiveRunPanel({
  job,
  calls,
  connectionState,
}: {
  job: Job;
  calls: LiveModelCall[];
  connectionState: StreamConnectionState;
}) {
  const activeCalls = calls.filter((call) => call.status === "running").length;
  return (
    <div className="live-run">
      <header className="live-run-header">
        <div>
          <span className="eyebrow">Live model output</span>
          <h1>运行输出</h1>
          <p>{job.message}</p>
        </div>
        <div className="live-run-summary">
          <span className={`stream-connection ${connectionState}`}>
            <Radio size={13} />
            {connectionLabel[connectionState]}
          </span>
          <strong>{job.progress}%</strong>
        </div>
      </header>

      <div className="live-progress-track">
        <span style={{ width: `${job.progress}%` }} />
      </div>

      {calls.length === 0 ? (
        <div className="live-run-waiting">
          <LoaderCircle className="spin" size={22} />
          <strong>{job.stage === "queued" ? "等待执行" : "正在准备模型上下文"}</strong>
          <span>{job.message}</span>
        </div>
      ) : (
        <div className="live-call-list">
          <div className="live-call-list-meta">
            <span>{calls.length} 个角色调用</span>
            <span>{activeCalls > 0 ? `${activeCalls} 个生成中` : "当前无生成中角色"}</span>
          </div>
          {calls.map((call) => (
            <article
              className={`live-call ${call.status}`}
              key={call.callId}
            >
              <header>
                <div className="live-call-title">
                  <span className="live-call-status">
                    {call.status === "running" ? (
                      <LoaderCircle className="spin" size={14} />
                    ) : call.status === "completed" ? (
                      <CheckCircle2 size={14} />
                    ) : (
                      <AlertCircle size={14} />
                    )}
                  </span>
                  <div>
                    <strong>{roleLabel(call.role)}</strong>
                    <span>
                      {call.roundNumber === 0
                        ? "起稿"
                        : `第 ${call.roundNumber} 轮`}
                    </span>
                  </div>
                </div>
                <code>{call.model}</code>
              </header>
              <div className="live-output">
                <SquareTerminal size={14} />
                <pre>
                  {call.output ||
                    (call.status === "failed"
                      ? call.message || "模型调用失败"
                      : "等待模型首个输出增量...")}
                </pre>
              </div>
              {call.status === "failed" && call.message && (
                <p className="live-call-error">{call.message}</p>
              )}
            </article>
          ))}
        </div>
      )}
    </div>
  );
}
