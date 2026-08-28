import { shouldUseTokenTransformer } from "./shouldUseTokenTransformer.js";
//#region src/utils/getDiffHunksRendererOptions.ts
function getDiffHunksRendererOptions(options) {
	return {
		theme: options?.theme,
		disableLineNumbers: options?.disableLineNumbers,
		overflow: options?.overflow,
		collapsed: options?.collapsed,
		disableFileHeader: options?.disableFileHeader,
		disableVirtualizationBuffers: options?.disableVirtualizationBuffers,
		stickyHeader: options?.stickyHeader,
		preferredHighlighter: options?.preferredHighlighter,
		useCSSClasses: options?.useCSSClasses,
		useTokenTransformer: shouldUseTokenTransformer(options),
		tokenizeMaxLineLength: options?.tokenizeMaxLineLength,
		tokenizeMaxLength: options?.tokenizeMaxLength,
		diffStyle: options?.diffStyle,
		diffIndicators: options?.diffIndicators,
		disableBackground: options?.disableBackground,
		hunkSeparators: typeof options?.hunkSeparators === "function" ? "custom" : options?.hunkSeparators,
		expandUnchanged: options?.expandUnchanged,
		loadDiffFiles: options?.loadDiffFiles,
		collapsedContextThreshold: options?.collapsedContextThreshold,
		lineDiffType: options?.lineDiffType,
		maxLineDiffLength: options?.maxLineDiffLength,
		expansionLineCount: options?.expansionLineCount,
		headerRenderMode: options?.renderCustomHeader != null ? "custom" : "default"
	};
}
//#endregion
export { getDiffHunksRendererOptions };

//# sourceMappingURL=getDiffHunksRendererOptions.js.map