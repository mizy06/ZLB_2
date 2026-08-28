import { processFile } from "./parsePatchFiles.js";
import { createTwoFilesPatch } from "diff";
//#region src/utils/parseDiffFromFile.ts
const MISSING_FILE_NAME = "/dev/null";
/**
* Parses a diff from two file contents objects.
*
* If both `oldFile` and `newFile` have a `cacheKey`, the resulting diff will
* automatically get a combined cache key in the format `oldKey:newKey`.
*/
function parseDiffFromFile(oldFile, newFile, options, throwOnError = false) {
	if (oldFile === null && newFile === null) throw new Error("parseDiffFromFile: You must pass oldFile, newFile, or both");
	const resolvedOldFile = oldFile ?? createMissingFile();
	const resolvedNewFile = newFile ?? createMissingFile();
	const fileData = processFile(createTwoFilesPatch(resolvedOldFile.name, resolvedNewFile.name, resolvedOldFile.contents, resolvedNewFile.contents, resolvedOldFile.header, resolvedNewFile.header, options), {
		cacheKey: (() => {
			const oldCacheKey = oldFile?.cacheKey ?? oldFile?.name;
			const newCacheKey = newFile?.cacheKey ?? newFile?.name;
			if (oldCacheKey != null && newCacheKey != null) return oldCacheKey + ":" + newCacheKey;
			return oldCacheKey ?? newCacheKey;
		})(),
		oldFile: resolvedOldFile,
		newFile: resolvedNewFile,
		throwOnError
	});
	if (fileData == null) throw new Error("parseDiffFrom: FileInvalid diff -- probably need to fix something -- if the files are the same maybe?");
	if (oldFile === null) {
		fileData.type = "new";
		fileData.prevName = void 0;
	} else if (newFile === null) {
		fileData.type = "deleted";
		fileData.prevName = void 0;
	}
	const language = newFile?.lang ?? (newFile === null ? oldFile?.lang : void 0);
	if (language != null) fileData.lang = language;
	return fileData;
}
function createMissingFile() {
	return {
		name: MISSING_FILE_NAME,
		contents: ""
	};
}
//#endregion
export { parseDiffFromFile };

//# sourceMappingURL=parseDiffFromFile.js.map