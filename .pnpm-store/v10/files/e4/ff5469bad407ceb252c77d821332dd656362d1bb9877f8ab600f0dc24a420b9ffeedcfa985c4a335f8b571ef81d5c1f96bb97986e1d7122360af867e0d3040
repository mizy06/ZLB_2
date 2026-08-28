import { BaseDiffOptions, DiffLineAnnotation, DiffsTextDocument, ExpansionDirections, FileDiffMetadata, NumericScrollLineAnchor, PendingCodeViewLayoutReset, RenderWindow, SelectionSide, StickySpecs, ThemeTypes, VirtualFileMetrics } from "../types.js";
import { WorkerPoolManager } from "../worker/WorkerPoolManager.js";
import { FileDiff, FileDiffOptions, FileDiffRenderProps } from "./FileDiff.js";
import { Virtualizer } from "./Virtualizer.js";
import { CodeView } from "./CodeView.js";

//#region src/components/VirtualizedFileDiff.d.ts
type LoadedPartialDiffContents = Awaited<ReturnType<NonNullable<BaseDiffOptions['loadDiffFiles']>>>;
declare const VIRTUALIZED_FILE_DIFF_LAYOUT_CHECKPOINT_INTERVAL = 3000;
declare class VirtualizedFileDiff<LAnnotation = undefined> extends FileDiff<LAnnotation> {
  readonly __id: string;
  top: number | undefined;
  height: number;
  private metrics;
  private cache;
  private isVisible;
  private isSetup;
  private virtualizer;
  private layoutDirty;
  private forceRenderOverride;
  private currentCollapsed;
  private currentExpandUnchanged;
  private pendingHydratedDiff;
  private pendingExpansions;
  constructor(options: FileDiffOptions<LAnnotation> | undefined, virtualizer: Virtualizer | CodeView<LAnnotation>, metrics?: Partial<VirtualFileMetrics>, workerManager?: WorkerPoolManager, isContainerManaged?: boolean);
  setMetrics(metrics?: Partial<VirtualFileMetrics>, force?: boolean): void;
  setLineAnnotations(lineAnnotations: DiffLineAnnotation<LAnnotation>[]): void;
  private syncLineAnnotations;
  private setFileAnnotationHeight;
  private hasFileAnnotations;
  private getLineHeight;
  private getEstimatedLineHeight;
  setOptions(options: FileDiffOptions<LAnnotation> | undefined): void;
  setThemeType(themeType: ThemeTypes): void;
  private resetLayoutCache;
  private invalidateDerivedLayoutCache;
  reconcileHeights(): boolean;
  onRender: (dirty: boolean) => boolean;
  flushManagers(): void;
  prepareCodeViewItem(fileDiff: FileDiffMetadata, top: number, reset?: PendingCodeViewLayoutReset, lineAnnotations?: DiffLineAnnotation<LAnnotation>[]): number;
  getLinePosition(lineNumber: number, side?: SelectionSide): {
    top: number;
    height: number;
  } | undefined;
  getEditorViewport(): HTMLElement | Document | undefined;
  getNumericScrollAnchor(localViewportTop: number): NumericScrollLineAnchor | undefined;
  getVirtualizedHeight(): number;
  getAdvancedStickySpecs(windowSpecs?: RenderWindow): StickySpecs | undefined;
  cleanUp(recycle?: boolean): void;
  expandHunk: (hunkIndex: number, direction: ExpansionDirections, expansionLineCountOverride?: number) => void;
  protected handleFilesLoaded(expectedDiff: FileDiffMetadata, files: LoadedPartialDiffContents): Promise<void>;
  consumeCodeViewLayoutChanges(expectedFileDiff: FileDiffMetadata): FileDiffMetadata | undefined;
  protected loadFilesIfNecessary(): void;
  isLineRenderable(lineNumber: number): boolean;
  /**
   * Invalidate layout after an edit session changed the rendered row set
   * without a line-count change (a mid-session region change or the exit
   * recompute): estimated heights bake the hunk shapes in, and nothing else
   * invalidates them now that editing does not flip expandUnchanged. Public
   * so CodeView can run it when reaping a session whose instance was already
   * released.
   */
  invalidateEditSessionLayout(): void;
  protected escalateEditSessionRender(): void;
  protected shouldSelfHealEditSession(): boolean;
  setVisibility(visible: boolean): void;
  rerender(): void;
  applyDocumentChange(textDocument: DiffsTextDocument, newLineAnnotations?: DiffLineAnnotation<LAnnotation>[], shouldUpdateBuffer?: boolean): void;
  private computeApproximateSize;
  private getActiveEstimatedHeight;
  private ensureEstimatedDiffHeights;
  private validateComputedHeight;
  render({
    fileContainer,
    fileDiff,
    forceRender,
    lineAnnotations,
    ...fileInputProps
  }?: FileDiffRenderProps<LAnnotation>): boolean;
  syncVirtualizedTop(): void;
  protected shouldDisableVirtualizationBuffers(): boolean;
  protected shouldGuardRebuildScroll(): boolean;
  private isSimpleMode;
  private isAdvancedMode;
  private getVirtualizedTop;
  private getSimpleVirtualizer;
  private getAdvancedVirtualizer;
  private isResizeDebuggingEnabled;
  private getDiffStyle;
  private getHunkSeparatorType;
  private approximateLayoutCheckpoints;
  private getLayoutCheckpointBeforeLineIndex;
  private getLayoutCheckpointBeforeTop;
  private getExpandedLineCount;
  private getLayoutLineCount;
  private computeRenderRangeFromWindow;
}
//#endregion
export { VIRTUALIZED_FILE_DIFF_LAYOUT_CHECKPOINT_INTERVAL, VirtualizedFileDiff };
//# sourceMappingURL=VirtualizedFileDiff.d.ts.map