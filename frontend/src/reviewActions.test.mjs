import assert from "node:assert/strict";
import test from "node:test";

import { reviewActionsForType } from "../.test-dist/reviewActions.js";


test("cross-link review exposes no node mutation action", () => {
  assert.deepEqual(reviewActionsForType("cross_link"), ["keep"]);
});


test("review action policy mirrors the backend transaction matrix", () => {
  assert.deepEqual(
    reviewActionsForType("root_choice"),
    ["keep", "accept_root"],
  );
  assert.deepEqual(
    reviewActionsForType("competing_parent"),
    ["keep", "change_parent", "rename"],
  );
  assert.deepEqual(
    reviewActionsForType("abstract_parent"),
    ["keep", "delete", "rename"],
  );
  assert.deepEqual(
    reviewActionsForType("uncovered_content"),
    ["keep", "rename"],
  );
});
