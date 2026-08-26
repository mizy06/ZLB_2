import type { JobEvent } from "./types";

const MAX_CALL_OUTPUT_CHARS = 160_000;

export type LiveModelCall = {
  callId: string;
  roundNumber: number;
  role: string;
  model: string;
  stage: string;
  status: "running" | "completed" | "failed";
  output: string;
  message: string;
  startedAt: string;
};

export type LiveStageStep = {
  id: string;
  stage: string;
  progress: number | null;
  message: string;
  status: "running" | "completed" | "failed" | "cancelled";
  startedAt: string;
  updatedAt: string;
};

export type JobStreamState = {
  calls: LiveModelCall[];
  steps: LiveStageStep[];
  lastEventId: number;
};

export const emptyJobStreamState = (): JobStreamState => ({
  calls: [],
  steps: [],
  lastEventId: 0,
});

export function mergeJobEvents(
  state: JobStreamState,
  events: JobEvent[],
): JobStreamState {
  const calls = state.calls.map((call) => ({ ...call }));
  const steps = state.steps.map((step) => ({ ...step }));
  const byId = new Map(calls.map((call) => [call.callId, call]));
  const byStage = new Map(steps.map((step) => [step.stage, step]));
  let lastEventId = state.lastEventId;

  for (const event of [...events].sort((left, right) => left.id - right.id)) {
    if (event.id <= lastEventId) continue;
    lastEventId = event.id;
    if (event.kind === "status" && event.stage) {
      for (const step of steps) {
        if (step.stage !== event.stage && step.status === "running") {
          step.status = "completed";
          step.updatedAt = event.created_at;
        }
      }
      let step = byStage.get(event.stage);
      if (!step) {
        const created: LiveStageStep = {
          id: `stage:${event.stage}`,
          stage: event.stage,
          progress: event.progress ?? null,
          message: event.message,
          status: "running",
          startedAt: event.created_at,
          updatedAt: event.created_at,
        };
        steps.push(created);
        byStage.set(created.stage, created);
        step = created;
      } else {
        step.progress = event.progress ?? step.progress;
        step.message = event.message || step.message;
        step.updatedAt = event.created_at;
      }
      continue;
    }
    if (
      event.kind === "job_complete"
      || event.kind === "job_failed"
      || event.kind === "job_cancelled"
    ) {
      for (const step of steps) {
        if (step.status !== "running") continue;
        step.status =
          event.kind === "job_failed"
            ? "failed"
            : event.kind === "job_cancelled"
              ? "cancelled"
              : "completed";
        step.updatedAt = event.created_at;
      }
      continue;
    }
    if (!event.call_id || !event.kind.startsWith("model_")) continue;

    let call = byId.get(event.call_id);
    if (!call) {
      call = {
        callId: event.call_id,
        roundNumber: event.round_number ?? 0,
        role: event.role,
        model: event.model,
        stage: event.stage,
        status: "running",
        output: "",
        message: "",
        startedAt: event.created_at,
      };
      calls.push(call);
      byId.set(call.callId, call);
    }

    if (event.kind === "model_delta" && event.delta) {
      const combined = `${call.output}${event.delta}`;
      call.output =
        combined.length <= MAX_CALL_OUTPUT_CHARS
          ? combined
          : `[较早输出已折叠]\n${combined.slice(-MAX_CALL_OUTPUT_CHARS)}`;
    } else if (event.kind === "model_complete") {
      call.status = "completed";
    } else if (event.kind === "model_error") {
      call.status = "failed";
      call.message = event.message;
    }
  }

  return { calls, steps, lastEventId };
}
