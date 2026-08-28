import { DEFAULT_THEMES } from "../constants.js";
import { linesFromFileContents } from "./computeFileOffsets.js";
import { getFiletypeFromFileName } from "./getFiletypeFromFileName.js";
import { createTransformerWithState } from "./createTransformerWithState.js";
import { formatCSSVariablePrefix } from "./formatCSSVariablePrefix.js";
import { getHighlighterThemeStyles } from "./getHighlighterThemeStyles.js";
import { getLineNodes } from "./getLineNodes.js";
//#region src/utils/renderFileWithHighlighter.ts
const DEFAULT_PLAIN_TEXT_OPTIONS = { forcePlainText: false };
function renderFileWithHighlighter(file, highlighter, { theme = DEFAULT_THEMES, tokenizeMaxLineLength, useTokenTransformer }, { forcePlainText, startingLine, totalLines, lines } = DEFAULT_PLAIN_TEXT_OPTIONS) {
	if (forcePlainText) {
		startingLine ??= 0;
		totalLines ??= Infinity;
	} else {
		startingLine = 0;
		totalLines = Infinity;
	}
	const isWindowedHighlight = startingLine > 0 || totalLines < Infinity;
	const { state, transformers } = createTransformerWithState(useTokenTransformer);
	const lang = forcePlainText ? "text" : file.lang ?? getFiletypeFromFileName(file.name);
	const baseThemeType = typeof theme === "string" ? highlighter.getTheme(theme).type : void 0;
	const themeStyles = getHighlighterThemeStyles({
		theme,
		highlighter
	});
	state.lineInfo = (shikiLineNumber) => ({
		type: "context",
		lineIndex: shikiLineNumber - 1 + startingLine,
		lineNumber: shikiLineNumber + startingLine
	});
	const hastConfig = (() => {
		if (typeof theme === "string") return {
			lang,
			theme,
			transformers,
			defaultColor: false,
			cssVariablePrefix: formatCSSVariablePrefix("token"),
			tokenizeMaxLineLength,
			tokenizeTimeLimit: 0
		};
		return {
			lang,
			themes: theme,
			transformers,
			defaultColor: false,
			cssVariablePrefix: formatCSSVariablePrefix("token"),
			tokenizeMaxLineLength,
			tokenizeTimeLimit: 0
		};
	})();
	const highlightedLines = getLineNodes(highlighter.codeToHast(isWindowedHighlight ? extractWindowedFileContent(lines ?? linesFromFileContents(file.contents), startingLine, totalLines) : file.contents, hastConfig));
	const code = isWindowedHighlight ? new Array(startingLine) : highlightedLines;
	if (isWindowedHighlight) code.push(...highlightedLines);
	return {
		code,
		themeStyles,
		baseThemeType
	};
}
function extractWindowedFileContent(lines, startingLine, totalLines) {
	if (lines.length === 0) return "";
	const endLine = Math.min(startingLine + totalLines, lines.length);
	return lines.slice(startingLine, endLine).join("");
}
//#endregion
export { renderFileWithHighlighter };

//# sourceMappingURL=renderFileWithHighlighter.js.map