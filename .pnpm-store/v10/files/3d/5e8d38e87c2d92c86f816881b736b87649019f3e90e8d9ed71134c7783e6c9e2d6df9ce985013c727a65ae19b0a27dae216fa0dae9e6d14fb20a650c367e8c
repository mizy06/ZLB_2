import { ChangeContent, ContextContent, FileDiffMetadata, Hunk } from "../types.js";
import { CreatePatchOptionsNonabortable } from "diff";

//#region src/utils/updateDiffHunks.d.ts
type HunkContent = ContextContent | ChangeContent;
type HunkMetadataUpdate = Pick<FileDiffMetadata, 'hunks' | 'splitLineCount' | 'unifiedLineCount' | 'type'>;
type FullDiffHunkUpdate = HunkMetadataUpdate & Pick<FileDiffMetadata, 'additionLines' | 'deletionLines'>;
/** Rebuilds all hunk metadata from the current deletion/addition line arrays. */
declare function recomputeDiffHunks(diff: FileDiffMetadata, parseDiffOptions?: CreatePatchOptionsNonabortable): FullDiffHunkUpdate;
declare function shouldTopAlignAdditionRecompute(diff: FileDiffMetadata, additionLines: string[]): boolean;
declare function recomputeTopAlignedAdditionDiff(diff: FileDiffMetadata, additionLines: string[], parseDiffOptions?: CreatePatchOptionsNonabortable): FullDiffHunkUpdate;
declare function recomputeEmptyDocumentDiff(diff: FileDiffMetadata, parseDiffOptions?: CreatePatchOptionsNonabortable): FullDiffHunkUpdate;
/** Rebuilds diff hunks after an edit, top-aligning sparse addition sides when needed. */
declare function recomputeDiffHunksForEdit(diff: FileDiffMetadata, parseDiffOptions?: CreatePatchOptionsNonabortable): FullDiffHunkUpdate;
declare function preserveTrailingEditorBlankLine(recomputed: Pick<FullDiffHunkUpdate, 'hunks' | 'additionLines' | 'splitLineCount' | 'unifiedLineCount'>, additionLines: string[]): void;
/** Updates hunk metadata after addition lines change; re-parses affected hunks only. */
declare function updateDiffHunks(diff: FileDiffMetadata, changedAdditionLineIndexes: Iterable<number>, parseDiffOptions?: CreatePatchOptionsNonabortable): HunkMetadataUpdate;
declare function syncHunkNoEOFCRFromFullFile(diff: FileDiffMetadata, hunkIndex: number): void;
declare function offsetHunkContent(content: HunkContent, additionOffset: number, deletionOffset: number): HunkContent;
declare function recomputeHunkRenderLineCounts(hunk: Hunk): void;
declare function recomputeDiffRenderLineCounts(diff: Pick<FileDiffMetadata, 'hunks' | 'splitLineCount' | 'unifiedLineCount' | 'additionLines'>): void;
//#endregion
export { offsetHunkContent, preserveTrailingEditorBlankLine, recomputeDiffHunks, recomputeDiffHunksForEdit, recomputeDiffRenderLineCounts, recomputeEmptyDocumentDiff, recomputeHunkRenderLineCounts, recomputeTopAlignedAdditionDiff, shouldTopAlignAdditionRecompute, syncHunkNoEOFCRFromFullFile, updateDiffHunks };
//# sourceMappingURL=updateDiffHunks.d.ts.map