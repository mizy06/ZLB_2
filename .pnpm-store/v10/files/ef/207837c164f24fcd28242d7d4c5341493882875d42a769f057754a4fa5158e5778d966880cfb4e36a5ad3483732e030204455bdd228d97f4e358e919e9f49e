import { getHunkSideEndBoundary, getHunkSideStartBoundary } from "./getHunkSideBoundaries.js";
import { cloneFileDiffMetadata } from "./cloneFileDiffMetadata.js";
import { splitFileContents } from "./splitFileContents.js";
//#region src/utils/hydratePartialDiff.ts
/**
* Hydrates a partial diff in place with full file line arrays.
*/
function hydratePartialDiff(type, fileDiff, files) {
	const targetFileDiff = type === "clone" ? cloneFileDiffMetadata(fileDiff) : fileDiff;
	if (!targetFileDiff.isPartial) throw new Error("hydratePartialDiff: fileDiff must be partial");
	switch (targetFileDiff.type) {
		case "change":
		case "rename-changed": return hydrateTwoSidedFileDiff(targetFileDiff, requireOldFile(targetFileDiff, files), requireNewFile(targetFileDiff, files));
		case "rename-pure": {
			const newFile = requireNewFile(targetFileDiff, files);
			requireMissingOldFile(targetFileDiff, files);
			const lines = splitFileContents(newFile.contents);
			targetFileDiff.isPartial = false;
			targetFileDiff.deletionLines = lines;
			targetFileDiff.additionLines = lines;
			setHydratedCacheKey(targetFileDiff, null, newFile);
			return targetFileDiff;
		}
	}
	throw new Error(`hydratePartialDiff: ${targetFileDiff.type} diffs cannot be hydrated from loaded files`);
}
function hydrateTwoSidedFileDiff(fileDiff, oldFile, newFile) {
	const deletionLines = splitFileContents(oldFile.contents);
	const additionLines = splitFileContents(newFile.contents);
	const { hunks, splitLineCount, unifiedLineCount } = hydrateHunks(fileDiff.hunks, additionLines.length);
	fileDiff.hunks = hunks;
	fileDiff.splitLineCount = splitLineCount;
	fileDiff.unifiedLineCount = unifiedLineCount;
	fileDiff.isPartial = false;
	fileDiff.deletionLines = deletionLines;
	fileDiff.additionLines = additionLines;
	setHydratedCacheKey(fileDiff, oldFile, newFile);
	return fileDiff;
}
function hydrateHunks(hunks, totalAdditionLines) {
	let splitLineCount = 0;
	let unifiedLineCount = 0;
	let lastHunkAdditionEnd = 0;
	const hydratedHunks = [];
	for (const hunk of hunks) {
		const additionLineIndex = Math.max(hunk.additionStart - 1, 0);
		const deletionLineIndex = Math.max(hunk.deletionStart - 1, 0);
		let contentAdditionLineIndex = additionLineIndex;
		let contentDeletionLineIndex = deletionLineIndex;
		let hunkAdditionLines = 0;
		let hunkDeletionLines = 0;
		let hunkSplitLineCount = 0;
		let hunkUnifiedLineCount = 0;
		const hunkContent = [];
		for (const content of hunk.hunkContent) {
			if (content.type === "context") {
				hunkContent.push({
					...content,
					additionLineIndex: contentAdditionLineIndex,
					deletionLineIndex: contentDeletionLineIndex
				});
				contentAdditionLineIndex += content.lines;
				contentDeletionLineIndex += content.lines;
				hunkSplitLineCount += content.lines;
				hunkUnifiedLineCount += content.lines;
				continue;
			}
			hunkContent.push({
				...content,
				additionLineIndex: contentAdditionLineIndex,
				deletionLineIndex: contentDeletionLineIndex
			});
			contentAdditionLineIndex += content.additions;
			contentDeletionLineIndex += content.deletions;
			hunkAdditionLines += content.additions;
			hunkDeletionLines += content.deletions;
			hunkSplitLineCount += Math.max(content.additions, content.deletions);
			hunkUnifiedLineCount += content.additions + content.deletions;
		}
		const collapsedBefore = Math.max(getHunkSideStartBoundary(hunk.additionStart, hunk.additionCount) - lastHunkAdditionEnd, 0);
		hydratedHunks.push({
			...hunk,
			collapsedBefore,
			additionLineIndex,
			deletionLineIndex,
			additionLines: hunkAdditionLines,
			deletionLines: hunkDeletionLines,
			hunkContent,
			splitLineStart: splitLineCount + collapsedBefore,
			unifiedLineStart: unifiedLineCount + collapsedBefore,
			splitLineCount: hunkSplitLineCount,
			unifiedLineCount: hunkUnifiedLineCount
		});
		splitLineCount += collapsedBefore + hunkSplitLineCount;
		unifiedLineCount += collapsedBefore + hunkUnifiedLineCount;
		lastHunkAdditionEnd = getHunkSideEndBoundary(hunk.additionStart, hunk.additionCount);
	}
	if (hydratedHunks.length > 0) {
		const lastHunk = hydratedHunks[hydratedHunks.length - 1];
		const lastHunkEnd = getHunkSideEndBoundary(lastHunk.additionStart, lastHunk.additionCount);
		const collapsedAfter = Math.max(totalAdditionLines - lastHunkEnd, 0);
		splitLineCount += collapsedAfter;
		unifiedLineCount += collapsedAfter;
	}
	return {
		hunks: hydratedHunks,
		splitLineCount,
		unifiedLineCount
	};
}
function requireOldFile(fileDiff, files) {
	if (files.oldFile == null) throw new Error(`hydratePartialDiff: ${fileDiff.type} diff for ${fileDiff.name} requires oldFile`);
	return files.oldFile;
}
function requireNewFile(fileDiff, files) {
	if (files.newFile == null) throw new Error(`hydratePartialDiff: ${fileDiff.type} diff for ${fileDiff.name} requires newFile`);
	return files.newFile;
}
function requireMissingOldFile(fileDiff, files) {
	if (files.oldFile !== null) throw new Error(`hydratePartialDiff: ${fileDiff.type} diff for ${fileDiff.name} requires oldFile to be null`);
}
function getHydratedCacheKey(fileDiff, oldFile, newFile) {
	if (fileDiff.cacheKey != null) return `${fileDiff.cacheKey}:hydrated`;
	return getLoadedFileCacheKey(oldFile, newFile);
}
function setHydratedCacheKey(fileDiff, oldFile, newFile) {
	const cacheKey = getHydratedCacheKey(fileDiff, oldFile, newFile);
	if (cacheKey == null) {
		delete fileDiff.cacheKey;
		return;
	}
	fileDiff.cacheKey = cacheKey;
}
function getLoadedFileCacheKey(oldFile, newFile) {
	if (oldFile != null && newFile != null) return oldFile.cacheKey != null && newFile.cacheKey != null ? `${oldFile.cacheKey}:${newFile.cacheKey}` : void 0;
	return oldFile?.cacheKey ?? newFile?.cacheKey;
}
//#endregion
export { hydratePartialDiff };

//# sourceMappingURL=hydratePartialDiff.js.map