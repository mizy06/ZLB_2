import type { Token } from '../common/token.js';
import type { MarkdownIt } from '../index.js';
import type { ParserCore } from '../parse/parser_core.js';
/**
 * StreamParser provides a lightweight incremental parsing layer that can reuse
 * tokens when the incoming markdown string is an append-only update. It falls
 * back to full parsing in all other scenarios to preserve correctness.
 */
export declare class StreamParser {
    private core;
    private cache;
    constructor(core: ParserCore);
    reset(): void;
    parse(src: string, env: Record<string, unknown> | undefined, md: MarkdownIt): Token[];
    private getAppendedSegment;
}
export default StreamParser;
