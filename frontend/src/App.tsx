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
  Images,
  Link2,
  LoaderCircle,
  Menu,
  Network,
  Paperclip,
  PanelRightClose,
  Play,
  Plus,
  RotateCcw,
  Search,
  Send,
  Settings2,
  Square,
  SquareTerminal,
  Sparkles,
  TableProperties,
  Trash2,
  Upload,
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
  cancelJob,
  checkModel,
  createJob,
  deleteJob,
  getHealth,
  getHistory,
  getJob,
  getModels,
  jobEventsUrl,
} from "./api";
import {
  AgentActivityFeed,
  type StreamConnectionState,
} from "./components/AgentActivityFeed";
import { ChunkList } from "./components/ChunkList";
import { DataTable } from "./components/DataTable";
import { GraphCanvas } from "./components/GraphCanvas";
import { Inspector } from "./components/Inspector";
import { LoopBuilder } from "./components/LoopBuilder";
import { MindmapAttachment } from "./components/MindmapAttachment";
import { VisualGallery } from "./components/VisualGallery";
import {
  canAdoptRestoredJob,
  canReplaceActiveJob,
  canStartJobSubmission,
  nextPollDelay,
  qualityPresentation,
  shouldContinuePolling,
} from "./jobLifecycle";
import {
  emptyJobStreamState,
  mergeJobEvents,
} from "./jobStream";
import {
  createExampleLoop,
  normalizeLoopConfig,
  selectedLoopModels,
} from "./loopConfig";
import { createSampleFile } from "./sample";
import type {
  AnalysisResult,
  Health,
  HistoryItem,
  Job,
  JobEvent,
  MindMapLoopConfig,
  ModelProvider,
} from "./types";

type View = "graph" | "visuals" | "nodes" | "chunks" | "stream";
const ACTIVE_TASK_KEY = "zlb-mindmap-active-task";
const PRODUCT_NAME = "Agent";
const PRODUCT_DESCRIPTION = "Mindmap workspace";

const stageLabels: Record<string, string> = {
  queued: "等待",
  starting: "启动",
  context_preparing: "上下文准备",
  agent_started: "Agent 启动",
  model_check: "模型角色",
  render: "幻灯片渲染",
  render_cache: "渲染缓存",
  encode: "图片编码",
  upload: "图片上下文",
  editorial_draft: "主编起稿",
  editorial_review: "并行审稿",
  editorial_revision: "主编修订",
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
  const [provider] = useState<ModelProvider>("qwen");
  const [loopExample, setLoopExample] = useState<MindMapLoopConfig>(
    createExampleLoop("qwen3.8-max-preview"),
  );
  const [loopConfig, setLoopConfig] = useState<MindMapLoopConfig>(
    createExampleLoop("qwen3.8-max-preview"),
  );
  const [modelStatus, setModelStatus] = useState<
    "idle" | "checking" | "available" | "denied"
  >("idle");
  const [modelMessage, setModelMessage] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [job, setJob] = useState<Job | null>(null);
  const currentJobIdRef = useRef<string | null>(null);
  const submittingRef = useRef(false);
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [view, setView] = useState<View>("graph");
  const [showCrossLinks, setShowCrossLinks] = useState(true);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [historyOpen, setHistoryOpen] = useState(() =>
    window.matchMedia("(min-width: 901px)").matches,
  );
  const [historyQuery, setHistoryQuery] = useState("");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [artifactOpen, setArtifactOpen] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [historyBusyId, setHistoryBusyId] = useState<string | null>(null);
  const [workspaceReady, setWorkspaceReady] = useState(false);
  const [streamState, setStreamState] = useState(emptyJobStreamState);
  const [streamConnection, setStreamConnection] =
    useState<StreamConnectionState>("idle");
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
    let disposed = false;
    void (async () => {
      try {
        const data = await getHealth();
        if (disposed) return;
        setHealth(data);
        const defaultModel = data.providers.qwen.default_model;
        const example = normalizeLoopConfig(
          data.architecture.loop?.example,
          defaultModel,
        );
        setLoopExample(example);
        setLoopConfig(example);
        try {
          const available = await getModels("qwen");
          if (disposed) return;
          setModels(available);
        } catch (caught) {
          if (disposed) return;
          setModels([defaultModel]);
          setError(caught instanceof Error ? caught.message : "模型列表加载失败");
        } finally {
          if (!disposed) setWorkspaceReady(true);
        }
      } catch (caught) {
        if (!disposed) {
          setError(caught instanceof Error ? caught.message : "健康检查失败");
        }
      }
    })();
    return () => {
      disposed = true;
    };
  }, []);

  useEffect(() => {
    if (!workspaceReady) return;
    let disposed = false;
    void refreshHistory().catch(() => undefined);
    const activeTaskId = window.localStorage.getItem(ACTIVE_TASK_KEY);
    if (!activeTaskId) return;
    void getJob(activeTaskId)
      .then((restored) => {
        if (
          disposed
          || !canAdoptRestoredJob(
            activeTaskId,
            currentJobIdRef.current,
          )
        ) {
          return;
        }
        currentJobIdRef.current = restored.id;
        setJob(restored);
        if (restored.loop_config) {
          setLoopConfig(
            normalizeLoopConfig(
              restored.loop_config,
              restored.loop_config.rounds[0]?.editor_model ||
                "qwen3.8-max-preview",
            ),
          );
        }
        if (restored.result) {
          setResult(restored.result);
          setSelectedNodeId(restored.result.root_id);
        } else if (shouldContinuePolling(restored.status)) {
          setView("stream");
        }
      })
      .catch(() => {
        if (
          !disposed
          && window.localStorage.getItem(ACTIVE_TASK_KEY) === activeTaskId
        ) {
          window.localStorage.removeItem(ACTIVE_TASK_KEY);
        }
      });
    return () => {
      disposed = true;
    };
  }, [workspaceReady, refreshHistory]);

  useEffect(() => {
    currentJobIdRef.current = job?.id ?? null;
  }, [job?.id]);

  useEffect(() => {
    setStreamState(emptyJobStreamState());
    setStreamConnection(job ? "connecting" : "idle");
  }, [job?.id]);

  useEffect(() => {
    if (!job || !shouldContinuePolling(job.status) || !workspaceReady) {
      if (job && !shouldContinuePolling(job.status)) {
        setStreamConnection("closed");
      }
      return;
    }
    const taskId = job.id;
    let disposed = false;
    let flushTimer: number | undefined;
    let terminalHandled = false;
    let pending: JobEvent[] = [];
    const source = new EventSource(jobEventsUrl(taskId));
    setStreamConnection("connecting");

    const refreshTerminalJob = () => {
      if (terminalHandled) return;
      terminalHandled = true;
      void getJob(taskId)
        .then((next) => {
          if (disposed || currentJobIdRef.current !== taskId) return;
          setJob(next);
          if (next.status === "completed" && next.result) {
            setResult(next.result);
            setSelectedNodeId(next.result.root_id);
            void refreshHistory();
          } else if (next.status === "failed") {
            setError(next.error || "任务执行失败");
          } else if (next.status === "cancelled") {
            setError("任务已取消，源文件仍保留在服务端。");
          }
        })
        .catch((caught) => {
          if (!disposed) {
            setError(
              caught instanceof Error ? caught.message : "任务状态读取失败",
            );
          }
        });
    };

    const flush = () => {
      if (pending.length === 0) return;
      const batch = pending;
      pending = [];
      flushTimer = undefined;
      setStreamState((current) => mergeJobEvents(current, batch));
      const statusEvent = [...batch]
        .reverse()
        .find((event) =>
          event.kind === "status"
          || event.kind === "agent_started"
          || event.kind === "context_preparing");
      if (statusEvent) {
        setJob((current) =>
          current?.id === taskId
            ? {
                ...current,
                stage: statusEvent.stage || current.stage,
                progress: Math.max(
                  current.progress,
                  statusEvent.progress ?? current.progress,
                ),
                message: statusEvent.message || current.message,
              }
            : current,
        );
      }
      if (
        batch.some((event) =>
          ["job_complete", "job_failed", "job_cancelled"].includes(
            event.kind,
          ),
        )
      ) {
        source.close();
        setStreamConnection("closed");
        refreshTerminalJob();
      }
    };

    const scheduleFlush = (immediate = false) => {
      if (immediate) {
        if (flushTimer !== undefined) window.clearTimeout(flushTimer);
        flush();
        return;
      }
      if (flushTimer === undefined) {
        flushTimer = window.setTimeout(flush, 50);
      }
    };

    source.onopen = () => {
      if (!disposed) setStreamConnection("live");
    };
    source.onmessage = (message) => {
      if (disposed) return;
      try {
        const event = JSON.parse(message.data) as JobEvent;
        if (event.task_id !== taskId) return;
        pending.push(event);
        scheduleFlush(
          ["job_complete", "job_failed", "job_cancelled"].includes(
            event.kind,
          ),
        );
      } catch {
        setError("实时输出包含无法解析的事件。");
      }
    };
    source.onerror = () => {
      if (!disposed && !terminalHandled) {
        setStreamConnection("reconnecting");
      }
    };

    return () => {
      if (flushTimer !== undefined) window.clearTimeout(flushTimer);
      flush();
      disposed = true;
      source.close();
    };
  }, [workspaceReady, job?.id, job?.status, refreshHistory]);

  useEffect(() => {
    if (!job || !shouldContinuePolling(job.status) || !workspaceReady) return;
    let disposed = false;
    let timer: number | undefined;
    let failures = 0;

    const schedule = (delay: number) => {
      timer = window.setTimeout(() => void poll(), delay);
    };
    const poll = async () => {
      const taskId = job.id;
      try {
        const next = await getJob(taskId);
        if (
          disposed
          || currentJobIdRef.current !== taskId
        ) {
          return;
        }
        failures = 0;
        setJob(next);
        if (next.status === "completed" && next.result) {
          setResult(next.result);
          setSelectedNodeId(next.result.root_id);
          void refreshHistory();
        } else if (next.status === "failed") {
          setError(next.error || "任务执行失败");
        } else if (next.status === "cancelled") {
          setError("任务已取消，源文件仍保留在服务端。");
        }
        if (shouldContinuePolling(next.status)) {
          schedule(nextPollDelay(0));
        }
      } catch (caught) {
        if (disposed) return;
        failures += 1;
        setError(caught instanceof Error ? caught.message : "任务状态读取失败");
        schedule(nextPollDelay(failures));
      }
    };

    schedule(nextPollDelay(0));
    return () => {
      disposed = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [workspaceReady, job?.id, job?.status, refreshHistory]);

  useEffect(() => {
    if (!job) return;
    if (shouldContinuePolling(job.status)) {
      window.localStorage.setItem(ACTIVE_TASK_KEY, job.id);
    } else if (window.localStorage.getItem(ACTIVE_TASK_KEY) === job.id) {
      window.localStorage.removeItem(ACTIVE_TASK_KEY);
    }
  }, [job]);

  useEffect(() => {
    if (!historyOpen && !settingsOpen) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        if (document.querySelector(".mindmap-viewer")) return;
        setHistoryOpen(false);
        setSettingsOpen(false);
      }
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [historyOpen, settingsOpen]);

  useEffect(() => {
    if (result) setArtifactOpen(false);
  }, [result?.task_id]);

  const running = job ? shouldContinuePolling(job.status) : false;
  const workspaceLabel = health
    ? `${health.workspace.name} · ${health.architecture.name}`
    : "正在连接工作空间";

  const acceptFile = useCallback((next: File | undefined) => {
    if (!next) return;
    if (!canReplaceActiveJob(job?.status ?? null)) {
      setError("当前任务仍在运行，请先取消任务再选择新文件。");
      return;
    }
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
  }, [job?.status]);

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    acceptFile(event.dataTransfer.files[0]);
  };

  const run = async () => {
    if (
      !canStartJobSubmission(
        Boolean(file),
        workspaceReady,
        running,
        submittingRef.current,
      )
      || !file
    ) {
      return;
    }
    submittingRef.current = true;
    setSubmitting(true);
    setError("");
    setResult(null);
    setSelectedNodeId(null);
    setView("stream");
    setSettingsOpen(false);
    try {
      const primaryModel = loopConfig.rounds[0].editor_model;
      const next = await createJob(
        file,
        provider,
        primaryModel,
        loopConfig,
      );
      currentJobIdRef.current = next.id;
      window.localStorage.setItem(ACTIVE_TASK_KEY, next.id);
      setJob(next);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "提交任务失败");
    } finally {
      submittingRef.current = false;
      setSubmitting(false);
    }
  };

  const cancelActiveJob = async () => {
    if (!job || !running) return;
    setError("");
    try {
      const cancelled = await cancelJob(job.id);
      setJob(cancelled);
      void refreshHistory().catch(() => undefined);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "取消任务失败");
    }
  };

  const verifyModel = async () => {
    setModelStatus("checking");
    setModelMessage("");
    try {
      const selectedModels = selectedLoopModels(loopConfig);
      const checks = await Promise.all(
        selectedModels.map(async (model) => ({
          model,
          ...(await checkModel(provider, model)),
        })),
      );
      const unavailable = checks.filter((check) => !check.ok);
      setModelStatus(unavailable.length === 0 ? "available" : "denied");
      setModelMessage(
        unavailable.length === 0
          ? `${selectedModels.length} 个模型均可用`
          : `${unavailable.map((check) => check.model).join("、")} 不可用`,
      );
    } catch (caught) {
      setModelStatus("denied");
      setModelMessage(caught instanceof Error ? caught.message : "检查失败");
    }
  };

  const openHistoryItem = async (item: HistoryItem) => {
    setHistoryBusyId(item.task_id);
    setError("");
    try {
      const restored = await getJob(item.task_id);
      setJob(restored);
      if (restored.loop_config) {
        setLoopConfig(
          normalizeLoopConfig(
            restored.loop_config,
            restored.loop_config.rounds[0]?.editor_model ||
              "qwen3.8-max-preview",
          ),
        );
      }
      if (restored.result) {
        setResult(restored.result);
        setSelectedNodeId(restored.result.root_id);
        setArtifactOpen(false);
      } else {
        setResult(null);
        setSelectedNodeId(null);
        if (restored.status === "failed") {
          setError(restored.error || "该历史任务执行失败。");
        }
      }
      setView(
        shouldContinuePolling(restored.status) ? "stream" : "graph",
      );
      setFile(null);
      if (window.innerWidth <= 700) setHistoryOpen(false);
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
    if (result.extraction_mode === "qwen") return "Qwen 生成";
    if (result.extraction_mode === "deepseek") return "历史 DeepSeek 任务";
    if (result.extraction_mode === "kimi") return "历史模型任务";
    if (result.extraction_mode === "mixed") return "模型与本地混合";
    return "本地确定性降级";
  }, [result]);

  const qualityState = result
    ? qualityPresentation({
        topology_valid: result.quality_report.topology_valid,
        structural_gate_passed:
          result.quality_report.structural_gate_passed,
        publish_gate_passed:
          result.quality_report.publish_gate_passed,
        quality_gate_passed:
          result.quality_report.quality_gate_passed,
        degraded_components: result.degraded_components,
        pending_reviews: 0,
      })
    : null;
  const sourceFilename = file?.name || result?.document.filename || "";
  const visibleHistory = useMemo(() => {
    const query = historyQuery.trim().toLocaleLowerCase();
    if (!query) return history;
    return history.filter((item) =>
      `${item.title} ${item.filename}`.toLocaleLowerCase().includes(query),
    );
  }, [history, historyQuery]);

  const clearFileSelection = () => {
    setFile(null);
    if (fileInput.current) fileInput.current.value = "";
  };

  const startNewTask = () => {
    if (running) {
      setError("当前任务仍在运行，请先取消任务再新建会话。");
      return;
    }
    clearFileSelection();
    setResult(null);
    setJob(null);
    setSelectedNodeId(null);
    setView("graph");
    setArtifactOpen(false);
    if (window.innerWidth <= 700) setHistoryOpen(false);
    setError("");
  };

  return (
    <div
      className={`app-shell agent-shell ${historyOpen ? "sidebar-open" : ""}`}
    >
      <header className="topbar">
        <div className="topbar-primary">
          <button
            type="button"
            className="topbar-icon"
            aria-label="历史记录"
            title="历史记录"
            onClick={() => setHistoryOpen((current) => !current)}
            disabled={!workspaceReady}
          >
            <Menu size={18} />
          </button>
          <button
            type="button"
            className="agent-selector"
            onClick={() => setSettingsOpen(true)}
          >
            <span className="brand-mark">
              <Network size={17} />
            </span>
            <span>
              <strong>{PRODUCT_NAME}</strong>
              <small>{PRODUCT_DESCRIPTION}</small>
            </span>
            <ChevronDown size={15} />
          </button>
        </div>
        <div className="topbar-actions">
          <button
            type="button"
            className="topbar-command"
            onClick={startNewTask}
            disabled={running}
          >
            <Plus size={16} />
            <span>新建会话</span>
          </button>
          <button
            type="button"
            className="topbar-icon"
            aria-label="Agent 设置"
            title="Agent 设置"
            onClick={() => setSettingsOpen(true)}
          >
            <Settings2 size={17} />
          </button>
          <div className="workspace-status">
            <span
              className={`status-dot ${health?.workspace.key_configured ? "online" : ""}`}
            />
            <span>{workspaceLabel}</span>
          </div>
        </div>
      </header>

      <input
        ref={fileInput}
        type="file"
        accept=".pdf,.pptx,.docx,.txt,.md"
        hidden
        onChange={(event) => acceptFile(event.target.files?.[0])}
      />

      <div className="workspace-layout">
        {settingsOpen && (
          <aside
            className="control-panel settings-drawer open"
            role="dialog"
            aria-modal="true"
            aria-label="Agent 设置"
          >
          <header className="settings-drawer-header">
            <div>
              <span className="eyebrow">Agent configuration</span>
              <h2>{PRODUCT_NAME}</h2>
            </div>
            <button
              type="button"
              className="topbar-icon"
              aria-label="关闭 Agent 设置"
              title="关闭"
              onClick={() => setSettingsOpen(false)}
            >
              <X size={18} />
            </button>
          </header>
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
              <h2>编排 loop</h2>
              <p>逐轮选择 Agent 角色与模型</p>
            </div>
          </div>

          <LoopBuilder
            config={loopConfig}
            example={loopExample}
            models={models}
            disabled={running || submitting}
            onChange={(next) => {
              setLoopConfig(next);
              setModelStatus("idle");
              setModelMessage("");
            }}
          />

          <button
            type="button"
            className={`model-check ${modelStatus}`}
            onClick={verifyModel}
            disabled={modelStatus === "checking" || !workspaceReady}
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
              ? "检查所选模型"
              : modelStatus === "checking"
                ? "正在检查"
                : modelMessage}
          </button>

          <button
            type="button"
            className="run-button"
            onClick={run}
            disabled={
              !canStartJobSubmission(
                Boolean(file),
                workspaceReady,
                running,
                submitting,
              )
            }
          >
            {running || submitting ? (
              <LoaderCircle className="spin" size={18} />
            ) : (
              <Play size={18} fill="currentColor" />
            )}
            {submitting
              ? "正在提交任务"
              : running
                ? "正在构建思维导图"
                : "开始构建"}
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
              <button
                type="button"
                className="cancel-job"
                onClick={() => void cancelActiveJob()}
              >
                <Square size={13} fill="currentColor" />
                取消任务
              </button>
            </div>
          )}

          {error && (
            <div className="error-box" role="alert">
              <AlertCircle size={16} />
              <span>{error}</span>
            </div>
          )}
          </aside>
        )}

        <main className="main-workspace">
          {result && artifactOpen ? (
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
                  <div>
                    <strong>{result.quality_report.cross_link_count}</strong>
                    <span>跨链</span>
                  </div>
                </div>
              </div>

              <div
                className={`quality-strip ${qualityState?.kind || "review"}`}
              >
                {qualityState?.kind === "passed" ? (
                  <CheckCircle2 size={16} />
                ) : (
                  <AlertCircle size={16} />
                )}
                <span>{qualityState?.label}</span>
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
                  className={view === "visuals" ? "active" : ""}
                  onClick={() => setView("visuals")}
                >
                  <Images size={16} /> 视觉
                  {result.assets.length > 0 && (
                    <span className="visual-tab-count">{result.assets.length}</span>
                  )}
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
                {streamState.calls.length > 0 && (
                  <button
                    type="button"
                    className={view === "stream" ? "active" : ""}
                    onClick={() => setView("stream")}
                  >
                    <SquareTerminal size={16} /> 运行输出
                    <span className="tab-count">
                      {streamState.calls.length}
                    </span>
                  </button>
                )}
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
                  aria-label="保存 JSON"
                >
                  <Download size={15} />
                  <span>保存 JSON</span>
                </a>
                <button
                  type="button"
                  className="reset-action"
                  aria-label="新建任务"
                  title="新建任务"
                  onClick={startNewTask}
                >
                  <RotateCcw size={15} />
                  <span>新建任务</span>
                </button>
                <button
                  type="button"
                  className="artifact-close"
                  aria-label="关闭工作区"
                  title="关闭工作区"
                  onClick={() => setArtifactOpen(false)}
                >
                  <PanelRightClose size={15} />
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
                {view === "visuals" && (
                  <VisualGallery
                    result={result}
                    onSelectNode={(id) => {
                      setSelectedNodeId(id);
                      setView("graph");
                    }}
                  />
                )}
                {view === "chunks" && <ChunkList chunks={result.chunks} />}
                {view === "stream" && job && (
                  <AgentActivityFeed
                    job={job}
                    calls={streamState.calls}
                    steps={streamState.steps}
                    connectionState={streamConnection}
                  />
                )}
              </div>
            </>
          ) : result ? (
            <div className="conversation-complete">
              <div className="message-thread">
                <article className="chat-message user-message">
                  <div className="message-avatar user-avatar">你</div>
                  <div className="message-content">
                    <p>为这份课程材料构建思维导图。</p>
                    <span className="message-file">
                      <FileStack size={15} />
                      {sourceFilename}
                    </span>
                  </div>
                </article>
                <article className="chat-message assistant-message">
                  <div className="message-avatar agent-avatar">
                    <Network size={17} />
                  </div>
                  <div className="message-content">
                    {job && (
                      <AgentActivityFeed
                        job={job}
                        calls={streamState.calls}
                        steps={streamState.steps}
                        connectionState={streamConnection}
                      />
                    )}
                    <strong>思维导图已完成</strong>
                    <p>
                      已生成 {result.quality_report.node_count} 个节点、
                      {result.quality_report.tree_edge_count} 条主树边，内容覆盖率
                      {Math.round(
                        result.quality_report.weighted_content_coverage * 100,
                      )}
                      %。
                    </p>
                    <MindmapAttachment result={result} />
                    <button
                      type="button"
                      className="open-artifact"
                      onClick={() => setArtifactOpen(true)}
                    >
                      <TableProperties size={16} />
                      查看结构数据
                    </button>
                  </div>
                </article>
              </div>
              <button
                type="button"
                className="new-conversation-action"
                onClick={startNewTask}
              >
                <Plus size={16} />
                新建会话
              </button>
            </div>
          ) : job && (running || streamState.calls.length > 0) ? (
            <div className="conversation-running">
              <div className="message-thread">
                <article className="chat-message user-message">
                  <div className="message-avatar user-avatar">你</div>
                  <div className="message-content">
                    <p>为这份课程材料构建思维导图。</p>
                    <span className="message-file">
                      <FileStack size={15} />
                      {sourceFilename}
                    </span>
                  </div>
                </article>
                <article className="chat-message assistant-message">
                  <div className="message-avatar agent-avatar">
                    <Network size={17} />
                  </div>
                  <div className="message-content">
                    <AgentActivityFeed
                      job={job}
                      calls={streamState.calls}
                      steps={streamState.steps}
                      connectionState={streamConnection}
                      onCancel={() => void cancelActiveJob()}
                    />
                  </div>
                </article>
              </div>
            </div>
          ) : (
            <div className="empty-workspace">
              <div className="chat-welcome">
                <div className="empty-state-icon">
                  <Network size={28} />
                </div>
                <h1>今天想整理哪份课程材料？</h1>
                <p>上传课件，Agent 会生成完整的课程思维导图。</p>
                {!file && (
                  <button
                    type="button"
                    className="sample-button welcome-sample"
                    onClick={() => acceptFile(createSampleFile())}
                  >
                    <Sparkles size={15} />
                    载入机器学习示例
                  </button>
                )}
              </div>
              <div
                className={`composer-stage ${dragging ? "dragging" : ""}`}
                onDragOver={(event) => {
                  event.preventDefault();
                  setDragging(true);
                }}
                onDragLeave={() => setDragging(false)}
                onDrop={handleDrop}
              >
                {file && (
                  <div className="composer-file">
                    <span>
                      <FileStack size={15} />
                      <strong>{file.name}</strong>
                      <small>{(file.size / 1024).toFixed(1)} KB</small>
                    </span>
                    <button
                      type="button"
                      aria-label="移除文件"
                      title="移除文件"
                      onClick={clearFileSelection}
                    >
                      <X size={15} />
                    </button>
                  </div>
                )}
                <div className="agent-composer">
                  <button
                    type="button"
                    className="composer-icon"
                    aria-label="上传课件"
                    title="上传课件"
                    onClick={() => fileInput.current?.click()}
                  >
                    <Paperclip size={18} />
                  </button>
                  <div className="composer-copy">
                    <strong>
                      {file ? "构建课程思维导图" : "上传课程文件"}
                    </strong>
                    <span>
                      {file
                        ? file.name
                        : "PDF、PPTX、DOCX、TXT 或 Markdown"}
                    </span>
                  </div>
                  <button
                    type="button"
                    className="composer-icon"
                    aria-label="Agent 设置"
                    title="Agent 设置"
                    onClick={() => setSettingsOpen(true)}
                  >
                    <Settings2 size={18} />
                  </button>
                  <button
                    type="button"
                    className="composer-send"
                    aria-label="开始构建"
                    title="开始构建"
                    onClick={() => void run()}
                    disabled={
                      !canStartJobSubmission(
                        Boolean(file),
                        workspaceReady,
                        running,
                        submitting,
                      )
                    }
                  >
                    {submitting ? (
                      <LoaderCircle className="spin" size={18} />
                    ) : (
                      <Send size={18} fill="currentColor" />
                    )}
                  </button>
                </div>
                <span className="composer-note">
                  {dragging
                    ? "松开即可添加课程文件"
                    : `${workspaceLabel} · 最多 150 页或幻灯片`}
                </span>
              </div>
              {error && (
                <div className="chat-error" role="alert">
                  <AlertCircle size={16} />
                  <span>{error}</span>
                </div>
              )}
            </div>
          )}
        </main>
      </div>
      {settingsOpen && (
        <button
          type="button"
          className="settings-scrim"
          aria-label="关闭 Agent 设置"
          onClick={() => setSettingsOpen(false)}
        />
      )}
      <div
        className={`history-overlay ${historyOpen ? "open" : ""}`}
        onMouseDown={(event) => {
          if (
            window.innerWidth <= 700
            && event.target === event.currentTarget
          ) {
            setHistoryOpen(false);
          }
        }}
      >
        <aside className="history-drawer" aria-label="会话">
          <header>
            <div>
              <span className="eyebrow">{PRODUCT_NAME}</span>
              <h2>会话</h2>
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
          <button
            type="button"
            className="sidebar-new-session"
            onClick={startNewTask}
            disabled={running}
          >
            <Plus size={15} />
            新建会话
          </button>
          <label className="sidebar-search">
            <Search size={14} />
            <input
              value={historyQuery}
              onChange={(event) => setHistoryQuery(event.target.value)}
              placeholder="搜索会话"
              aria-label="搜索会话"
            />
          </label>
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
          ) : visibleHistory.length === 0 ? (
            <div className="history-state compact">
              <Search size={20} />
              <strong>没有匹配的会话</strong>
            </div>
          ) : (
            <div className="history-list">
              {visibleHistory.map((item) => (
                <div
                  className={`history-item ${
                    item.task_id === job?.id ? "active" : ""
                  }`}
                  key={item.task_id}
                >
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
    </div>
  );
}

export default App;
