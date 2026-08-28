//#region src/utils/getDiffFileInput.ts
function getDiffFileInput({ oldFile, newFile }, context) {
	if (oldFile === void 0 && newFile === void 0) return;
	if (oldFile === void 0 || newFile === void 0) throw new Error(`${context}: Pass null for an intentionally missing oldFile or newFile side`);
	if (oldFile === null) {
		if (newFile === null) throw new Error(`${context}: You must pass oldFile, newFile, or both`);
		return {
			oldFile,
			newFile
		};
	}
	if (newFile === null) return {
		oldFile,
		newFile
	};
	return {
		oldFile,
		newFile
	};
}
//#endregion
export { getDiffFileInput };

//# sourceMappingURL=getDiffFileInput.js.map