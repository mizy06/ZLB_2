import { computeLineOffsets } from "../utils/computeFileOffsets.js";
//#region src/editor/pieceTable.ts
const MAX_FIND_MATCHES = 1e5;
const LINE_FEED = 10;
const CARRIAGE_RETURN = 13;
const WORD_SEPARATORS = "`~!@#$%^&*()-=+[{]}\\|;:'\",.<>/?";
var Piece = class {
	source;
	offset;
	length;
	lineOffsetStart;
	lineOffsetEnd;
	hasVirtualTrailingCRBreak;
	firstCharCode;
	lastCharCode;
	static Original = 0;
	static Added = 1;
	constructor(source, offset, length, lineOffsetStart, lineOffsetEnd, hasVirtualTrailingCRBreak, firstCharCode, lastCharCode) {
		this.source = source;
		this.offset = offset;
		this.length = length;
		this.lineOffsetStart = lineOffsetStart;
		this.lineOffsetEnd = lineOffsetEnd;
		this.hasVirtualTrailingCRBreak = hasVirtualTrailingCRBreak;
		this.firstCharCode = firstCharCode;
		this.lastCharCode = lastCharCode;
	}
	get lineBreakCount() {
		return this.lineOffsetEnd - this.lineOffsetStart + (this.hasVirtualTrailingCRBreak ? 1 : 0);
	}
};
var TextBuffer = class {
	text;
	lineOffsets;
	constructor(text) {
		this.text = text;
		this.lineOffsets = computeLineOffsets(text);
	}
	append(text) {
		const offset = this.text.length;
		for (let i = 0; i < text.length; i++) {
			const charCode = text.charCodeAt(i);
			if (charCode !== LINE_FEED && charCode !== CARRIAGE_RETURN) continue;
			if (charCode === CARRIAGE_RETURN && text.charCodeAt(i + 1) === LINE_FEED) i++;
			this.lineOffsets.push(offset + i + 1);
		}
		this.text += text;
		return offset;
	}
};
var PieceNode = class {
	piece;
	subtreeLength;
	subtreeLineBreakCount;
	subtreeFirstCharCode;
	subtreeLastCharCode;
	left = null;
	right = null;
	parent = null;
	priority = 0;
	constructor(piece, subtreeLength = piece.length, subtreeLineBreakCount = piece.lineBreakCount, subtreeFirstCharCode = piece.firstCharCode, subtreeLastCharCode = piece.lastCharCode) {
		this.piece = piece;
		this.subtreeLength = subtreeLength;
		this.subtreeLineBreakCount = subtreeLineBreakCount;
		this.subtreeFirstCharCode = subtreeFirstCharCode;
		this.subtreeLastCharCode = subtreeLastCharCode;
	}
	updateSubtreeLength() {
		this.subtreeLength = (this.left?.subtreeLength ?? 0) + this.piece.length + (this.right?.subtreeLength ?? 0);
		this.subtreeLineBreakCount = (this.left?.subtreeLineBreakCount ?? 0) + this.piece.lineBreakCount + (this.right?.subtreeLineBreakCount ?? 0) - (formsCRLF(this.left?.subtreeLastCharCode, this.piece.firstCharCode) ? 1 : 0) - (formsCRLF(this.piece.lastCharCode, this.right?.subtreeFirstCharCode) ? 1 : 0);
		this.subtreeFirstCharCode = this.left?.subtreeFirstCharCode ?? this.piece.firstCharCode;
		this.subtreeLastCharCode = this.right?.subtreeLastCharCode ?? this.piece.lastCharCode;
	}
};
/**
* A piece table is a data structure that allows for efficient insertion and deletion of text.
* It is a tree of pieces, where each piece is a segment of text that is either original or added.
* The tree is a treap (a binary search tree that also keeps each node's random priority in heap
* order, which keeps the tree balanced without an explicit rebalancing pass). Each edit reshapes
* only the nodes along one root-to-leaf path via split and merge in O(log P), instead of
* rebuilding all P pieces.
* Inspired by https://code.visualstudio.com/blogs/2018/03/23/text-buffer-reimplementation
*/
var PieceTable = class {
	#original;
	#add = new TextBuffer("");
	#root = null;
	#length = 0;
	#lineCount = 0;
	#lastVisitedLine = null;
	#lastVisitedLineLength = null;
	#lastPosition = null;
	#priorityState = 2654435769;
	constructor(originalText) {
		this.#original = new TextBuffer(originalText);
		const piece = this.#createPiece(Piece.Original, 0, originalText.length);
		this.#root = piece.length > 0 ? this.#createNode(piece) : null;
		this.#length = this.#root?.subtreeLength ?? 0;
		this.#lineCount = (this.#root?.subtreeLineBreakCount ?? 0) + 1;
	}
	get lineCount() {
		return this.#lineCount;
	}
	getText(range) {
		if (range === void 0) return this.#textFromPieces();
		const start = this.offsetAt(range.start);
		const end = this.offsetAt(range.end);
		return this.getTextSlice(start, end);
	}
	getLineText(line, includeLineBreak = false) {
		if (this.#lastVisitedLine !== null && this.#lastVisitedLine[0] === line && this.#lastVisitedLine[1] === includeLineBreak) return this.#lastVisitedLine[2];
		const offset = this.#getLineOffset(line);
		if (offset === void 0) throw new Error(`Line index out of range: ${line}`);
		const text = this.getTextSlice(offset[0], offset[1], !includeLineBreak);
		this.#lastVisitedLine = [
			line,
			includeLineBreak,
			text
		];
		this.#lastVisitedLineLength = [
			line,
			includeLineBreak,
			text.length
		];
		return text;
	}
	getLineLength(line, includeLineBreak = false) {
		const lastVisitedLineLength = this.#lastVisitedLineLength;
		const lastVisitedLine = this.#lastVisitedLine;
		if (lastVisitedLineLength !== null && lastVisitedLineLength[0] === line && lastVisitedLineLength[1] === includeLineBreak) return lastVisitedLineLength[2];
		if (lastVisitedLine !== null && lastVisitedLine[0] === line && lastVisitedLine[1] === includeLineBreak) {
			const length = lastVisitedLine[2].length;
			this.#lastVisitedLineLength = [
				line,
				includeLineBreak,
				length
			];
			return length;
		}
		const offset = this.#getLineOffset(line);
		if (offset === void 0) throw new Error(`Line index out of range: ${line}`);
		const [start, end] = offset;
		let length = end - start;
		if (!includeLineBreak) while (length > 0 && isEOL(this.charAt(start + length - 1).charCodeAt(0))) length--;
		this.#lastVisitedLineLength = [
			line,
			includeLineBreak,
			length
		];
		return length;
	}
	getTextSlice(start, end, trimEOF = false) {
		if (start >= end) return "";
		const sliceStart = clamp(start, 0, this.#length);
		const sliceEnd = clamp(end, sliceStart, this.#length);
		if (sliceStart >= sliceEnd) return "";
		const location = this.#findPieceAtOffset(sliceStart);
		if (location === void 0) return "";
		const chunks = [];
		let [node, offsetInPiece] = location;
		let remaining = sliceEnd - sliceStart;
		while (node !== null && remaining > 0) {
			const takeLength = Math.min(node.piece.length - offsetInPiece, remaining);
			const buffer = this.#bufferFor(node.piece.source);
			const start = node.piece.offset + offsetInPiece;
			let end = start + takeLength;
			if (trimEOF) while (end > start && isEOL(buffer.text.charCodeAt(end - 1))) end--;
			chunks.push(buffer.text.slice(start, end));
			remaining -= takeLength;
			offsetInPiece = 0;
			node = this.#nextNode(node);
		}
		return chunks.join("");
	}
	charAt(offset) {
		const location = this.#findPieceAtOffset(offset);
		if (location === void 0) return "";
		const [node, offsetInPiece] = location;
		return this.#bufferFor(node.piece.source).text.charAt(node.piece.offset + offsetInPiece);
	}
	includes(needle) {
		if (needle.length === 0) return true;
		const prefixTable = createPrefixTable(needle);
		let matched = 0;
		let found = false;
		this.#forEachPieceSegment((segment) => {
			for (let offset = segment.start; offset < segment.end; offset++) {
				const charCode = segment.text.charCodeAt(offset);
				while (matched > 0 && charCode !== needle.charCodeAt(matched)) matched = prefixTable[matched - 1];
				if (charCode === needle.charCodeAt(matched)) matched++;
				if (matched === needle.length) {
					found = true;
					return false;
				}
			}
			return true;
		});
		return found;
	}
	findNextNonOverlappingSubstring(needle, occupied) {
		if (needle.length === 0 || needle.length > this.#length) return;
		const ranges = normalizeRanges(occupied, this.#length);
		const pivot = ranges.reduce((max, [, end]) => Math.max(max, end), 0);
		const prefixTable = createPrefixTable(needle);
		let matched = 0;
		let documentOffset = 0;
		let wrappedOffset;
		let foundOffset;
		this.#forEachPieceSegment((segment) => {
			for (let offset = segment.start; offset < segment.end; offset++) {
				const charCode = segment.text.charCodeAt(offset);
				while (matched > 0 && charCode !== needle.charCodeAt(matched)) matched = prefixTable[matched - 1];
				if (charCode === needle.charCodeAt(matched)) matched++;
				if (matched === needle.length) {
					const start = documentOffset - needle.length + 1;
					if (!rangeOverlaps(ranges, start, start + needle.length)) {
						if (start >= pivot) {
							foundOffset = start;
							return false;
						}
						wrappedOffset ??= start;
					}
					matched = prefixTable[matched - 1];
				}
				documentOffset++;
			}
			return true;
		});
		return foundOffset ?? wrappedOffset;
	}
	search(searchParams) {
		if (searchParams.text.length === 0 || this.#length === 0) return [];
		if (searchParams.text.includes("\n") || searchParams.text.includes("\r") || searchParams.regex && (searchParams.text.includes("\\n") || searchParams.text.includes("\\r"))) return [];
		let pattern;
		try {
			pattern = compileSearchRegExp(searchParams.text, searchParams.regex, searchParams.caseSensitive);
		} catch {
			return [];
		}
		return this.#collectSearchMatchesLineByLine(pattern, searchParams.wholeWord, MAX_FIND_MATCHES);
	}
	#collectSearchMatchesLineByLine(pattern, wholeWord, limit) {
		const out = [];
		const documentText = this.#textFromPieces();
		const docLength = documentText.length;
		const lineOffsets = computeLineOffsets(documentText);
		for (let line = 0; line < lineOffsets.length; line++) {
			const lineStart = lineOffsets[line];
			let lineEnd = lineOffsets[line + 1] ?? docLength;
			while (lineEnd > lineStart && isEOL(documentText.charCodeAt(lineEnd - 1))) lineEnd--;
			const lineText = documentText.slice(lineStart, lineEnd);
			pattern.lastIndex = 0;
			let match;
			while ((match = pattern.exec(lineText)) !== null) {
				const rel = match.index;
				const fragment = match[0];
				if (fragment.length === 0) {
					pattern.lastIndex = advancePastEmptyMatch(lineText, rel);
					continue;
				}
				const docStart = lineStart + rel;
				if (!wholeWord || isWholeWordAtDocOffsets(documentText, docStart, fragment.length)) {
					out.push([docStart, docStart + fragment.length]);
					if (out.length >= limit) return out;
				}
				if (rel === pattern.lastIndex) pattern.lastIndex = advancePastEmptyMatch(lineText, rel);
			}
		}
		return out;
	}
	insert(text, offset) {
		if (text.length === 0) return;
		const start = clamp(offset, 0, this.#length);
		this.#replaceRangeIncremental(start, start, text);
		this.#invalidateCaches();
	}
	delete(offset, length) {
		if (length <= 0 || this.#length === 0) return;
		const start = clamp(offset, 0, this.#length);
		const end = clamp(start + length, start, this.#length);
		if (start === end) return;
		this.#replaceRangeIncremental(start, end, "");
		this.#invalidateCaches();
	}
	applyEdits(edits) {
		if (edits.length === 0) return;
		for (let i = edits.length - 1; i >= 0; i--) {
			const edit = edits[i];
			const start = clamp(edit.start, 0, this.#length);
			const end = clamp(edit.end, start, this.#length);
			this.#replaceRangeIncremental(start, end, edit.text);
		}
		this.#invalidateCaches();
	}
	positionAt(offset) {
		const clampedOffset = clamp(offset, 0, this.#length);
		if (this.#length === 0) return {
			line: 0,
			character: 0
		};
		const line = this.#lineAtOffset(clampedOffset);
		const character = clampedOffset - (line === 0 ? 0 : this.#lineBreakOffset(line - 1));
		this.#lastPosition = [
			line,
			character,
			clampedOffset
		];
		return {
			line,
			character
		};
	}
	positionsAt(offsets) {
		const positions = Array.from({ length: offsets.length });
		if (offsets.length === 0) return positions;
		if (this.#length === 0) return positions.fill({
			line: 0,
			character: 0
		});
		for (let i = 0; i < offsets.length; i++) positions[i] = this.positionAt(offsets[i]);
		return positions;
	}
	offsetAt(position) {
		if (position.line < 0 || this.#length === 0) return 0;
		if (position.line >= this.#lineCount) throw new Error(`Line index out of range: ${position.line}`);
		const lastPosition = this.#lastPosition;
		if (lastPosition !== null && lastPosition[0] === position.line && lastPosition[1] === position.character) return lastPosition[2];
		const offset = this.#getLineOffset(position.line);
		if (offset === void 0) throw new Error(`Line index out of range: ${position.line}`);
		const character = clamp(position.character, 0, offset[1] - offset[0]);
		return offset[0] + character;
	}
	#findPieceAtOffset(offset) {
		if (offset < 0 || offset >= this.#length) return;
		let node = this.#root;
		let remaining = offset;
		while (node !== null) {
			const leftLength = node.left?.subtreeLength ?? 0;
			if (remaining < leftLength) {
				node = node.left;
				continue;
			}
			remaining -= leftLength;
			if (remaining < node.piece.length) return [node, remaining];
			remaining -= node.piece.length;
			node = node.right;
		}
	}
	#nextNode(node) {
		if (node.right !== null) {
			let next = node.right;
			while (next.left !== null) next = next.left;
			return next;
		}
		let current = node;
		while (current.parent !== null && current === current.parent.right) current = current.parent;
		return current.parent;
	}
	#getLineOffset(line) {
		if (line < 0) throw new Error(`Line index out of range: ${line}`);
		if (this.#length === 0) {
			if (line === 0) return [0, 0];
			throw new Error(`Line index out of range: ${line}`);
		}
		if (line >= this.#lineCount) throw new Error(`Line index out of range: ${line}`);
		return [line === 0 ? 0 : this.#lineBreakOffset(line - 1), line < this.#lineCount - 1 ? this.#lineBreakOffset(line) : this.#length];
	}
	#lineAtOffset(offset) {
		let node = this.#root;
		let remaining = clamp(offset, 0, this.#length);
		let line = 0;
		while (node !== null) {
			const leftLength = node.left?.subtreeLength ?? 0;
			if (remaining < leftLength) {
				node = node.left;
				continue;
			}
			line += (node.left?.subtreeLineBreakCount ?? 0) - (formsCRLF(node.left?.subtreeLastCharCode, node.piece.firstCharCode) ? 1 : 0);
			remaining -= leftLength;
			if (remaining <= node.piece.length) {
				const buffer = this.#bufferFor(node.piece.source);
				const lineOffsetEnd = Math.min(upperBound(buffer.lineOffsets, node.piece.offset + remaining), node.piece.lineOffsetEnd);
				line += lineOffsetEnd - node.piece.lineOffsetStart;
				if (remaining === node.piece.length && node.piece.hasVirtualTrailingCRBreak) line++;
				if (remaining === node.piece.length && formsCRLF(node.piece.lastCharCode, this.#nextNode(node)?.piece.firstCharCode)) line--;
				return line;
			}
			line += node.piece.lineBreakCount - (formsCRLF(node.piece.lastCharCode, node.right?.subtreeFirstCharCode) ? 1 : 0);
			remaining -= node.piece.length;
			node = node.right;
		}
		return this.#lineCount - 1;
	}
	#lineBreakOffset(lineBreakIndex) {
		let node = this.#root;
		let remaining = lineBreakIndex;
		let documentOffset = 0;
		let followingCharCode;
		while (node !== null) {
			const leftLineBreakCount = (node.left?.subtreeLineBreakCount ?? 0) - (formsCRLF(node.left?.subtreeLastCharCode, node.piece.firstCharCode) ? 1 : 0);
			if (remaining < leftLineBreakCount) {
				followingCharCode = node.piece.firstCharCode;
				node = node.left;
				continue;
			}
			const leftLength = node.left?.subtreeLength ?? 0;
			documentOffset += leftLength;
			remaining -= leftLineBreakCount;
			const nextCharCode = node.right?.subtreeFirstCharCode ?? followingCharCode;
			const pieceLineBreakCount = node.piece.lineBreakCount - (formsCRLF(node.piece.lastCharCode, nextCharCode) ? 1 : 0);
			if (remaining < pieceLineBreakCount) return documentOffset + this.#pieceLineBreakOffset(node.piece, remaining);
			documentOffset += node.piece.length;
			remaining -= pieceLineBreakCount;
			node = node.right;
		}
		return this.#length;
	}
	#pieceLineBreakOffset(piece, lineBreakIndex) {
		if (lineBreakIndex < piece.lineOffsetEnd - piece.lineOffsetStart) return this.#bufferFor(piece.source).lineOffsets[piece.lineOffsetStart + lineBreakIndex] - piece.offset;
		return piece.length;
	}
	#textFromPieces() {
		const chunks = [];
		this.#forEachPieceSegment((segment) => {
			chunks.push(segment.text.slice(segment.start, segment.end));
		});
		return chunks.join("");
	}
	#forEachPieceSegment(callback) {
		this.#walk(this.#root, (node) => {
			const buffer = this.#bufferFor(node.piece.source);
			return callback({
				text: buffer.text,
				lineOffsets: buffer.lineOffsets,
				lineOffsetStart: node.piece.lineOffsetStart,
				lineOffsetEnd: node.piece.lineOffsetEnd,
				start: node.piece.offset,
				end: node.piece.offset + node.piece.length
			});
		});
	}
	#bufferFor(source) {
		return source === Piece.Original ? this.#original : this.#add;
	}
	#createPiece(source, offset, length) {
		const buffer = this.#bufferFor(source);
		const end = offset + length;
		const lineOffsetStart = upperBound(buffer.lineOffsets, offset);
		const lineOffsetEnd = upperBound(buffer.lineOffsets, end);
		const lastCharCode = buffer.text.charCodeAt(end - 1);
		return new Piece(source, offset, length, lineOffsetStart, lineOffsetEnd, lastCharCode === CARRIAGE_RETURN && buffer.lineOffsets[lineOffsetEnd - 1] !== end, buffer.text.charCodeAt(offset), lastCharCode);
	}
	#replaceRangeIncremental(start, end, text) {
		if (start === end && text.length === 0) return;
		const [left, rest] = this.#split(this.#root, start);
		const right = this.#dropPrefix(rest, end - start);
		let root;
		if (text.length > 0) {
			const insertedPiece = this.#createPiece(Piece.Added, this.#add.append(text), text.length);
			root = this.#mergeNodes(this.#appendCoalescing(left, insertedPiece), right);
		} else {
			const [seamPiece, restRight] = this.#popLeftmost(right);
			root = seamPiece === void 0 ? left : this.#mergeNodes(this.#appendCoalescing(left, seamPiece), restRight);
		}
		if (root !== null) root.parent = null;
		this.#root = root;
		this.#length = root?.subtreeLength ?? 0;
		this.#lineCount = (root?.subtreeLineBreakCount ?? 0) + 1;
	}
	#invalidateCaches() {
		this.#lastVisitedLine = null;
		this.#lastVisitedLineLength = null;
		this.#lastPosition = null;
	}
	#nextPriority() {
		this.#priorityState = Math.imul(this.#priorityState, 1664525) + 1013904223 >>> 0;
		return this.#priorityState;
	}
	#createNode(piece) {
		const node = new PieceNode(piece);
		node.priority = this.#nextPriority();
		return node;
	}
	#setLeft(node, child) {
		node.left = child;
		if (child !== null) child.parent = node;
	}
	#setRight(node, child) {
		node.right = child;
		if (child !== null) child.parent = node;
	}
	#split(node, offset) {
		if (node === null) return [null, null];
		if (offset <= 0) return [null, node];
		if (offset >= node.subtreeLength) return [node, null];
		const leftLength = node.left?.subtreeLength ?? 0;
		if (offset <= leftLength) {
			const [left, right] = this.#split(node.left, offset);
			this.#setLeft(node, right);
			node.updateSubtreeLength();
			return [left, node];
		}
		const pieceLength = node.piece.length;
		if (offset >= leftLength + pieceLength) {
			const [left, right] = this.#split(node.right, offset - leftLength - pieceLength);
			this.#setRight(node, left);
			node.updateSubtreeLength();
			return [node, right];
		}
		const inPiece = offset - leftLength;
		const leftNode = new PieceNode(this.#createPiece(node.piece.source, node.piece.offset, inPiece));
		const rightNode = new PieceNode(this.#createPiece(node.piece.source, node.piece.offset + inPiece, pieceLength - inPiece));
		leftNode.priority = node.priority;
		rightNode.priority = node.priority;
		this.#setLeft(leftNode, node.left);
		this.#setRight(rightNode, node.right);
		leftNode.updateSubtreeLength();
		rightNode.updateSubtreeLength();
		return [leftNode, rightNode];
	}
	#dropPrefix(node, offset) {
		if (node === null || offset >= node.subtreeLength) return null;
		if (offset <= 0) return node;
		const leftLength = node.left?.subtreeLength ?? 0;
		if (offset <= leftLength) {
			this.#setLeft(node, this.#dropPrefix(node.left, offset));
			node.updateSubtreeLength();
			return node;
		}
		const pieceEnd = leftLength + node.piece.length;
		if (offset >= pieceEnd) return this.#dropPrefix(node.right, offset - pieceEnd);
		const inPiece = offset - leftLength;
		const rightNode = new PieceNode(this.#createPiece(node.piece.source, node.piece.offset + inPiece, node.piece.length - inPiece));
		rightNode.priority = node.priority;
		this.#setRight(rightNode, node.right);
		rightNode.updateSubtreeLength();
		return rightNode;
	}
	#mergeNodes(left, right) {
		if (left === null) return right;
		if (right === null) return left;
		if (left.priority >= right.priority) {
			this.#setRight(left, this.#mergeNodes(left.right, right));
			left.updateSubtreeLength();
			return left;
		}
		this.#setLeft(right, this.#mergeNodes(left, right.left));
		right.updateSubtreeLength();
		return right;
	}
	#appendCoalescing(tree, piece) {
		if (tree === null) return this.#createNode(piece);
		let last = tree;
		while (last.right !== null) last = last.right;
		if (canCoalescePieces(last.piece, piece)) {
			last.piece = coalesceTwoPieces(last.piece, piece);
			for (let node = last; node !== null;) {
				node.updateSubtreeLength();
				if (node === tree) break;
				node = node.parent;
			}
			return tree;
		}
		return this.#mergeNodes(tree, this.#createNode(piece));
	}
	#popLeftmost(tree) {
		if (tree === null) return [void 0, null];
		if (tree.left === null) return [tree.piece, tree.right];
		const [piece, newLeft] = this.#popLeftmost(tree.left);
		this.#setLeft(tree, newLeft);
		tree.updateSubtreeLength();
		return [piece, tree];
	}
	#walk(node, visit) {
		if (node === null) return true;
		if (!this.#walk(node.left, visit)) return false;
		if (visit(node) === false) return false;
		return this.#walk(node.right, visit);
	}
};
function isEOL(charCode) {
	return charCode === 10 || charCode === 13;
}
function clamp(value, min, max) {
	return Math.min(Math.max(value, min), max);
}
function createPrefixTable(text) {
	const table = Array.from({ length: text.length }).fill(0);
	let matched = 0;
	for (let i = 1; i < text.length; i++) {
		const charCode = text.charCodeAt(i);
		while (matched > 0 && charCode !== text.charCodeAt(matched)) matched = table[matched - 1];
		if (charCode === text.charCodeAt(matched)) matched++;
		table[i] = matched;
	}
	return table;
}
function normalizeRanges(ranges, length) {
	const normalized = [];
	for (const [rawStart, rawEnd] of ranges) {
		const start = clamp(rawStart, 0, length);
		const end = clamp(rawEnd, start, length);
		if (start < end) normalized.push([start, end]);
	}
	normalized.sort((a, b) => a[0] - b[0]);
	const merged = [];
	for (const range of normalized) {
		const previous = merged[merged.length - 1];
		if (previous !== void 0 && range[0] <= previous[1]) {
			previous[1] = Math.max(previous[1], range[1]);
			continue;
		}
		merged.push(range);
	}
	return merged;
}
function rangeOverlaps(ranges, start, end) {
	let low = 0;
	let high = ranges.length;
	while (low < high) {
		const mid = low + Math.floor((high - low) / 2);
		if (ranges[mid][1] <= start) low = mid + 1;
		else high = mid;
	}
	const range = ranges[low];
	return range !== void 0 && range[0] < end;
}
function canCoalescePieces(prev, next) {
	return prev.source === next.source && prev.offset + prev.length === next.offset && !formsCRLF(prev.lastCharCode, next.firstCharCode);
}
function coalesceTwoPieces(prev, next) {
	return new Piece(prev.source, prev.offset, prev.length + next.length, prev.lineOffsetStart, next.lineOffsetEnd, next.hasVirtualTrailingCRBreak, prev.firstCharCode, next.lastCharCode);
}
function formsCRLF(leftCharCode, rightCharCode) {
	return leftCharCode === CARRIAGE_RETURN && rightCharCode === LINE_FEED;
}
function upperBound(values, target) {
	let lo = 0;
	let hi = values.length;
	while (lo < hi) {
		const mid = lo + Math.floor((hi - lo) / 2);
		if (values[mid] <= target) lo = mid + 1;
		else hi = mid;
	}
	return lo;
}
function escapeRegExp(text) {
	return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
function isWordSeparatorCharCode(charCode) {
	if (charCode <= 32 || charCode === 127) return true;
	const ch = String.fromCharCode(charCode);
	return WORD_SEPARATORS.includes(ch);
}
function isWholeWordAtDocOffsets(text, docStart, length) {
	const beforeOk = docStart <= 0 || isWordSeparatorCharCode(text.charCodeAt(docStart - 1));
	const afterOk = docStart + length >= text.length || isWordSeparatorCharCode(text.charCodeAt(docStart + length));
	return beforeOk && afterOk;
}
function compileSearchRegExp(source, isRegex, caseSensitive) {
	const body = isRegex ? source : escapeRegExp(source);
	return new RegExp(body, `g${caseSensitive ? "" : "i"}${isRegex ? "m" : ""}`);
}
/** Expands `$&`, `$1`, `$$`, etc. in a regex replace string using a match. */
function expandReplaceString(replacement, match) {
	return replacement.replace(/\$([$&]|\d+)/g, (_token, group) => {
		if (group === "$") return "$";
		if (group === "&") return match[0] ?? "";
		return match[Number(group)] ?? "";
	});
}
/**
* Builds the text to insert for one search match, including regex capture
* substitution when regex mode is enabled.
*/
function buildSearchReplacementText(positionAt, offsetAt, getLineText, searchParams, matchStart, matchEnd) {
	if (!searchParams.regex) return searchParams.replaceText;
	const position = positionAt(matchStart);
	const lineText = getLineText(position.line);
	const relStart = matchStart - offsetAt({
		line: position.line,
		character: 0
	});
	let pattern;
	try {
		pattern = compileSearchRegExp(searchParams.text, true, searchParams.caseSensitive);
	} catch {
		return searchParams.replaceText;
	}
	pattern.lastIndex = relStart;
	const match = pattern.exec(lineText);
	if (match === null || match.index !== relStart || match[0].length !== matchEnd - matchStart) return searchParams.replaceText;
	return expandReplaceString(searchParams.replaceText, match);
}
function advancePastEmptyMatch(text, index) {
	if (index + 1 < text.length) {
		const first = text.charCodeAt(index);
		const second = text.charCodeAt(index + 1);
		if (first >= 55296 && first <= 56319 && second >= 56320 && second <= 57343) return index + 2;
	}
	return index + 1;
}
//#endregion
export { PieceTable, buildSearchReplacementText };

//# sourceMappingURL=pieceTable.js.map