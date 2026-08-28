import { areOptionsEqual } from "../../utils/areOptionsEqual.js";
import { File } from "../../components/File.js";
import { VirtualizedFile } from "../../components/VirtualizedFile.js";
import { useStableCallback } from "./useStableCallback.js";
import { useCreateEditor } from "../EditContext.js";
import { noopRender } from "../constants.js";
import { WorkerPoolContext } from "../WorkerPoolContext.js";
import { useVirtualizer } from "../Virtualizer.js";
import { useCallback, useContext, useEffect, useLayoutEffect, useRef } from "react";
//#region src/react/utils/useFileInstance.ts
const useIsomorphicLayoutEffect = typeof window === "undefined" ? useEffect : useLayoutEffect;
function useFileInstance({ file, options, editorOptions, lineAnnotations, selectedLines, prerenderedHTML, metrics, hasGutterRenderUtility, hasCustomHeader, disableWorkerPool, edit }) {
	const simpleVirtualizer = useVirtualizer();
	const controlledSelection = selectedLines !== void 0;
	const poolManager = useContext(WorkerPoolContext);
	const createEditor = useCreateEditor();
	const instanceRef = useRef(null);
	const ref = useStableCallback((node) => {
		if (node != null) {
			if (instanceRef.current != null) throw new Error("File: An instance should not already exist when a node is created");
			if (simpleVirtualizer != null) instanceRef.current = new VirtualizedFile(mergeFileOptions({
				controlledSelection,
				hasCustomHeader,
				hasGutterRenderUtility,
				options
			}), simpleVirtualizer, metrics, !disableWorkerPool ? poolManager : void 0, true);
			else instanceRef.current = new File(mergeFileOptions({
				controlledSelection,
				hasCustomHeader,
				hasGutterRenderUtility,
				options
			}), !disableWorkerPool ? poolManager : void 0, true);
			instanceRef.current.hydrate({
				file,
				fileContainer: node,
				lineAnnotations,
				prerenderedHTML
			});
		} else {
			if (instanceRef.current == null) throw new Error("File: A File instance should exist when unmounting");
			instanceRef.current.cleanUp();
			instanceRef.current = null;
		}
	});
	useIsomorphicLayoutEffect(() => {
		if (instanceRef.current == null) return;
		const newOptions = mergeFileOptions({
			controlledSelection,
			hasCustomHeader,
			hasGutterRenderUtility,
			options
		});
		const forceRender = newOptions !== void 0 && !areOptionsEqual(instanceRef.current.options, newOptions);
		instanceRef.current.setOptions(newOptions);
		instanceRef.current.render({
			file,
			lineAnnotations,
			forceRender
		});
		if (selectedLines !== void 0) instanceRef.current.setSelectedLines(selectedLines);
	});
	useIsomorphicLayoutEffect(() => {
		if (edit && instanceRef.current != null) {
			if (createEditor === void 0) throw new Error("File: EditContext is not attached");
			const editor = createEditor(editorOptions ?? {});
			if (editor == null) throw new Error("File: EditProvider.createEditor must return an editor instance");
			try {
				return editor.edit(instanceRef.current);
			} catch (error) {
				editor.cleanUp();
				throw error;
			}
		}
	}, [edit]);
	return {
		ref,
		getHoveredLine: useCallback(() => {
			return instanceRef.current?.getHoveredLine();
		}, [])
	};
}
function mergeFileOptions({ options, controlledSelection, hasCustomHeader, hasGutterRenderUtility }) {
	if (!(controlledSelection || hasGutterRenderUtility || hasCustomHeader)) return options;
	return {
		...options,
		controlledSelection,
		renderCustomHeader: hasCustomHeader ? noopRender : options?.renderCustomHeader,
		renderGutterUtility: hasGutterRenderUtility ? noopRender : options?.renderGutterUtility
	};
}
//#endregion
export { useFileInstance };

//# sourceMappingURL=useFileInstance.js.map