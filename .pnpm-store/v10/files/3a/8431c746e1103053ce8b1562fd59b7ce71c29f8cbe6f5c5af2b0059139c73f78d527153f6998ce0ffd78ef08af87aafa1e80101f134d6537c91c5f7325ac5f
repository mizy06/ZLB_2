import type { Token } from '../common/token.js';
export interface RendererOptions {
    langPrefix?: string;
    highlight?: ((str: string, lang: string, attrs: string) => string | Promise<string>) | null;
    xhtmlOut?: boolean;
    breaks?: boolean;
}
export type RendererEnv = Record<string, unknown>;
export type RendererRuleResult = string | Promise<string>;
export type RendererRule = (tokens: Token[], idx: number, options: RendererOptions, env: RendererEnv, self: Renderer) => RendererRuleResult;
export declare class Renderer {
    readonly rules: Record<string, RendererRule>;
    private baseOptions;
    private normalizedBase;
    constructor(options?: RendererOptions);
    set(options: RendererOptions): this;
    render(tokens: Token[], options?: RendererOptions, env?: RendererEnv): string;
    renderAsync(tokens: Token[], options?: RendererOptions, env?: RendererEnv): Promise<string>;
    renderInline(tokens: Token[], options?: RendererOptions, env?: RendererEnv): string;
    renderInlineAsync(tokens: Token[], options?: RendererOptions, env?: RendererEnv): Promise<string>;
    renderInlineAsText(tokens: Token[], options?: RendererOptions, env?: RendererEnv): string;
    renderAttrs(token: Token): string;
    renderToken(tokens: Token[], idx: number, options: RendererOptions): string;
    private mergeOptions;
    private buildNormalizedBase;
    private renderSingleToken;
    private renderInlineTokens;
    private renderInlineTokensAsync;
    private renderInlineAsTextInternal;
}
export default Renderer;
