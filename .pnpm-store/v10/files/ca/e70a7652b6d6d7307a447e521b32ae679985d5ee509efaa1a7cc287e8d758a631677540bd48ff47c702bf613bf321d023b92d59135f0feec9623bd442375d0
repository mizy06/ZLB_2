import type { Token } from '../common/token.js';
import type { MarkdownIt } from '../index.js';
export interface ChunkedOptions {
    maxChunkChars?: number;
    maxChunkLines?: number;
    fenceAware?: boolean;
    maxChunks?: number;
    fallbackOnGlobalState?: boolean;
}
export interface ChunkRange {
    start: number;
    end: number;
    lineCount: number;
}
type ChunkSplitOptions = Required<Omit<ChunkedOptions, 'maxChunks' | 'fallbackOnGlobalState'>> & {
    maxChunks?: number;
};
/**
 * Chunk a markdown document on reasonably safe boundaries (blank-line separated)
 * and parse each chunk separately, then merge token streams with line map offsets.
 *
 * @experimental Markdown is not always chunk-local. The default path falls back
 * to a full parse for known document-level state and unsafe chunk boundaries;
 * disabling those fallbacks can produce output that differs from full parsing.
 */
export declare function chunkedParse(md: MarkdownIt, src: string, env?: Record<string, unknown>, opts?: ChunkedOptions): Token[];
/**
 * Split text into chunks by blank lines without breaking fenced code blocks.
 * Keeps chunk sizes under maxChunkChars/maxChunkLines where possible.
 */
export declare function splitIntoChunks(src: string, opts: ChunkSplitOptions): string[];
export declare function splitIntoChunkRanges(src: string, opts: ChunkSplitOptions, final?: boolean): ChunkRange[];
export declare function hasUnsafeChunkBoundary(src: string, ranges: ChunkRange[], options?: {
    rangesCoverWholeSource: boolean;
}): boolean;
export {};
