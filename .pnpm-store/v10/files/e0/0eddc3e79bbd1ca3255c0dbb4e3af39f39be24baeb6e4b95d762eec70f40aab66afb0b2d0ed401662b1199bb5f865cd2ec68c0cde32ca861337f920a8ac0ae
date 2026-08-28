import type { ParseSource } from './source.js';
import { Token } from '../common/token.js';
export interface MarkdownItOptions {
    html?: boolean;
    xhtmlOut?: boolean;
    breaks?: boolean;
    langPrefix?: string;
    linkify?: boolean;
    typographer?: boolean;
    quotes?: string;
    maxNesting?: number;
}
export declare class State {
    src: ParseSource;
    env: Record<string, unknown>;
    tokens: Token[];
    inlineMode: boolean;
    md: any;
    Token: typeof Token;
    constructor(src: ParseSource, md: any, env?: Record<string, unknown>);
}
export default State;
