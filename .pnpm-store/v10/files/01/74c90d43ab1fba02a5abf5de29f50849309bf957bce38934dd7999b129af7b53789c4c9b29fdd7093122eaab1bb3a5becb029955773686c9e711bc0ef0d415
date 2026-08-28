import type { Token } from '../common/token.js';
import type { RendererEnv, RendererOptions } from './renderer.js';
import Renderer from './renderer.js';
type RenderInput = string | Token[];
/**
 * Render markdown or pre-generated tokens to HTML using a shared Renderer instance.
 */
export declare function render(input: RenderInput, options?: RendererOptions, env?: RendererEnv): string;
/**
 * Asynchronous render variant that awaits async rules (e.g. async highlight).
 */
export declare function renderAsync(input: RenderInput, options?: RendererOptions, env?: RendererEnv): Promise<string>;
export { Renderer };
export type { RendererEnv, RendererOptions };
export default render;
