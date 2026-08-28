//#region src/editor/utils.ts
function h(tagName, props, parent) {
	const { style, dataset, children, ...attrs } = props ?? {};
	const el = document.createElement(tagName);
	Object.assign(el, attrs);
	if (style !== void 0) if (typeof style === "string") el.style.cssText = style;
	else Object.assign(el.style, style);
	if (dataset !== void 0) if (typeof dataset === "string") el.dataset[dataset] = "";
	else if (Array.isArray(dataset)) dataset.forEach((key) => {
		el.dataset[key] = "";
	});
	else Object.assign(el.dataset, dataset);
	if (children !== void 0) el.replaceChildren(...children);
	if (parent !== void 0) parent.appendChild(el);
	return el;
}
function addEventListener(el, event, listener, options) {
	el.addEventListener(event, listener, options);
	return () => el.removeEventListener(event, listener, options);
}
function getLineNumberAttr(el, key = "line") {
	const value = el.dataset[key];
	if (value === void 0) return;
	const lineNumber = parseInt(value, 10);
	if (Number.isNaN(lineNumber)) return;
	return lineNumber;
}
function clampDomOffset(node, offset) {
	if (node.nodeType === 3) {
		const length = node.textContent?.length ?? 0;
		return Math.max(0, Math.min(offset, length));
	}
	if (node.nodeType === 1) return Math.max(0, Math.min(offset, node.childNodes.length));
	return 0;
}
function extend(obj, attrs) {
	return Object.assign(obj, attrs);
}
function debounce(func, wait) {
	let timeout;
	return function(...args) {
		clearTimeout(timeout);
		timeout = setTimeout(() => func.apply(this, args), wait);
	};
}
function round(value, precision = 1e3) {
	return Math.round(value * precision) / precision;
}
function endsWithLineBreak(text) {
	return text.endsWith("\n") || text.endsWith("\r");
}
function createSegmenter(options) {
	if (typeof Intl === "undefined" || typeof Intl.Segmenter !== "function") return;
	return new Intl.Segmenter(void 0, options);
}
let graphemeSegmenter;
let graphemeSegmenterInit = false;
function getGraphemeSegmenter() {
	if (!graphemeSegmenterInit) {
		graphemeSegmenter = createSegmenter({ granularity: "grapheme" });
		graphemeSegmenterInit = true;
	}
	return graphemeSegmenter;
}
function lookupScrollContainer(element) {
	const ownerDocument = element.ownerDocument;
	let parentElement = element.parentElement;
	while (parentElement != null && parentElement !== ownerDocument.body && parentElement !== ownerDocument.documentElement) {
		const overflowY = parentElement.ownerDocument.defaultView?.getComputedStyle(parentElement).overflowY;
		if (overflowY === "auto" || overflowY === "scroll" || overflowY === "overlay") return parentElement;
		parentElement = parentElement.parentElement;
	}
	return ownerDocument;
}
//#endregion
export { addEventListener, clampDomOffset, createSegmenter, debounce, endsWithLineBreak, extend, getGraphemeSegmenter, getLineNumberAttr, h, lookupScrollContainer, round };

//# sourceMappingURL=utils.js.map