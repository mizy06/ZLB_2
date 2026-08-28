import { DiffLineAnnotation, EditorChange, EditorSelection, Position, Range, ResolvedTextEdit, TextEdit } from "../types.js";
import { EditStack } from "./editStack.js";
import { SearchParams } from "./searchPanel.js";

//#region src/editor/textDocument.d.ts
interface TextDocumentChange {
  /** The edits that were applied to the text document. */
  readonly changes: EditorChange[];
  /** First line whose rendered content or tokenizer state may have changed. */
  readonly startLine: number;
  /** Character on the first changed line where the edit began. */
  readonly startCharacter: number;
  /** Character on the original last changed line where the edit ended. */
  readonly endCharacter: number;
  /** Last line whose rendered content may have changed after the edit. */
  readonly endLine: number;
  /** Whether the original edit range ended at the previous document EOF. */
  readonly endedAtDocumentEnd: boolean;
  /** Line count before the edit was applied. */
  readonly previousLineCount: number;
  /** Line count after the edit was applied. */
  readonly lineCount: number;
  /** Difference between the old and new line counts. */
  readonly lineDelta: number;
  /** Exact rendered line ranges touched by each edit after the edit was applied. */
  readonly changedLineRanges: readonly [startLine: number, endLine: number][];
  /** Per-edit rendered line ranges before adjacent ranges are coalesced. */
  readonly changedLineChanges?: readonly [startLine: number, endLine: number, lineDelta: number, startCharacter?: number, endCharacter?: number, endedAtDocumentEnd?: boolean][];
}
type TextDocumentHistoryResult<LAnnotation> = [change: TextDocumentChange, selections?: EditorSelection[], lineAnnotations?: DiffLineAnnotation<LAnnotation>[], selectionEdits?: ResolvedTextEdit[]];
/**
 * A vscode-languageserver-textdocument compatible text document.
 */
declare class TextDocument<LAnnotation> {
  #private;
  constructor(uri: string, text: string, languageId?: string, version?: number, editStack?: EditStack<LAnnotation>);
  get uri(): string;
  get languageId(): string;
  get version(): number;
  get lineCount(): number;
  get eol(): string;
  get canUndo(): boolean;
  get canRedo(): boolean;
  positionAt(offset: number): Position;
  positionsAt(offsets: readonly number[]): Position[];
  offsetAt(position: Position): number;
  getText(range?: Range): string;
  getLineText(line: number, includeLineBreak?: boolean): string;
  normalizeEol(text: string): string;
  getLineLength(line: number, includeLineBreak?: boolean): number;
  charAt(offset: number): string;
  charAt(position: Position): string;
  getTextSlice(start: number, end: number): string;
  findNextNonOverlappingSubstring(needle: string, occupied: readonly [start: number, end: number][]): number | undefined;
  search(searchParams: SearchParams): [start: number, end: number][];
  applyEdits(edits: TextEdit[], updateHistory?: boolean, selectionsBefore?: EditorSelection[], selectionsAfter?: EditorSelection[], undoBoundary?: boolean): TextDocumentChange | undefined;
  resolveEdits(edits: readonly TextEdit[]): ResolvedTextEdit[];
  applyResolvedEdits(edits: ResolvedTextEdit[], updateHistory?: boolean, selectionsBefore?: EditorSelection[], selectionsAfter?: EditorSelection[], undoBoundary?: boolean): TextDocumentChange | undefined;
  setLastUndoSelectionsAfter(selections: EditorSelection[]): void;
  setLastUndoLineAnnotations(lineAnnotationsBefore: DiffLineAnnotation<LAnnotation>[], lineAnnotationsAfter: DiffLineAnnotation<LAnnotation>[]): void;
  undo(): TextDocumentHistoryResult<LAnnotation> | undefined;
  redo(): TextDocumentHistoryResult<LAnnotation> | undefined;
  normalizePosition(position: Position): Position;
}
//#endregion
export { type Position, type Range, TextDocument, TextDocumentChange, type TextEdit };
//# sourceMappingURL=textDocument.d.ts.map