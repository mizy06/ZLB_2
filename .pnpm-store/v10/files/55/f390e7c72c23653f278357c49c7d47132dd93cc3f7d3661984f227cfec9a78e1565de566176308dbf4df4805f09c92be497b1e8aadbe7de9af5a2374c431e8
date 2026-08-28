import { createSegmenter, endsWithLineBreak, getGraphemeSegmenter } from "./utils.js";
import { applyDocumentChangeToLineAnnotations } from "./lineAnnotations.js";
//#region src/editor/selection.ts
const DirectionBackward = -1;
const DirectionNone = 0;
const DirectionForward = 1;
const AUTO_SURROUND_CLOSE_CHARS = /* @__PURE__ */ new Map([
	["'", "'"],
	["\"", "\""],
	["`", "`"],
	["{", "}"],
	["[", "]"],
	["<", ">"],
	["(", ")"]
]);
const AUTO_SURROUND_QUOTE_CHARS = /* @__PURE__ */ new Set([
	"'",
	"\"",
	"`"
]);
const AUTO_SURROUND_BRACKET_CHARS = /* @__PURE__ */ new Set([
	"{",
	"[",
	"(",
	"<"
]);
/**
* Converts a selection from a web selection to an editor selection.
*/
function convertSelection(range, direction = 0) {
	const start = boundaryToPosition(range.startContainer, range.startOffset);
	const end = boundaryToPosition(range.endContainer, range.endOffset);
	if (start === null || end === null) return;
	return {
		start,
		end,
		direction
	};
}
/**
* Resolves the indent edits for a selection.
*/
function resolveIndentEdits(textDocument, selection, tabSize, outdent) {
	if (textDocument === void 0) return [[], selection];
	const { start, end } = selection;
	const edits = [];
	let newSelection = { ...selection };
	const blockIndent = start.line !== end.line;
	let endLine = end.line;
	if (start.line < end.line && end.character === 0) endLine--;
	for (let line = start.line; line <= endLine; line++) {
		const lineText = textDocument.getLineText(line);
		if (lineText === void 0) continue;
		if (blockIndent && lineText.trim().length === 0) continue;
		const indentUnit = lineText.startsWith("	") ? "	" : " ".repeat(tabSize);
		let deleteLength = 0;
		let newText = indentUnit;
		if (outdent) {
			if (lineText.startsWith("	")) deleteLength = 1;
			else if (lineText.startsWith(" ")) {
				const leadingSpacesLength = lineText.length - lineText.trimStart().length;
				deleteLength = Math.min(indentUnit.length, leadingSpacesLength);
			}
			if (deleteLength === 0) continue;
			newText = "";
		}
		edits.push({
			range: {
				start: {
					line,
					character: 0
				},
				end: {
					line,
					character: deleteLength
				}
			},
			newText
		});
		const delta = newText.length - deleteLength;
		if (line === start.line) newSelection = {
			...newSelection,
			start: {
				...start,
				character: Math.max(0, start.character + delta)
			}
		};
		if (line === end.line) newSelection = {
			...newSelection,
			end: {
				...end,
				character: Math.max(0, end.character + delta)
			}
		};
	}
	return [edits, newSelection];
}
/**
* Maps the cursor move to all selections.
*/
function mapCursorMove(textDocument, selections, shortcut, options = {}) {
	const lineCount = textDocument.lineCount;
	return selections.map((selection) => {
		let { line, character } = shortcut === "up" || shortcut === "left" ? selection.start : selection.end;
		if (shortcut === "textStart" || shortcut === "start" || shortcut === "end") {
			const caret = getCaretPosition(selection);
			line = caret.line;
			character = caret.character;
			const softLine = getSoftLineInfo(textDocument, line, character, options);
			if (shortcut === "textStart") {
				const softLineText = textDocument.getLineText(line).slice(softLine.start, softLine.end);
				const indent = softLine.start + getLeadingSpaces(softLineText);
				character = character === indent ? softLine.start : indent;
			} else character = shortcut === "start" ? softLine.start : softLine.end;
		} else if (shortcut === "up") {
			const moved = moveBySoftLine(textDocument, line, character, -1, options);
			if (moved !== void 0) {
				line = moved.line;
				character = moved.character;
			} else if (line > 0) line = options.resolveRenderableLine == null ? line - 1 : options.resolveRenderableLine(line - 1, "up") ?? line;
		} else if (shortcut === "down") {
			const moved = moveBySoftLine(textDocument, line, character, 1, options);
			if (moved !== void 0) {
				line = moved.line;
				character = moved.character;
			} else {
				const maxLine = Math.max(lineCount - 1, 0);
				if (line < maxLine) line = options.resolveRenderableLine == null ? line + 1 : Math.min(options.resolveRenderableLine(line + 1, "down") ?? line, maxLine);
			}
		} else if (isCollapsedSelection(selection)) {
			const lineLength = textDocument.getLineLength(line);
			character = Math.min(character, lineLength);
			if (shortcut === "left") {
				if (character > 0) character = stepCharacterByGrapheme(textDocument, line, character, false);
				else if (line > 0) {
					const targetLine = options.resolveRenderableLine == null ? line - 1 : options.resolveRenderableLine(line - 1, "up");
					if (targetLine !== void 0) {
						line = targetLine;
						character = textDocument.getLineLength(line);
					}
				}
			} else if (character < lineLength) character = stepCharacterByGrapheme(textDocument, line, character, true);
			else if (line < lineCount - 1) {
				const targetLine = options.resolveRenderableLine == null ? line + 1 : options.resolveRenderableLine(line + 1, "down");
				if (targetLine !== void 0) {
					line = Math.min(targetLine, lineCount - 1);
					character = 0;
				}
			}
		}
		const pos = {
			line,
			character
		};
		return {
			start: pos,
			end: pos,
			direction: 0
		};
	});
}
function moveBySoftLine(textDocument, line, character, direction, options) {
	if (options.getSoftLineOffsets === void 0) return;
	const current = getSoftLineInfo(textDocument, line, character, options);
	const targetIndex = current.index + direction;
	let targetLine = line;
	let target;
	if (targetIndex >= 0 && targetIndex < current.count) target = getSoftLineInfoAtIndex(textDocument, targetLine, targetIndex, options);
	else {
		const nextLine = line + direction;
		if (nextLine < 0 || nextLine >= textDocument.lineCount) return {
			line,
			character
		};
		const resolvedLine = options.resolveRenderableLine == null ? nextLine : options.resolveRenderableLine(nextLine, direction < 0 ? "up" : "down");
		if (resolvedLine === void 0) return {
			line,
			character
		};
		targetLine = Math.min(resolvedLine, textDocument.lineCount - 1);
		const targetCount = getSoftLineCount(textDocument, targetLine, options);
		target = getSoftLineInfoAtIndex(textDocument, targetLine, direction < 0 ? targetCount - 1 : 0, options);
	}
	const column = Math.max(0, character - current.start);
	const targetCharacter = target.start + column;
	const landedCharacter = target.index === target.count - 1 ? targetCharacter : Math.min(targetCharacter, target.end);
	const targetLineText = textDocument.getLineText(targetLine);
	return {
		line: targetLine,
		character: landedCharacter > targetLineText.length ? landedCharacter : snapCharacterToGraphemeBoundary(targetLineText, landedCharacter)
	};
}
function snapCharacterToGraphemeBoundary(lineText, character) {
	if (character <= 0 || character >= lineText.length) return character;
	const segmenter = getGraphemeSegmenter();
	if (segmenter !== void 0) {
		for (const segment of segmenter.segment(lineText)) {
			if (character <= segment.index) return character;
			const segmentEnd = segment.index + segment.segment.length;
			if (character < segmentEnd) return segmentEnd;
		}
		return character;
	}
	let segmentStart = 0;
	for (const codePoint of lineText) {
		if (character <= segmentStart) return character;
		const segmentEnd = segmentStart + codePoint.length;
		if (character < segmentEnd) return segmentEnd;
		segmentStart = segmentEnd;
	}
	return character;
}
function getSoftLineInfo(textDocument, line, character, options) {
	const lineLength = textDocument.getLineLength(line);
	const offsets = options.getSoftLineOffsets?.(line);
	if (offsets === void 0 || offsets.length < 2) return {
		start: 0,
		end: lineLength,
		index: 0,
		count: 1
	};
	for (let index = 0; index + 1 < offsets.length; index++) {
		const softLine = getSoftLineInfoAtIndex(textDocument, line, index, options);
		if (character >= softLine.start && character <= softLine.end) return softLine;
	}
	return getSoftLineInfoAtIndex(textDocument, line, character < (offsets[0] ?? 0) ? 0 : offsets.length - 2, options);
}
function getSoftLineCount(textDocument, line, options) {
	const offsets = options.getSoftLineOffsets?.(line);
	return offsets === void 0 || offsets.length < 2 ? 1 : offsets.length - 1;
}
function getSoftLineInfoAtIndex(textDocument, line, index, options) {
	const lineLength = textDocument.getLineLength(line);
	const offsets = options.getSoftLineOffsets?.(line);
	if (offsets === void 0 || offsets.length < 2) return {
		start: 0,
		end: lineLength,
		index: 0,
		count: 1
	};
	const count = offsets.length - 1;
	const boundedIndex = Math.max(0, Math.min(index, count - 1));
	const start = Math.max(0, Math.min(lineLength, offsets[boundedIndex] ?? 0));
	return {
		start,
		end: Math.max(start, Math.min(lineLength, offsets[boundedIndex + 1] ?? lineLength)),
		index: boundedIndex,
		count
	};
}
/**
* Same as mapCursorMove, but with shift key pressed.
*/
function mapSelectionShift(textDocument, selections, shortcut, options = {}) {
	return selections.map((selection) => {
		const focusPosition = selection.direction === -1 ? selection.start : selection.end;
		const [movedFocusSelection] = mapCursorMove(textDocument, [{
			start: focusPosition,
			end: focusPosition,
			direction: 0
		}], shortcut, options);
		return createSelectionFrom(selection, movedFocusSelection);
	});
}
/**
* Applies a text change to the given text document
*/
function applyTextChangeToSelections(textDocument, selections, edit, lineAnnotations, tabSize = 2, undoBoundary = false) {
	if (selections[selections.length - 1] === void 0) return { nextSelections: [] };
	const selectionPositions = [];
	for (const selection of selections) selectionPositions.push(selection.start, selection.end);
	const selectionOffsets = selectionPositions.map((position) => textDocument.offsetAt(position));
	const primaryStartOffset = selectionOffsets[(selections.length - 1) * 2];
	const primaryEndOffset = selectionOffsets[(selections.length - 1) * 2 + 1];
	const ordered = [];
	let isAlreadyOrdered = true;
	for (let index = 0; index < selections.length; index++) {
		const entry = {
			index,
			start: selectionOffsets[index * 2],
			end: selectionOffsets[index * 2 + 1]
		};
		const previous = ordered[ordered.length - 1];
		if (previous !== void 0 && (entry.start < previous.start || entry.start === previous.start && entry.end < previous.end)) isAlreadyOrdered = false;
		ordered.push(entry);
	}
	if (!isAlreadyOrdered) ordered.sort((a, b) => {
		const startOrder = a.start - b.start;
		if (startOrder !== 0) return startOrder;
		const endOrder = a.end - b.end;
		if (endOrder !== 0) return endOrder;
		return a.index - b.index;
	});
	const adjustedChange = normalizeLeadingIndentForChange(textDocument, edit, tabSize);
	const edits = [];
	const nextSelectionOffsets = Array.from({ length: selections.length });
	let offsetDelta = 0;
	let mergedGroup;
	const finalizeMergedGroup = () => {
		if (mergedGroup === void 0) return;
		const perGroupChange = normalizeLeadingIndentForChange(textDocument, {
			start: mergedGroup.start,
			end: mergedGroup.end,
			text: adjustedChange.text
		}, tabSize);
		const newText = expandSingleNewlineInsert(textDocument, perGroupChange.text, perGroupChange.start);
		edits.push({
			start: perGroupChange.start,
			end: perGroupChange.end,
			text: newText
		});
		const nextOffsets = [mergedGroup.start + offsetDelta + newText.length, mergedGroup.start + offsetDelta + newText.length];
		for (const index of mergedGroup.indices) nextSelectionOffsets[index] = nextOffsets;
		offsetDelta += newText.length - (perGroupChange.end - perGroupChange.start);
		mergedGroup = void 0;
	};
	for (const entry of ordered) {
		const startOffset = Math.max(0, entry.start + (adjustedChange.start - primaryStartOffset));
		const endOffset = Math.max(startOffset, entry.end + (adjustedChange.end - primaryEndOffset));
		if (mergedGroup !== void 0 && startOffset < mergedGroup.end) {
			mergedGroup.end = Math.max(mergedGroup.end, endOffset);
			mergedGroup.indices.push(entry.index);
			continue;
		}
		finalizeMergedGroup();
		mergedGroup = {
			start: startOffset,
			end: endOffset,
			indices: [entry.index]
		};
	}
	finalizeMergedGroup();
	const change = textDocument.applyResolvedEdits(edits, true, selections, void 0, undoBoundary);
	const nextSelections = createSelectionsFromOffsetPairs(textDocument, nextSelectionOffsets.map((offsets) => {
		if (offsets === void 0) throw new Error("Missing next selection offsets");
		return offsets;
	}));
	textDocument.setLastUndoSelectionsAfter(nextSelections);
	if (change !== void 0 && lineAnnotations !== void 0) {
		const nextLineAnnotations = applyDocumentChangeToLineAnnotations(change, lineAnnotations);
		if (nextLineAnnotations !== void 0) textDocument.setLastUndoLineAnnotations(lineAnnotations, nextLineAnnotations);
	}
	return {
		nextSelections,
		change
	};
}
/**
* Returns the next anchor/focus offsets after replacing a selection range.
* When the inserted text still contains the original selection (auto-surround),
* the inner range is reselected to match VS Code/CodeMirror behavior.
*/
function getAutoSurroundPreservedOffset(originalText, newText) {
	if (newText.length !== originalText.length + 2) return;
	const closeChar = AUTO_SURROUND_CLOSE_CHARS.get(newText[0]);
	if (closeChar === void 0 || newText[newText.length - 1] !== closeChar || newText.slice(1, -1) !== originalText) return;
	return 1;
}
function getNextSelectionOffsetPairAfterReplace(textDocument, entry, offsetDelta, newText) {
	const insertStart = entry.start + offsetDelta;
	const insertEnd = insertStart + newText.length;
	if (entry.end - entry.start > 0) {
		const originalText = textDocument.getTextSlice(entry.start, entry.end);
		const preservedOffset = getAutoSurroundPreservedOffset(originalText, newText) ?? newText.indexOf(originalText);
		if (preservedOffset !== -1 && preservedOffset + originalText.length <= newText.length) {
			const rangeStart = insertStart + preservedOffset;
			return [rangeStart, rangeStart + originalText.length];
		}
	}
	return [insertEnd, insertEnd];
}
/**
* Applies text replacements to multiple selections. Texts pair by selection
* index unless they are explicitly marked as document ordered.
*/
function applyTextReplaceToSelections(textDocument, selections, texts, lineAnnotations, undoBoundary = false, textOrder = "selection") {
	if (selections.length !== texts.length) throw new Error("Selection text replacements must match the selection count");
	const selectionPositions = [];
	for (const selection of selections) selectionPositions.push(selection.start, selection.end);
	const selectionOffsets = selectionPositions.map((position) => textDocument.offsetAt(position));
	const ordered = [];
	let isAlreadyOrdered = true;
	for (let index = 0; index < selections.length; index++) {
		const entry = {
			index,
			start: selectionOffsets[index * 2],
			end: selectionOffsets[index * 2 + 1]
		};
		const previous = ordered[ordered.length - 1];
		if (previous !== void 0 && (entry.start < previous.start || entry.start === previous.start && entry.end < previous.end)) isAlreadyOrdered = false;
		ordered.push(entry);
	}
	if (!isAlreadyOrdered) ordered.sort((a, b) => {
		const startOrder = a.start - b.start;
		if (startOrder !== 0) return startOrder;
		const endOrder = a.end - b.end;
		if (endOrder !== 0) return endOrder;
		return a.index - b.index;
	});
	const allDeletes = texts.every((text) => text === "");
	let edits;
	const nextSelectionOffsetPairs = Array.from({ length: selections.length });
	if (allDeletes) {
		edits = [];
		let hasEffect = false;
		for (const entry of ordered) {
			nextSelectionOffsetPairs[entry.index] = [entry.end, entry.end];
			if (entry.start >= entry.end) continue;
			hasEffect = true;
			const last = edits[edits.length - 1];
			if (last !== void 0 && entry.start < last.end) edits[edits.length - 1] = {
				start: last.start,
				end: Math.max(last.end, entry.end),
				text: ""
			};
			else edits.push({
				start: entry.start,
				end: entry.end,
				text: ""
			});
		}
		if (!hasEffect) return { nextSelections: selections };
		for (const entry of ordered) {
			const caret = entry.end;
			let delta = 0;
			let next = caret;
			for (const edit of edits) {
				if (caret <= edit.start) break;
				if (caret >= edit.end) {
					delta -= edit.end - edit.start;
					continue;
				}
				next = edit.start + delta;
				break;
			}
			if (next === caret) next += delta;
			nextSelectionOffsetPairs[entry.index] = [next, next];
		}
	} else {
		edits = [];
		let offsetDelta = 0;
		let previousEditEnd = -1;
		for (let index = 0; index < ordered.length; index++) {
			const entry = ordered[index];
			if (entry.start < previousEditEnd) throw new Error("Overlapping multi-selection edits are not supported");
			previousEditEnd = entry.end;
			const newText = expandSingleNewlineInsert(textDocument, texts[textOrder === "document" ? index : entry.index], entry.start);
			edits.push({
				start: entry.start,
				end: entry.end,
				text: newText
			});
			nextSelectionOffsetPairs[entry.index] = getNextSelectionOffsetPairAfterReplace(textDocument, entry, offsetDelta, newText);
			offsetDelta += newText.length - (entry.end - entry.start);
		}
	}
	const change = textDocument.applyResolvedEdits(edits, true, selections, void 0, undoBoundary);
	const nextSelections = createSelectionsFromOffsetPairs(textDocument, nextSelectionOffsetPairs.map((offsets) => {
		if (offsets === void 0) throw new Error("Missing next selection offsets");
		return offsets;
	}));
	textDocument.setLastUndoSelectionsAfter(nextSelections);
	if (change !== void 0 && lineAnnotations !== void 0) {
		const nextLineAnnotations = applyDocumentChangeToLineAnnotations(change, lineAnnotations);
		if (nextLineAnnotations !== void 0) textDocument.setLastUndoLineAnnotations(lineAnnotations, nextLineAnnotations);
	}
	return {
		nextSelections,
		change
	};
}
function shouldAutoSurroundChar(autoSurround, char) {
	if (autoSurround === "never") return false;
	if (autoSurround === "brackets") return AUTO_SURROUND_BRACKET_CHARS.has(char);
	if (autoSurround === "quotes") return AUTO_SURROUND_QUOTE_CHARS.has(char);
	return true;
}
/**
* Returns per-selection replacement text when typing a surround character over
* non-collapsed selections, matching VS Code auto-surround behavior.
*/
function getAutoSurroundReplacementTexts(textDocument, selections, char, autoSurround) {
	if (char.length !== 1 || selections.length === 0) return;
	const closeChar = AUTO_SURROUND_CLOSE_CHARS.get(char);
	if (closeChar === void 0 || !shouldAutoSurroundChar(autoSurround, char)) return;
	const replacements = [];
	for (const selection of selections) {
		if (isCollapsedSelection(selection)) return;
		replacements.push(char + textDocument.getText(selection) + closeChar);
	}
	return replacements;
}
/**
* Swaps the two characters adjacent to a collapsed selection, matching browser
* insertTranspose (Ctrl+T) behavior.
*/
function applyTransposeToSelections(textDocument, selections, lineAnnotations) {
	const edits = [];
	const nextOffsetPairs = [];
	for (const selection of selections) {
		const [anchor, focus] = getSelectionAnchorAndFocusOffsets(textDocument, selection);
		if (!isCollapsedSelection(selection)) {
			nextOffsetPairs.push([anchor, focus]);
			continue;
		}
		const { line, character } = selection.start;
		const offset = anchor;
		const lineText = textDocument.getLineText(line);
		const lineLength = lineText.length;
		const lineStart = offset - character;
		const graphemeStarts = getLineGraphemeStarts(lineText);
		let edit;
		if (character > 0 && character < lineLength) {
			const before = findClusterBreak(lineText, character, false, graphemeStarts);
			const after = findClusterBreak(lineText, character, true, graphemeStarts);
			edit = {
				start: lineStart + before,
				end: lineStart + after,
				text: lineText.slice(character, after) + lineText.slice(before, character)
			};
			nextOffsetPairs.push([lineStart + after, lineStart + after]);
		} else if (character === lineLength && graphemeStarts.length >= 2) {
			const lastStart = graphemeStarts[graphemeStarts.length - 1];
			const secondLastStart = graphemeStarts[graphemeStarts.length - 2];
			edit = {
				start: lineStart + secondLastStart,
				end: offset,
				text: lineText.slice(lastStart, lineLength) + lineText.slice(secondLastStart, lastStart)
			};
			nextOffsetPairs.push([offset, offset]);
		} else if (character === 0 && line > 0 && lineLength > 0) {
			const prevLine = line - 1;
			const prevLineText = textDocument.getLineText(prevLine);
			const prevLength = prevLineText.length;
			const prevEnd = textDocument.offsetAt({
				line: prevLine,
				character: prevLength
			});
			const prevGraphemeStart = prevLength > 0 ? findClusterBreak(prevLineText, prevLength, false, getLineGraphemeStarts(prevLineText)) : prevLength;
			const firstEnd = findClusterBreak(lineText, 0, true, graphemeStarts);
			const prevStart = prevEnd - (prevLength - prevGraphemeStart);
			const newText = lineText.slice(0, firstEnd) + textDocument.getTextSlice(prevEnd, offset) + prevLineText.slice(prevGraphemeStart, prevLength);
			edit = {
				start: prevStart,
				end: offset + firstEnd,
				text: newText
			};
			const caret = prevStart + newText.length;
			nextOffsetPairs.push([caret, caret]);
		} else {
			nextOffsetPairs.push([anchor, focus]);
			continue;
		}
		edits.push(edit);
	}
	if (edits.length === 0) return { nextSelections: selections };
	edits.sort((a, b) => a.start - b.start);
	for (let index = 1; index < edits.length; index++) if (edits[index].start < edits[index - 1].end) throw new Error("Overlapping multi-selection edits are not supported");
	const change = textDocument.applyResolvedEdits(edits, true, selections);
	const nextSelections = createSelectionsFromOffsetPairs(textDocument, nextOffsetPairs);
	textDocument.setLastUndoSelectionsAfter(nextSelections);
	if (change !== void 0 && lineAnnotations !== void 0) {
		const nextLineAnnotations = applyDocumentChangeToLineAnnotations(change, lineAnnotations);
		if (nextLineAnnotations !== void 0) textDocument.setLastUndoLineAnnotations(lineAnnotations, nextLineAnnotations);
	}
	return {
		nextSelections,
		change
	};
}
/**
* Deletes from each selection to the end of its line, including the line break
* when the caret is already at the end of a non-final line. Non-collapsed
* selections delete their selected text instead.
*/
function applyDeleteHardLineForwardToSelections(textDocument, selections, lineAnnotations) {
	const deleteSelections = selections.map((selection) => {
		const range = resolveDeleteHardLineForwardRange(textDocument, selection);
		return {
			start: range.start,
			end: range.end,
			direction: 0
		};
	});
	return applyTextReplaceToSelections(textDocument, deleteSelections, deleteSelections.map(() => ""), lineAnnotations);
}
/**
* Deletes from each selection back to the start of its soft (visual) line.
* Non-collapsed selections delete their selected text instead.
*/
function applyDeleteSoftLineBackwardToSelections(textDocument, selections, getSoftLineStart, lineAnnotations) {
	const deleteSelections = selections.map((selection) => {
		if (!isCollapsedSelection(selection)) return {
			start: selection.start,
			end: selection.end,
			direction: 0
		};
		const caret = getCaretPosition(selection);
		const { line, character } = caret;
		const softLineStart = getSoftLineStart?.(line, character) ?? 0;
		if (character > softLineStart) return {
			start: {
				line,
				character: softLineStart
			},
			end: {
				line,
				character
			},
			direction: 0
		};
		if (line === 0) return {
			start: caret,
			end: caret,
			direction: 0
		};
		const prevLineLength = textDocument.getLineLength(line - 1);
		return {
			start: {
				line: line - 1,
				character: prevLineLength
			},
			end: {
				line,
				character: 0
			},
			direction: 0
		};
	});
	return applyTextReplaceToSelections(textDocument, deleteSelections, deleteSelections.map(() => ""), lineAnnotations);
}
/**
* Deletes the word or separator group immediately before each selection.
* Non-collapsed selections delete their selected text instead.
*/
function applyDeleteWordBackwardToSelections(textDocument, selections, lineAnnotations) {
	const deleteSelections = selections.map((selection) => {
		const [start, end] = resolveDeleteWordBackwardRange(textDocument, selection);
		return {
			start,
			end,
			direction: 0
		};
	});
	return applyTextReplaceToSelections(textDocument, deleteSelections, deleteSelections.map(() => ""), lineAnnotations);
}
/**
* Resolves the document range deleted by Backspace or Delete at a collapsed
* caret. Non-collapsed selections delete their selected text instead.
*/
function resolveDeleteCharacterRange(textDocument, selection, forward) {
	if (!isCollapsedSelection(selection)) return [selection.start, selection.end];
	const caret = getCaretPosition(selection);
	let { line, character } = caret;
	const lineLength = textDocument.getLineLength(line);
	const lineCount = textDocument.lineCount;
	character = Math.min(character, lineLength);
	if (forward) {
		if (character < lineLength) return [{
			line,
			character
		}, {
			line,
			character: stepCharacterByGrapheme(textDocument, line, character, true)
		}];
		if (line < lineCount - 1) return [{
			line,
			character: lineLength
		}, {
			line: line + 1,
			character: 0
		}];
		return [caret, caret];
	}
	if (character > 0) return [{
		line,
		character: stepCharacterByGrapheme(textDocument, line, character, false)
	}, {
		line,
		character
	}];
	if (line > 0) {
		const prevLineLength = textDocument.getLineLength(line - 1);
		return [{
			line: line - 1,
			character: prevLineLength
		}, {
			line,
			character: 0
		}];
	}
	return [caret, caret];
}
/**
* Deletes one grapheme (or selected text) at each selection.
*/
function applyDeleteCharacterToSelections(textDocument, selections, forward, lineAnnotations, tabSize = 2) {
	const deleteSelections = selections.map((selection) => {
		let [start, end] = resolveDeleteCharacterRange(textDocument, selection, forward);
		if (!forward && isCollapsedSelection(selection)) {
			const normalized = normalizeLeadingIndentForChange(textDocument, {
				start: textDocument.offsetAt(start),
				end: textDocument.offsetAt(end),
				text: ""
			}, tabSize);
			start = textDocument.positionAt(normalized.start);
			end = textDocument.positionAt(normalized.end);
		}
		return {
			start,
			end,
			direction: 0
		};
	});
	return applyTextReplaceToSelections(textDocument, deleteSelections, deleteSelections.map(() => ""), lineAnnotations);
}
/**
* Checks if a selection is collapsed.
*/
function isCollapsedSelection(selection) {
	return selection.start.line === selection.end.line && selection.start.character === selection.end.character;
}
/**
* Returns the caret (focus) position for a selection.
*/
function getCaretPosition(selection) {
	const { start, end, direction } = selection;
	return direction === -1 ? start : end;
}
/**
* Checks if a line is editable.
*/
function isLineEditable(lineType) {
	return lineType === "context" || lineType === "context-expanded" || lineType === "change-addition";
}
/**
* Checks whether selections `a` and `b` intersect.
*/
function selectionIntersects(a, b) {
	const aCollapsed = isCollapsedSelection(a);
	const bCollapsed = isCollapsedSelection(b);
	if (aCollapsed && bCollapsed) return comparePosition(a.start, b.start) === 0;
	if (aCollapsed) return comparePosition(b.start, a.start) <= 0 && comparePosition(a.start, b.end) <= 0;
	if (bCollapsed) return comparePosition(a.start, b.start) <= 0 && comparePosition(b.start, a.end) <= 0;
	return comparePosition(a.start, b.end) < 0 && comparePosition(b.start, a.end) < 0;
}
/**
* Compares two positions.
*/
function comparePosition(a, b) {
	if (a.line !== b.line) return a.line - b.line;
	return a.character - b.character;
}
/**
* Creates a selection from anchor and focus offsets.
*/
function createSelectionFromAnchorAndFocusOffsets(textDocument, anchorOffset, focusOffset) {
	const direction = anchorOffset === focusOffset ? 0 : anchorOffset < focusOffset ? 1 : -1;
	const start = Math.min(anchorOffset, focusOffset);
	const end = Math.max(anchorOffset, focusOffset);
	return {
		start: textDocument.positionAt(start),
		end: textDocument.positionAt(end),
		direction
	};
}
/**
* Maps a single offset from the pre-edit document into the post-edit document.
* `edits` are resolved edits in pre-edit offsets, sorted ascending and
* non-overlapping. An offset at or after an edit's start shifts to the end of
* that edit's replacement (right gravity), so text inserted at the caret pushes
* the caret past it; an offset strictly before an edit is only shifted by the
* net length change of the edits that precede it.
*/
function remapOffsetThroughEdits(offset, edits) {
	let delta = 0;
	for (const edit of edits) {
		if (offset < edit.start) break;
		if (offset >= edit.end) delta += edit.text.length - (edit.end - edit.start);
		else return edit.start + delta + edit.text.length;
	}
	return offset + delta;
}
/**
* Re-anchors selections after a batch of text edits has been applied, so the
* caret keeps pointing at the same logical location in the changed buffer.
*
* `selectionOffsets` (one `[start, end]` pair per selection) and `edits` are
* measured in the PRE-edit document; the returned selections are built from
* `textDocument`, which must already reflect the applied edits. Selection
* direction is preserved by remapping each edge and re-deriving anchor/focus.
*/
function remapSelectionsAfterEdits(textDocument, selections, selectionOffsets, edits) {
	return selections.map((selection, index) => {
		const [startOffset, endOffset] = selectionOffsets[index];
		const nextStart = remapOffsetThroughEdits(startOffset, edits);
		const nextEnd = remapOffsetThroughEdits(endOffset, edits);
		return createSelectionFromAnchorAndFocusOffsets(textDocument, selection.direction === -1 ? nextEnd : nextStart, selection.direction === -1 ? nextStart : nextEnd);
	});
}
/**
* Creates a selection from a anchor and focus selection.
*/
function createSelectionFrom(anchorSelection, focusSelection) {
	const anchor = anchorSelection.direction === -1 ? anchorSelection.end : anchorSelection.start;
	const currentStartOrder = comparePosition(anchor, focusSelection.start);
	const currentEndOrder = comparePosition(anchor, focusSelection.end);
	let focus = focusSelection.end;
	if (currentStartOrder <= 0) focus = focusSelection.end;
	else if (currentEndOrder >= 0) focus = focusSelection.start;
	else focus = currentStartOrder === 0 ? focusSelection.end : focusSelection.start;
	const anchorVsFocus = comparePosition(anchor, focus);
	return {
		start: anchorVsFocus <= 0 ? anchor : focus,
		end: anchorVsFocus <= 0 ? focus : anchor,
		direction: anchorVsFocus === 0 ? 0 : anchorVsFocus < 0 ? 1 : -1
	};
}
/**
* Extends or shrinks the selection `original` using the endpoints of `target`, \
* matching contenteditable shift + click extend behavior.
*/
function extendSelection(original, target) {
	const leftExtended = comparePosition(target.start, original.start) < 0;
	const rightExtended = comparePosition(target.end, original.end) > 0;
	if (leftExtended && !rightExtended) return {
		start: target.start,
		end: original.end,
		direction: -1
	};
	if (rightExtended && !leftExtended) return {
		start: original.start,
		end: target.end,
		direction: 1
	};
	if (original.direction === -1) return {
		start: target.start,
		end: original.end,
		direction: comparePosition(target.start, original.end) === 0 ? 0 : -1
	};
	return {
		start: original.start,
		end: target.end,
		direction: comparePosition(original.start, target.end) === 0 ? 0 : 1
	};
}
/**
* Extends multiple selections.
*/
function extendSelections(selections, target) {
	return mergeOverlappingSelections(selections.map((selection) => {
		return extendSelection(selection, target);
	}));
}
/**
* Merges overlapping selections.
*/
function mergeOverlappingSelections(selections) {
	if (selections.length <= 1) return selections;
	const ordered = selections.map((selection, index) => ({
		index,
		selection
	})).sort((a, b) => {
		const startOrder = comparePosition(a.selection.start, b.selection.start);
		if (startOrder !== 0) return startOrder;
		const endOrder = comparePosition(a.selection.end, b.selection.end);
		return endOrder !== 0 ? endOrder : a.index - b.index;
	});
	const merged = [];
	let current = ordered[0];
	for (const entry of ordered.slice(1)) {
		if (selectionIntersects(current.selection, entry.selection)) {
			const latest = entry.index > current.index ? entry : current;
			const start = comparePosition(entry.selection.start, current.selection.start) < 0 ? entry.selection.start : current.selection.start;
			const end = comparePosition(entry.selection.end, current.selection.end) > 0 ? entry.selection.end : current.selection.end;
			let direction = latest.selection.direction;
			if (direction === 0 && comparePosition(start, end) !== 0) direction = comparePosition(latest.selection.start, start) === 0 ? -1 : 1;
			current = {
				index: latest.index,
				selection: {
					direction,
					end,
					start
				}
			};
			continue;
		}
		merged.push(current);
		current = entry;
	}
	merged.push(current);
	return merged.sort((a, b) => a.index - b.index).map(({ selection }) => selection);
}
/**
* Converts selections into merged line blocks for line-based commands.
*/
function getSelectedLineBlocks(selections) {
	const blocks = selections.map((selection) => {
		let endLine = selection.end.line;
		if (selection.end.character === 0 && comparePosition(selection.start, selection.end) !== 0) endLine--;
		return {
			startLine: selection.start.line,
			endLine: Math.max(selection.start.line, endLine)
		};
	}).sort((a, b) => {
		const startOrder = a.startLine - b.startLine;
		return startOrder !== 0 ? startOrder : a.endLine - b.endLine;
	});
	const merged = [];
	for (const block of blocks) {
		const previous = merged.at(-1);
		if (previous !== void 0 && block.startLine <= previous.endLine + 1) previous.endLine = Math.max(previous.endLine, block.endLine);
		else merged.push({ ...block });
	}
	return merged;
}
/**
* Moves a selection's line positions after its lines are shifted, clamping to
* the target document bounds.
*/
function shiftSelectionLines(selection, direction, lineCount, getLineLength) {
	const shiftPosition = (position) => {
		const line = position.line + direction;
		if (line >= lineCount) {
			const lastLine = Math.max(0, lineCount - 1);
			return {
				line: lastLine,
				character: getLineLength(lastLine)
			};
		}
		if (line < 0) return {
			line: 0,
			character: 0
		};
		return {
			line,
			character: position.character
		};
	};
	return {
		start: shiftPosition(selection.start),
		end: shiftPosition(selection.end),
		direction: selection.direction
	};
}
/**
* Finds the next matching word and updates the selections.
*/
function findNextMatch(textDocument, selections) {
	if (selections.length === 0) return;
	const normalizedSelections = selections.map((selection) => isCollapsedSelection(selection) ? expandCollapsedSelectionToWord(textDocument, selection) : selection);
	const texts = normalizedSelections.map((s) => textDocument.getText(s));
	const needle = texts[0];
	if (needle.length === 0 || texts.some((t) => t !== needle)) return;
	const occupied = normalizedSelections.map((s) => [textDocument.offsetAt(s.start), textDocument.offsetAt(s.end)]);
	const nextOffset = textDocument.findNextNonOverlappingSubstring(needle, occupied);
	if (nextOffset === void 0) return normalizedSelections.some((selection, index) => {
		const original = selections[index];
		return comparePosition(selection.start, original.start) !== 0 || comparePosition(selection.end, original.end) !== 0 || selection.direction !== original.direction;
	}) ? normalizedSelections : void 0;
	const added = createSelectionFromAnchorAndFocusOffsets(textDocument, nextOffset, nextOffset + needle.length);
	return [...normalizedSelections, added];
}
/**
* Get the full selection of the document.
*/
function getDocumentFullSelection(textDocument) {
	const lastLine = textDocument.lineCount - 1;
	return {
		start: {
			line: 0,
			character: 0
		},
		end: {
			line: lastLine,
			character: textDocument.getLineLength(lastLine)
		},
		direction: 1
	};
}
/**
* Get the boundary selection of the document.
*/
function getDocumentBoundarySelection(textDocument, atEnd, trimmedEndNewLine) {
	let line = 0;
	if (atEnd) {
		const lastLine = textDocument.lineCount - 1;
		line = trimmedEndNewLine === true && lastLine > 0 && textDocument.getLineLength(lastLine) === 0 ? lastLine - 1 : lastLine;
	}
	const character = atEnd ? textDocument.getLineLength(line) : 0;
	const start = {
		line,
		character
	};
	return {
		start,
		end: start,
		direction: 1
	};
}
/** Resolves the document offset range one selection contributes to a copy. */
function resolveClipboardRegion(textDocument, selection) {
	if (isCollapsedSelection(selection)) {
		const line = selection.start.line;
		return {
			start: textDocument.offsetAt({
				line,
				character: 0
			}),
			end: line < textDocument.lineCount - 1 ? textDocument.offsetAt({
				line: line + 1,
				character: 0
			}) : textDocument.offsetAt({
				line,
				character: textDocument.getLineLength(line)
			})
		};
	}
	const start = textDocument.offsetAt(selection.start);
	const end = textDocument.offsetAt(selection.end);
	return start <= end ? {
		start,
		end
	} : {
		start: end,
		end: start
	};
}
/**
* Resolves the document offset range each selection contributes to the
* clipboard, ordered by position. A collapsed selection contributes its whole
* logical line including the trailing line break; the final line has no
* trailing break to include. A ranged selection contributes the selected text.
*/
function resolveClipboardRegions(textDocument, selections) {
	return selections.map((selection) => resolveClipboardRegion(textDocument, selection)).sort((a, b) => {
		const startOrder = a.start - b.start;
		return startOrder !== 0 ? startOrder : a.end - b.end;
	});
}
/**
* Gets the text contributed by each selection in document order, preserving
* the pairing needed to paste the values into another set of selections.
*/
function getSelectionClipboardTexts(textDocument, selections) {
	return resolveClipboardRegions(textDocument, selections).map(({ start, end }) => textDocument.getTextSlice(start, end));
}
/**
* Get the clipboard text of the selections for the given text document. Used by
* both copy and cut so the two stay in sync. Overlapping regions (e.g. several
* carets on one line) are merged so the same text is never emitted twice, and a
* line-ending separator is inserted only between regions that aren't already
* contiguous in the document.
*/
function getSelectionText(textDocument, selections) {
	const regions = resolveClipboardRegions(textDocument, selections);
	const eol = textDocument.eol;
	let result = "";
	let prevEnd = -1;
	for (const region of regions) {
		if (region.end <= region.start) continue;
		if (region.start <= prevEnd) {
			if (region.end > prevEnd) {
				result += textDocument.getTextSlice(prevEnd, region.end);
				prevEnd = region.end;
			}
			continue;
		}
		if (result.length > 0 && !endsWithLineBreak(result)) result += eol;
		result += textDocument.getTextSlice(region.start, region.end);
		prevEnd = region.end;
	}
	return result;
}
function resolveSelectionCutEdit(textDocument, selection) {
	if (isCollapsedSelection(selection)) return resolveCollapsedSelectionCutEdit(textDocument, selection);
	const [start, end] = comparePosition(selection.start, selection.end) <= 0 ? [selection.start, selection.end] : [selection.end, selection.start];
	return {
		start: textDocument.offsetAt(start),
		end: textDocument.offsetAt(end),
		text: ""
	};
}
function resolveCollapsedSelectionCutEdit(textDocument, selection) {
	const line = selection.start.line;
	const lineStart = textDocument.offsetAt({
		line,
		character: 0
	});
	const lineEnd = textDocument.offsetAt({
		line,
		character: textDocument.getLineLength(line)
	});
	if (line < textDocument.lineCount - 1) return {
		start: lineStart,
		end: textDocument.offsetAt({
			line: line + 1,
			character: 0
		}),
		text: ""
	};
	if (line > 0) return {
		start: textDocument.offsetAt({
			line: line - 1,
			character: textDocument.getLineLength(line - 1)
		}),
		end: lineEnd,
		text: ""
	};
	return {
		start: lineStart,
		end: lineEnd,
		text: ""
	};
}
function mergeCutEdits(orderedCuts) {
	const edits = [];
	for (const { edit } of orderedCuts) {
		if (edit.start >= edit.end) continue;
		const last = edits.at(-1);
		if (last !== void 0 && edit.start <= last.end) edits[edits.length - 1] = {
			start: last.start,
			end: Math.max(last.end, edit.end),
			text: ""
		};
		else edits.push(edit);
	}
	return edits;
}
function mapCutSelectionOffsets(orderedCuts, edits) {
	const nextOffsets = Array.from({ length: orderedCuts.length });
	let editIndex = 0;
	let offsetDelta = 0;
	for (const cut of orderedCuts) {
		while (editIndex < edits.length && cut.edit.start > edits[editIndex].end) {
			const edit = edits[editIndex];
			offsetDelta -= edit.end - edit.start;
			editIndex++;
		}
		const edit = edits[editIndex];
		if (edit !== void 0 && cut.edit.start >= edit.start && cut.edit.start <= edit.end) nextOffsets[cut.index] = edit.start + offsetDelta;
		else nextOffsets[cut.index] = cut.edit.start + offsetDelta;
	}
	return nextOffsets;
}
function resolveSelectionCut(textDocument, selections) {
	const orderedCuts = [...selections.map((selection, index) => ({
		index,
		edit: resolveSelectionCutEdit(textDocument, selection)
	}))].sort((a, b) => {
		const startOrder = a.edit.start - b.edit.start;
		if (startOrder !== 0) return startOrder;
		const endOrder = a.edit.end - b.edit.end;
		if (endOrder !== 0) return endOrder;
		return a.index - b.index;
	});
	const edits = mergeCutEdits(orderedCuts);
	return {
		text: getSelectionText(textDocument, selections),
		edits,
		nextSelectionOffsets: mapCutSelectionOffsets(orderedCuts, edits)
	};
}
/**
* Get the anchor node and offset for a selection.
*/
function getSelectionAnchor(lineElement, character) {
	const ch = Math.max(0, character);
	const tokens = collectTokens(lineElement);
	let last = null;
	for (const token of tokens) {
		last = token;
		const base = getCharacterIndex(token);
		if (ch <= base + (token.textContent?.length ?? 0)) {
			const anchor = textAt(token, ch < base ? 0 : ch - base);
			if (anchor !== null) return anchor;
		}
	}
	if (last !== null) {
		const anchor = textAt(last, last.textContent?.length ?? 0);
		if (anchor !== null) return anchor;
		return [last, 0];
	}
	let textOffset = 0;
	let lastTextNode = null;
	for (const child of lineElement.childNodes) {
		if (child.nodeType === 1 && child.tagName === "BR") return [child, 0];
		if (child.nodeType !== 3) continue;
		lastTextNode = child;
		const len = getTextOffset(lastTextNode.textContent, lastTextNode.textContent?.length ?? 0);
		if (ch <= textOffset + len) return [lastTextNode, getTextOffset(lastTextNode.textContent, ch - textOffset)];
		textOffset += len;
	}
	if (lastTextNode !== null) return [lastTextNode, getTextOffset(lastTextNode.textContent, lastTextNode.textContent?.length ?? 0)];
	return [lineElement, 0];
}
/**
* Expands a zero-width selection to the word-like segment that contains the caret.
*/
function expandCollapsedSelectionToWord(textDocument, selection) {
	const { line, character } = selection.start;
	const lineText = textDocument.getLineText(line);
	const span = expandCollapsedLineWord(lineText, Math.max(0, Math.min(character, lineText.length)));
	if (span === void 0) return selection;
	return {
		start: {
			line,
			character: span.start
		},
		end: {
			line,
			character: span.end
		},
		direction: 1
	};
}
function expandCollapsedLineWord(lineText, character) {
	const segmenter = createSegmenter({ granularity: "word" });
	if (segmenter !== void 0) {
		for (const seg of segmenter.segment(lineText)) {
			if (seg.isWordLike !== true) continue;
			const lo = seg.index;
			const hi = lo + seg.segment.length;
			if (character >= lo && character <= hi) return {
				start: lo,
				end: hi
			};
		}
		return;
	}
	const wordRe = /[\p{Alphabetic}\p{Number}_]+/gu;
	let match;
	while ((match = wordRe.exec(lineText)) !== null) {
		const lo = match.index;
		const hi = lo + match[0].length;
		if (character >= lo && character <= hi) return {
			start: lo,
			end: hi
		};
	}
}
function resolveDeleteWordBackwardRange(textDocument, selection) {
	if (!isCollapsedSelection(selection)) return [selection.start, selection.end];
	const caret = getCaretPosition(selection);
	const { line, character: head } = caret;
	if (head === 0) {
		if (line === 0) return [caret, caret];
		const prevLineLength = textDocument.getLineLength(line - 1);
		return [{
			line: line - 1,
			character: prevLineLength
		}, {
			line,
			character: 0
		}];
	}
	const lineText = textDocument.getLineText(line);
	const graphemeStarts = getLineGraphemeStarts(lineText);
	let pos = head;
	let match;
	while (pos > 0) {
		const prev = findClusterBreak(lineText, pos, false, graphemeStarts);
		const nextChar = lineText.slice(prev, pos);
		const nextMatch = !/\S/.test(nextChar) ? 0 : /\p{Alphabetic}|\p{Number}|_/u.test(nextChar) ? 1 : 2;
		if (match !== void 0 && nextMatch !== match) break;
		if (nextMatch !== 0 || pos !== head) match = nextMatch;
		pos = prev;
	}
	return [{
		line,
		character: pos
	}, {
		line,
		character: head
	}];
}
function findClusterBreak(text, pos, forward, graphemeStarts) {
	if (forward) {
		for (const start of graphemeStarts) if (start > pos) return start;
		return text.length;
	}
	for (let i = graphemeStarts.length - 1; i >= 0; i--) {
		const start = graphemeStarts[i];
		if (start < pos) return start;
	}
	return 0;
}
function getLineGraphemeStarts(lineText) {
	const graphemeStarts = [0];
	const segmenter = getGraphemeSegmenter();
	if (segmenter !== void 0) {
		for (const segment of segmenter.segment(lineText)) if (segment.index > 0) graphemeStarts.push(segment.index);
		return graphemeStarts;
	}
	let index = 0;
	for (const codePoint of lineText) {
		if (index > 0) graphemeStarts.push(index);
		index += codePoint.length;
	}
	return graphemeStarts;
}
function stepCharacterByGrapheme(textDocument, line, character, forward) {
	const lineLength = textDocument.getLineLength(line);
	if (forward) {
		if (character >= lineLength) return lineLength;
		const lineStart = textDocument.offsetAt({
			line,
			character: 0
		});
		const suffix = textDocument.getTextSlice(lineStart + character, lineStart + lineLength);
		const segmenter = getGraphemeSegmenter();
		if (segmenter !== void 0) {
			for (const segment of segmenter.segment(suffix)) return character + segment.segment.length;
			return lineLength;
		}
		for (const codePoint of suffix) return character + codePoint.length;
		return lineLength;
	}
	if (character <= 0) return 0;
	const lineStart = textDocument.offsetAt({
		line,
		character: 0
	});
	const prefix = textDocument.getTextSlice(lineStart, lineStart + character);
	let prevStart = 0;
	const segmenter = getGraphemeSegmenter();
	if (segmenter !== void 0) {
		for (const segment of segmenter.segment(prefix)) prevStart = segment.index;
		return prevStart;
	}
	let index = 0;
	for (const codePoint of prefix) {
		prevStart = index;
		index += codePoint.length;
	}
	return prevStart;
}
function getSelectionAnchorAndFocusOffsets(textDocument, selection) {
	const isBackward = selection.direction === -1;
	return [textDocument.offsetAt(isBackward ? selection.end : selection.start), textDocument.offsetAt(getCaretPosition(selection))];
}
function resolveDeleteHardLineForwardRange(textDocument, selection) {
	if (!isCollapsedSelection(selection)) return {
		start: selection.start,
		end: selection.end
	};
	const { line, character } = selection.start;
	const lineLength = textDocument.getLineText(line).length;
	if (character < lineLength) return {
		start: {
			line,
			character
		},
		end: {
			line,
			character: lineLength
		}
	};
	if (line < textDocument.lineCount - 1) return {
		start: {
			line,
			character
		},
		end: {
			line: line + 1,
			character: 0
		}
	};
	return {
		start: {
			line,
			character
		},
		end: {
			line,
			character
		}
	};
}
function expandSingleNewlineInsert(textDocument, insertText, insertStartOffset) {
	if (insertText !== "\n" && insertText !== "\r" && insertText !== "\r\n") return insertText;
	const line = textDocument.positionAt(insertStartOffset).line;
	const lineText = textDocument.getLineText(line);
	const indentLen = getLeadingSpaces(lineText);
	if (indentLen === 0) return insertText;
	return insertText + lineText.slice(0, indentLen);
}
function getLeadingSpaces(text) {
	let indent = 0;
	for (; indent < text.length; indent++) {
		const c = text.charCodeAt(indent);
		if (c !== 32 && c !== 9) break;
	}
	return indent;
}
function createSelectionsFromOffsetPairs(textDocument, offsetPairs) {
	const normalizedOffsets = [];
	for (const [anchorOffset, focusOffset] of offsetPairs) normalizedOffsets.push(Math.min(anchorOffset, focusOffset), Math.max(anchorOffset, focusOffset));
	const positions = textDocument.positionsAt(normalizedOffsets);
	return offsetPairs.map(([anchorOffset, focusOffset], index) => {
		const direction = anchorOffset === focusOffset ? 0 : anchorOffset < focusOffset ? 1 : -1;
		return {
			start: positions[index * 2],
			end: positions[index * 2 + 1],
			direction
		};
	});
}
function normalizeLeadingIndentForChange(textDocument, change, tabSize) {
	if (change.text !== "" || change.start !== change.end - 1) return change;
	const caretPosition = textDocument.positionAt(change.end);
	if (caretPosition.character === 0) return change;
	const lineText = textDocument.getLineText(caretPosition.line);
	const leadingText = lineText.slice(0, caretPosition.character);
	if (/[^ \t]/.test(leadingText)) return change;
	if (lineText[caretPosition.character - 1] === "	") return change;
	const softTabStart = Math.max(0, caretPosition.character - tabSize);
	const softTabText = lineText.slice(softTabStart, caretPosition.character);
	if (softTabText.length === tabSize && /^ +$/.test(softTabText)) return {
		...change,
		start: change.end - softTabText.length
	};
	return change;
}
function boundaryToPosition(node, offset) {
	let lineEl = node.nodeType === 1 ? node : node.parentElement;
	while (lineEl !== null && getLineIndex(lineEl) === void 0) lineEl = lineEl.parentElement;
	if (lineEl === null) return null;
	const line = getLineIndex(lineEl);
	if (line === void 0) return null;
	if (node.nodeType === 3) {
		if (node.parentElement === null) return null;
		if (findTokenSpan(node.parentElement) !== null) return {
			line,
			character: getLineChildEnd(node, offset)
		};
		return {
			line,
			character: offsetBefore(lineEl, node) + getTextOffset(node.textContent, offset)
		};
	}
	if (node.nodeType === 1) {
		const el = node;
		if (el.tagName === "DIV") {
			let character = 0;
			for (let i = 0; i < offset; i++) character = getLineChildEnd(el.childNodes[i]);
			return {
				line,
				character
			};
		}
		if (el.tagName === "BR") return {
			line,
			character: 0
		};
		if (el.tagName === "SPAN") {
			if (offset < el.childNodes.length) {
				const next = el.childNodes[offset];
				if (next?.nodeType === 1) {
					const nextBase = getCharacterIndex(next);
					if (nextBase !== void 0) return {
						line,
						character: nextBase
					};
					const token = findTokenSpan(next);
					const tokenBase = token === null ? void 0 : getCharacterIndex(token);
					if (tokenBase !== void 0) return {
						line,
						character: tokenBase
					};
				}
			}
			return {
				line,
				character: offset > 0 ? getLineChildEnd(el.childNodes[offset - 1]) : offsetBefore(lineEl, el)
			};
		}
		return {
			line,
			character: offsetBefore(lineEl, el)
		};
	}
	return null;
}
function collectTokens(line) {
	const tokens = [];
	for (const child of line.childNodes) {
		if (child.nodeType !== 1) continue;
		const el = child;
		if (el.tagName !== "SPAN") continue;
		if (getCharacterIndex(el) !== void 0) {
			tokens.push(el);
			continue;
		}
		for (const nested of el.childNodes) if (nested.nodeType === 1 && getCharacterIndex(nested) !== void 0) tokens.push(nested);
	}
	return tokens;
}
function textAt(token, offset) {
	let remaining = Math.max(0, offset);
	const stack = [{
		container: token,
		index: 0
	}];
	while (stack.length > 0) {
		const frame = stack[stack.length - 1];
		if (frame.index >= frame.container.childNodes.length) {
			stack.pop();
			continue;
		}
		const walkNode = frame.container.childNodes[frame.index];
		frame.index++;
		if (walkNode.nodeType === 3) {
			const len = getTextOffset(walkNode.textContent, walkNode.textContent?.length ?? 0);
			if (remaining <= len) return [walkNode, remaining];
			remaining -= len;
		} else if (walkNode.nodeType === 1) stack.push({
			container: walkNode,
			index: 0
		});
	}
	return null;
}
function textLengthBefore(root, target) {
	let before = 0;
	const stack = [{
		container: root,
		index: 0
	}];
	while (stack.length > 0) {
		const frame = stack[stack.length - 1];
		if (frame.index >= frame.container.childNodes.length) {
			stack.pop();
			continue;
		}
		const walkNode = frame.container.childNodes[frame.index];
		if (walkNode === target) return before;
		frame.index++;
		if (walkNode.nodeType === 3) before += getTextOffset(walkNode.textContent, walkNode.textContent?.length ?? 0);
		else if (walkNode.nodeType === 1) stack.push({
			container: walkNode,
			index: 0
		});
	}
	return before;
}
function isInside(token, node) {
	let current = node;
	while (current !== null) {
		if (current === token) return true;
		current = current.parentElement;
	}
	return false;
}
function offsetBefore(line, node) {
	if (node.parentElement === line) {
		let offset = 0;
		const index = Array.prototype.indexOf.call(line.childNodes, node);
		for (let i = 0; i < index; i++) offset = getLineChildEnd(line.childNodes[i]);
		return offset;
	}
	for (const token of collectTokens(line)) if (isInside(token, node)) return getCharacterIndex(token) + (node.nodeType === 3 ? textLengthBefore(token, node) : 0);
	let offset = 0;
	let target = node.nodeType === 1 ? node : node.parentElement;
	while (target !== null && target.parentElement !== null) {
		if (getLineIndex(target.parentElement) !== void 0) break;
		const parent = target.parentElement;
		const index = Array.prototype.indexOf.call(parent.childNodes, target);
		for (let i = 0; i < index; i++) offset = getLineChildEnd(parent.childNodes[i]);
		target = parent;
	}
	return offset;
}
function findTokenSpan(el) {
	let current = el;
	while (current !== null) {
		if (getLineIndex(current) !== void 0) return null;
		if (getCharacterIndex(current) !== void 0) return current;
		current = current.parentElement;
	}
	return null;
}
function getLineChildEnd(child, textOffsetInChild) {
	if (child === void 0) return 0;
	if (child.nodeType === 3) {
		const parent = child.parentElement;
		if (parent === null) return 0;
		const token = findTokenSpan(parent);
		if (token === null) return 0;
		const base = getCharacterIndex(token);
		if (base === void 0) return 0;
		const length = textOffsetInChild === void 0 ? getTextOffset(child.textContent, child.textContent?.length ?? 0) : getTextOffset(child.textContent, textOffsetInChild);
		return base + textLengthBefore(token, child) + length;
	}
	if (child.nodeType !== 1) return 0;
	const el = child;
	if (el.tagName !== "SPAN" && el.tagName !== "BR") return 0;
	const base = getCharacterIndex(el);
	if (base !== void 0) return base + (el.textContent?.length ?? 0);
	let end = 0;
	for (const token of el.childNodes) end = Math.max(end, getLineChildEnd(token));
	return end;
}
function getLineIndex(el) {
	const { line, lineType } = el.dataset;
	if (line !== void 0 && lineType !== "change-deletion") {
		const lineNumber = parseInt(line, 10);
		if (!Number.isNaN(lineNumber)) return lineNumber - 1;
	}
}
function getCharacterIndex(el) {
	const { char } = el.dataset;
	if (char !== void 0) {
		const charIndex = parseInt(char, 10);
		if (!Number.isNaN(charIndex)) return charIndex;
	}
}
function getTextOffset(text, offset) {
	const value = text ?? "";
	const lineBreakIndex = value.search(/[\r\n]/);
	return Math.min(offset, lineBreakIndex === -1 ? value.length : lineBreakIndex);
}
//#endregion
export { DirectionBackward, DirectionForward, DirectionNone, applyDeleteCharacterToSelections, applyDeleteHardLineForwardToSelections, applyDeleteSoftLineBackwardToSelections, applyDeleteWordBackwardToSelections, applyTextChangeToSelections, applyTextReplaceToSelections, applyTransposeToSelections, comparePosition, convertSelection, createSelectionFrom, createSelectionFromAnchorAndFocusOffsets, expandCollapsedSelectionToWord, extendSelection, extendSelections, findNextMatch, getAutoSurroundReplacementTexts, getCaretPosition, getDocumentBoundarySelection, getDocumentFullSelection, getSelectedLineBlocks, getSelectionAnchor, getSelectionClipboardTexts, getSelectionText, isCollapsedSelection, isLineEditable, mapCursorMove, mapSelectionShift, mergeOverlappingSelections, remapSelectionsAfterEdits, resolveDeleteCharacterRange, resolveIndentEdits, resolveSelectionCut, selectionIntersects, shiftSelectionLines };

//# sourceMappingURL=selection.js.map