import { FileDiffMetadata, Hunk } from "../types.js";

//#region src/utils/realignChangeContent.d.ts
/**
 * Re-split count-mismatched change blocks in every hunk so paired lines are
 * chosen by content similarity instead of position, then slide blank-line
 * insert/delete blocks to the top of their blank run. Mutates `hunks` in
 * place; rendered row counts are unchanged (a split block covers the same
 * split/unified rows as the original).
 */
declare function realignChangeContentBySimilarity(diff: Pick<FileDiffMetadata, 'hunks' | 'additionLines' | 'deletionLines'>): void;
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
declare function slideBlankBoundaryBlocksUp(hunk: Hunk, diff: Pick<FileDiffMetadata, 'additionLines' | 'deletionLines'>): void;
//#endregion
export { realignChangeContentBySimilarity, slideBlankBoundaryBlocksUp };
//# sourceMappingURL=realignChangeContent.d.ts.map