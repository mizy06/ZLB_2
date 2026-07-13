import type { Health, Job } from "./types";

async function parseResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `请求失败：HTTP ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export async function getHealth(): Promise<Health> {
  return parseResponse(await fetch("/api/health"));
}

export async function getModels(provider: string): Promise<string[]> {
  const result = await parseResponse<{ models: string[] }>(
    await fetch(`/api/models?provider=${encodeURIComponent(provider)}`),
  );
  return result.models;
}

export async function checkModel(
  provider: string,
  model: string,
): Promise<{ ok: boolean; message: string }> {
  const form = new FormData();
  form.append("provider", provider);
  form.append("model", model);
  return parseResponse(
    await fetch("/api/model-check", { method: "POST", body: form }),
  );
}

export async function createJob(
  file: File,
  provider: string,
  model: string,
  useAi: boolean,
): Promise<Job> {
  const form = new FormData();
  form.append("file", file);
  form.append("provider", provider);
  form.append("model", model);
  form.append("use_ai", String(useAi));
  return parseResponse(
    await fetch("/api/jobs", { method: "POST", body: form }),
  );
}

export async function getJob(id: string): Promise<Job> {
  return parseResponse(await fetch(`/api/jobs/${id}`));
}
