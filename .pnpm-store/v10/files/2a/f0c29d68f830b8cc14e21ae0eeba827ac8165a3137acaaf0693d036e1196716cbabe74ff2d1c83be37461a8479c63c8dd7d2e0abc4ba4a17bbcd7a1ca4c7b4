//#region src/utils/computeFileOffsets.d.ts
/**
 * Computes line start offsets for a string.
 */
declare function computeLineOffsets(contents: string): number[];
/**
 * Counts line breaks in a string, treating `\n`, `\r`, and `\r\n` the same way
 * {@link computeLineOffsets} does (a `\r\n` pair is one break). Mirrors that
 * scan but counts in a single pass instead of building and discarding an
 * offsets array, so sizing the changed-line range for large edits stays cheap.
 * A unit test asserts it stays in lockstep with `computeLineOffsets`.
 */
declare function countLineBreaks(contents: string): number;
/**
 * Splits file contents into lines aligned with {@link computeLineOffsets}.
 * Unlike splitFileContents, a trailing newline produces a final empty line.
 */
declare function linesFromFileContents(contents: string): string[];
//#endregion
export { computeLineOffsets, countLineBreaks, linesFromFileContents };
//# sourceMappingURL=computeFileOffsets.d.ts.map