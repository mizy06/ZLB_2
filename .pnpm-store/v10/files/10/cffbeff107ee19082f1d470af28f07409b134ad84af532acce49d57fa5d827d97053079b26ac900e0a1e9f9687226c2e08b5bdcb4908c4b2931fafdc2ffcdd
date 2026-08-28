import { VirtualWindowSpecs } from "../types.js";

//#region src/components/Virtualizer.d.ts
interface SubscribedInstance {
  onRender(dirty: boolean): boolean;
  reconcileHeights(): boolean;
  setVisibility(visible: boolean): void;
}
interface VirtualizerConfig {
  /** Extra pixels rendered above and below the viewport to reduce blanking during fast scrolls. */
  overscrollSize: number;
  /** Margin used by IntersectionObserver to decide when items should be considered visible. */
  intersectionObserverMargin: number;
  /** Enables noisy resize logs to help tune metrics and investigate scroll jitter. */
  resizeDebugging: boolean;
}
interface VirtualizerScrollOptions {
  top: number;
  behavior?: ScrollBehavior;
}
declare class Virtualizer {
  static __STOP: boolean;
  static __lastScrollPosition: number;
  readonly __id: string;
  readonly config: VirtualizerConfig;
  type: 'simple';
  private intersectionObserver;
  private scrollTop;
  private height;
  private scrollHeight;
  private windowSpecs;
  private root;
  private contentContainer;
  private resizeObserver;
  private observers;
  private visibleInstances;
  private visibleInstancesDirty;
  private instancesChanged;
  private reconcileQueue;
  private scrollDirty;
  private heightDirty;
  private scrollHeightDirty;
  private renderedObservers;
  private connectQueue;
  constructor(config?: Partial<VirtualizerConfig>);
  setup(root: HTMLElement | Document, contentContainer?: Element): void;
  instanceChanged(instance: SubscribedInstance, domDirty: boolean): void;
  requestHeightReconcile(instance: SubscribedInstance): void;
  getWindowSpecs(): VirtualWindowSpecs;
  getRoot(): HTMLElement | Document | undefined;
  isInstanceVisible(elementTop: number, elementHeight: number): boolean;
  private handleContainerResize;
  private setupWindow;
  private setupElement;
  cleanUp(): void;
  getOffsetInScrollContainer(element: HTMLElement): number;
  connect(container: HTMLElement, instance: SubscribedInstance): () => void;
  disconnect(container: HTMLElement): void;
  private handleWindowResize;
  private handleWindowScroll;
  private handleElementScroll;
  private computeRenderRangeAndEmit;
  private scrollFix;
  private applyScrollFix;
  private getScrollAnchor;
  private handleIntersectionChange;
  /** Return the logical vertical position for the scroll container */
  getScrollTop(): number;
  /** Scroll to a logical vertical position and queue the normal render pass. */
  scrollTo({
    top,
    behavior
  }: VirtualizerScrollOptions): void;
  private clampScrollTop;
  private getScrollHeight;
  private getHeight;
  markDOMDirty(): void;
  private getScrollContainerElement;
}
//#endregion
export { Virtualizer, VirtualizerConfig, VirtualizerScrollOptions };
//# sourceMappingURL=Virtualizer.d.ts.map