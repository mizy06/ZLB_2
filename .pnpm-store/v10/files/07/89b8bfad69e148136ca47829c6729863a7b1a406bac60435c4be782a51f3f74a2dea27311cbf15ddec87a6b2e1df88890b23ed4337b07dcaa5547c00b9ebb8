import type { Token } from '../common/token.js';
import type { MarkdownIt } from '../index.js';
export interface UnboundedBufferOptions {
    mode?: 'full' | 'stream';
    maxChunkChars?: number;
    maxChunkLines?: number;
    fenceAware?: boolean;
    autoTune?: boolean;
    retainTokens?: boolean;
    onChunkTokens?: UnboundedTokenConsumer;
}
export interface ParseStringUnboundedOptions extends Omit<UnboundedBufferOptions, 'retainTokens' | 'onChunkTokens'> {
    fallbackOnGlobalState?: boolean;
}
export interface UnboundedBufferStats {
    mode: 'full' | 'stream';
    fedChunks: number;
    parsedChunks: number;
    committedChars: number;
    committedLines: number;
    pendingChars: number;
    pendingLines: number;
    retainedTokens: boolean;
}
export interface UnboundedChunkInfo {
    chunkIndex: number;
    chunkChars: number;
    chunkLines: number;
    tokenCount: number;
    startOffset: number;
    endOffset: number;
    startLine: number;
    endLine: number;
}
export type UnboundedTokenConsumer = (tokens: Token[], info: UnboundedChunkInfo) => void;
export type AutoUnboundedDecision = 'yes' | 'need-lines' | 'no';
/**
 * Append-only parser for sources that already arrive as chunks.
 *
 * @experimental Streaming output can be committed before future document-level
 * definitions are known. Use full-string parsing when exact full-parse parity
 * matters for references, footnotes, abbreviations, or plugin global state.
 */
export declare class UnboundedBuffer {
    private readonly md;
    private readonly options;
    private pending;
    private tokens;
    private committedChars;
    private committedLines;
    private fedChunks;
    private parsedChunks;
    private globalStateEnv;
    private markedGlobalStateReason;
    constructor(md: MarkdownIt, opts?: UnboundedBufferOptions);
    feed(chunk: string): void;
    flushAvailable(env?: Record<string, unknown>): Token[] | null;
    flushIfBoundary(env?: Record<string, unknown>): Token[] | null;
    flushForce(env?: Record<string, unknown>): Token[];
    reset(): void;
    peek(): Token[];
    pendingText(): string;
    stats(): UnboundedBufferStats;
    private resolveWindow;
    private prepareGlobalStateEnv;
    private commitRanges;
    private updateEnvDiagnostics;
}
/**
 * Parse an iterable chunk source without first joining all chunks.
 *
 * @experimental This is for explicit chunk-stream inputs. It may flush earlier
 * chunks before later document-level definitions are observed.
 */
export declare function parseIterable(md: MarkdownIt, chunks: Iterable<string>, env?: Record<string, unknown>, opts?: UnboundedBufferOptions): Token[];
/**
 * Parse an async iterable chunk source without first joining all chunks.
 *
 * @experimental This is for explicit chunk-stream inputs. It may flush earlier
 * chunks before later document-level definitions are observed.
 */
export declare function parseAsyncIterable(md: MarkdownIt, chunks: AsyncIterable<string>, env?: Record<string, unknown>, opts?: UnboundedBufferOptions): Promise<Token[]>;
/**
 * Parse iterable chunks and deliver token chunks to a sink.
 *
 * @experimental Sink output is streaming-oriented and can differ from a final
 * full parse when future document-level definitions affect earlier text.
 */
export declare function parseIterableToSink(md: MarkdownIt, chunks: Iterable<string>, onChunkTokens: UnboundedTokenConsumer, env?: Record<string, unknown>, opts?: Omit<UnboundedBufferOptions, 'retainTokens' | 'onChunkTokens'>): UnboundedBufferStats;
/**
 * Parse async iterable chunks and deliver token chunks to a sink.
 *
 * @experimental Sink output is streaming-oriented and can differ from a final
 * full parse when future document-level definitions affect earlier text.
 */
export declare function parseAsyncIterableToSink(md: MarkdownIt, chunks: AsyncIterable<string>, onChunkTokens: UnboundedTokenConsumer, env?: Record<string, unknown>, opts?: Omit<UnboundedBufferOptions, 'retainTokens' | 'onChunkTokens'>): Promise<UnboundedBufferStats>;
export declare function shouldAutoUseUnbounded(md: MarkdownIt, totalChars: number, totalLines: number): boolean;
export declare function getAutoUnboundedDecision(md: MarkdownIt, totalChars: number, totalLines?: number): AutoUnboundedDecision;
/**
 * Parse a complete string through the unbounded chunking path.
 *
 * @experimental Defaults to correctness-first fallback for known global-state
 * constructs. Disabling the fallback is performance-oriented and can diverge
 * from normal full parsing.
 */
export declare function parseStringUnbounded(md: MarkdownIt, src: string, env?: Record<string, unknown>, opts?: ParseStringUnboundedOptions): Token[];
