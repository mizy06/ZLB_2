import type { ParseSource } from '../source.js';
import { Token } from '../../common/token.js';
/**
 * StateInline - state object for inline parser
 */
export declare class StateInline {
    src: ParseSource;
    md: any;
    env: any;
    tokens: Token[];
    Token: typeof Token;
    tokens_meta: any[];
    pos: number;
    posMax: number;
    level: number;
    pending: string;
    pendingLevel: number;
    cache: Array<number | undefined>;
    delimiters: any[];
    _prev_delimiters: any[];
    backticks: Record<number, number>;
    backticksScanned: boolean;
    linkLevel: number;
    linkLabelNoCloseFrom: number;
    maxNesting: number;
    constructor(src: ParseSource, md: any, env: any, outTokens: Token[]);
    /**
     * Push pending text as a text token
     */
    pushPending(): Token;
    pushSimple(type: string, tag: string): Token;
    /**
     * Push a new token to the output
     */
    push(type: string, tag: string, nesting: number): Token;
    /**
     * Scan delimiter run (for emphasis)
     */
    scanDelims(start: number, canSplitWord: boolean): {
        can_open: boolean;
        can_close: boolean;
        length: number;
    } | null;
}
export default StateInline;
