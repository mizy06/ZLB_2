import { EditorSelection, TextEdit } from "../types.js";
import { TextDocument } from "./textDocument.js";

//#region src/editor/languages.d.ts
interface LanguageConfig {
  lineComment?: string | null;
  blockComment?: readonly [open: string, close: string];
}
type LanguageConfigMap = Readonly<Record<string, LanguageConfig>>;
interface ResolvedLanguageConfig {
  lineComment: string | null;
  blockComment: readonly [open: string, close: string];
}
/** Resolves language-specific comment tokens over the editor defaults. */
declare function resolveCommentConfig(languageId: string, overrides?: LanguageConfigMap): ResolvedLanguageConfig;
/** Builds one aligned batch of line-comment edits for all selected lines. */
declare function resolveLineCommentEdits(textDocument: TextDocument<unknown>, selections: readonly EditorSelection[], token: string): TextEdit[];
interface BlockCommentEditResult {
  edits: TextEdit[];
  nextSelectionOffsets: Array<readonly [start: number, end: number, direction: EditorSelection['direction']]>;
}
/** Builds block-comment edits and content-preserving post-edit selections. */
declare function resolveBlockCommentEdits(textDocument: TextDocument<unknown>, selections: readonly EditorSelection[], [open, close]: readonly [string, string], linewise?: boolean): BlockCommentEditResult | undefined;
//#endregion
export { BlockCommentEditResult, LanguageConfig, LanguageConfigMap, resolveBlockCommentEdits, resolveCommentConfig, resolveLineCommentEdits };
//# sourceMappingURL=languages.d.ts.map