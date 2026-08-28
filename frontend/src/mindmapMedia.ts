import type { VisualAsset } from "./types";

export function isPageEvidenceAsset(
  asset: Pick<VisualAsset, "visual_kind">,
): boolean {
  return asset.visual_kind === "full_page" || asset.visual_kind === "full_slide";
}

export function isRenderableNodeMedia(
  asset: VisualAsset | undefined,
): asset is VisualAsset {
  if (!asset?.url) return false;
  return !isPageEvidenceAsset(asset);
}
