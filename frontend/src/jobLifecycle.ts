export type JobStatus =
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "cancelled";

export type QualityPresentation = {
  kind: "failed" | "degraded" | "review" | "passed";
  label: string;
};

type QualityState = {
  topology_valid: boolean;
  structural_gate_passed?: boolean;
  publish_gate_passed?: boolean;
  quality_gate_passed: boolean;
  degraded_components: string[];
  pending_reviews: number;
};

export function shouldContinuePolling(status: JobStatus): boolean {
  return status === "queued" || status === "running";
}

export function nextPollDelay(failureCount: number): number {
  const exponent = Math.max(0, Math.trunc(failureCount));
  return Math.min(900 * 2 ** exponent, 10_000);
}

export function canReplaceActiveJob(
  status: JobStatus | null,
): boolean {
  return status === null || !shouldContinuePolling(status);
}

export function canStartJobSubmission(
  hasFile: boolean,
  workspaceReady: boolean,
  running: boolean,
  submitting: boolean,
): boolean {
  return hasFile && workspaceReady && !running && !submitting;
}

export function canAdoptRestoredJob(
  activeTaskId: string | null,
  currentTaskId: string | null,
): boolean {
  return Boolean(
    activeTaskId
    && (!currentTaskId || currentTaskId === activeTaskId),
  );
}

export function qualityPresentation(
  state: QualityState,
): QualityPresentation {
  const structural =
    state.structural_gate_passed ?? state.topology_valid;
  const publish =
    state.publish_gate_passed ?? state.quality_gate_passed;
  if (!structural || !state.topology_valid) {
    return { kind: "failed", label: "结构校验失败" };
  }
  if (publish) {
    return { kind: "passed", label: "发布质量门通过" };
  }
  if (state.degraded_components.length > 0) {
    return {
      kind: "degraded",
      label: "结构合法，但关键阶段已降级",
    };
  }
  if (state.pending_reviews > 0) {
    return {
      kind: "review",
      label: "结构合法，发布前仍需复核",
    };
  }
  return {
    kind: "review",
    label: "结构合法，但发布质量门未通过",
  };
}
