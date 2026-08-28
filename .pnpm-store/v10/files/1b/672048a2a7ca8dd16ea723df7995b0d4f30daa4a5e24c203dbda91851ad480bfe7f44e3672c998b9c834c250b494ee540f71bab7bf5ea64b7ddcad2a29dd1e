//#region src/editor/utils.d.ts
declare function h<K extends keyof HTMLElementTagNameMap>(tagName: K, props?: {
  style?: string | Partial<CSSStyleDeclaration>;
  dataset?: DOMStringMap | string[] | string;
  children?: (Node | string)[];
} & Partial<Omit<HTMLElementTagNameMap[K], 'style' | 'dataset' | 'children'>>, parent?: Element | ShadowRoot | DocumentFragment): HTMLElementTagNameMap[K];
declare function addEventListener<K extends keyof HTMLElementEventMap>(el: HTMLElement, event: K, listener: (this: HTMLElement, evt: HTMLElementEventMap[K]) => void, options?: AddEventListenerOptions): () => void;
declare function addEventListener<K extends keyof DocumentEventMap>(el: Document, event: K, listener: (this: Document, evt: DocumentEventMap[K]) => void, options?: AddEventListenerOptions): () => void;
declare function addEventListener<K extends keyof WindowEventMap>(el: Window, event: K, listener: (this: Window, evt: WindowEventMap[K]) => void, options?: AddEventListenerOptions): () => void;
declare function addEventListener<K extends keyof MediaQueryListEventMap>(el: MediaQueryList, event: K, listener: (this: MediaQueryList, evt: MediaQueryListEventMap[K]) => void, options?: AddEventListenerOptions): () => void;
declare function getLineNumberAttr(el: HTMLElement, key?: string): number | undefined;
declare function clampDomOffset(node: Node, offset: number): number;
declare function extend<T extends object>(obj: T, attrs: Partial<T>): T;
declare function debounce<T extends (...args: any[]) => void>(func: T, wait: number): (...args: Parameters<T>) => void;
declare function round(value: number, precision?: number): number;
declare function endsWithLineBreak(text: string): boolean;
declare function createSegmenter(options: Intl.SegmenterOptions): Intl.Segmenter | undefined;
declare function getGraphemeSegmenter(): Intl.Segmenter | undefined;
declare function lookupScrollContainer(element: HTMLElement): HTMLElement | Document;
//#endregion
export { addEventListener, clampDomOffset, createSegmenter, debounce, endsWithLineBreak, extend, getGraphemeSegmenter, getLineNumberAttr, h, lookupScrollContainer, round };
//# sourceMappingURL=utils.d.ts.map