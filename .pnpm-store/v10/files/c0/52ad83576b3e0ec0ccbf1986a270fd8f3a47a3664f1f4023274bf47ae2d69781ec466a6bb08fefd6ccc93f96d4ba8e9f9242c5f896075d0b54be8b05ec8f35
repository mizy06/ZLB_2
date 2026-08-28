import type { TextSource } from '../parse/source.js';
export interface PieceTableStats {
    length: number;
    lineBreaks: number;
    pieces: number;
}
/**
 * Piece-table source storage used by editable parsing.
 *
 * @experimental This supports the experimental editable-buffer APIs and is not
 * part of the markdown-it compatibility surface.
 */
export declare class PieceTable {
    private original;
    private add;
    private pieces;
    private totalLength;
    private totalLineBreaks;
    constructor(initial?: string);
    get length(): number;
    get lineBreaks(): number;
    stats(): PieceTableStats;
    append(text: string): void;
    insert(offset: number, text: string): void;
    delete(start: number, end: number): void;
    replace(start: number, end: number, text: string): void;
    slice(start?: number, end?: number): string;
    toString(): string;
    view(start?: number, end?: number, windowSize?: number): TextSource;
    iterateChunks(chunkSize?: number): Iterable<string>;
    iterateRangeChunks(start?: number, end?: number, chunkSize?: number): Iterable<string>;
    lineOfOffset(offset: number): number;
    offsetOfLine(line: number): number;
    private getBuffer;
    private makePiece;
    private splitAt;
    private mergeAdjacentAround;
}
/**
 * TextSource view over a PieceTable range.
 *
 * @experimental This supports the experimental editable-buffer APIs and is not
 * part of the markdown-it compatibility surface.
 */
export declare class PieceTableSourceView implements TextSource {
    private readonly startOffset;
    private readonly endOffset;
    private readonly cacheSize;
    private cachedStart;
    private cachedEnd;
    private cachedText;
    constructor(table: PieceTable, start?: number, end?: number, windowSize?: number);
    private readonly table;
    get length(): number;
    charAt(index: number): string;
    charCodeAt(index: number): number;
    slice(start?: number, end?: number): string;
    indexOf(searchValue: string, fromIndex?: number): number;
    includes(searchValue: string, fromIndex?: number): boolean;
    toString(): string;
    private ensureWindow;
}
