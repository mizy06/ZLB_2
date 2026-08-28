/**
 * Block-level rule management with Ruler pattern
 */
import type { StateBlock } from './state_block.js';
export type BlockRuleFn = (state: StateBlock, startLine: number, endLine: number, silent: boolean) => boolean;
export interface BlockNamedRule {
    name: string;
    fn: BlockRuleFn;
}
export declare class BlockRuler {
    private _rules;
    private cache;
    private namedCache;
    version: number;
    private invalidateCache;
    push(name: string, fn: BlockRuleFn, options?: {
        alt?: string[];
    }): void;
    before(beforeName: string, name: string, fn: BlockRuleFn, options?: {
        alt?: string[];
    }): void;
    after(afterName: string, name: string, fn: BlockRuleFn, options?: {
        alt?: string[];
    }): void;
    getRules(chainName: string): BlockRuleFn[];
    getNamedRules(chainName: string): BlockNamedRule[];
    getRulesForState(state: StateBlock, chainName: string): BlockRuleFn[];
    at(name: string, fn: BlockRuleFn, options?: {
        alt?: string[];
    }): void;
    enable(names: string | string[], ignoreInvalid?: boolean): string[];
    disable(names: string | string[], ignoreInvalid?: boolean): string[];
    enableOnly(names: string[]): void;
    private compileCache;
}
export default BlockRuler;
