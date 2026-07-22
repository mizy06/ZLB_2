import {
  AlertCircle,
  Check,
  CheckCircle2,
  ChevronDown,
  CircleGauge,
  Download,
  FileStack,
  GitBranch,
  History,
  Link2,
  ListChecks,
  LoaderCircle,
  Network,
  Play,
  RotateCcw,
  Sparkles,
  TableProperties,
  Trash2,
  Upload,
  Workflow,
  X,
} from "lucide-react";
import {
  type DragEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import {
  checkModel,
  createJob,
  deleteJob,
  getHealth,
  getHistory,
  getJob,
  getModels,
  resolveReview,
} from "./api";
import { ChunkList } from "./components/ChunkList";
import { DataTable } from "./components/DataTable";
import { GraphCanvas } from "./components/GraphCanvas";
import { Inspector } from "./components/Inspector";
import { ReviewQueue } from "./components/ReviewQueue";
import { createSampleFile } from "./sample";
import type {
  AnalysisResult,
  Health,
  HistoryItem,
  Job,
  ModelProvider,
  ReviewResolution,
} from "./types";

type View = "graph" | "nodes" | "chunks" | "reviews";

const stageLabels: Record<string, string> = {
  queued: "等待",
  starting: "启动",
  model_check: "模型角色",
  parse: "文档解析",
  ledger: "内容账本",
  themes: "全局主题",
  branch_plan: "分支规划",
  branches: "分支团队",
  merge_audit: "合并审计",
  normalize: "候选归一",
  verify: "父边校验",
  solve: "拓扑求解",
  finalize: "版本写入",
  complete: "完成",
};

function historyTime(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [models, setModels] = useState<string[]>([]);
  const [provider] = useState<ModelProvider>("kimi");
  const [model, setModel] = useState("kimi-k3");
  const [mode, setMode] = useState<"standard" | "precision">("standard");
  const [modelStatus, setModelStatus] = useState<
    "idle" | "checking" | "available" | "denied"
  >("idle");
  const [modelMessage, setModelMessage] = useState("");
  const [useAi, setUseAi] = useState(true);
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [job, setJob] = useState<Job | null>(null);
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [view, setView] = useState<View>("graph");
  const [showCrossLinks, setShowCrossLinks] = useState(true);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [busyReviewId, setBusyReviewId] = useState<string | null>(null);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [historyBusyId, setHistoryBusyId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);

  const refreshHistory = useCallback(async () => {
    setHistoryLoading(true);
    try {
      setHistory(await getHistory());
    } finally {
      setHistoryLoading(false);
    }
  }, []);

  useEffect(() => {
    void getHealth()
      .then((data) => {
        setHealth(data);
        const defaultModel = data.providers.kimi.default_model;
        setModel(defaultModel);
        void getModels("kimi")
          .then(setModels)
          .catch(() => setModels([defaultModel]));
      })
      .catch((caught) => setError(caught.message));
    void refreshHistory().catch(() => undefined);
  }, [refreshHistory]);

  useEffect(() => {
    if (!job || job.status === "completed" || job.status === "failed") return;
    const timer = window.setInterval(() => {
      void getJob(job.id)
        .then((next) => {
          setJob(next);
          if (next.status === "completed" && next.result) {
            setResult(next.result);
            setSelectedNodeId(next.result.root_id);
            void refreshHistory();
          }
          if (next.status === "failed") setError(next.error || "任务执行失败");
        })
        .catch((caught) => setError(caught.message));
    }, 700);
    return () => window.clearInterval(timer);
  }, [job, refreshHistory]);

  useEffect(() => {
    if (!historyOpen) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setHistoryOpen(false);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [historyOpen]);

  const running = job?.status === "queued" || job?.status === "running";
  const workspaceLabel = health
    ? `${health.workspace.name} · ${health.architecture.name}`
    : "正在连接工作空间";

  const acceptFile = useCallback((next: File | undefined) => {
    if (!next) return;
    const allowed = [".pdf", ".pptx", ".docx", ".txt", ".md"];
    const suffix = next.name.slice(next.name.lastIndexOf(".")).toLowerCase();
    if (!allowed.includes(suffix)) {
      setError("请上传 PDF、PPTX、DOCX、TXT 或 MD 文件。");
      return;
    }
    setFile(next);
    setError("");
    setResult(null);
    setJob(null);
    setView("graph");
  }, []);

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    acceptFile(event.dataTransfer.files[0]);
  };

  const run = async () => {
    if (!file) return;
    setError("");
    setResult(null);
    setSelectedNodeId(null);
    setView("graph");
    try {
      const next = await createJob(file, provider, model, useAi, mode);
      setJob(next);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "提交任务失败");
    }
  };

  const verifyModel = async () => {
    setModelStatus("checking");
    setModelMessage("");
    try {
      const checked = await checkModel(provider, model);
      setModelStatus(checked.ok ? "available" : "denied");
      setModelMessage(checked.message);
    } catch (caught) {
      setModelStatus("denied");
      setModelMessage(caught instanceof Error ? caught.message : "检查失败");
    }
  };

  const handleReview = async (
    reviewId: string,
    resolution: ReviewResolution,
  ) => {
    if (!result) return;
    setBusyReviewId(reviewId);
    setError("");
    try {
      const updated = await resolveReview(result.task_id, reviewId, resolution);
      setResult(updated);
      setJob((current) =>
        current ? { ...current, result: updated } : current,
      );
      void refreshHistory().catch(() => undefined);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "复核操作失败");
    } finally {
      setBusyReviewId(null);
    }
  };

  const openHistoryItem = async (item: HistoryItem) => {
    setHistoryBusyId(item.task_id);
    setError("");
    try {
      const restored = await getJob(item.task_id);
      if (!restored.result) throw new Error("历史记录中没有可恢复的导图。");
      setJob(restored);
      setResult(restored.result);
      setMode(restored.result.mode);
      setSelectedNodeId(restored.result.root_id);
      setView("graph");
      setFile(null);
      setHistoryOpen(false);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "历史记录加载失败");
    } finally {
      setHistoryBusyId(null);
    }
  };

  const removeHistoryItem = async (item: HistoryItem) => {
    setHistoryBusyId(item.task_id);
    setError("");
    try {
      await deleteJob(item.task_id);
      setHistory((current) =>
        current.filter((entry) => entry.task_id !== item.task_id),
      );
      if (result?.task_id === item.task_id) {
        setResult(null);
        setJob(null);
        setSelectedNodeId(null);
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "历史记录删除失败");
    } finally {
      setHistoryBusyId(null);
    }
  };

  const modeLabel = useMemo(() => {
    if (!result) return "";
    if (result.extraction_mode === "kimi") return "Kimi K3 生成";
    if (result.extraction_mode === "mixed") return "模型与本地混合";
    return "本地确定性降级";
  }, [result]);

  const pendingReviews =
    result?.review_items.filter((item) => item.status === "pending").length || 0;

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">
            <Network size={20} />
          </span>
          <div>
            <strong>ZLB 思维导图 Agent</strong>
            <span>C+ 课程知识工作台</span>
          </div>
        </div>
        <div className="topbar-actions">
          <button
            type="button"
            className="history-toggle"
            onClick={() => setHistoryOpen(true)}
          >
            <History size={16} />
            <span>历史记录</span>
            {history.length > 0 && <b>{history.length}</b>}
          </button>
          <div className="workspace-status">
            <span
              className={`status-dot ${health?.workspace.key_configured ? "online" : ""}`}
            />
            <span>{workspaceLabel}</span>
          </div>
        </div>
      </header>

      <div className="workspace-layout">
        <aside className="control-panel">
          <div className="panel-heading">
            <span className="step-number">01</span>
            <div>
              <h2>导入课件</h2>
              <p>PDF · PPTX · DOCX · TXT · MD</p>
            </div>
          </div>

          <div
            className={`drop-zone ${dragging ? "dragging" : ""} ${file ? "has-file" : ""}`}
            onDragOver={(event) => {
              event.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={handleDrop}
            onClick={() => fileInput.current?.click()}
            role="button"
            tabIndex={0}
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === " ") {
                fileInput.current?.click();
              }
            }}
          >
            <input
              ref={fileInput}
              type="file"
              accept=".pdf,.pptx,.docx,.txt,.md"
              hidden
              onChange={(event) => acceptFile(event.target.files?.[0])}
            />
            {file ? (
              <>
                <FileStack size={25} />
                <strong>{file.name}</strong>
                <span>{(file.size / 1024).toFixed(1)} KB</span>
              </>
            ) : (
              <>
                <Upload size={25} />
                <strong>拖入或选择课件</strong>
                <span>最大 150 页或幻灯片</span>
              </>
            )}
          </div>
          <button
            type="button"
            className="sample-button"
            onClick={() => acceptFile(createSampleFile())}
          >
            <Sparkles size={15} />
            载入机器学习示例
          </button>

          <div className="divider" />

          <div className="panel-heading compact">
            <span className="step-number">02</span>
            <div>
              <h2>运行配置</h2>
              <p>生成与校验角色独立调度</p>
            </div>
          </div>

          <label className="field-label">运行档位</label>
          <div className="mode-control" aria-label="运行档位">
            <button
              type="button"
              className={mode === "standard" ? "active" : ""}
              onClick={() => setMode("standard")}
              title="单校验器与全局拓扑求解"
            >
              标准档
            </button>
            <button
              type="button"
              className={mode === "precision" ? "active" : ""}
              onClick={() => setMode("precision")}
              title="高风险项双校验并按需仲裁"
            >
              高精档
            </button>
          </div>

          <label className="field-label" htmlFor="model-select">
            生成模型服务
          </label>
          <div className="provider-control" aria-label="模型服务商">
            <button
              type="button"
              className="active"
              onClick={() => {
                setModel(health?.providers.kimi.default_model || "kimi-k3");
                setModelStatus("idle");
                void getModels("kimi")
                  .then(setModels)
                  .catch(() => setModels(["kimi-k3"]));
              }}
            >
              Kimi
            </button>
          </div>
          <label className="field-label model-label" htmlFor="model-select">
            模型
          </label>
          <div className="select-wrap">
            <select
              id="model-select"
              value={model}
              onChange={(event) => {
                setModel(event.target.value);
                setModelStatus("idle");
              }}
            >
              {!models.includes(model) && <option value={model}>{model}</option>}
              {models.map((item) => (
                <option value={item} key={item}>
                  {item}
                </option>
              ))}
            </select>
            <ChevronDown size={15} />
          </div>

          <button
            type="button"
            className={`model-check ${modelStatus}`}
            onClick={verifyModel}
            disabled={modelStatus === "checking"}
          >
            {modelStatus === "checking" ? (
              <LoaderCircle className="spin" size={15} />
            ) : modelStatus === "available" ? (
              <Check size={15} />
            ) : modelStatus === "denied" ? (
              <AlertCircle size={15} />
            ) : (
              <CircleGauge size={15} />
            )}
            {modelStatus === "idle"
              ? "检查生成模型"
              : modelStatus === "checking"
                ? "正在检查"
                : modelMessage}
          </button>

          <label className="toggle-row">
            <span>
              <strong>启用模型 Agent</strong>
              <small>失败阶段自动切换确定性实现</small>
            </span>
            <input
              type="checkbox"
              checked={useAi}
              onChange={(event) => setUseAi(event.target.checked)}
            />
            <i />
          </label>

          <button
            type="button"
            className="run-button"
            onClick={run}
            disabled={!file || running}
          >
            {running ? (
              <LoaderCircle className="spin" size={18} />
            ) : (
              <Play size={18} fill="currentColor" />
            )}
            {running ? "正在构建思维导图" : "开始构建"}
          </button>

          {running && job && (
            <div className="progress-box" aria-live="polite">
              <div className="progress-meta">
                <span>{stageLabels[job.stage] || job.stage}</span>
                <strong>{job.progress}%</strong>
              </div>
              <div className="progress-track">
                <span style={{ width: `${job.progress}%` }} />
              </div>
              <p>{job.message}</p>
            </div>
          )}

          {error && (
            <div className="error-box" role="alert">
              <AlertCircle size={16} />
              <span>{error}</span>
            </div>
          )}
        </aside>

        <main className="main-workspace">
          {result ? (
            <>
              <div className="result-header">
                <div>
                  <span className="eyebrow">
                    {result.document.file_type.toUpperCase()} · {modeLabel} · v
                    {result.graph_version}
                  </span>
                  <h1>{result.document.title}</h1>
                </div>
                <div className="result-stats">
                  <div>
                    <strong>{result.quality_report.node_count}</strong>
                    <span>节点</span>
                  </div>
                  <div>
                    <strong>{result.quality_report.tree_edge_count}</strong>
                    <span>主树边</span>
                  </div>
                  <div>
                    <strong>
                      {Math.round(
                        result.quality_report.weighted_content_coverage * 100,
                      )}
                      %
                    </strong>
                    <span>内容覆盖</span>
                  </div>
                  <div className={pendingReviews > 0 ? "attention" : ""}>
                    <strong>{pendingReviews}</strong>
                    <span>待复核</span>
                  </div>
                </div>
              </div>

              <div
                className={`quality-strip ${
                  result.quality_report.quality_gate_passed ? "passed" : "review"
                }`}
              >
                {result.quality_report.quality_gate_passed ? (
                  <CheckCircle2 size={16} />
                ) : (
                  <AlertCircle size={16} />
                )}
                <span>
                  {result.quality_report.quality_gate_passed
                    ? "质量门通过"
                    : "主树合法，仍有质量项需要复核"}
                </span>
                <b>{result.solver_status}</b>
              </div>

              {(result.warnings.length > 0 ||
                result.quality_report.warnings.length > 0) && (
                <div className="warning-strip">
                  <AlertCircle size={16} />
                  <span>
                    {[
                      ...new Set([
                        ...result.warnings,
                        ...result.quality_report.warnings,
                      ]),
                    ].join(" ")}
                  </span>
                </div>
              )}

              <div className="view-tabs" role="tablist">
                <button
                  type="button"
                  className={view === "graph" ? "active" : ""}
                  onClick={() => setView("graph")}
                >
                  <GitBranch size={16} /> 主树
                </button>
                <button
                  type="button"
                  className={view === "nodes" ? "active" : ""}
                  onClick={() => setView("nodes")}
                >
                  <TableProperties size={16} /> 节点
                </button>
                <button
                  type="button"
                  className={view === "chunks" ? "active" : ""}
                  onClick={() => setView("chunks")}
                >
                  <FileStack size={16} /> 内容单元
                </button>
                <button
                  type="button"
                  className={view === "reviews" ? "active" : ""}
                  onClick={() => setView("reviews")}
                >
                  <ListChecks size={16} /> 复核
                  {pendingReviews > 0 && <span className="tab-count">{pendingReviews}</span>}
                </button>
                {view === "graph" && result.cross_links.length > 0 && (
                  <button
                    type="button"
                    className={`cross-toggle ${showCrossLinks ? "active" : ""}`}
                    onClick={() => setShowCrossLinks((current) => !current)}
                    title="显示或隐藏跨链"
                  >
                    <Link2 size={15} />
                    跨链
                  </button>
                )}
                <a
                  className="save-action"
                  href={`/api/jobs/${result.task_id}/export.json`}
                  download
                  title="保存完整 JSON"
                >
                  <Download size={15} />
                  <span>保存 JSON</span>
                </a>
                <button
                  type="button"
                  className="reset-action"
                  aria-label="新建任务"
                  title="新建任务"
                  onClick={() => {
                    setResult(null);
                    setJob(null);
                    setSelectedNodeId(null);
                    setView("graph");
                  }}
                >
                  <RotateCcw size={15} />
                  <span>新建任务</span>
                </button>
              </div>

              <div
                className={`result-body ${view} ${
                  result.warnings.length > 0 ||
                  result.quality_report.warnings.length > 0
                    ? "has-warning"
                    : ""
                }`}
              >
                {view === "graph" && (
                  <>
                    <GraphCanvas
                      result={result}
                      selectedNodeId={selectedNodeId}
                      showCrossLinks={showCrossLinks}
                      onSelectNode={setSelectedNodeId}
                    />
                    <Inspector
                      result={result}
                      nodeId={selectedNodeId}
                      onClose={() => setSelectedNodeId(null)}
                    />
                  </>
                )}
                {view === "nodes" && (
                  <DataTable
                    result={result}
                    onSelectNode={(id) => {
                      setSelectedNodeId(id);
                      setView("graph");
                    }}
                  />
                )}
                {view === "chunks" && <ChunkList chunks={result.chunks} />}
                {view === "reviews" && (
                  <ReviewQueue
                    result={result}
                    busyReviewId={busyReviewId}
                    onResolve={(reviewId, resolution) =>
                      void handleReview(reviewId, resolution)
                    }
                    onSelectNode={(id) => {
                      setSelectedNodeId(id);
                      setView("graph");
                    }}
                  />
                )}
              </div>
            </>
          ) : (
            <div className="empty-workspace">
              <div className="empty-state-icon">
                <Workflow size={34} />
              </div>
              <span className="eyebrow">C+ Supervisor ready</span>
              <h1>{running ? "正在组织分支团队" : "等待课程材料"}</h1>
              <p>{running ? job?.message : "选择左侧课件后开始构建。"}</p>
            </div>
          )}
        </main>
      </div>
      {historyOpen && (
        <div
          className="history-overlay"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setHistoryOpen(false);
          }}
        >
          <aside
            className="history-drawer"
            role="dialog"
            aria-modal="true"
            aria-label="历史记录"
          >
            <header>
              <div>
                <span className="eyebrow">SQLite history</span>
                <h2>历史记录</h2>
              </div>
              <button
                type="button"
                title="关闭"
                aria-label="关闭历史记录"
                onClick={() => setHistoryOpen(false)}
              >
                <X size={18} />
              </button>
            </header>
            {historyLoading ? (
              <div className="history-state">
                <LoaderCircle className="spin" size={20} />
                <span>正在读取历史记录</span>
              </div>
            ) : history.length === 0 ? (
              <div className="history-state">
                <History size={23} />
                <strong>还没有历史记录</strong>
                <span>完成一次思维导图构建后会自动保存在这里。</span>
              </div>
            ) : (
              <div className="history-list">
                {history.map((item) => (
                  <div className="history-item" key={item.task_id}>
                    <button
                      type="button"
                      className="history-open"
                      disabled={historyBusyId === item.task_id}
                      onClick={() => void openHistoryItem(item)}
                    >
                      <div>
                        <strong>{item.title}</strong>
                        <time dateTime={item.updated_at}>
                          {historyTime(item.updated_at)}
                        </time>
                      </div>
                      <p>{item.filename}</p>
                      <span>
                        {item.file_type.toUpperCase()} · {item.node_count} 节点 ·
                        v{item.graph_version}
                      </span>
                    </button>
                    <button
                      type="button"
                      className="history-delete"
                      title="删除历史记录"
                      aria-label={`删除 ${item.title}`}
                      disabled={historyBusyId === item.task_id}
                      onClick={() => void removeHistoryItem(item)}
                    >
                      {historyBusyId === item.task_id ? (
                        <LoaderCircle className="spin" size={15} />
                      ) : (
                        <Trash2 size={15} />
                      )}
                    </button>
                  </div>
                ))}
              </div>
            )}
          </aside>
        </div>
      )}
    </div>
  );
}

export default App;
