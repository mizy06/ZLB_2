import type { State } from '../../parse/state.js';
export type CoreRule = (state: State) => void;
export interface CoreNamedRule {
    name: string;
    fn: CoreRule;
}
export declare class CoreRuler {
    private rules;
    private cache;
    private namedCache;
    version: number;
    private invalidateCache;
    push(name: string, fn: CoreRule): void;
    at(name: string, fn: CoreRule): void;
    before(beforeName: string, name: string, fn: CoreRule): void;
    after(afterName: string, name: string, fn: CoreRule): void;
    enable(names: string | string[], ignoreInvalid?: boolean): string[];
    disable(names: string | string[], ignoreInvalid?: boolean): string[];
    enableOnly(names: string[]): void;
    private compileCache;
    getRules(_chainName?: string): CoreRule[];
    getNamedRules(_chainName?: string): CoreNamedRule[];
}
export default CoreRuler;
