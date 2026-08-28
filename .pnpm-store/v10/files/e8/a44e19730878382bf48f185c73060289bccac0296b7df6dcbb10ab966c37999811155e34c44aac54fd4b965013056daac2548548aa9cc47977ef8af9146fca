import { CodeViewItem, CodeViewScrollTarget, DiffLineAnnotation, DiffsEditor, FileContents, LineAnnotation } from "../types.js";
import { GetHoveredLineResult } from "../managers/InteractionManager.js";
import { CodeView as CodeView$1, CodeViewLineSelection, CodeViewOptions } from "../components/CodeView.js";
import { EditorOptions } from "../editor/editor.js";
import { CSSProperties, ReactNode, Ref } from "react";

//#region src/react/CodeView.d.ts
type CodeViewGutterUtilityGetter = (() => GetHoveredLineResult<'file'> | undefined) | (() => GetHoveredLineResult<'diff'> | undefined);
type CodeViewReactOptions<LAnnotation = undefined> = Omit<CodeViewOptions<LAnnotation>, 'controlledSelection' | 'createEditor' | 'onSelectedLinesChange'>;
interface CodeViewBaseProps<LAnnotation> {
  options?: CodeViewReactOptions<LAnnotation>;
  /**
   * Creation-time options passed to the nearest EditProvider factory.
   * CodeView supplies its item-specific change callback.
   */
  editorOptions?: Omit<EditorOptions<LAnnotation>, 'onChange'>;
  className?: string;
  style?: CSSProperties;
  containerRef?: Ref<HTMLDivElement>;
  disableWorkerPool?: boolean;
  selectedLines?: CodeViewLineSelection | null;
  onSelectedLinesChange?(selection: CodeViewLineSelection | null): void;
  onScroll?(scrollTop: number, viewer: CodeView$1<LAnnotation>): void;
  /** Render a non-virtualized node at the very start of the scroll content,
   * before the first item. Always rendered; scrolls with the content. */
  renderCodeViewHeader?(): ReactNode;
  /** Render a non-virtualized node at the very end of the scroll content, after
   * the last item. Always rendered; scrolls with the content. */
  renderCodeViewFooter?(): ReactNode;
  /** Called with the owning item on every edited-document change. */
  onItemEditChange?(item: CodeViewItem<LAnnotation>, file: FileContents, lineAnnotations?: LineAnnotation<LAnnotation>[] | DiffLineAnnotation<LAnnotation>[]): void;
  /**
   * Called once with the final contents when an item's edit session ends
   * (edit turned off, item removed or collapsed). Not called for sessions
   * that produced no changes. Committing is user-space: make one combined
   * item write carrying the new file/fileDiff (with a fresh `cacheKey`,
   * since the contents changed) along with `edit: false`.
   */
  onItemEditComplete?(item: CodeViewItem<LAnnotation>, file: FileContents, lineAnnotations?: LineAnnotation<LAnnotation>[] | DiffLineAnnotation<LAnnotation>[]): void;
  renderCustomHeader?(item: CodeViewItem<LAnnotation>): ReactNode;
  renderHeaderPrefix?(item: CodeViewItem<LAnnotation>): ReactNode;
  renderHeaderFilenameSuffix?(item: CodeViewItem<LAnnotation>): ReactNode;
  renderHeaderMetadata?(item: CodeViewItem<LAnnotation>): ReactNode;
  renderAnnotation?(annotation: LineAnnotation<LAnnotation> | DiffLineAnnotation<LAnnotation>, item: CodeViewItem<LAnnotation>): ReactNode;
  renderGutterUtility?(getHoveredLine: CodeViewGutterUtilityGetter, item: CodeViewItem<LAnnotation>): ReactNode;
}
interface ControlledCodeViewProps<LAnnotation> extends CodeViewBaseProps<LAnnotation> {
  items: readonly CodeViewItem<LAnnotation>[];
  initialItems?: never;
}
interface UncontrolledCodeViewProps<LAnnotation> extends CodeViewBaseProps<LAnnotation> {
  initialItems?: readonly CodeViewItem<LAnnotation>[];
  items?: never;
}
type CodeViewProps<LAnnotation = undefined> = ControlledCodeViewProps<LAnnotation> | UncontrolledCodeViewProps<LAnnotation>;
interface CodeViewHandle<LAnnotation> {
  addItems(items: readonly CodeViewItem<LAnnotation>[]): void;
  getItem(id: string): CodeViewItem<LAnnotation> | undefined;
  removeItem(id: string): boolean;
  updateItem(item: CodeViewItem<LAnnotation>): boolean;
  updateItemId(oldId: string, newId: string): boolean;
  scrollTo(target: CodeViewScrollTarget): void;
  setSelectedLines(selection: CodeViewLineSelection | null): void;
  getSelectedLines(): CodeViewLineSelection | null;
  clearSelectedLines(): void;
  getEditor(id: string): DiffsEditor<LAnnotation> | undefined;
  getInstance(): CodeView$1<LAnnotation> | undefined;
}
type CodeViewComponent = <LAnnotation = undefined>(props: CodeViewProps<LAnnotation> & {
  ref?: React.Ref<CodeViewHandle<LAnnotation>>;
}) => React.JSX.Element;
declare const CodeView: CodeViewComponent;
//#endregion
export { CodeView, CodeViewHandle, CodeViewProps, CodeViewReactOptions, ControlledCodeViewProps, UncontrolledCodeViewProps };
//# sourceMappingURL=CodeView.d.ts.map