//#region src/editor/popover.d.ts
declare const POPOVER_BOUNDARY_LINES = 3;
declare const POPOVER_FLIP_HYSTERESIS_PX = 4;
/**
 * The visible scroll viewport expressed in the overlay's coordinate space (the
 * same space --popover-y uses), or undefined when no usable layout geometry
 * exists (e.g. a detached unit-test DOM, where every rect is zero).
 */
interface PopoverPlacementBounds {
  /** The top of the popover in overlay coordinate space. */
  top: number;
  /** The bottom of the popover in overlay coordinate space. */
  bottom: number;
}
interface PopoverViewportBounds extends PopoverPlacementBounds {
  /** The left edge of the visible viewport in overlay coordinate space. */
  left: number;
  /** The right edge of the visible viewport in overlay coordinate space. */
  right: number;
}
interface PopoverManagerOptions {
  hasActivePopover: () => boolean;
  updateActivePopover: () => void;
}
/**
 * Shared placement logic for the editor's overlay popovers: each anchors below
 * or above a document position, flipping to the opposite side only when the
 * preferred side would be clipped by the visible scrollport.
 */
declare class PopoverManager {
  #private;
  constructor(options: PopoverManagerOptions);
  setViewportElements(fileContainer: HTMLElement, codeElement: HTMLElement): void;
  cleanUp(): void;
  resetPlacement(placementKey?: string): void;
  setPlacement(placement: 'preferred' | 'fallback', placementKey?: string): void;
  choosePlacement(input: {
    /** Bounds for the anchor's preferred side (e.g. above for backward, below for forward). */preferred: PopoverPlacementBounds; /** Bounds for the opposite edge we flip to when the preferred side has no room. */
    fallback: PopoverPlacementBounds; /** The visible scrollport in overlay coordinate space, or undefined without layout geometry (e.g. a detached test DOM). */
    viewport: PopoverPlacementBounds | undefined; /** The popover's measured height; 0 before it has laid out. */
    popoverHeight: number; /** Whether the anchor is within the document's first/last rows; only used as a fallback signal when `viewport` is unavailable. */
    atDocumentEdge: boolean; /** Keeps hysteresis independent when more than one popover kind is active. */
    placementKey?: string;
  }): 'preferred' | 'fallback';
  /**
   * Returns the bounds of the popover in overlay coordinate space.
   */
  getPlacementBounds(): PopoverViewportBounds | undefined;
}
declare function setPopoverPositionStyles(popover: HTMLElement, {
  gutterWidth,
  placeAbove,
  viewport,
  x,
  y
}: {
  gutterWidth: number;
  placeAbove: boolean;
  viewport: PopoverViewportBounds | undefined;
  x: number;
  y: number;
}): void;
//#endregion
export { POPOVER_BOUNDARY_LINES, POPOVER_FLIP_HYSTERESIS_PX, PopoverManager, PopoverManagerOptions, PopoverPlacementBounds, PopoverViewportBounds, setPopoverPositionStyles };
//# sourceMappingURL=popover.d.ts.map