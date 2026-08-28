import { getHunkSideStartBoundary } from "./getHunkSideBoundaries.js";
import { parseDiffFromFile } from "./parseDiffFromFile.js";
import { getExpandedRegion, getTrailingExpandedRegion } from "./virtualDiffLayout.js";
import { offsetHunkContent, preserveTrailingEditorBlankLine, recomputeDiffHunks, recomputeDiffHunksForEdit, recomputeDiffRenderLineCounts, recomputeHunkRenderLineCounts, syncHunkNoEOFCRFromFullFile } from "./updateDiffHunks.js";
//#region src/utils/editSessionHunks.ts
const deletionLineSetCache = /* @__PURE__ */ new WeakMap();
/**
* Drops the editor document's phantom trailing empty line (a document ending
* in a newline exposes one extra empty line the parsed diff never contains)
* so session line arrays compare like parse-derived ones.
*/
function normalizeEditorLines(lines) {
	if (lines.length > 1 && lines[lines.length - 1] === "") return lines.slice(0, -1);
	return lines;
}
/**
* Find the complete old/current divergence core. The old side is immutable
* during an edit session, so this result needs no prior-pass snapshot.
*/
function findDivergenceCore(deletionLines, additionLines) {
	const maxStart = Math.min(deletionLines.length, additionLines.length);
	let start = 0;
	while (start < maxStart && deletionLines[start] === additionLines[start]) start++;
	let deletionEnd = deletionLines.length;
	let additionEnd = additionLines.length;
	while (deletionEnd > start && additionEnd > start && deletionLines[deletionEnd - 1] === additionLines[additionEnd - 1]) {
		deletionEnd--;
		additionEnd--;
	}
	if (start === deletionEnd && start === additionEnd) return;
	return {
		start,
		deletionEnd,
		additionEnd
	};
}
/**
* Rebuild the session skeleton as a pure function of the immutable old lines,
* current new lines, and old-side ranges of the previous regions. One
* canonical parse supplies the same change blocks that session exit will use.
*/
function rebuildSessionHunks(diff, parseDiffOptions) {
	const previousHunks = diff.hunks;
	const editorAdditionLines = diff.additionLines;
	const canonicalAdditionLines = normalizeEditorLines(editorAdditionLines);
	const canonicalDiff = canonicalAdditionLines === editorAdditionLines ? diff : {
		...diff,
		additionLines: canonicalAdditionLines
	};
	const plans = buildRegionPlans(previousHunks, parseCanonicalChangeBlocks(canonicalDiff, parseDiffOptions), diff.deletionLines.length);
	const nextHunks = buildRegionHunks(canonicalDiff, plans);
	diff.additionLines = canonicalAdditionLines;
	diff.hunks = nextHunks;
	diff.editSessionDirty = true;
	finalizeSessionHunks(diff);
	preserveTrailingEditorBlankLine(diff, editorAdditionLines);
	if (!hasRegionOrSplitLayoutChanged(previousHunks, diff.hunks)) return;
	return { regions: plans.map((plan) => plan.previousSpan) };
}
/**
* Keep a cheap content-only path when a same-line-count pass cannot alter the
* canonical blocks. Gap, ambiguous, or multi-region edits rebuild statelessly.
*/
function applySessionChangedLines(diff, changedAdditionLineIndexes, parseDiffOptions, previousAdditionLines) {
	const lines = Array.from(new Set(changedAdditionLineIndexes)).filter((line) => line >= 0 && line < diff.additionLines.length).sort((a, b) => a - b);
	if (lines.length === 0) return;
	const { hunks } = diff;
	let regionIndex;
	let hunkIndex = 0;
	for (const line of lines) {
		while (hunkIndex < hunks.length) {
			const hunk = hunks[hunkIndex];
			if (line < getHunkAdditionStart(hunk) + hunk.additionCount) break;
			hunkIndex++;
		}
		const hunk = hunks[hunkIndex];
		const start = hunk == null ? void 0 : getHunkAdditionStart(hunk);
		if (start == null || line < start || regionIndex != null && regionIndex !== hunkIndex) return rebuildSessionHunks(diff, parseDiffOptions);
		regionIndex = hunkIndex;
	}
	if (regionIndex == null) return;
	if (canRetainCanonicalBlocks(diff, lines, regionIndex, previousAdditionLines, parseDiffOptions)) {
		diff.editSessionDirty = true;
		return;
	}
	return rebuildSessionHunks(diff, parseDiffOptions);
}
function canRetainCanonicalBlocks(diff, changedLines, regionIndex, previousAdditionLines, parseDiffOptions) {
	if (previousAdditionLines == null || parseDiffOptions?.ignoreWhitespace === true || parseDiffOptions?.stripTrailingCr === true) return false;
	const deletionLineSet = getDeletionLineSet(diff);
	const hunk = diff.hunks[regionIndex];
	if (hunk.hunkContent.some(isPureChange)) return false;
	for (const line of changedLines) {
		const previousLine = previousAdditionLines.get(line);
		const additionLine = diff.additionLines[line];
		if (previousLine == null || additionLine == null || deletionLineSet.has(previousLine) || deletionLineSet.has(additionLine)) return false;
		let insideBalancedChange = false;
		for (const content of hunk.hunkContent) if (content.type === "change" && content.additions === content.deletions && line >= content.additionLineIndex && line < content.additionLineIndex + content.additions) {
			insideBalancedChange = true;
			break;
		}
		if (!insideBalancedChange) return false;
	}
	return true;
}
function getDeletionLineSet(diff) {
	const cached = deletionLineSetCache.get(diff);
	if (cached?.lines === diff.deletionLines) return cached.set;
	const set = new Set(diff.deletionLines);
	deletionLineSetCache.set(diff, {
		lines: diff.deletionLines,
		set
	});
	return set;
}
function isPureChange(content) {
	return content?.type === "change" && (content.additions === 0 || content.deletions === 0);
}
/** Preserve expansion at the surviving outer edges of rebuilt old-side gaps. */
function remapExpandedHunksForRegionChange(expandedHunks, change) {
	const remapped = /* @__PURE__ */ new Map();
	const { regions } = change;
	for (let key = 0; key <= regions.length; key++) {
		const previous = regions[key - 1];
		const next = regions[key];
		const fromStartSource = key === 0 ? expandedHunks.get(0) : previous == null ? void 0 : expandedHunks.get(previous.lastIndex + 1);
		const fromEndSource = next == null ? void 0 : expandedHunks.get(next.firstIndex);
		const fromStart = fromStartSource?.fromStart ?? 0;
		const fromEnd = fromEndSource?.fromEnd ?? 0;
		if (fromStart > 0 || fromEnd > 0) remapped.set(key, {
			fromStart,
			fromEnd
		});
	}
	return remapped;
}
/** Snapshot the expanded gap-edge slices before the exit recompute. */
function captureExpansionAnchors(diff, expandedHunks, collapsedContextThreshold) {
	const anchors = [];
	if (diff.isPartial) return anchors;
	for (const [hunkIndex, hunk] of diff.hunks.entries()) {
		const region = getExpandedRegion({
			isPartial: diff.isPartial,
			rangeSize: hunk.collapsedBefore,
			expandedHunks,
			hunkIndex,
			collapsedContextThreshold
		});
		if (region.rangeSize <= collapsedContextThreshold) continue;
		const gapEnd = getHunkDeletionStart(hunk);
		const gapStart = gapEnd - region.rangeSize;
		if (region.fromStart > 0) anchors.push([gapStart, gapStart + region.fromStart]);
		if (region.fromEnd > 0) anchors.push([gapEnd - region.fromEnd, gapEnd]);
	}
	const trailingRegion = getTrailingExpandedRegion({
		fileDiff: diff,
		hunkIndex: diff.hunks.length - 1,
		expandedHunks,
		collapsedContextThreshold,
		errorPrefix: "captureExpansionAnchors"
	});
	if (trailingRegion != null && trailingRegion.fromStart > 0 && trailingRegion.rangeSize > collapsedContextThreshold) {
		const lastHunk = diff.hunks[diff.hunks.length - 1];
		const gapStart = getHunkDeletionStart(lastHunk) + lastHunk.deletionCount;
		anchors.push([gapStart, gapStart + trailingRegion.fromStart]);
	}
	return anchors;
}
/**
* Rebuild gap expansion state against the recomputed hunks: for each new
* gap, an anchor touching the gap's start edge restores `fromStart`, one
* touching its end edge restores `fromEnd`, and anchors for gaps that no
* longer exist drop.
*/
function rebuildExpansionFromAnchors(diff, anchors) {
	const rebuilt = /* @__PURE__ */ new Map();
	if (anchors.length === 0) return rebuilt;
	const applyGap = (key, gapStart, gapEnd) => {
		if (gapEnd <= gapStart) return;
		let fromStart = 0;
		let fromEnd = 0;
		for (const [start, end] of anchors) {
			if (end <= gapStart || start >= gapEnd) continue;
			if (start <= gapStart) fromStart = Math.max(fromStart, Math.min(end, gapEnd) - gapStart);
			if (end >= gapEnd) fromEnd = Math.max(fromEnd, gapEnd - Math.max(start, gapStart));
		}
		if (fromStart > 0 || fromEnd > 0) rebuilt.set(key, {
			fromStart,
			fromEnd
		});
	};
	for (const [hunkIndex, hunk] of diff.hunks.entries()) {
		const gapEnd = getHunkDeletionStart(hunk);
		applyGap(hunkIndex, gapEnd - Math.max(hunk.collapsedBefore, 0), gapEnd);
	}
	const lastHunk = diff.hunks[diff.hunks.length - 1];
	if (lastHunk != null && !diff.isPartial && diff.deletionLines.length > 0) applyGap(diff.hunks.length, getHunkDeletionStart(lastHunk) + lastHunk.deletionCount, diff.deletionLines.length);
	return rebuilt;
}
/**
* Genuine session exit: when session passes reshaped the hunks, run the real
* full recompute so exit state matches a non-session edit pipeline, and clear
* the marker. Returns true when a recompute ran.
*/
function finishEditSessionForDiff(diff, parseDiffOptions) {
	if (diff.editSessionDirty !== true) return false;
	diff.editSessionDirty = void 0;
	Object.assign(diff, diff.additionLines.length <= 1 && diff.additionLines.join("") === "" ? recomputeDiffHunks(diff, parseDiffOptions) : recomputeDiffHunksForEdit(diff, parseDiffOptions));
	return true;
}
function parseCanonicalChangeBlocks(diff, parseDiffOptions) {
	if (findDivergenceCore(diff.deletionLines, diff.additionLines) == null) return [];
	const parsed = parseDiffFromFile({
		name: diff.prevName ?? diff.name,
		contents: diff.deletionLines.join("")
	}, {
		name: diff.name,
		contents: diff.additionLines.join(""),
		lang: diff.lang
	}, parseDiffOptions);
	const blocks = [];
	let coveredAdditions = 0;
	let coveredDeletions = 0;
	for (const hunk of parsed.hunks) {
		const contextLines = hunk.additionCount > 0 ? hunk.additionLineIndex - coveredAdditions : hunk.deletionLineIndex - coveredDeletions;
		coveredAdditions += contextLines;
		coveredDeletions += contextLines;
		for (const content of hunk.hunkContent) {
			if (content.type === "context") {
				coveredAdditions += content.lines;
				coveredDeletions += content.lines;
				continue;
			}
			const block = offsetHunkContent(content, 0, 0);
			if (block.additions === 0) block.additionLineIndex = coveredAdditions;
			if (block.deletions === 0) block.deletionLineIndex = coveredDeletions;
			blocks.push(block);
			coveredAdditions += block.additions;
			coveredDeletions += block.deletions;
		}
	}
	return blocks;
}
function buildRegionPlans(previousHunks, blocks, deletionLineCount) {
	const previousPlans = previousHunks.map((hunk, index) => {
		const deletionStart = getHunkDeletionStart(hunk);
		return {
			deletionStart,
			deletionEnd: deletionStart + hunk.deletionCount,
			blocks: [],
			previousSpan: {
				firstIndex: index,
				lastIndex: index
			}
		};
	});
	const plans = [];
	let previousIndex = 0;
	for (const block of blocks) {
		const blockStart = block.deletionLineIndex;
		const blockEnd = blockStart + block.deletions;
		while (previousIndex < previousPlans.length && previousPlans[previousIndex].deletionEnd < blockStart) {
			plans.push(previousPlans[previousIndex]);
			previousIndex++;
		}
		let plan = plans.length > 0 && blockTouchesRegion(blockStart, blockEnd, plans[plans.length - 1]) ? plans.pop() : void 0;
		while (previousIndex < previousPlans.length && previousPlans[previousIndex].deletionStart <= blockEnd) {
			plan = mergeRegionPlans(plan, previousPlans[previousIndex]);
			previousIndex++;
		}
		if (plan == null) {
			let deletionStart = blockStart;
			let deletionEnd = blockEnd;
			if ((block.deletions === 0 || block.additions === 0) && deletionLineCount > block.deletions) {
				const previousEnd = plans[plans.length - 1]?.deletionEnd ?? 0;
				const nextStart = previousPlans[previousIndex]?.deletionStart ?? deletionLineCount;
				if (blockStart > previousEnd) deletionStart--;
				else if (blockEnd < nextStart) deletionEnd++;
			}
			plan = {
				deletionStart,
				deletionEnd,
				blocks: [],
				previousSpan: void 0
			};
		}
		plan.deletionStart = Math.min(plan.deletionStart, blockStart);
		plan.deletionEnd = Math.max(plan.deletionEnd, blockEnd);
		plan.blocks.push(block);
		plans.push(plan);
	}
	while (previousIndex < previousPlans.length) {
		plans.push(previousPlans[previousIndex]);
		previousIndex++;
	}
	return plans;
}
function blockTouchesRegion(blockStart, blockEnd, region) {
	return blockStart <= region.deletionEnd && blockEnd >= region.deletionStart;
}
function mergeRegionPlans(target, source) {
	if (target == null) return source;
	target.deletionStart = Math.min(target.deletionStart, source.deletionStart);
	target.deletionEnd = Math.max(target.deletionEnd, source.deletionEnd);
	target.blocks.push(...source.blocks);
	if (source.previousSpan != null) {
		target.previousSpan ??= { ...source.previousSpan };
		target.previousSpan.firstIndex = Math.min(target.previousSpan.firstIndex, source.previousSpan.firstIndex);
		target.previousSpan.lastIndex = Math.max(target.previousSpan.lastIndex, source.previousSpan.lastIndex);
	}
	return target;
}
function buildRegionHunks(diff, plans) {
	const hunks = [];
	let deletionCursor = 0;
	let additionCursor = 0;
	for (const plan of plans) {
		const contextBefore = plan.deletionStart - deletionCursor;
		if (contextBefore < 0) throw new Error("buildRegionHunks: overlapping old-side regions");
		deletionCursor += contextBefore;
		additionCursor += contextBefore;
		const additionStart = additionCursor;
		const hunkContent = [];
		for (const canonicalBlock of plan.blocks) {
			const deletionContext = canonicalBlock.deletionLineIndex - deletionCursor;
			const additionContext = canonicalBlock.additionLineIndex - additionCursor;
			if (deletionContext < 0 || deletionContext !== additionContext) throw new Error("buildRegionHunks: canonical block context mismatch");
			pushContext(hunkContent, deletionContext, additionCursor, deletionCursor);
			deletionCursor += deletionContext;
			additionCursor += additionContext;
			hunkContent.push({ ...canonicalBlock });
			deletionCursor += canonicalBlock.deletions;
			additionCursor += canonicalBlock.additions;
		}
		const trailingContext = plan.deletionEnd - deletionCursor;
		if (trailingContext < 0) throw new Error("buildRegionHunks: block exceeds its old-side region");
		pushContext(hunkContent, trailingContext, additionCursor, deletionCursor);
		deletionCursor += trailingContext;
		additionCursor += trailingContext;
		hunks.push(createRegionHunk(diff, {
			additionStart,
			additionEnd: additionCursor,
			deletionStart: plan.deletionStart,
			deletionEnd: plan.deletionEnd
		}, hunkContent));
	}
	if (diff.deletionLines.length - deletionCursor !== diff.additionLines.length - additionCursor) throw new Error("buildRegionHunks: trailing context mismatch");
	return hunks;
}
function createRegionHunk(diff, bounds, hunkContent) {
	const additionCount = bounds.additionEnd - bounds.additionStart;
	const deletionCount = bounds.deletionEnd - bounds.deletionStart;
	let additionLines = 0;
	let deletionLines = 0;
	for (const content of hunkContent) if (content.type === "change") {
		additionLines += content.additions;
		deletionLines += content.deletions;
	}
	const hunk = {
		collapsedBefore: 0,
		additionStart: getUnifiedStart(bounds.additionStart, additionCount),
		additionCount,
		additionLines,
		additionLineIndex: getUnifiedLineIndex(bounds.additionStart, additionCount),
		deletionStart: getUnifiedStart(bounds.deletionStart, deletionCount),
		deletionCount,
		deletionLines,
		deletionLineIndex: getUnifiedLineIndex(bounds.deletionStart, deletionCount),
		hunkContent,
		hunkSpecs: `@@ -${getUnifiedStart(bounds.deletionStart, deletionCount)},${deletionCount} +${getUnifiedStart(bounds.additionStart, additionCount)},${additionCount} @@`,
		splitLineStart: 0,
		splitLineCount: 0,
		unifiedLineStart: 0,
		unifiedLineCount: 0,
		noEOFCRAdditions: false,
		noEOFCRDeletions: false
	};
	recomputeHunkRenderLineCounts(hunk);
	return hunk;
}
function pushContext(hunkContent, lines, additionLineIndex, deletionLineIndex) {
	if (lines > 0) hunkContent.push({
		type: "context",
		lines,
		additionLineIndex,
		deletionLineIndex
	});
}
function hasRegionOrSplitLayoutChanged(previous, next) {
	if (previous.length !== next.length) return true;
	for (let index = 0; index < previous.length; index++) {
		const previousHunk = previous[index];
		const nextHunk = next[index];
		if (getHunkDeletionStart(previousHunk) !== getHunkDeletionStart(nextHunk) || previousHunk.deletionCount !== nextHunk.deletionCount || getHunkAdditionStart(previousHunk) !== getHunkAdditionStart(nextHunk) || previousHunk.additionCount !== nextHunk.additionCount || previousHunk.splitLineCount !== nextHunk.splitLineCount || !haveSameSplitRowMapping(previousHunk, nextHunk)) return true;
	}
	return false;
}
function haveSameSplitRowMapping(previous, next) {
	const previousRows = iterateSplitRowMapping(previous);
	const nextRows = iterateSplitRowMapping(next);
	while (true) {
		const previousRow = previousRows.next();
		const nextRow = nextRows.next();
		if (previousRow.done === true || nextRow.done === true) return previousRow.done === nextRow.done;
		if (previousRow.value[0] !== nextRow.value[0] || previousRow.value[1] !== nextRow.value[1]) return false;
	}
}
function* iterateSplitRowMapping(hunk) {
	for (const content of hunk.hunkContent) {
		if (content.type === "context") {
			for (let offset = 0; offset < content.lines; offset++) yield [content.deletionLineIndex + offset, content.additionLineIndex + offset];
			continue;
		}
		const rowCount = Math.max(content.deletions, content.additions);
		for (let offset = 0; offset < rowCount; offset++) yield [offset < content.deletions ? content.deletionLineIndex + offset : void 0, offset < content.additions ? content.additionLineIndex + offset : void 0];
	}
}
function getHunkAdditionStart(hunk) {
	return getHunkSideStartBoundary(hunk.additionStart, hunk.additionCount);
}
function getHunkDeletionStart(hunk) {
	return getHunkSideStartBoundary(hunk.deletionStart, hunk.deletionCount);
}
function getUnifiedStart(lineIndex, count) {
	return count === 0 ? lineIndex : lineIndex + 1;
}
function getUnifiedLineIndex(lineIndex, count) {
	return count === 0 ? lineIndex - 1 : lineIndex;
}
function finalizeSessionHunks(diff) {
	recomputeDiffRenderLineCounts(diff);
	for (let index = 0; index < diff.hunks.length; index++) syncHunkNoEOFCRFromFullFile(diff, index);
}
//#endregion
export { applySessionChangedLines, captureExpansionAnchors, findDivergenceCore, finishEditSessionForDiff, normalizeEditorLines, rebuildExpansionFromAnchors, rebuildSessionHunks, remapExpandedHunksForRegionChange };

//# sourceMappingURL=editSessionHunks.js.map