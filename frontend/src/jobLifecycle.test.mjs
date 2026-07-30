import assert from "node:assert/strict";
import test from "node:test";

import {
  canReplaceActiveJob,
  nextPollDelay,
  qualityPresentation,
  shouldContinuePolling,
} from "../.test-dist/jobLifecycle.js";

test("polling is terminal for completed, failed, and cancelled jobs", () => {
  assert.equal(shouldContinuePolling("queued"), true);
  assert.equal(shouldContinuePolling("running"), true);
  assert.equal(shouldContinuePolling("completed"), false);
  assert.equal(shouldContinuePolling("failed"), false);
  assert.equal(shouldContinuePolling("cancelled"), false);
});

test("poll delay backs off and remains bounded", () => {
  assert.equal(nextPollDelay(0), 900);
  assert.equal(nextPollDelay(1), 1_800);
  assert.equal(nextPollDelay(8), 10_000);
});

test("an active job cannot be silently replaced by a file selection", () => {
  assert.equal(canReplaceActiveJob(null), true);
  assert.equal(canReplaceActiveJob("completed"), true);
  assert.equal(canReplaceActiveJob("failed"), true);
  assert.equal(canReplaceActiveJob("cancelled"), true);
  assert.equal(canReplaceActiveJob("queued"), false);
  assert.equal(canReplaceActiveJob("running"), false);
});

test("quality presentation separates structural and publish gates", () => {
  assert.deepEqual(
    qualityPresentation({
      topology_valid: false,
      structural_gate_passed: false,
      publish_gate_passed: false,
      quality_gate_passed: false,
      degraded_components: [],
      pending_reviews: 0,
    }),
    { kind: "failed", label: "结构校验失败" },
  );
  assert.deepEqual(
    qualityPresentation({
      topology_valid: true,
      structural_gate_passed: true,
      publish_gate_passed: false,
      quality_gate_passed: false,
      degraded_components: ["parent_verifier"],
      pending_reviews: 0,
    }),
    { kind: "degraded", label: "结构合法，但关键阶段已降级" },
  );
  assert.deepEqual(
    qualityPresentation({
      topology_valid: true,
      structural_gate_passed: true,
      publish_gate_passed: false,
      quality_gate_passed: false,
      degraded_components: [],
      pending_reviews: 2,
    }),
    { kind: "review", label: "结构合法，发布前仍需复核" },
  );
  assert.deepEqual(
    qualityPresentation({
      topology_valid: true,
      structural_gate_passed: true,
      publish_gate_passed: true,
      quality_gate_passed: true,
      degraded_components: [],
      pending_reviews: 0,
    }),
    { kind: "passed", label: "发布质量门通过" },
  );
});
