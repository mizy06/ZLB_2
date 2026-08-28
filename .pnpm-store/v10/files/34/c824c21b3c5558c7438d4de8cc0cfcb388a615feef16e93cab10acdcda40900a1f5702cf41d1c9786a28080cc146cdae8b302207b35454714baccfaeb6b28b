//#region src/editor/matchBrackets.ts
const OPEN_BRACKETS = /* @__PURE__ */ new Map([
	["(", ")"],
	["[", "]"],
	["{", "}"]
]);
const CLOSE_BRACKETS = new Map([...OPEN_BRACKETS].map(([open, close]) => [close, open]));
const MAX_BRACKET_SCAN_LINES = 1e3;
const MAX_BRACKET_SCAN_CHARACTERS = 5e4;
function findBracketMatchRanges(textDocument, tokenizer, position) {
	const bracketPosition = findAdjacentBracket(textDocument, tokenizer, textDocument.normalizePosition(position));
	if (bracketPosition === void 0) return;
	const closingBracket = OPEN_BRACKETS.get(bracketPosition.char);
	const openingBracket = CLOSE_BRACKETS.get(bracketPosition.char);
	if (closingBracket !== void 0) return createBracketMatchRanges(bracketPosition, findClosingBracket(textDocument, tokenizer, bracketPosition, closingBracket));
	if (openingBracket !== void 0) return createBracketMatchRanges(findOpeningBracket(textDocument, tokenizer, bracketPosition, openingBracket), bracketPosition);
}
function findAdjacentBracket(textDocument, tokenizer, position) {
	const previousPosition = getPreviousCharacterPosition(position);
	if (previousPosition !== void 0) {
		const previousBracket = getBracketAtPosition(textDocument, tokenizer, previousPosition);
		if (previousBracket !== void 0) return previousBracket;
	}
	return getBracketAtPosition(textDocument, tokenizer, position);
}
function getPreviousCharacterPosition(position) {
	if (position.character > 0) return {
		line: position.line,
		character: position.character - 1
	};
}
function getBracketAtPosition(textDocument, tokenizer, position) {
	const char = textDocument.getLineText(position.line)[position.character];
	if (char === void 0 || !OPEN_BRACKETS.has(char) && !CLOSE_BRACKETS.has(char) || isInIgnoredTokenRange(tokenizer, position)) return;
	return {
		...position,
		char
	};
}
function findClosingBracket(textDocument, tokenizer, bracketPosition, closingBracket) {
	let depth = 0;
	let scannedLines = 0;
	let scannedCharacters = 0;
	for (let line = bracketPosition.line; line < textDocument.lineCount; line++) {
		if (scannedLines >= MAX_BRACKET_SCAN_LINES) return;
		scannedLines++;
		const lineText = textDocument.getLineText(line);
		const ignoredRanges = tokenizer.getStringCommentRegexpRangesInLine(line);
		const ignoredRangeCursor = { index: 0 };
		const startCharacter = line === bracketPosition.line ? bracketPosition.character : 0;
		for (let character = startCharacter; character < lineText.length; character++) {
			if (scannedCharacters >= MAX_BRACKET_SCAN_CHARACTERS) return;
			scannedCharacters++;
			if (isCharacterIgnoredForward(ignoredRanges, character, ignoredRangeCursor)) continue;
			const char = lineText[character];
			if (char === bracketPosition.char) depth++;
			else if (char === closingBracket) {
				depth--;
				if (depth === 0) return {
					line,
					character,
					char
				};
			}
		}
	}
}
function findOpeningBracket(textDocument, tokenizer, bracketPosition, openingBracket) {
	let depth = 0;
	let scannedLines = 0;
	let scannedCharacters = 0;
	for (let line = bracketPosition.line; line >= 0; line--) {
		if (scannedLines >= MAX_BRACKET_SCAN_LINES) return;
		scannedLines++;
		const lineText = textDocument.getLineText(line);
		const ignoredRanges = tokenizer.getStringCommentRegexpRangesInLine(line);
		const ignoredRangeCursor = { index: ignoredRanges === null ? -1 : ignoredRanges.length - 1 };
		const startCharacter = line === bracketPosition.line ? bracketPosition.character : lineText.length - 1;
		for (let character = startCharacter; character >= 0; character--) {
			if (scannedCharacters >= MAX_BRACKET_SCAN_CHARACTERS) return;
			scannedCharacters++;
			if (isCharacterIgnoredBackward(ignoredRanges, character, ignoredRangeCursor)) continue;
			const char = lineText[character];
			if (char === bracketPosition.char) depth++;
			else if (char === openingBracket) {
				depth--;
				if (depth === 0) return {
					line,
					character,
					char
				};
			}
		}
	}
}
function isInIgnoredTokenRange(tokenizer, position) {
	return isCharacterInIgnoredRanges(tokenizer.getStringCommentRegexpRangesInLine(position.line), position.character);
}
function isCharacterInIgnoredRanges(ranges, character) {
	if (ranges === null) return false;
	for (const [start, end] of ranges) {
		if (character < start) return false;
		if (character < end) return true;
	}
	return false;
}
function isCharacterIgnoredForward(ranges, character, cursor) {
	if (ranges === null) return false;
	while (cursor.index < ranges.length && character >= ranges[cursor.index][1]) cursor.index++;
	const range = ranges[cursor.index];
	return range !== void 0 && character >= range[0];
}
function isCharacterIgnoredBackward(ranges, character, cursor) {
	if (ranges === null) return false;
	while (cursor.index >= 0 && character < ranges[cursor.index][0]) cursor.index--;
	const range = ranges[cursor.index];
	return range !== void 0 && character < range[1];
}
function createBracketMatchRanges(firstPosition, secondPosition) {
	if (firstPosition === void 0 || secondPosition === void 0) return;
	return [createCharacterRange(firstPosition), createCharacterRange(secondPosition)];
}
function createCharacterRange(position) {
	return {
		start: {
			line: position.line,
			character: position.character
		},
		end: {
			line: position.line,
			character: position.character + 1
		}
	};
}
//#endregion
export { findBracketMatchRanges };

//# sourceMappingURL=matchBrackets.js.map