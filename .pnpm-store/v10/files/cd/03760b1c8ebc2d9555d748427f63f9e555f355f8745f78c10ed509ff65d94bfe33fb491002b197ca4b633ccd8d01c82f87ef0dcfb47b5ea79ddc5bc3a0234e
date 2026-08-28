import { getHunkSideEndBoundary } from "./getHunkSideBoundaries.js";
//#region src/utils/getTotalLineCountFromHunks.ts
function getTotalLineCountFromHunks(hunks) {
	const lastHunk = hunks.at(-1);
	if (lastHunk == null) return 0;
	return Math.max(getHunkSideEndBoundary(lastHunk.additionStart, lastHunk.additionCount), getHunkSideEndBoundary(lastHunk.deletionStart, lastHunk.deletionCount));
}
//#endregion
export { getTotalLineCountFromHunks };

//# sourceMappingURL=getTotalLineCountFromHunks.js.map