import assert from "node:assert/strict";
import test from "node:test";

import {
  isPageEvidenceAsset,
  isRenderableNodeMedia,
} from "../.test-dist/mindmapMedia.js";

const asset = (visualKind, url = "/asset.png") => ({
  asset_id: `asset-${visualKind}`,
  render_id: "render-test",
  filename: "asset.png",
  url,
  visual_kind: visualKind,
  status: "ready",
  ocr_text: "",
  sha1: "",
});

test("full-page renders stay evidence instead of becoming node screenshots", () => {
  assert.equal(isPageEvidenceAsset(asset("full_page")), true);
  assert.equal(isPageEvidenceAsset(asset("full_slide")), true);
  assert.equal(isRenderableNodeMedia(asset("full_page")), false);
  assert.equal(isRenderableNodeMedia(asset("full_slide")), false);
});

test("knowledge visuals with a URL remain eligible as node media", () => {
  assert.equal(isPageEvidenceAsset(asset("picture")), false);
  assert.equal(isRenderableNodeMedia(asset("picture")), true);
  assert.equal(isRenderableNodeMedia(asset("picture", "")), false);
});
