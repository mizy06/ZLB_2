import type { ParseSource } from './source.js';
import { CoreRuler } from '../rules/core/ruler.js';
import { ParserBlock } from './parser_block.js';
import { ParserInline } from './parser_inline/index.js';
import { State } from './state.js';
export declare class ParserCore {
    private fallbackParser;
    private lastState;
    block: ParserBlock;
    inline: ParserInline;
    ruler: CoreRuler;
    private linkifyInstance;
    private cachedCoreRulesVersion;
    private cachedCoreRules;
    private cachedCoreNamedRulesVersion;
    private cachedCoreNamedRules;
    constructor();
    private resolveParser;
    createState(src: ParseSource, env?: Record<string, unknown>, md?: any): State;
    private getCoreRules;
    private getCoreNamedRules;
    process(state: State): void;
    parseSource(src: ParseSource, env?: Record<string, unknown>, md?: any): State;
    parse(src: string, env?: Record<string, unknown>, md?: any): State;
    getTokens(): Array<import('../types/index.js').Token>;
}
