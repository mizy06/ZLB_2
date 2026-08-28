import { getLineAnnotationName } from "../utils/getLineAnnotationName.js";
import { getLineNumberAttr, h } from "./utils.js";
//#region src/editor/lineAnnotations.ts
function applyDocumentChangeToLineAnnotations(change, lineAnnotations) {
	const annotationChanges = getLineAnnotationChanges(change);
	if (annotationChanges.length === 0) return;
	const nextLineAnnotations = [];
	let changed = false;
	for (const annotation of lineAnnotations) {
		if (annotation.side === "deletions" || annotation.lineNumber <= 0) {
			nextLineAnnotations.push(annotation);
			continue;
		}
		let line = annotation.lineNumber - 1;
		let lineCount = change.previousLineCount;
		let annotationChanged = false;
		for (const lineChange of annotationChanges) {
			const nextLineCount = Math.max(1, lineCount + lineChange.lineDelta);
			const nextLine = mapLineThroughLineChange(line, lineChange, nextLineCount);
			if (nextLine === void 0) {
				annotationChanged = true;
				line = void 0;
				break;
			}
			if (nextLine !== line || lineChangeTouchesAnnotationLine(line, lineChange)) annotationChanged = true;
			line = nextLine;
			lineCount = nextLineCount;
		}
		if (line === void 0) {
			changed = true;
			continue;
		}
		const lineNumber = line + 1;
		if (annotationChanged) {
			nextLineAnnotations.push(lineNumber === annotation.lineNumber ? annotation : {
				...annotation,
				lineNumber
			});
			changed = true;
			continue;
		}
		nextLineAnnotations.push(annotation);
	}
	return changed ? nextLineAnnotations : void 0;
}
function getLineAnnotationChanges(change) {
	if (change.changedLineChanges !== void 0) return change.changedLineChanges.flatMap(([startLine, changedEndLine, lineDelta, startCharacter = 0, _endCharacter = 0, endedAtDocumentEnd = false]) => {
		if (lineDelta === 0) return [];
		const insertedLineBreaks = Math.max(0, changedEndLine - startLine);
		return [{
			startLine,
			startCharacter,
			endLine: startLine + Math.max(0, insertedLineBreaks - lineDelta),
			deletesEndLine: lineDelta < 0 && endedAtDocumentEnd,
			insertedLineBreaks,
			lineDelta
		}];
	});
	if (change.lineDelta === 0) return change.changedLineRanges.flatMap(([startLine, endLine]) => {
		const insertedLineBreaks = endLine - startLine;
		if (insertedLineBreaks <= 0) return [];
		return [{
			startLine,
			startCharacter: 0,
			endLine: startLine,
			deletesEndLine: false,
			insertedLineBreaks,
			lineDelta: insertedLineBreaks
		}];
	});
	const removedLineCount = Math.max(0, -change.lineDelta);
	const deletedToDocumentEnd = change.endedAtDocumentEnd && change.startLine + removedLineCount === change.previousLineCount - 1;
	return [{
		startLine: change.startLine,
		startCharacter: change.startCharacter,
		endLine: change.startLine + removedLineCount,
		deletesEndLine: deletedToDocumentEnd,
		insertedLineBreaks: Math.max(0, change.lineDelta),
		lineDelta: change.lineDelta
	}];
}
function mapLineThroughLineChange(line, lineChange, nextLineCount) {
	if (line < lineChange.startLine) return line;
	if (line > lineChange.endLine || lineChange.endLine > lineChange.startLine && line === lineChange.endLine && !lineChange.deletesEndLine) return line + lineChange.lineDelta;
	if (lineChange.startLine === lineChange.endLine) {
		if (lineChange.startCharacter === 0) return line + lineChange.insertedLineBreaks;
		return line;
	}
	if (lineChangeDeletesAnnotationLine(line, lineChange)) return;
	const replacementLineOffset = Math.min(Math.max(0, line - lineChange.startLine), lineChange.insertedLineBreaks);
	return clampLine(lineChange.startLine + replacementLineOffset, nextLineCount);
}
function lineChangeDeletesAnnotationLine(line, lineChange) {
	if (lineChange.lineDelta >= 0 || line < lineChange.startLine || line > lineChange.endLine) return false;
	if (line === lineChange.startLine && lineChange.startCharacter > 0) return false;
	if (line === lineChange.endLine && !lineChange.deletesEndLine) return false;
	return true;
}
function lineChangeTouchesAnnotationLine(line, lineChange) {
	if (lineChange.lineDelta === 0 || line < lineChange.startLine || line > lineChange.endLine) return false;
	return !(lineChange.endLine > lineChange.startLine && line === lineChange.endLine && !lineChange.deletesEndLine);
}
function clampLine(line, lineCount) {
	return Math.max(0, Math.min(line, Math.max(0, lineCount - 1)));
}
function renderLineAnnotations(lineAnnotations, contentEl, gutterEl) {
	const additionAnnotations = /* @__PURE__ */ new Map();
	const deletionAnnotations = /* @__PURE__ */ new Map();
	for (const annotation of lineAnnotations) {
		const lineNumber = annotation.lineNumber;
		if (!additionAnnotations.has(lineNumber)) additionAnnotations.set(lineNumber, []);
		if (!deletionAnnotations.has(lineNumber)) deletionAnnotations.set(lineNumber, []);
		(annotation.side === "deletions" ? deletionAnnotations : additionAnnotations).get(lineNumber).push(getLineAnnotationName(annotation));
	}
	const leftCodeElement = contentEl.parentElement?.previousElementSibling;
	let leftGutterElement;
	let leftContentElement;
	if (leftCodeElement != null && leftCodeElement instanceof HTMLElement && leftCodeElement.dataset.deletions !== void 0) for (const child of leftCodeElement.children) {
		const el = child;
		const { gutter, content } = el.dataset;
		if (gutter !== void 0) leftGutterElement = el;
		else if (content !== void 0) leftContentElement = el;
	}
	cleanLineAnnotationElements(contentEl, gutterEl);
	if (leftContentElement !== void 0) cleanLineAnnotationElements(leftContentElement, leftGutterElement);
	const additionsAnnotationElements = createLineAnnotationElements(additionAnnotations, contentEl, gutterEl);
	if (leftContentElement === void 0) return;
	const deletionsAnnotationElements = createLineAnnotationElements(deletionAnnotations, leftContentElement, leftGutterElement);
	requestAnimationFrame(() => {
		syncPairedLineAnnotationHeights(additionAnnotations, deletionAnnotations, additionsAnnotationElements, deletionsAnnotationElements);
	});
}
function cleanLineAnnotationElements(contentEl, gutterEl) {
	const staleElements = [];
	for (let i = 1; i < contentEl.childElementCount; i++) {
		const el = contentEl.children[i];
		if (el.dataset.lineAnnotation !== void 0) {
			staleElements.push(el);
			if (gutterEl !== void 0) staleElements.push(gutterEl.children[i]);
		}
	}
	for (const el of staleElements) el.remove();
}
function createLineAnnotationElements(lineAnnotations, contentEl, gutterEl) {
	const annotationElements = /* @__PURE__ */ new Map();
	for (const el of contentEl.children) {
		const lineNumber = getLineNumberAttr(el);
		if (lineNumber !== void 0) {
			const annotations = lineAnnotations.get(lineNumber);
			if (annotations !== void 0) {
				const annotationElement = h("div", {
					dataset: { lineAnnotation: "0," + (lineNumber - 1) },
					children: [h("div", {
						dataset: "annotationContent",
						children: annotations.map((name) => h("slot", { name }))
					})]
				});
				el.after(annotationElement);
				annotationElements.set(lineNumber, annotationElement);
			}
		}
	}
	if (gutterEl !== void 0) for (const el of gutterEl.children) {
		const lineNumber = getLineNumberAttr(el, "columnNumber");
		if (lineNumber !== void 0 && lineAnnotations.has(lineNumber)) {
			const bufferEl = h("div", {
				dataset: {
					gutterBuffer: "annotation",
					bufferSize: "1"
				},
				style: { gridRow: "span 1" }
			});
			el.after(bufferEl);
		}
	}
	return annotationElements;
}
function syncPairedLineAnnotationHeights(additionAnnotations, deletionAnnotations, additionAnnotationElements, deletionAnnotationElements) {
	const offsetHeights = /* @__PURE__ */ new Map();
	for (const [lineNumber, annotations] of additionAnnotations.entries()) {
		const annotationElement = deletionAnnotationElements.get(lineNumber);
		if (annotations.length === 0 && annotationElement !== void 0) {
			const height = measureAnnotationContentHeight(annotationElement);
			if (height > 0) offsetHeights.set(lineNumber, height);
		}
	}
	for (const [lineNumber, annotations] of deletionAnnotations.entries()) {
		const annotationElement = additionAnnotationElements.get(lineNumber);
		if (annotations.length === 0 && annotationElement !== void 0) {
			const height = measureAnnotationContentHeight(annotationElement);
			if (height > 0) offsetHeights.set(lineNumber, height);
		}
	}
	applyLineAnnotationMinHeights(additionAnnotations, additionAnnotationElements, offsetHeights);
	applyLineAnnotationMinHeights(deletionAnnotations, deletionAnnotationElements, offsetHeights);
}
function measureAnnotationContentHeight(lineAnnotationEl) {
	const content = lineAnnotationEl.firstElementChild;
	if (!(content instanceof HTMLElement)) return 0;
	return content.getBoundingClientRect().height;
}
function applyLineAnnotationMinHeights(lineAnnotations, annotationElements, offsetHeights) {
	for (const [lineNumber, annotationElement] of annotationElements.entries()) {
		const annotations = lineAnnotations.get(lineNumber);
		const offsetHeight = offsetHeights.get(lineNumber);
		if (annotations?.length === 0 && offsetHeight !== void 0) annotationElement.style.setProperty("--diffs-annotation-min-height", `${offsetHeight}px`);
	}
}
//#endregion
export { applyDocumentChangeToLineAnnotations, renderLineAnnotations };

//# sourceMappingURL=lineAnnotations.js.map