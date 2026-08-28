import { CODE_VIEW_FOOTER_ATTRIBUTE, CODE_VIEW_HEADER_ATTRIBUTE } from "../constants.js";
//#region src/utils/createCodeViewHeaderFooterHostElement.ts
function createCodeViewHeaderFooterHostElement(type, container, resizeObserver) {
	const element = document.createElement("div");
	element.style.display = "flow-root";
	if (type === "header") {
		element.setAttribute(CODE_VIEW_HEADER_ATTRIBUTE, "");
		container.before(element);
	} else {
		element.setAttribute(CODE_VIEW_FOOTER_ATTRIBUTE, "");
		container.after(element);
	}
	resizeObserver?.observe(element);
	return element;
}
//#endregion
export { createCodeViewHeaderFooterHostElement };

//# sourceMappingURL=createCodeViewHeaderFooterHostElement.js.map