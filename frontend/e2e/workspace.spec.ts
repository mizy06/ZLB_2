import { readFile } from "node:fs/promises";

import { expect, test } from "@playwright/test";

const accessToken = process.env.MINDMAP_E2E_TOKEN;

test.beforeEach(async ({ page }) => {
  if (!accessToken) {
    throw new Error("MINDMAP_E2E_TOKEN is required for production E2E.");
  }
  await page.route("**/api/models?*", async (route) => {
    await route.fulfill({
      status: 502,
      contentType: "application/json",
      body: JSON.stringify({ detail: "provider unavailable in E2E" }),
    });
  });
});

test("session, local workflow, history, and downloads survive model-list failure", async ({
  page,
}, testInfo) => {
  await page.goto("/");

  await expect(page.getByText("生产工作台鉴权")).toBeVisible();
  await page.getByPlaceholder("访问令牌").fill(accessToken!);
  await page.getByRole("button", { name: "进入工作台" }).click();

  await expect(page.getByText("生产工作台鉴权")).toBeHidden();
  await expect(page.getByRole("button", { name: "历史记录" })).toBeEnabled();
  await expect(page.getByText("模型列表不可用")).toBeVisible();

  await page.getByRole("button", { name: "载入机器学习示例" }).click();
  await page
    .locator(".toggle-row input[type=checkbox]")
    .uncheck({ force: true });
  await page.getByRole("button", { name: "开始构建" }).click();

  await expect(
    page.getByRole("heading", {
      level: 1,
      name: "机器学习基础",
      exact: true,
    }),
  ).toBeVisible({ timeout: 60_000 });
  await expect(page.getByLabel("课程思维导图")).toBeVisible();
  await expect(page.getByText("导图画布加载失败")).toHaveCount(0);

  const [jsonDownload] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("link", { name: "保存 JSON" }).click(),
  ]);
  const jsonPath = await jsonDownload.path();
  expect(jsonPath).not.toBeNull();
  const exported = JSON.parse(await readFile(jsonPath!, "utf-8"));
  expect(exported.document.title).toBe("机器学习基础");
  expect(exported.nodes.length).toBeGreaterThan(0);

  const [pngDownload] = await Promise.all([
    page.waitForEvent("download"),
    page.getByLabel("保存 PNG").click(),
  ]);
  const pngPath = await pngDownload.path();
  expect(pngPath).not.toBeNull();
  const png = await readFile(pngPath!);
  expect(png.subarray(0, 8)).toEqual(
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
  );

  await page.getByRole("button", { name: "历史记录" }).click();
  await expect(page.getByRole("dialog", { name: "历史记录" })).toBeVisible();
  await expect(page.getByText("机器学习基础", { exact: true }).first()).toBeVisible();

  const horizontalOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth,
  );
  expect(horizontalOverflow).toBeLessThanOrEqual(1);

  await page.screenshot({
    path: testInfo.outputPath(`${testInfo.project.name}-workspace.png`),
    fullPage: true,
  });
});
