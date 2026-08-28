//#region src/utils/isGutterUtilityPath.ts
function isGutterUtilityPath(path) {
	for (const element of path) {
		if (!(element instanceof HTMLElement)) continue;
		if (element.hasAttribute("data-utility-button") || element.hasAttribute("data-gutter-utility-slot") || element.getAttribute("slot") === "gutter-utility-slot" || element.getAttribute("name") === "gutter-utility-slot") return true;
	}
	return false;
}
//#endregion
export { isGutterUtilityPath };

//# sourceMappingURL=isGutterUtilityPath.js.map