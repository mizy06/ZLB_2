import type { MarkdownItOptions } from '../index.js';
export interface ChunkRecommendation {
    strategy: 'plain' | 'discrete' | 'adaptive';
    maxChunkChars?: number;
    maxChunkLines?: number;
    fenceAware: boolean;
    maxChunks?: number;
    notes?: string;
}
/**
 * Suggest full-parse chunk settings for the current synthetic harness defaults.
 *
 * @experimental Recommendations are workload-dependent; validate on the corpus
 * you plan to parse.
 */
export declare function recommendFullChunkStrategy(sizeChars: number, sizeLines?: number, opts?: Partial<MarkdownItOptions>): ChunkRecommendation;
/**
 * Suggest stream chunk settings for the current synthetic harness defaults.
 *
 * @experimental Recommendations are workload-dependent; validate on the corpus
 * you plan to parse.
 */
export declare function recommendStreamChunkStrategy(sizeChars: number, sizeLines?: number, opts?: Partial<MarkdownItOptions>): ChunkRecommendation;
