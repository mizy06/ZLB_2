//#region src/editor/editStack.ts
/** Largest number of undo or redo entries kept; oldest entries drop first once exceeded. */
const DEFAULT_EDIT_STACK_MAX_ENTRIES = 100;
const COALESCING_MODE_INSERT = 1;
const COALESCING_MODE_BACKSPACE = 2;
const COALESCING_MODE_DELETE = 3;
/** A stack of edit entries. */
var EditStack = class {
	#undoStack = [];
	#redoStack = [];
	#maxEntries;
	#canCoalesce = false;
	constructor(options) {
		this.#maxEntries = Math.max(1, options?.maxEntries ?? DEFAULT_EDIT_STACK_MAX_ENTRIES);
	}
	get canUndo() {
		return this.#undoStack.length > 0;
	}
	get canRedo() {
		return this.#redoStack.length > 0;
	}
	/** Clears both the undo and redo stacks. */
	clear() {
		this.#undoStack.length = 0;
		this.#redoStack.length = 0;
		this.#canCoalesce = false;
	}
	/** Clears the redo stack. */
	clearRedo() {
		this.#redoStack.length = 0;
	}
	/** Pushes a new entry onto the undo stack. */
	push(entry) {
		this.#undoStack.push(entry);
		this.clearRedo();
		this.#canCoalesce = true;
		if (this.#undoStack.length > this.#maxEntries) this.#undoStack.shift();
	}
	/** Sets the selections after the last undo entry. */
	setLastUndoSelectionsAfter(selections) {
		const lastEntry = this.#undoStack[this.#undoStack.length - 1];
		if (lastEntry !== void 0) lastEntry.selectionsAfter = selections.map((selection) => ({ ...selection }));
	}
	/** Sets the line annotations after the last undo entry. */
	setLastUndoLineAnnotations(lineAnnotationsBefore, lineAnnotationsAfter) {
		const lastEntry = this.#undoStack[this.#undoStack.length - 1];
		if (lastEntry !== void 0) {
			lastEntry.lineAnnotationsBefore = lineAnnotationsBefore.slice();
			lastEntry.lineAnnotationsAfter = lineAnnotationsAfter.slice();
		}
	}
	/** Returns the last undo entry, or `undefined` if empty. */
	peekUndo() {
		return this.#undoStack[this.#undoStack.length - 1];
	}
	/** Returns the last undo entry only while its coalescing group is open. */
	peekUndoForCoalescing() {
		return this.#canCoalesce ? this.peekUndo() : void 0;
	}
	/** Replaces the last undo entry with the given entry. */
	replaceLastUndo(entry) {
		if (this.#undoStack.length === 0) {
			this.push(entry);
			return;
		}
		this.#undoStack[this.#undoStack.length - 1] = entry;
		this.clearRedo();
		this.#canCoalesce = true;
	}
	/** Moves the latest undo entry to the redo stack and returns it, or `undefined` if empty. */
	popUndoToRedo() {
		const entry = this.#undoStack.pop();
		if (entry !== void 0) {
			this.#redoStack.push(entry);
			this.#canCoalesce = false;
			return entry;
		}
	}
	/** Moves the latest redo entry back to the undo stack and returns it, or `undefined` if empty. */
	popRedoToUndo() {
		const entry = this.#redoStack.pop();
		if (entry !== void 0) {
			this.#undoStack.push(entry);
			this.#canCoalesce = false;
			return entry;
		}
	}
};
function createEditStackEntry(textDocument, resolvedEdits, versionBefore, versionAfter, selectionsBefore, selectionsAfter, lineAnnotationsBefore, lineAnnotationsAfter) {
	const forwardEdits = [...resolvedEdits].sort((a, b) => a.start - b.start);
	const inverseEdits = [];
	let coalescingMode;
	if (selectionsBefore?.length === forwardEdits.length) {
		const caretOffsets = [];
		for (const selection of selectionsBefore) {
			if (selection.start.line !== selection.end.line || selection.start.character !== selection.end.character) break;
			caretOffsets.push(textDocument.offsetAt(selection.start));
		}
		if (caretOffsets.length === forwardEdits.length) {
			caretOffsets.sort((a, b) => a - b);
			let isBackspace = true;
			let isDelete = true;
			for (let i = 0; i < forwardEdits.length; i++) {
				const edit = forwardEdits[i];
				if (edit.text.length > 0 || edit.start === edit.end) {
					isBackspace = false;
					isDelete = false;
					break;
				}
				isBackspace &&= caretOffsets[i] === edit.end;
				isDelete &&= caretOffsets[i] === edit.start;
			}
			coalescingMode = isBackspace ? COALESCING_MODE_BACKSPACE : isDelete ? COALESCING_MODE_DELETE : void 0;
		}
	}
	for (let i = 0, offsetDelta = 0; i < forwardEdits.length; i++) {
		const edit = forwardEdits[i];
		const replacedText = textDocument.getTextSlice(edit.start, edit.end);
		const startAfterEdit = edit.start + offsetDelta;
		inverseEdits.push({
			start: startAfterEdit,
			end: startAfterEdit + edit.text.length,
			text: replacedText
		});
		offsetDelta += edit.text.length - (edit.end - edit.start);
	}
	return {
		forwardEdits: forwardEdits.map((edit) => ({ ...edit })),
		inverseEdits,
		versionBefore,
		versionAfter,
		selectionsBefore: selectionsBefore?.map((selection) => ({ ...selection })),
		selectionsAfter: selectionsAfter?.map((selection) => ({ ...selection })),
		lineAnnotationsBefore: lineAnnotationsBefore?.slice(),
		lineAnnotationsAfter: lineAnnotationsAfter?.slice(),
		coalescingMode
	};
}
/** Determines if the change matches following modes:
* - 'insert': simple typing
* - 'backspace': backward delete
* - 'delete': forward delete
*/
function shouldCoalesceEditStackEntry(previousEntry, nextEntry) {
	if (previousEntry === void 0 || previousEntry.undoBoundary === true || nextEntry.undoBoundary === true || previousEntry.forwardEdits.length === 0 || previousEntry.forwardEdits.length !== previousEntry.inverseEdits.length || previousEntry.forwardEdits.length !== nextEntry.forwardEdits.length || nextEntry.forwardEdits.length !== nextEntry.inverseEdits.length) return false;
	let mode;
	for (let i = 0; i < previousEntry.forwardEdits.length; i++) {
		const previousForward = previousEntry.forwardEdits[i];
		const previousInverse = previousEntry.inverseEdits[i];
		const nextForward = nextEntry.forwardEdits[i];
		const nextInverse = nextEntry.inverseEdits[i];
		const mappedNextStart = mapOffsetAfterForwardBatchToBefore(nextForward.start, previousEntry.forwardEdits);
		const previousWasInsert = previousForward.start <= previousForward.end && previousForward.text.length > 0 && !previousForward.text.includes("\n") && !previousInverse.text.includes("\n");
		const nextIsInsert = nextForward.start === nextForward.end && nextForward.text.length > 0 && !nextForward.text.includes("\n") && nextInverse.text.length === 0;
		if (previousWasInsert && nextIsInsert) {
			if (nextForward.start !== previousInverse.end) return false;
			mode ??= COALESCING_MODE_INSERT;
			if (mode !== COALESCING_MODE_INSERT || previousEntry.coalescingMode !== void 0 && previousEntry.coalescingMode !== COALESCING_MODE_INSERT || nextEntry.coalescingMode !== void 0 && nextEntry.coalescingMode !== COALESCING_MODE_INSERT) return false;
			continue;
		}
		const previousWasDelete = previousForward.text.length === 0 && previousForward.end > previousForward.start && previousInverse.text.length > 0;
		const nextIsDelete = nextForward.text.length === 0 && nextForward.end > nextForward.start && nextInverse.text.length > 0;
		if (previousWasDelete && nextIsDelete) {
			let nextMode;
			if (mappedNextStart === previousForward.end) nextMode = COALESCING_MODE_DELETE;
			else if (mappedNextStart + (nextForward.end - nextForward.start) !== previousForward.start) return false;
			else nextMode = COALESCING_MODE_BACKSPACE;
			mode ??= nextMode;
			if (mode !== nextMode || previousEntry.coalescingMode !== void 0 && previousEntry.coalescingMode !== nextMode || nextEntry.coalescingMode !== void 0 && nextEntry.coalescingMode !== nextMode) return false;
			continue;
		}
		return false;
	}
	return mode !== void 0;
}
/** Coalesce edit stack entries for simple typing and single-character deletes. */
function coalesceEditStackEntries(previousEntry, nextEntry) {
	const forwardEdits = [];
	const replacedTexts = [];
	let coalescingMode;
	for (let i = 0; i < previousEntry.forwardEdits.length; i++) {
		const previousForward = previousEntry.forwardEdits[i];
		const previousInverse = previousEntry.inverseEdits[i];
		const nextForward = nextEntry.forwardEdits[i];
		const nextInverse = nextEntry.inverseEdits[i];
		const mappedNextStart = mapOffsetAfterForwardBatchToBefore(nextForward.start, previousEntry.forwardEdits);
		if (previousForward.text.length > 0) {
			coalescingMode ??= COALESCING_MODE_INSERT;
			forwardEdits.push({
				start: previousForward.start,
				end: previousForward.end,
				text: previousForward.text + nextForward.text
			});
			replacedTexts.push(previousInverse.text);
			continue;
		}
		if (mappedNextStart === previousForward.end) {
			coalescingMode ??= COALESCING_MODE_DELETE;
			forwardEdits.push({
				start: previousForward.start,
				end: mappedNextStart + (nextForward.end - nextForward.start),
				text: ""
			});
			replacedTexts.push(previousInverse.text + nextInverse.text);
			continue;
		}
		coalescingMode ??= COALESCING_MODE_BACKSPACE;
		forwardEdits.push({
			start: Math.min(previousForward.start, mappedNextStart),
			end: previousForward.end,
			text: ""
		});
		replacedTexts.push(nextInverse.text + previousInverse.text);
	}
	return {
		forwardEdits,
		inverseEdits: buildInverseEditsFromReplacedTexts(forwardEdits, replacedTexts),
		versionBefore: previousEntry.versionBefore,
		versionAfter: nextEntry.versionAfter,
		selectionsBefore: previousEntry.selectionsBefore?.slice(),
		selectionsAfter: nextEntry.selectionsAfter?.slice(),
		lineAnnotationsBefore: previousEntry.lineAnnotationsBefore?.slice(),
		lineAnnotationsAfter: nextEntry.lineAnnotationsAfter?.slice(),
		coalescingMode
	};
}
function buildInverseEditsFromReplacedTexts(forwardEdits, replacedTexts) {
	const inverseEdits = [];
	for (let i = 0, offsetDelta = 0; i < forwardEdits.length; i++) {
		const edit = forwardEdits[i];
		const startAfterEdit = edit.start + offsetDelta;
		inverseEdits.push({
			start: startAfterEdit,
			end: startAfterEdit + edit.text.length,
			text: replacedTexts[i]
		});
		offsetDelta += edit.text.length - (edit.end - edit.start);
	}
	return inverseEdits;
}
function mapOffsetAfterForwardBatchToBefore(offsetAfter, forwardEdits) {
	let offset = offsetAfter;
	for (const edit of forwardEdits) {
		const oldLength = edit.end - edit.start;
		const newLength = edit.text.length;
		const delta = newLength - oldLength;
		if (offset < edit.start) continue;
		if (offset >= edit.start + newLength) {
			offset -= delta;
			continue;
		}
		offset = edit.start + Math.min(offset - edit.start, oldLength);
	}
	return offset;
}
//#endregion
export { EditStack, coalesceEditStackEntries, createEditStackEntry, shouldCoalesceEditStackEntry };

//# sourceMappingURL=editStack.js.map