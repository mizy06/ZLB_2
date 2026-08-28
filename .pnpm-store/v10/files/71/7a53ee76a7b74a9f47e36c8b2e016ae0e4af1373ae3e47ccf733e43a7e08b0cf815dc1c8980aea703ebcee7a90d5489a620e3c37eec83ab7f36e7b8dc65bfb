import { EditorSelection, TextEdit } from "../types.js";
import { TextDocument } from "./textDocument.js";
import { PopoverViewportBounds } from "./popover.js";

//#region src/editor/selectionAction.d.ts
interface SelectionActionContext<LAnnotation> {
  /** The current selection (live: reflects keyboard-driven changes). */
  selection: EditorSelection;
  /** The text document. */
  textDocument: TextDocument<LAnnotation>;
  /** Applies the edits to the text document. */
  applyEdits: (edits: TextEdit[]) => void;
  /** Gets the text of the current selection. */
  getSelectionText: () => string;
  /** Replaces the text of the current selection. */
  replaceSelectionText: (text: string) => void;
  /** Closes the selection action. */
  close: () => void;
}
/**
 * Selection action widget.
 */
declare class SelectionActionWidget {
  #private;
  constructor(selectionActionElement: HTMLElement, overlayElement: HTMLElement, onHeightChange: () => void);
  /**
   * Repositions the selection action widget.
   * @param left - The left position of the selection action widget.
   * @param top - The top position of the selection action widget.
   * @param gutterWidth - The width of the gutter.
   * @param placeAbove - Whether the selection action widget should be placed above the anchor.
   * @param visible - Whether the selection intersects the viewport.
   */
  reposition(left: number, top: number, gutterWidth: number, placeAbove: boolean, visible: boolean, viewport?: PopoverViewportBounds): void;
  /**
   * Gets the height of the selection action widget.
   * @returns The height of the selection action widget.
   */
  get height(): number;
  /**
   * Cleans up the selection action widget.
   */
  cleanup(): void;
}
//#endregion
export { SelectionActionContext, SelectionActionWidget };
//# sourceMappingURL=selectionAction.d.ts.map