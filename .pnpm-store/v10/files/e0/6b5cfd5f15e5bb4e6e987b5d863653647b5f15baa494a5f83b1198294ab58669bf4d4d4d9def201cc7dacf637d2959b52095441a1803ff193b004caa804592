import type { Token } from '../../types/index.js';
import type { ParseSource } from '../source.js';
import { InlineRuler } from './ruler.js';
import { StateInline } from './state_inline.js';
export declare function isPlainInlineText(src: string): boolean;
export declare class ParserInline {
    ruler: InlineRuler;
    ruler2: InlineRuler;
    private cachedRulesVersion;
    private cachedRules;
    private cachedRules2Version;
    private cachedRules2;
    private readonly defaultRulerVersion;
    private readonly defaultRuler2Version;
    constructor();
    /**
     * Skip single token by running all rules in validation mode
     */
    skipToken(state: StateInline): void;
    /**
     * Generate tokens for input string
     */
    tokenize(state: StateInline): void;
    /**
     * ParserInline.parse(str, md, env, outTokens)
     *
     * Process input string and push inline tokens into `outTokens`.
     * Matches the signature from original markdown-it/lib/parser_inline.mjs
     */
    isDefaultRuleset(): boolean;
    parseSource(src: ParseSource, md: any, env: any, outTokens: Token[]): void;
    parse(str: string, md: any, env: any, outTokens: Token[]): void;
    private getRules;
    private getRules2;
}
export default ParserInline;
