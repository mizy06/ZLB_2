/**
 * InlineRuler - manages inline parsing rules
 * Similar to original markdown-it/lib/ruler.mjs but for inline rules
 */
import type { StateInline } from './state_inline.js';
export type InlineRuleFn = (state: StateInline, silent?: boolean) => boolean | void;
export interface InlineRule {
    name: string;
    fn: InlineRuleFn;
    alt?: string[];
    enabled: boolean;
}
export type InlineRuleSnapshot = Readonly<{
    name: string;
    fn: InlineRuleFn;
    alt?: readonly string[];
    enabled: boolean;
}>;
export interface InlineNamedRule {
    name: string;
    fn: InlineRuleFn;
}
export declare class InlineRuler {
    private rules;
    private cache;
    private namedCache;
    version: number;
    private invalidateCache;
    /**
     * Push new rule to the end of chain
     */
    push(name: string, fn: InlineRuleFn, options?: {
        alt?: string[];
    }): void;
    at(name: string): InlineRuleSnapshot | undefined;
    at(name: string, fn: InlineRuleFn, options?: {
        alt?: string[];
    }): void;
    before(beforeName: string, name: string, fn: InlineRuleFn, options?: {
        alt?: string[];
    }): void;
    after(afterName: string, name: string, fn: InlineRuleFn, options?: {
        alt?: string[];
    }): void;
    enable(names: string | string[], ignoreInvalid?: boolean): string[];
    disable(names: string | string[], ignoreInvalid?: boolean): string[];
    enableOnly(names: string[]): void;
    /**
     * Get rules for specified chain name (or empty string for default)
     */
    getRules(chainName: string): InlineRuleFn[];
    getNamedRules(chainName: string): InlineNamedRule[];
    private compileCache;
}
export default InlineRuler;
