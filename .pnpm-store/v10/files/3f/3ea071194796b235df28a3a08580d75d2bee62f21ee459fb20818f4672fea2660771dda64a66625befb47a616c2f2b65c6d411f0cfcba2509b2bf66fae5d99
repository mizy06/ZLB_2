//#region src/utils/realignChangeContent.ts
const MAX_ALIGNMENT_COMPARISONS = 4096;
const MIN_IMPROVEMENT_PER_PAIR = .5;
/**
* Re-split count-mismatched change blocks in every hunk so paired lines are
* chosen by content similarity instead of position, then slide blank-line
* insert/delete blocks to the top of their blank run. Mutates `hunks` in
* place; rendered row counts are unchanged (a split block covers the same
* split/unified rows as the original).
*/
function realignChangeContentBySimilarity(diff) {
	for (const hunk of diff.hunks) {
		for (let index = 0; index < hunk.hunkContent.length; index++) {
			const content = hunk.hunkContent[index];
			if (content.type !== "change") continue;
			const replacement = realignChangeBlock(diff, content);
			if (replacement != null) {
				hunk.hunkContent.splice(index, 1, ...replacement);
				index += replacement.length - 1;
			}
		}
		slideBlankBoundaryBlocksUp(hunk, diff);
	}
}
/**
* Slide pure insert/delete blocks made entirely of blank lines to the top of
* the blank run they sit in. Adding or removing a blank line next to
* existing blanks is ambiguous, and the diff library reports the change at
* the run's bottom — so pressing Enter at the end of a line marks a blank
* *below* the caret as inserted while the caret's own new line renders as
* context. Sliding up anchors the change to the content above it (the caret
* line after an Enter) instead.
*
* The slide is all-or-nothing: it only applies when the block comes to rest
* directly beneath remaining in-hunk content. A slide that would consume the
* hunk's entire leading context was stopped by the hunk's edge — a context
* window cut, not the top of the blank run — and that landing spot is
* arbitrary, so the block keeps the library's bottom-of-run anchor (which
* sits against the content below the run). Non-blank blocks never slide, so
* code that merely ends like its neighbor (an added function before an
* identical `}`) keeps the library's canonical position.
*/
function slideBlankBoundaryBlocksUp(hunk, diff) {
	const { hunkContent } = hunk;
	for (let index = 1; index < hunkContent.length; index++) {
		const block = hunkContent[index];
		const previous = hunkContent[index - 1];
		if (block.type !== "change" || block.additions > 0 && block.deletions > 0 || previous.type !== "context") continue;
		const isInsert = block.additions > 0;
		const lines = isInsert ? diff.additionLines : diff.deletionLines;
		const blockStart = isInsert ? block.additionLineIndex : block.deletionLineIndex;
		const blockLength = isInsert ? block.additions : block.deletions;
		const unit = lines[blockStart] ?? "";
		if (unit.trim() !== "") continue;
		let uniform = true;
		for (let offset = 1; offset < blockLength; offset++) if (lines[blockStart + offset] !== unit) {
			uniform = false;
			break;
		}
		if (!uniform) continue;
		let slide = 0;
		while (slide < previous.lines && diff.additionLines[previous.additionLineIndex + previous.lines - 1 - slide] === unit) slide++;
		if (slide === 0) continue;
		if (index === 1 && slide === previous.lines) continue;
		block.additionLineIndex -= slide;
		block.deletionLineIndex -= slide;
		const blockAdditionEnd = block.additionLineIndex + block.additions;
		const blockDeletionEnd = block.deletionLineIndex + block.deletions;
		const next = hunkContent[index + 1];
		if (next?.type === "context") {
			next.lines += slide;
			next.additionLineIndex = blockAdditionEnd;
			next.deletionLineIndex = blockDeletionEnd;
		} else hunkContent.splice(index + 1, 0, {
			type: "context",
			lines: slide,
			additionLineIndex: blockAdditionEnd,
			deletionLineIndex: blockDeletionEnd
		});
		previous.lines -= slide;
		if (previous.lines === 0) {
			hunkContent.splice(index - 1, 1);
			index--;
		}
	}
}
function realignChangeBlock(diff, content) {
	const { deletions, additions, deletionLineIndex, additionLineIndex } = content;
	const pairCount = Math.min(deletions, additions);
	const surplus = Math.abs(additions - deletions);
	if (pairCount === 0 || surplus === 0 || pairCount * (surplus + 1) > MAX_ALIGNMENT_COMPARISONS) return null;
	const strippedDeletions = [];
	for (let line = 0; line < deletions; line++) strippedDeletions.push(stripWhitespace(diff.deletionLines[deletionLineIndex + line] ?? ""));
	const strippedAdditions = [];
	for (let line = 0; line < additions; line++) strippedAdditions.push(stripWhitespace(diff.additionLines[additionLineIndex + line] ?? ""));
	const additionsAreLonger = additions > deletions;
	let bestOffset = 0;
	let bestScore = -1;
	for (let offset = 0; offset <= surplus; offset++) {
		let score = 0;
		for (let pair = 0; pair < pairCount; pair++) score += lineSimilarity(strippedDeletions[pair + (additionsAreLonger ? 0 : offset)], strippedAdditions[pair + (additionsAreLonger ? offset : 0)]);
		if (offset === 0) bestScore = score + pairCount * MIN_IMPROVEMENT_PER_PAIR;
		else if (score > bestScore) {
			bestScore = score;
			bestOffset = offset;
		}
	}
	if (bestOffset === 0) return null;
	const blocks = [];
	const pushBlock = (blockDeletions, blockAdditions, blockDeletionIndex, blockAdditionIndex) => {
		if (blockDeletions > 0 || blockAdditions > 0) blocks.push({
			type: "change",
			deletions: blockDeletions,
			additions: blockAdditions,
			deletionLineIndex: blockDeletionIndex,
			additionLineIndex: blockAdditionIndex
		});
	};
	if (additionsAreLonger) {
		pushBlock(0, bestOffset, deletionLineIndex, additionLineIndex);
		pushBlock(pairCount, pairCount, deletionLineIndex, additionLineIndex + bestOffset);
		pushBlock(0, additions - pairCount - bestOffset, deletionLineIndex + pairCount, additionLineIndex + bestOffset + pairCount);
	} else {
		pushBlock(bestOffset, 0, deletionLineIndex, additionLineIndex);
		pushBlock(pairCount, pairCount, deletionLineIndex + bestOffset, additionLineIndex);
		pushBlock(deletions - pairCount - bestOffset, 0, deletionLineIndex + bestOffset + pairCount, additionLineIndex + pairCount);
	}
	return blocks;
}
const WHITESPACE = /\s+/g;
function stripWhitespace(line) {
	return line.replace(WHITESPACE, "");
}
function lineSimilarity(a, b) {
	if (a === b) return 1;
	const maxLength = Math.max(a.length, b.length);
	const minLength = Math.min(a.length, b.length);
	if (minLength === 0) return 0;
	let prefix = 0;
	while (prefix < minLength && a[prefix] === b[prefix]) prefix++;
	let suffix = 0;
	while (suffix < minLength - prefix && a[a.length - 1 - suffix] === b[b.length - 1 - suffix]) suffix++;
	return (prefix + suffix) / maxLength;
}
//#endregion
export { realignChangeContentBySimilarity, slideBlankBoundaryBlocksUp };

//# sourceMappingURL=realignChangeContent.js.map