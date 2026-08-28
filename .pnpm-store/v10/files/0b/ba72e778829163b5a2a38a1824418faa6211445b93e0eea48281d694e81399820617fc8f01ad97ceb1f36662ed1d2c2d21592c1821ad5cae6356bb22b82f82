import type { Token } from '../common/token.js';
import type { MarkdownIt } from '../index.js';
/**
 * Debounced stream parser wrapper for real-time editing scenarios.
 *
 * When user types character-by-character, it's inefficient to parse on every keystroke.
 * This wrapper debounces parse calls to balance responsiveness and performance.
 *
 * @example
 * ```typescript
 * const md = MarkdownIt({ stream: true })
 * const debouncedParser = new DebouncedStreamParser(md, 100) // 100ms debounce
 *
 * editor.on('change', (text) => {
 *   debouncedParser.parse(text, (tokens) => {
 *     // Render tokens
 *     renderMarkdown(tokens)
 *   })
 * })
 * ```
 */
export declare class DebouncedStreamParser {
    private md;
    private debounceMs;
    private timeoutId;
    private pendingCallback;
    private lastText;
    private lastTokens;
    /**
     * @param md - MarkdownIt instance with stream enabled
     * @param debounceMs - Milliseconds to wait before parsing (default: 150ms)
     */
    constructor(md: MarkdownIt, debounceMs?: number);
    /**
     * Parse text with debouncing. Callback is called with the parsed tokens.
     *
     * @param text - Markdown text to parse
     * @param callback - Called with tokens when parsing completes
     * @param immediate - If true, parse immediately without debouncing
     */
    parse(text: string, callback: (tokens: Token[]) => void, immediate?: boolean): void;
    /**
     * Cancel any pending parse operation
     */
    cancel(): void;
    /**
     * Force immediate parse, bypassing debounce
     */
    flush(text: string): Token[];
    /**
     * Reset the parser state
     */
    reset(): void;
    private executeParse;
    /**
     * Get parser statistics
     */
    getStats(): import("./parser.js").StreamStats;
}
/**
 * Throttled stream parser wrapper - limits parse frequency.
 * Unlike debouncing, throttling ensures parsing happens at regular intervals
 * even during continuous typing.
 *
 * @example
 * ```typescript
 * const md = MarkdownIt({ stream: true })
 * const throttledParser = new ThrottledStreamParser(md, 200) // Parse at most every 200ms
 *
 * editor.on('change', (text) => {
 *   throttledParser.parse(text, (tokens) => {
 *     renderMarkdown(tokens)
 *   })
 * })
 * ```
 */
export declare class ThrottledStreamParser {
    private md;
    private throttleMs;
    private lastParseTime;
    private timeoutId;
    private pendingText;
    private pendingCallback;
    private lastTokens;
    constructor(md: MarkdownIt, throttleMs?: number);
    parse(text: string, callback: (tokens: Token[]) => void): void;
    cancel(): void;
    reset(): void;
    private executeParse;
    getStats(): import("./parser.js").StreamStats;
}
