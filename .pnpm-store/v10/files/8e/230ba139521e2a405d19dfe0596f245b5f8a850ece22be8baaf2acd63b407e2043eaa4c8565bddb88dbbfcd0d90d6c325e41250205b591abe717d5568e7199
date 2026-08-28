import { FileDiffMetadata, HunkExpansionRegion } from "../types.js";
import { CreatePatchOptionsNonabortable } from "diff";

//#region src/utils/editSessionHunks.d.ts
interface DivergenceCore {
  start: number;
  deletionEnd: number;
  additionEnd: number;
}
interface PreviousRegionSpan {
  firstIndex: number;
  lastIndex: number;
}
/** Maps rebuilt regions back to the previous skeleton for expansion remapping. */
interface SessionRegionChange {
  regions: Array<PreviousRegionSpan | undefined>;
}
/**
 * Drops the editor document's phantom trailing empty line (a document ending
 * in a newline exposes one extra empty line the parsed diff never contains)
 * so session line arrays compare like parse-derived ones.
 */
declare function normalizeEditorLines(lines: string[]): string[];
/**
 * Find the complete old/current divergence core. The old side is immutable
 * during an edit session, so this result needs no prior-pass snapshot.
 */
declare function findDivergenceCore(deletionLines: string[], additionLines: string[]): DivergenceCore | undefined;
/**
 * Rebuild the session skeleton as a pure function of the immutable old lines,
 * current new lines, and old-side ranges of the previous regions. One
 * canonical parse supplies the same change blocks that session exit will use.
 */
declare function rebuildSessionHunks(diff: FileDiffMetadata, parseDiffOptions?: CreatePatchOptionsNonabortable): SessionRegionChange | undefined;
/**
 * Keep a cheap content-only path when a same-line-count pass cannot alter the
 * canonical blocks. Gap, ambiguous, or multi-region edits rebuild statelessly.
 */
declare function applySessionChangedLines(diff: FileDiffMetadata, changedAdditionLineIndexes: Iterable<number>, parseDiffOptions?: CreatePatchOptionsNonabortable, previousAdditionLines?: ReadonlyMap<number, string>): SessionRegionChange | undefined;
/** Preserve expansion at the surviving outer edges of rebuilt old-side gaps. */
declare function remapExpandedHunksForRegionChange(expandedHunks: Map<number, HunkExpansionRegion>, change: SessionRegionChange): Map<number, HunkExpansionRegion>;
/**
 * An expanded gap-edge slice in old-side (deletion-line) coordinates as a
 * `[start, end)` range. Old-side coordinates survive the exit recompute
 * unchanged — edits only touch the new side — so these anchor best-effort
 * expansion preservation across the recompute.
 */
type ExpansionAnchorRange = [start: number, end: number];
/** Snapshot the expanded gap-edge slices before the exit recompute. */
declare function captureExpansionAnchors(diff: FileDiffMetadata, expandedHunks: Map<number, HunkExpansionRegion>, collapsedContextThreshold: number): ExpansionAnchorRange[];
/**
 * Rebuild gap expansion state against the recomputed hunks: for each new
 * gap, an anchor touching the gap's start edge restores `fromStart`, one
 * touching its end edge restores `fromEnd`, and anchors for gaps that no
 * longer exist drop.
 */
declare function rebuildExpansionFromAnchors(diff: FileDiffMetadata, anchors: ExpansionAnchorRange[]): Map<number, HunkExpansionRegion>;
/**
 * Genuine session exit: when session passes reshaped the hunks, run the real
 * full recompute so exit state matches a non-session edit pipeline, and clear
 * the marker. Returns true when a recompute ran.
 */
declare function finishEditSessionForDiff(diff: FileDiffMetadata, parseDiffOptions?: CreatePatchOptionsNonabortable): boolean;
//#endregion
export { DivergenceCore, ExpansionAnchorRange, SessionRegionChange, applySessionChangedLines, captureExpansionAnchors, findDivergenceCore, finishEditSessionForDiff, normalizeEditorLines, rebuildExpansionFromAnchors, rebuildSessionHunks, remapExpandedHunksForRegionChange };
//# sourceMappingURL=editSessionHunks.d.ts.map