//#region src/utils/getHunkSideBoundaries.ts
/** Converts a unified hunk side's start/count into its consumed-file range. */
function getHunkSideStartBoundary(start, count) {
	return start - (count === 0 ? 0 : 1);
}
function getHunkSideEndBoundary(start, count) {
	return getHunkSideStartBoundary(start, count) + count;
}
//#endregion
export { getHunkSideEndBoundary, getHunkSideStartBoundary };

//# sourceMappingURL=getHunkSideBoundaries.js.map