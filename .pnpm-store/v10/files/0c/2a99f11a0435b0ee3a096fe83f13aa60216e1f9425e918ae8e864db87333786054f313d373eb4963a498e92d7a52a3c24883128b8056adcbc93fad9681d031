import { BaseCodeOptions, DiffsHighlighter, HighlightedToken, RenderRange } from "../types.js";
import { TextDocument, TextDocumentChange } from "./textDocument.js";

//#region src/editor/tokenizer.d.ts
interface EditorTokenizerProps {
  highlighter: DiffsHighlighter;
  textDocument: TextDocument<unknown>;
  codeOptions: BaseCodeOptions;
  matchBrackets?: boolean;
  setStyle: (style: string) => void;
  onDeferTokenize: (lines: Map<number, Array<HighlightedToken>>, themeType: 'dark' | 'light') => void;
  onThemeChange?: () => void;
  __debug?: boolean;
}
/** Stoppable code tokenizer for the editor */
declare class EditorTokenizer {
  #private;
  get themeType(): 'light' | 'dark';
  getStringCommentRegexpRangesInLine(lineIndex: number): [number, number][] | null;
  constructor({
    codeOptions,
    highlighter,
    textDocument,
    matchBrackets,
    setStyle,
    onDeferTokenize,
    onThemeChange,
    __debug
  }: EditorTokenizerProps);
  syncTheme(codeOptions: BaseCodeOptions): void;
  cleanUp(): void;
  tokenize(change: TextDocumentChange, renderRange?: RenderRange, hostRealignsRows?: boolean): Map<number, Array<HighlightedToken>>;
  prebuildStateStack(renderRange?: RenderRange): void;
  stopBackgroundTokenize(): void;
  pauseBackgroundTokenize(): void;
  resumeBackgroundTokenize(): void;
}
declare function renderLineTokens(tokens: Array<HighlightedToken>): (HTMLElement | string)[];
//#endregion
export { EditorTokenizer, EditorTokenizerProps, renderLineTokens };
//# sourceMappingURL=tokenizer.d.ts.map