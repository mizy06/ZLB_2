import { dequeueRender, queueRender } from "../managers/UniversalRenderingManager.js";
import { isGutterUtilityPath } from "../utils/isGutterUtilityPath.js";
import { getFiletypeFromFileName } from "../utils/getFiletypeFromFileName.js";
import { isSafari } from "../utils/platform.js";
import { isMoveCursorShortcut, isPrimaryModifier } from "./platform.js";
import { resolveEditorCommandFromKeyboardEvent, resolveFindAgainShortcut } from "./command.js";
import { EditStack } from "./editStack.js";
import editor_default from "./editor2.js";
import { resolveBlockCommentEdits, resolveCommentConfig, resolveLineCommentEdits } from "./languages.js";
import { addEventListener, clampDomOffset, extend, getLineNumberAttr, h, lookupScrollContainer, round } from "./utils.js";
import { applyDocumentChangeToLineAnnotations, renderLineAnnotations } from "./lineAnnotations.js";
import { PopoverManager } from "./popover.js";
import { applyDeleteCharacterToSelections, applyDeleteHardLineForwardToSelections, applyDeleteSoftLineBackwardToSelections, applyDeleteWordBackwardToSelections, applyTextChangeToSelections, applyTextReplaceToSelections, applyTransposeToSelections, comparePosition, convertSelection, createSelectionFrom, createSelectionFromAnchorAndFocusOffsets, expandCollapsedSelectionToWord, extendSelection, extendSelections, findNextMatch, getAutoSurroundReplacementTexts, getCaretPosition, getDocumentBoundarySelection, getDocumentFullSelection, getSelectedLineBlocks, getSelectionAnchor, getSelectionClipboardTexts, getSelectionText, isCollapsedSelection, isLineEditable, mapCursorMove, mapSelectionShift, mergeOverlappingSelections, remapSelectionsAfterEdits, resolveIndentEdits, resolveSelectionCut, selectionIntersects, shiftSelectionLines } from "./selection.js";
import { MarkerRenderer, markerSeverityDatasetKey } from "./marker.js";
import { findBracketMatchRanges } from "./matchBrackets.js";
import { createSpriteElement } from "./sprite.js";
import { SearchPanelWidget } from "./searchPanel.js";
import { SelectionActionWidget } from "./selectionAction.js";
import { cloneEditorState, createStateStorage } from "./stateStorage.js";
import { TextDocument } from "./textDocument.js";
import { Metrics, getExpandedAsciiTextColumns, getUnicodeMeasurementOffsets, snapTextOffsetToUnicodeBoundary } from "./textMeasure.js";
import { EditorTokenizer, renderLineTokens } from "./tokenizer.js";
//#region src/editor/editor.ts
function getShadowRootRange(shadowRoot) {
	const selection = shadowRoot.getSelection?.();
	if (selection == null || selection.rangeCount === 0) return;
	const range = selection.getRangeAt(0);
	return {
		collapsed: range.collapsed,
		startContainer: range.startContainer,
		startOffset: range.startOffset,
		endContainer: range.endContainer,
		endOffset: range.endOffset
	};
}
function requirePersistedCacheKey(file) {
	if (typeof file.cacheKey !== "string" || file.cacheKey.length === 0) throw new Error(`Editor persistState requires a non-empty file.cacheKey for "${file.name}". Provide a unique, stable cacheKey for every editable file.`);
	return file.cacheKey;
}
function isPromise(value) {
	return typeof value === "object" && value !== null && "then" in value && typeof value.then === "function";
}
const MAX_EDIT_WIDEN_WINDOW_MULTIPLE = 2;
const MAX_WRAP_OFFSETS_CACHE_LINES = 1e4;
const SELECTION_ACTION_POPOVER_PLACEMENT_KEY = "selection-action";
const MULTI_SELECTION_CLIPBOARD_TYPE = "application/vnd.pierre.diffs-selections+json";
var Editor = class {
	#options;
	#metrics = new Metrics();
	#tokenizer;
	#popoverManager;
	#textDocumentCache = /* @__PURE__ */ new Map();
	#stateStorage;
	#stateStorageOption;
	#pendingStateWrites = /* @__PURE__ */ new Map();
	#pendingStateRestore;
	#stateRestoreGeneration = 0;
	#restoreStateOnNextSync = false;
	#editorEventDisposes;
	#globalEventDisposes;
	#selectEventDisposes;
	#detach;
	#attachState = {
		generation: 0,
		callback: void 0,
		delivered: false
	};
	#contentOffset;
	#gutterWidthCache;
	#contentWidthCache;
	#lineYCache = /* @__PURE__ */ new Map();
	#wrapLineOffsetsCache = /* @__PURE__ */ new Map();
	#lineElementsCache = /* @__PURE__ */ new Map();
	#lastAccessedCharX;
	#globalStyleElement;
	#editorStyleElement;
	#themeStyleElement;
	#spriteElement;
	#fileContainer;
	#gutterElement;
	#contentElement;
	#overlayElement;
	#overlayElements;
	#primaryCaretElement;
	#resizeObserver;
	#fileInstance;
	#fileInfo;
	#lineAnnotations;
	#textDocument;
	#renderRange;
	#viewportWindowLines;
	#markerRenderer;
	#searchPanel;
	#selectionAction;
	#canMountSelectionAction = true;
	#shouldIgnoreSelectionChange = false;
	#suppressNativeSelectionSync = false;
	#contentHasFocus = false;
	#replacementFocusRequest;
	#isComposing = false;
	#isGutterMouseDown = false;
	#isContentMouseDown = false;
	#shiftKeyPressed = false;
	#selectionStart;
	#deletedSelectionText = "";
	#reservedSelections;
	#initSelections;
	#selections;
	#matches;
	#scrollingToLine;
	#scrollingToLineChar;
	#scrollingToLineFixed = false;
	#scrollingToLineNoFocus = false;
	#retainSearchPanelFocus = false;
	#fontRemeasureScheduled = false;
	#themeSelectionRefreshFrame;
	#onDeferTokenize = (lines, themeType) => {
		this.#fileInstance?.updateRenderCache(lines, themeType);
		if (this.#renderRange !== void 0 && this.#renderRange.totalLines !== Infinity) {
			const { startingLine, totalLines } = this.#renderRange;
			const endLine = Math.min(startingLine + totalLines, this.#textDocument?.lineCount ?? 0);
			for (const [line, tokens] of lines) if (line >= startingLine && line < endLine) {
				const lineElement = this.#getLineElement(line);
				if (lineElement !== void 0) lineElement.replaceChildren(...renderLineTokens(tokens));
			}
		}
	};
	constructor(options = {}) {
		this.#options = options;
	}
	setOptions(options) {
		const previousStorageOption = this.#options.persistStateStorage ?? "inMemory";
		const nextOptions = {
			...this.#options,
			...options
		};
		if (nextOptions.persistState === true && this.#fileInstance?.type === "file") {
			const file = this.#fileInstance.__getCurrentFile?.() ?? this.#fileInfo;
			if (file !== void 0) requirePersistedCacheKey(file);
		}
		this.#options = nextOptions;
		if (this.#options.persistState !== true) {
			this.#textDocumentCache.clear();
			this.#stateRestoreGeneration++;
			this.#restoreStateOnNextSync = false;
		}
		if ((this.#options.persistStateStorage ?? "inMemory") !== previousStorageOption) {
			this.#stateRestoreGeneration++;
			this.#stateStorage = void 0;
			this.#stateStorageOption = void 0;
			this.#pendingStateWrites.clear();
		}
	}
	edit(fileInstance) {
		if (this.#options.persistState === true && fileInstance.type === "file") {
			const file = fileInstance.__getCurrentFile?.();
			if (file !== void 0) requirePersistedCacheKey(file);
		}
		this.#invalidateOnAttach();
		this.#fileInstance = fileInstance;
		this.#initialize();
		this.#detach = fileInstance.attachEditor(this);
		return () => this.cleanUp();
	}
	/**
	* Apply edits to current attached file. Every edit joins the undo timeline:
	* a programmatic edit must leave the document and its history exactly as
	* the same edit typed by the user would (history equivalence — see
	* TextDocument.applyResolvedEdits), so it is undoable like any other edit.
	*
	* @param updateHistory Whether to record caller selection snapshots for
	* exact undo/redo restoration. Defaults to true. When false, live selections
	* are remapped during replay and the text edit still joins the undo timeline.
	*/
	applyEdits(edits, updateHistory = true) {
		const textDocument = this.#textDocument;
		if (textDocument == null) throw new Error("Editor is not attached");
		const wasFocused = this.#contentHasFocus;
		const selectionsBefore = this.#selections;
		const selectionOffsetsBefore = selectionsBefore?.map((selection) => [textDocument.offsetAt(selection.start), textDocument.offsetAt(selection.end)]);
		const resolvedEditOffsets = selectionsBefore === void 0 ? void 0 : textDocument.resolveEdits(edits).sort((a, b) => a.start - b.start);
		const change = textDocument.applyEdits(edits, updateHistory, selectionsBefore);
		if (change === void 0) return;
		let nextSelections;
		if (selectionsBefore !== void 0 && selectionOffsetsBefore !== void 0 && resolvedEditOffsets !== void 0) {
			nextSelections = remapSelectionsAfterEdits(textDocument, selectionsBefore, selectionOffsetsBefore, resolvedEditOffsets);
			if (updateHistory) textDocument.setLastUndoSelectionsAfter(nextSelections);
		}
		this.#applyChange(change, nextSelections, this.#applyChangeToLineAnnotations(change), { skipFocus: !wasFocused });
	}
	/** Whether there is an edit to undo. */
	get canUndo() {
		return this.#textDocument?.canUndo ?? false;
	}
	/** Whether there is an undone edit to redo. */
	get canRedo() {
		return this.#textDocument?.canRedo ?? false;
	}
	/** Undo the last edit. Does nothing when there is nothing to undo. */
	undo() {
		this.#runCommand("undo");
	}
	/** Redo the last undone edit. Does nothing when there is nothing to redo. */
	redo() {
		this.#runCommand("redo");
	}
	getFile() {
		const fileInfo = this.#fileInfo;
		const textDocument = this.#textDocument;
		if (fileInfo === void 0 || textDocument === void 0) return;
		const file = { ...fileInfo };
		Object.defineProperty(file, "contents", {
			enumerable: true,
			get: () => textDocument.getText()
		});
		return file;
	}
	getText() {
		return this.#textDocument?.getText() ?? "";
	}
	getState() {
		const fileInstance = this.#fileInstance;
		return {
			selections: this.#selections,
			view: fileInstance != null ? {
				scrollLeft: fileInstance.getCodeScrollLeft(),
				scrollTop: this.#getViewportScrollTop()
			} : void 0
		};
	}
	setState({ selections, view }) {
		if (this.#fileInstance === void 0 || this.#textDocument === void 0) throw new Error("Editor is not attached");
		this.#canMountSelectionAction = false;
		this.#updateSelections(selections ?? []);
		if (view != null) {
			this.#fileInstance.setCodeScrollLeft(view.scrollLeft);
			if (view.scrollTop !== void 0) this.#setViewportScrollTop(view.scrollTop);
			return;
		}
		this.#scrollToPrimaryCaret();
	}
	setSelections(selections) {
		const textDocument = this.#textDocument;
		if (textDocument === void 0) throw new Error("Text document is not initialized");
		const resolvedSelections = selections.map((selection) => {
			let start = textDocument.normalizePosition(selection.start);
			let end = textDocument.normalizePosition(selection.end);
			let direction = selection.direction === "none" ? 0 : selection.direction === "backward" ? -1 : 1;
			if (comparePosition(start, end) > 0) {
				[start, end] = [end, start];
				if (direction !== 0) direction = direction === 1 ? -1 : 1;
			}
			return {
				direction,
				start,
				end
			};
		});
		this.#canMountSelectionAction = false;
		this.#updateSelections(resolvedSelections);
		const primarySelection = resolvedSelections.at(-1);
		if (primarySelection !== void 0) this.#revealLineIfCollapsed(getCaretPosition(primarySelection).line);
		this.#scrollToPrimaryCaret();
	}
	setMarkers(markers) {
		const textDocument = this.#textDocument;
		if (textDocument === void 0) throw new Error("Text document is not initialized");
		if (markers.length === 0) {
			this.#markerRenderer?.cleanup();
			this.#markerRenderer = void 0;
			this.#updateSelections(this.#selections ?? []);
			return;
		}
		this.#markerRenderer ??= new MarkerRenderer({
			popoverManager: this.#getPopoverManager(),
			getLineHeight: () => this.#metrics.lineHeight,
			getOverlayElement: () => this.#overlayElement,
			getGutterWidth: () => this.#getGutterWidth(),
			getCharX: (line, character) => this.#getCharX(line, character),
			getLineY: (line) => this.#getLineY(line),
			isMouseDown: () => this.#isContentMouseDown || this.#isGutterMouseDown
		});
		this.#markerRenderer.setMarkers(markers, textDocument);
		if (this.#contentElement !== void 0) this.#markerRenderer.listenHover(this.#contentElement);
		this.#updateSelections(this.#selections ?? []);
	}
	focus(options) {
		const preventScroll = options?.preventScroll ?? false;
		const lineNumber = options?.lineNumber;
		if (lineNumber === "first-visible" || typeof lineNumber === "number") {
			const textDocument = this.#textDocument;
			if (textDocument == null || this.#fileInstance == null) return;
			const targetLineNumber = lineNumber === "first-visible" ? this.#getFirstVisibleLineNumber(options?.offset) : lineNumber;
			if (targetLineNumber == null) return;
			const position = textDocument.normalizePosition({
				line: targetLineNumber - 1,
				character: lineNumber === "first-visible" ? 0 : options?.character ?? 0
			});
			this.#focusAtPosition(position, preventScroll);
			return;
		}
		const primarySelection = this.#selections?.at(-1);
		if (primarySelection !== void 0) {
			const pos = primarySelection.direction === -1 ? primarySelection.end : primarySelection.start;
			this.#focus(pos, preventScroll);
		} else this.#focus(void 0, preventScroll);
	}
	blur() {
		this.#replacementFocusRequest = void 0;
		this.#contentHasFocus = false;
		this.#shouldIgnoreSelectionChange = false;
		this.#contentElement?.blur();
	}
	cleanUp(recycle = false) {
		this.#invalidateOnAttach();
		if (!recycle) this.#attachState.delivered = false;
		const hadFileInstance = this.#fileInstance != null;
		const shouldRestoreState = this.#options.persistState === true;
		this.#stateRestoreGeneration++;
		this.#persistCurrentState();
		if (hadFileInstance) this.#restoreStateOnNextSync = shouldRestoreState;
		dequeueRender(this.#handleCustomPasteEvent);
		this.#tokenizer?.cleanUp();
		this.#tokenizer = void 0;
		if (!recycle) {
			this.#textDocument = void 0;
			this.#fileInfo = void 0;
		}
		this.#globalEventDisposes?.forEach((dispose) => dispose());
		this.#globalEventDisposes = void 0;
		this.#editorEventDisposes?.forEach((dispose) => dispose());
		this.#editorEventDisposes = void 0;
		this.#selectEventDisposes?.forEach((dispose) => dispose());
		this.#selectEventDisposes = void 0;
		this.#detach?.(recycle);
		this.#detach = void 0;
		this.#gutterWidthCache = void 0;
		this.#contentWidthCache = void 0;
		this.#lineYCache.clear();
		this.#wrapLineOffsetsCache.clear();
		this.#lineElementsCache.clear();
		this.#lastAccessedCharX = void 0;
		this.#globalStyleElement?.remove();
		this.#globalStyleElement = void 0;
		this.#editorStyleElement?.remove();
		this.#editorStyleElement = void 0;
		this.#themeStyleElement?.remove();
		this.#themeStyleElement = void 0;
		this.#spriteElement?.remove();
		this.#spriteElement = void 0;
		this.#fileContainer = void 0;
		this.#popoverManager?.cleanUp();
		this.#popoverManager = void 0;
		this.#gutterElement = void 0;
		this.#contentElement?.removeAttribute("contentEditable");
		this.#contentElement = void 0;
		this.#replacementFocusRequest = void 0;
		this.#contentHasFocus = false;
		this.#overlayElement?.remove();
		this.#overlayElement = void 0;
		this.#resizeObserver?.disconnect();
		this.#resizeObserver = void 0;
		this.#fontRemeasureScheduled = false;
		if (this.#themeSelectionRefreshFrame !== void 0) {
			cancelAnimationFrame(this.#themeSelectionRefreshFrame);
			this.#themeSelectionRefreshFrame = void 0;
		}
		this.#resetState();
		this.#fileInstance = void 0;
	}
	/** @internal Capture outgoing state and substitute cached text before render. */
	__prepareFile(file) {
		if (this.#options.persistState !== true) return file;
		const cacheKey = requirePersistedCacheKey(file);
		const fileInfo = this.#fileInfo;
		const languageId = file.lang ?? getFiletypeFromFileName(file.name);
		if (fileInfo !== void 0 && (requirePersistedCacheKey(fileInfo) !== cacheKey || fileInfo.name !== file.name || this.#textDocument?.languageId !== languageId)) {
			this.#stateRestoreGeneration++;
			this.#persistCurrentState();
		}
		const textDocument = this.#getCachedTextDocument(file, cacheKey);
		if (textDocument === void 0 || textDocument.getText() === file.contents) return file;
		return {
			...file,
			contents: textDocument.getText()
		};
	}
	/** @internal */
	__postponeBgTokenizeToNextFrame() {
		const tokenizer = this.#tokenizer;
		if (tokenizer !== void 0) {
			tokenizer.pauseBackgroundTokenize();
			requestAnimationFrame(() => {
				tokenizer.resumeBackgroundTokenize();
			});
		}
	}
	/** @internal */
	__captureFocusForDOMReplacement() {
		const contentElement = this.#contentElement;
		const shadowActiveElement = this.#fileContainer?.shadowRoot?.activeElement;
		if (contentElement != null && (this.#contentHasFocus || shadowActiveElement === contentElement || shadowActiveElement != null && contentElement.contains(shadowActiveElement))) this.#replacementFocusRequest = {};
	}
	/** @internal */
	__syncRenderView = (highlighter, fileContainer, fileOrDiff, lineAnnotations, renderRange) => {
		const fileInstance = this.#fileInstance;
		if (fileInstance == null) return;
		const shadowRoot = fileContainer.shadowRoot;
		if (shadowRoot == null) {
			console.error("[editor] Could not find the shadow root.");
			return;
		}
		let codeElement;
		let gutterEl;
		let contentEl;
		for (const el of shadowRoot.querySelectorAll("[data-code]")) if (el.dataset.deletions === void 0) {
			codeElement = el;
			for (const child of el.children) {
				const el = child;
				const { gutter, content } = el.dataset;
				if (gutter !== void 0) gutterEl = el;
				else if (content !== void 0) contentEl = el;
			}
			break;
		}
		if (codeElement === void 0 || contentEl === void 0) {
			this.#replacementFocusRequest = void 0;
			return;
		}
		this.#getPopoverManager().setViewportElements(fileContainer, codeElement);
		if (this.#fileContainer !== fileContainer) {
			this.#fileContainer = fileContainer;
			if (this.#globalStyleElement !== void 0) fileContainer.appendChild(this.#globalStyleElement);
			if (this.#editorStyleElement !== void 0) shadowRoot.appendChild(this.#editorStyleElement);
			if (this.#themeStyleElement !== void 0) shadowRoot.appendChild(this.#themeStyleElement);
			if (this.#spriteElement !== void 0) shadowRoot.prepend(this.#spriteElement);
		}
		const shouldRebuildDocument = this.#textDocument === void 0 || this.#fileInfo === void 0 || this.#fileInfo.name !== fileOrDiff.name || this.#fileInfo.lang !== fileOrDiff.lang || this.#fileInfo.cacheKey !== fileOrDiff.cacheKey;
		const persistedCacheKey = this.#options.persistState === true ? requirePersistedCacheKey(fileOrDiff) : void 0;
		let persistedStateTarget;
		if (shouldRebuildDocument) {
			this.#invalidateOnAttach();
			let contents = "";
			if ("contents" in fileOrDiff) contents = fileOrDiff.contents;
			else contents = fileOrDiff.additionLines.join("");
			const editStack = new EditStack({ maxEntries: this.#options.historyMaxEntries });
			const { name, lang, cacheKey } = fileOrDiff;
			const languageId = lang ?? getFiletypeFromFileName(fileOrDiff.name);
			const cachedTextDocument = persistedCacheKey !== void 0 ? this.#getCachedTextDocument(fileOrDiff, persistedCacheKey) : void 0;
			const reusableTextDocument = fileInstance.type === "file" || cachedTextDocument?.getText() === contents ? cachedTextDocument : void 0;
			const textDocument = reusableTextDocument ?? new TextDocument(fileOrDiff.name, contents, languageId, 0, editStack);
			this.#fileInfo = {
				name,
				lang,
				cacheKey
			};
			this.#textDocument = textDocument;
			if (persistedCacheKey !== void 0) {
				this.#textDocumentCache.set(persistedCacheKey, textDocument);
				persistedStateTarget = {
					cacheKey: persistedCacheKey,
					textDocument
				};
			}
			this.#tokenizer?.cleanUp();
			this.#tokenizer = void 0;
			this.#resetState();
			this.#wrapLineOffsetsCache.clear();
			this.#selections = this.#initSelections;
			if (this.#options.__debug === true) console.log(reusableTextDocument !== void 0 ? "[diffs/editor] cached text document reused for" : "[diffs/editor] text document rebuilt from", fileOrDiff.name);
		}
		if (persistedStateTarget === void 0 && this.#restoreStateOnNextSync && persistedCacheKey !== void 0 && this.#textDocument !== void 0) persistedStateTarget = {
			cacheKey: persistedCacheKey,
			textDocument: this.#textDocument
		};
		const textDocument = this.#textDocument;
		if (this.#tokenizer == null && textDocument != null) this.#tokenizer = new EditorTokenizer({
			highlighter,
			textDocument,
			codeOptions: this.#fileInstance?.__getEffectiveCodeOptions() ?? {},
			matchBrackets: this.#options.matchBrackets,
			onDeferTokenize: this.#onDeferTokenize,
			onThemeChange: () => this.#scheduleThemeSelectionRefresh(),
			setStyle: (css) => {
				this.#themeStyleElement.textContent = css;
			},
			__debug: this.#options.__debug
		});
		if (this.#contentElement !== contentEl) {
			this.#gutterElement = gutterEl;
			this.#contentElement = extend(contentEl, {
				contentEditable: "true",
				role: "textbox",
				ariaMultiLine: "true",
				autocapitalize: "off",
				writingSuggestions: "off",
				autocorrect: false,
				spellcheck: false,
				translate: false
			});
			if (this.#overlayElement !== void 0) contentEl.after(this.#overlayElement);
			this.#metrics.init(contentEl);
			this.#remeasureMetricsOnFontLoad();
			this.#listenContentElement(contentEl, gutterEl);
			if (this.#contentElement !== void 0 && this.#options.__debug === true) console.log("[diffs/editor] full re-render triggered !!!");
		}
		if (this.#replacementFocusRequest != null) this.#replacementFocusRequest.target = contentEl;
		if (contentEl.ariaLabel !== fileOrDiff.name) contentEl.ariaLabel = fileOrDiff.name;
		if (lineAnnotations !== void 0 && lineAnnotations.length > 0 || this.#isDiff) for (const child of this.#contentElement.children) {
			const el = child;
			const { lineAnnotation, lineType, separator } = el.dataset;
			if (lineAnnotation !== void 0 || separator !== void 0 || lineType === "change-deletion") el.setAttribute("contenteditable", "false");
		}
		this.#resetCache();
		this.#tokenizer?.syncTheme(this.#fileInstance?.__getEffectiveCodeOptions() ?? {});
		this.#lineAnnotations = lineAnnotations;
		this.#renderRange = renderRange;
		this.#viewportWindowLines = renderRange?.totalLines;
		this.#tokenizer?.prebuildStateStack(renderRange);
		this.#markerRenderer?.removePopover();
		if (this.#selections !== void 0 || this.#matches !== void 0 || this.#markerRenderer !== void 0) this.#updateSelections(this.#selections ?? []);
		if (this.#initSelections !== void 0 && this.#primaryCaretElement !== void 0) {
			this.#initSelections = void 0;
			this.#scrollToPrimaryCaret(false, "center");
		} else if (this.#scrollingToLine !== void 0) this.#scrollToLine(this.#scrollingToLine, this.#scrollingToLineChar, this.#scrollingToLineNoFocus);
		else if (this.#replacementFocusRequest !== void 0) this.#restoreReplacementFocus();
		else if (this.#selections !== void 0 && this.#selections.length > 0 && this.#contentHasFocus && !this.#retainSearchPanelFocus) this.focus({ preventScroll: true });
		if (this.#retainSearchPanelFocus) this.#searchPanel?.focus();
		if (this.#options.__debug === true && renderRange !== void 0) {
			const { startingLine, totalLines } = renderRange;
			console.log("[diffs/editor] render file:", fileOrDiff.name, "RenderRange:", startingLine + "-" + (startingLine + totalLines), "of", this.#textDocument?.lineCount, "lines");
		}
		if (persistedStateTarget !== void 0) {
			this.#restoreStateOnNextSync = false;
			this.#restorePersistedState(persistedStateTarget.cacheKey, persistedStateTarget.textDocument);
		}
		this.#scheduleOnAttach(fileInstance);
	};
	#getCachedTextDocument(file, cacheKey) {
		const textDocument = this.#textDocumentCache.get(cacheKey);
		const languageId = file.lang ?? getFiletypeFromFileName(file.name);
		return textDocument?.languageId === languageId ? textDocument : void 0;
	}
	#getStateStorage() {
		const option = this.#options.persistStateStorage ?? "inMemory";
		if (this.#stateStorage === void 0 || this.#stateStorageOption !== option) {
			this.#stateStorage = createStateStorage(option);
			this.#stateStorageOption = option;
		}
		return this.#stateStorage;
	}
	#persistCurrentState() {
		const fileInfo = this.#fileInfo;
		const textDocument = this.#textDocument;
		if (this.#options.persistState !== true || this.#fileInstance === void 0 || fileInfo === void 0 || textDocument === void 0) return;
		const cacheKey = requirePersistedCacheKey(fileInfo);
		this.#textDocumentCache.set(cacheKey, textDocument);
		let storage;
		try {
			storage = this.#getStateStorage();
		} catch {
			return;
		}
		const state = cloneEditorState(this.getState());
		const pendingRestore = this.#pendingStateRestore;
		if (pendingRestore?.cacheKey === cacheKey && pendingRestore.textDocument === textDocument) {
			this.#pendingStateRestore = void 0;
			if (textDocument.version === pendingRestore.documentVersion && this.#selections === pendingRestore.selections && state.view?.scrollLeft === pendingRestore.view?.scrollLeft && state.view?.scrollTop === pendingRestore.view?.scrollTop) return;
			this.#writeState(storage, cacheKey, state, pendingRestore.completion);
			return;
		}
		this.#writeState(storage, cacheKey, state);
	}
	#writeState(storage, cacheKey, state, waitFor) {
		const previousWrite = this.#pendingStateWrites.get(cacheKey);
		if (waitFor !== void 0 || previousWrite !== void 0) {
			let pending = waitFor ?? Promise.resolve();
			if (previousWrite !== void 0) pending = pending.then(() => previousWrite);
			this.#trackStateWrite(cacheKey, pending.then(() => storage.set(cacheKey, state)));
			return;
		}
		let result;
		try {
			result = storage.set(cacheKey, state);
		} catch {
			return;
		}
		if (!isPromise(result)) return;
		this.#trackStateWrite(cacheKey, result);
	}
	#trackStateWrite(cacheKey, result) {
		const pending = result.catch(() => {});
		this.#pendingStateWrites.set(cacheKey, pending);
		pending.finally(() => {
			if (this.#pendingStateWrites.get(cacheKey) === pending) this.#pendingStateWrites.delete(cacheKey);
		});
	}
	#restorePersistedState(cacheKey, textDocument) {
		const generation = ++this.#stateRestoreGeneration;
		const documentVersion = textDocument.version;
		const selections = this.#selections;
		const view = this.getState().view;
		let inputWatch;
		const applyState = (state) => {
			const currentView = this.getState().view;
			if (generation !== this.#stateRestoreGeneration || this.#textDocument !== textDocument || textDocument.version !== documentVersion || this.#selections !== selections || currentView?.scrollLeft !== view?.scrollLeft || this.#fileInfo === void 0 || requirePersistedCacheKey(this.#fileInfo) !== cacheKey) return;
			const userScrolled = inputWatch?.userScrolled() === true;
			if (state === void 0) {
				this.#fileInstance?.setCodeScrollLeft(0);
				if (!userScrolled) this.#setViewportScrollTop(0);
				return;
			}
			const restored = cloneEditorState(state);
			if (userScrolled && restored.view !== void 0) restored.view = { scrollLeft: restored.view.scrollLeft };
			this.setState(restored);
		};
		const readState = () => {
			let result;
			try {
				result = this.#getStateStorage().get(cacheKey);
			} catch {
				return;
			}
			if (isPromise(result)) return result.then(applyState).catch(() => {});
			else try {
				applyState(result);
			} catch {}
		};
		const pendingWrite = this.#pendingStateWrites.get(cacheKey);
		const result = pendingWrite === void 0 ? readState() : pendingWrite.then(readState);
		if (isPromise(result)) {
			inputWatch = this.#watchViewportUserInput();
			const pendingRestore = {
				cacheKey,
				textDocument,
				documentVersion,
				selections,
				view,
				completion: result.catch(() => {})
			};
			this.#pendingStateRestore = pendingRestore;
			pendingRestore.completion.finally(() => {
				inputWatch?.dispose();
				if (this.#pendingStateRestore === pendingRestore) this.#pendingStateRestore = void 0;
			});
		}
	}
	#watchViewportUserInput() {
		const viewport = this.#getScrollViewport();
		if (!(viewport instanceof HTMLElement)) return;
		let scrolled = false;
		const eventTypes = [
			"wheel",
			"touchstart",
			"mousedown"
		];
		const dispose = () => {
			for (const type of eventTypes) viewport.removeEventListener(type, onInput, { capture: true });
		};
		const onInput = () => {
			scrolled = true;
			dispose();
		};
		for (const type of eventTypes) viewport.addEventListener(type, onInput, {
			capture: true,
			passive: true
		});
		return {
			userScrolled: () => scrolled,
			dispose
		};
	}
	#isLineRenderable(line) {
		return this.#fileInstance?.isLineRenderable?.(line + 1) ?? true;
	}
	get #resolveRenderableLine() {
		const fileInstance = this.#fileInstance;
		if (fileInstance?.getNearestRenderableLine == null) return;
		return (line, direction) => {
			const nearest = fileInstance.getNearestRenderableLine(line + 1, direction);
			return nearest == null ? void 0 : nearest - 1;
		};
	}
	#revealLineIfCollapsed(line) {
		if (!this.#isLineRenderable(line)) this.#fileInstance?.revealLine?.(line + 1);
	}
	get #diffSyle() {
		return this.#fileInstance?.options.diffStyle ?? "split";
	}
	get #isDiff() {
		return this.#fileInstance?.type === "file-diff";
	}
	get #isWrap() {
		return this.#fileInstance?.options.overflow === "wrap";
	}
	#getPopoverManager() {
		return this.#popoverManager ??= new PopoverManager({
			hasActivePopover: () => this.#selectionAction !== void 0 || this.#markerRenderer?.isPopoverVisible() === true,
			updateActivePopover: () => {
				this.#updateSelectionActionPopover();
				this.#markerRenderer?.updatePopoverPosition();
			}
		});
	}
	#resetCache() {
		this.#lineYCache.clear();
		this.#lineElementsCache.clear();
		this.#lastAccessedCharX = void 0;
	}
	#resetState() {
		this.#setEditorActiveLineSafe(null);
		this.#gutterWidthCache = void 0;
		this.#contentWidthCache = void 0;
		this.#shouldIgnoreSelectionChange = false;
		this.#suppressNativeSelectionSync = false;
		this.#overlayElements?.forEach((el) => el.remove());
		this.#overlayElements = void 0;
		this.#selections = void 0;
		this.#reservedSelections = void 0;
		this.#scrollingToLine = void 0;
		this.#markerRenderer?.cleanup();
		this.#markerRenderer = void 0;
		this.#searchPanel?.cleanup();
		this.#searchPanel = void 0;
		this.#selectionAction?.cleanup();
		this.#selectionAction = void 0;
		this.#canMountSelectionAction = true;
	}
	#invalidateOnAttach() {
		const attachState = this.#attachState;
		attachState.generation++;
		if (attachState.callback != null) {
			dequeueRender(attachState.callback);
			attachState.callback = void 0;
		}
	}
	#scheduleOnAttach(fileInstance) {
		const attachState = this.#attachState;
		const textDocument = this.#textDocument;
		if (attachState.delivered || attachState.callback != null || textDocument == null) return;
		const { generation } = attachState;
		const callback = () => {
			if (attachState.callback !== callback) return;
			attachState.callback = void 0;
			if (generation !== attachState.generation || this.#fileInstance !== fileInstance || this.#textDocument !== textDocument) return;
			const contentElement = this.#contentElement;
			const shadowRoot = this.#fileContainer?.shadowRoot;
			if (contentElement == null || shadowRoot == null || !shadowRoot.contains(contentElement)) return;
			attachState.delivered = true;
			this.#options.onAttach?.(this, fileInstance);
		};
		attachState.callback = callback;
		queueRender(callback);
	}
	#getScrollViewport() {
		const viewport = this.#fileInstance?.getEditorViewport?.();
		if (viewport !== void 0) return viewport;
		const fileContainer = this.#fileContainer;
		if (this.#fileInstance == null || fileContainer == null) return;
		return lookupScrollContainer(fileContainer);
	}
	#getViewportScrollTop() {
		const viewport = this.#getScrollViewport();
		if (viewport instanceof HTMLElement) return viewport.scrollTop;
		return viewport?.defaultView?.scrollY ?? 0;
	}
	#setViewportScrollTop(scrollTop) {
		const viewport = this.#getScrollViewport();
		if (viewport instanceof HTMLElement) viewport.scrollTop = scrollTop;
		else if (viewport instanceof Document) viewport.defaultView?.scrollTo({ top: scrollTop });
	}
	#initialize() {
		this.#globalStyleElement = h("style", {
			dataset: "editorGlobalCss",
			textContent: `
        [data-annotation-slot] {
          user-select: none;
          -webkit-user-select: none;
        }
      `
		});
		this.#editorStyleElement = h("style", {
			dataset: "editorCss",
			textContent: editor_default
		});
		this.#themeStyleElement = h("style", { dataset: "editorThemeCss" });
		this.#spriteElement = createSpriteElement();
		this.#overlayElement = h("div", { dataset: "editorOverlay" });
		const replacementFocusTargetIsContent = (event) => {
			const target = event.composedPath()[0];
			return target instanceof Node && this.#contentElement?.contains(target) === true;
		};
		const cancelReplacementFocus = () => {
			if (this.#replacementFocusRequest == null) return;
			this.#replacementFocusRequest = void 0;
			this.#contentHasFocus = false;
			this.#shouldIgnoreSelectionChange = false;
		};
		this.#globalEventDisposes = [
			addEventListener(document, "focusin", (event) => {
				if (!replacementFocusTargetIsContent(event)) cancelReplacementFocus();
			}, { passive: true }),
			addEventListener(document, "pointerdown", (event) => {
				if (!replacementFocusTargetIsContent(event)) queueMicrotask(cancelReplacementFocus);
			}, {
				capture: true,
				passive: true
			}),
			addEventListener(document, "selectionchange", () => {
				const shadowRoot = this.#fileContainer?.shadowRoot;
				if (this.#shouldIgnoreSelectionChange || this.#suppressNativeSelectionSync || shadowRoot == null || !this.#contentHasFocus) return;
				if (this.#selections !== void 0 && this.#selections.length > 1 && !this.#isContentMouseDown) return;
				const selectionRaw = document.getSelection();
				if (selectionRaw == null) return;
				const composedRange = typeof selectionRaw.getComposedRanges === "function" ? selectionRaw.getComposedRanges({ shadowRoots: [shadowRoot] })?.[0] : getShadowRootRange(shadowRoot);
				if (composedRange === void 0 || !this.#rangeBelongsToEditor(composedRange)) return;
				let selection = convertSelection(composedRange, 0);
				if (selection === void 0) return;
				if (this.#isContentMouseDown && this.#shiftKeyPressed && this.#selections !== void 0 && this.#selections.length > 0) {
					const primarySelection = this.#selections.at(-1);
					this.#updateSelections([extendSelection(primarySelection, selection)]);
					return;
				}
				if (this.#isContentMouseDown) if (this.#selectionStart !== void 0) selection = createSelectionFrom(this.#selectionStart, selection);
				else this.#selectionStart = selection;
				else if (this.#selectionStart !== void 0) selection.direction = createSelectionFrom(this.#selectionStart, selection).direction;
				else if (this.#selections !== void 0 && this.#selections.length === 1) {
					const previous = this.#selections[0];
					if (comparePosition(previous.start, selection.start) === 0 && comparePosition(previous.end, selection.end) === 0) selection.direction = previous.direction;
				}
				if (this.#reservedSelections !== void 0) this.#updateSelections([...this.#reservedSelections.filter((reservedSelection) => !selectionIntersects(reservedSelection, selection)), selection]);
				else this.#updateSelections([selection]);
			}, { passive: true }),
			addEventListener(document, "pointerup", (e) => {
				if (e.pointerType !== "mouse") return;
				this.#selectEventDisposes?.forEach((dispose) => dispose());
				this.#selectEventDisposes = void 0;
				if (this.#isGutterMouseDown) {
					this.#isGutterMouseDown = false;
					this.#focus();
				}
				this.#shouldIgnoreSelectionChange = false;
				this.#isContentMouseDown = false;
				this.#shiftKeyPressed = false;
				this.#selectionStart = void 0;
				this.#reservedSelections = void 0;
				if (this.#options.enabledSelectionAction === true && this.#selections !== void 0 && this.#selections.length > 0 && !isCollapsedSelection(this.#selections.at(-1))) this.#updateSelections(this.#selections);
			}, { passive: true }),
			addEventListener(document, "keydown", (e) => {
				if (e.key === "Shift") this.#selectionStart = this.#selections?.at(-1);
			}, { passive: true }),
			addEventListener(document, "keyup", (e) => {
				if (e.key === "Shift") this.#selectionStart = void 0;
			}, { passive: true })
		];
	}
	#replaceSelectEventListeners(disposes) {
		this.#selectEventDisposes?.forEach((dispose) => dispose());
		this.#selectEventDisposes = disposes;
	}
	#isLineSelectionEnabled() {
		return this.#fileInstance?.options.enableLineSelection === true;
	}
	#preserveEditorSelectionsForGutterGesture() {
		this.#suppressNativeSelectionSync = this.#selections !== void 0;
	}
	#listenContentElement(contentEl, gutterEl) {
		const { onFocus, onBlur } = this.#options;
		const targetIsContentElement = (e) => {
			const target = e.composedPath()[0];
			return target !== void 0 && (target === contentEl || contentEl.contains(target));
		};
		this.#editorEventDisposes?.forEach((dispose) => dispose());
		this.#editorEventDisposes = [
			addEventListener(contentEl, "focus", () => {
				this.#contentHasFocus = true;
				onFocus?.();
				if (!this.#isContentMouseDown && !this.#shouldIgnoreSelectionChange && this.#selections !== void 0 && this.#selections.length > 0) this.#setWindowSelection(this.#selections.at(-1));
			}, { passive: true }),
			addEventListener(contentEl, "blur", () => {
				if (this.#replacementFocusRequest?.target === contentEl) {
					this.#replacementFocusRequest = void 0;
					this.#shouldIgnoreSelectionChange = false;
				}
				this.#contentHasFocus = false;
				onBlur?.();
			}, { passive: true }),
			addEventListener(contentEl, "pointerdown", (e) => {
				this.#canMountSelectionAction = true;
				this.#suppressNativeSelectionSync = false;
				if (e.pointerType !== "mouse") return;
				if (this.#isDeletedLineTarget(e)) {
					this.#setDeletedTextSelectionActive(true);
					if (this.#selections !== void 0) this.#updateSelections([]);
					return;
				}
				this.#setDeletedTextSelectionActive(false);
				this.#markerRenderer?.removePopover();
				if (isSafari() && this.#lineAnnotations !== void 0 && this.#lineAnnotations.length > 0) {
					const annotationDisposes = [...contentEl.querySelectorAll("[data-line-annotation]")].map((el) => [addEventListener(el, "mouseenter", () => {
						this.#shouldIgnoreSelectionChange = true;
					}), addEventListener(el, "mouseleave", () => {
						this.#shouldIgnoreSelectionChange = false;
					})]).flat();
					this.#replaceSelectEventListeners(annotationDisposes);
				}
				this.#isContentMouseDown = true;
				this.#selectionStart = void 0;
				if (e.button === 0 && isPrimaryModifier(e)) this.#reservedSelections = this.#selections?.map((selection) => ({ ...selection }));
				if (e.shiftKey) {
					const primarySelection = this.#selections?.at(-1);
					if (primarySelection !== void 0) {
						const pos = primarySelection.direction === -1 ? primarySelection.end : primarySelection.start;
						this.#setWindowSelection({
							start: pos,
							end: pos,
							direction: 0
						});
					}
					this.#shiftKeyPressed = true;
				}
			}, { passive: true }),
			addEventListener(contentEl, "keydown", (e) => {
				if (!targetIsContentElement(e)) return;
				this.#canMountSelectionAction = true;
				this.#suppressNativeSelectionSync = false;
				const command = resolveEditorCommandFromKeyboardEvent(e, this.#options.keymap);
				if (command !== void 0) {
					e.preventDefault();
					if (command === "simplifySelection") {
						this.#searchPanel?.close();
						this.#searchPanel = void 0;
						this.#retainSearchPanelFocus = false;
						this.#selectionAction?.cleanup();
						this.#selectionAction = void 0;
					}
					this.#runCommand(command);
					return;
				}
				const mvShortcut = isMoveCursorShortcut(e);
				const textDocument = this.#textDocument;
				if (this.#selections !== void 0 && this.#selections.length > 0 && mvShortcut !== void 0 && textDocument !== void 0) {
					const cursorMoveOptions = {
						getSoftLineOffsets: this.#isWrap ? (line) => this.#wrapLineTextOrWholeLine(line) : void 0,
						resolveRenderableLine: this.#resolveRenderableLine
					};
					if (e.shiftKey) this.#updateSelections(mapSelectionShift(textDocument, this.#selections, mvShortcut, cursorMoveOptions));
					else this.#updateSelections(mapCursorMove(textDocument, this.#selections, mvShortcut, cursorMoveOptions));
					this.#scrollToPrimaryCaret();
					e.preventDefault();
					return;
				}
				if ((e.key.length === 1 ? e.key.toLowerCase() : e.key) === "v" && isPrimaryModifier(e)) {
					if (e.repeat && this.#isDiff) {
						e.preventDefault();
						return;
					}
					if (this.#options.clipboard !== void 0) {
						e.preventDefault();
						queueRender(this.#handleCustomPasteEvent);
						return;
					}
				}
				if (this.#searchPanel !== void 0) {
					const findAgain = resolveFindAgainShortcut(e);
					if (findAgain !== void 0) {
						e.preventDefault();
						this.#searchPanel.navigate(findAgain === "previous");
						return;
					}
				}
			}),
			addEventListener(contentEl, "copy", (e) => {
				if (!targetIsContentElement(e)) return;
				e.preventDefault();
				if (this.#isDeletedTextSelectionActive()) e.clipboardData?.setData("text", this.#deletedTextForClipboard());
				else this.#writeSelectionClipboardData(e.clipboardData, this.#getSelectionText(), this.#getSelectionClipboardTexts());
			}),
			addEventListener(contentEl, "cut", (e) => {
				if (!targetIsContentElement(e)) return;
				e.preventDefault();
				if (this.#isDeletedTextSelectionActive()) e.clipboardData?.setData("text", this.#deletedTextForClipboard());
				else {
					const selectionTexts = this.#getSelectionClipboardTexts();
					this.#writeSelectionClipboardData(e.clipboardData, this.#cutSelectionText(), selectionTexts);
				}
			}),
			addEventListener(contentEl, "paste", (e) => {
				if (!targetIsContentElement(e)) return;
				e.preventDefault();
				const clipboardData = e.clipboardData;
				const textDocument = this.#textDocument;
				if (clipboardData === null || textDocument === void 0) return;
				let text = clipboardData.getData("text");
				const selectionCount = this.#selections?.length ?? 0;
				if (selectionCount > 1) {
					const multiSelectionText = clipboardData.getData(MULTI_SELECTION_CLIPBOARD_TYPE);
					if (multiSelectionText !== void 0) try {
						const selectionTexts = JSON.parse(multiSelectionText);
						if (Array.isArray(selectionTexts) && selectionTexts.length === selectionCount) text = selectionTexts;
					} catch {}
				}
				this.#replaceSelectionText(Array.isArray(text) ? text.map((t) => textDocument.normalizeEol(t)) : textDocument.normalizeEol(text), void 0, true, "document");
			}),
			addEventListener(contentEl, "beforeinput", (e) => {
				if (!targetIsContentElement(e)) return;
				if (e.inputType === "insertCompositionText") return;
				e.preventDefault();
				this.#handleInput(e.inputType, e.data);
			}),
			addEventListener(contentEl, "drop", (e) => {
				if (!targetIsContentElement(e)) return;
				e.preventDefault();
			}),
			addEventListener(contentEl, "compositionstart", (e) => {
				if (!targetIsContentElement(e)) return;
				this.#isComposing = true;
				this.#shouldIgnoreSelectionChange = true;
			}, { passive: true }),
			addEventListener(contentEl, "compositionend", (e) => {
				if (!targetIsContentElement(e)) return;
				this.#shouldIgnoreSelectionChange = false;
				const wasComposing = this.#isComposing;
				this.#isComposing = false;
				if (e.data !== "" || !wasComposing) this.#handleInput("insertText", e.data);
			}, { passive: true })
		];
		const deletionsCode = this.#fileContainer?.shadowRoot?.querySelector("[data-deletions]");
		if (deletionsCode != null) this.#editorEventDisposes.push(addEventListener(deletionsCode, "pointerdown", (e) => {
			const path = e.composedPath();
			if (isGutterUtilityPath(path)) {
				this.#preserveEditorSelectionsForGutterGesture();
				return;
			}
			const target = path[0];
			const gutterRow = target instanceof HTMLElement ? target.closest("[data-column-number]") : null;
			if (gutterRow instanceof HTMLElement) {
				if (this.#isLineSelectionEnabled()) {
					this.#preserveEditorSelectionsForGutterGesture();
					return;
				}
				if (this.#beginDeletionGutterSelection(gutterRow, deletionsCode, e.pointerType === "mouse")) return;
			}
			this.#setDeletedTextSelectionActive(true);
			if (this.#selections !== void 0) this.#updateSelections([]);
		}, { passive: true }));
		if (gutterEl !== void 0) {
			const resolveGutterTarget = (eventTarget, includeContentLine = false) => {
				let target = eventTarget;
				if (target?.dataset.lineNumberContent !== void 0) target = target.parentElement ?? void 0;
				else if (includeContentLine && target?.tagName === "SPAN") target = target.closest("[data-line]");
				return target;
			};
			const resolveEditableLine = (target) => {
				if (target === void 0) return;
				const lineType = target.dataset.lineType;
				const lineNumber = getLineNumberAttr(target) ?? getLineNumberAttr(target, "columnNumber");
				if (lineNumber === void 0 || lineType === void 0 || !isLineEditable(lineType)) return;
				return lineNumber - 1;
			};
			this.#editorEventDisposes.push(addEventListener(gutterEl, "pointerdown", (e) => {
				const path = e.composedPath();
				if (isGutterUtilityPath(path)) {
					this.#preserveEditorSelectionsForGutterGesture();
					return;
				}
				const gutterRow = resolveGutterTarget(path[0]);
				if (gutterRow !== void 0 && this.#isLineSelectionEnabled()) {
					this.#preserveEditorSelectionsForGutterGesture();
					return;
				}
				if (gutterRow?.dataset.lineType === "change-deletion") {
					const code = gutterRow.closest("[data-code]");
					if (code != null) this.#beginDeletionGutterSelection(gutterRow, code, e.pointerType === "mouse");
					return;
				}
				if (e.pointerType !== "mouse") return;
				const textDocument = this.#textDocument;
				const lineIndex = resolveEditableLine(gutterRow);
				if (lineIndex === void 0 || textDocument === void 0) return;
				this.#canMountSelectionAction = true;
				this.#markerRenderer?.removePopover();
				const selection = this.#spanLineSelection(lineIndex, lineIndex, textDocument);
				this.#isGutterMouseDown = true;
				this.#selectionStart = selection;
				this.#updateSelections([selection]);
				this.#setWindowSelection(selection);
				this.#focus();
				this.#replaceSelectEventListeners([addEventListener(document, "mousemove", (e) => {
					if (!this.#isGutterMouseDown) return;
					const textDocument = this.#textDocument;
					const lineIndex = resolveEditableLine(resolveGutterTarget(e.composedPath()[0], true));
					if (lineIndex === void 0 || textDocument === void 0) return;
					const anchorLine = this.#selectionStart?.start.line ?? lineIndex;
					const selection = this.#spanLineSelection(anchorLine, lineIndex, textDocument);
					this.#selectionStart ??= selection;
					this.#updateSelections([selection]);
					this.#focus(selection.direction === -1 ? selection.start : selection.end);
				}, { passive: true })]);
			}, { passive: true }));
		}
		this.#markerRenderer?.listenHover(contentEl);
		this.#resizeObserver?.disconnect();
		this.#resizeObserver = new ResizeObserver(this.#handleLayoutResize);
		this.#resizeObserver.observe(contentEl);
		this.#resizeObserver.observe(contentEl.parentElement);
		this.#computeContentOffset(contentEl);
	}
	#handleCustomPasteEvent = async () => {
		const clipboard = this.#options.clipboard;
		if (clipboard !== void 0) {
			let text = await clipboard.readText();
			const selectionCount = this.#selections?.length ?? 0;
			if (selectionCount > 1) {
				const multiSelectionText = await clipboard.readText(MULTI_SELECTION_CLIPBOARD_TYPE);
				try {
					const selectionTexts = JSON.parse(multiSelectionText);
					if (Array.isArray(selectionTexts) && selectionTexts.length === selectionCount) text = selectionTexts;
				} catch {}
			}
			const textDocument = this.#textDocument;
			if (textDocument !== void 0) this.#replaceSelectionText(Array.isArray(text) ? text.map((t) => textDocument.normalizeEol(t)) : textDocument.normalizeEol(text), void 0, true, "document");
		}
	};
	#computeContentOffset(contentEl) {
		if (this.#isDiff && this.#diffSyle === "split" && this.#isWrap) {
			this.#contentOffset = {
				top: contentEl.offsetTop,
				left: contentEl.offsetLeft - this.#getGutterWidth()
			};
			if (this.#options.__debug === true) console.log("[diffs/editor] content offset:", this.#contentOffset);
		}
	}
	get #activeContentOffset() {
		if (this.#isDiff && this.#diffSyle === "split" && this.#isWrap) return this.#contentOffset;
	}
	#runCommand(command) {
		const textDocument = this.#textDocument;
		if (textDocument === void 0) return;
		switch (command) {
			case "openSearchPanel":
				this.#openSearchPanel("find");
				break;
			case "openSearchReplacePanel":
				this.#openSearchPanel("replace");
				break;
			case "findNextMatch": {
				const selections = this.#selections;
				if (selections === void 0) break;
				if (selections.some(isCollapsedSelection)) {
					const expanded = selections.map((sel) => {
						if (isCollapsedSelection(sel)) return expandCollapsedSelectionToWord(textDocument, sel);
						return sel;
					});
					this.#updateSelections(expanded);
					this.focus();
				} else {
					const nextMatch = findNextMatch(textDocument, selections);
					if (nextMatch !== void 0) {
						this.#updateSelections(nextMatch);
						const primaryMatch = nextMatch.at(-1);
						if (primaryMatch !== void 0) this.#revealLineIfCollapsed(getCaretPosition(primaryMatch).line);
						this.#scrollToPrimaryCaret();
					}
				}
				break;
			}
			case "moveLineUp":
			case "moveLineDown":
				this.#moveSelectedLines(command === "moveLineUp" ? -1 : 1);
				break;
			case "copyLineUp":
			case "copyLineDown":
				this.#copySelectedLines(command === "copyLineUp" ? -1 : 1);
				break;
			case "simplifySelection": {
				const selections = this.#selections;
				const primarySelection = selections?.at(-1);
				if (selections === void 0 || primarySelection === void 0) break;
				if (selections.length > 1) {
					this.#updateSelections([primarySelection]);
					this.#focus(getCaretPosition(primarySelection));
				} else if (!isCollapsedSelection(primarySelection)) {
					const caret = getCaretPosition(primarySelection);
					this.#updateSelections([{
						start: caret,
						end: caret,
						direction: 0
					}]);
					this.#focus(caret);
				}
				break;
			}
			case "insertBlankLine":
				this.#insertBlankLine();
				break;
			case "deleteHardLineForward":
				this.#deleteHardLineForward();
				break;
			case "toggleComment":
			case "toggleBlockComment": {
				const selections = this.#selections;
				if (selections === void 0) break;
				const { lineComment, blockComment } = resolveCommentConfig(textDocument.languageId, this.#options.languageCommentConfig);
				if (command === "toggleComment" && lineComment !== null) {
					this.#applyCommandEdits(resolveLineCommentEdits(textDocument, selections, lineComment));
					break;
				}
				const linewise = command === "toggleComment";
				const result = resolveBlockCommentEdits(textDocument, selections, blockComment, linewise);
				if (result !== void 0) this.#applyCommandEdits(result.edits, linewise ? void 0 : (document) => result.nextSelectionOffsets.map(([start, end, direction]) => ({
					start: document.positionAt(start),
					end: document.positionAt(end),
					direction
				})));
				break;
			}
			case "indent":
			case "outdent":
			case "indentLess":
			case "indentMore":
				if (this.#selections !== void 0) {
					const edits = [];
					const nextSelections = [];
					const editedLines = /* @__PURE__ */ new Set();
					const sameLineIndents = [];
					for (const selection of this.#selections) {
						const startLine = selection.start.line;
						const outdent = command === "outdent" || command === "indentLess";
						const lineBased = command === "indentLess" || command === "indentMore";
						if (startLine !== selection.end.line || outdent || lineBased) {
							const ret = resolveIndentEdits(textDocument, selection, this.#metrics.tabSize, outdent);
							for (const edit of ret[0]) {
								const line = edit.range.start.line;
								if (!editedLines.has(line)) {
									editedLines.add(line);
									edits.push(edit);
								}
							}
							nextSelections.push(ret[1]);
						} else {
							const text = textDocument.charAt({
								line: startLine,
								character: 0
							}) === "	" ? "	" : " ".repeat(this.#metrics.tabSize);
							edits.push({
								range: selection,
								newText: text
							});
							sameLineIndents.push({
								line: startLine,
								startCharacter: selection.start.character,
								addedLength: text.length - (selection.end.character - selection.start.character),
								selectionIndex: nextSelections.length
							});
							const nextPosition = {
								line: selection.start.line,
								character: selection.start.character + text.length
							};
							nextSelections.push({
								start: nextPosition,
								end: nextPosition,
								direction: 0
							});
						}
					}
					for (const indent of sameLineIndents) {
						let shift = 0;
						for (const other of sameLineIndents) if (other.line === indent.line && other.startCharacter < indent.startCharacter) shift += other.addedLength;
						if (shift !== 0) {
							const current = nextSelections[indent.selectionIndex];
							const position = {
								line: indent.line,
								character: current.start.character + shift
							};
							nextSelections[indent.selectionIndex] = {
								start: position,
								end: position,
								direction: 0
							};
						}
					}
					const change = textDocument.applyEdits(edits, true, this.#selections, nextSelections);
					if (change !== void 0) this.#applyChange(change, nextSelections);
				}
				break;
			case "selectAll": {
				const fullSelection = getDocumentFullSelection(textDocument);
				this.#updateSelections([fullSelection]);
				this.focus();
				const renderedLineRanges = this.#getRenderedEditableLineRanges();
				const firstRenderedLine = renderedLineRanges[0]?.[0];
				const lastRenderedLine = renderedLineRanges.at(-1)?.[1];
				if (firstRenderedLine !== void 0 && lastRenderedLine !== void 0) {
					this.#suppressNativeSelectionSync = true;
					this.#setWindowSelection({
						start: {
							line: firstRenderedLine,
							character: 0
						},
						end: {
							line: lastRenderedLine,
							character: textDocument.getLineLength(lastRenderedLine)
						},
						direction: 1
					});
				}
				break;
			}
			case "moveCursorToDocStart":
			case "moveCursorToDocEnd":
				{
					const boundarySelection = getDocumentBoundarySelection(textDocument, command === "moveCursorToDocEnd", this.#isDiff);
					this.#updateSelections([boundarySelection]);
					this.#revealLineIfCollapsed(getCaretPosition(boundarySelection).line);
					this.#scrollToPrimaryCaret();
				}
				break;
			case "expandSelectionDocStart":
			case "expandSelectionDocEnd":
				{
					const atEnd = command === "expandSelectionDocEnd";
					const selections = this.#selections;
					if (selections !== void 0) {
						const boundarySelection = getDocumentBoundarySelection(textDocument, atEnd, this.#isDiff);
						this.#updateSelections(extendSelections(selections, boundarySelection));
						this.#revealLineIfCollapsed(getCaretPosition(boundarySelection).line);
						this.#scrollToPrimaryCaret();
					}
				}
				break;
			case "undo":
			case "redo":
				this.#applyHistoryChange(command);
				break;
		}
	}
	#applyHistoryChange(command) {
		const textDocument = this.#textDocument;
		if (textDocument === void 0) return;
		if (command === "undo" && !textDocument.canUndo || command === "redo" && !textDocument.canRedo) return;
		const selections = this.#selections;
		const selectionOffsets = selections?.map((selection) => [textDocument.offsetAt(selection.start), textDocument.offsetAt(selection.end)]);
		const result = command === "undo" ? textDocument.undo() : textDocument.redo();
		if (result === void 0) return;
		const [change, recordedSelections, lineAnnotations, selectionEdits] = result;
		const nextSelections = recordedSelections ?? (selections !== void 0 && selectionOffsets !== void 0 && selectionEdits !== void 0 ? remapSelectionsAfterEdits(textDocument, selections, selectionOffsets, selectionEdits) : void 0);
		this.#applyChange(change, nextSelections, lineAnnotations);
	}
	/** Applies one undoable command batch and records its resulting selections. */
	#applyCommandEdits(edits, resolveNextSelections) {
		const textDocument = this.#textDocument;
		const selections = this.#selections;
		if (textDocument === void 0 || selections === void 0) return;
		const remapSelections = resolveNextSelections === void 0;
		const selectionOffsets = remapSelections ? selections.map((selection) => [textDocument.offsetAt(selection.start), textDocument.offsetAt(selection.end)]) : void 0;
		const resolvedEdits = remapSelections ? edits.map((edit) => {
			const start = textDocument.offsetAt(edit.range.start);
			const end = textDocument.offsetAt(edit.range.end);
			return {
				start: Math.min(start, end),
				end: Math.max(start, end),
				text: edit.newText
			};
		}).sort((a, b) => {
			const startOrder = a.start - b.start;
			return startOrder !== 0 ? startOrder : a.end - b.end;
		}) : void 0;
		const change = textDocument.applyEdits(edits, true, selections, void 0, true);
		if (change === void 0) return;
		const nextSelections = remapSelections ? remapSelectionsAfterEdits(textDocument, selections, selectionOffsets, resolvedEdits) : resolveNextSelections(textDocument);
		textDocument.setLastUndoSelectionsAfter(nextSelections);
		this.#applyChange(change, nextSelections, this.#applyChangeToLineAnnotations(change));
	}
	/** Copies selected line blocks and keeps the selection in the requested copy. */
	#copySelectedLines(direction) {
		const textDocument = this.#textDocument;
		const selections = this.#selections;
		if (textDocument === void 0 || selections === void 0) return;
		const blocks = getSelectedLineBlocks(selections);
		if (blocks.length === 0) return;
		const copiedLinesBefore = [];
		let copiedLineCount = 0;
		const edits = [];
		for (const block of blocks) {
			copiedLinesBefore.push(copiedLineCount);
			const blockLineCount = block.endLine - block.startLine + 1;
			copiedLineCount += blockLineCount;
			const text = textDocument.getText({
				start: {
					line: block.startLine,
					character: 0
				},
				end: {
					line: block.endLine,
					character: textDocument.getLineLength(block.endLine)
				}
			});
			if (direction > 0) {
				const position = {
					line: block.startLine,
					character: 0
				};
				edits.push({
					range: {
						start: position,
						end: position
					},
					newText: text + textDocument.eol
				});
			} else if (block.endLine < textDocument.lineCount - 1) {
				const position = {
					line: block.endLine + 1,
					character: 0
				};
				edits.push({
					range: {
						start: position,
						end: position
					},
					newText: text + textDocument.eol
				});
			} else {
				const position = {
					line: block.endLine,
					character: textDocument.getLineLength(block.endLine)
				};
				edits.push({
					range: {
						start: position,
						end: position
					},
					newText: textDocument.eol + text
				});
			}
		}
		const nextSelections = selections.map((selection) => {
			const line = selection.start.line;
			let low = 0;
			let high = blocks.length - 1;
			while (low <= high) {
				const middle = low + high >>> 1;
				const block = blocks[middle];
				if (line < block.startLine) high = middle - 1;
				else if (line > block.endLine) low = middle + 1;
				else {
					low = middle;
					break;
				}
			}
			const blockIndex = Math.max(0, low <= high ? low : high);
			const block = blocks[blockIndex];
			const shift = copiedLinesBefore[blockIndex] + (direction > 0 ? block.endLine - block.startLine + 1 : 0);
			return {
				start: {
					...selection.start,
					line: selection.start.line + shift
				},
				end: {
					...selection.end,
					line: selection.end.line + shift
				},
				direction: selection.direction
			};
		});
		this.#applyCommandEdits(edits, () => nextSelections);
	}
	/** Inserts an indented blank line after each selection's final line. */
	#insertBlankLine() {
		const textDocument = this.#textDocument;
		const selections = this.#selections;
		if (textDocument === void 0 || selections === void 0) return;
		const selectionLines = selections.map((selection) => getCaretPosition(selection).line);
		const targetLines = Array.from(new Set(selectionLines)).sort((a, b) => a - b);
		const targetIndex = /* @__PURE__ */ new Map();
		const indents = /* @__PURE__ */ new Map();
		const edits = [];
		for (let index = 0; index < targetLines.length; index++) {
			const line = targetLines[index];
			const lineText = textDocument.getLineText(line);
			const indent = /^\s*/.exec(lineText)?.[0] ?? "";
			targetIndex.set(line, index);
			indents.set(line, indent);
			const position = {
				line,
				character: textDocument.getLineLength(line)
			};
			edits.push({
				range: {
					start: position,
					end: position
				},
				newText: textDocument.eol + indent
			});
		}
		const nextSelections = selections.map((_, index) => {
			const line = selectionLines[index];
			const position = {
				line: line + 1 + targetIndex.get(line),
				character: indents.get(line).length
			};
			return {
				start: position,
				end: position,
				direction: 0
			};
		});
		this.#applyCommandEdits(edits, () => nextSelections);
	}
	#moveSelectedLines(direction) {
		const textDocument = this.#textDocument;
		const selections = this.#selections;
		if (textDocument === void 0 || selections === void 0) return;
		const blocks = getSelectedLineBlocks(selections);
		if (blocks.length === 0 || direction < 0 && blocks[0].startLine === 0 || direction > 0 && blocks.at(-1).endLine >= textDocument.lineCount - 1) return;
		const lineCount = textDocument.lineCount;
		const lineRangeEnd = (line) => line < lineCount - 1 ? {
			line: line + 1,
			character: 0
		} : {
			line,
			character: textDocument.getLineLength(line)
		};
		const getLinesText = (lines, appendFinalLineBreak) => {
			const text = lines.map((line) => textDocument.getLineText(line)).join(textDocument.eol);
			return appendFinalLineBreak ? text + textDocument.eol : text;
		};
		const edits = [];
		if (direction < 0) for (const block of blocks) {
			const previousLine = block.startLine - 1;
			const blockLines = [];
			for (let line = block.startLine; line <= block.endLine; line++) blockLines.push(line);
			edits.push({
				range: {
					start: {
						line: previousLine,
						character: 0
					},
					end: lineRangeEnd(block.endLine)
				},
				newText: getLinesText([...blockLines, previousLine], block.endLine < lineCount - 1)
			});
		}
		else for (let index = blocks.length - 1; index >= 0; index--) {
			const block = blocks[index];
			const nextLine = block.endLine + 1;
			const blockLines = [];
			for (let line = block.startLine; line <= block.endLine; line++) blockLines.push(line);
			edits.push({
				range: {
					start: {
						line: block.startLine,
						character: 0
					},
					end: lineRangeEnd(nextLine)
				},
				newText: getLinesText([nextLine, ...blockLines], nextLine < lineCount - 1)
			});
		}
		const lastBlock = blocks.at(-1);
		const lastLineLengthAfterMove = direction > 0 && lastBlock.endLine === lineCount - 2 ? textDocument.getLineLength(lastBlock.endLine) : textDocument.getLineLength(lineCount - 1);
		const nextSelections = selections.map((selection) => shiftSelectionLines(selection, direction, lineCount, (line) => line === lineCount - 1 ? lastLineLengthAfterMove : textDocument.getLineLength(line)));
		const change = textDocument.applyEdits(edits, true, selections, nextSelections, true);
		if (change !== void 0) this.#applyChange(change, nextSelections);
	}
	#handleLayoutResize = () => {
		const lineAnnotations = this.#lineAnnotations?.length ?? 0;
		const prevGutterWidth = this.#gutterWidthCache;
		const prevContentWidth = this.#contentWidthCache;
		this.#gutterWidthCache = void 0;
		this.#contentWidthCache = void 0;
		const gutterWidthChanged = this.#getGutterWidth() !== prevGutterWidth;
		const contentWidthChanged = this.#getContentWidth() !== prevContentWidth;
		if (!gutterWidthChanged && !contentWidthChanged) return;
		this.#lineElementsCache.clear();
		this.#lastAccessedCharX = void 0;
		this.#metrics.clearTextWidthCache();
		if (contentWidthChanged) {
			this.#wrapLineOffsetsCache.clear();
			if (this.#isWrap || lineAnnotations > 0) this.#lineYCache.clear();
		}
		if (this.#selections !== void 0 || this.#matches !== void 0 || this.#markerRenderer !== void 0) {
			this.#updateSelections(this.#selections ?? []);
			if (this.#selections !== void 0 && this.#contentHasFocus) this.focus();
		}
		this.#markerRenderer?.removePopover();
		this.#computeContentOffset(this.#contentElement);
	};
	#remeasureMetricsOnFontLoad() {
		if (this.#fontRemeasureScheduled) return;
		const fonts = document.fonts;
		if (fonts === void 0) return;
		this.#fontRemeasureScheduled = true;
		fonts.ready.then(() => {
			if (this.#contentElement === void 0 || !this.#metrics.remeasureCharacterWidth()) return;
			this.#gutterWidthCache = void 0;
			this.#contentWidthCache = void 0;
			this.#resetCache();
			this.#wrapLineOffsetsCache.clear();
			if (this.#selections !== void 0 || this.#matches !== void 0 || this.#markerRenderer !== void 0) this.#updateSelections(this.#selections ?? []);
			this.#markerRenderer?.removePopover();
		});
	}
	#rerender(change, newLineAnnotations, renderRange = this.#renderRange, shouldUpdateBuffer) {
		const tokenizer = this.#tokenizer;
		const fileInstance = this.#fileInstance;
		const textDocument = this.#textDocument;
		const gutterEl = this.#gutterElement;
		const contentEl = this.#contentElement;
		if (tokenizer === void 0 || fileInstance === void 0 || textDocument === void 0 || contentEl === void 0) return;
		tokenizer.stopBackgroundTokenize();
		const t = performance.now();
		const dirtyLines = tokenizer.tokenize(change, renderRange, !this.#isDiff);
		const t2 = performance.now();
		if (dirtyLines.size > 0) {
			const children = contentEl.children;
			const dirtyLineIndexes = /* @__PURE__ */ new Set();
			for (const lineIndex of dirtyLines.keys()) if (this.#isLineRenderable(lineIndex)) dirtyLineIndexes.add(lineIndex);
			for (let i = 0; i < children.length; i++) {
				const child = children[i];
				if (child !== void 0) {
					const lineNumber = getLineNumberAttr(child);
					const lineType = child.dataset.lineType;
					if (lineNumber === void 0 || lineType === "change-deletion") continue;
					const lineIndex = lineNumber - 1;
					if (dirtyLineIndexes.has(lineIndex)) {
						const tokens = dirtyLines.get(lineIndex);
						child.replaceChildren(...renderLineTokens(tokens));
						dirtyLineIndexes.delete(lineIndex);
						if (dirtyLineIndexes.size === 0) break;
					}
				}
			}
			if (dirtyLineIndexes.size > 0) {
				let lastRenderedLineNumber = 0;
				for (let i = children.length - 1; i >= 0; i--) {
					const child = children[i];
					const lineNumber = getLineNumberAttr(child);
					if (lineNumber !== void 0 && child.dataset.lineType !== "change-deletion") {
						lastRenderedLineNumber = lineNumber;
						break;
					}
				}
				for (const lineIndex of dirtyLineIndexes) {
					if (lineIndex < lastRenderedLineNumber) continue;
					const tokens = dirtyLines.get(lineIndex);
					const lineNumber = String(lineIndex + 1);
					h("div", {
						dataset: {
							line: lineNumber,
							lineType: "context",
							lineIndex: lineIndex.toString()
						},
						children: renderLineTokens(tokens)
					}, contentEl);
					if (gutterEl !== void 0) h("div", {
						dataset: {
							lineType: "context",
							columnNumber: lineNumber,
							lineIndex: lineIndex.toString()
						},
						children: [h("span", {
							dataset: { lineNumberContent: "" },
							textContent: lineNumber
						})]
					}, gutterEl);
				}
			}
		}
		if (change.lineDelta < 0) for (const children of [contentEl.children, gutterEl?.children ?? []]) for (let i = children.length - 1; i >= 0; i--) {
			const child = children[i];
			const lineNumber = getLineNumberAttr(child) ?? getLineNumberAttr(child, "columnNumber");
			const lineType = child.dataset.lineType;
			if (lineNumber === void 0 || lineType === "change-deletion") continue;
			if (lineNumber - 1 < change.lineCount) break;
			child.remove();
		}
		const didLineCountChange = change.lineDelta !== 0;
		if (didLineCountChange) {
			let gridRow = contentEl.children.length;
			for (const child of contentEl.children) {
				const { bufferSize } = child.dataset;
				if (bufferSize !== void 0) gridRow += parseInt(bufferSize) - 1;
			}
			contentEl.style.gridRow = "span " + gridRow;
			if (gutterEl !== void 0) gutterEl.style.gridRow = "span " + gridRow;
		}
		fileInstance.updateRenderCache(dirtyLines, tokenizer.themeType, {
			shouldRefreshDiffsView: this.#isDiff && !didLineCountChange,
			lineCountChangeInFlight: didLineCountChange
		});
		if (didLineCountChange) fileInstance.applyDocumentChange(textDocument, newLineAnnotations, shouldUpdateBuffer);
		if (didLineCountChange || this.#isDiff && this.#diffSyle === "unified") this.#resetCache();
		if (newLineAnnotations !== void 0) {
			this.#lineAnnotations = newLineAnnotations;
			renderLineAnnotations(newLineAnnotations, contentEl, gutterEl);
		}
		if (this.#options.__debug === true) console.log(`[diffs/editor] re-render in: ${round(performance.now() - t2)}ms,`, `tokenize in: ${round(t2 - t)}ms (${dirtyLines.size} dirty lines)`);
	}
	#handleInput(inputType, data) {
		switch (inputType) {
			case "insertText": {
				const text = data ?? "";
				const textDocument = this.#textDocument;
				const selections = this.#selections;
				const autoSurroundTexts = textDocument !== void 0 && selections !== void 0 ? getAutoSurroundReplacementTexts(textDocument, selections, text, this.#options.autoSurround) : void 0;
				this.#replaceSelectionText(autoSurroundTexts ?? text);
				break;
			}
			case "insertCompositionText": break;
			case "insertLineBreak":
			case "insertParagraph":
				this.#replaceSelectionText(this.#textDocument?.eol ?? "\n");
				break;
			case "deleteContentBackward":
				this.#deleteSelectionText();
				break;
			case "deleteContentForward":
				this.#deleteSelectionText(true);
				break;
			case "deleteSoftLineBackward":
			case "deleteHardLineBackward":
				this.#deleteSoftLineBackward();
				break;
			case "deleteWordBackward":
				this.#deleteWordBackward();
				break;
			case "insertTranspose":
				this.#insertTranspose();
				break;
			default:
				console.warn(`[diffs] Unknown input type: ${inputType}`, data);
				break;
		}
	}
	#focus(position, preventScroll = true, shouldFocus) {
		this.#contentHasFocus = true;
		if (position !== void 0) {
			this.#shouldIgnoreSelectionChange = true;
			this.#setWindowSelection({
				start: position,
				end: position,
				direction: 0
			});
			queueRender(() => {
				if (shouldFocus?.() === false || !this.#contentHasFocus) {
					this.#shouldIgnoreSelectionChange = false;
					return;
				}
				this.#contentElement?.focus({ preventScroll });
				queueRender(() => {
					this.#shouldIgnoreSelectionChange = false;
				});
			});
		} else if (shouldFocus?.() !== false) this.#contentElement?.focus({ preventScroll });
		else this.#contentHasFocus = false;
	}
	#restoreReplacementFocus(position) {
		const request = this.#replacementFocusRequest;
		if (request == null) return;
		if (this.#retainSearchPanelFocus) {
			this.#replacementFocusRequest = void 0;
			this.#contentHasFocus = false;
			this.#shouldIgnoreSelectionChange = false;
			return;
		}
		const contentElement = this.#contentElement;
		if (contentElement == null || !this.#replacementFocusIsAvailable(contentElement)) {
			this.#replacementFocusRequest = void 0;
			this.#contentHasFocus = false;
			return;
		}
		const shouldFocus = () => {
			if (this.#replacementFocusRequest !== request) return false;
			const shouldRestore = this.#replacementFocusIsAvailable(contentElement);
			this.#replacementFocusRequest = void 0;
			return shouldRestore;
		};
		if (position != null) {
			this.#focus(position, true, shouldFocus);
			return;
		}
		const primarySelection = this.#selections?.at(-1);
		if (primarySelection == null) {
			this.#focus(void 0, true, shouldFocus);
			return;
		}
		const primaryPosition = primarySelection.direction === -1 ? primarySelection.end : primarySelection.start;
		this.#focus(primaryPosition, true, shouldFocus);
	}
	#replacementFocusIsAvailable(contentElement) {
		const fileContainer = this.#fileContainer;
		const shadowRoot = fileContainer?.shadowRoot;
		if (fileContainer == null || shadowRoot == null || this.#contentElement !== contentElement || !shadowRoot.contains(contentElement)) return false;
		const { activeElement: shadowActiveElement } = shadowRoot;
		if (shadowActiveElement === contentElement || shadowActiveElement != null && contentElement.contains(shadowActiveElement)) return true;
		if (shadowActiveElement != null) return false;
		const { ownerDocument } = fileContainer;
		const { activeElement } = ownerDocument;
		return activeElement == null || activeElement === ownerDocument.body || activeElement === ownerDocument.documentElement || activeElement === fileContainer;
	}
	#getFirstVisibleLineNumber(offset = 0) {
		const contentElement = this.#contentElement;
		const fileContainer = this.#fileContainer;
		if (this.#textDocument == null || contentElement == null || fileContainer == null) return;
		const viewport = this.#getScrollViewport();
		if (viewport === void 0) return;
		let viewportTop;
		let viewportBottom;
		if (viewport instanceof HTMLElement) {
			const viewportRect = viewport.getBoundingClientRect();
			viewportTop = viewportRect.top;
			viewportBottom = viewportRect.bottom;
		} else {
			viewportTop = 0;
			viewportBottom = viewport.defaultView?.innerHeight ?? 0;
		}
		const stickyHeader = fileContainer.shadowRoot?.querySelector("[data-diffs-header][data-sticky]");
		if (stickyHeader != null) viewportTop = Math.max(viewportTop, stickyHeader.getBoundingClientRect().bottom);
		if (Number.isFinite(offset)) viewportTop += Math.max(0, offset);
		if (viewportBottom <= viewportTop) return;
		for (const child of contentElement.children) {
			const row = child;
			const lineNumber = getLineNumberAttr(row);
			const lineType = row.dataset.lineType;
			if (lineNumber == null || lineType == null || !isLineEditable(lineType)) continue;
			const rowRect = row.getBoundingClientRect();
			if (rowRect.bottom <= rowRect.top) continue;
			if (rowRect.top >= viewportTop && rowRect.top < viewportBottom) return lineNumber;
		}
	}
	#focusAtPosition(position, preventScroll) {
		const selection = {
			start: position,
			end: position,
			direction: 0
		};
		this.#canMountSelectionAction = false;
		this.#updateSelections([selection]);
		this.#revealLineIfCollapsed(position.line);
		if (preventScroll) this.#focus(position, true);
		else this.#scrollToPrimaryCaret();
	}
	#setWindowSelection(selection) {
		const winSelection = window.getSelection();
		if (winSelection === null) return;
		let { start, end, direction } = selection;
		if (comparePosition(start, end) > 0) [start, end] = [end, start];
		const startLineElement = this.#getLineElement(start.line);
		const endLineElement = this.#getLineElement(end.line);
		if (startLineElement === void 0 || endLineElement === void 0) return;
		let [anchorNode, anchorOffset] = getSelectionAnchor(startLineElement, start.character);
		let [focusNode, focusOffset] = getSelectionAnchor(endLineElement, end.character);
		if (direction === -1) [anchorNode, anchorOffset, focusNode, focusOffset] = [
			focusNode,
			focusOffset,
			anchorNode,
			anchorOffset
		];
		try {
			winSelection.setBaseAndExtent(anchorNode, clampDomOffset(anchorNode, anchorOffset), focusNode, clampDomOffset(focusNode, focusOffset));
		} catch (err) {
			console.error("[diffs/editor] failed to update window selection:", err);
		}
	}
	#scrollToPrimaryCaret(noFocus = false, scrollPosition = "nearest") {
		const primarySelection = this.#selections?.at(-1);
		if (primarySelection === void 0) return;
		const primaryCaretElement = this.#primaryCaretElement;
		if (primaryCaretElement !== void 0) {
			primaryCaretElement.scrollIntoView({
				block: scrollPosition,
				inline: "nearest"
			});
			if (!noFocus) {
				const position = primarySelection.direction === -1 ? primarySelection.end : primarySelection.start;
				if (this.#replacementFocusRequest !== void 0) this.#restoreReplacementFocus(position);
				else this.#focus(position);
			}
		} else {
			const pos = getCaretPosition(primarySelection);
			this.#scrollToLine(pos.line, pos.character, noFocus);
		}
	}
	#getScrollMargin() {
		const top = this.#searchPanel !== void 0 ? 48 : 0;
		const start = this.#getGutterWidth() + this.#metrics.ch;
		return `${top}px ${this.#metrics.ch}px 0 ${start}px`;
	}
	#scrollToLine(line, char = 0, noFocus = false) {
		this.__postponeBgTokenizeToNextFrame();
		const virtualCaret = h("div", { style: {
			position: "absolute",
			left: "0",
			width: "2px",
			height: this.#metrics.lineHeight + "px",
			scrollMargin: this.#getScrollMargin()
		} });
		if (this.#getLineElement(line) !== void 0) {
			const [left, wrapLine] = this.#getCharX(line, char);
			const lineY = this.#getLineY(line) + wrapLine * this.#metrics.lineHeight;
			virtualCaret.style.top = lineY + "px";
			virtualCaret.style.left = left + "px";
			this.#overlayElement?.appendChild(virtualCaret);
			virtualCaret.scrollIntoView({
				block: "center",
				inline: "nearest"
			});
			if (!noFocus) {
				const position = {
					line,
					character: char
				};
				if (this.#replacementFocusRequest !== void 0) this.#restoreReplacementFocus(position);
				else this.#focus(position);
			}
			this.#scrollingToLine = void 0;
			this.#scrollingToLineChar = void 0;
			this.#scrollingToLineFixed = false;
			this.#scrollingToLineNoFocus = false;
		} else {
			const modelLinePosition = this.#fileInstance?.getLinePosition?.(line + 1);
			if (modelLinePosition !== void 0) {
				virtualCaret.style.top = modelLinePosition.top + "px";
				this.#fileContainer?.shadowRoot?.appendChild(virtualCaret);
				virtualCaret.scrollIntoView({
					block: "center",
					inline: "nearest"
				});
				if (modelLinePosition.height > 0 && this.#isLineRenderable(line)) {
					this.#scrollingToLine = line;
					this.#scrollingToLineChar = char;
					this.#scrollingToLineNoFocus = noFocus;
				} else {
					this.#scrollingToLine = void 0;
					this.#scrollingToLineChar = void 0;
					this.#scrollingToLineNoFocus = false;
				}
			} else {
				let yFix = 0;
				if (this.#scrollingToLine === line && this.#contentElement !== void 0) for (let i = this.#contentElement.childElementCount - 1; i >= 0; i--) {
					const child = this.#contentElement.children[i];
					const lineType = child.dataset.lineType;
					const lineNumber = getLineNumberAttr(child);
					if (lineType !== void 0 && isLineEditable(lineType) && lineNumber !== void 0) {
						yFix = (line - (lineNumber - 1)) * this.#metrics.lineHeight;
						break;
					}
				}
				const approximateLineY = ((this.#lineAnnotations ?? []).filter((annotation) => annotation.lineNumber < line).length + line) * this.#metrics.lineHeight + yFix;
				virtualCaret.style.top = approximateLineY + "px";
				this.#fileContainer?.shadowRoot?.appendChild(virtualCaret);
				virtualCaret.scrollIntoView({
					block: "center",
					inline: "nearest"
				});
				if (this.#scrollingToLine === line && (yFix === 0 || this.#scrollingToLineFixed) || !this.#isLineRenderable(line)) {
					this.#scrollingToLine = void 0;
					this.#scrollingToLineChar = void 0;
					this.#scrollingToLineFixed = false;
					this.#scrollingToLineNoFocus = false;
				} else {
					this.#scrollingToLine = line;
					this.#scrollingToLineChar = char;
					this.#scrollingToLineFixed = yFix !== 0;
					this.#scrollingToLineNoFocus = noFocus;
				}
			}
		}
		virtualCaret.remove();
	}
	#spanLineSelection(anchorLine, focusLine, textDocument) {
		const lineStart = (line) => ({
			line,
			character: 0
		});
		const lineEnd = (line) => ({
			line,
			character: textDocument.getLineText(line).length
		});
		if (focusLine < anchorLine) return {
			start: lineStart(focusLine),
			end: lineEnd(anchorLine),
			direction: -1
		};
		return {
			start: lineStart(anchorLine),
			end: lineEnd(focusLine),
			direction: 1
		};
	}
	#isDeletedLineTarget(event) {
		const target = event.composedPath()[0];
		return target instanceof HTMLElement && target.closest("[data-line]")?.getAttribute("data-line-type") === "change-deletion";
	}
	#selectDeletedLines(anchorContent, focusContent, deletionsCode) {
		const rows = [...deletionsCode.querySelectorAll("[data-content] > [data-line]")];
		const anchorIndex = rows.indexOf(anchorContent);
		const focusIndex = rows.indexOf(focusContent);
		const [topContent, bottomContent] = focusIndex < anchorIndex ? [focusContent, anchorContent] : [anchorContent, focusContent];
		const winSelection = window.getSelection();
		if (winSelection !== null) {
			const range = document.createRange();
			range.setStart(topContent, 0);
			range.setEnd(bottomContent, bottomContent.childNodes.length);
			winSelection.removeAllRanges();
			winSelection.addRange(range);
		}
		this.#setDeletedTextSelectionActive(true);
		this.#updateSelections([]);
		this.#setEditorActiveLineSafe(getLineNumberAttr(focusContent) ?? null, true, "deletions");
		const lo = Math.min(anchorIndex, focusIndex);
		const hi = Math.max(anchorIndex, focusIndex);
		this.#deletedSelectionText = lo < 0 ? "" : rows.slice(lo, hi + 1).filter((row) => row.getAttribute("data-line-type") === "change-deletion").map((row) => row.textContent ?? "").join("\n");
	}
	#contentRowForGutterRow(gutterRow, contentColumn) {
		const gutterColumn = gutterRow.parentElement;
		if (gutterColumn == null || contentColumn == null) return;
		const index = [...gutterColumn.children].indexOf(gutterRow);
		const row = contentColumn.children[index];
		return row instanceof HTMLElement ? row : void 0;
	}
	#beginDeletionGutterSelection(gutterRow, code, isMouse) {
		const contentColumn = code.querySelector("[data-content]");
		const anchorContent = this.#contentRowForGutterRow(gutterRow, contentColumn);
		if (anchorContent === void 0) return false;
		this.#selectDeletedLines(anchorContent, anchorContent, code);
		if (isMouse) this.#replaceSelectEventListeners([addEventListener(document, "mousemove", (moveEvent) => {
			const moveTarget = moveEvent.composedPath()[0];
			const moveGutter = moveTarget instanceof HTMLElement ? moveTarget.closest("[data-column-number]") : null;
			if (moveGutter instanceof HTMLElement && code.contains(moveGutter)) {
				const focusContent = this.#contentRowForGutterRow(moveGutter, contentColumn);
				if (focusContent !== void 0) this.#selectDeletedLines(anchorContent, focusContent, code);
			}
		}, { passive: true })]);
		return true;
	}
	#isDeletedTextSelectionActive() {
		return this.#fileContainer?.shadowRoot?.querySelector("pre")?.hasAttribute("data-deleted-text-selection") ?? false;
	}
	#deletedTextForClipboard() {
		return this.#deletedSelectionText !== "" ? this.#deletedSelectionText : window.getSelection()?.toString() ?? "";
	}
	#setDeletedTextSelectionActive(active) {
		const pre = this.#fileContainer?.shadowRoot?.querySelector("pre");
		if (pre == null) return;
		if (active) {
			pre.setAttribute("data-deleted-text-selection", "");
			this.#setEditorActiveLineSafe(null);
			this.#deletedSelectionText = "";
		} else {
			pre.removeAttribute("data-deleted-text-selection");
			this.#deletedSelectionText = "";
		}
	}
	#setEditorActiveLineSafe(lineNumber, lineNumberOnly = false, side = "additions") {
		try {
			this.#fileInstance?.setEditorActiveLine(lineNumber, {
				lineNumberOnly,
				side
			});
		} catch {}
	}
	#scheduleThemeSelectionRefresh() {
		if (this.#themeSelectionRefreshFrame !== void 0) return;
		this.#themeSelectionRefreshFrame = requestAnimationFrame(() => {
			this.#themeSelectionRefreshFrame = void 0;
			if (this.#selections !== void 0 || this.#matches !== void 0 || this.#markerRenderer !== void 0) this.#updateSelections(this.#selections ?? []);
		});
	}
	#updateSelections(selections) {
		this.__postponeBgTokenizeToNextFrame();
		this.#primaryCaretElement = void 0;
		this.#setEditorActiveLineSafe(null);
		if (selections.length === 0 && this.#matches === void 0 && this.#markerRenderer === void 0) {
			this.#selections = void 0;
			this.#overlayElements?.forEach((el) => el.remove());
			this.#overlayElements?.clear();
			this.#selectionAction?.cleanup();
			this.#selectionAction = void 0;
			return;
		}
		const fragment = document.createDocumentFragment();
		const renderCtx = {
			fragment,
			elements: /* @__PURE__ */ new Map()
		};
		if (selections.length > 0) {
			const normalizedSelections = mergeOverlappingSelections(selections);
			const primarySelection = normalizedSelections.at(-1);
			this.#selections = normalizedSelections;
			const hasNonEmptySelection = normalizedSelections.some((selection) => !isCollapsedSelection(selection));
			const caretLine = getCaretPosition(primarySelection).line + 1;
			this.#setEditorActiveLineSafe(caretLine, hasNonEmptySelection);
			for (const selection of normalizedSelections) {
				if (!isCollapsedSelection(selection)) this.#renderSelection(renderCtx, "selection", selection);
				this.#renderCaret(renderCtx, selection, selection === primarySelection);
			}
			const bracketMatchRanges = this.#options.matchBrackets !== false && this.#textDocument !== void 0 && this.#tokenizer !== void 0 && isCollapsedSelection(primarySelection) ? findBracketMatchRanges(this.#textDocument, this.#tokenizer, primarySelection.start) : void 0;
			if (bracketMatchRanges !== void 0) for (const range of bracketMatchRanges) this.#renderSelection(renderCtx, "bracketMatch", range);
		}
		const textDocument = this.#textDocument;
		if (this.#matches !== void 0 && textDocument !== void 0) {
			const matches = this.#matches;
			const renderRange = this.#renderRange;
			const renderedLineRanges = renderRange !== void 0 && Number.isFinite(renderRange.totalLines) || this.#isDiff && this.#fileInstance?.options.expandUnchanged !== true ? this.#getRenderedEditableLineRanges() : void 0;
			const primarySelection = this.#selections?.at(-1);
			const primaryStartOffset = primarySelection !== void 0 ? textDocument.offsetAt(primarySelection.start) : -1;
			const primaryEndOffset = primarySelection !== void 0 ? textDocument.offsetAt(primarySelection.end) : -1;
			let firstMatchIndex = 0;
			const rangeCount = renderedLineRanges?.length ?? 1;
			for (let rangeIndex = 0; rangeIndex < rangeCount; rangeIndex++) {
				let visibleEndOffset = Infinity;
				const lineRange = renderedLineRanges?.[rangeIndex];
				if (lineRange !== void 0) {
					const [firstLine, lastLine] = lineRange;
					const visibleStartOffset = textDocument.offsetAt({
						line: firstLine,
						character: 0
					});
					const endLine = lastLine + 1;
					visibleEndOffset = endLine < textDocument.lineCount ? textDocument.offsetAt({
						line: endLine,
						character: 0
					}) : textDocument.offsetAt({
						line: endLine - 1,
						character: textDocument.getLineLength(endLine - 1)
					});
					let low = firstMatchIndex;
					let high = matches.length;
					while (low < high) {
						const middle = low + Math.floor((high - low) / 2);
						if (matches[middle][1] <= visibleStartOffset) low = middle + 1;
						else high = middle;
					}
					firstMatchIndex = low;
				}
				for (; firstMatchIndex < matches.length; firstMatchIndex++) {
					const [startOffset, endOffset] = matches[firstMatchIndex];
					if (startOffset >= visibleEndOffset) break;
					const range = {
						start: textDocument.positionAt(startOffset),
						end: textDocument.positionAt(endOffset)
					};
					const isFocused = primaryStartOffset === startOffset && primaryEndOffset === endOffset;
					this.#renderSelection(renderCtx, "match", range, isFocused ? "focus" : void 0);
				}
			}
		}
		if (this.#markerRenderer !== void 0 && textDocument !== void 0) for (const marker of this.#markerRenderer.markers) this.#renderSelection(renderCtx, "marker", marker, markerSeverityDatasetKey(marker.severity));
		this.#overlayElement?.appendChild(fragment);
		this.#overlayElements?.forEach((el) => el.remove());
		this.#overlayElements?.clear();
		this.#overlayElements = renderCtx.elements;
		this.#updateSelectionActionPopover();
	}
	#renderSelection(renderCtx, type, range, extraDataset) {
		if (this.#textDocument === void 0) return;
		const { start, end } = range;
		let firstLine = start.line;
		let endLine = end.line + 1;
		if (this.#renderRange !== void 0) {
			const { startingLine, totalLines } = this.#renderRange;
			firstLine = Math.max(firstLine, startingLine);
			endLine = Math.min(endLine, startingLine + totalLines);
		}
		for (let line = firstLine; line < endLine; line++) {
			if (!this.#isLineVisible(line)) continue;
			const isLastLine = line === end.line;
			const startChar = line === start.line ? start.character : 0;
			const endChar = isLastLine ? end.character : this.#textDocument.getLineLength(line);
			if (this.#isWrap) {
				const contentWidth = this.#getContentWidth();
				const lineText = this.#textDocument.getLineText(line);
				if (2 * this.#metrics.ch + this.#metrics.measureTextWidth(lineText) > contentWidth) {
					this.#renderWrappedSelection(renderCtx, line, lineText, startChar, endChar, isLastLine, type, extraDataset);
					continue;
				}
			}
			let left = 0;
			let width = 0;
			let paddingEnd = 0;
			if (startChar === 0) left = this.#getGutterWidth() + this.#metrics.ch + (this.#activeContentOffset?.left ?? 0);
			else left = this.#getCharX(line, startChar)[0];
			if (!isLastLine && type === "selection") paddingEnd = this.#metrics.ch;
			if (startChar === endChar) width = paddingEnd;
			else width = this.#getCharX(line, endChar)[0] - left + paddingEnd;
			this.#renderSelectionBlock(renderCtx, type, line, 0, left, width, extraDataset);
		}
	}
	#renderWrappedSelection(renderCtx, line, lineText, startChar, endChar, isLastLine, type, extraDataset) {
		const wrapOffsets = this.#wrapLineTextOrWholeLine(line);
		const segmentCount = wrapOffsets.length - 1;
		const offsetLeft = this.#getGutterWidth() + this.#metrics.ch + (this.#activeContentOffset?.left ?? 0);
		for (let wrapLine = 0; wrapLine < segmentCount; wrapLine++) {
			const segmentStart = wrapOffsets[wrapLine];
			const segmentEnd = wrapOffsets[wrapLine + 1];
			const wrapStartChar = Math.max(startChar, segmentStart);
			const wrapEndChar = Math.min(endChar, segmentEnd);
			if (wrapStartChar > wrapEndChar) continue;
			const segmentStartWidth = this.#segmentTextWidth(lineText, segmentStart, wrapStartChar);
			const segmentLeft = offsetLeft + segmentStartWidth;
			let paddingEnd = 0;
			if (!isLastLine && wrapLine === segmentCount - 1 && type === "selection") paddingEnd = this.#metrics.ch;
			const segmentWidth = wrapStartChar === wrapEndChar ? paddingEnd : this.#segmentTextWidth(lineText, segmentStart, wrapEndChar) - segmentStartWidth + paddingEnd;
			this.#renderSelectionBlock(renderCtx, type, line, wrapLine, segmentLeft, segmentWidth, extraDataset);
		}
	}
	#segmentTextWidth(lineText, segmentStart, character) {
		if (character <= segmentStart) return 0;
		const segmentText = lineText.slice(segmentStart, character);
		const asciiColumns = getExpandedAsciiTextColumns(segmentText, this.#metrics.tabSize);
		return asciiColumns !== -1 ? asciiColumns * this.#metrics.ch : this.#metrics.measureTextWidth(segmentText);
	}
	#renderSelectionBlock(renderCtx, type, line, wrapLine, left, width, extraDataset) {
		if (width === 0) return;
		const { ch, lineHeight } = this.#metrics;
		const y = this.#getLineY(line) + wrapLine * lineHeight;
		const cacheKey = `${type}-${line}/${wrapLine}-${left}-${width} ${extraDataset ?? ""}`;
		const overlayEls = this.#overlayElements;
		const rounded = (this.#options.roundedSelection ?? true) && type === "selection";
		const addRoundedCorner = (line, wrapLine, left, radius) => {
			const top = this.#getLineY(line) + wrapLine * lineHeight;
			const lineElement = this.#getLineElement(line);
			let cornerBg = "initial";
			if (lineElement !== void 0 && (lineElement.dataset.lineType === "change-addition" || lineElement.dataset.selectedLine !== void 0)) cornerBg = getComputedStyle(lineElement).getPropertyValue("--diffs-line-bg");
			const css = `width:${ch}px;transform:translateX(${left}px) translateY(${top}px);--diffs-selection-corner-bg:${cornerBg}`;
			const dataset = {
				selectionCorner: "",
				[radius]: ""
			};
			const cacheKeyPrefix = `${type}-block-${line}/${wrapLine}-${left}-1ch`;
			let cacheKey = cacheKeyPrefix + "-" + radius;
			if (radius === "rbl") {
				const prevCornerKey = cacheKeyPrefix + "-rtl";
				const prevCorner = renderCtx.elements.get(prevCornerKey);
				if (prevCorner !== void 0) {
					prevCorner.remove();
					renderCtx.elements.delete(prevCornerKey);
					cacheKey += "-rtl";
					dataset.rtl = "";
				}
			}
			let cornerEl = renderCtx.elements.get(cacheKey);
			if (cornerEl !== void 0) return;
			if (overlayEls?.has(cacheKey) === true) {
				cornerEl = overlayEls.get(cacheKey);
				cornerEl.style.cssText = css;
				overlayEls.delete(cacheKey);
			} else cornerEl = h("div", {
				dataset: "selectionRange",
				style: { cssText: css },
				children: [h("div", { dataset })]
			}, renderCtx.fragment);
			renderCtx.elements.set(cacheKey, cornerEl);
		};
		const addRadiusStyle = (element) => {
			const end = left + width;
			const dataset = element.dataset;
			const previousSelectionRange = renderCtx.previousSelectionRange;
			if (previousSelectionRange === void 0 || previousSelectionRange.line !== line || previousSelectionRange.wrapLine !== wrapLine) renderCtx.previousSelectionRange = {
				element,
				line,
				wrapLine,
				left,
				width
			};
			if (previousSelectionRange === void 0 || end <= previousSelectionRange.left) [
				"rtl",
				"rtr",
				"rbl",
				"rbr"
			].forEach((key) => {
				dataset[key] = "";
			});
			else {
				const prevLine = previousSelectionRange.line;
				const prevWrapLine = previousSelectionRange.wrapLine;
				const prevLeft = previousSelectionRange.left;
				const prevDataset = previousSelectionRange.element.dataset;
				const prevEnd = prevLeft + previousSelectionRange.width;
				if (prevLeft > left) addRoundedCorner(prevLine, prevWrapLine, prevLeft - ch, "rbr");
				delete prevDataset.rbl;
				delete dataset.rtl;
				delete dataset.rtr;
				if (end >= prevEnd) delete prevDataset.rbr;
				if (end > prevEnd) {
					addRoundedCorner(prevLine, prevWrapLine, prevEnd, "rbl");
					dataset.rtr = "";
				}
				if (end < prevEnd) addRoundedCorner(line, wrapLine, end, "rtl");
				if (left < prevLeft) dataset.rtl = "";
				dataset.rbl = "";
				dataset.rbr = "";
			}
		};
		let rangeEl = renderCtx.elements.get(cacheKey);
		if (rangeEl !== void 0) {
			if (rounded) addRadiusStyle(rangeEl);
			return;
		}
		if (overlayEls?.has(cacheKey) === true) {
			rangeEl = overlayEls.get(cacheKey);
			overlayEls.delete(cacheKey);
		} else rangeEl = h("div", { dataset: extraDataset ? [type + "Range", extraDataset] : type + "Range" }, renderCtx.fragment);
		rangeEl.style.width = `${width}px`;
		rangeEl.style.transform = `translateX(${left}px) translateY(${y}px)`;
		if (rounded) addRadiusStyle(rangeEl);
		renderCtx.elements.set(cacheKey, rangeEl);
	}
	#renderCaret(renderCtx, selection, isPrimary) {
		const { line, character } = getCaretPosition(selection);
		if (!this.#isLineVisible(line)) return;
		const [left, wrapLine] = this.#getCharX(line, character);
		const cacheKey = "caret-" + line + "/" + wrapLine + ":" + character;
		if (renderCtx.elements.has(cacheKey)) return;
		const caretEl = h("div", {
			dataset: "caret",
			style: { transform: `translateX(${left - 1}px) translateY(${this.#getLineY(line) + wrapLine * this.#metrics.lineHeight}px)` }
		}, renderCtx.fragment);
		renderCtx.elements.set(cacheKey, caretEl);
		if (isPrimary) {
			caretEl.style.scrollMargin = this.#getScrollMargin();
			this.#primaryCaretElement = caretEl;
		}
	}
	#updateSelectionActionPopover() {
		const primarySelection = this.#selections?.at(-1);
		const overlayElement = this.#overlayElement;
		const textDocument = this.#textDocument;
		const renderSelectionAction = this.#options.renderSelectionAction;
		const cleanup = () => {
			this.#selectionAction?.cleanup();
			this.#selectionAction = void 0;
		};
		if (this.#options.enabledSelectionAction !== true || renderSelectionAction === void 0 || primarySelection === void 0 || isCollapsedSelection(primarySelection) || this.#isContentMouseDown || overlayElement === void 0 || textDocument === void 0) {
			cleanup();
			return;
		}
		const head = getCaretPosition(primarySelection);
		if (!this.#isLineVisible(head.line)) {
			cleanup();
			return;
		}
		if (this.#selectionAction === void 0) {
			if (!this.#canMountSelectionAction) return;
			const getActiveSelection = () => this.#selections?.at(-1) ?? primarySelection;
			const selectionActionElement = renderSelectionAction({
				textDocument,
				get selection() {
					return getActiveSelection();
				},
				applyEdits: (edits) => this.applyEdits(edits),
				getSelectionText: () => this.#textDocument?.getText(getActiveSelection()) ?? "",
				replaceSelectionText: (text) => {
					this.#replaceSelectionText(text, [getActiveSelection()]);
				},
				close: () => {
					cleanup();
					this.#scrollToPrimaryCaret();
				}
			});
			this.#selectionAction = new SelectionActionWidget(selectionActionElement, overlayElement, () => this.#updateSelectionActionPopover());
			this.#getPopoverManager().resetPlacement(SELECTION_ACTION_POPOVER_PLACEMENT_KEY);
		}
		const lineHeight = this.#metrics.lineHeight;
		const isBackward = primarySelection.direction === -1;
		const preferred = {
			placeAbove: isBackward,
			anchor: head
		};
		const fallback = isBackward ? {
			placeAbove: false,
			anchor: primarySelection.end
		} : {
			placeAbove: true,
			anchor: primarySelection.start
		};
		const popoverHeight = this.#selectionAction.height;
		const candidateGeometry = (candidate) => {
			const [left, candidateWrapLine] = this.#getCharX(candidate.anchor.line, candidate.anchor.character);
			const rowTop = this.#getLineY(candidate.anchor.line) + candidateWrapLine * lineHeight;
			const anchorTop = candidate.placeAbove ? rowTop : rowTop + lineHeight;
			const top = candidate.placeAbove ? anchorTop - popoverHeight : anchorTop;
			return {
				top,
				bottom: top + popoverHeight,
				left,
				anchorTop,
				rowTop
			};
		};
		const preferredGeometry = candidateGeometry(preferred);
		const lineCount = textDocument.lineCount;
		const atDocumentEdge = isBackward ? head.line < 3 : head.line >= lineCount - 3;
		const fallbackGeometry = this.#isLineVisible(fallback.anchor.line) ? candidateGeometry(fallback) : void 0;
		const popoverManager = this.#getPopoverManager();
		const viewport = popoverManager.getPlacementBounds();
		const useFallback = fallbackGeometry !== void 0 && popoverManager.choosePlacement({
			preferred: preferredGeometry,
			fallback: fallbackGeometry,
			viewport,
			popoverHeight,
			atDocumentEdge,
			placementKey: SELECTION_ACTION_POPOVER_PLACEMENT_KEY
		}) === "fallback";
		if (fallbackGeometry === void 0) popoverManager.setPlacement("preferred", SELECTION_ACTION_POPOVER_PLACEMENT_KEY);
		const { placeAbove } = useFallback ? fallback : preferred;
		const { left, anchorTop } = useFallback && fallbackGeometry !== void 0 ? fallbackGeometry : preferredGeometry;
		const selectionTop = isBackward ? preferredGeometry.rowTop : fallbackGeometry?.rowTop ?? -Infinity;
		const selectionBottom = (isBackward ? fallbackGeometry?.rowTop ?? Infinity : preferredGeometry.rowTop) + (primarySelection.end.line > primarySelection.start.line && primarySelection.end.character === 0 ? 0 : lineHeight);
		const isSelectionVisible = viewport === void 0 || selectionBottom > viewport.top && selectionTop < viewport.bottom;
		this.#selectionAction.reposition(left, anchorTop, this.#getGutterWidth(), placeAbove, isSelectionVisible, viewport);
	}
	#openSearchPanel(mode) {
		if (this.#searchPanel !== void 0) {
			this.#searchPanel.setMode(mode);
			return;
		}
		this.#renderSearchPanel(mode);
	}
	#renderSearchPanel(mode) {
		this.#searchPanel?.cleanup();
		const textDocument = this.#textDocument;
		const preElement = this.#fileContainer?.shadowRoot?.querySelector("pre");
		const selections = this.#selections;
		if (textDocument === void 0 || preElement == null) return;
		let defaultQuery = "";
		let initialMatch = void 0;
		if (selections !== void 0 && selections.length > 0) {
			let primarySelection = selections.at(-1);
			if (isCollapsedSelection(primarySelection)) {
				primarySelection = expandCollapsedSelectionToWord(textDocument, primarySelection);
				this.#updateSelections([...selections.slice(0, -1), primarySelection]);
				const selectionText = textDocument.getText(primarySelection);
				if (selectionText !== "" && !selectionText.includes("\n")) {
					defaultQuery = selectionText;
					initialMatch = [textDocument.offsetAt(primarySelection.start), textDocument.offsetAt(primarySelection.end)];
				}
			}
		}
		const scrollToMatch = ([startOffset, endOffset], retainFocus) => {
			const nextSelection = createSelectionFromAnchorAndFocusOffsets(textDocument, startOffset, endOffset);
			this.#updateSelections([nextSelection]);
			this.#revealLineIfCollapsed(getCaretPosition(nextSelection).line);
			this.#scrollToPrimaryCaret(true);
			this.#retainSearchPanelFocus = retainFocus;
		};
		const searchPanel = new SearchPanelWidget({
			textDocument,
			containerElement: preElement,
			defaultQuery,
			mode,
			initialMatch,
			scrollToMatch,
			applyReplace: (edits) => {
				if (edits.length === 0) return;
				const change = textDocument.applyEdits(edits.map((edit) => ({
					range: {
						start: textDocument.positionAt(edit.start),
						end: textDocument.positionAt(edit.end)
					},
					newText: edit.text
				})), true, this.#selections);
				if (change !== void 0) this.#applyChange(change, void 0, this.#applyChangeToLineAnnotations(change), { skipSearchRefresh: true });
			},
			onUpdate: (allMatches, options) => {
				if (allMatches.length === 0) {
					this.#matches = void 0;
					this.#updateSelections(this.#selections ?? []);
					return;
				}
				this.#matches = allMatches;
				if (options?.syncSelection === false) {
					this.#updateSelections(this.#selections ?? []);
					const primarySelection = this.#selections?.at(-1);
					if (primarySelection !== void 0) {
						const startOffset = textDocument.offsetAt(primarySelection.start);
						const endOffset = textDocument.offsetAt(primarySelection.end);
						for (const match of allMatches) if (match[0] === startOffset && match[1] === endOffset) return match;
					}
					return;
				}
				const primarySelection = this.#selections?.at(-1);
				let searchOffset = 0;
				let nextMatch;
				if (primarySelection !== void 0) searchOffset = textDocument.offsetAt(primarySelection.start);
				for (const m of allMatches) if (m[0] >= searchOffset) {
					nextMatch = m;
					break;
				}
				if (nextMatch !== void 0) scrollToMatch(nextMatch, true);
				else this.#updateSelections(this.#selections ?? []);
				return nextMatch;
			},
			onClose: () => {
				this.#searchPanel = void 0;
				this.#retainSearchPanelFocus = false;
				this.#matches = void 0;
				this.#updateSelections(this.#selections ?? []);
			}
		});
		this.#searchPanel = searchPanel;
		this.#retainSearchPanelFocus = false;
	}
	#getSelectionText() {
		const textDocument = this.#textDocument;
		const selections = this.#selections;
		if (textDocument === void 0 || selections === void 0) return "";
		return getSelectionText(textDocument, selections);
	}
	#getSelectionClipboardTexts() {
		const textDocument = this.#textDocument;
		const selections = this.#selections;
		if (textDocument === void 0 || selections === void 0) return [];
		return getSelectionClipboardTexts(textDocument, selections);
	}
	/** Writes both the portable text and the selection pairing metadata. */
	#writeSelectionClipboardData(clipboardData, text, selectionTexts) {
		if (clipboardData === null) return;
		clipboardData.setData("text", text);
		if (selectionTexts.length > 1) clipboardData.setData(MULTI_SELECTION_CLIPBOARD_TYPE, JSON.stringify(selectionTexts));
	}
	#cutSelectionText() {
		const textDocument = this.#textDocument;
		const selections = this.#selections;
		if (textDocument === void 0 || selections === void 0 || selections.length === 0) return "";
		if (selections.some((selection) => isCollapsedSelection(selection))) {
			const cut = resolveSelectionCut(textDocument, selections);
			this.#applySelectionCutEdits(cut.edits, cut.nextSelectionOffsets);
			return cut.text;
		}
		const text = getSelectionText(textDocument, selections);
		this.#replaceSelectionText("", void 0, true);
		return text;
	}
	#applySelectionCutEdits(edits, nextSelectionOffsets) {
		const textDocument = this.#textDocument;
		const selections = this.#selections;
		if (textDocument === void 0 || selections === void 0 || edits.length === 0) return;
		const change = textDocument.applyResolvedEdits(edits, true, selections, void 0, true);
		if (change === void 0) return;
		const nextSelections = nextSelectionOffsets.map((offset) => {
			const caret = textDocument.positionAt(offset);
			return {
				start: caret,
				end: caret,
				direction: 0
			};
		});
		textDocument.setLastUndoSelectionsAfter(nextSelections);
		this.#applyChange(change, nextSelections, this.#applyChangeToLineAnnotations(change));
	}
	#replaceSelectionText(text, selections = this.#selections, undoBoundary = false, textOrder = "selection") {
		if (selections === void 0) return;
		const textDocument = this.#textDocument;
		const primarySelection = selections.at(-1);
		if (textDocument === void 0 || primarySelection === void 0) return;
		const { nextSelections, change } = Array.isArray(text) && text.length === selections.length ? applyTextReplaceToSelections(textDocument, selections, text, this.#lineAnnotations, undoBoundary, textOrder) : applyTextChangeToSelections(textDocument, selections, {
			start: textDocument.offsetAt(primarySelection.start),
			end: textDocument.offsetAt(primarySelection.end),
			text: Array.isArray(text) ? text.join(textDocument.eol) : text
		}, this.#lineAnnotations, void 0, undoBoundary);
		if (change !== void 0) this.#applyChange(change, nextSelections, this.#applyChangeToLineAnnotations(change));
	}
	#deleteSelectionText(forward = false) {
		const selections = this.#selections;
		const textDocument = this.#textDocument;
		if (selections === void 0 || textDocument === void 0) return;
		const { nextSelections, change } = applyDeleteCharacterToSelections(textDocument, selections, forward, this.#lineAnnotations, this.#metrics.tabSize);
		if (change !== void 0) this.#applyChange(change, nextSelections, this.#applyChangeToLineAnnotations(change));
	}
	#deleteSoftLineBackward() {
		const selections = this.#selections;
		const textDocument = this.#textDocument;
		if (selections === void 0 || textDocument === void 0) return;
		const { nextSelections, change } = applyDeleteSoftLineBackwardToSelections(textDocument, selections, this.#isWrap ? (line, character) => {
			const wrapOffsets = this.#wrapLineTextOrWholeLine(line);
			for (let w = 0; w + 1 < wrapOffsets.length; w++) {
				const segmentStart = wrapOffsets[w];
				const segmentEnd = wrapOffsets[w + 1];
				if (character >= segmentStart && character <= segmentEnd) return segmentStart;
			}
			return 0;
		} : void 0, this.#lineAnnotations);
		if (change !== void 0) this.#applyChange(change, nextSelections, this.#applyChangeToLineAnnotations(change));
	}
	#deleteWordBackward() {
		const selections = this.#selections;
		const textDocument = this.#textDocument;
		if (selections === void 0 || textDocument === void 0) return;
		const { nextSelections, change } = applyDeleteWordBackwardToSelections(textDocument, selections, this.#lineAnnotations);
		if (change !== void 0) this.#applyChange(change, nextSelections, this.#applyChangeToLineAnnotations(change));
	}
	#deleteHardLineForward() {
		const selections = this.#selections;
		const textDocument = this.#textDocument;
		if (selections === void 0 || textDocument === void 0) return;
		const { nextSelections, change } = applyDeleteHardLineForwardToSelections(textDocument, selections, this.#lineAnnotations);
		if (change !== void 0) this.#applyChange(change, nextSelections, this.#applyChangeToLineAnnotations(change));
	}
	#insertTranspose() {
		const selections = this.#selections;
		const textDocument = this.#textDocument;
		if (selections === void 0 || textDocument === void 0) return;
		const { nextSelections, change } = applyTransposeToSelections(textDocument, selections, this.#lineAnnotations);
		if (change !== void 0) this.#applyChange(change, nextSelections, this.#applyChangeToLineAnnotations(change));
	}
	#applyChange(change, newSelections, newLineAnnotations, options) {
		const fileRef = this.getFile();
		const onChange = this.#options.onChange;
		if (fileRef !== void 0 && onChange !== void 0) {
			const lineAnnotations = newLineAnnotations ?? this.#lineAnnotations;
			onChange(fileRef, lineAnnotations, {
				changes: change.changes,
				file: fileRef,
				lineAnnotations
			});
		}
		if (change.lineDelta !== 0 || this.#isWrap) {
			for (const line of this.#lineYCache.keys()) if (line >= change.startLine) this.#lineYCache.delete(line);
		}
		if (this.#wrapLineOffsetsCache.size > 0) {
			if (change.lineDelta === 0 && (change.changedLineRanges.length === 1 || change.changedLineChanges?.every(([, , editLineDelta]) => editLineDelta === 0) === true)) for (const [rangeStart, rangeEnd] of change.changedLineRanges) for (let line = rangeStart; line <= rangeEnd; line++) this.#wrapLineOffsetsCache.delete(line);
			else for (const line of this.#wrapLineOffsetsCache.keys()) if (line >= change.startLine) this.#wrapLineOffsetsCache.delete(line);
		}
		this.#lastAccessedCharX = void 0;
		let renderRange = this.#renderRange;
		let shouldUpdateBuffer;
		if (renderRange !== void 0 && newSelections !== void 0 && newSelections.length > 0) {
			const primarySelection = newSelections.at(-1);
			const renderRangeEndLine = renderRange.startingLine + renderRange.totalLines;
			if (primarySelection.end.line >= renderRangeEndLine) {
				const widenedTotalLines = primarySelection.end.line - renderRange.startingLine + 1;
				const maxWidenLines = this.#viewportWindowLines === void 0 || this.#viewportWindowLines === Infinity ? Infinity : this.#viewportWindowLines * MAX_EDIT_WIDEN_WINDOW_MULTIPLE;
				if (change.startLine <= renderRangeEndLine && widenedTotalLines <= maxWidenLines && this.#isLineRenderable(primarySelection.end.line)) {
					if (primarySelection.end.line > renderRangeEndLine) shouldUpdateBuffer = true;
					renderRange = {
						...renderRange,
						totalLines: widenedTotalLines
					};
					this.#renderRange = renderRange;
				} else shouldUpdateBuffer = true;
			}
		}
		this.#rerender(change, newLineAnnotations, renderRange, shouldUpdateBuffer);
		if (options?.skipSearchRefresh !== true && this.#searchPanel !== void 0 && this.#matches !== void 0) this.#searchPanel.updateMatches({ syncSelection: false });
		if (newSelections !== void 0) {
			this.#updateSelections(newSelections);
			if (options?.skipFocus !== true) {
				const revealTarget = newSelections.at(-1);
				if (revealTarget !== void 0) this.#revealLineIfCollapsed(getCaretPosition(revealTarget).line);
				if (this.#primaryCaretElement !== void 0) requestAnimationFrame(() => {
					this.#primaryCaretElement?.scrollIntoView({
						block: "nearest",
						inline: "nearest"
					});
				});
				else if (newSelections.length > 0) {
					const pos = getCaretPosition(newSelections.at(-1));
					this.#scrollToLine(pos.line, pos.character);
				}
				this.focus({ preventScroll: true });
			}
		}
	}
	#applyChangeToLineAnnotations(change) {
		if (this.#lineAnnotations !== void 0) {
			const nextLineAnnotations = applyDocumentChangeToLineAnnotations(change, this.#lineAnnotations);
			if (nextLineAnnotations !== void 0) {
				this.#textDocument?.setLastUndoLineAnnotations(this.#lineAnnotations, nextLineAnnotations);
				return nextLineAnnotations;
			}
		}
	}
	#getRenderedEditableLineRanges() {
		const contentElement = this.#contentElement;
		if (contentElement === void 0) return [];
		const ranges = [];
		for (const child of contentElement.children) {
			const el = child;
			const lineType = el.dataset.lineType;
			const lineNumber = getLineNumberAttr(el);
			if (lineNumber === void 0 || lineType === void 0 || !isLineEditable(lineType)) continue;
			const line = lineNumber - 1;
			const current = ranges.at(-1);
			if (current !== void 0 && line <= current[1] + 1) current[1] = Math.max(current[1], line);
			else ranges.push([line, line]);
		}
		return ranges;
	}
	#getLineElement(line) {
		let lineElement = this.#lineElementsCache.get(line);
		if (lineElement !== void 0) return lineElement ?? void 0;
		const renderRange = this.#renderRange;
		if (renderRange !== void 0 && (line < renderRange.startingLine || line >= renderRange.startingLine + renderRange.totalLines)) return;
		const contentElement = this.#contentElement;
		if (contentElement === void 0) return;
		if (renderRange !== void 0) {
			const { startingLine } = renderRange;
			const { children } = contentElement;
			for (let i = line - startingLine; i <= children.length; i++) {
				const child = children[i];
				if (child === void 0) break;
				const lineNumber = getLineNumberAttr(child);
				const lineType = child.dataset.lineType;
				if (lineNumber !== void 0 && lineNumber === line + 1 && lineType !== void 0 && isLineEditable(lineType)) {
					lineElement = child;
					break;
				}
			}
		}
		lineElement ??= contentElement.querySelector(`[data-line="${line + 1}"]` + (this.#diffSyle === "unified" ? ":not([data-line-type=\"change-deletion\"])" : ""));
		if (lineElement !== void 0) this.#lineElementsCache.set(line, lineElement);
		return lineElement ?? void 0;
	}
	#getGutterWidth() {
		if (this.#gutterElement === void 0) return 0;
		if (this.#gutterWidthCache === void 0) {
			const diffsColumnNumberWidth = this.#contentElement?.parentElement?.style.getPropertyValue("--diffs-column-number-width");
			if (diffsColumnNumberWidth !== void 0 && diffsColumnNumberWidth.length > 2 && diffsColumnNumberWidth.endsWith("px")) this.#gutterWidthCache = parseInt(diffsColumnNumberWidth.slice(0, -2), 10);
			else this.#gutterWidthCache = this.#gutterElement.offsetWidth;
		}
		return this.#gutterWidthCache;
	}
	#getContentWidth() {
		if (this.#contentElement === void 0) return 0;
		if (this.#contentWidthCache === void 0) {
			const diffsColumnContentWidth = this.#contentElement.parentElement?.style.getPropertyValue("--diffs-column-content-width");
			if (diffsColumnContentWidth !== void 0 && diffsColumnContentWidth.length > 2 && diffsColumnContentWidth.endsWith("px")) this.#contentWidthCache = parseFloat(diffsColumnContentWidth.slice(0, -2));
			else this.#contentWidthCache = this.#contentElement.offsetWidth;
		}
		return this.#contentWidthCache;
	}
	#getLineY(line) {
		const cachedY = this.#lineYCache.get(line);
		if (cachedY !== void 0) return cachedY;
		const lineElement = this.#getLineElement(line);
		if (lineElement === void 0) return -1;
		let y = lineElement.offsetTop + this.#metrics.paddingTop;
		y += this.#activeContentOffset?.top ?? 0;
		this.#lineYCache.set(line, y);
		return y;
	}
	#getCharX(line, char) {
		if (this.#lastAccessedCharX !== void 0 && this.#lastAccessedCharX[0] === line && this.#lastAccessedCharX[1] === char) return [this.#lastAccessedCharX[2], this.#lastAccessedCharX[3]];
		const lineText = this.#textDocument?.getLineText(line);
		const offsetLeft = this.#getGutterWidth() + this.#metrics.ch;
		if (lineText === void 0 || lineText.length === 0 || char <= 0) return [offsetLeft + (this.#activeContentOffset?.left ?? 0), 0];
		const boundedCharacter = snapTextOffsetToUnicodeBoundary(lineText, Math.min(char, lineText.length));
		const textBeforeCharacter = lineText.slice(0, boundedCharacter);
		const asciiColumns = getExpandedAsciiTextColumns(textBeforeCharacter, this.#metrics.tabSize);
		let left = 0;
		let wrapLine = 0;
		if (asciiColumns !== -1) left = offsetLeft + asciiColumns * this.#metrics.ch;
		else left = offsetLeft + this.#metrics.measureTextWidth(textBeforeCharacter);
		if (this.#isWrap) {
			const contentWidth = this.#getContentWidth();
			if (2 * this.#metrics.ch + this.#metrics.measureTextWidth(lineText) > contentWidth) {
				const wrapOffsets = this.#wrapLineText(line);
				if (wrapOffsets == null) return [left + (this.#activeContentOffset?.left ?? 0), 0];
				for (let w = 0; w + 1 < wrapOffsets.length; w++) {
					const segmentStart = wrapOffsets[w];
					if (boundedCharacter <= wrapOffsets[w + 1]) {
						wrapLine = w;
						const prefixInSegment = lineText.slice(segmentStart, boundedCharacter);
						const segmentAsciiColumns = getExpandedAsciiTextColumns(prefixInSegment, this.#metrics.tabSize);
						if (segmentAsciiColumns !== -1) left = offsetLeft + segmentAsciiColumns * this.#metrics.ch;
						else left = offsetLeft + this.#metrics.measureTextWidth(prefixInSegment);
						break;
					}
				}
			}
			left += this.#activeContentOffset?.left ?? 0;
		}
		if (this.#lastAccessedCharX !== void 0) {
			this.#lastAccessedCharX[0] = line;
			this.#lastAccessedCharX[1] = char;
			this.#lastAccessedCharX[2] = left;
			this.#lastAccessedCharX[3] = wrapLine;
		} else this.#lastAccessedCharX = [
			line,
			char,
			left,
			wrapLine
		];
		return [left, wrapLine];
	}
	#wrapLineText(line) {
		const cachedOffsets = this.#wrapLineOffsetsCache.get(line);
		if (cachedOffsets !== void 0) return cachedOffsets;
		if (this.#wrapLineOffsetsCache.size >= MAX_WRAP_OFFSETS_CACHE_LINES) this.#wrapLineOffsetsCache.clear();
		const lineText = this.#textDocument?.getLineText(line);
		if (lineText === void 0 || lineText.length === 0) {
			const offsets = new Uint32Array([0]);
			this.#wrapLineOffsetsCache.set(line, offsets);
			return offsets;
		}
		const contentElement = this.#contentElement;
		if (contentElement == null || !contentElement.isConnected) return;
		const div = h("div", {
			style: {
				position: "absolute",
				top: "0",
				left: "0",
				width: "100%",
				boxSizing: "border-box",
				visibility: "hidden",
				pointerEvents: "none",
				whiteSpace: "pre-wrap",
				wordBreak: "break-word",
				font: "inherit",
				paddingInline: "1ch",
				tabSize: this.#metrics.tabSize.toString()
			},
			textContent: lineText
		}, contentElement);
		const textNode = div.firstChild;
		const range = document.createRange();
		const starts = [];
		try {
			const divRect = div.getBoundingClientRect();
			if (divRect.width === 0) return;
			const unicodeOffsets = getUnicodeMeasurementOffsets(lineText);
			const wrapLineStartLeft = divRect.left + this.#metrics.ch;
			const graphemeCount = unicodeOffsets === void 0 ? lineText.length : unicodeOffsets.length - 1;
			const graphemeStart = (index) => unicodeOffsets === void 0 ? index : unicodeOffsets[index];
			const measureGrapheme = (index) => {
				range.setStart(textNode, graphemeStart(index));
				range.setEnd(textNode, graphemeStart(index + 1));
				return range.getBoundingClientRect();
			};
			starts.push(0);
			let lastTop = measureGrapheme(0).top;
			let searchStart = 1;
			while (searchStart < graphemeCount) {
				let low = searchStart;
				let high = graphemeCount;
				while (low < high) {
					const mid = low + high >> 1;
					if (measureGrapheme(mid).top > lastTop) high = mid;
					else low = mid + 1;
				}
				if (low >= graphemeCount) break;
				const { left, top } = measureGrapheme(low);
				const startsPastLineStart = isSafari() && left - wrapLineStartLeft > this.#metrics.ch / 2;
				starts.push(graphemeStart(startsPastLineStart ? low - 1 : low));
				lastTop = top;
				searchStart = low + 1;
			}
			const offsets = new Uint32Array(starts.length + 1);
			for (let i = 0; i < starts.length; i++) offsets[i] = starts[i];
			offsets[starts.length] = lineText.length;
			this.#wrapLineOffsetsCache.set(line, offsets);
			return offsets;
		} finally {
			div.remove();
		}
	}
	#wrapLineTextOrWholeLine(line) {
		const offsets = this.#wrapLineText(line);
		if (offsets !== void 0) return offsets;
		const length = this.#textDocument?.getLineText(line)?.length ?? 0;
		return Uint32Array.of(0, length);
	}
	#rangeBelongsToEditor({ startContainer, endContainer }) {
		const contentEl = this.#contentElement;
		if (contentEl === void 0) return false;
		return contentEl.contains(startContainer) && contentEl.contains(endContainer);
	}
	#isLineVisible(line) {
		const lineCount = this.#textDocument?.lineCount ?? 0;
		if (line < 0 || line >= lineCount) return false;
		return this.#getLineElement(line) !== void 0;
	}
};
//#endregion
export { Editor };

//# sourceMappingURL=editor.js.map