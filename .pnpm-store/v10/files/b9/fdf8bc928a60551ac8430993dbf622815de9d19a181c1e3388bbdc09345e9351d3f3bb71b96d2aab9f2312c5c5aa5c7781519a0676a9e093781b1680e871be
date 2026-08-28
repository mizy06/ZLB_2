import { DiffLineAnnotation, EditorSelection, Position, Range, ResolvedTextEdit, SelectionDirection, TextEdit } from "../types.js";
import { TextDocument, TextDocumentChange } from "./textDocument.js";

//#region src/editor/selection.d.ts
declare const DirectionBackward = -1;
declare const DirectionNone = 0;
declare const DirectionForward = 1;
interface CursorMoveOptions {
  getSoftLineOffsets?: (line: number) => ArrayLike<number> | undefined;
  /**
   * Fold-skip resolver for vertical motion crossing document lines: the
   * nearest renderable line at or beyond the target in the move direction,
   * or undefined when everything that way is hidden inside a collapsed
   * region (the caret then stays put). Soft-line moves within one document
   * line never consult it.
   */
  resolveRenderableLine?: ResolveRenderableLine;
}
/**
 * Converts a selection from a web selection to an editor selection.
 */
declare function convertSelection(range: StaticRange, direction?: SelectionDirection): EditorSelection | undefined;
/**
 * Resolves the indent edits for a selection.
 */
declare function resolveIndentEdits(textDocument: TextDocument<unknown>, selection: EditorSelection, tabSize: number, outdent: boolean): [edits: TextEdit[], nextSelection: EditorSelection];
/**
 * The nearest zero-based document line at or beyond `line` in `direction`
 * that has a rendered row, or undefined when everything that way is hidden
 * inside a collapsed region. Vertical caret motion uses it to skip collapsed
 * regions atomically, like code folds.
 */
type ResolveRenderableLine = (line: number, direction: 'up' | 'down') => number | undefined;
/**
 * Maps the cursor move to all selections.
 */
declare function mapCursorMove(textDocument: TextDocument<unknown>, selections: EditorSelection[], shortcut: 'textStart' | 'start' | 'end' | 'up' | 'down' | 'left' | 'right', options?: CursorMoveOptions): EditorSelection[];
/**
 * Same as mapCursorMove, but with shift key pressed.
 */
declare function mapSelectionShift(textDocument: TextDocument<unknown>, selections: EditorSelection[], shortcut: 'textStart' | 'start' | 'end' | 'up' | 'down' | 'left' | 'right', options?: CursorMoveOptions): EditorSelection[];
/**
 * Applies a text change to the given text document
 */
declare function applyTextChangeToSelections<LAnnotation>(textDocument: TextDocument<LAnnotation>, selections: EditorSelection[], edit: ResolvedTextEdit, lineAnnotations?: DiffLineAnnotation<LAnnotation>[], tabSize?: number, undoBoundary?: boolean): {
  nextSelections: EditorSelection[];
  change?: TextDocumentChange;
};
/**
 * Applies text replacements to multiple selections. Texts pair by selection
 * index unless they are explicitly marked as document ordered.
 */
declare function applyTextReplaceToSelections<LAnnotation>(textDocument: TextDocument<LAnnotation>, selections: EditorSelection[], texts: string[], lineAnnotations?: DiffLineAnnotation<LAnnotation>[], undoBoundary?: boolean, textOrder?: 'selection' | 'document'): {
  nextSelections: EditorSelection[];
  change?: TextDocumentChange;
};
type AutoSurround = 'default' | 'never' | 'brackets' | 'quotes' | 'languageDefined';
/**
 * Returns per-selection replacement text when typing a surround character over
 * non-collapsed selections, matching VS Code auto-surround behavior.
 */
declare function getAutoSurroundReplacementTexts<LAnnotation>(textDocument: TextDocument<LAnnotation>, selections: EditorSelection[], char: string, autoSurround?: AutoSurround): string[] | undefined;
/**
 * Swaps the two characters adjacent to a collapsed selection, matching browser
 * insertTranspose (Ctrl+T) behavior.
 */
declare function applyTransposeToSelections<LAnnotation>(textDocument: TextDocument<LAnnotation>, selections: EditorSelection[], lineAnnotations?: DiffLineAnnotation<LAnnotation>[]): {
  nextSelections: EditorSelection[];
  change?: TextDocumentChange;
};
/**
 * Deletes from each selection to the end of its line, including the line break
 * when the caret is already at the end of a non-final line. Non-collapsed
 * selections delete their selected text instead.
 */
declare function applyDeleteHardLineForwardToSelections<LAnnotation>(textDocument: TextDocument<LAnnotation>, selections: EditorSelection[], lineAnnotations?: DiffLineAnnotation<LAnnotation>[]): {
  nextSelections: EditorSelection[];
  change?: TextDocumentChange;
};
/**
 * Deletes from each selection back to the start of its soft (visual) line.
 * Non-collapsed selections delete their selected text instead.
 */
declare function applyDeleteSoftLineBackwardToSelections<LAnnotation>(textDocument: TextDocument<LAnnotation>, selections: EditorSelection[], getSoftLineStart?: (line: number, character: number) => number, lineAnnotations?: DiffLineAnnotation<LAnnotation>[]): {
  nextSelections: EditorSelection[];
  change?: TextDocumentChange;
};
/**
 * Deletes the word or separator group immediately before each selection.
 * Non-collapsed selections delete their selected text instead.
 */
declare function applyDeleteWordBackwardToSelections<LAnnotation>(textDocument: TextDocument<LAnnotation>, selections: EditorSelection[], lineAnnotations?: DiffLineAnnotation<LAnnotation>[]): {
  nextSelections: EditorSelection[];
  change?: TextDocumentChange;
};
/**
 * Resolves the document range deleted by Backspace or Delete at a collapsed
 * caret. Non-collapsed selections delete their selected text instead.
 */
declare function resolveDeleteCharacterRange(textDocument: TextDocument<unknown>, selection: EditorSelection, forward: boolean): [start: Position, end: Position];
/**
 * Deletes one grapheme (or selected text) at each selection.
 */
declare function applyDeleteCharacterToSelections<LAnnotation>(textDocument: TextDocument<LAnnotation>, selections: EditorSelection[], forward: boolean, lineAnnotations?: DiffLineAnnotation<LAnnotation>[], tabSize?: number): {
  nextSelections: EditorSelection[];
  change?: TextDocumentChange;
};
/**
 * Checks if a selection is collapsed.
 */
declare function isCollapsedSelection(selection: EditorSelection | Range): boolean;
/**
 * Returns the caret (focus) position for a selection.
 */
declare function getCaretPosition(selection: EditorSelection): Position;
/**
 * Checks if a line is editable.
 */
declare function isLineEditable(lineType: string): boolean;
/**
 * Checks whether selections `a` and `b` intersect.
 */
declare function selectionIntersects(a: EditorSelection | Range, b: EditorSelection | Range): boolean;
/**
 * Compares two positions.
 */
declare function comparePosition(a: Position, b: Position): number;
/**
 * Creates a selection from anchor and focus offsets.
 */
declare function createSelectionFromAnchorAndFocusOffsets(textDocument: TextDocument<unknown>, anchorOffset: number, focusOffset: number): EditorSelection;
/**
 * Re-anchors selections after a batch of text edits has been applied, so the
 * caret keeps pointing at the same logical location in the changed buffer.
 *
 * `selectionOffsets` (one `[start, end]` pair per selection) and `edits` are
 * measured in the PRE-edit document; the returned selections are built from
 * `textDocument`, which must already reflect the applied edits. Selection
 * direction is preserved by remapping each edge and re-deriving anchor/focus.
 */
declare function remapSelectionsAfterEdits(textDocument: TextDocument<unknown>, selections: readonly EditorSelection[], selectionOffsets: ReadonlyArray<readonly [number, number]>, edits: readonly ResolvedTextEdit[]): EditorSelection[];
/**
 * Creates a selection from a anchor and focus selection.
 */
declare function createSelectionFrom(anchorSelection: EditorSelection, focusSelection: EditorSelection): EditorSelection;
/**
 * Extends or shrinks the selection `original` using the endpoints of `target`, \
 * matching contenteditable shift + click extend behavior.
 */
declare function extendSelection(original: EditorSelection, target: EditorSelection): EditorSelection;
/**
 * Extends multiple selections.
 */
declare function extendSelections(selections: EditorSelection[], target: EditorSelection): EditorSelection[];
/**
 * Merges overlapping selections.
 */
declare function mergeOverlappingSelections(selections: EditorSelection[]): EditorSelection[];
/**
 * Converts selections into merged line blocks for line-based commands.
 */
declare function getSelectedLineBlocks(selections: EditorSelection[]): {
  startLine: number;
  endLine: number;
}[];
/**
 * Moves a selection's line positions after its lines are shifted, clamping to
 * the target document bounds.
 */
declare function shiftSelectionLines(selection: EditorSelection, direction: -1 | 1, lineCount: number, getLineLength: (line: number) => number): EditorSelection;
/**
 * Finds the next matching word and updates the selections.
 */
declare function findNextMatch(textDocument: TextDocument<unknown>, selections: EditorSelection[]): EditorSelection[] | undefined;
/**
 * Get the full selection of the document.
 */
declare function getDocumentFullSelection(textDocument: TextDocument<unknown>): EditorSelection;
/**
 * Get the boundary selection of the document.
 */
declare function getDocumentBoundarySelection(textDocument: TextDocument<unknown>, atEnd: boolean, trimmedEndNewLine?: boolean): EditorSelection;
/**
 * Gets the text contributed by each selection in document order, preserving
 * the pairing needed to paste the values into another set of selections.
 */
declare function getSelectionClipboardTexts(textDocument: TextDocument<unknown>, selections: EditorSelection[]): string[];
/**
 * Get the clipboard text of the selections for the given text document. Used by
 * both copy and cut so the two stay in sync. Overlapping regions (e.g. several
 * carets on one line) are merged so the same text is never emitted twice, and a
 * line-ending separator is inserted only between regions that aren't already
 * contiguous in the document.
 */
declare function getSelectionText(textDocument: TextDocument<unknown>, selections: EditorSelection[]): string;
declare function resolveSelectionCut(textDocument: TextDocument<unknown>, selections: EditorSelection[]): {
  text: string;
  edits: ResolvedTextEdit[];
  nextSelectionOffsets: number[];
};
/**
 * Get the anchor node and offset for a selection.
 */
declare function getSelectionAnchor(lineElement: HTMLElement, character: number): [Node, number];
/**
 * Expands a zero-width selection to the word-like segment that contains the caret.
 */
declare function expandCollapsedSelectionToWord(textDocument: TextDocument<unknown>, selection: EditorSelection): EditorSelection;
//#endregion
export { AutoSurround, CursorMoveOptions, DirectionBackward, DirectionForward, DirectionNone, ResolveRenderableLine, applyDeleteCharacterToSelections, applyDeleteHardLineForwardToSelections, applyDeleteSoftLineBackwardToSelections, applyDeleteWordBackwardToSelections, applyTextChangeToSelections, applyTextReplaceToSelections, applyTransposeToSelections, comparePosition, convertSelection, createSelectionFrom, createSelectionFromAnchorAndFocusOffsets, expandCollapsedSelectionToWord, extendSelection, extendSelections, findNextMatch, getAutoSurroundReplacementTexts, getCaretPosition, getDocumentBoundarySelection, getDocumentFullSelection, getSelectedLineBlocks, getSelectionAnchor, getSelectionClipboardTexts, getSelectionText, isCollapsedSelection, isLineEditable, mapCursorMove, mapSelectionShift, mergeOverlappingSelections, remapSelectionsAfterEdits, resolveDeleteCharacterRange, resolveIndentEdits, resolveSelectionCut, selectionIntersects, shiftSelectionLines };
//# sourceMappingURL=selection.d.ts.map