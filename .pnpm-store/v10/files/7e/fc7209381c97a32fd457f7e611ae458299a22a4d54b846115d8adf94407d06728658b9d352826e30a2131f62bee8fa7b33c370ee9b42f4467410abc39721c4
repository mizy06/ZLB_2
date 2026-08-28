import { getHunkSideEndBoundary, getHunkSideStartBoundary } from "./getHunkSideBoundaries.js";
import { cleanLastNewline } from "./cleanLastNewline.js";
import { parseDiffFromFile } from "./parseDiffFromFile.js";
import { hasTrailingContextMismatch } from "./virtualDiffLayout.js";
//#region src/utils/updateDiffHunks.ts
/** Rebuilds all hunk metadata from the current deletion/addition line arrays. */
function recomputeDiffHunks(diff, parseDiffOptions) {
	const recomputed = parseDiffFromFile({
		name: diff.prevName ?? diff.name,
		contents: diff.deletionLines.join("")
	}, {
		name: diff.name,
		contents: diff.additionLines.join(""),
		lang: diff.lang
	}, parseDiffOptions);
	return {
		hunks: recomputed.hunks,
		splitLineCount: recomputed.splitLineCount,
		unifiedLineCount: recomputed.unifiedLineCount,
		additionLines: recomputed.additionLines,
		deletionLines: recomputed.deletionLines,
		type: recomputed.type
	};
}
function buildTopAlignedAdditionSentinel(lineCount, deletionContents) {
	const count = Math.max(lineCount, 1);
	let sentinel = Array.from({ length: count }, (_, index) => `${" ".repeat(index + 1)}\n`).join("");
	if (sentinel === deletionContents) sentinel = Array.from({ length: count }, (_, index) => `\u0000${" ".repeat(index)}\n`).join("");
	return sentinel;
}
function hasOnlyBlankAdditionContents(additionLines) {
	for (const line of additionLines) if (line.trim().length > 0) return false;
	return true;
}
function shouldTopAlignAdditionRecompute(diff, additionLines) {
	return additionLines.length > 0 && additionLines.length < diff.deletionLines.length && hasOnlyBlankAdditionContents(additionLines);
}
function recomputeTopAlignedAdditionDiff(diff, additionLines, parseDiffOptions) {
	const deletionContents = diff.deletionLines.join("");
	const additionSentinel = buildTopAlignedAdditionSentinel(additionLines.length, deletionContents);
	const recomputed = parseDiffFromFile({
		name: diff.prevName ?? diff.name,
		contents: deletionContents
	}, {
		name: diff.name,
		contents: additionSentinel,
		lang: diff.lang
	}, parseDiffOptions);
	return {
		hunks: recomputed.hunks,
		splitLineCount: recomputed.splitLineCount,
		unifiedLineCount: recomputed.unifiedLineCount,
		additionLines,
		deletionLines: recomputed.deletionLines,
		type: recomputed.type
	};
}
function recomputeEmptyDocumentDiff(diff, parseDiffOptions) {
	return recomputeTopAlignedAdditionDiff(diff, [""], parseDiffOptions);
}
/** Rebuilds diff hunks after an edit, top-aligning sparse addition sides when needed. */
function recomputeDiffHunksForEdit(diff, parseDiffOptions) {
	if (diff.additionLines.length === 0) return recomputeEmptyDocumentDiff(diff, parseDiffOptions);
	if (shouldTopAlignAdditionRecompute(diff, diff.additionLines)) return recomputeTopAlignedAdditionDiff(diff, diff.additionLines, parseDiffOptions);
	const additionLines = diff.additionLines;
	const recomputed = recomputeDiffHunks(diff, parseDiffOptions);
	preserveTrailingEditorBlankLine(recomputed, additionLines);
	return recomputed;
}
function hasTrailingEditorBlankLine(additionLines) {
	return additionLines.length > 1 && additionLines.at(-1) === "";
}
function preserveTrailingEditorBlankLine(recomputed, additionLines) {
	if (!hasTrailingEditorBlankLine(additionLines)) return;
	const extraLineCount = additionLines.length - recomputed.additionLines.length;
	if (extraLineCount <= 0) return;
	const extraAdditionLineIndex = recomputed.additionLines.length;
	const lastHunk = recomputed.hunks.at(-1);
	if (lastHunk == null) return;
	if (getHunkSideEndBoundary(lastHunk.additionStart, lastHunk.additionCount) !== extraAdditionLineIndex) return;
	for (const content of lastHunk.hunkContent) if (content.type === "change" && content.additions < content.deletions && content.additionLineIndex + content.additions === extraAdditionLineIndex) {
		recomputed.additionLines = additionLines;
		content.additions += extraLineCount;
		lastHunk.additionCount += extraLineCount;
		lastHunk.additionLines += extraLineCount;
		recomputeDiffRenderLineCounts(recomputed);
		return;
	}
}
/** Updates hunk metadata after addition lines change; re-parses affected hunks only. */
function updateDiffHunks(diff, changedAdditionLineIndexes, parseDiffOptions) {
	if (diff.isPartial) return applyHunkUpdateResult(diff, recomputeDiffHunks(diff, parseDiffOptions));
	if (diff.deletionLines.length !== diff.additionLines.length) return applyHunkUpdateResult(diff, recomputeDiffHunks(diff, parseDiffOptions));
	const changedLines = Array.from(changedAdditionLineIndexes);
	if (changedLines.length === 0) return applyHunkUpdateResult(diff, {
		hunks: diff.hunks,
		splitLineCount: diff.splitLineCount,
		unifiedLineCount: diff.unifiedLineCount,
		type: diff.type
	});
	for (const line of changedLines) {
		const additionLine = diff.additionLines[line];
		const deletionLine = diff.deletionLines[line];
		if (additionLine == null || deletionLine == null) return applyHunkUpdateResult(diff, recomputeDiffHunks(diff, parseDiffOptions));
		if (cleanLastNewline(additionLine) === cleanLastNewline(deletionLine)) return applyHunkUpdateResult(diff, recomputeDiffHunks(diff, parseDiffOptions));
	}
	const affectedHunkIndexes = getAffectedHunkIndexes(diff, changedLines);
	if (affectedHunkIndexes.size === 0) return applyHunkUpdateResult(diff, recomputeDiffHunks(diff, parseDiffOptions));
	for (const hunkIndex of affectedHunkIndexes) if (!reparseHunkRegion(diff, hunkIndex, parseDiffOptions)) return applyHunkUpdateResult(diff, recomputeDiffHunks(diff, parseDiffOptions));
	recomputeDiffRenderLineCounts(diff);
	if (hasTrailingContextMismatch(diff)) return applyHunkUpdateResult(diff, recomputeDiffHunks(diff, parseDiffOptions));
	return applyHunkUpdateResult(diff, {
		hunks: diff.hunks,
		splitLineCount: diff.splitLineCount,
		unifiedLineCount: diff.unifiedLineCount,
		type: diff.type
	});
}
function applyHunkUpdateResult(diff, result) {
	Object.assign(diff, result);
	return result;
}
function getAffectedHunkIndexes(diff, changedAdditionLineIndexes) {
	const indexes = /* @__PURE__ */ new Set();
	for (const line of changedAdditionLineIndexes) {
		const hunkIndex = findHunkIndexForAdditionLine(diff, line);
		if (hunkIndex == null) return /* @__PURE__ */ new Set();
		indexes.add(hunkIndex);
	}
	return indexes;
}
function findHunkIndexForAdditionLine(diff, line) {
	for (const [hunkIndex, hunk] of diff.hunks.entries()) {
		const end = hunk.additionLineIndex + hunk.additionCount;
		if (line >= hunk.additionLineIndex && line < end) return hunkIndex;
	}
}
function reparseHunkRegion(diff, hunkIndex, parseDiffOptions) {
	const hunk = diff.hunks[hunkIndex];
	if (hunk == null) return false;
	const deletionSlice = diff.deletionLines.slice(hunk.deletionLineIndex, hunk.deletionLineIndex + hunk.deletionCount);
	const additionSlice = diff.additionLines.slice(hunk.additionLineIndex, hunk.additionLineIndex + hunk.additionCount);
	const reparsed = parseDiffFromFile({
		name: diff.prevName ?? diff.name,
		contents: deletionSlice.join("")
	}, {
		name: diff.name,
		contents: additionSlice.join(""),
		lang: diff.lang
	}, {
		...parseDiffOptions,
		context: 0
	});
	const reparsedHunk = reparsed.hunks[0];
	if (reparsedHunk == null || reparsed.hunks.length !== 1) return false;
	applyReparsedHunk(hunk, reparsedHunk);
	syncHunkNoEOFCRFromFullFile(diff, hunkIndex);
	return true;
}
function syncHunkNoEOFCRFromFullFile(diff, hunkIndex) {
	const hunk = diff.hunks[hunkIndex];
	if (hunk == null) return;
	if (!(hunkIndex === diff.hunks.length - 1)) {
		hunk.noEOFCRAdditions = false;
		hunk.noEOFCRDeletions = false;
		return;
	}
	const lastAdditionLine = diff.additionLines.at(-1);
	const lastDeletionLine = diff.deletionLines.at(-1);
	hunk.noEOFCRAdditions = lastAdditionLine != null && lastAdditionLine !== "" && !lastAdditionLine.endsWith("\n");
	hunk.noEOFCRDeletions = lastDeletionLine != null && lastDeletionLine !== "" && !lastDeletionLine.endsWith("\n");
}
function applyReparsedHunk(target, parsed) {
	const additionOffset = target.additionLineIndex;
	const deletionOffset = target.deletionLineIndex;
	target.hunkContent = parsed.hunkContent.map((content) => offsetHunkContent(content, additionOffset, deletionOffset));
	target.additionLineIndex = additionOffset + parsed.additionLineIndex;
	target.additionStart = target.additionStart + parsed.additionLineIndex;
	target.additionCount = parsed.additionCount;
	target.additionLines = parsed.additionLines;
	if (parsed.deletionLineIndex >= 0) {
		target.deletionLineIndex = deletionOffset + parsed.deletionLineIndex;
		target.deletionStart = target.deletionStart + parsed.deletionLineIndex;
	}
	target.deletionCount = parsed.deletionCount;
	target.deletionLines = parsed.deletionLines;
	target.noEOFCRAdditions = parsed.noEOFCRAdditions;
	target.noEOFCRDeletions = parsed.noEOFCRDeletions;
	recomputeHunkRenderLineCounts(target);
}
function offsetHunkContent(content, additionOffset, deletionOffset) {
	return {
		...content,
		additionLineIndex: content.additionLineIndex + additionOffset,
		deletionLineIndex: content.deletionLineIndex + deletionOffset
	};
}
function recomputeHunkRenderLineCounts(hunk) {
	let splitLineCount = 0;
	let unifiedLineCount = 0;
	for (const content of hunk.hunkContent) if (content.type === "context") {
		splitLineCount += content.lines;
		unifiedLineCount += content.lines;
	} else {
		splitLineCount += Math.max(content.additions, content.deletions);
		unifiedLineCount += content.additions + content.deletions;
	}
	hunk.splitLineCount = splitLineCount;
	hunk.unifiedLineCount = unifiedLineCount;
}
function recomputeDiffRenderLineCounts(diff) {
	let splitTotal = 0;
	let unifiedTotal = 0;
	let lastHunkAdditionEnd = 0;
	for (const hunk of diff.hunks) {
		hunk.collapsedBefore = Math.max(getHunkSideStartBoundary(hunk.additionStart, hunk.additionCount) - lastHunkAdditionEnd, 0);
		hunk.splitLineStart = splitTotal + hunk.collapsedBefore;
		hunk.unifiedLineStart = unifiedTotal + hunk.collapsedBefore;
		recomputeHunkRenderLineCounts(hunk);
		splitTotal += hunk.collapsedBefore + hunk.splitLineCount;
		unifiedTotal += hunk.collapsedBefore + hunk.unifiedLineCount;
		lastHunkAdditionEnd = getHunkSideEndBoundary(hunk.additionStart, hunk.additionCount);
	}
	if (diff.hunks.length > 0) {
		const lastHunk = diff.hunks[diff.hunks.length - 1];
		const collapsedAfter = Math.max(diff.additionLines.length - getHunkSideEndBoundary(lastHunk.additionStart, lastHunk.additionCount), 0);
		splitTotal += collapsedAfter;
		unifiedTotal += collapsedAfter;
	}
	diff.splitLineCount = splitTotal;
	diff.unifiedLineCount = unifiedTotal;
}
//#endregion
export { offsetHunkContent, preserveTrailingEditorBlankLine, recomputeDiffHunks, recomputeDiffHunksForEdit, recomputeDiffRenderLineCounts, recomputeEmptyDocumentDiff, recomputeHunkRenderLineCounts, recomputeTopAlignedAdditionDiff, shouldTopAlignAdditionRecompute, syncHunkNoEOFCRFromFullFile, updateDiffHunks };

//# sourceMappingURL=updateDiffHunks.js.map