import type { Token } from '../common/token.js';
import type { MarkdownIt } from '../index.js';
export interface EditableBufferStats {
    edits: number;
    fullParses: number;
    localizedParses: number;
    sourceChars: number;
    sourceLineBreaks: number;
    lastMode: 'idle' | 'full' | 'localized';
    lastAnchorLine: number;
    lastAnchorTokenStart: number;
    lastReparsedChars: number;
    pieceCount: number;
}
/**
 * Piece-table backed buffer for repeated edits.
 *
 * @experimental Localized reparsing has markdown-specific correctness limits
 * and falls back to full parsing when document-level state makes that necessary.
 */
export declare class EditableBuffer {
    private readonly md;
    private source;
    private tokens;
    private statsState;
    private globalStateReason;
    private staleGlobalStateReason;
    constructor(md: MarkdownIt, initial?: string);
    length(): number;
    slice(start?: number, end?: number): string;
    toString(): string;
    peek(): Token[];
    stats(): EditableBufferStats;
    reset(text?: string): void;
    parse(env?: Record<string, unknown>): Token[];
    append(text: string, env?: Record<string, unknown>): Token[];
    insert(offset: number, text: string, env?: Record<string, unknown>): Token[];
    delete(start: number, end: number, env?: Record<string, unknown>): Token[];
    replace(start: number, end: number, text: string, env?: Record<string, unknown>): Token[];
    private detectSourceGlobalState;
    private fullParse;
    private localizedReparse;
    private findAnchorForEditLine;
    private collectTopLevelSegments;
}
