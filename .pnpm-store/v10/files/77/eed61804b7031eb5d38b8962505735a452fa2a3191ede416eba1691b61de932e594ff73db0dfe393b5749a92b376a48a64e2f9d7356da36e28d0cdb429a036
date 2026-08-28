import { getHunkSideEndBoundary, getHunkSideStartBoundary } from "./getHunkSideBoundaries.js";
import { getDefaultHunkSeparatorHeight } from "./computeVirtualFileMetrics.js";
//#region src/utils/virtualDiffLayout.ts
/** One-based new-file line range covered by a hunk, as `[start, end)`. */
function getHunkAdditionLineRange(hunk) {
	return [getHunkSideStartBoundary(hunk.additionStart, hunk.additionCount) + 1, getHunkSideEndBoundary(hunk.additionStart, hunk.additionCount) + 1];
}
function getExpandedRegion({ isPartial, rangeSize, expandedHunks, hunkIndex, collapsedContextThreshold }) {
	const normalizedRangeSize = Math.max(rangeSize, 0);
	if (normalizedRangeSize === 0 || isPartial) return {
		fromStart: 0,
		fromEnd: 0,
		rangeSize: normalizedRangeSize,
		collapsedLines: normalizedRangeSize,
		renderAll: false
	};
	if (expandedHunks === true || normalizedRangeSize <= collapsedContextThreshold) return {
		fromStart: normalizedRangeSize,
		fromEnd: 0,
		rangeSize: normalizedRangeSize,
		collapsedLines: 0,
		renderAll: true
	};
	const region = expandedHunks?.get(hunkIndex);
	const fromStart = Math.min(Math.max(region?.fromStart ?? 0, 0), normalizedRangeSize);
	const fromEnd = Math.min(Math.max(region?.fromEnd ?? 0, 0), normalizedRangeSize);
	const expandedCount = fromStart + fromEnd;
	const renderAll = expandedCount >= normalizedRangeSize;
	return {
		fromStart: renderAll ? normalizedRangeSize : fromStart,
		fromEnd: renderAll ? 0 : fromEnd,
		rangeSize: normalizedRangeSize,
		collapsedLines: Math.max(normalizedRangeSize - expandedCount, 0),
		renderAll
	};
}
function hasTrailingContext(fileDiff) {
	const lastHunk = fileDiff.hunks[fileDiff.hunks.length - 1];
	if (lastHunk == null || fileDiff.isPartial || fileDiff.additionLines.length === 0 || fileDiff.deletionLines.length === 0) return false;
	const additionRemaining = fileDiff.additionLines.length - getHunkSideEndBoundary(lastHunk.additionStart, lastHunk.additionCount);
	const deletionRemaining = fileDiff.deletionLines.length - getHunkSideEndBoundary(lastHunk.deletionStart, lastHunk.deletionCount);
	return additionRemaining > 0 || deletionRemaining > 0;
}
function hasTrailingContextMismatch(fileDiff) {
	const lastHunk = fileDiff.hunks[fileDiff.hunks.length - 1];
	if (lastHunk == null || fileDiff.isPartial || fileDiff.additionLines.length === 0 || fileDiff.deletionLines.length === 0) return false;
	const additionRemaining = fileDiff.additionLines.length - getHunkSideEndBoundary(lastHunk.additionStart, lastHunk.additionCount);
	const deletionRemaining = fileDiff.deletionLines.length - getHunkSideEndBoundary(lastHunk.deletionStart, lastHunk.deletionCount);
	if (additionRemaining <= 0 && deletionRemaining <= 0) return false;
	return additionRemaining !== deletionRemaining;
}
function getTrailingContextRangeSize({ fileDiff, errorPrefix }) {
	const lastHunk = fileDiff.hunks[fileDiff.hunks.length - 1];
	if (lastHunk == null || fileDiff.isPartial || fileDiff.additionLines.length === 0 || fileDiff.deletionLines.length === 0) return 0;
	const additionRemaining = fileDiff.additionLines.length - getHunkSideEndBoundary(lastHunk.additionStart, lastHunk.additionCount);
	const deletionRemaining = fileDiff.deletionLines.length - getHunkSideEndBoundary(lastHunk.deletionStart, lastHunk.deletionCount);
	if (additionRemaining <= 0 && deletionRemaining <= 0) return 0;
	if (additionRemaining !== deletionRemaining) throw new Error(`${errorPrefix}: trailing context mismatch (additions=${additionRemaining}, deletions=${deletionRemaining}) for ${fileDiff.name}`);
	return Math.min(additionRemaining, deletionRemaining);
}
function getTrailingExpandedRegion({ fileDiff, hunkIndex, expandedHunks, collapsedContextThreshold, errorPrefix }) {
	if (hunkIndex !== fileDiff.hunks.length - 1) return;
	const trailingRangeSize = getTrailingContextRangeSize({
		fileDiff,
		errorPrefix
	});
	if (trailingRangeSize <= 0) return;
	if (expandedHunks === true || trailingRangeSize <= collapsedContextThreshold) return {
		fromStart: trailingRangeSize,
		fromEnd: 0,
		rangeSize: trailingRangeSize,
		collapsedLines: 0,
		renderAll: true
	};
	const region = expandedHunks?.get(fileDiff.hunks.length);
	const fromStart = Math.min(Math.max(region?.fromStart ?? 0, 0), trailingRangeSize);
	return {
		fromStart,
		fromEnd: 0,
		rangeSize: trailingRangeSize,
		collapsedLines: trailingRangeSize - fromStart,
		renderAll: fromStart >= trailingRangeSize
	};
}
/**
* Whether a one-based new-file line currently has (or will have on scroll) a
* rendered row under the given expansion state — the editor-facing
* visibility oracle. False only for lines hidden inside a collapsed
* unchanged region; lines outside the diff's modeled range report true so
* callers keep their existing missing-row handling. Computed from the same
* inputs as `iterateOverDiff` so layout math and the oracle cannot diverge.
*/
function isAdditionLineRenderable({ fileDiff, lineNumber, expandedHunks, collapsedContextThreshold }) {
	if (expandedHunks === true || fileDiff.isPartial) return true;
	for (const [hunkIndex, hunk] of fileDiff.hunks.entries()) {
		const [hunkStart, hunkEnd] = getHunkAdditionLineRange(hunk);
		if (lineNumber < hunkStart) {
			const region = getExpandedRegion({
				isPartial: fileDiff.isPartial,
				rangeSize: hunk.collapsedBefore,
				expandedHunks,
				hunkIndex,
				collapsedContextThreshold
			});
			const gapStart = hunkStart - region.rangeSize;
			return region.renderAll || lineNumber < gapStart + region.fromStart || lineNumber >= hunkStart - region.fromEnd;
		}
		if (lineNumber < hunkEnd) return true;
	}
	const trailingRegion = getTrailingExpandedRegion({
		fileDiff,
		hunkIndex: fileDiff.hunks.length - 1,
		expandedHunks,
		collapsedContextThreshold,
		errorPrefix: "isAdditionLineRenderable"
	});
	if (trailingRegion == null || trailingRegion.renderAll) return true;
	const lastHunk = fileDiff.hunks[fileDiff.hunks.length - 1];
	const [, trailingStart] = getHunkAdditionLineRange(lastHunk);
	return lineNumber < trailingStart + trailingRegion.fromStart || lineNumber >= trailingStart + trailingRegion.rangeSize;
}
/**
* The nearest renderable new-file line at or beyond `lineNumber` in the
* given direction (one-based), or undefined when every line that way is
* hidden inside collapsed regions. Sequential caret motion uses this to skip
* over collapsed regions like code folds; it walks the hunk metadata once
* instead of probing line by line across a gap.
*/
function getNearestRenderableAdditionLine({ fileDiff, lineNumber, direction, expandedHunks, collapsedContextThreshold }) {
	if (expandedHunks === true || fileDiff.isPartial) return lineNumber;
	const ranges = [];
	let modeledEnd = 1;
	for (const [hunkIndex, hunk] of fileDiff.hunks.entries()) {
		const [hunkStart, hunkEnd] = getHunkAdditionLineRange(hunk);
		const region = getExpandedRegion({
			isPartial: fileDiff.isPartial,
			rangeSize: hunk.collapsedBefore,
			expandedHunks,
			hunkIndex,
			collapsedContextThreshold
		});
		const gapStart = hunkStart - region.rangeSize;
		if (region.renderAll) ranges.push([gapStart, hunkStart]);
		else {
			if (region.fromStart > 0) ranges.push([gapStart, gapStart + region.fromStart]);
			if (region.fromEnd > 0) ranges.push([hunkStart - region.fromEnd, hunkStart]);
		}
		ranges.push([hunkStart, hunkEnd]);
		modeledEnd = hunkEnd;
	}
	const trailingRegion = getTrailingExpandedRegion({
		fileDiff,
		hunkIndex: fileDiff.hunks.length - 1,
		expandedHunks,
		collapsedContextThreshold,
		errorPrefix: "getNearestRenderableAdditionLine"
	});
	if (trailingRegion != null) {
		const trailingStart = modeledEnd;
		modeledEnd = trailingStart + trailingRegion.rangeSize;
		if (trailingRegion.renderAll) ranges.push([trailingStart, modeledEnd]);
		else if (trailingRegion.fromStart > 0) ranges.push([trailingStart, trailingStart + trailingRegion.fromStart]);
	}
	if (lineNumber >= modeledEnd) return lineNumber;
	if (direction === "down") {
		for (const [start, end] of ranges) if (end > lineNumber) return Math.max(start, lineNumber);
		return;
	}
	for (let index = ranges.length - 1; index >= 0; index--) {
		const [start, end] = ranges[index];
		if (start <= lineNumber) return Math.min(end - 1, lineNumber);
	}
}
function getHunkSeparatorHeight({ type, metrics }) {
	return metrics.hunkSeparatorHeight ?? getDefaultHunkSeparatorHeight(type);
}
function getHunkSeparatorGap({ type, metrics }) {
	return type === "simple" || type === "metadata" || type === "line-info-basic" ? 0 : metrics.spacing;
}
function hasLeadingHunkSeparator({ type, hunkIndex, hunkSpecs }) {
	switch (type) {
		case "simple": return hunkIndex > 0;
		case "metadata": return hunkSpecs != null;
		case "line-info":
		case "line-info-basic":
		case "custom": return true;
	}
}
function hasTrailingHunkSeparator(type) {
	return type !== "simple" && type !== "metadata";
}
function getLeadingHunkSeparatorLayout({ type, metrics, hunkIndex, hunkSpecs }) {
	if (!hasLeadingHunkSeparator({
		type,
		hunkIndex,
		hunkSpecs
	})) return;
	const height = getHunkSeparatorHeight({
		type,
		metrics
	});
	const gap = getHunkSeparatorGap({
		type,
		metrics
	});
	const gapBefore = hunkIndex > 0 ? gap : 0;
	const gapAfter = gap;
	return {
		height,
		gapBefore,
		gapAfter,
		totalHeight: gapBefore + height + gapAfter
	};
}
function getTrailingHunkSeparatorLayout({ type, metrics }) {
	if (!hasTrailingHunkSeparator(type)) return;
	const height = getHunkSeparatorHeight({
		type,
		metrics
	});
	const gapBefore = getHunkSeparatorGap({
		type,
		metrics
	});
	return {
		height,
		gapBefore,
		gapAfter: 0,
		totalHeight: gapBefore + height
	};
}
//#endregion
export { getExpandedRegion, getHunkAdditionLineRange, getHunkSeparatorGap, getHunkSeparatorHeight, getLeadingHunkSeparatorLayout, getNearestRenderableAdditionLine, getTrailingContextRangeSize, getTrailingExpandedRegion, getTrailingHunkSeparatorLayout, hasLeadingHunkSeparator, hasTrailingContext, hasTrailingContextMismatch, hasTrailingHunkSeparator, isAdditionLineRenderable };

//# sourceMappingURL=virtualDiffLayout.js.map