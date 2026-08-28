import { FileDiffMetadata, Hunk, HunkExpansionRegion, HunkSeparators, VirtualFileMetrics } from "../types.js";

//#region src/utils/virtualDiffLayout.d.ts
interface ExpandedRegionResult {
  fromStart: number;
  fromEnd: number;
  rangeSize: number;
  collapsedLines: number;
  renderAll: boolean;
}
interface GetExpandedRegionProps {
  isPartial: boolean;
  rangeSize: number;
  expandedHunks: Map<number, HunkExpansionRegion> | true | undefined;
  hunkIndex: number;
  collapsedContextThreshold: number;
}
interface GetTrailingContextRangeSizeProps {
  fileDiff: FileDiffMetadata;
  errorPrefix: string;
}
interface GetTrailingExpandedRegionProps extends GetTrailingContextRangeSizeProps {
  hunkIndex: number;
  expandedHunks: GetExpandedRegionProps['expandedHunks'];
  collapsedContextThreshold: number;
}
/** One-based new-file line range covered by a hunk, as `[start, end)`. */
declare function getHunkAdditionLineRange(hunk: Hunk): [number, number];
interface HunkSeparatorLayout {
  height: number;
  gapBefore: number;
  gapAfter: number;
  totalHeight: number;
}
interface HunkSeparatorBaseProps {
  type: HunkSeparators;
  metrics: VirtualFileMetrics;
}
interface LeadingHunkSeparatorLayoutProps extends HunkSeparatorBaseProps {
  hunkIndex: number;
  hunkSpecs: string | undefined;
}
declare function getExpandedRegion({
  isPartial,
  rangeSize,
  expandedHunks,
  hunkIndex,
  collapsedContextThreshold
}: GetExpandedRegionProps): ExpandedRegionResult;
declare function hasTrailingContext(fileDiff: FileDiffMetadata): boolean;
declare function hasTrailingContextMismatch(fileDiff: FileDiffMetadata): boolean;
declare function getTrailingContextRangeSize({
  fileDiff,
  errorPrefix
}: GetTrailingContextRangeSizeProps): number;
declare function getTrailingExpandedRegion({
  fileDiff,
  hunkIndex,
  expandedHunks,
  collapsedContextThreshold,
  errorPrefix
}: GetTrailingExpandedRegionProps): ExpandedRegionResult | undefined;
interface IsAdditionLineRenderableProps {
  fileDiff: FileDiffMetadata;
  /** One-based line number in the new file. */
  lineNumber: number;
  expandedHunks: Map<number, HunkExpansionRegion> | true | undefined;
  collapsedContextThreshold: number;
}
/**
 * Whether a one-based new-file line currently has (or will have on scroll) a
 * rendered row under the given expansion state — the editor-facing
 * visibility oracle. False only for lines hidden inside a collapsed
 * unchanged region; lines outside the diff's modeled range report true so
 * callers keep their existing missing-row handling. Computed from the same
 * inputs as `iterateOverDiff` so layout math and the oracle cannot diverge.
 */
declare function isAdditionLineRenderable({
  fileDiff,
  lineNumber,
  expandedHunks,
  collapsedContextThreshold
}: IsAdditionLineRenderableProps): boolean;
interface GetNearestRenderableAdditionLineProps extends IsAdditionLineRenderableProps {
  direction: 'up' | 'down';
}
/**
 * The nearest renderable new-file line at or beyond `lineNumber` in the
 * given direction (one-based), or undefined when every line that way is
 * hidden inside collapsed regions. Sequential caret motion uses this to skip
 * over collapsed regions like code folds; it walks the hunk metadata once
 * instead of probing line by line across a gap.
 */
declare function getNearestRenderableAdditionLine({
  fileDiff,
  lineNumber,
  direction,
  expandedHunks,
  collapsedContextThreshold
}: GetNearestRenderableAdditionLineProps): number | undefined;
declare function getHunkSeparatorHeight({
  type,
  metrics
}: HunkSeparatorBaseProps): number;
declare function getHunkSeparatorGap({
  type,
  metrics
}: HunkSeparatorBaseProps): number;
declare function hasLeadingHunkSeparator({
  type,
  hunkIndex,
  hunkSpecs
}: Omit<LeadingHunkSeparatorLayoutProps, 'metrics'>): boolean;
declare function hasTrailingHunkSeparator(type: HunkSeparators): boolean;
declare function getLeadingHunkSeparatorLayout({
  type,
  metrics,
  hunkIndex,
  hunkSpecs
}: LeadingHunkSeparatorLayoutProps): HunkSeparatorLayout | undefined;
declare function getTrailingHunkSeparatorLayout({
  type,
  metrics
}: HunkSeparatorBaseProps): HunkSeparatorLayout | undefined;
//#endregion
export { ExpandedRegionResult, GetExpandedRegionProps, GetNearestRenderableAdditionLineProps, GetTrailingContextRangeSizeProps, GetTrailingExpandedRegionProps, HunkSeparatorLayout, IsAdditionLineRenderableProps, getExpandedRegion, getHunkAdditionLineRange, getHunkSeparatorGap, getHunkSeparatorHeight, getLeadingHunkSeparatorLayout, getNearestRenderableAdditionLine, getTrailingContextRangeSize, getTrailingExpandedRegion, getTrailingHunkSeparatorLayout, hasLeadingHunkSeparator, hasTrailingContext, hasTrailingContextMismatch, hasTrailingHunkSeparator, isAdditionLineRenderable };
//# sourceMappingURL=virtualDiffLayout.d.ts.map