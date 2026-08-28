import { DiffLineAnnotation, DiffsEditableComponent, DiffsEditor, EditableInstance, EditorChangeEvent, EditorState, FileContents, LineAnnotation, Range, TextEdit } from "../types.js";
import { EditorKeymap } from "./command.js";
import { LanguageConfigMap } from "./languages.js";
import { Marker } from "./marker.js";
import { AutoSurround } from "./selection.js";
import { SelectionActionContext } from "./selectionAction.js";
import { PersistStateStorage } from "./stateStorage.js";

//#region src/editor/editor.d.ts
interface EditorOptions<LAnnotation> {
  /** The maximum number of entries to keep in the undo stack. */
  historyMaxEntries?: number;
  /** Custom keymap groups checked before defaults; later groups take precedence. */
  keymap?: EditorKeymap;
  /**
   * Preserve each file's document and item-local editor state when switching files.
   * Every editable file must provide a unique, stable `cacheKey`.
   */
  persistState?: boolean;
  /**
   * Storage for serializable editor state. Text documents stay in this Editor's
   * in-memory cache. Defaults to `"inMemory"`.
   */
  persistStateStorage?: PersistStateStorage;
  /** Render rounded corners for selection ranges, default is true. */
  roundedSelection?: boolean;
  /** Highlight matching brackets near the caret, default is true. */
  matchBrackets?: boolean;
  /**
   * Controls auto-surround when typing quotes or brackets over a selection.
   * Default is `"default"` (both quotes and brackets).
   */
  autoSurround?: AutoSurround;
  /** Per-language comment tokens used by the comment commands. */
  languageCommentConfig?: LanguageConfigMap;
  /**
   * Show a floating selection action popover after a user-created selection,
   * default is disabled. Programmatic selection updates do not open it.
   */
  enabledSelectionAction?: boolean;
  /**
   * Custom clipboard provider.
   * Highly recommended to use native clipboard API if you are building an electron app.
   * see https://www.electronjs.org/docs/latest/api/clipboard
   */
  clipboard?: {
    readText: (type?: string) => Promise<string> | string;
  };
  /** Render the selection action widget element. */
  renderSelectionAction?: (context: SelectionActionContext<LAnnotation>) => HTMLElement;
  /** Callback when the editor is attached to a file. */
  onAttach?: (editor: Editor<LAnnotation>, fileInstance: DiffsEditableComponent<LAnnotation>) => void;
  /** Callback when the editor document changes. */
  onChange?: (file: FileContents, lineAnnotations: LineAnnotation<LAnnotation>[] | DiffLineAnnotation<LAnnotation>[] | undefined, event: EditorChangeEvent<LAnnotation>) => void;
  /** Callback when the editor gains focus. */
  onFocus?: () => void;
  /** Callback when the editor loses focus. */
  onBlur?: () => void;
  __debug?: boolean;
}
interface EditorFocusOptions extends FocusOptions {
  /** One-based document line number or first editable line with a visible top. */
  lineNumber?: number | 'first-visible';
  /** Zero-based character offset for a numeric line. Defaults to 0. */
  character?: number;
  /** Non-negative CSS pixels below the viewport or sticky header. */
  offset?: number;
}
declare class Editor<LAnnotation> implements DiffsEditor<LAnnotation> {
  #private;
  constructor(options?: EditorOptions<LAnnotation>);
  setOptions(options: EditorOptions<LAnnotation>): void;
  edit<T extends DiffsEditableComponent<LAnnotation>>(fileInstance: EditableInstance<T>): () => void;
  /**
   * Apply edits to current attached file. Every edit joins the undo timeline:
   * a programmatic edit must leave the document and its history exactly as
   * the same edit typed by the user would (history equivalence — see
   * TextDocument.applyResolvedEdits), so it is undoable like any other edit.
   *
   * @param updateHistory Whether to record caller selection snapshots for
   * exact undo/redo restoration. Defaults to true. When false, live selections
   * are remapped during replay and the text edit still joins the undo timeline.
   */
  applyEdits(edits: TextEdit[], updateHistory?: boolean): void;
  /** Whether there is an edit to undo. */
  get canUndo(): boolean;
  /** Whether there is an undone edit to redo. */
  get canRedo(): boolean;
  /** Undo the last edit. Does nothing when there is nothing to undo. */
  undo(): void;
  /** Redo the last undone edit. Does nothing when there is nothing to redo. */
  redo(): void;
  getFile(): FileContents | undefined;
  getText(): string;
  getState(): EditorState;
  setState({
    selections,
    view
  }: EditorState): void;
  setSelections(selections: (Range & {
    direction: 'none' | 'backward' | 'forward';
  })[]): void;
  setMarkers(markers: Marker[]): void;
  focus(options?: EditorFocusOptions): void;
  blur(): void;
  cleanUp(recycle?: boolean): void;
  /** @internal Capture outgoing state and substitute cached text before render. */
  __prepareFile(file: FileContents): FileContents;
  /** @internal */
  __postponeBgTokenizeToNextFrame(): void;
  /** @internal */
  __captureFocusForDOMReplacement(): void;
  /** @internal */
  __syncRenderView: DiffsEditor<LAnnotation>['__syncRenderView'];
}
//#endregion
export { Editor, EditorFocusOptions, EditorOptions };
//# sourceMappingURL=editor.d.ts.map