import { ResolvedTextEdit } from "../types.js";
import { TextDocument } from "./textDocument.js";

//#region src/editor/searchPanel.d.ts
type MatchRange = [startOffset: number, endOffset: number];
type SearchPanelMode = 'find' | 'replace';
interface SearchParams {
  text: string;
  replaceText: string;
  caseSensitive: boolean;
  wholeWord: boolean;
  regex: boolean;
}
interface SearchPanelOptions {
  textDocument: TextDocument<unknown>;
  containerElement: HTMLElement;
  defaultQuery: string;
  mode?: SearchPanelMode;
  initialMatch?: MatchRange;
  scrollToMatch: (nextMatch: MatchRange, retainFocus: boolean) => void;
  applyReplace: (edits: ResolvedTextEdit[]) => void;
  onUpdate: (matches: MatchRange[], options?: {
    syncSelection?: boolean;
  }) => MatchRange | undefined;
  onClose: () => void;
}
declare class SearchPanelWidget {
  #private;
  constructor(options: SearchPanelOptions);
  focus(): void;
  navigate(findPrevious: boolean): void;
  updateMatches(options?: {
    syncSelection?: boolean;
  }): void;
  setMode(mode: SearchPanelMode): void;
  close(): void;
  cleanup(): void;
}
//#endregion
export { MatchRange, SearchPanelMode, SearchPanelOptions, SearchPanelWidget, SearchParams };
//# sourceMappingURL=searchPanel.d.ts.map