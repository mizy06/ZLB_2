import { Range } from "../types.js";
import { TextDocument } from "./textDocument.js";
import { PopoverManager } from "./popover.js";

//#region src/editor/marker.d.ts
type MarkerSeverity = 'error' | 'warning' | 'info' | 'hint';
interface Marker extends Range {
  severity: MarkerSeverity;
  message: string | {
    html: string;
  } | HTMLElement;
  source?: string;
  metadata?: Record<string, unknown>;
}
interface MarkerRenderOptions {
  popoverManager: PopoverManager;
  getLineHeight: () => number;
  getOverlayElement: () => HTMLElement | undefined;
  getGutterWidth: () => number;
  getCharX: (line: number, character: number) => [number, number];
  getLineY: (line: number) => number;
  isMouseDown: () => boolean;
}
declare class MarkerRenderer {
  #private;
  constructor(editor: MarkerRenderOptions);
  get markers(): readonly Marker[];
  isPopoverVisible(): boolean;
  updatePopoverPosition(): void;
  setMarkers<LAnnotation>(markers: Marker[], textDocument: TextDocument<LAnnotation>): void;
  listenHover(contentEl: HTMLElement): void;
  removePopover(): void;
  cleanup(): void;
}
declare function markerSeverityDatasetKey(severity: MarkerSeverity): string;
//#endregion
export { Marker, MarkerRenderOptions, MarkerRenderer, MarkerSeverity, markerSeverityDatasetKey };
//# sourceMappingURL=marker.d.ts.map