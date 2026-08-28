//#region src/utils/cloneFileDiffMetadata.ts
function cloneFileDiffMetadata(fileDiff) {
	return {
		...fileDiff,
		hunks: fileDiff.hunks.map((hunk) => ({
			...hunk,
			hunkContent: hunk.hunkContent.map((content) => ({ ...content }))
		})),
		deletionLines: [...fileDiff.deletionLines],
		additionLines: [...fileDiff.additionLines]
	};
}
//#endregion
export { cloneFileDiffMetadata };

//# sourceMappingURL=cloneFileDiffMetadata.js.map