import { DEFAULT_THEMES } from "../constants.js";
import { addEventListener, debounce, h } from "./utils.js";
import { colorUtils } from "@pierre/theming/color";
import { EncodedTokenMetadata, INITIAL } from "shiki/textmate";
//#region src/editor/tokenizer.ts
const TOKENIZE_TIME_LIMIT = 500;
let nextTokenizerId = 0;
/** Stoppable code tokenizer for the editor */
var EditorTokenizer = class {
	#highlighter;
	#grammar;
	#mediaQueryList;
	#themeType = "dark";
	#themeName = "";
	#colorMap;
	#textDocument;
	#tokenizeMaxLineLength;
	#setStyle;
	#onDeferTokenize;
	#onThemeChange;
	#matchBrackets;
	#debug;
	#disposes;
	#isCleanedUp = false;
	#stateStack = [INITIAL];
	#comparisonStateStack = [];
	#comparisonStateStackStart = 0;
	#comparisonLineChanges = [];
	#lastLine = -1;
	#isStopped = true;
	#isPaused = false;
	#backgroundJobId = 0;
	#tokenizerId = ++nextTokenizerId;
	#backgroundPrebuildEndLine = -1;
	#pendingPrebuildEndLine = -1;
	#backgroundChangedLineRanges;
	#backgroundChangedRangeIndex = 0;
	#bracketIgnoredRanges = [];
	#isMessageListenerAttached = false;
	#prebuildStateStack = debounce(async (renderRange) => {
		if (this.#isCleanedUp) return;
		const { startingLine = 0, totalLines = Infinity } = renderRange ?? {};
		const endLine = Math.min(totalLines === Infinity ? Infinity : startingLine + totalLines, this.#textDocument.lineCount);
		if (this.#grammar === void 0 && !isGrammarlessLanguage(this.#textDocument.languageId)) {
			await this.#highlighter.loadLanguage(this.#textDocument.languageId);
			if (this.#isCleanedUp) return;
			this.#grammar = this.#highlighter.getLanguage(this.#textDocument.languageId);
		}
		this.#ensureActiveTheme();
		this.#scheduleStatePrebuild(endLine);
	}, 500);
	#onMessage = ({ data }) => {
		if (typeof data !== "object" || data === null) return;
		const { type, tokenizerId, jobId } = data;
		if (type === "tokenize" && tokenizerId === this.#tokenizerId && typeof jobId === "number" && jobId === this.#backgroundJobId) if (this.#backgroundPrebuildEndLine >= 0) this.#backgroundPrebuild(jobId);
		else this.#backgroundTokenize(jobId);
	};
	get themeType() {
		return this.#themeType;
	}
	getStringCommentRegexpRangesInLine(lineIndex) {
		if (!this.#matchBrackets || lineIndex < 0 || lineIndex >= this.#textDocument.lineCount) return null;
		this.#ensureGrammar();
		if (this.#grammar === void 0) return null;
		if (this.#bracketIgnoredRanges[lineIndex] === void 0) {
			this.#buildStateStack(lineIndex);
			const state = this.#stateStack[lineIndex] ?? INITIAL;
			const result = this.#tokenizeLineAt(lineIndex, state);
			this.#stateStack[lineIndex + 1] = result.state;
		}
		return this.#bracketIgnoredRanges[lineIndex] ?? null;
	}
	constructor({ codeOptions, highlighter, textDocument, matchBrackets, setStyle, onDeferTokenize, onThemeChange, __debug }) {
		const { themeType: themeTypeOption = "system", theme = DEFAULT_THEMES, tokenizeMaxLineLength = 1e3 } = codeOptions;
		this.#mediaQueryList = window.matchMedia("(prefers-color-scheme: dark)");
		let themeType;
		if (themeTypeOption === "system") themeType = this.#resolveSystemThemeType();
		else themeType = themeTypeOption;
		if (typeof theme !== "string" && themeTypeOption === "system") {
			const observer = new MutationObserver((mutations) => {
				for (const { type, attributeName } of mutations) if (type === "attributes" && attributeName !== null && (attributeName === "class" || attributeName.startsWith("data-"))) {
					const themeType = this.#resolveSystemThemeType();
					this.#emitThemeChange(theme[themeType], themeType);
					break;
				}
			});
			observer.observe(document.documentElement, { attributes: true });
			observer.observe(document.body, { attributes: true });
			this.#disposes = [addEventListener(this.#mediaQueryList, "change", () => {
				const themeType = this.#resolveSystemThemeType();
				this.#emitThemeChange(theme[themeType], themeType);
			}), () => observer.disconnect()];
		}
		this.#highlighter = highlighter;
		this.#textDocument = textDocument;
		this.#tokenizeMaxLineLength = tokenizeMaxLineLength;
		this.#setStyle = setStyle;
		this.#onDeferTokenize = onDeferTokenize;
		this.#onThemeChange = onThemeChange;
		this.#matchBrackets = matchBrackets !== false;
		this.#debug = __debug ?? false;
		this.#ensureGrammar();
		this.#colorMap = [];
		this.#setTheme(typeof theme === "string" ? theme : theme[themeType], typeof theme === "string" ? void 0 : themeType);
	}
	#emitThemeChange(themeName, themeType) {
		if (themeName === this.#themeName && themeType === this.#themeType) return;
		this.#setTheme(themeName, themeType);
		this.stopBackgroundTokenize();
		this.#stateStack = [INITIAL];
		this.#comparisonStateStack = [];
		this.#comparisonStateStackStart = 0;
		this.#comparisonLineChanges = [];
		if (this.#grammar !== void 0 && this.#textDocument.lineCount > 0) this.#scheduleBackgroundTokenize(0);
		this.#onThemeChange?.();
	}
	#resolveSystemThemeType() {
		try {
			if (typeof document !== "undefined" && typeof getComputedStyle === "function" && document.body != null) {
				const colorSchemes = getComputedStyle(document.body).colorScheme.split(/\s+/);
				const supportsDark = colorSchemes.includes("dark");
				if (supportsDark !== colorSchemes.includes("light")) return supportsDark ? "dark" : "light";
			}
		} catch {}
		return this.#mediaQueryList.matches ? "dark" : "light";
	}
	syncTheme(codeOptions) {
		const { themeType = "system", theme = DEFAULT_THEMES } = codeOptions;
		if (typeof theme === "string") {
			const pinnedThemeType = this.#highlighter.getTheme(theme).type;
			if (theme === this.#themeName && pinnedThemeType === this.#themeType) return;
			this.#emitThemeChange(theme, pinnedThemeType);
			return;
		}
		const nextThemeType = themeType === "system" ? this.#resolveSystemThemeType() : themeType;
		const nextThemeName = theme[nextThemeType];
		if (nextThemeType === this.#themeType && nextThemeName === this.#themeName) return;
		this.#emitThemeChange(nextThemeName, nextThemeType);
	}
	#setTheme(themeName, themeType) {
		const { theme, colorMap } = this.#highlighter.setTheme(themeName);
		const { colors = {} } = this.#highlighter.getTheme(themeName);
		const selectionBackground = colors["editor.selectionBackground"];
		const themeLineHighlightBackground = colors["editor.lineHighlightBackground"];
		const lineHighlightBackground = themeLineHighlightBackground != null && themeLineHighlightBackground.trim() !== "" && !colorUtils.isFullyTransparent(themeLineHighlightBackground) ? themeLineHighlightBackground : void 0;
		const lineHighlightBorder = colors["editor.lineHighlightBorder"] ?? (lineHighlightBackground == null ? "color-mix(in lab, var(--diffs-bg) 70%, var(--diffs-fg))" : "transparent");
		const activeLineSourceMix = lineHighlightBackground == null ? "100%" : "85%";
		const cursorForeground = colors["editorCursor.foreground"];
		const findMatchBackground = colors["editor.findMatchBackground"];
		const findMatchHighlightBackground = colors["editor.findMatchHighlightBackground"];
		const bracketMatchBackground = colors["editorBracketMatch.background"];
		const bracketMatchBorder = colors["editorBracketMatch.border"];
		const hintForeground = colors["editorHint.foreground"];
		const infoForeground = colors["editorInfo.foreground"];
		const warningForeground = colors["editorWarning.foreground"];
		const errorForeground = colors["editorError.foreground"];
		this.#setStyle(`:host {
      --diffs-editor-selection-bg: ${selectionBackground ?? "var(--diffs-line-bg)"};
      --diffs-editor-line-highlight-border: ${lineHighlightBorder};
      --diffs-editor-active-line-source-mix: ${activeLineSourceMix};
      --diffs-editor-match-bg: ${findMatchBackground ?? "initial"};
      --diffs-editor-match-highlight-bg: ${findMatchHighlightBackground ?? "initial"};
      --diffs-editor-bracket-match-bg: ${bracketMatchBackground ?? "initial"};
      --diffs-editor-bracket-match-border: ${bracketMatchBorder ?? "initial"};
      --diffs-editor-cursor-fg: ${cursorForeground ?? "initial"};
      --diffs-editor-hint-fg: ${hintForeground ?? "initial"};
      --diffs-editor-info-fg: ${infoForeground ?? "initial"};
      --diffs-editor-warning-fg: ${warningForeground ?? "initial"};
      --diffs-editor-error-fg: ${errorForeground ?? "initial"};
    }`);
		this.#themeName = themeName;
		this.#themeType = themeType ?? theme.type;
		this.#colorMap = colorMap;
	}
	#ensureActiveTheme() {
		if (this.#themeName === "") return;
		const { colorMap } = this.#highlighter.setTheme(this.#themeName);
		this.#colorMap = colorMap;
	}
	cleanUp() {
		this.#isCleanedUp = true;
		this.stopBackgroundTokenize();
		this.#detachMessageListener();
		this.#disposes?.forEach((dispose) => dispose());
		this.#disposes = void 0;
	}
	tokenize(change, renderRange, hostRealignsRows = false) {
		this.#ensureGrammar();
		this.#ensureActiveTheme();
		if (this.#grammar === void 0 && !isGrammarlessLanguage(this.#textDocument.languageId)) throw new Error(`Grammar for language "${this.#textDocument.languageId}" not loaded`);
		if (this.#matchBrackets) this.#bracketIgnoredRanges.length = Math.min(this.#bracketIgnoredRanges.length, change.startLine);
		const { lineCount } = this.#textDocument;
		const { startingLine = 0, totalLines = Infinity } = renderRange ?? {};
		const renderRangeEndLine = totalLines === Infinity ? lineCount : Math.min(startingLine + totalLines, lineCount);
		const dirtyStart = change.startLine;
		const viewStart = Math.max(startingLine, dirtyStart);
		const crossesRenderRangeEnd = renderRange !== void 0 && totalLines !== Infinity && change.lineDelta > 0 && dirtyStart < renderRangeEndLine && change.endLine >= renderRangeEndLine;
		const canReuseCachedStates = change.lineDelta === 0 && (change.changedLineChanges?.every(([, , lineDelta]) => lineDelta === 0) ?? true);
		const canReuseShiftedStates = hostRealignsRows && change.lineDelta !== 0 && dirtyStart >= startingLine;
		const canCacheTokenizedStates = canReuseCachedStates || renderRange === void 0 || dirtyStart >= viewStart;
		const changedLineRanges = change.changedLineRanges ?? [[dirtyStart, change.endLine]];
		this.#comparisonStateStack = [];
		this.#comparisonStateStackStart = 0;
		this.#comparisonLineChanges = [];
		let offscreenSyncEnd = -1;
		if (dirtyStart < viewStart) {
			for (const [rangeStart, rangeEnd] of changedLineRanges) if (rangeStart < viewStart) offscreenSyncEnd = Math.max(offscreenSyncEnd, Math.min(rangeEnd, viewStart - 1));
		}
		const shouldFlushOffscreenLines = offscreenSyncEnd >= dirtyStart && (canReuseCachedStates || change.lineDelta < 0);
		if (canReuseCachedStates) this.#buildStateStack(dirtyStart);
		else {
			this.#shiftComparisonStateStack(change);
			if (renderRange === void 0 || dirtyStart >= viewStart) this.#buildStateStack(viewStart);
		}
		let changedRangeIndex = 0;
		let currentChangedRangeEnd = changedLineRanges[changedRangeIndex][1];
		let backgroundStartLine;
		let backgroundChangedRangeIndex = 0;
		let line = canReuseCachedStates ? changedLineRanges[changedRangeIndex][0] : viewStart;
		let settled = false;
		const dirtyLines = /* @__PURE__ */ new Map();
		const offscreenDirtyLines = shouldFlushOffscreenLines ? /* @__PURE__ */ new Map() : void 0;
		if (offscreenDirtyLines !== void 0 && !canReuseCachedStates) {
			const offscreenEnd = Math.min(offscreenSyncEnd + 1, viewStart, renderRangeEndLine);
			if (offscreenEnd > dirtyStart) {
				this.#buildStateStack(offscreenEnd);
				let offscreenLine = dirtyStart;
				let offscreenState = this.#stateStack[offscreenLine] ?? INITIAL;
				for (; offscreenLine < offscreenEnd; offscreenLine++) {
					const resolved = this.#tokenizeLineAt(offscreenLine, offscreenState);
					offscreenState = resolved.state;
					offscreenDirtyLines.set(offscreenLine, resolved.resolvedTokens);
				}
				this.#stateStack[offscreenEnd] = offscreenState;
			}
		}
		let state = this.#stateStack[line] ?? INITIAL;
		for (; line < renderRangeEndLine;) {
			const previousNextState = canReuseCachedStates ? this.#stateStack[line + 1] : canReuseShiftedStates ? this.#getPreviousEndState(line + 1) : void 0;
			if (canCacheTokenizedStates) this.#stateStack[line] = state;
			const { resolvedTokens, state: nextState } = this.#tokenizeLineAt(line, state);
			state = nextState;
			if (line >= viewStart) dirtyLines.set(line, resolvedTokens);
			else offscreenDirtyLines?.set(line, resolvedTokens);
			if (canCacheTokenizedStates) this.#stateStack[line + 1] = state;
			settled = line >= currentChangedRangeEnd && (canReuseCachedStates || canReuseShiftedStates) && previousNextState !== void 0 && state.equals(previousNextState);
			if (settled) {
				changedRangeIndex++;
				const nextRange = changedLineRanges[changedRangeIndex];
				if (nextRange === void 0) break;
				if (nextRange[0] >= renderRangeEndLine) {
					backgroundStartLine = nextRange[0];
					backgroundChangedRangeIndex = changedRangeIndex;
					break;
				}
				let nextState = this.#stateStack[nextRange[0]];
				if (canReuseShiftedStates) for (let stateLine = line + 2; stateLine <= nextRange[0]; stateLine++) {
					nextState = this.#getPreviousEndState(stateLine);
					if (nextState === void 0) break;
					this.#stateStack[stateLine] = nextState;
				}
				if (nextState === void 0) {
					currentChangedRangeEnd = nextRange[1];
					line++;
				} else {
					line = nextRange[0];
					state = nextState;
					currentChangedRangeEnd = nextRange[1];
				}
				settled = false;
				continue;
			}
			line++;
		}
		if (canCacheTokenizedStates) if (line < renderRangeEndLine) this.#stateStack[line + 1] = state;
		else this.#stateStack[line] = state;
		if (settled && canReuseShiftedStates && backgroundStartLine === void 0) {
			for (let stateLine = line + 2; stateLine <= lineCount; stateLine++) {
				const previousState = this.#getPreviousEndState(stateLine);
				if (previousState === void 0) break;
				this.#stateStack[stateLine] = previousState;
			}
			this.#comparisonStateStack = [];
			this.#comparisonStateStackStart = 0;
			this.#comparisonLineChanges = [];
		}
		if (offscreenDirtyLines !== void 0 && offscreenDirtyLines.size > 0) this.#onDeferTokenize(offscreenDirtyLines, this.#themeType);
		if (backgroundStartLine !== void 0) this.#scheduleBackgroundTokenize(backgroundStartLine, changedLineRanges, backgroundChangedRangeIndex);
		else if (!settled && line < lineCount) {
			const backgroundLine = crossesRenderRangeEnd && dirtyStart >= viewStart ? renderRangeEndLine : dirtyStart < viewStart && !canReuseCachedStates ? dirtyStart : line;
			this.#scheduleBackgroundTokenize(backgroundLine, changedLineRanges, changedRangeIndex);
		}
		return dirtyLines;
	}
	prebuildStateStack(renderRange) {
		this.#ensureGrammar();
		this.#prebuildStateStack(renderRange);
	}
	stopBackgroundTokenize() {
		this.#pendingPrebuildEndLine = -1;
		if (this.#isStopped) return;
		this.#isStopped = true;
		this.#isPaused = false;
		this.#lastLine = -1;
		this.#backgroundPrebuildEndLine = -1;
		this.#backgroundChangedLineRanges = void 0;
		this.#backgroundChangedRangeIndex = 0;
		this.#comparisonStateStack = [];
		this.#comparisonStateStackStart = 0;
		this.#comparisonLineChanges = [];
		this.#detachMessageListener();
	}
	pauseBackgroundTokenize() {
		if (this.#isStopped || this.#isPaused) return;
		if (this.#debug) console.log("[diffs/editor] background tokenization paused", { jobId: this.#backgroundJobId });
		this.#isPaused = true;
	}
	resumeBackgroundTokenize() {
		if (this.#isStopped || !this.#isPaused || this.#grammar === void 0 || this.#lastLine < 0) return;
		if (this.#debug) console.log("[diffs/editor] background tokenization resumed", { jobId: this.#backgroundJobId });
		this.#isPaused = false;
		this.#postTokenizeMessage(this.#backgroundJobId);
	}
	#ensureGrammar() {
		if (this.#grammar === void 0 && !isGrammarlessLanguage(this.#textDocument.languageId) && this.#highlighter.getLoadedLanguages().includes(this.#textDocument.languageId)) this.#grammar = this.#highlighter.getLanguage(this.#textDocument.languageId);
	}
	#attachMessageListener() {
		if (this.#isMessageListenerAttached) return;
		globalThis.addEventListener("message", this.#onMessage);
		this.#isMessageListenerAttached = true;
	}
	#detachMessageListener() {
		if (!this.#isMessageListenerAttached) return;
		globalThis.removeEventListener("message", this.#onMessage);
		this.#isMessageListenerAttached = false;
	}
	#postTokenizeMessage(jobId) {
		globalThis.postMessage({
			type: "tokenize",
			tokenizerId: this.#tokenizerId,
			jobId
		});
	}
	#scheduleBackgroundTokenize(startLine, changedLineRanges, changedRangeIndex = 0) {
		if (isGrammarlessLanguage(this.#textDocument.languageId)) return;
		const jobId = ++this.#backgroundJobId;
		if (this.#debug) console.log("[diffs/editor] background tokenization scheduled", {
			jobId,
			startLine,
			changedLineRanges,
			changedRangeIndex
		});
		this.#isStopped = false;
		this.#isPaused = false;
		this.#lastLine = startLine;
		if (this.#backgroundPrebuildEndLine >= 0) this.#pendingPrebuildEndLine = Math.max(this.#pendingPrebuildEndLine, this.#backgroundPrebuildEndLine);
		this.#backgroundPrebuildEndLine = -1;
		this.#backgroundChangedLineRanges = changedLineRanges;
		this.#backgroundChangedRangeIndex = changedRangeIndex;
		this.#attachMessageListener();
		this.#postTokenizeMessage(jobId);
	}
	#scheduleStatePrebuild(endLine) {
		if (this.#grammar === void 0 || this.#stateStack.length > endLine) return;
		if (!this.#isStopped) {
			if (this.#backgroundPrebuildEndLine >= 0) this.#backgroundPrebuildEndLine = Math.max(this.#backgroundPrebuildEndLine, endLine);
			else this.#pendingPrebuildEndLine = Math.max(this.#pendingPrebuildEndLine, endLine);
			return;
		}
		const jobId = ++this.#backgroundJobId;
		this.#isStopped = false;
		this.#isPaused = false;
		this.#lastLine = this.#stateStack.length - 1;
		this.#backgroundPrebuildEndLine = endLine;
		this.#pendingPrebuildEndLine = -1;
		this.#backgroundChangedLineRanges = void 0;
		this.#backgroundChangedRangeIndex = 0;
		this.#attachMessageListener();
		this.#postTokenizeMessage(jobId);
	}
	#tokenizeLineAt(line, state) {
		const lineText = this.#textDocument.getLineText(line);
		if (lineText.length > this.#tokenizeMaxLineLength) {
			console.warn(`[diffs] Line(${line}) too long to tokenize: ${lineText.length}`);
			this.#cacheBracketIgnoredRanges(line, null);
			return {
				resolvedTokens: [[
					0,
					"",
					lineText
				]],
				state
			};
		}
		if (this.#grammar === void 0 || lineText === "" || lineText.trim() === "") {
			this.#cacheBracketIgnoredRanges(line, null);
			return {
				resolvedTokens: [[
					0,
					"",
					lineText
				]],
				state
			};
		}
		const result = tokenizeLine(this.#grammar, this.#colorMap, lineText, state, TOKENIZE_TIME_LIMIT, this.#matchBrackets);
		this.#cacheBracketIgnoredRanges(line, result.bracketIgnoredRanges);
		return {
			resolvedTokens: result.resolvedTokens,
			state: result.ruleStack
		};
	}
	#cacheBracketIgnoredRanges(line, ranges) {
		if (this.#matchBrackets) this.#bracketIgnoredRanges[line] = ranges;
	}
	#shiftComparisonStateStack(change) {
		const lineChanges = change.changedLineChanges ?? [[
			change.startLine,
			change.endLine,
			change.lineDelta
		]];
		const comparisonStart = change.startLine + 1;
		if (comparisonStart <= this.#stateStack.length - comparisonStart) {
			this.#comparisonStateStack = this.#stateStack;
			this.#comparisonStateStackStart = 0;
			this.#stateStack = this.#stateStack.slice(0, comparisonStart);
		} else {
			this.#comparisonStateStackStart = comparisonStart;
			this.#comparisonStateStack = this.#stateStack.slice(comparisonStart);
			this.#stateStack.length = Math.min(this.#stateStack.length, comparisonStart);
		}
		this.#comparisonLineChanges = lineChanges;
	}
	#getPreviousEndState(line) {
		let previousLine = line;
		for (let index = this.#comparisonLineChanges.length - 1; index >= 0; index--) {
			const [startLine, endLine, lineDelta] = this.#comparisonLineChanges[index];
			if (lineDelta === 0) continue;
			if (previousLine > endLine) previousLine -= lineDelta;
			else if (previousLine > startLine) return this.#stateStack[line];
		}
		return this.#comparisonStateStack[previousLine - this.#comparisonStateStackStart] ?? this.#stateStack[line];
	}
	#buildStateStack(endAt, timeBudget) {
		const boundedEndAt = Math.min(Math.max(0, endAt), this.#textDocument.lineCount);
		if (this.#stateStack.length > boundedEndAt || this.#grammar === void 0) return true;
		const startedAt = timeBudget === void 0 ? 0 : performance.now();
		let line = this.#stateStack.length - 1;
		let state = this.#stateStack[line] ?? INITIAL;
		while (line < boundedEndAt) {
			this.#stateStack[line] = state;
			const lineText = this.#textDocument.getLineText(line);
			if (lineText.length <= this.#tokenizeMaxLineLength && lineText !== "" && lineText.trim() !== "") {
				const result = tokenizeLine(this.#grammar, this.#colorMap, lineText, state, TOKENIZE_TIME_LIMIT, this.#matchBrackets, false);
				this.#cacheBracketIgnoredRanges(line, result.bracketIgnoredRanges);
				state = result.ruleStack;
			} else this.#cacheBracketIgnoredRanges(line, null);
			line++;
			this.#stateStack[line] = state;
			if (timeBudget !== void 0 && performance.now() - startedAt > timeBudget) break;
		}
		return line >= boundedEndAt;
	}
	#backgroundPrebuild(jobId) {
		if (this.#isStopped || this.#isPaused || this.#grammar === void 0 || jobId !== this.#backgroundJobId) return;
		this.#ensureActiveTheme();
		const complete = this.#buildStateStack(this.#backgroundPrebuildEndLine, 1);
		if (this.#isStopped || this.#isPaused || jobId !== this.#backgroundJobId) return;
		if (complete) {
			this.stopBackgroundTokenize();
			return;
		}
		this.#lastLine = this.#stateStack.length - 1;
		this.#postTokenizeMessage(jobId);
	}
	#backgroundTokenize(jobId) {
		if (this.#isStopped || this.#isPaused || this.#grammar === void 0 || jobId !== this.#backgroundJobId) return;
		this.#ensureActiveTheme();
		const t = performance.now();
		const lines = /* @__PURE__ */ new Map();
		const totalLines = this.#textDocument.lineCount;
		const changedLineRanges = this.#backgroundChangedLineRanges;
		let line = this.#lastLine;
		let state = this.#stateStack[line] ?? INITIAL;
		let settled = false;
		let changedRangeIndex = this.#backgroundChangedRangeIndex;
		let currentChangedRangeEnd = changedLineRanges?.[changedRangeIndex]?.[1];
		for (; line < totalLines;) {
			this.#stateStack[line] = state;
			const previousNextState = currentChangedRangeEnd !== void 0 ? this.#getPreviousEndState(line + 1) : void 0;
			const lineText = this.#textDocument.getLineText(line);
			if (lineText.length > this.#tokenizeMaxLineLength) {
				console.warn(`[diffs] Line(${line}) too long to tokenize: ${lineText.length}`);
				lines.set(line, [[
					0,
					"",
					lineText
				]]);
				this.#cacheBracketIgnoredRanges(line, null);
			} else if (lineText === "" || lineText.trim() === "") {
				lines.set(line, [[
					0,
					"",
					lineText
				]]);
				this.#cacheBracketIgnoredRanges(line, null);
			} else {
				const ret = tokenizeLine(this.#grammar, this.#colorMap, lineText, state, TOKENIZE_TIME_LIMIT, this.#matchBrackets);
				lines.set(line, ret.resolvedTokens);
				this.#cacheBracketIgnoredRanges(line, ret.bracketIgnoredRanges);
				state = ret.ruleStack;
			}
			this.#stateStack[line + 1] = state;
			settled = currentChangedRangeEnd !== void 0 && line >= currentChangedRangeEnd && previousNextState !== void 0 && state.equals(previousNextState);
			line++;
			if (settled) {
				changedRangeIndex++;
				const nextRange = changedLineRanges?.[changedRangeIndex];
				if (nextRange === void 0) break;
				currentChangedRangeEnd = nextRange[1];
				if (this.#stateStack[nextRange[0]] === void 0) settled = false;
				else {
					line = nextRange[0];
					state = this.#stateStack[line] ?? state;
					settled = false;
					continue;
				}
			}
			if (performance.now() - t > 1) break;
		}
		this.#onDeferTokenize(lines, this.#themeType);
		if (this.#isStopped || this.#isPaused || jobId !== this.#backgroundJobId) return;
		if (settled || line >= totalLines) {
			const pendingPrebuildEndLine = this.#pendingPrebuildEndLine;
			this.stopBackgroundTokenize();
			if (pendingPrebuildEndLine >= 0) this.#scheduleStatePrebuild(pendingPrebuildEndLine);
			return;
		}
		this.#lastLine = line;
		this.#backgroundChangedRangeIndex = changedRangeIndex;
		this.#postTokenizeMessage(jobId);
	}
};
function tokenizeLine(grammar, colorMap, lineText, stateStack, timeLimit, collectBracketIgnoredRanges = true, resolveTokens = true) {
	const result = grammar.tokenizeLine2(lineText, stateStack, timeLimit);
	if (result.stoppedEarly) console.warn(`[diffs] Time limit reached when tokenizing line: ${lineText.substring(0, 100)}`);
	const rawTokens = result.tokens;
	const tokensLength = rawTokens.length / 2;
	const resolvedTokens = [];
	const bracketIgnoredRanges = [];
	if (!resolveTokens && !collectBracketIgnoredRanges) return {
		ruleStack: result.ruleStack,
		resolvedTokens,
		bracketIgnoredRanges
	};
	for (let j = 0; j < tokensLength; j++) {
		const offset = rawTokens[2 * j];
		const nextOffset = j + 1 < tokensLength ? rawTokens[2 * j + 2] : lineText.length;
		if (offset === nextOffset) continue;
		const metadata = rawTokens[2 * j + 1];
		if (resolveTokens) {
			const fg = EncodedTokenMetadata.getForeground(metadata);
			resolvedTokens.push([
				offset,
				colorMap[fg],
				lineText.slice(offset, nextOffset)
			]);
		}
		if (collectBracketIgnoredRanges && EncodedTokenMetadata.getTokenType(metadata) > 0) bracketIgnoredRanges.push([offset, nextOffset]);
	}
	return {
		ruleStack: result.ruleStack,
		resolvedTokens,
		bracketIgnoredRanges
	};
}
function renderLineTokens(tokens) {
	return tokens.map(([char, fg, textContent]) => {
		if (char === 0 && fg === "") {
			if (textContent === "") return h("br");
			return textContent;
		}
		return h("span", {
			dataset: { char: char.toString() },
			style: `color:${fg};`,
			textContent
		});
	});
}
function isGrammarlessLanguage(languageId) {
	return languageId === "text" || languageId === "ansi";
}
//#endregion
export { EditorTokenizer, renderLineTokens };

//# sourceMappingURL=tokenizer.js.map