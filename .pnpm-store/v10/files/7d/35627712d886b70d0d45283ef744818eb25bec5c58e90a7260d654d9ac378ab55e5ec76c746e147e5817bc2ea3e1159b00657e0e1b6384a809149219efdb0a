import { AppliedThemeStyleCache, BaseCodeOptions, BaseDiffOptions, CustomPreProperties, DiffLineAnnotation, DiffsEditableComponent, DiffsEditor, DiffsTextDocument, EditorActiveLineOptions, ExpansionDirections, FileContents, FileDiffMetadata, HighlightedToken, HunkData, HunkSeparators, MaybeDiffFileInput, PostRenderPhase, PrePropertiesConfig, RenderHeaderFilenameSuffixCallback, RenderHeaderMetadataCallback, RenderHeaderPrefixCallback, RenderRange, SelectedLineRange, ThemeTypes } from "../types.js";
import { GetHoveredLineResult, GetLineIndexUtility, InteractionManager, InteractionManagerBaseOptions, SelectionWriteOptions } from "../managers/InteractionManager.js";
import { WorkerPoolManager } from "../worker/WorkerPoolManager.js";
import { ResizeManager } from "../managers/ResizeManager.js";
import { ScrollSyncManager } from "../managers/ScrollSyncManager.js";
import { DiffHunksRenderer, DiffHunksRendererOptions, HunksRenderResult } from "../renderers/DiffHunksRenderer.js";

//#region src/components/FileDiff.d.ts
type LoadedPartialDiffContents = Awaited<ReturnType<NonNullable<BaseDiffOptions['loadDiffFiles']>>>;
type DeferredSelectedLinesWrite = [range: SelectedLineRange | null, options: SelectionWriteOptions | undefined];
type DeferredEditorActiveLineWrite = [lineNumber: number | null, options: EditorActiveLineOptions | undefined];
interface FileDiffRenderBaseProps<LAnnotation> {
  fileDiff?: FileDiffMetadata;
  deferManagers?: boolean;
  forceRender?: boolean;
  preventEmit?: boolean;
  fileContainer?: HTMLElement;
  containerWrapper?: HTMLElement;
  lineAnnotations?: DiffLineAnnotation<LAnnotation>[];
  renderRange?: RenderRange;
}
type FileDiffRenderProps<LAnnotation> = FileDiffRenderBaseProps<LAnnotation> & MaybeDiffFileInput;
type FileDiffHydrationProps<LAnnotation> = Omit<FileDiffRenderBaseProps<LAnnotation>, 'fileContainer'> & MaybeDiffFileInput & {
  fileContainer: HTMLElement;
  prerenderedHTML?: string;
};
type FileDiffType = 'file-diff' | 'unresolved-file';
interface FileDiffOptions<LAnnotation> extends Omit<BaseDiffOptions, 'hunkSeparators'>, InteractionManagerBaseOptions<'diff'> {
  hunkSeparators?: Exclude<HunkSeparators, 'custom'>
  /**
  * @deprecated Custom hunk separator functions are deprecated and will be
  * removed in a future version.
  */
  | ((hunk: HunkData, instance: FileDiff<LAnnotation>) => HTMLElement | DocumentFragment | null | undefined);
  disableFileHeader?: boolean;
  renderHeaderPrefix?: RenderHeaderPrefixCallback;
  renderHeaderFilenameSuffix?: RenderHeaderFilenameSuffixCallback;
  renderHeaderMetadata?: RenderHeaderMetadataCallback;
  renderCustomHeader?: RenderHeaderMetadataCallback;
  /**
   * When true, errors during rendering are rethrown instead of being caught
   * and displayed in the DOM. Useful for testing or when you want to handle
   * errors yourself.
   */
  disableErrorHandling?: boolean;
  renderAnnotation?(annotation: DiffLineAnnotation<LAnnotation>): HTMLElement | undefined;
  renderGutterUtility?(getHoveredRow: () => GetHoveredLineResult<'diff'> | undefined): HTMLElement | null | undefined;
  onPostRender?(node: HTMLElement, instance: FileDiff<LAnnotation>, phase: PostRenderPhase): unknown;
}
interface AnnotationElementCache<LAnnotation> {
  element: HTMLElement;
  annotation: DiffLineAnnotation<LAnnotation>;
}
interface CustomHunkElementCache {
  element: HTMLElement;
  hunkData: HunkData;
}
interface PendingFileLoad {
  fileDiff: FileDiffMetadata;
  promise: Promise<void>;
}
type HydrationSetup<LAnnotation> = {
  fileDiff: FileDiffMetadata | undefined;
  lineAnnotations: DiffLineAnnotation<LAnnotation>[] | undefined;
} & MaybeDiffFileInput;
declare class FileDiff<LAnnotation = undefined> implements DiffsEditableComponent<LAnnotation> {
  options: FileDiffOptions<LAnnotation>;
  protected workerManager?: WorkerPoolManager | undefined;
  protected isContainerManaged: boolean;
  static LoadedCustomComponent: boolean;
  readonly __id: string;
  readonly type: FileDiffType;
  protected fileContainer: HTMLElement | undefined;
  protected spriteSVG: SVGElement | undefined;
  protected pre: HTMLPreElement | undefined;
  protected codeUnified: HTMLElement | undefined;
  protected codeDeletions: HTMLElement | undefined;
  protected codeAdditions: HTMLElement | undefined;
  protected bufferBefore: HTMLElement | undefined;
  protected bufferAfter: HTMLElement | undefined;
  protected themeCSSStyle: HTMLStyleElement | undefined;
  protected appliedThemeCSS: AppliedThemeStyleCache | undefined;
  protected hasAdoptedThemeCSS: boolean;
  protected unsafeCSSStyle: HTMLStyleElement | undefined;
  protected appliedUnsafeCSS: string | undefined;
  protected gutterUtilityContent: HTMLElement | undefined;
  protected headerElement: HTMLElement | undefined;
  protected headerPrefix: HTMLElement | undefined;
  protected headerFilenameSuffix: HTMLElement | undefined;
  protected headerMetadata: HTMLElement | undefined;
  protected headerCustom: HTMLElement | undefined;
  protected separatorCache: Map<string, CustomHunkElementCache>;
  protected errorWrapper: HTMLElement | undefined;
  protected placeHolder: HTMLElement | undefined;
  protected hunksRenderer: DiffHunksRenderer<LAnnotation>;
  protected resizeManager: ResizeManager;
  protected scrollSyncManager: ScrollSyncManager;
  protected interactionManager: InteractionManager<'diff'>;
  protected annotationCache: Map<string, AnnotationElementCache<LAnnotation>>;
  protected lineAnnotations: DiffLineAnnotation<LAnnotation>[];
  protected managersDirty: boolean;
  protected deletionFile?: FileContents | null;
  protected additionFile?: FileContents | null;
  fileDiff: FileDiffMetadata | undefined;
  protected renderRange: RenderRange | undefined;
  protected pendingFiles: PendingFileLoad | undefined;
  protected appliedPreAttributes: PrePropertiesConfig | undefined;
  protected lastRenderedHeaderHTML: string | undefined;
  protected cachedHeaderHTML: string | undefined;
  protected lastRowCount: number | undefined;
  private mounted;
  protected enabled: boolean;
  protected editor: DiffsEditor<LAnnotation> | undefined;
  protected refreshViewTimeout: ReturnType<typeof setTimeout> | undefined;
  protected lineStateRefreshPending: boolean;
  protected deferredSelectedLines: DeferredSelectedLinesWrite | undefined;
  protected deferredEditorActiveLine: DeferredEditorActiveLineWrite | undefined;
  constructor(options?: FileDiffOptions<LAnnotation>, workerManager?: WorkerPoolManager | undefined, isContainerManaged?: boolean);
  protected handleHighlightRender: () => void;
  protected getHunksRendererOptions(options: FileDiffOptions<LAnnotation>): DiffHunksRendererOptions;
  protected createHunksRenderer(options: FileDiffOptions<LAnnotation>): DiffHunksRenderer<LAnnotation>;
  getLineIndex: GetLineIndexUtility;
  setOptions(options: FileDiffOptions<LAnnotation> | undefined): void;
  protected syncInteractionOptions(): void;
  private mergeOptions;
  setThemeType(themeType: ThemeTypes): void;
  private applyCachedThemeState;
  private hasThemeChanged;
  getHoveredLine: () => GetHoveredLineResult<'diff'> | undefined;
  setLineAnnotations(lineAnnotations: DiffLineAnnotation<LAnnotation>[]): void;
  private canPartiallyRender;
  setSelectedLines(range: SelectedLineRange | null, options?: SelectionWriteOptions): void;
  setEditorActiveLine(lineNumber: number | null, options?: EditorActiveLineOptions): void;
  protected flushDeferredLineState(): void;
  flushManagers(): void;
  protected shouldApplyColumnVariables(overflow: 'scroll' | 'wrap'): boolean;
  getCodeScrollLeft(): number;
  setCodeScrollLeft(position: number): void;
  __getEffectiveCodeOptions(): BaseCodeOptions;
  cleanUp(recycle?: boolean): void;
  virtualizedSetup(): void;
  hydrate({
    fileContainer,
    prerenderedHTML,
    preventEmit,
    lineAnnotations,
    fileDiff,
    ...fileInputProps
  }: FileDiffHydrationProps<LAnnotation>): void;
  protected hydrateElements(fileContainer: HTMLElement, prerenderedHTML: string | undefined): void;
  protected hydrationSetup({
    fileDiff,
    oldFile,
    newFile,
    lineAnnotations
  }: HydrationSetup<LAnnotation>): void;
  rerender(): void;
  onThemeChange(): void;
  handleExpandHunk: (hunkIndex: number, direction: ExpansionDirections, expansionLineCountOverride?: number) => void;
  expandHunk: (hunkIndex: number, direction: ExpansionDirections, expansionLineCountOverride?: number) => void;
  protected loadFilesIfNecessary(): void;
  private loadFilesForDiff;
  protected handleFilesLoaded(expectedDiff: FileDiffMetadata, files: LoadedPartialDiffContents): Promise<void>;
  protected setHydratedState(files: LoadedPartialDiffContents): void;
  render({
    fileDiff,
    deferManagers,
    forceRender,
    preventEmit,
    lineAnnotations,
    fileContainer,
    containerWrapper,
    renderRange,
    ...fileInputProps
  }: FileDiffRenderProps<LAnnotation>): boolean;
  protected emitPostRender(unmount?: boolean): void;
  protected get fileDiffCache(): FileDiffMetadata | undefined;
  private syncRenderViewToEditor;
  private computeEditorRenderRange;
  attachEditor(editor: DiffsEditor<LAnnotation>): (recycle?: boolean) => void;
  private finishEditSession;
  /**
   * Run the genuine session-end recompute: restore recompute-shaped hunks (a
   * context-only region collapses away, boundaries re-derive), preserve
   * expansion state best-effort via old-side anchors, and repaint through
   * the session render path — which also invalidates virtualized layout,
   * since nothing else does at exit now that editing does not flip
   * expandUnchanged. Marker-guarded and idempotent; CodeView also calls this
   * when reaping a session whose detach closure was consumed by a recycle.
   * Safe on a cleaned-up instance: the recompute is pure metadata work and
   * the deferred rerender is enabled-guarded. Returns true when a recompute
   * ran.
   */
  completeEditSession(): boolean;
  applyDocumentChange(textDocument: DiffsTextDocument, newLineAnnotations?: DiffLineAnnotation<LAnnotation>[]): void;
  updateRenderCache(dirtyLines: Map<number, Array<HighlightedToken>>, themeType: 'dark' | 'light', options?: {
    shouldRefreshDiffsView?: boolean;
    lineCountChangeInFlight?: boolean;
  }): void;
  isLineRenderable(lineNumber: number): boolean;
  getNearestRenderableLine(lineNumber: number, direction: 'up' | 'down'): number | undefined;
  revealLine(lineNumber: number): boolean;
  protected shouldSelfHealEditSession(): boolean;
  protected escalateEditSessionRender(): void;
  private handleEditSessionRender;
  private removeRenderedCode;
  private clearAuxiliaryNodes;
  renderPlaceholder(height: number): boolean;
  primeHighlightCache(fileDiff?: FileDiffMetadata | undefined): Promise<void>;
  private cleanChildNodes;
  private renderSeparators;
  protected renderAnnotations(): void;
  protected renderGutterUtility(): void;
  protected getOrCreateFileContainer(fileContainer?: HTMLElement, parentNode?: HTMLElement): HTMLElement;
  private adoptReusableShellElements;
  private ensureSpriteSVG;
  private getOrCreatePreNode;
  protected syncCodeNodesFromPre(pre: HTMLPreElement): void;
  private applyHeaderToDOM;
  private clearHeaderSlots;
  private upsertHeaderSlotElement;
  private replaceHeaderSlotContent;
  private createHeaderSlotElement;
  protected injectUnsafeCSS(): void;
  private applyThemeState;
  private hydrateMeasuredScrollbar;
  protected shouldGuardRebuildScroll(): boolean;
  private applyHunksToDOM;
  private applyCodeColumnsInPlace;
  private replaceCodeColumns;
  private applyPartialRender;
  private insertPartialHTML;
  private refreshSplitDiffView;
  private refreshUnifiedDiffView;
  private renderPartialColumn;
  private mergeBuffersIfNecessary;
  private applyRowSpan;
  private trimColumnRows;
  private trimColumns;
  private getBufferSize;
  private updateBufferSize;
  private getColumnPair;
  private getCodeColumns;
  protected updateBuffers(renderRange: RenderRange): void;
  private applyBuffers;
  protected shouldDisableVirtualizationBuffers(): boolean;
  protected applyPreNodeAttributes(pre: HTMLPreElement, {
    additionsContentAST,
    deletionsContentAST,
    totalLines
  }: HunksRenderResult, customProperties?: CustomPreProperties): void;
  private applyErrorToDOM;
  private cleanupErrorWrapper;
}
//#endregion
export { FileDiff, FileDiffHydrationProps, FileDiffOptions, FileDiffRenderBaseProps, FileDiffRenderProps, FileDiffType };
//# sourceMappingURL=FileDiff.d.ts.map