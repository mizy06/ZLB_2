import { DEFAULT_RENDER_RANGE, DEFAULT_THEMES } from "../constants.js";
import { areFilesEqual } from "../utils/areFilesEqual.js";
import { getFileAnnotations, shouldRenderFileAnnotations } from "../utils/includesFileAnnotations.js";
import { createGutterGap, createGutterItem, createGutterWrapper, createHastElement } from "../utils/hast_utils.js";
import { areLanguagesAttached } from "../highlighter/languages/areLanguagesAttached.js";
import { getHighlighterIfLoaded, getSharedHighlighter } from "../highlighter/shared_highlighter.js";
import { getThemes } from "../utils/getThemes.js";
import { areThemesAttached } from "../highlighter/themes/areThemesAttached.js";
import { hasResolvedThemes } from "../highlighter/themes/hasResolvedThemes.js";
import { applyLineTextWithNewline } from "../utils/applyLineTextWithNewline.js";
import { areFileRenderOptionsEqual } from "../utils/areFileRenderOptionsEqual.js";
import { areRenderRangesEqual } from "../utils/areRenderRangesEqual.js";
import { linesFromFileContents } from "../utils/computeFileOffsets.js";
import { createAnnotationElement } from "../utils/createAnnotationElement.js";
import { createContentColumn } from "../utils/createContentColumn.js";
import { createFileHeaderElement } from "../utils/createFileHeaderElement.js";
import { createPreElement } from "../utils/createPreElement.js";
import { getFiletypeFromFileName } from "../utils/getFiletypeFromFileName.js";
import { getHighlighterOptions } from "../utils/getHighlighterOptions.js";
import { getLineAnnotationName } from "../utils/getLineAnnotationName.js";
import { isFilePlainText } from "../utils/isFilePlainText.js";
import { renderFileWithHighlighter } from "../utils/renderFileWithHighlighter.js";
import { toHtml } from "hast-util-to-html";
//#region src/renderers/FileRenderer.ts
function isLineCacheForFile(lineCache, file) {
	return file.cacheKey == null ? lineCache.file === file && lineCache.sourceContents === file.contents : lineCache.cacheKey === file.cacheKey;
}
let instanceId = -1;
var FileRenderer = class {
	options;
	onRenderUpdate;
	workerManager;
	__id = `file-renderer:${++instanceId}`;
	highlighter;
	renderCache;
	computedLang = "text";
	lineAnnotations = {};
	lineCache;
	pendingStructuralRows;
	textDocumentCache = /* @__PURE__ */ new WeakMap();
	editSessionActive = false;
	constructor(options = { theme: DEFAULT_THEMES }, onRenderUpdate, workerManager) {
		this.options = options;
		this.onRenderUpdate = onRenderUpdate;
		this.workerManager = workerManager;
		if (workerManager?.isWorkingPool() !== true) this.highlighter = areThemesAttached(options.theme ?? DEFAULT_THEMES) ? getHighlighterIfLoaded() : void 0;
	}
	setOptions(options) {
		this.options = options;
	}
	mergeOptions(options) {
		this.options = {
			...this.options,
			...options
		};
	}
	setLineAnnotations(lineAnnotations) {
		this.lineAnnotations = {};
		for (const annotation of lineAnnotations) {
			const arr = this.lineAnnotations[annotation.lineNumber] ?? [];
			this.lineAnnotations[annotation.lineNumber] = arr;
			arr.push(annotation);
		}
	}
	cleanUp() {
		this.recycle();
		this.workerManager = void 0;
		this.onRenderUpdate = void 0;
	}
	/**
	* Enter edit-session mode: rendering happens locally with the token
	* transformer forced on, and worker-pool requests/results are suspended
	* for this renderer. Called on every editor attach, including a re-attach
	* after recycle.
	*/
	beginEditSession() {
		this.editSessionActive = true;
	}
	/** Leave edit-session mode. Rendering returns to the pool when one works. */
	endEditSession() {
		this.editSessionActive = false;
	}
	/**
	* Ensures that the DOM is compatible with editor render updates
	*/
	editorRenderReady() {
		return this.renderCache?.options.useTokenTransformer === true && this.renderCache.highlighted && this.renderCache.result != null;
	}
	recycle() {
		this.clearRenderCache();
		this.highlighter = void 0;
		this.workerManager?.cleanUpTasks(this);
		this.lineCache = void 0;
		this.endEditSession();
		this.textDocumentCache = /* @__PURE__ */ new WeakMap();
	}
	syncEditedContentsToFile() {
		const { renderCache, lineCache } = this;
		if (renderCache?.isDirty !== true || lineCache == null || !isLineCacheForFile(lineCache, renderCache.file)) return;
		renderCache.file.contents = lineCache.lines.join("");
	}
	hasUnkeyedFileContentsChanged(file) {
		const { lineCache } = this;
		return file.cacheKey == null && lineCache != null && lineCache.file === file && lineCache.sourceContents !== file.contents;
	}
	invalidateChangedUnkeyedFile(file) {
		if (!this.hasUnkeyedFileContentsChanged(file)) return;
		this.workerManager?.cleanUpTasks(this);
		this.clearRenderCache();
		this.lineCache = void 0;
		this.textDocumentCache = /* @__PURE__ */ new WeakMap();
	}
	clearRenderCache() {
		this.syncEditedContentsToFile();
		this.pendingStructuralRows = void 0;
		const renderCache = this.renderCache;
		this.renderCache = void 0;
		if (renderCache != null && renderCache.isDirty === true && renderCache.file.cacheKey != null) this.workerManager?.evictFileFromCache(renderCache.file.cacheKey);
	}
	hydrate(file) {
		const { options } = this.getRenderOptions(file);
		const massiveFile = isFileMassive(this.getOrCreateLineCache(file).length, this.getTokenizeMaxLength());
		let cache = this.workerManager?.getFileResultCache(file);
		if (cache != null && !areFileRenderOptionsEqual(options, cache.options)) cache = void 0;
		this.renderCache ??= {
			file,
			options,
			highlighted: !massiveFile && !isFilePlainText(file),
			result: massiveFile ? void 0 : cache?.result,
			renderRange: void 0
		};
		if (!this.editSessionActive && this.workerManager?.isWorkingPool() === true) {
			if (this.renderCache.result == null && !massiveFile) this.workerManager.highlightFileAST(this, file);
		} else if (this.highlighter == null) {
			this.computedLang = file.lang ?? getFiletypeFromFileName(file.name);
			this.initializeHighlighter();
		}
	}
	getLocalHighlightTheme() {
		return this.workerManager?.getFileRenderOptions().theme ?? this.options.theme ?? DEFAULT_THEMES;
	}
	getEffectiveCodeOptions() {
		const poolOptions = this.workerManager?.isWorkingPool() === true ? this.workerManager.getFileRenderOptions() : void 0;
		return {
			theme: this.getLocalHighlightTheme(),
			tokenizeMaxLineLength: poolOptions?.tokenizeMaxLineLength ?? this.options.tokenizeMaxLineLength
		};
	}
	getRenderOptions(file) {
		const options = (() => {
			if (this.workerManager?.isWorkingPool() === true) {
				const poolOptions = this.workerManager.getFileRenderOptions();
				if (this.editSessionActive && poolOptions.useTokenTransformer !== true) return {
					...poolOptions,
					useTokenTransformer: true
				};
				return poolOptions;
			}
			const { tokenizeMaxLineLength = 1e3 } = this.options;
			return {
				theme: this.getLocalHighlightTheme(),
				useTokenTransformer: this.editSessionActive || this.options.useTokenTransformer === true,
				tokenizeMaxLineLength
			};
		})();
		const { renderCache } = this;
		if (renderCache?.result == null) return {
			options,
			forceHighlight: true
		};
		if (!areFilesEqual(file, renderCache.file) || !areFileRenderOptionsEqual(options, renderCache.options)) return {
			options,
			forceHighlight: true
		};
		return {
			options,
			forceHighlight: false
		};
	}
	getOrCreateLineCache(file) {
		this.invalidateChangedUnkeyedFile(file);
		let { lineCache } = this;
		if (lineCache == null || !isLineCacheForFile(lineCache, file)) lineCache = {
			cacheKey: file.cacheKey,
			file,
			sourceContents: file.contents,
			lines: linesFromFileContents(file.contents)
		};
		this.lineCache = lineCache;
		return lineCache.lines;
	}
	getLineCount(file) {
		const lines = this.getOrCreateLineCache(file);
		return this.textDocumentCache.get(file)?.lineCount ?? lines.length;
	}
	updateRenderCache(dirtyLines, themeType, lineCountChangeInFlight = false) {
		this.pendingStructuralRows = void 0;
		if (this.renderCache == null) return;
		const { file, result } = this.renderCache;
		if (result == null) return;
		const pendingStructuralRows = lineCountChangeInFlight ? /* @__PURE__ */ new Map() : void 0;
		this.pendingStructuralRows = pendingStructuralRows;
		const lineCache = this.lineCache != null && isLineCacheForFile(this.lineCache, file) ? this.lineCache : void 0;
		for (const [line, tokens] of dirtyLines) {
			if (pendingStructuralRows === void 0 && lineCache != null && line < lineCache.lines.length) {
				const lineText = tokens.map((token) => token[2]).join("");
				lineCache.lines[line] = applyLineTextWithNewline(lineCache.lines[line] ?? "", lineText);
			}
			const row = {
				type: "element",
				tagName: "div",
				properties: {
					"data-line": line + 1,
					"data-line-type": "context",
					"data-line-index": line
				},
				children: tokens.map(([char, fg, text]) => {
					if (char === 0 && fg === "") {
						if (text === "") return {
							type: "element",
							tagName: "br",
							properties: {},
							children: []
						};
						return {
							type: "text",
							value: text
						};
					}
					return {
						type: "element",
						tagName: "span",
						properties: {
							"data-char": char,
							style: `color:${fg};`
						},
						children: [{
							type: "text",
							value: text
						}]
					};
				})
			};
			if (pendingStructuralRows !== void 0) pendingStructuralRows.set(line, row);
			else result.code[line] = row;
		}
		result.baseThemeType = themeType;
		this.renderCache.isDirty = true;
	}
	applyDocumentChange(textDocument) {
		const pendingStructuralRows = this.pendingStructuralRows;
		this.pendingStructuralRows = void 0;
		if (this.renderCache == null) return;
		const { file, result } = this.renderCache;
		if (result == null) return;
		const previousLines = this.lineCache != null && isLineCacheForFile(this.lineCache, file) ? this.lineCache.lines : linesFromFileContents(file.contents);
		const nextLines = linesFromFileContents(textDocument.getText());
		if (previousLines.length !== nextLines.length) {
			const maxShared = Math.min(previousLines.length, nextLines.length);
			let prefix = 0;
			while (prefix < maxShared && previousLines[prefix] === nextLines[prefix]) prefix++;
			let suffix = 0;
			while (suffix < maxShared - prefix && previousLines[previousLines.length - 1 - suffix] === nextLines[nextLines.length - 1 - suffix]) suffix++;
			const previousCode = result.code;
			result.code = new Array(nextLines.length);
			for (let i = 0; i < prefix; i++) result.code[i] = previousCode[i];
			for (let i = 0; i < suffix; i++) result.code[nextLines.length - 1 - i] = previousCode[previousLines.length - 1 - i];
			if (pendingStructuralRows !== void 0) {
				for (const [line, row] of pendingStructuralRows) if (line < nextLines.length) result.code[line] = row;
			}
			for (let i = prefix; i < nextLines.length - suffix; i++) result.code[i] ??= {
				type: "element",
				tagName: "div",
				properties: {
					"data-line": i + 1,
					"data-line-type": "context",
					"data-line-index": i
				},
				children: [{
					type: "element",
					tagName: "span",
					properties: { "data-char": 0 },
					children: [{
						type: "text",
						value: textDocument.getLineText(i)
					}]
				}]
			};
			for (let i = 0; i < result.code.length; i++) {
				const line = result.code[i];
				if (line?.type === "element") {
					line.properties["data-line"] = i + 1;
					line.properties["data-line-index"] = i;
				}
			}
			this.renderCache.isDirty = true;
		}
		this.lineCache = {
			cacheKey: file.cacheKey,
			file,
			sourceContents: file.contents,
			lines: nextLines
		};
		this.textDocumentCache.set(file, textDocument);
	}
	renderFile(file = this.renderCache?.file, renderRange = DEFAULT_RENDER_RANGE) {
		if (file == null) return;
		this.invalidateChangedUnkeyedFile(file);
		if (this.renderCache?.isDirty === true && !areFilesEqual(file, this.renderCache.file)) {
			this.clearRenderCache();
			this.lineCache = void 0;
			this.textDocumentCache = /* @__PURE__ */ new WeakMap();
		}
		let { options, forceHighlight } = this.getRenderOptions(file);
		if (this.renderCache?.isDirty === true && !areFileRenderOptionsEqual(options, this.renderCache.options)) this.clearRenderCache();
		const cache = this.getMatchingWorkerResultCache(file, options);
		if (cache != null && !this.hasHighlightedRenderCache(file, options)) {
			this.renderCache = {
				file,
				highlighted: true,
				renderRange: void 0,
				...cache
			};
			forceHighlight = false;
		}
		this.renderCache ??= {
			file,
			highlighted: false,
			options,
			result: void 0,
			renderRange: void 0
		};
		const lines = this.getOrCreateLineCache(file);
		const hasContent = file.contents.length > 0;
		const forcePlainText = !hasContent || isFilePlainText(file) || isFileMassive(lines.length, this.getTokenizeMaxLength());
		const newContent = !areFilesEqual(file, this.renderCache.file);
		const newRenderRange = !areRenderRangesEqual(this.renderCache.renderRange, renderRange);
		if (!this.editSessionActive && this.workerManager?.isWorkingPool() === true) {
			if (forcePlainText || this.renderCache.result == null || !this.renderCache.highlighted && (newContent || newRenderRange)) {
				this.renderCache.file = file;
				this.renderCache.options = options;
				this.renderCache.highlighted = false;
				if (this.renderCache.result == null || newContent || newRenderRange || forceHighlight) this.renderCache.result = this.workerManager.getPlainFileAST(file, renderRange.startingLine, renderRange.totalLines, lines);
				this.renderCache.renderRange = renderRange;
			}
			if (!forcePlainText && hasContent && (!this.renderCache.highlighted || forceHighlight)) this.workerManager.highlightFileAST(this, file);
		} else {
			this.computedLang = file.lang ?? getFiletypeFromFileName(file.name);
			const hasThemes = this.highlighter != null && areThemesAttached(options.theme);
			const hasLangs = this.highlighter != null && areLanguagesAttached(this.computedLang);
			const canHighlight = !forcePlainText && hasLangs;
			if (this.highlighter != null && hasThemes && (forceHighlight || forcePlainText || !this.renderCache.highlighted && canHighlight || this.renderCache.result == null)) {
				const { result, options } = this.renderFileWithHighlighter(file, this.highlighter, forcePlainText || !hasLangs);
				this.renderCache = {
					file,
					options,
					highlighted: canHighlight,
					result,
					renderRange: void 0
				};
			}
			if (!hasThemes || !forcePlainText && !hasLangs) this.asyncHighlight(file).then(({ result, options }) => {
				if (this.renderCache != null) this.renderCache.highlighted = false;
				this.applyHighlightResult(file, result, options, !forcePlainText);
			});
		}
		return this.renderCache.result != null ? this.processFileResult(this.renderCache.file, renderRange, this.renderCache.result) : void 0;
	}
	async asyncRender(file, renderRange = DEFAULT_RENDER_RANGE) {
		const { result } = await this.asyncHighlight(file);
		return this.processFileResult(file, renderRange, result);
	}
	async asyncHighlight(file) {
		const forcePlainText = isFileMassive(this.getOrCreateLineCache(file).length, this.getTokenizeMaxLength());
		this.computedLang = forcePlainText ? "text" : file.lang ?? getFiletypeFromFileName(file.name);
		const hasThemes = this.highlighter != null && hasResolvedThemes(getThemes(this.getLocalHighlightTheme()));
		const hasLangs = forcePlainText || this.highlighter != null && areLanguagesAttached(this.computedLang);
		if (this.highlighter == null || !hasThemes || !hasLangs) this.highlighter = await this.initializeHighlighter();
		return this.renderFileWithHighlighter(file, this.highlighter, forcePlainText);
	}
	renderFileWithHighlighter(file, highlighter, forcePlainText = false) {
		const { options } = this.getRenderOptions(file);
		return {
			result: renderFileWithHighlighter(file, highlighter, options, { forcePlainText }),
			options
		};
	}
	processFileResult(file, renderRange, { code, themeStyles, baseThemeType }) {
		const totalLines = this.getLineCount(file);
		const { disableFileHeader = false } = this.options;
		const contentArray = [];
		const gutter = createGutterWrapper();
		const endLine = Math.min(renderRange.startingLine + renderRange.totalLines, totalLines);
		let rowCount = 0;
		const fileLevelAnnotations = shouldRenderFileAnnotations(renderRange) ? getFileAnnotations(this.lineAnnotations) : void 0;
		if (fileLevelAnnotations != null) {
			gutter.children.push(createGutterGap("context", "annotation", 1));
			contentArray.push(createAnnotationElement({
				type: "annotation",
				hunkIndex: -1,
				lineIndex: -1,
				annotations: fileLevelAnnotations.map((annotation) => getLineAnnotationName(annotation))
			}));
			rowCount++;
		}
		for (let lineIndex = renderRange.startingLine; lineIndex < endLine; lineIndex++) {
			const lineNumber = lineIndex + 1;
			const line = code[lineIndex];
			if (line == null) {
				const message = "FileRenderer.processFileResult: Line doesnt exist";
				console.error(message, {
					name: file.name,
					lineIndex,
					lineNumber
				});
				throw new Error(message);
			}
			gutter.children.push(createGutterItem("context", lineNumber, `${lineIndex}`));
			contentArray.push(line);
			rowCount++;
			const annotations = this.lineAnnotations[lineNumber];
			if (annotations != null) {
				gutter.children.push(createGutterGap("context", "annotation", 1));
				contentArray.push(createAnnotationElement({
					type: "annotation",
					hunkIndex: 0,
					lineIndex: lineNumber,
					annotations: annotations.map((annotation) => getLineAnnotationName(annotation))
				}));
				rowCount++;
			}
		}
		gutter.properties.style = `grid-row: span ${rowCount}`;
		return {
			gutterAST: gutter.children ?? [],
			contentAST: contentArray,
			preAST: this.createPreElement(totalLines),
			headerAST: !disableFileHeader ? this.renderHeader(file) : void 0,
			totalLines,
			rowCount,
			themeStyles,
			baseThemeType,
			bufferBefore: renderRange.bufferBefore,
			bufferAfter: renderRange.bufferAfter,
			css: ""
		};
	}
	renderHeader(file) {
		const { headerRenderMode = "default", stickyHeader = false } = this.options;
		return createFileHeaderElement({
			fileOrDiff: file,
			mode: headerRenderMode,
			stickyHeader
		});
	}
	renderFullHTML(result) {
		return toHtml(this.renderFullAST(result));
	}
	renderFullAST(result, children = []) {
		children.push(createHastElement({
			tagName: "code",
			children: this.renderCodeAST(result),
			properties: { "data-code": "" }
		}));
		return {
			...result.preAST,
			children
		};
	}
	renderCodeAST(result) {
		const gutter = createGutterWrapper();
		gutter.children = result.gutterAST;
		gutter.properties.style = `grid-row: span ${result.rowCount}`;
		return [gutter, createContentColumn(result.contentAST, result.rowCount)];
	}
	renderPartialHTML(children, includeCodeNode = false) {
		if (!includeCodeNode) return toHtml(children);
		return toHtml(createHastElement({
			tagName: "code",
			children,
			properties: { "data-code": "" }
		}));
	}
	async initializeHighlighter() {
		this.highlighter = await getSharedHighlighter(getHighlighterOptions(this.computedLang, {
			theme: this.getLocalHighlightTheme(),
			preferredHighlighter: this.workerManager?.getPreferredHighlighter() ?? this.options.preferredHighlighter
		}));
		return this.highlighter;
	}
	onHighlightSuccess(file, result, options, highlighted = true) {
		if (this.editSessionActive) return;
		this.applyHighlightResult(file, result, options, highlighted);
	}
	applyHighlightResult(file, result, options, highlighted = true) {
		if (this.renderCache == null) return;
		const triggerRenderUpdate = !areFilesEqual(file, this.renderCache.file) || !this.renderCache.highlighted || !areFileRenderOptionsEqual(options, this.renderCache.options);
		this.renderCache = {
			file,
			options,
			highlighted,
			result,
			renderRange: void 0
		};
		if (triggerRenderUpdate) this.onRenderUpdate?.();
	}
	getMatchingWorkerResultCache(file, options) {
		if (this.editSessionActive) return;
		const cache = this.workerManager?.getFileResultCache(file);
		if (cache == null || !areFileRenderOptionsEqual(options, cache.options)) return;
		return cache;
	}
	hasHighlightedRenderCache(file, options) {
		const { renderCache } = this;
		return renderCache?.result != null && renderCache.highlighted && areFilesEqual(file, renderCache.file) && areFileRenderOptionsEqual(options, renderCache.options);
	}
	onHighlightError(error) {
		console.error(error);
	}
	getTokenizeMaxLength() {
		return this.options.tokenizeMaxLength ?? 1e5;
	}
	createPreElement(totalLines) {
		const { disableLineNumbers = false, overflow = "scroll" } = this.options;
		return createPreElement({
			type: "file",
			diffIndicators: "none",
			disableBackground: true,
			disableLineNumbers,
			overflow,
			split: false,
			totalLines
		});
	}
};
function isFileMassive(lineCount, tokenizeMaxLength) {
	return lineCount > tokenizeMaxLength;
}
//#endregion
export { FileRenderer };

//# sourceMappingURL=FileRenderer.js.map