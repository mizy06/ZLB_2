/**
 * ParserBlock
 *
 * Block-level tokenizer.
 */
import type { Token } from '../types/index.js';
import type { ParseSource } from './source.js';
import { BlockRuler } from './parser_block/ruler.js';
import { StateBlock } from './parser_block/state_block.js';
export declare class ParserBlock {
    ruler: BlockRuler;
    private cachedRulesVersion;
    private cachedRules;
    constructor();
    /**
     * Generate tokens for input range
     */
    tokenize(state: StateBlock, startLine: number, endLine: number): void;
    /**
     * ParserBlock.parse(src, md, env, outTokens)
     *
     * Process input string and push block tokens into `outTokens`
     */
    parse(src: ParseSource, md: any, env: any, outTokens: Token[]): void;
    private getRules;
}
