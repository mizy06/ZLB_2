import type { Token } from '../common/token.js';
import type { MarkdownIt } from '../index.js';
/**
 * Accumulates input and calls stream.parse at safe block boundaries.
 *
 * @experimental This helper is intended for append-heavy editing flows and is
 * not part of the markdown-it compatibility surface.
 */
export declare class StreamBuffer {
    private md;
    private text;
    private lastFlushedLength;
    constructor(md: MarkdownIt);
    feed(chunk: string): void;
    flushIfBoundary(): Token[] | null;
    flushForce(): Token[];
    getText(): string;
    getTokens(): Token[];
    stats(): import("./parser.js").StreamStats;
}
