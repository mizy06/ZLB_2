import { countLineBreaks } from "../utils/computeFileOffsets.js";
import { EditStack, coalesceEditStackEntries, createEditStackEntry, shouldCoalesceEditStackEntry } from "./editStack.js";
import { PieceTable } from "./pieceTable.js";
//#region src/editor/textDocument.ts
/**
* A vscode-languageserver-textdocument compatible text document.
*/
var TextDocument = class TextDocument {
	#uri;
	#languageId;
	#version;
	#pieceTable;
	#editStack;
	#eol;
	constructor(uri, text, languageId = "text", version = 0, editStack = new EditStack()) {
		this.#uri = new URL(uri, "file://").toString();
		this.#languageId = languageId;
		this.#version = version;
		this.#pieceTable = new PieceTable(text);
		this.#editStack = editStack;
		const firstLineBreak = this.#pieceTable.getLineText(0, true);
		if (firstLineBreak.endsWith("\r\n")) this.#eol = "\r\n";
		else if (firstLineBreak.endsWith("\r")) this.#eol = "\r";
		else this.#eol = "\n";
	}
	get uri() {
		return this.#uri;
	}
	get languageId() {
		return this.#languageId;
	}
	get version() {
		return this.#version;
	}
	get lineCount() {
		return this.#pieceTable.lineCount;
	}
	get eol() {
		return this.#eol;
	}
	get canUndo() {
		return this.#editStack.canUndo;
	}
	get canRedo() {
		return this.#editStack.canRedo;
	}
	positionAt(offset) {
		return this.normalizePosition(this.#pieceTable.positionAt(offset));
	}
	positionsAt(offsets) {
		const positions = this.#pieceTable.positionsAt(offsets);
		for (let i = 0; i < positions.length; i++) positions[i] = this.normalizePosition(positions[i]);
		return positions;
	}
	offsetAt(position) {
		return this.#pieceTable.offsetAt(this.normalizePosition(position));
	}
	getText(range) {
		if (range === void 0) return this.#pieceTable.getText();
		return this.#pieceTable.getText({
			start: this.normalizePosition(range.start),
			end: this.normalizePosition(range.end)
		});
	}
	getLineText(line, includeLineBreak) {
		return this.#pieceTable.getLineText(line, includeLineBreak);
	}
	normalizeEol(text) {
		return text.replace(/\r\n|\r|\n/g, this.eol);
	}
	getLineLength(line, includeLineBreak) {
		return this.#pieceTable.getLineLength(line, includeLineBreak);
	}
	charAt(positionOrOffset) {
		if (typeof positionOrOffset === "number") return this.#pieceTable.charAt(positionOrOffset);
		return this.#pieceTable.charAt(this.offsetAt(positionOrOffset));
	}
	getTextSlice(start, end) {
		return this.#pieceTable.getTextSlice(start, end);
	}
	findNextNonOverlappingSubstring(needle, occupied) {
		return this.#pieceTable.findNextNonOverlappingSubstring(needle, occupied);
	}
	search(searchParams) {
		return this.#pieceTable.search(searchParams);
	}
	applyEdits(edits, updateHistory = true, selectionsBefore, selectionsAfter, undoBoundary = false) {
		if (edits.length === 0) return;
		return this.#applyResolvedEdits(this.#sortAndValidateResolvedEdits(this.resolveEdits(edits)), updateHistory, selectionsBefore, selectionsAfter, undoBoundary);
	}
	resolveEdits(edits) {
		return edits.map((edit) => this.#resolveEdit(edit));
	}
	applyResolvedEdits(edits, updateHistory = true, selectionsBefore, selectionsAfter, undoBoundary = false) {
		if (edits.length === 0) return;
		return this.#applyResolvedEdits(this.#sortAndValidateResolvedEdits(edits.map((edit) => this.#normalizeResolvedEdit(edit))), updateHistory, selectionsBefore, selectionsAfter, undoBoundary);
	}
	#applyResolvedEdits(resolvedEdits, updateHistory, selectionsBefore, selectionsAfter, undoBoundary) {
		const entry = createEditStackEntry(this, resolvedEdits, this.#version, this.#version + 1, updateHistory ? selectionsBefore : void 0, updateHistory ? selectionsAfter : void 0);
		if (updateHistory && undoBoundary) entry.undoBoundary = true;
		const previousEntry = this.#editStack.peekUndoForCoalescing();
		const change = this.#applyResolvedEditsToBuffer(resolvedEdits);
		this.#version++;
		if (change.lineDelta === 0 && shouldCoalesceEditStackEntry(previousEntry, entry)) this.#editStack.replaceLastUndo(coalesceEditStackEntries(previousEntry, entry));
		else this.#editStack.push(entry);
		return change;
	}
	setLastUndoSelectionsAfter(selections) {
		this.#editStack.setLastUndoSelectionsAfter(selections);
	}
	setLastUndoLineAnnotations(lineAnnotationsBefore, lineAnnotationsAfter) {
		this.#editStack.setLastUndoLineAnnotations(lineAnnotationsBefore, lineAnnotationsAfter);
	}
	undo() {
		const entry = this.#editStack.popUndoToRedo();
		if (entry === void 0) return;
		const change = this.#applyResolvedEditsToBuffer(entry.inverseEdits);
		if (change === void 0) return;
		this.#version = entry.versionBefore;
		const selections = entry.selectionsBefore?.slice();
		return [
			change,
			selections,
			entry.lineAnnotationsBefore?.slice(),
			selections === void 0 ? entry.inverseEdits.map((edit) => ({ ...edit })) : void 0
		];
	}
	redo() {
		const entry = this.#editStack.popRedoToUndo();
		if (entry === void 0) return;
		const change = this.#applyResolvedEditsToBuffer(entry.forwardEdits);
		if (change === void 0) return;
		this.#version = entry.versionAfter;
		const selections = entry.selectionsAfter?.slice();
		return [
			change,
			selections,
			entry.lineAnnotationsAfter?.slice(),
			selections === void 0 ? entry.forwardEdits.map((edit) => ({ ...edit })) : void 0
		];
	}
	normalizePosition(position) {
		const line = TextDocument.#clampIndex(position.line, this.lineCount - 1);
		return {
			line,
			character: TextDocument.#clampIndex(position.character, this.getLineLength(line))
		};
	}
	static #clampIndex(value, max) {
		if (Number.isNaN(value)) return 0;
		return Math.max(0, Math.min(Math.floor(value), max));
	}
	#resolveEdit(edit) {
		let start = this.offsetAt(edit.range.start);
		let end = this.offsetAt(edit.range.end);
		if (start > end) {
			const t = start;
			start = end;
			end = t;
		}
		return this.#normalizeResolvedEdit({
			start,
			end,
			text: edit.newText
		});
	}
	#normalizeResolvedEdit(edit) {
		let { start, end } = edit;
		const isInsertion = start === end;
		if (this.#isInsideSurrogatePair(start)) start--;
		if (isInsertion) end = start;
		else if (this.#isInsideSurrogatePair(end)) end++;
		return {
			start,
			end,
			text: edit.text
		};
	}
	#isInsideSurrogatePair(offset) {
		const previous = this.#pieceTable.charAt(offset - 1).charCodeAt(0);
		const next = this.#pieceTable.charAt(offset).charCodeAt(0);
		return previous >= 55296 && previous <= 56319 && next >= 56320 && next <= 57343;
	}
	#sortAndValidateResolvedEdits(edits) {
		const sortedEdits = [...edits].sort((a, b) => {
			const startDelta = a.start - b.start;
			return startDelta === 0 ? a.end - b.end : startDelta;
		});
		for (let i = 0; i < sortedEdits.length - 1; i++) if (sortedEdits[i].end > sortedEdits[i + 1].start) throw new Error("Overlapping text edits are not supported");
		return sortedEdits;
	}
	#applyResolvedEditsToBuffer(edits) {
		const previousLineCount = this.#pieceTable.lineCount;
		const editPositions = this.positionsAt(edits.flatMap((edit) => [edit.start, edit.end]));
		const changedLineRange = this.#computeChangedLineRange(edits, editPositions);
		const startPosition = editPositions[0];
		const endPosition = editPositions[editPositions.length - 1];
		const endedAtDocumentEnd = endPosition.line === previousLineCount - 1 && endPosition.character === this.#pieceTable.getLineLength(endPosition.line);
		this.#pieceTable.applyEdits(edits);
		const lineCount = this.#pieceTable.lineCount;
		return {
			changes: edits.map((edit, index) => ({
				...edit,
				range: {
					start: editPositions[index * 2],
					end: editPositions[index * 2 + 1]
				}
			})),
			startLine: changedLineRange.startLine,
			startCharacter: startPosition.character,
			endCharacter: endPosition.character,
			endLine: Math.min(changedLineRange.endLine, Math.max(0, lineCount - 1)),
			endedAtDocumentEnd,
			previousLineCount,
			lineCount,
			lineDelta: lineCount - previousLineCount,
			changedLineRanges: changedLineRange.ranges,
			changedLineChanges: changedLineRange.changes
		};
	}
	#computeChangedLineRange(edits, editPositions) {
		let startLine = Infinity;
		let endLine = 0;
		let lineDeltaBeforeEdit = 0;
		const ranges = [];
		const changes = [];
		const previousLastLine = this.#pieceTable.lineCount - 1;
		const previousLastLineLength = this.#pieceTable.getLineLength(previousLastLine);
		for (let i = 0; i < edits.length; i++) {
			const edit = edits[i];
			const editStart = editPositions[i * 2];
			const editEnd = editPositions[i * 2 + 1];
			const editStartLine = editStart.line;
			const editEndLine = editEnd.line;
			const insertedLineSpan = countLineBreaks(edit.text);
			const changedStartLine = editStartLine + lineDeltaBeforeEdit;
			const changedEndLine = changedStartLine + insertedLineSpan;
			const lineDelta = insertedLineSpan - (editEndLine - editStartLine);
			startLine = Math.min(startLine, editStartLine);
			endLine = Math.max(endLine, changedEndLine);
			const lastRange = ranges[ranges.length - 1];
			if (lastRange !== void 0 && changedStartLine <= lastRange[1] + 1) ranges[ranges.length - 1] = [lastRange[0], Math.max(lastRange[1], changedEndLine)];
			else ranges.push([changedStartLine, changedEndLine]);
			changes.push([
				changedStartLine,
				changedEndLine,
				lineDelta,
				editStart.character,
				editEnd.character,
				editEndLine === previousLastLine && editEnd.character === previousLastLineLength
			]);
			lineDeltaBeforeEdit += lineDelta;
		}
		if (startLine === Infinity) return {
			startLine: 0,
			endLine: 0,
			ranges: [[0, 0]],
			changes: [[
				0,
				0,
				0,
				0,
				0,
				false
			]]
		};
		return {
			startLine,
			endLine,
			ranges,
			changes
		};
	}
};
//#endregion
export { TextDocument };

//# sourceMappingURL=textDocument.js.map