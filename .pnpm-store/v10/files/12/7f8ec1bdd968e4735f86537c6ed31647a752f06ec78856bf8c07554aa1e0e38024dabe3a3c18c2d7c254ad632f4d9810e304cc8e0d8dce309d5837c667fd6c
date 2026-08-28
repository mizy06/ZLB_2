//#region src/editor/textMeasure.d.ts
declare class Metrics {
  #private;
  /** Width of the '0' character. */
  ch: number;
  /** Size of a tab(\t) character. */
  tabSize: number;
  /** Height of the code line. */
  lineHeight: number;
  /** Padding top of the root element. */
  paddingTop: number;
  /** initialize the metrics */
  init(root: HTMLElement): void;
  /**
   * Re-measure the '0' character width against the font that is loaded right
   * now, returning true when measurement-dependent UI should refresh.
   *
   * A custom web font can finish loading after the editor first renders.
   * Until then canvas measureText reports the fallback font's width, and
   * getComputedStyle returns the same font-family string before and after the
   * file arrives, so init()'s font guard never re-measures on its own. Call
   * this once fonts have settled (e.g. on document.fonts.ready) to replace a
   * width measured against the fallback font with the real glyph width. Font
   * completion can also change DOM-measured emoji/ZWJ widths while leaving the
   * ASCII width unchanged, and the computed font string stays the same in both
   * cases. The boolean return lets the caller skip re-rendering when there is no
   * measured state to refresh.
   */
  remeasureCharacterWidth(): boolean;
  /** measure the width of the text */
  measureTextWidth(text: string): number;
  /** measure the width of the text using the canvas measureText API */
  canvasMeasureTextWidth(text: string): number;
  /**
   * measure the width of the text using the DOM
   * this is slow because it cause a reflow, use it for non-ascii text;
   * results are memoized per text so repeated measurements skip the reflow
   */
  domMeasureTextWidth(text: string): number;
  /**
   * discard memoized DOM text widths
   * call this when the inherited font may have changed without re-running
   * init(), e.g. on a layout reflow, so stale widths are not reused
   */
  clearTextWidthCache(): void;
}
/** Check if the text needs DOM text measurement. */
declare function needsDomTextMeasurement(text: string): boolean;
/** snap the text offset to the Unicode boundary */
declare function snapTextOffsetToUnicodeBoundary(text: string, offset: number): number;
/** get the offsets of the Unicode grapheme clusters in the text */
declare function getUnicodeMeasurementOffsets(text: string): number[] | undefined;
/**
 * Count the rendered columns of ASCII text, advancing each tab to the next
 * fixed tab stop (a multiple of tabSize) to match CSS `tab-size`. Returns -1
 * for non-ASCII text, which must be measured glyph-by-glyph instead.
 */
declare function getExpandedAsciiTextColumns(text: string, tabSize: number): number;
//#endregion
export { Metrics, getExpandedAsciiTextColumns, getUnicodeMeasurementOffsets, needsDomTextMeasurement, snapTextOffsetToUnicodeBoundary };
//# sourceMappingURL=textMeasure.d.ts.map