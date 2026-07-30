import type {
  AnalysisResult,
  Health,
  HistoryItem,
  Job,
  ModelProvider,
  ReviewResolution,
} from "./types";

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

export async function createSession(token: string): Promise<void> {
  await parseResponse(
    await fetch("/api/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
    }),
  );
}

export async function getModels(provider: ModelProvider): Promise<string[]> {
  const result = await parseResponse<{ models: string[] }>(
    await fetch(`/api/models?provider=${encodeURIComponent(provider)}`),
  );
  return result.models;
}

export async function checkModel(
  provider: ModelProvider,
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
  provider: ModelProvider,
  model: string,
  useAi: boolean,
  mode: "standard" | "precision",
): Promise<Job> {
  const form = new FormData();
  form.append("file", file);
  form.append("provider", provider);
  form.append("model", model);
  form.append("use_ai", String(useAi));
  form.append("mode", mode);
  return parseResponse(
    await fetch("/api/jobs", { method: "POST", body: form }),
  );
}

export async function getJob(id: string): Promise<Job> {
  return parseResponse(await fetch(`/api/jobs/${id}`));
}

export async function cancelJob(id: string): Promise<Job> {
  return parseResponse(
    await fetch(`/api/jobs/${id}/cancel`, { method: "POST" }),
  );
}

export async function getHistory(): Promise<HistoryItem[]> {
  return parseResponse(await fetch("/api/history"));
}

export async function deleteJob(id: string): Promise<void> {
  await parseResponse(
    await fetch(`/api/jobs/${id}`, {
      method: "DELETE",
    }),
  );
}

export async function resolveReview(
  taskId: string,
  reviewId: string,
  resolution: ReviewResolution,
  expectedGraphVersion: number,
): Promise<AnalysisResult> {
  const response = await parseResponse<{ result: AnalysisResult }>(
    await fetch(`/api/jobs/${taskId}/reviews/${reviewId}/resolve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ...resolution,
        expected_graph_version: expectedGraphVersion,
      }),
    }),
  );
  return response.result;
}
