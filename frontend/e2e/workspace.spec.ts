import { expect, test } from '@playwright/test';
import { fileURLToPath } from 'node:url';

const TASK_ID = 'task-preview';
const CREATED_AT = '2026-08-04T00:30:47.283787+00:00';
const UPDATED_AT = '2026-08-04T00:38:44.807583+00:00';
const PNG_1X1 = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Zl1sAAAAASUVORK5CYII=',
  'base64',
);
const PPTX_PATH = fileURLToPath(new URL('../../test/18任意项级数.pptx', import.meta.url));

const historyItem = {
  task_id: TASK_ID,
  title: 'RNA 加工知识导图',
  filename: 'RNA Processing I.pptx',
  file_type: 'pptx',
  mode: 'standard',
  extraction_mode: 'qwen',
  graph_version: 2,
  node_count: 37,
  review_count: 0,
  quality_gate_passed: true,
  created_at: CREATED_AT,
  updated_at: UPDATED_AT,
  status: 'completed',
  stage: 'complete',
  progress: 100,
  error: null,
};

const completedJob = {
  id: TASK_ID,
  status: 'completed',
  stage: 'complete',
  progress: 100,
  message: '思维导图已生成',
  mode: 'standard',
  loop_config: {
    rounds: [{ editor_model: 'qwen3.8-max-preview' }],
  },
  result: {
    task_id: TASK_ID,
    graph_version: 2,
    root_id: 'root',
    nodes: [{ id: 'root' }],
    tree_edges: [],
    cross_links: [],
    warnings: [],
    document: {
      filename: historyItem.filename,
      title: historyItem.title,
    },
    quality_report: {
      quality_gate_passed: true,
    },
  },
  error: null,
};

const interactions = [
  {
    id: 'interaction-preview',
    kind: 'initial',
    instruction: '请为初学者梳理 RNA 加工的关键步骤和概念关系。',
    created_at: CREATED_AT,
    base_graph_version: 0,
    result_graph_version: 1,
    status: 'completed',
    error: null,
  },
  {
    id: 'interaction-revision',
    kind: 'revision',
    instruction: '合并重复分支，并把关键步骤调整为更清晰的学习顺序。',
    created_at: UPDATED_AT,
    base_graph_version: 1,
    result_graph_version: 2,
    status: 'completed',
    error: null,
  },
];

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('kimi-web.onboarded', '1');
    localStorage.setItem('kimi-locale', 'zh');
  });

  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());
    if (!url.pathname.startsWith('/api/')) {
      await route.continue();
      return;
    }
    if (url.pathname === '/api/health') {
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({
          status: 'ok',
          default_model: 'qwen3.8-max-preview',
          providers: {
            qwen: {
              configured: true,
              default_model: 'qwen3.8-max-preview',
            },
          },
        }),
      });
      return;
    }
    if (url.pathname === '/api/models') {
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({
          models: ['qwen3.8-max-preview'],
          count: 1,
        }),
      });
      return;
    }
    if (url.pathname === '/api/history') {
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify([historyItem]),
      });
      return;
    }
    if (url.pathname === `/api/jobs/${TASK_ID}`) {
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify(completedJob),
      });
      return;
    }
    if (url.pathname === `/api/jobs/${TASK_ID}/interactions`) {
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify(interactions),
      });
      return;
    }
    if (url.pathname === `/api/jobs/${TASK_ID}/export.png`) {
      await route.fulfill({
        contentType: 'image/png',
        body: PNG_1X1,
      });
      return;
    }
    await route.fulfill({
      status: 404,
      contentType: 'application/json',
      body: JSON.stringify({ detail: `Unhandled E2E route: ${url.pathname}` }),
    });
  });
});

test('TopoMind shell renders branded navigation, collapsible actions, and full-resolution media', async ({
  page,
}, testInfo) => {
  const errors: string[] = [];
  page.on('console', (message) => {
    if (message.type() === 'error') errors.push(message.text());
  });
  page.on('pageerror', (error) => errors.push(error.message));

  await page.goto('/');

  await expect(page).toHaveTitle('TopoMind');
  if (testInfo.project.name === 'desktop-chromium') {
    await expect(page.locator('.ch-name')).toHaveText('拓知');
    await expect(page.locator('.ch-logo .brand-mark')).toBeVisible();
    await expect(page.locator('.model-pill-fixed')).toHaveText('qwen3.8-max');
    await expect(page.getByRole('button', { name: /qwen3\.8-max/ })).toHaveCount(0);
    await page.locator('.mode-pill').click();
    await expect(page.getByRole('menuitemradio', { name: /单 Agent 绘图/ })).toBeVisible();
    await expect(page.getByRole('menuitemradio', { name: /Multi-Agent 绘图/ })).toBeVisible();
  } else {
    await expect(page.getByRole('button', { name: '切换会话 / 工作区' })).toHaveCount(0);
    await expect(page.locator('.mobile-brand')).toBeVisible();
    await page.getByRole('button', { name: '会话设置' }).click();
    const settings = page.getByRole('dialog');
    await expect(settings.getByText('qwen3.8-max', { exact: true })).toBeVisible();
    await expect(settings.getByRole('tab', { name: '单 Agent 绘图' })).toBeVisible();
    await expect(settings.getByRole('tab', { name: 'Multi-Agent 绘图' })).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(settings).toBeHidden();
  }
  await expect(page.locator('.ch-backend:visible')).toHaveCount(0);
  await expect(
    page
      .locator('.u-bub .u-text')
      .filter({ hasText: '请为初学者梳理 RNA 加工的关键步骤和概念关系。' })
      .last(),
  ).toContainText('请为初学者梳理 RNA 加工的关键步骤和概念关系。');
  await expect(
    page
      .locator('.u-bub .u-text')
      .filter({ hasText: '合并重复分支，并把关键步骤调整为更清晰的学习顺序。' })
      .last(),
  ).toContainText('合并重复分支，并把关键步骤调整为更清晰的学习顺序。');
  await expect(page.getByText(/已按你的要求更新到 v2/)).toBeVisible();

  const action = page.locator('.box').first();
  await expect(action.locator('.bh')).toContainText('修改思维导图');
  await expect(action.locator('.bh')).toContainText(historyItem.filename);
  await expect(action).not.toHaveClass(/\bopen\b/);
  await action.locator('.bh').click();
  await expect(action).toHaveClass(/\bopen\b/);

  const thumbnail = page.locator('.media-image').first();
  await expect(thumbnail).toBeVisible();
  await expect
    .poll(() => thumbnail.evaluate((image) => image.naturalWidth))
    .toBeGreaterThan(0);

  await page.locator('.media-image-button').first().click();
  const previewImage = page.locator('.file-preview .fp-image');
  await expect(previewImage).toBeVisible();
  await expect
    .poll(() => previewImage.evaluate((image) => image.naturalWidth))
    .toBeGreaterThan(0);

  const visibleText = await page.locator('body').innerText();
  expect(visibleText).not.toMatch(
    /KIMI|Kimi|Moonshot|审批|批准|权限|Approval|Permission|YOLO/,
  );
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth,
    ),
  ).toBeLessThanOrEqual(1);
  expect(errors).toEqual([]);

  await page.screenshot({
    path: testInfo.outputPath(`${testInfo.project.name}-topomind-shell.png`),
    fullPage: true,
  });
});

test('empty conversation omits helper copy and workspace switch controls', async ({ page }, testInfo) => {
  await page.route('**/api/history', async (route) => {
    await route.fulfill({
      contentType: 'application/json',
      body: '[]',
    });
  });

  await page.goto('/');

  await expect(page.getByText('还没有消息 —— 在下方输入开始对话', { exact: true })).toHaveCount(0);
  await expect(page.locator('.ws-pick-btn')).toHaveCount(0);
  await expect(page.locator('.empty-add-workspace')).toHaveCount(0);
  if (testInfo.project.name === 'mobile-chromium') {
    await expect(page.getByRole('button', { name: '切换会话 / 工作区' })).toHaveCount(0);
  }
});

test('PPTX attachment works without crypto.randomUUID', async ({ page }) => {
  await page.addInitScript(() => {
    if (typeof Crypto !== 'undefined') {
      Object.defineProperty(Crypto.prototype, 'randomUUID', {
        configurable: true,
        value: undefined,
      });
    }
  });

  await page.goto('/');
  await expect(page.getByText(/已按你的要求更新到 v2/)).toBeVisible();
  const input = page.locator('input[type="file"]');
  await expect(input).toHaveAttribute(
    'accept',
    '.pdf,.ppt,.pptx,.doc,.docx,.txt,.md,.markdown',
  );
  await input.setInputFiles(PPTX_PATH);

  const chip = page.locator('.att-chip').filter({ hasText: '18任意项级数.pptx' });
  await expect(chip).toBeVisible();
  await expect(chip).not.toHaveClass(/\buploading\b/);
  await expect(chip).not.toHaveClass(/\bis-error\b/);
});
