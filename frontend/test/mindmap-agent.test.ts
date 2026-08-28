import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { contextUsageFromSource, MindmapAgentApi } from '../src/api/mindmapAgent';

function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

const completedJob = {
  id: 'task_1',
  status: 'completed',
  stage: 'complete',
  progress: 100,
  message: '思维导图已生成',
  mode: 'standard',
  loop_config: { rounds: [{ editor_model: 'qwen3.8-max-preview' }] },
  result: {
    task_id: 'task_1',
    graph_version: 1,
    root_id: 'root',
    nodes: [{ id: 'root' }, { id: 'child' }],
    tree_edges: [{ source: 'root', target: 'child' }],
    cross_links: [],
    document: { filename: 'course.md', title: '课程' },
    quality_report: { quality_gate_passed: true },
  },
  error: null,
} as const;

describe('MindmapAgentApi human loop', () => {
  beforeEach(() => {
    if (typeof File === 'undefined') {
      class TestFile extends Blob {
        readonly name: string;
        readonly lastModified = 0;

        constructor(parts: BlobPart[], name: string, options?: FilePropertyBag) {
          super(parts, options);
          this.name = name;
        }
      }
      vi.stubGlobal('File', TestFile);
    }
    vi.stubGlobal('fetch', vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('sends the first natural-language requirement and refines without another attachment', async () => {
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    vi.mocked(fetch).mockImplementation(async (input, init) => {
      const url = String(input);
      requests.push({ url, init });
      if (url === '/api/health') {
        return json({
          default_model: 'qwen3.8-max-preview',
          architecture: {
            loop: {
              example: {
                rounds: [{ editor_model: 'qwen3.8-max-preview' }],
              },
            },
          },
        });
      }
      if (url === '/api/jobs' && init?.method === 'POST') {
        return json({ ...completedJob, status: 'queued', stage: 'queued', progress: 0, result: null });
      }
      if (url === '/api/jobs/task_1') return json(completedJob);
      if (url === '/api/jobs/task_1/refine') {
        return json({ ...completedJob, status: 'queued', stage: 'queued', progress: 0 });
      }
      throw new Error(`unexpected request: ${url}`);
    });

    const api = new MindmapAgentApi();
    const session = await api.createSession({});
    const upload = await api.uploadFile({
      file: new Blob(['# 课程'], { type: 'text/markdown' }),
      name: 'course.md',
    });

    await api.submitPrompt(session.id, {
      model: 'qwen3.8-max-preview',
      content: [
        { type: 'text', text: '面向初学者，突出概念之间的关系' },
        {
          type: 'file',
          fileId: upload.id,
          name: upload.name,
          mediaType: upload.mediaType,
          size: upload.size,
        },
      ],
    });
    await api.submitPrompt(session.id, {
      content: [{ type: 'text', text: '把重复的两个分支合并' }],
    });

    const createRequest = requests.find((item) => item.url === '/api/jobs');
    const form = createRequest?.init?.body as FormData;
    const loopConfig = JSON.parse(String(form.get('loop_config')));
    const refineRequest = requests.find((item) => item.url.endsWith('/refine'));

    expect(form.get('model')).toBe('qwen3.8-max');
    expect(loopConfig.rounds).toEqual([{ editor_model: 'qwen3.8-max' }]);
    expect(loopConfig.human_instruction).toBe('面向初学者，突出概念之间的关系');
    expect(JSON.parse(String(refineRequest?.init?.body))).toEqual({
      instruction: '把重复的两个分支合并',
      expected_graph_version: 1,
    });
  });

  it('uses a fixed two-round four-role loop for multi-agent drawing', async () => {
    const multiAgentRounds = Array.from({ length: 2 }, () => ({
      editor_model: 'qwen3.8-max',
      content_omission_model: 'qwen3.8-max',
      pruning_model: 'qwen3.8-max',
      multilevel_structure_model: 'qwen3.8-max',
    }));
    const multiAgentJob = {
      ...completedJob,
      loop_config: { rounds: multiAgentRounds },
    };
    let createForm: FormData | null = null;

    vi.mocked(fetch).mockImplementation(async (input, init) => {
      const url = String(input);
      if (url === '/api/jobs' && init?.method === 'POST') {
        createForm = init.body as FormData;
        return json({
          ...multiAgentJob,
          status: 'queued',
          stage: 'queued',
          progress: 0,
          result: null,
        });
      }
      if (url === '/api/jobs/task_1') return json(multiAgentJob);
      throw new Error(`unexpected request: ${url}`);
    });

    const api = new MindmapAgentApi();
    const session = await api.createSession({ model: 'another-model' });
    const upload = await api.uploadFile({
      file: new Blob(['# 课程'], { type: 'text/markdown' }),
      name: 'course.md',
    });

    await api.submitPrompt(session.id, {
      model: 'another-model',
      swarmMode: true,
      content: [
        { type: 'text', text: '先生成，再进行两轮多角色删改' },
        {
          type: 'file',
          fileId: upload.id,
          name: upload.name,
          mediaType: upload.mediaType,
          size: upload.size,
        },
      ],
    });

    expect(createForm?.get('model')).toBe('qwen3.8-max');
    expect(JSON.parse(String(createForm?.get('loop_config'))).rounds).toEqual(multiAgentRounds);
    await expect(api.getSessionStatus(session.id)).resolves.toMatchObject({
      model: 'qwen3.8-max',
      swarmMode: true,
    });
  });

  it('exposes only qwen3.8-max and ignores stored preview model names', async () => {
    vi.mocked(fetch).mockImplementation(async (input) => {
      const url = String(input);
      if (url === '/api/jobs/task_1') return json(completedJob);
      throw new Error(`unexpected request: ${url}`);
    });

    const api = new MindmapAgentApi();
    await expect(api.listModels()).resolves.toEqual([
      expect.objectContaining({
        id: 'qwen3.8-max',
        model: 'qwen3.8-max',
        displayName: 'qwen3.8-max',
      }),
    ]);
    await expect(api.getSessionStatus('task_1')).resolves.toMatchObject({
      model: 'qwen3.8-max',
      swarmMode: false,
    });
  });

  it('normalizes live and manifest context usage for the composer ring', () => {
    expect(contextUsageFromSource({
      context_usage: 0.25,
      max_context_tokens: 131072,
    })).toEqual({
      contextTokens: 250000,
      contextLimit: 1000000,
    });
    expect(contextUsageFromSource({
      manifest: {
        context_tokens: 45000,
        max_context_tokens: 131072,
        context_usage: 45000 / 131072,
      },
    })).toEqual({
      contextTokens: 45000,
      contextLimit: 1000000,
    });
  });

  it('reads persisted context usage from a job manifest in session status', async () => {
    vi.mocked(fetch).mockImplementation(async (input) => {
      const url = String(input);
      if (url === '/api/jobs/task_1') {
        return json({
          ...completedJob,
          context_tokens: 45000,
          max_context_tokens: 1000000,
          context_usage: 45000 / 1000000,
        });
      }
      throw new Error(`unexpected request: ${url}`);
    });

    const api = new MindmapAgentApi();
    await expect(api.getSessionStatus('task_1')).resolves.toMatchObject({
      contextTokens: 45000,
      maxContextTokens: 1000000,
      contextUsage: 45000 / 1000000,
    });
  });

  it('does not restore backend progress percentages into active tool calls', async () => {
    vi.mocked(fetch).mockImplementation(async (input) => {
      const url = String(input);
      if (url === '/api/jobs/task_1') {
        return json({
          ...completedJob,
          status: 'running',
          stage: 'editorial_draft',
          progress: 47,
          message: '主编正在生成初稿',
          result: null,
        });
      }
      if (url === '/api/jobs/task_1/interactions') {
        return json([{
          id: 'interaction_1',
          kind: 'initial',
          instruction: '生成导图',
          created_at: '2026-08-10T01:00:00+00:00',
          base_graph_version: 0,
          result_graph_version: null,
          status: 'running',
          error: null,
        }]);
      }
      throw new Error(`unexpected request: ${url}`);
    });

    const snapshot = await new MindmapAgentApi().getSessionSnapshot('task_1');
    const toolUse = snapshot.messages.at(-1)?.content.find(
      (part) => part.type === 'toolUse',
    );

    expect(toolUse).toMatchObject({
      type: 'toolUse',
      input: '主编正在生成初稿',
    });
    expect(JSON.stringify(toolUse)).not.toContain('47%');
    expect(snapshot.inFlightTurn?.runningTools[0]?.lastProgress).toEqual({
      kind: 'editorial_draft',
      text: '主编正在生成初稿',
    });
  });

  it('projects compaction as transcript activity instead of a tool call', async () => {
    class TestEventSource {
      static instances: TestEventSource[] = [];
      onopen: (() => void) | null = null;
      onmessage: ((message: { data: string }) => void) | null = null;
      onerror: (() => void) | null = null;

      constructor(readonly url: string) {
        TestEventSource.instances.push(this);
      }

      close(): void {}

      emit(event: Record<string, unknown>): void {
        this.onmessage?.({ data: JSON.stringify(event) });
      }
    }

    vi.stubGlobal('EventSource', TestEventSource);
    const events: unknown[] = [];
    const api = new MindmapAgentApi();
    const connection = api.connectEvents({
      onEvent: (event) => events.push(event),
      onResync: () => {},
      onError: () => {},
      onConnectionChange: () => {},
    });

    connection.subscribe('task_1');
    const source = TestEventSource.instances[0];
    expect(source?.url).toBe('/api/jobs/task_1/events');

    source?.emit({
      id: 1,
      task_id: 'task_1',
      kind: 'compaction_started',
      trigger: 'preflight_visual',
      created_at: '2026-08-10T01:00:00+00:00',
      stage: '',
      message: '',
      call_id: '',
      role: '',
      model: '',
      delta: '',
    });
    source?.emit({
      id: 2,
      task_id: 'task_1',
      kind: 'compaction',
      tokensBefore: 120000,
      tokensAfter: 39000,
      summary: '保留了可追溯的视觉证据。',
      created_at: '2026-08-10T01:00:01+00:00',
      stage: '',
      message: '',
      call_id: '',
      role: '',
      model: '',
      delta: '',
    });
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(events).toContainEqual({
      type: 'compactionStarted',
      sessionId: 'task_1',
      trigger: 'auto',
    });
    expect(events).toContainEqual({
      type: 'compactionCompleted',
      sessionId: 'task_1',
      tokensBefore: 120000,
      tokensAfter: 39000,
      summary: '保留了可追溯的视觉证据。',
    });
    expect(JSON.stringify(events)).not.toContain('"toolUse"');
  });

  it('stages uploads when randomUUID is unavailable on an insecure HTTP origin', async () => {
    vi.stubGlobal('crypto', {});

    const api = new MindmapAgentApi();
    const session = await api.createSession({});
    const upload = await api.uploadFile({
      file: new Blob(['pptx-bytes'], {
        type: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
      }),
      name: 'lesson.pptx',
    });

    expect(session.id).toMatch(/^draft_/);
    expect(upload.id).toMatch(/^upload_/);
    expect(upload.name).toBe('lesson.pptx');
  });

  it('rebuilds a multi-turn snapshot and cache-busts the latest graph image', async () => {
    vi.mocked(fetch).mockImplementation(async (input) => {
      const url = String(input);
      if (url === '/api/jobs/task_1') {
        return json({
          ...completedJob,
          result: { ...completedJob.result, graph_version: 2 },
        });
      }
      if (url === '/api/jobs/task_1/interactions') {
        return json([
          {
            id: 'interaction_1',
            kind: 'initial',
            instruction: '面向初学者',
            created_at: '2026-08-10T01:00:00+00:00',
            base_graph_version: 0,
            result_graph_version: 1,
            status: 'completed',
            error: null,
          },
          {
            id: 'interaction_2',
            kind: 'revision',
            instruction: '合并重复分支',
            created_at: '2026-08-10T02:00:00+00:00',
            base_graph_version: 1,
            result_graph_version: 2,
            status: 'completed',
            error: null,
          },
        ]);
      }
      throw new Error(`unexpected request: ${url}`);
    });

    const snapshot = await new MindmapAgentApi().getSessionSnapshot('task_1');
    const latestAssistant = snapshot.messages.at(-1);
    const mediaResult = latestAssistant?.content.find(
      (part) => part.type === 'toolResult' && JSON.stringify(part.output).includes('image_url'),
    );

    expect(snapshot.messages).toHaveLength(4);
    expect(snapshot.messages[0]?.content).toEqual([
      { type: 'text', text: '面向初学者\n\n处理文件：course.md' },
    ]);
    expect(snapshot.messages[2]?.content).toEqual([
      { type: 'text', text: '合并重复分支' },
    ]);
    expect(JSON.stringify(mediaResult)).toContain('/api/jobs/task_1/export.png?v=2');
    expect(snapshot.session.usage.turnCount).toBe(2);
  });
});
