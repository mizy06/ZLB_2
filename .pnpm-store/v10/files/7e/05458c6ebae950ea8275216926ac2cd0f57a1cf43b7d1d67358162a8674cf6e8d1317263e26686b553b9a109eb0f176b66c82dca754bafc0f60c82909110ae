//#region src/utils/cleanLastNewline.ts
function cleanLastNewline(contents) {
	let end = contents.length;
	if (contents.charCodeAt(end - 1) === 10) {
		end--;
		if (contents.charCodeAt(end - 1) === 13) end--;
	}
	return contents.slice(0, end);
}
//#endregion
export { cleanLastNewline };

//# sourceMappingURL=cleanLastNewline.js.map