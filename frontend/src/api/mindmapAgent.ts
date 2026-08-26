import type {
  AppConfig,
  AppEvent,
  AppMessage,
  AppModel,
  AppProvider,
  AppSession,
  AppSessionRuntimeStatus,
  AppSessionSnapshot,
  AppTask,
  AppTerminal,
  AppWorkspace,
  ApprovalResponse,
  FsBrowseResult,
  FsEntry,
  FsKind,
  KimiEventConnection,
  KimiEventHandlers,
  KimiWebApi,
  Page,
  PageRequest,
  PromptSubmission,
  PromptSubmitResult,
  ProviderRefreshResult,
  QuestionResponse,
} from './types';

const WORKSPACE_ID = 'mindmap-agent';
const WORKSPACE_ROOT = '/workspace';
const FIXED_MODEL = 'qwen3.8-max';
const QWEN38_MAX_CONTEXT_LIMIT = 131072;
const EMPTY_USAGE = {
  inputTokens: 0,
  outputTokens: 0,
  cacheReadTokens: 0,
  cacheCreationTokens: 0,
  totalCostUsd: 0,
  contextTokens: 0,
  contextLimit: QWEN38_MAX_CONTEXT_LIMIT,
  turnCount: 0,
};

interface MindmapLoopRound {
  editor_model: string;
  content_omission_model?: string | null;
  pruning_model?: string | null;
  multilevel_structure_model?: string | null;
}

interface MindmapLoopConfig {
  rounds: MindmapLoopRound[];
}

function drawingLoopConfig(multiAgent: boolean): MindmapLoopConfig {
  const rounds = multiAgent ? 2 : 1;
  return {
    rounds: Array.from({ length: rounds }, () => ({
      editor_model: FIXED_MODEL,
      ...(multiAgent
        ? {
            content_omission_model: FIXED_MODEL,
            pruning_model: FIXED_MODEL,
            multilevel_structure_model: FIXED_MODEL,
          }
        : {}),
    })),
  };
}

function isMultiAgentLoop(loopConfig?: MindmapLoopConfig | null): boolean {
  if (!loopConfig?.rounds.length) return false;
  return (
    loopConfig.rounds.length > 1
    || loopConfig.rounds.some(
      (round) =>
        Boolean(round.content_omission_model)
        || Boolean(round.pruning_model)
        || Boolean(round.multilevel_structure_model),
    )
  );
}

interface BackendHealth {
  default_model?: string;
  providers?: {
    qwen?: {
      default_model?: string;
    };
  };
  architecture?: {
    loop?: {
      example?: MindmapLoopConfig;
    };
  };
}

interface BackendResult {
  task_id: string;
  graph_version: number;
  root_id: string;
  nodes: unknown[];
  tree_edges: unknown[];
  cross_links: unknown[];
  warnings?: string[];
  document: {
    filename: string;
    title: string;
  };
  quality_report?: {
    quality_gate_passed?: boolean;
  };
}

interface BackendJob {
  id: string;
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
  stage: string;
  progress: number;
  message: string;
  mode: 'standard' | 'precision';
  loop_config?: MindmapLoopConfig | null;
  result?: BackendResult | null;
  error?: string | null;
  context_tokens?: number;
  max_context_tokens?: number;
  context_usage?: number;
  manifest?: Record<string, unknown> | null;
}

interface BackendInteraction {
  id: string;
  kind: 'initial' | 'revision';
  instruction: string;
  created_at: string;
  base_graph_version: number;
  result_graph_version?: number | null;
  status: BackendJob['status'];
  error?: string | null;
}

interface BackendHistoryItem {
  task_id: string;
  title: string;
  filename: string;
  created_at: string;
  updated_at: string;
  status: BackendJob['status'];
  stage: string;
  progress: number;
  error?: string | null;
}

interface BackendJobEvent {
  id: number;
  task_id: string;
  kind:
    | 'status'
    | 'model_start'
    | 'model_delta'
    | 'model_complete'
    | 'model_error'
    | 'job_complete'
    | 'job_failed'
    | 'job_cancelled'
    | 'usage'
    | 'compaction';
  context_tokens?: number;
  max_context_tokens?: number;
  context_usage?: number;
  tokensBefore?: number;
  tokensAfter?: number;
  summary?: string;
  trigger?: string;
  created_at: string;
  stage: string;
  progress?: number | null;
  message: string;
  call_id: string;
  round_number?: number | null;
  role: string;
  model: string;
  delta: string;
}

interface StoredUpload {
  blob: Blob;
  name: string;
  mediaType: string;
  size: number;
}

interface SessionDraft {
  session: AppSession;
  promptText?: string;
  uploadId?: string;
}

async function parseResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { detail?: string };
    throw new Error(body.detail || `HTTP ${response.status}`);
  }
  return response.json() as Promise<T>;
}

function nowIso(): string {
  return new Date().toISOString();
}

let fallbackUidCounter = 0;

function uid(prefix: string): string {
  const webCrypto = globalThis.crypto;
  if (typeof webCrypto?.randomUUID === 'function') {
    return `${prefix}_${webCrypto.randomUUID()}`;
  }

  // randomUUID is restricted to secure contexts in some browsers. The public
  // IP deployment currently runs over HTTP, so use a collision-resistant local
  // identifier instead of failing before an attachment can be staged.
  fallbackUidCounter += 1;
  const timestamp = Date.now().toString(36);
  const counter = fallbackUidCounter.toString(36);
  const entropy = Math.random().toString(36).slice(2, 12);
  return `${prefix}_${timestamp}_${counter}_${entropy}`;
}

function sessionFromHistory(item: BackendHistoryItem, titleOverride?: string): AppSession {
  return {
    id: item.task_id,
    title: titleOverride || item.title || item.filename,
    createdAt: item.created_at,
    updatedAt: item.updated_at,
    busy: item.status === 'queued' || item.status === 'running',
    mainTurnActive: item.status === 'queued' || item.status === 'running',
    lastTurnReason:
      item.status === 'completed'
        ? 'completed'
        : item.status === 'failed' || item.status === 'cancelled'
          ? item.status === 'failed'
            ? 'failed'
            : 'cancelled'
          : undefined,
    pendingInteraction: 'none',
    archived: false,
    lastPrompt: item.filename,
    cwd: WORKSPACE_ROOT,
    model: FIXED_MODEL,
    usage: { ...EMPTY_USAGE },
    messageCount: item.status === 'completed' ? 2 : 1,
    lastSeq: item.progress,
    workspaceId: WORKSPACE_ID,
  };
}

function stageLabel(stage: string): string {
  const labels: Record<string, string> = {
    queued: '排队等待',
    starting: '启动任务',
    parse: '解析文档',
    ingest: '读取内容',
    chunk: '切分内容',
    extract: '提取知识',
    solve: '构建结构',
    validate: '校验图谱',
    render: '渲染思维导图',
    review: '检查结果',
    complete: '完成任务',
    failed: '任务失败',
    cancelled: '任务取消',
  };
  return labels[stage] || stage.replaceAll('_', ' ');
}

function roleLabel(role: string): string {
  const labels: Record<string, string> = {
    global_editor: '全局编辑',
    content_omission: '内容查漏',
    pruning: '结构精简',
    multilevel_structure: '层级校正',
    vision: '视觉理解',
  };
  return labels[role] || role.replaceAll('_', ' ') || '模型处理';
}

function resultSummary(job: BackendJob): string {
  const result = job.result;
  if (!result) return job.message || '思维导图已生成。';
  const title = result.document.title || result.document.filename;
  const quality = result.quality_report?.quality_gate_passed === false ? '，结果包含质量提示' : '';
  return `已完成《${title}》的思维导图，共 ${result.nodes.length} 个节点${quality}。`;
}

function interactionSummary(job: BackendJob, interaction: BackendInteraction): string {
  const version = interaction.result_graph_version;
  const isLatest = Boolean(version && version === job.result?.graph_version);
  if (!isLatest) {
    return version ? `思维导图 v${version} 已完成。` : '本轮思维导图处理已完成。';
  }
  if (interaction.kind === 'revision') {
    const quality = job.result?.quality_report?.quality_gate_passed === false ? '，结果包含质量提示' : '';
    return `已按你的要求更新到 v${version}，当前共 ${job.result?.nodes.length ?? 0} 个节点${quality}。`;
  }
  return resultSummary(job);
}

function resultMediaContent(
  taskId: string,
  toolCallId: string,
  graphVersion?: number | null,
): AppMessage['content'] {
  const versionQuery = graphVersion ? `?v=${encodeURIComponent(graphVersion)}` : '';
  const url = `/api/jobs/${encodeURIComponent(taskId)}/export.png${versionQuery}`;
  return [
    {
      type: 'toolUse',
      toolCallId,
      toolName: 'ReadMediaFile',
      input: `mindmap-${taskId}.png`,
    },
    {
      type: 'toolResult',
      toolCallId,
      output: [
        { type: 'text', text: `<image path="mindmap-${taskId}.png">` },
        { type: 'text', text: 'Mime type: image/png.' },
        { type: 'image_url', imageUrl: { url } },
      ],
    },
  ];
}

class MindmapEventConnection implements KimiEventConnection {
  private readonly subscribed = new Set<string>();
  private readonly sources = new Map<string, EventSource>();
  private readonly seqBySession = new Map<string, number>();
  private readonly promptBySession = new Map<string, string>();
  private readonly openStageBySession = new Map<string, string>();
  private readonly openCallsBySession = new Map<string, Map<string, string>>();
  private closed = false;

  constructor(
    private readonly api: MindmapAgentApi,
    private readonly handlers: KimiEventHandlers,
  ) {}

  subscribe(sessionId: string): void {
    if (this.closed) return;
    this.subscribed.add(sessionId);
    this.handlers.onConnectionChange(true);
    this.attach(sessionId);
  }

  unsubscribe(sessionId: string): void {
    this.subscribed.delete(sessionId);
    this.sources.get(sessionId)?.close();
    this.sources.delete(sessionId);
  }

  bindNextPromptId(sessionId: string, promptId: string): void {
    this.promptBySession.set(sessionId, promptId);
  }

  seedSnapshot(sessionId: string, snapshot: AppSessionSnapshot): void {
    this.seqBySession.set(sessionId, snapshot.asOfSeq);
    if (snapshot.inFlightTurn?.promptId) {
      this.promptBySession.set(sessionId, snapshot.inFlightTurn.promptId);
    }
  }

  abort(): void {}
  terminalAttach(): void {}
  terminalInput(): void {}
  terminalResize(): void {}
  terminalDetach(): void {}
  terminalClose(): void {}
  markSideChannelAgent(): void {}

  health(): { connected: boolean; open: boolean; stale: boolean } {
    return {
      connected: !this.closed,
      open: !this.closed,
      stale: false,
    };
  }

  reconnect(): void {
    if (this.closed) return;
    for (const sessionId of this.subscribed) {
      this.sources.get(sessionId)?.close();
      this.sources.delete(sessionId);
      this.attach(sessionId);
    }
  }

  close(): void {
    this.closed = true;
    for (const source of this.sources.values()) source.close();
    this.sources.clear();
    this.handlers.onConnectionChange(false);
    this.api.dropConnection(this);
  }

  taskAvailable(sessionId: string): void {
    this.sources.get(sessionId)?.close();
    this.sources.delete(sessionId);
    this.openStageBySession.delete(sessionId);
    this.openCallsBySession.delete(sessionId);
    if (this.subscribed.has(sessionId)) this.attach(sessionId);
  }

  emit(sessionId: string, event: AppEvent): void {
    const seq = (this.seqBySession.get(sessionId) ?? 0) + 1;
    this.seqBySession.set(sessionId, seq);
    this.handlers.onEvent(event, { sessionId, seq });
  }

  private attach(sessionId: string): void {
    if (this.closed || this.sources.has(sessionId) || this.api.isTerminal(sessionId)) return;
    const taskId = this.api.taskIdForSession(sessionId);
    if (!taskId) return;

    const source = new EventSource(`/api/jobs/${encodeURIComponent(taskId)}/events`);
    this.sources.set(sessionId, source);
    source.onopen = () => this.handlers.onConnectionChange(true);
    source.onmessage = (message) => {
      try {
        const event = JSON.parse(message.data) as BackendJobEvent;
        if (event.task_id !== taskId) return;
        void this.consume(sessionId, taskId, event);
      } catch (error) {
        this.handlers.onError(500, error instanceof Error ? error.message : '实时事件解析失败', false);
      }
    };
    source.onerror = () => {
      if (this.api.isTerminal(sessionId) || this.closed) return;
      this.handlers.onConnectionChange(false);
    };
  }

  private promptId(sessionId: string): string {
    return this.promptBySession.get(sessionId) || this.api.promptIdForSession(sessionId);
  }

  private message(
    sessionId: string,
    id: string,
    role: AppMessage['role'],
    content: AppMessage['content'],
    createdAt: string,
  ): AppMessage {
    return {
      id,
      sessionId,
      role,
      content,
      createdAt,
      promptId: this.promptId(sessionId),
    };
  }

  private finishStage(sessionId: string, createdAt: string): void {
    const toolCallId = this.openStageBySession.get(sessionId);
    if (!toolCallId) return;
    this.emit(sessionId, {
      type: 'messageCreated',
      message: this.message(
        sessionId,
        `result_${toolCallId}`,
        'tool',
        [{ type: 'toolResult', toolCallId, output: '完成' }],
        createdAt,
      ),
    });
    this.openStageBySession.delete(sessionId);
  }

  private finishCall(
    sessionId: string,
    callId: string,
    createdAt: string,
    output: string,
    isError = false,
  ): void {
    const calls = this.openCallsBySession.get(sessionId);
    const toolCallId = calls?.get(callId);
    if (!toolCallId) return;
    this.emit(sessionId, {
      type: 'messageCreated',
      message: this.message(
        sessionId,
        `result_${toolCallId}`,
        'tool',
        [{ type: 'toolResult', toolCallId, output: output || (isError ? '失败' : '完成'), isError }],
        createdAt,
      ),
    });
    calls?.delete(callId);
  }

  private finishOpenCalls(sessionId: string, createdAt: string, isError = false): void {
    const calls = this.openCallsBySession.get(sessionId);
    if (!calls) return;
    for (const callId of [...calls.keys()]) {
      this.finishCall(sessionId, callId, createdAt, isError ? '任务中断' : '完成', isError);
    }
  }

  private async consume(
    sessionId: string,
    taskId: string,
    event: BackendJobEvent,
  ): Promise<void> {
    if (event.kind === 'usage') {
      const ctxUsed = Number(event.context_tokens ?? 0);
      const ctxMax = Number(event.max_context_tokens ?? QWEN38_MAX_CONTEXT_LIMIT);
      const currentSession = this.api.sessionCache.get(sessionId) || this.api.drafts.get(sessionId)?.session;
      const nextUsage: any = {
        ...(currentSession?.usage || EMPTY_USAGE),
        contextTokens: ctxUsed,
        contextLimit: ctxMax > 0 ? ctxMax : QWEN38_MAX_CONTEXT_LIMIT,
        inputTokens: Number((event as any).total_tokens ?? currentSession?.usage.inputTokens ?? 0),
      };
      if (currentSession) {
        currentSession.usage = nextUsage;
        this.api.sessionCache.set(sessionId, currentSession);
      }
      this.emit(sessionId, {
        type: 'sessionUsageUpdated',
        sessionId,
        usage: nextUsage,
        model: FIXED_MODEL,
      });
      return;
    }

    if (event.kind === 'compaction') {
      const tokensBefore = Number(event.tokensBefore ?? 0);
      const tokensAfter = Number(event.tokensAfter ?? 0);
      const currentSession = this.api.sessionCache.get(sessionId) || this.api.drafts.get(sessionId)?.session;
      const nextUsage: any = {
        ...(currentSession?.usage || EMPTY_USAGE),
        contextTokens: tokensAfter,
        contextLimit: QWEN38_MAX_CONTEXT_LIMIT,
      };
      if (currentSession) {
        currentSession.usage = nextUsage;
        this.api.sessionCache.set(sessionId, currentSession);
      }
      this.emit(sessionId, {
        type: 'sessionUsageUpdated',
        sessionId,
        usage: nextUsage,
        model: FIXED_MODEL,
      });
      this.emit(sessionId, {
        type: 'messageCreated',
        message: this.message(
          sessionId,
          `compaction_${sessionId}_${Date.now()}`,
          'assistant',
          [{
            type: 'text',
            text: `ℹ️ [上下文自动压缩] 上下文用量已达高水位阈值 (${tokensBefore}/${QWEN38_MAX_CONTEXT_LIMIT})，已自动通过 Qwen3.8-max 压缩提纯至 ${tokensAfter} Tokens。`,
          }],
          event.created_at,
        ),
      });
      return;
    }

    if (event.kind === 'status') {
      if (event.context_tokens !== undefined || event.max_context_tokens !== undefined) {
        const ctxUsed = Number(event.context_tokens ?? 0);
        const ctxMax = Number(event.max_context_tokens ?? QWEN38_MAX_CONTEXT_LIMIT);
        const currentSession = this.api.sessionCache.get(sessionId) || this.api.drafts.get(sessionId)?.session;
        const nextUsage: any = {
          ...(currentSession?.usage || EMPTY_USAGE),
          contextTokens: ctxUsed,
          contextLimit: ctxMax > 0 ? ctxMax : QWEN38_MAX_CONTEXT_LIMIT,
        };
        if (currentSession) {
          currentSession.usage = nextUsage;
          this.api.sessionCache.set(sessionId, currentSession);
        }
        this.emit(sessionId, {
          type: 'sessionUsageUpdated',
          sessionId,
          usage: nextUsage,
          model: FIXED_MODEL,
        });
      }
      const nextToolCallId = `stage_${sessionId}_${this.promptId(sessionId)}_${event.stage || event.id}`;
      const current = this.openStageBySession.get(sessionId);
      if (current && current !== nextToolCallId) this.finishStage(sessionId, event.created_at);
      if (!current || current !== nextToolCallId) {
        this.openStageBySession.set(sessionId, nextToolCallId);
        this.emit(sessionId, {
          type: 'messageCreated',
          message: this.message(
            sessionId,
            `message_${nextToolCallId}`,
            'assistant',
            [{
              type: 'toolUse',
              toolCallId: nextToolCallId,
              toolName: stageLabel(event.stage),
              input: `${event.message || stageLabel(event.stage)}${event.progress == null ? '' : ` · ${event.progress}%`}`,
            }],
            event.created_at,
          ),
        });
      } else if (event.message) {
        this.emit(sessionId, {
          type: 'toolOutput',
          sessionId,
          toolCallId: nextToolCallId,
          outputChunk: event.message,
          stream: 'stdout',
        });
      }
      return;
    }

    if (event.kind === 'model_start') {
      const toolCallId = `model_${sessionId}_${this.promptId(sessionId)}_${event.call_id || event.id}`;
      const calls = this.openCallsBySession.get(sessionId) ?? new Map<string, string>();
      calls.set(event.call_id || String(event.id), toolCallId);
      this.openCallsBySession.set(sessionId, calls);
      this.emit(sessionId, {
        type: 'messageCreated',
        message: this.message(
          sessionId,
          `message_${toolCallId}`,
          'assistant',
          [{
            type: 'toolUse',
            toolCallId,
            toolName: roleLabel(event.role),
            input: [event.model, event.round_number ? `第 ${event.round_number} 轮` : '']
              .filter(Boolean)
              .join(' · '),
          }],
          event.created_at,
        ),
      });
      return;
    }

    if (event.kind === 'model_delta') {
      const toolCallId = this.openCallsBySession
        .get(sessionId)
        ?.get(event.call_id || String(event.id));
      if (!toolCallId || !event.delta) return;
      this.emit(sessionId, {
        type: 'toolOutput',
        sessionId,
        toolCallId,
        outputChunk: event.delta,
        stream: 'stdout',
      });
      return;
    }

    if (event.kind === 'model_complete' || event.kind === 'model_error') {
      this.finishCall(
        sessionId,
        event.call_id || String(event.id),
        event.created_at,
        event.message,
        event.kind === 'model_error',
      );
      return;
    }

    if (
      event.kind === 'job_complete'
      || event.kind === 'job_failed'
      || event.kind === 'job_cancelled'
    ) {
      this.finishStage(sessionId, event.created_at);
      this.finishOpenCalls(sessionId, event.created_at, event.kind === 'job_failed');
      const [job, interactions] = await Promise.all([
        this.api.fetchJob(taskId),
        this.api.fetchInteractions(taskId),
      ]);
      const ctxUsed = Number((job as any).context_tokens ?? (job.manifest as any)?.context_tokens ?? 0);
      const ctxMax = Number((job as any).max_context_tokens ?? (job.manifest as any)?.max_context_tokens ?? QWEN38_MAX_CONTEXT_LIMIT);
      const finalUsage: any = {
        ...(this.api.sessionCache.get(sessionId)?.usage || EMPTY_USAGE),
        contextTokens: ctxUsed,
        contextLimit: ctxMax > 0 ? ctxMax : QWEN38_MAX_CONTEXT_LIMIT,
      };
      const existingSession = this.api.sessionCache.get(sessionId);
      if (existingSession) {
        existingSession.usage = finalUsage;
        this.api.sessionCache.set(sessionId, existingSession);
      }
      this.emit(sessionId, {
        type: 'sessionUsageUpdated',
        sessionId,
        usage: finalUsage,
        model: FIXED_MODEL,
      });
      const isComplete = event.kind === 'job_complete' && job.status === 'completed';
      const reason = event.kind === 'job_cancelled' ? 'cancelled' : event.kind === 'job_failed' ? 'failed' : 'completed';
      const latestInteraction = interactions.at(-1);
      const content: AppMessage['content'] = [{
        type: 'text',
        text: isComplete
          ? latestInteraction
            ? interactionSummary(job, latestInteraction)
            : resultSummary(job)
          : job.error || event.message || (reason === 'cancelled' ? '任务已取消。' : '任务执行失败。'),
      }];
      if (isComplete) {
        content.push(...resultMediaContent(
          taskId,
          `result_media_${sessionId}_${this.promptId(sessionId)}`,
          job.result?.graph_version,
        ));
      }
      this.emit(sessionId, {
        type: 'messageCreated',
        message: this.message(
          sessionId,
          `final_${sessionId}_${this.promptId(sessionId)}`,
          'assistant',
          content,
          event.created_at,
        ),
      });
      this.emit(sessionId, {
        type: 'sessionWorkChanged',
        sessionId,
        busy: false,
        mainTurnActive: false,
        pendingInteraction: 'none',
        lastTurnReason: reason === 'completed' ? 'completed' : reason,
      });
      this.emit(sessionId, {
        type: 'turnActiveChanged',
        sessionId,
        active: false,
        reason,
      });
      this.emit(sessionId, {
        type: 'promptCompleted',
        sessionId,
        promptId: this.promptId(sessionId),
        reason,
      });
      this.api.markTerminal(sessionId);
      this.sources.get(sessionId)?.close();
      this.sources.delete(sessionId);
    }
  }
}

export class MindmapAgentApi implements KimiWebApi {
  private readonly uploads = new Map<string, StoredUpload>();
  readonly drafts = new Map<string, SessionDraft>();
  private readonly taskBySession = new Map<string, string>();
  private readonly sessionByTask = new Map<string, string>();
  private readonly promptBySession = new Map<string, string>();
  private readonly terminalSessions = new Set<string>();
  private readonly connections = new Set<MindmapEventConnection>();
  private readonly titleOverrides = new Map<string, string>();
  readonly sessionCache = new Map<string, AppSession>();
  private healthCache: BackendHealth | null = null;

  async getHealth(): Promise<{ status: 'ok'; uptimeSec: number }> {
    await this.health();
    return { status: 'ok', uptimeSec: 0 };
  }

  async getMeta(): Promise<{
    serverVersion: string;
    serverId: string;
    startedAt: string;
    capabilities: Record<string, boolean>;
    openInApps: string[];
    dangerousBypassAuth: boolean;
    backend: 'v1' | 'v2';
  }> {
    return {
      serverVersion: 'mindmap-agent',
      serverId: WORKSPACE_ID,
      startedAt: nowIso(),
      capabilities: {},
      openInApps: [],
      dangerousBypassAuth: true,
      backend: 'v1',
    };
  }

  async listSessions(input?: PageRequest): Promise<Page<AppSession>> {
    const history = await parseResponse<BackendHistoryItem[]>(await fetch('/api/history?limit=100'));
    let items = history.map((item) => {
      const session = sessionFromHistory(item, this.titleOverrides.get(item.task_id));
      this.sessionCache.set(session.id, session);
      return session;
    });
    if (input?.beforeId) {
      const index = items.findIndex((item) => item.id === input.beforeId);
      items = index >= 0 ? items.slice(index + 1) : [];
    }
    const pageSize = input?.pageSize ?? items.length;
    return {
      items: items.slice(0, pageSize),
      hasMore: items.length > pageSize,
    };
  }

  async createSession(input: {
    title?: string;
    cwd?: string;
    model?: string;
    workspaceId?: string;
  }): Promise<AppSession> {
    const createdAt = nowIso();
    const session: AppSession = {
      id: uid('draft'),
      title: input.title || '新建会话',
      createdAt,
      updatedAt: createdAt,
      busy: false,
      mainTurnActive: false,
      pendingInteraction: 'none',
      archived: false,
      cwd: input.cwd || WORKSPACE_ROOT,
      model: FIXED_MODEL,
      usage: { ...EMPTY_USAGE },
      messageCount: 0,
      lastSeq: 0,
      workspaceId: input.workspaceId || WORKSPACE_ID,
    };
    this.drafts.set(session.id, { session });
    this.sessionCache.set(session.id, session);
    return session;
  }

  async getSession(sessionId: string): Promise<AppSession> {
    const draft = this.drafts.get(sessionId);
    if (draft) return draft.session;
    const taskId = this.taskIdForSession(sessionId) || sessionId;
    const [job, interactions] = await Promise.all([
      this.fetchJob(taskId),
      this.fetchInteractions(taskId),
    ]);
    return this.sessionFromJob(sessionId, job, interactions);
  }

  async updateSession(
    sessionId: string,
    input: {
      title?: string;
      cwd?: string;
      model?: string;
      permissionMode?: string;
      planMode?: boolean;
      swarmMode?: boolean;
      goalObjective?: string;
      goalControl?: 'pause' | 'resume' | 'cancel';
      thinking?: string;
    },
  ): Promise<AppSession> {
    if (input.title) this.titleOverrides.set(sessionId, input.title);
    const draft = this.drafts.get(sessionId);
    if (draft) {
      draft.session = {
        ...draft.session,
        title: input.title ?? draft.session.title,
        cwd: input.cwd ?? draft.session.cwd,
        model: FIXED_MODEL,
        updatedAt: nowIso(),
      };
      this.sessionCache.set(sessionId, draft.session);
      return draft.session;
    }
    const session = await this.getSession(sessionId);
    const updated = {
      ...session,
      title: input.title ?? session.title,
      cwd: input.cwd ?? session.cwd,
      model: FIXED_MODEL,
      updatedAt: nowIso(),
    };
    this.sessionCache.set(sessionId, updated);
    return updated;
  }

  async getSessionStatus(sessionId: string): Promise<AppSessionRuntimeStatus> {
    const taskId = this.taskIdForSession(sessionId);
    const job = taskId ? await this.fetchJob(taskId) : null;
    const ctxUsed = (job as any)?.context_tokens ?? (job as any)?.usage?.context_tokens ?? ((job?.manifest as any)?.context_tokens ?? 0);
    const ctxMax = (job as any)?.max_context_tokens ?? (job as any)?.usage?.max_context_tokens ?? ((job?.manifest as any)?.max_context_tokens ?? QWEN38_MAX_CONTEXT_LIMIT);
    const ctxUsage = (job as any)?.context_usage ?? (ctxMax > 0 ? ctxUsed / ctxMax : 0);
    return {
      model: FIXED_MODEL,
      thinkingEffort: 'off',
      permission: 'auto',
      planMode: false,
      swarmMode: isMultiAgentLoop(job?.loop_config),
      contextTokens: ctxUsed,
      maxContextTokens: ctxMax,
      contextUsage: ctxUsage,
    };
  }

  async getSessionGoal(): Promise<null> {
    return null;
  }

  async getSessionWarnings(): Promise<[]> {
    return [];
  }

  async archiveSession(sessionId: string): Promise<{ archived: true }> {
    const taskId = this.taskIdForSession(sessionId);
    if (taskId) {
      await parseResponse(await fetch(`/api/jobs/${encodeURIComponent(taskId)}`, { method: 'DELETE' }));
    }
    this.drafts.delete(sessionId);
    return { archived: true };
  }

  async restoreSession(sessionId: string): Promise<AppSession> {
    return this.getSession(sessionId);
  }

  async listMessages(sessionId: string): Promise<Page<AppMessage>> {
    const snapshot = await this.getSessionSnapshot(sessionId);
    return { items: [...snapshot.messages].reverse(), hasMore: false };
  }

  async getSessionSnapshot(sessionId: string): Promise<AppSessionSnapshot> {
    const draft = this.drafts.get(sessionId);
    if (draft && !this.taskIdForSession(sessionId)) {
      return {
        asOfSeq: 0,
        epoch: sessionId,
        session: draft.session,
        messages: [],
        hasMoreMessages: false,
        inFlightTurn: null,
        subagents: [],
        pendingApprovals: [],
        pendingQuestions: [],
      };
    }

    const taskId = this.taskIdForSession(sessionId) || sessionId;
    this.registerTask(sessionId, taskId);
    const [job, storedInteractions] = await Promise.all([
      this.fetchJob(taskId),
      this.fetchInteractions(taskId),
    ]);
    const fallbackInteraction: BackendInteraction = {
      id: `legacy_${taskId}`,
      kind: 'initial',
      instruction: '',
      created_at: this.sessionCache.get(sessionId)?.createdAt || nowIso(),
      base_graph_version: 0,
      result_graph_version: job.result?.graph_version,
      status: job.status,
      error: job.error,
    };
    const interactions = storedInteractions.length ? storedInteractions : [fallbackInteraction];
    const session = this.sessionFromJob(sessionId, job, interactions);
    this.sessionCache.set(sessionId, session);
    const filename = job.result?.document.filename || session.lastPrompt || session.title;
    const messages: AppMessage[] = [];
    let activePromptId = this.promptIdForSession(sessionId);
    let activeToolCallId = '';
    interactions.forEach((interaction, index) => {
      const isLast = index === interactions.length - 1;
      const promptId = isLast
        ? this.promptIdForSession(sessionId)
        : `prompt_${interaction.id}`;
      if (isLast) activePromptId = promptId;
      const userText =
        interaction.kind === 'initial'
          ? interaction.instruction
            ? `${interaction.instruction}\n\n处理文件：${filename}`
            : `请根据附件生成思维导图。\n\n处理文件：${filename}`
          : interaction.instruction;
      messages.push({
        id: `user_${sessionId}_${interaction.id}`,
        sessionId,
        role: 'user',
        content: [{ type: 'text', text: userText }],
        createdAt: interaction.created_at,
        promptId,
      });

      const assistantContent: AppMessage['content'] = [];
      if (interaction.status === 'queued' || interaction.status === 'running') {
        const toolCallId = `snapshot_stage_${sessionId}_${interaction.id}`;
        if (isLast) activeToolCallId = toolCallId;
        assistantContent.push({
          type: 'toolUse',
          toolCallId,
          toolName: stageLabel(job.stage),
          input: `${job.message || stageLabel(job.stage)} · ${job.progress}%`,
        });
      } else if (interaction.status === 'completed') {
        const version = interaction.result_graph_version;
        const isLatest = Boolean(version && version === job.result?.graph_version);
        if (isLatest) {
          const toolCallId = `snapshot_complete_${sessionId}_${interaction.id}`;
          assistantContent.push(
            {
              type: 'toolUse',
              toolCallId,
              toolName: interaction.kind === 'revision' ? '修改思维导图' : '生成思维导图',
              input: version ? `${filename} · v${version}` : filename,
            },
            { type: 'toolResult', toolCallId, output: '完成' },
            { type: 'text', text: interactionSummary(job, interaction) },
            ...resultMediaContent(
              taskId,
              `snapshot_media_${sessionId}_${interaction.id}`,
              version,
            ),
          );
        } else {
          assistantContent.push({ type: 'text', text: interactionSummary(job, interaction) });
        }
      } else {
        assistantContent.push({
          type: 'text',
          text:
            interaction.error
            || (interaction.status === 'cancelled' ? '任务已取消。' : '任务执行失败。'),
        });
      }
      messages.push({
        id: `assistant_${sessionId}_${interaction.id}`,
        sessionId,
        role: 'assistant',
        content: assistantContent,
        createdAt: interaction.created_at,
        promptId,
      });
    });

    if (job.status === 'completed' || job.status === 'failed' || job.status === 'cancelled') {
      this.markTerminal(sessionId);
    } else {
      this.markActive(sessionId);
    }

    return {
      asOfSeq: Math.max(job.progress, messages.length, 1),
      epoch: taskId,
      session,
      messages,
      hasMoreMessages: false,
      inFlightTurn:
        job.status === 'queued' || job.status === 'running'
          ? {
              turnId: 1,
              assistantText: '',
              thinkingText: '',
              runningTools: [{
                toolCallId: activeToolCallId || `snapshot_stage_${sessionId}`,
                name: stageLabel(job.stage),
                args: job.message,
                lastProgress: {
                  kind: job.stage,
                  text: job.message,
                  percent: job.progress,
                },
              }],
              promptId: activePromptId,
            }
          : null,
      subagents: [],
      pendingApprovals: [],
      pendingQuestions: [],
    };
  }

  async exportSession(sessionId: string): Promise<{ blob: Blob; fileName: string }> {
    const taskId = this.taskIdForSession(sessionId) || sessionId;
    const response = await fetch(`/api/jobs/${encodeURIComponent(taskId)}/export.json`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return {
      blob: await response.blob(),
      fileName: `mindmap-${taskId}.json`,
    };
  }

  async submitPrompt(sessionId: string, input: PromptSubmission): Promise<PromptSubmitResult> {
    const uploadContent = input.content.find((part) => part.type === 'file' || part.type === 'image' || part.type === 'video');
    const uploadId =
      uploadContent?.type === 'file'
        ? uploadContent.fileId
        : uploadContent?.type === 'image' || uploadContent?.type === 'video'
          ? uploadContent.source.kind === 'file'
            ? uploadContent.source.fileId
            : undefined
          : undefined;
    const upload = uploadId ? this.uploads.get(uploadId) : undefined;
    const promptText = input.content
      .filter((part): part is { type: 'text'; text: string } => part.type === 'text')
      .map((part) => part.text)
      .join('\n')
      .trim();
    const existingTaskId = this.taskIdForSession(sessionId);
    if (existingTaskId) {
      if (uploadId) {
        throw new Error('当前会话已绑定原始文件；请新建会话后再处理另一份文件。');
      }
      if (!promptText) {
        throw new Error('请输入你希望如何修改当前思维导图。');
      }
      const current = await this.fetchJob(existingTaskId);
      const graphVersion = current.result?.graph_version;
      if (!graphVersion) {
        throw new Error('当前任务还没有可供修改的图版本。');
      }
      await parseResponse<BackendJob>(
        await fetch(`/api/jobs/${encodeURIComponent(existingTaskId)}/refine`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            instruction: promptText,
            expected_graph_version: graphVersion,
          }),
        }),
      );
      const promptId = uid('prompt');
      this.promptBySession.set(sessionId, promptId);
      this.markActive(sessionId);
      const draft = this.drafts.get(sessionId);
      const cached = draft?.session || this.sessionCache.get(sessionId);
      if (cached) {
        const updated = {
          ...cached,
          lastPrompt: promptText,
          busy: true,
          mainTurnActive: true,
          updatedAt: nowIso(),
          currentPromptId: promptId,
          messageCount: cached.messageCount + 1,
        };
        this.sessionCache.set(sessionId, updated);
        if (draft) draft.session = updated;
      }
      for (const connection of this.connections) connection.taskAvailable(sessionId);
      return {
        promptId,
        userMessageId: uid('user'),
        status: 'running',
      };
    }

    const uploadIds = input.content
      .map((part) => {
        if (part.type === 'file') return part.fileId;
        if ((part.type === 'image' || part.type === 'video') && part.source.kind === 'file') return part.source.fileId;
        return undefined;
      })
      .filter((id): id is string => typeof id === 'string' && id.length > 0);

    const uploads = uploadIds
      .map((id) => this.uploads.get(id))
      .filter((u): u is StoredUpload => u !== undefined);

    if (uploads.length === 0 && upload) {
      uploads.push(upload);
    }

    if (uploads.length === 0) {
      throw new Error('请先附加 PDF、PPT、PPTX、DOC、DOCX、TXT 或 MD 文件。');
    }

        const displayTitle = uploads.map((u) => u.name).join(' & ');
    const model = FIXED_MODEL;
    const configuredLoop = drawingLoopConfig(input.swarmMode === true);
    const form = new FormData();
    for (const u of uploads) {
      const f = new File([u.blob], u.name, { type: u.mediaType });
      form.append('files', f);
      if (uploads.length === 1) {
        form.append('file', f);
      }
    }
    form.append('provider', 'qwen');
    form.append('model', model);
    form.append('use_ai', 'true');
    form.append('loop_config', JSON.stringify({
      ...configuredLoop,
      human_instruction: promptText,
    }));
    const job = await parseResponse<BackendJob>(
      await fetch('/api/jobs', { method: 'POST', body: form }),
    );
    const promptId = uid('prompt');
    this.promptBySession.set(sessionId, promptId);
    this.markActive(sessionId);
    this.registerTask(sessionId, job.id);
    const draft = this.drafts.get(sessionId);
    if (draft) {
      draft.promptText = promptText;
      draft.uploadId = uploadIds[0] || uploadId;
      draft.session = {
        ...draft.session,
        title: displayTitle || '思维导图任务',
        lastPrompt: promptText || displayTitle || '思维导图任务',
        busy: true,
        mainTurnActive: true,
        updatedAt: nowIso(),
        model,
        messageCount: 1,
      };
    }
    for (const connection of this.connections) connection.taskAvailable(sessionId);
    return {
      promptId,
      userMessageId: uid('user'),
      status: 'running',
    };
  }

  async steerPrompts(_sessionId: string, promptIds: string[]): Promise<{ steered: boolean; promptIds: string[] }> {
    return { steered: false, promptIds };
  }

  async abortPrompt(sessionId: string): Promise<{ aborted: boolean }> {
    return this.abortSession(sessionId);
  }

  async abortSession(sessionId: string): Promise<{ aborted: boolean }> {
    const taskId = this.taskIdForSession(sessionId);
    if (!taskId) return { aborted: false };
    await parseResponse(
      await fetch(`/api/jobs/${encodeURIComponent(taskId)}/cancel`, { method: 'POST' }),
    );
    return { aborted: true };
  }

  async compactSession(): Promise<void> {}
  async undoSession(): Promise<void> {}

  async forkSession(sessionId: string): Promise<AppSession> {
    const original = await this.getSession(sessionId);
    return this.createSession({
      title: `${original.title} 副本`,
      cwd: original.cwd,
      model: original.model,
      workspaceId: original.workspaceId,
    });
  }

  async createChildSession(sessionId: string): Promise<AppSession> {
    return this.forkSession(sessionId);
  }

  async listChildSessions(): Promise<AppSession[]> {
    return [];
  }

  async startBtw(): Promise<{ agentId: string }> {
    return { agentId: uid('side') };
  }

  async respondApproval(
    _sessionId: string,
    _approvalId: string,
    _response: ApprovalResponse,
  ): Promise<{ resolved: true; resolvedAt: string }> {
    return { resolved: true, resolvedAt: nowIso() };
  }

  async respondQuestion(
    _sessionId: string,
    _questionId: string,
    _response: QuestionResponse,
  ): Promise<{ resolved: true; resolvedAt: string }> {
    return { resolved: true, resolvedAt: nowIso() };
  }

  async dismissQuestion(): Promise<{ dismissed: true; dismissedAt: string }> {
    return { dismissed: true, dismissedAt: nowIso() };
  }

  async listSkills(): Promise<[]> {
    return [];
  }

  async listSkillsForWorkspace(): Promise<[]> {
    return [];
  }

  async activateSkill(_sessionId: string, skillName: string): Promise<{ activated: true; skillName: string }> {
    return { activated: true, skillName };
  }

  async listTasks(): Promise<AppTask[]> {
    return [];
  }

  async getTask(_sessionId: string, taskId: string): Promise<AppTask> {
    throw new Error(`任务 ${taskId} 不存在`);
  }

  async cancelTask(): Promise<{ cancelled: true }> {
    return { cancelled: true };
  }

  async listTerminals(): Promise<AppTerminal[]> {
    return [];
  }

  async createTerminal(): Promise<AppTerminal> {
    throw new Error('拓知暂不提供终端');
  }

  async getTerminal(): Promise<AppTerminal> {
    throw new Error('拓知暂不提供终端');
  }

  async closeTerminal(): Promise<{ closed: true }> {
    return { closed: true };
  }

  async listDirectory(): Promise<{ items: FsEntry[]; truncated: boolean }> {
    return { items: [], truncated: false };
  }

  async readFile(
    _sessionId: string,
    input: { path: string },
  ): Promise<{
    path: string;
    content: string;
    encoding: 'utf-8';
    size: number;
    truncated: boolean;
    etag: string;
    mime: string;
    isBinary: boolean;
  }> {
    return {
      path: input.path,
      content: '',
      encoding: 'utf-8',
      size: 0,
      truncated: false,
      etag: '',
      mime: 'text/plain',
      isBinary: false,
    };
  }

  async searchFiles(
    _workspace: string,
    _input: { query: string; limit?: number },
  ): Promise<{ items: Array<{ path: string; name: string; kind: FsKind; score: number; matchPositions: number[] }>; truncated: boolean }> {
    return { items: [], truncated: false };
  }

  async grepFiles(): Promise<{ files: []; filesScanned: number; truncated: boolean; elapsedMs: number }> {
    return { files: [], filesScanned: 0, truncated: false, elapsedMs: 0 };
  }

  async getGitStatus(): Promise<{
    branch: string;
    ahead: number;
    behind: number;
    entries: Record<string, string>;
    additions: number;
    deletions: number;
    pullRequest: null;
  }> {
    return {
      branch: 'main',
      ahead: 0,
      behind: 0,
      entries: {},
      additions: 0,
      deletions: 0,
      pullRequest: null,
    };
  }

  async getFileDiff(_sessionId: string, path: string): Promise<{ path: string; diff: string }> {
    return { path, diff: '' };
  }

  getFileDownloadUrl(): string {
    return '#';
  }

  async openFile(): Promise<{ opened: true }> {
    return { opened: true };
  }

  async revealFile(): Promise<{ revealed: true }> {
    return { revealed: true };
  }

  async openInApp(): Promise<void> {}

  connectEvents(handlers: KimiEventHandlers): KimiEventConnection {
    const connection = new MindmapEventConnection(this, handlers);
    this.connections.add(connection);
    return connection;
  }

  async listWorkspaces(): Promise<AppWorkspace[]> {
    const history = await parseResponse<BackendHistoryItem[]>(await fetch('/api/history?limit=100'));
    return [{
      id: WORKSPACE_ID,
      root: WORKSPACE_ROOT,
      name: '拓知 TopoMind',
      lastOpenedAt: history[0]?.updated_at,
      sessionCount: history.length,
    }];
  }

  async addWorkspace(): Promise<AppWorkspace> {
    return {
      id: WORKSPACE_ID,
      root: WORKSPACE_ROOT,
      name: '拓知 TopoMind',
      lastOpenedAt: nowIso(),
      sessionCount: 0,
    };
  }

  async updateWorkspace(_id: string, input: { name: string }): Promise<AppWorkspace> {
    return {
      id: WORKSPACE_ID,
      root: WORKSPACE_ROOT,
      name: input.name,
      lastOpenedAt: nowIso(),
      sessionCount: 0,
    };
  }

  async deleteWorkspace(): Promise<void> {}

  async browseFs(): Promise<FsBrowseResult> {
    return { path: WORKSPACE_ROOT, parent: null, entries: [] };
  }

  async getFsHome(): Promise<{ home: string; recentRoots: string[] }> {
    return { home: WORKSPACE_ROOT, recentRoots: [WORKSPACE_ROOT] };
  }

  async listModels(): Promise<AppModel[]> {
    return [{
      id: FIXED_MODEL,
      provider: 'qwen',
      model: FIXED_MODEL,
      displayName: FIXED_MODEL,
      maxContextSize: QWEN38_MAX_CONTEXT_LIMIT,
      capabilities: ['vision'],
      supportEfforts: [],
      defaultEffort: 'off',
    }];
  }

  async listProviders(): Promise<AppProvider[]> {
    const models = await this.listModels();
    return [{
      id: 'qwen',
      type: 'openai-compatible',
      defaultModel: await this.defaultModel(),
      hasApiKey: true,
      status: 'connected',
      models: models.map((model) => model.id),
    }];
  }

  async addProvider(input: {
    type: string;
    apiKey?: string;
    baseUrl?: string;
    defaultModel?: string;
  }): Promise<AppProvider> {
    return {
      id: 'qwen',
      type: input.type,
      baseUrl: input.baseUrl,
      defaultModel: input.defaultModel,
      hasApiKey: Boolean(input.apiKey),
      status: 'connected',
    };
  }

  async deleteProvider(): Promise<{ deleted: true }> {
    return { deleted: true };
  }

  async refreshProvider(): Promise<ProviderRefreshResult> {
    return { changed: [], unchanged: ['qwen'], failed: [] };
  }

  async refreshAllProviders(): Promise<ProviderRefreshResult> {
    return this.refreshProvider();
  }

  async refreshOAuthProviderModels(): Promise<ProviderRefreshResult> {
    return this.refreshProvider();
  }

  async uploadFile(input: { file: Blob; name?: string }): Promise<{
    id: string;
    name: string;
    mediaType: string;
    size: number;
  }> {
    const id = uid('upload');
    const name = input.name || (input.file instanceof File ? input.file.name : 'attachment');
    const mediaType = input.file.type || 'application/octet-stream';
    const stored = {
      blob: input.file,
      name,
      mediaType,
      size: input.file.size,
    };
    this.uploads.set(id, stored);
    return { id, name, mediaType, size: stored.size };
  }

  getFileUrl(fileId: string): string {
    const taskId = fileId.startsWith('mindmap_') ? fileId.slice('mindmap_'.length) : '';
    return taskId ? `/api/jobs/${encodeURIComponent(taskId)}/export.png` : '#';
  }

  async getFileBlob(fileId: string): Promise<Blob> {
    const upload = this.uploads.get(fileId);
    if (upload) return upload.blob;
    const taskId = fileId.startsWith('mindmap_') ? fileId.slice('mindmap_'.length) : '';
    if (!taskId) throw new Error('文件不存在');
    const response = await fetch(`/api/jobs/${encodeURIComponent(taskId)}/export.png`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.blob();
  }

  async getConfig(): Promise<AppConfig> {
    return {
      providers: {
        qwen: {
          type: 'openai-compatible',
          defaultModel: await this.defaultModel(),
          hasApiKey: true,
        },
      },
      defaultProvider: 'qwen',
      defaultModel: await this.defaultModel(),
      thinking: { enabled: false, effort: 'off' },
      planMode: false,
      defaultPlanMode: false,
    };
  }

  async setConfig(patch: Partial<AppConfig>): Promise<AppConfig> {
    return { ...(await this.getConfig()), ...patch };
  }

  async getAuth(): Promise<{
    ready: boolean;
    providersCount: number;
    defaultModel: string | null;
    managedProvider: { status: string } | null;
  }> {
    return {
      ready: true,
      providersCount: 1,
      defaultModel: await this.defaultModel(),
      managedProvider: null,
    };
  }

  async startOAuthLogin(): Promise<{
    flowId: string;
    provider: string;
    status: 'authenticated';
  }> {
    return { flowId: uid('auth'), provider: 'qwen', status: 'authenticated' };
  }

  async pollOAuthLogin(): Promise<null> {
    return null;
  }

  async cancelOAuthLogin(): Promise<{ cancelled: boolean; status: string }> {
    return { cancelled: true, status: 'cancelled' };
  }

  async logout(): Promise<{ loggedOut: boolean }> {
    return { loggedOut: false };
  }

  taskIdForSession(sessionId: string): string | undefined {
    return this.taskBySession.get(sessionId) || (sessionId.startsWith('draft_') ? undefined : sessionId);
  }

  promptIdForSession(sessionId: string): string {
    return this.promptBySession.get(sessionId) || `prompt_${sessionId}`;
  }

  isTerminal(sessionId: string): boolean {
    return this.terminalSessions.has(sessionId);
  }

  markTerminal(sessionId: string): void {
    this.terminalSessions.add(sessionId);
  }

  markActive(sessionId: string): void {
    this.terminalSessions.delete(sessionId);
  }

  dropConnection(connection: MindmapEventConnection): void {
    this.connections.delete(connection);
  }

  async fetchJob(taskId: string): Promise<BackendJob> {
    return parseResponse(await fetch(`/api/jobs/${encodeURIComponent(taskId)}`));
  }

  async fetchInteractions(taskId: string): Promise<BackendInteraction[]> {
    const response = await fetch(`/api/jobs/${encodeURIComponent(taskId)}/interactions`);
    if (response.status === 404) return [];
    return parseResponse(response);
  }

  private registerTask(sessionId: string, taskId: string): void {
    this.taskBySession.set(sessionId, taskId);
    this.sessionByTask.set(taskId, sessionId);
  }

  private async health(): Promise<BackendHealth> {
    if (this.healthCache) return this.healthCache;
    this.healthCache = await parseResponse<BackendHealth>(await fetch('/api/health'));
    return this.healthCache;
  }

  private async defaultModel(): Promise<string> {
    return FIXED_MODEL;
  }

  private sessionFromJob(
    sessionId: string,
    job: BackendJob,
    interactions: BackendInteraction[] = [],
  ): AppSession {
    const draft = this.drafts.get(sessionId)?.session;
    const cached = this.sessionCache.get(sessionId);
    const base = draft || cached;
    const title =
      this.titleOverrides.get(sessionId)
      || job.result?.document.title
      || job.result?.document.filename
      || base?.title
      || `任务 ${job.id.slice(0, 8)}`;
    const busy = job.status === 'queued' || job.status === 'running';
    const latestInteraction = interactions.at(-1);
    return {
      id: sessionId,
      title,
      createdAt: base?.createdAt || interactions[0]?.created_at || nowIso(),
      updatedAt: busy ? nowIso() : base?.updatedAt || nowIso(),
      busy,
      mainTurnActive: busy,
      pendingInteraction: 'none',
      lastTurnReason:
        job.status === 'completed'
          ? 'completed'
          : job.status === 'failed'
            ? 'failed'
            : job.status === 'cancelled'
              ? 'cancelled'
              : undefined,
      archived: false,
      currentPromptId: this.promptIdForSession(sessionId),
      lastPrompt:
        latestInteraction?.instruction
        || base?.lastPrompt
        || job.result?.document.filename
        || base?.title,
      cwd: WORKSPACE_ROOT,
      model: FIXED_MODEL,
      usage: {
        ...EMPTY_USAGE,
        contextTokens: (job as any).context_tokens ?? ((job.manifest as any)?.context_tokens ?? 0),
        contextLimit: (job as any).max_context_tokens ?? ((job.manifest as any)?.max_context_tokens ?? QWEN38_MAX_CONTEXT_LIMIT),
        turnCount: Math.max(interactions.length, 1),
      },
      messageCount: interactions.length ? interactions.length * 2 : job.status === 'completed' ? 2 : 1,
      lastSeq: job.progress,
      workspaceId: WORKSPACE_ID,
    };
  }
}
