import {
  AlertCircle,
  Check,
  ChevronDown,
  CircleGauge,
  FileStack,
  GitBranch,
  LoaderCircle,
  Network,
  Play,
  RotateCcw,
  Sparkles,
  TableProperties,
  Upload,
} from "lucide-react";
import {
  type DragEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { checkModel, createJob, getHealth, getJob, getModels } from "./api";
import { ChunkList } from "./components/ChunkList";
import { DataTable } from "./components/DataTable";
import { GraphCanvas } from "./components/GraphCanvas";
import { Inspector } from "./components/Inspector";
import { createSampleFile } from "./sample";
import type { AnalysisResult, Health, Job } from "./types";

type View = "graph" | "nodes" | "chunks";

const stageLabels: Record<string, string> = {
  queued: "等待",
  starting: "启动",
  parse: "解析",
  chunk: "切分",
  model_check: "鉴权",
  extract: "抽取",
  normalize: "归一",
  complete: "完成",
};

function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [models, setModels] = useState<string[]>([]);
  const [provider, setProvider] = useState<"bailian" | "deepseek">("bailian");
  const [model, setModel] = useState("qwen3.7-plus");
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
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    void getHealth()
      .then((data) => {
        setHealth(data);
        const preferred = data.providers.deepseek.configured
          ? "deepseek"
          : "bailian";
        setProvider(preferred);
        setModel(data.providers[preferred].default_model);
        void getModels(preferred).then(setModels).catch(() => undefined);
      })
      .catch((caught) => setError(caught.message));
  }, []);

  useEffect(() => {
    if (!job || job.status === "completed" || job.status === "failed") return;
    const timer = window.setInterval(() => {
      void getJob(job.id)
        .then((next) => {
          setJob(next);
          if (next.status === "completed" && next.result) {
            setResult(next.result);
            setSelectedNodeId(next.result.nodes[0]?.id || null);
          }
          if (next.status === "failed") setError(next.error || "任务执行失败");
        })
        .catch((caught) => setError(caught.message));
    }, 700);
    return () => window.clearInterval(timer);
  }, [job]);

  const running = job?.status === "queued" || job?.status === "running";
  const workspaceLabel = health
    ? `${health.workspace.name} · ${health.workspace.id_suffix || "workspace"}`
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
    try {
      const next = await createJob(file, provider, model, useAi);
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

  const modeLabel = useMemo(() => {
    if (!result) return "";
    if (result.extraction_mode === "bailian") return "百炼模型抽取";
    if (result.extraction_mode === "deepseek") return "DeepSeek 模型抽取";
    if (result.extraction_mode === "mixed") return "模型 + 本地混合抽取";
    return "本地启发式抽取";
  }, [result]);

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">
            <Network size={20} />
          </span>
          <div>
            <strong>ZLB 知识导图</strong>
            <span>课程知识编织工作台</span>
          </div>
        </div>
        <div className="workspace-status">
          <span
            className={`status-dot ${health?.workspace.key_configured ? "online" : ""}`}
          />
          <span>{workspaceLabel}</span>
        </div>
      </header>

      <div className="workspace-layout">
        <aside className="control-panel">
          <div className="panel-heading">
            <span className="step-number">01</span>
            <div>
              <h2>导入课件</h2>
              <p>保留页码、章节和原文证据</p>
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
                <span>PDF · PPTX · DOCX · TXT · MD</span>
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
              <h2>抽取配置</h2>
              <p>模型生成候选，代码负责归一</p>
            </div>
          </div>

          <label className="field-label" htmlFor="model-select">
            模型服务
          </label>
          <div className="provider-control" aria-label="模型服务商">
            <button
              type="button"
              className={provider === "bailian" ? "active" : ""}
              onClick={() => {
                setProvider("bailian");
                setModel(health?.providers.bailian.default_model || "qwen3.7-plus");
                setModelStatus("idle");
                void getModels("bailian").then(setModels).catch(() => setModels([]));
              }}
            >
              百炼
            </button>
            <button
              type="button"
              className={provider === "deepseek" ? "active" : ""}
              onClick={() => {
                setProvider("deepseek");
                setModel(
                  health?.providers.deepseek.default_model || "deepseek-v4-flash",
                );
                setModelStatus("idle");
                void getModels("deepseek")
                  .then(setModels)
                  .catch(() => setModels(["deepseek-v4-flash", "deepseek-v4-pro"]));
              }}
            >
              DeepSeek
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
              ? "检查模型权限"
              : modelStatus === "checking"
                ? "正在检查"
                : modelMessage}
          </button>

          <label className="toggle-row">
            <span>
              <strong>优先使用{provider === "bailian" ? "百炼" : " DeepSeek"}</strong>
              <small>{provider === "bailian" ? "百炼" : "DeepSeek"} 不可用时自动本地降级</small>
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
            {running ? "正在构建知识图" : "开始构建"}
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
                    {result.document.file_type.toUpperCase()} · {modeLabel}
                  </span>
                  <h1>{result.document.title}</h1>
                </div>
                <div className="result-stats">
                  <div>
                    <strong>{result.quality.node_count}</strong>
                    <span>节点</span>
                  </div>
                  <div>
                    <strong>{result.quality.edge_count}</strong>
                    <span>关系</span>
                  </div>
                  <div>
                    <strong>
                      {Math.round(result.quality.evidence_coverage * 100)}%
                    </strong>
                    <span>证据覆盖</span>
                  </div>
                </div>
              </div>

              {(result.warnings.length > 0 ||
                result.quality.warnings.length > 0) && (
                <div className="warning-strip">
                  <AlertCircle size={16} />
                  <span>
                    {[...result.warnings, ...result.quality.warnings].join(" ")}
                  </span>
                </div>
              )}

              <div className="view-tabs" role="tablist">
                <button
                  type="button"
                  className={view === "graph" ? "active" : ""}
                  onClick={() => setView("graph")}
                >
                  <GitBranch size={16} /> 关系图
                </button>
                <button
                  type="button"
                  className={view === "nodes" ? "active" : ""}
                  onClick={() => setView("nodes")}
                >
                  <TableProperties size={16} /> 节点表
                </button>
                <button
                  type="button"
                  className={view === "chunks" ? "active" : ""}
                  onClick={() => setView("chunks")}
                >
                  <FileStack size={16} /> Chunks
                </button>
                <button
                  type="button"
                  className="reset-action"
                  onClick={() => {
                    setResult(null);
                    setJob(null);
                    setSelectedNodeId(null);
                  }}
                >
                  <RotateCcw size={15} /> 新建任务
                </button>
              </div>

              <div className={`result-body ${view}`}>
                {view === "graph" && (
                  <>
                    <GraphCanvas
                      result={result}
                      selectedNodeId={selectedNodeId}
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
              </div>
            </>
          ) : (
            <div className="empty-workspace">
              <div className="empty-visual" aria-hidden="true">
                <span className="node n1">概念</span>
                <span className="node n2">方法</span>
                <span className="node n3">原理</span>
                <span className="node n4">应用</span>
                <i className="line l1" />
                <i className="line l2" />
                <i className="line l3" />
              </div>
              <span className="eyebrow">Knowledge map agent</span>
              <h1>从课件到可追溯的知识网络</h1>
              <p>上传课程文档，工作流会保留章节位置、抽取候选节点，并用确定性规则完成归一与关系校验。</p>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}

export default App;
