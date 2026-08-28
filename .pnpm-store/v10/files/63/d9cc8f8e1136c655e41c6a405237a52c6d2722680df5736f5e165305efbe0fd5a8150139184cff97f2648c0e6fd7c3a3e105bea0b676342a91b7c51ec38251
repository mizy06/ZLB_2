/**
 * StateBlock - Parser state class for block-level parsing
 */
import type { ParseSource } from '../source.js';
import { Token } from '../../common/token.js';
export declare const LineFlag: {
    readonly Pipe: 1;
    readonly ParagraphTerminator: 2;
};
export declare class StateBlock {
    src: ParseSource;
    md: any;
    env: any;
    tokens: Token[];
    Token: typeof Token;
    bMarks: number[];
    eMarks: number[];
    tShift: number[];
    sCount: number[];
    bsCount: number[];
    lineFlags: number[];
    blkIndent: number;
    line: number;
    lineMax: number;
    tight: boolean;
    ddIndent: number;
    listIndent: number;
    parentType: string;
    level: number;
    constructor(src: ParseSource, md: any, env: any, tokens: Token[]);
    push(type: string, tag: string, nesting: number): Token;
    isEmpty(line: number): boolean;
    skipEmptyLines(from: number): number;
    skipSpaces(pos: number): number;
    skipSpacesBack(pos: number, min: number): number;
    skipChars(pos: number, code: number): number;
    skipCharsBack(pos: number, code: number, min: number): number;
    getLines(begin: number, end: number, indent: number, keepLastLF: boolean): string;
}
export default StateBlock;
