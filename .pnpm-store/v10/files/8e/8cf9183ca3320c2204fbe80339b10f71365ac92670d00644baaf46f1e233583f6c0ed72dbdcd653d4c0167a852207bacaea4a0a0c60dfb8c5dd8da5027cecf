import { DiffLineAnnotation, EditorSelection, ResolvedTextEdit } from "../types.js";
import { TextDocument } from "./textDocument.js";

//#region src/editor/editStack.d.ts
type EditStackCoalescingMode = 1 | 2 | 3;
/** An entry in the edit stack. */
interface EditStackEntry<LAnnotation> {
  /** Forward offset edits from the entry's base text to its final text. */
  forwardEdits: ResolvedTextEdit[];
  /** Inverse offset edits from the entry's final text back to its base text. */
  inverseEdits: ResolvedTextEdit[];
  /** Document version before the entry is applied. */
  versionBefore: number;
  /** Document version after the entry is applied. */
  versionAfter: number;
  /** Selection before the transaction. */
  selectionsBefore?: EditorSelection[];
  /** Selection after the transaction. */
  selectionsAfter?: EditorSelection[];
  /** Line annotations before the transaction. */
  lineAnnotationsBefore?: DiffLineAnnotation<LAnnotation>[];
  /** Line annotations after the transaction. */
  lineAnnotationsAfter?: DiffLineAnnotation<LAnnotation>[];
  /** Input mode inferred from the edit or retained by a coalesced run. */
  coalescingMode?: EditStackCoalescingMode;
  /**
   * When `true`, this entry is its own undo step and never merges with the
   * entry before or after it. Set for paste and cut, which otherwise look like
   * typing and would merge into the previous keystroke.
   */
  undoBoundary?: boolean;
}
/** Options for the edit stack. */
interface EditStackOptions {
  /** The maximum number of entries to keep in the undo stack. */
  maxEntries?: number;
}
/** A stack of edit entries. */
declare class EditStack<LAnnotation> {
  #private;
  constructor(options?: EditStackOptions);
  get canUndo(): boolean;
  get canRedo(): boolean;
  /** Clears both the undo and redo stacks. */
  clear(): void;
  /** Clears the redo stack. */
  clearRedo(): void;
  /** Pushes a new entry onto the undo stack. */
  push(entry: EditStackEntry<LAnnotation>): void;
  /** Sets the selections after the last undo entry. */
  setLastUndoSelectionsAfter(selections: EditorSelection[]): void;
  /** Sets the line annotations after the last undo entry. */
  setLastUndoLineAnnotations(lineAnnotationsBefore: DiffLineAnnotation<LAnnotation>[], lineAnnotationsAfter: DiffLineAnnotation<LAnnotation>[]): void;
  /** Returns the last undo entry, or `undefined` if empty. */
  peekUndo(): EditStackEntry<LAnnotation> | undefined;
  /** Returns the last undo entry only while its coalescing group is open. */
  peekUndoForCoalescing(): EditStackEntry<LAnnotation> | undefined;
  /** Replaces the last undo entry with the given entry. */
  replaceLastUndo(entry: EditStackEntry<LAnnotation>): void;
  /** Moves the latest undo entry to the redo stack and returns it, or `undefined` if empty. */
  popUndoToRedo(): EditStackEntry<LAnnotation> | void;
  /** Moves the latest redo entry back to the undo stack and returns it, or `undefined` if empty. */
  popRedoToUndo(): EditStackEntry<LAnnotation> | void;
}
declare function createEditStackEntry<LAnnotation>(textDocument: TextDocument<LAnnotation>, resolvedEdits: ResolvedTextEdit[], versionBefore: number, versionAfter: number, selectionsBefore?: EditorSelection[], selectionsAfter?: EditorSelection[], lineAnnotationsBefore?: DiffLineAnnotation<LAnnotation>[], lineAnnotationsAfter?: DiffLineAnnotation<LAnnotation>[]): EditStackEntry<LAnnotation>;
/** Determines if the change matches following modes:
 * - 'insert': simple typing
 * - 'backspace': backward delete
 * - 'delete': forward delete
 */
declare function shouldCoalesceEditStackEntry<LAnnotation>(previousEntry: EditStackEntry<LAnnotation> | undefined, nextEntry: EditStackEntry<LAnnotation>): boolean;
/** Coalesce edit stack entries for simple typing and single-character deletes. */
declare function coalesceEditStackEntries<LAnnotation>(previousEntry: EditStackEntry<LAnnotation>, nextEntry: EditStackEntry<LAnnotation>): EditStackEntry<LAnnotation>;
//#endregion
export { EditStack, EditStackEntry, EditStackOptions, coalesceEditStackEntries, createEditStackEntry, shouldCoalesceEditStackEntry };
//# sourceMappingURL=editStack.d.ts.map