"use client";
import { DIFFS_TAG_NAME } from "../constants.js";
import { renderFileChildren } from "./utils/renderFileChildren.js";
import { templateRender } from "./utils/templateRender.js";
import { useFileInstance } from "./utils/useFileInstance.js";
import { jsx } from "react/jsx-runtime";
//#region src/react/File.tsx
function File({ file, lineAnnotations, selectedLines, options, editorOptions, metrics, className, style, renderAnnotation, renderCustomHeader, renderHeaderPrefix, renderHeaderFilenameSuffix, renderHeaderMetadata, prerenderedHTML, renderGutterUtility, disableWorkerPool = false, edit = false }) {
	const { ref, getHoveredLine } = useFileInstance({
		file,
		options,
		editorOptions,
		metrics,
		lineAnnotations,
		selectedLines,
		prerenderedHTML,
		hasGutterRenderUtility: renderGutterUtility != null,
		hasCustomHeader: renderCustomHeader != null,
		disableWorkerPool,
		edit
	});
	return /* @__PURE__ */ jsx(DIFFS_TAG_NAME, {
		ref,
		className,
		style,
		children: templateRender(renderFileChildren({
			file,
			renderAnnotation,
			renderCustomHeader,
			renderHeaderPrefix,
			renderHeaderFilenameSuffix,
			renderHeaderMetadata,
			renderGutterUtility,
			lineAnnotations,
			getHoveredLine
		}), prerenderedHTML)
	});
}
//#endregion
export { File };

//# sourceMappingURL=File.js.map