export type GlobalMarkdownStateReason = 'reference-definition' | 'footnote-definition' | 'abbreviation-definition';
export declare function detectGlobalMarkdownState(src: string): GlobalMarkdownStateReason | null;
export declare function detectGlobalMarkdownStateFromChunks(chunks: Iterable<string>): GlobalMarkdownStateReason | null;
export declare function hasGlobalMarkdownState(src: string): boolean;
export declare function getKnownGlobalMarkdownState(env: Record<string, unknown>): GlobalMarkdownStateReason | null;
export declare function runWithKnownGlobalMarkdownState<T>(env: Record<string, unknown>, reason: GlobalMarkdownStateReason | null, run: () => T): T;
export declare function markKnownGlobalMarkdownState(env: Record<string, unknown>, reason: GlobalMarkdownStateReason): void;
export declare function finalizeKnownGlobalMarkdownState(env: Record<string, unknown>): void;
export declare function resetKnownGlobalMarkdownState(env: Record<string, unknown>): void;
