import { Element, ElementContent, Properties } from "../node_modules/.pnpm/@types_hast@3.0.4/node_modules/@types/hast/index.js";
import { BaseCodeOptions, BaseDiffOptions, BaseDiffOptionsWithDefaults, CustomPreProperties, DiffLineAnnotation, DiffsHighlighter, DiffsTextDocument, ExpansionDirections, FileDiffMetadata, FileHeaderRenderMode, HighlightedToken, HunkData, HunkExpansionRegion, LineTypes, RenderDiffOptions, RenderRange, ThemedDiffResult } from "../types.js";
import { WorkerPoolManager } from "../worker/WorkerPoolManager.js";
import { DiffLineMetadata } from "../utils/iterateOverDiff.js";

//#region src/renderers/DiffHunksRenderer.d.ts
interface DiffHunksRendererOptions extends BaseDiffOptions {
  headerRenderMode?: FileHeaderRenderMode;
}
interface DiffHunksRendererOptionsWithDefaults extends Omit<BaseDiffOptionsWithDefaults, 'themeType'> {
  headerRenderMode: FileHeaderRenderMode;
}
interface UnifiedLineDecorationProps {
  type: 'context' | 'context-expanded' | 'change';
  lineType: LineTypes;
  additionLineIndex: number | undefined;
  deletionLineIndex: number | undefined;
}
interface SplitLineDecorationProps {
  side: 'deletions' | 'additions';
  type: 'context' | 'context-expanded' | 'change';
  lineIndex: number | undefined;
}
interface LineDecoration {
  gutterLineType: LineTypes;
  gutterProperties?: Properties;
  contentProperties?: Properties;
}
interface RenderedLineContext {
  type: 'context' | 'context-expanded' | 'change';
  hunkIndex: number;
  lineIndex: number;
  unifiedLineIndex: number;
  splitLineIndex: number;
  deletionLine?: DiffLineMetadata;
  additionLine?: DiffLineMetadata;
}
interface InjectedRow {
  content: Element;
  gutter: Element;
}
interface SplitInjectedRow {
  deletion: InjectedRow | undefined;
  addition: InjectedRow | undefined;
}
interface UnifiedInjectedRowPlacement {
  before?: InjectedRow[];
  after?: InjectedRow[];
}
interface SplitInjectedRowPlacement {
  before?: SplitInjectedRow[];
  after?: SplitInjectedRow[];
}
interface HunksRenderResult {
  unifiedGutterAST: ElementContent[] | undefined;
  unifiedContentAST: ElementContent[] | undefined;
  deletionsGutterAST: ElementContent[] | undefined;
  deletionsContentAST: ElementContent[] | undefined;
  additionsGutterAST: ElementContent[] | undefined;
  additionsContentAST: ElementContent[] | undefined;
  hunkData: HunkData[];
  css: string;
  preNode: Element;
  headerElement: Element | undefined;
  totalLines: number;
  themeStyles: string;
  baseThemeType: 'light' | 'dark' | undefined;
  rowCount: number;
  bufferBefore: number;
  bufferAfter: number;
}
declare class DiffHunksRenderer<LAnnotation = undefined> {
  options: DiffHunksRendererOptions;
  private onRenderUpdate?;
  private workerManager?;
  readonly __id: string;
  private highlighter;
  private diff;
  private expandedHunks;
  private deletionAnnotations;
  private additionAnnotations;
  private computedLang;
  private renderCache;
  private editSessionActive;
  constructor(options?: DiffHunksRendererOptions, onRenderUpdate?: (() => unknown) | undefined, workerManager?: WorkerPoolManager | undefined);
  cleanUp(): void;
  recycle(): void;
  /**
   * Enter edit-session mode: hunk updates preserve the current region
   * skeleton instead of recomputing hunks, and rendering happens locally
   * with the token transformer forced on (worker-pool requests/results are
   * suspended for this renderer). An empty additions document gets one row so
   * the editor has a line for its caret. Called on every editor attach,
   * including a re-attach after recycle.
   */
  beginEditSession(): void;
  /** Leave edit-session mode. The exit recompute is the host's concern. */
  endEditSession(): void;
  /**
   * Ensures that the DOM is compatible with editor render updates
   */
  editorRenderReady(): boolean;
  /**
   * Re-highlights the current diff in the background and swaps the fresh
   * result in (with a re-render) once it completes. Needed after an edit
   * session's exit recompute: session passes plain-fill shifted lines in the
   * cached result, and the recompute mutates the diff in place (same object,
   * same cacheKey), so identity/cacheKey checks would otherwise treat the
   * stale highlight as current forever. The current result — content-correct,
   * mostly highlighted — keeps rendering until the fresh one lands, so no
   * interim paint drops highlighting.
   */
  refreshHighlightedResult(): Promise<void>;
  private applyRefreshedResult;
  get diffCache(): FileDiffMetadata | undefined;
  clearRenderCache(): void;
  setOptions(options: DiffHunksRendererOptions): void;
  mergeOptions(options: Partial<DiffHunksRendererOptions>): void;
  expandHunk(index: number, direction: ExpansionDirections, expansionLineCount?: number): void;
  getExpandedHunk(hunkIndex: number): HunkExpansionRegion;
  getExpandedHunksMap(): Map<number, HunkExpansionRegion>;
  /** Replace the whole expansion map (session-exit expansion remapping). */
  setExpandedHunksMap(expandedHunks: Map<number, HunkExpansionRegion>): void;
  setLineAnnotations(lineAnnotations: DiffLineAnnotation<LAnnotation>[]): void;
  /**
   * Returns true when a session-mode pass changed the region skeleton itself
   * (a gap edit synthesized or merged regions), which changes the rendered
   * row set without a line-count change — the host must escalate to a full
   * re-render instead of its cheap refresh path.
   */
  updateRenderCache(dirtyLines: Map<number, Array<HighlightedToken>>, themeType: 'dark' | 'light', lineCountChangeInFlight?: boolean): boolean;
  private applyExpansionRemap;
  applyDocumentChange(textDocument: DiffsTextDocument): void;
  private applySessionDocumentChange;
  private markEditSessionPass;
  protected getUnifiedLineDecoration({
    lineType
  }: UnifiedLineDecorationProps): LineDecoration;
  protected getSplitLineDecoration({
    side,
    type
  }: SplitLineDecorationProps): LineDecoration;
  private createAnnotationElement;
  protected getUnifiedInjectedRowsForLine?: (ctx: RenderedLineContext) => UnifiedInjectedRowPlacement | undefined;
  protected getSplitInjectedRowsForLine?: (ctx: RenderedLineContext) => SplitInjectedRowPlacement | undefined;
  protected getOptionsWithDefaults(): DiffHunksRendererOptionsWithDefaults;
  initializeHighlighter(): Promise<DiffsHighlighter>;
  hydrate(diff: FileDiffMetadata | undefined): void;
  private getLocalHighlightTheme;
  getEffectiveCodeOptions(): Pick<BaseCodeOptions, 'theme' | 'tokenizeMaxLineLength'>;
  private getRenderOptions;
  renderDiff(diff?: FileDiffMetadata | undefined, renderRange?: RenderRange): HunksRenderResult | undefined;
  asyncRender(diff: FileDiffMetadata, renderRange?: RenderRange): Promise<HunksRenderResult>;
  protected createPreElement(split: boolean, totalLines: number, customProperties?: CustomPreProperties): Element;
  private asyncHighlight;
  private renderDiffWithHighlighter;
  onHighlightSuccess(diff: FileDiffMetadata, result: ThemedDiffResult, options: RenderDiffOptions, highlighted?: boolean): void;
  private applyHighlightResult;
  private getMatchingWorkerResultCache;
  private hasHighlightedRenderCache;
  onHighlightError(error: unknown): void;
  private getTokenizeMaxLength;
  private processDiffResult;
  renderCodeAST(type: 'unified' | 'deletions' | 'additions', result: HunksRenderResult): ElementContent[] | undefined;
  renderFullAST(result: HunksRenderResult, children?: ElementContent[]): Element;
  renderFullHTML(result: HunksRenderResult, tempChildren?: ElementContent[]): string;
  renderPartialHTML(children: ElementContent[], columnType?: 'unified' | 'deletions' | 'additions'): string;
  private pushFileLevelAnnotations;
  private getAnnotations;
  private renderHeader;
}
//#endregion
export { DiffHunksRenderer, DiffHunksRendererOptions, DiffHunksRendererOptionsWithDefaults, HunksRenderResult, InjectedRow, LineDecoration, RenderedLineContext, SplitInjectedRow, SplitInjectedRowPlacement, SplitLineDecorationProps, UnifiedInjectedRowPlacement, UnifiedLineDecorationProps };
//# sourceMappingURL=DiffHunksRenderer.d.ts.map