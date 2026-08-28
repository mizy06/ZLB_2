"use client";
import { areManagedSnapshotsEqual } from "../utils/areManagedSnapshotsEqual.js";
import { areOptionsEqual } from "../utils/areOptionsEqual.js";
import { CodeView as CodeView$1 } from "../components/CodeView.js";
import { useStableCallback } from "./utils/useStableCallback.js";
import { useCreateEditor } from "./EditContext.js";
import { renderDiffChildren } from "./utils/renderDiffChildren.js";
import { renderFileChildren } from "./utils/renderFileChildren.js";
import { WorkerPoolContext } from "./WorkerPoolContext.js";
import { forwardRef, memo, useContext, useEffect, useImperativeHandle, useLayoutEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { createPortal, flushSync } from "react-dom";
import { Fragment, jsx, jsxs } from "react/jsx-runtime";
//#region src/react/CodeView.tsx
const useIsomorphicLayoutEffect = typeof window === "undefined" ? useEffect : useLayoutEffect;
function createDefaultCache(controlled) {
	return {
		instance: void 0,
		items: void 0,
		controlled,
		managedOptions: void 0,
		disableFlushSync: false,
		slotCoordinator: void 0
	};
}
function CodeViewInner(props, ref) {
	const { className, containerRef, disableWorkerPool = false, editorOptions, initialItems, items: controlledItems, onItemEditChange, onItemEditComplete, onScroll, onSelectedLinesChange, options, renderAnnotation, renderCodeViewFooter, renderCodeViewHeader, renderCustomHeader, renderGutterUtility, renderHeaderFilenameSuffix, renderHeaderMetadata, renderHeaderPrefix, selectedLines, style } = props;
	const controlled = controlledItems !== void 0;
	const contextCreateEditor = useCreateEditor();
	const poolManager = useContext(WorkerPoolContext);
	const cachedDataRef = useRef(createDefaultCache(controlled));
	const hasCustomHeader = renderCustomHeader != null;
	const hasAnnotationRenderer = renderAnnotation != null;
	const hasGutterRenderer = renderGutterUtility != null;
	const hasHeaderRenderers = hasCustomHeader || renderHeaderPrefix != null || renderHeaderFilenameSuffix != null || renderHeaderMetadata != null;
	const hasRenderers = hasHeaderRenderers || hasAnnotationRenderer || hasGutterRenderer;
	const hasCodeViewHeader = renderCodeViewHeader != null;
	const hasCodeViewFooter = renderCodeViewFooter != null;
	const emitSelectedLinesChange = useStableCallback((selection) => {
		onSelectedLinesChange?.(selection);
	});
	const controlledSelection = selectedLines !== void 0;
	const createEditor = useStableCallback((options) => {
		if (contextCreateEditor == null) throw new Error("CodeView: EditContext is not attached");
		const editor = contextCreateEditor({
			...editorOptions,
			...options
		});
		if (editor == null) throw new Error("CodeView: EditProvider.createEditor must return an editor instance");
		return editor;
	});
	const emitItemEditChange = useStableCallback((item, file, lineAnnotations) => {
		onItemEditChange?.(item, file, lineAnnotations);
	});
	const emitItemEditComplete = useStableCallback((item, file, lineAnnotations) => {
		onItemEditComplete?.(item, file, lineAnnotations);
	});
	const managedOptions = useMemo(() => createManagedCodeViewOptions({
		options,
		hasCustomHeader,
		hasGutterRenderer,
		hasCodeViewHeader,
		hasCodeViewFooter,
		onSelectedLinesChange: onSelectedLinesChange != null ? emitSelectedLinesChange : void 0,
		controlledSelection,
		createEditor: contextCreateEditor != null ? createEditor : void 0,
		onItemEditChange: onItemEditChange != null ? emitItemEditChange : void 0,
		onItemEditComplete: onItemEditComplete != null ? emitItemEditComplete : void 0
	}), [
		contextCreateEditor,
		controlledSelection,
		createEditor,
		emitItemEditChange,
		emitItemEditComplete,
		emitSelectedLinesChange,
		hasCodeViewFooter,
		hasCodeViewHeader,
		hasCustomHeader,
		hasGutterRenderer,
		onItemEditChange,
		onItemEditComplete,
		onSelectedLinesChange,
		options
	]);
	const [slotContentStore] = useState(() => createSlotContentStore());
	const [, forceUpdate] = useState({});
	const nodeRef = useStableCallback((node) => {
		if (cachedDataRef.current.instance != null && (node == null || node !== cachedDataRef.current.instance.getContainerElement())) {
			cachedDataRef.current.instance.cleanUp();
			slotContentStore.publish(void 0);
			cachedDataRef.current = createDefaultCache(controlled);
		}
		if (node != null && node !== cachedDataRef.current.instance?.getContainerElement()) {
			cachedDataRef.current.instance = new CodeView$1(managedOptions, !disableWorkerPool ? poolManager : void 0, true);
			cachedDataRef.current.instance.setup(node);
		}
		if (typeof containerRef === "function") containerRef(node);
		else if (containerRef != null) containerRef.current = node;
	});
	const onSnapshotChange = useStableCallback((snapshot) => {
		if (cachedDataRef.current.disableFlushSync) slotContentStore.publish(snapshot);
		else flushSync(() => {
			slotContentStore.publish(snapshot);
		});
	});
	const slotCoordinator = useMemo(() => {
		if (!hasHeaderRenderers && !hasAnnotationRenderer && !hasGutterRenderer && !hasCodeViewHeader && !hasCodeViewFooter) return;
		else return {
			hasHeaderRenderers,
			hasAnnotationRenderer,
			hasGutterRenderer,
			onSnapshotChange
		};
	}, [
		onSnapshotChange,
		hasAnnotationRenderer,
		hasGutterRenderer,
		hasHeaderRenderers,
		hasCodeViewHeader,
		hasCodeViewFooter
	]);
	useIsomorphicLayoutEffect(() => {
		return onScroll != null ? cachedDataRef.current.instance?.subscribeToScroll(onScroll) : void 0;
	});
	useIsomorphicLayoutEffect(() => {
		const { instance, controlled: prevControlled, items: prevItems, managedOptions: prevManagedOptions, slotCoordinator: prevSlotCoordinator } = cachedDataRef.current;
		if (instance == null) return;
		try {
			cachedDataRef.current.disableFlushSync = true;
			let shouldRender = false;
			if (!areOptionsEqual(managedOptions, prevManagedOptions)) {
				cachedDataRef.current.managedOptions = managedOptions;
				instance.setOptions(managedOptions);
				shouldRender = true;
			}
			if (prevControlled !== controlled) {
				console.error("CodeView: cannot switch between controlled and uncontrolled modes. Remount with a new key instead.");
				return;
			}
			if (controlled) {
				if (controlledItems !== prevItems) if (areItemListsEqual(prevItems, controlledItems)) cachedDataRef.current.items = controlledItems;
				else if (isAppendOnlyItemUpdate(prevItems, controlledItems)) {
					cachedDataRef.current.items = controlledItems;
					instance.addItems(controlledItems.slice(prevItems.length));
				} else {
					cachedDataRef.current.items = controlledItems;
					instance.setItems(controlledItems);
					shouldRender = true;
				}
			} else if (prevItems == null) {
				const seedItems = initialItems ?? [];
				cachedDataRef.current.items = seedItems;
				if (seedItems.length > 0) {
					instance.setItems(seedItems);
					shouldRender = true;
				}
			}
			if (selectedLines !== void 0) instance.setSelectedLines(selectedLines, { notify: false });
			const slotPublish = instance.setSlotCoordinator(slotCoordinator);
			let forceInlinePublish = false;
			if (slotCoordinator !== prevSlotCoordinator) {
				if (slotCoordinator == null || prevSlotCoordinator == null) forceInlinePublish = true;
				cachedDataRef.current.slotCoordinator = slotCoordinator;
			}
			if (shouldRender || slotPublish) instance.render(true);
			if (slotPublish && slotCoordinator == null) slotContentStore.publish(void 0);
			if (forceInlinePublish) forceUpdate({});
		} finally {
			cachedDataRef.current.disableFlushSync = false;
		}
	});
	useImperativeHandle(ref, () => ({
		addItems(items) {
			const { controlled, instance } = cachedDataRef.current;
			assertUncontrolledCodeViewAction(controlled, "addItems");
			if (instance == null) console.error("CodeView.addItems: no valid instance to append items with", items);
			else instance.addItems(items);
		},
		getItem(id) {
			const { instance } = cachedDataRef.current;
			if (instance == null) {
				console.error("CodeView.getItem: no valid instance exists", id);
				return;
			} else return instance.getItem(id);
		},
		removeItem(id) {
			const { controlled, instance } = cachedDataRef.current;
			assertUncontrolledCodeViewAction(controlled, "removeItem");
			if (instance == null) {
				console.error("CodeView.removeItem: no valid instance to remove item from", id);
				return false;
			}
			return instance.removeItem(id);
		},
		updateItem(item) {
			const { controlled, instance } = cachedDataRef.current;
			assertUncontrolledCodeViewAction(controlled, "updateItem");
			if (instance == null) {
				console.error("CodeView.updateItem: no valid instance to update item with", item);
				return false;
			}
			return instance.updateItem(item);
		},
		updateItemId(oldId, newId) {
			const { controlled, instance } = cachedDataRef.current;
			assertUncontrolledCodeViewAction(controlled, "updateItemId");
			if (instance == null) {
				console.error("CodeView.updateItemId: no valid instance to update item id with", oldId, newId);
				return false;
			}
			return instance.updateItemId(oldId, newId);
		},
		scrollTo(target) {
			const { instance } = cachedDataRef.current;
			if (instance == null) console.error("CodeView.scrollTo: no valid instance to scroll with", target);
			else instance.scrollTo(target);
		},
		setSelectedLines(selection) {
			const { instance } = cachedDataRef.current;
			if (instance == null) console.error("CodeView.setSelectedLines: no valid instance to update selection with", selection);
			else {
				instance.setSelectedLines(selection, { notify: false });
				emitSelectedLinesChange(selection);
			}
		},
		getSelectedLines() {
			const { instance } = cachedDataRef.current;
			if (instance == null) {
				console.error("CodeView.getSelectedLines: no valid instance exists");
				return null;
			} else return instance.getSelectedLines();
		},
		clearSelectedLines() {
			const { instance } = cachedDataRef.current;
			if (instance == null) console.error("CodeView.clearSelectedLines: no valid instance to update selection with");
			else {
				instance.clearSelectedLines({ notify: false });
				emitSelectedLinesChange(null);
			}
		},
		getEditor(id) {
			const { instance } = cachedDataRef.current;
			if (instance == null) {
				console.error("CodeView.getEditor: no valid instance exists", id);
				return;
			}
			return instance.getEditor(id);
		},
		getInstance() {
			return cachedDataRef.current.instance;
		}
	}), [emitSelectedLinesChange]);
	return /* @__PURE__ */ jsxs(Fragment, { children: [/* @__PURE__ */ jsx("div", {
		ref: nodeRef,
		className,
		style
	}), (hasRenderers || hasCodeViewHeader || hasCodeViewFooter) && /* @__PURE__ */ jsx(SlotPortals, {
		managedContentStore: slotContentStore,
		renderCustomHeader,
		renderHeaderPrefix,
		renderHeaderFilenameSuffix,
		renderHeaderMetadata,
		renderAnnotation,
		renderGutterUtility,
		renderCodeViewHeader,
		renderCodeViewFooter
	})] });
}
const CodeView = forwardRef(CodeViewInner);
function isAppendOnlyItemUpdate(previousItems, nextItems) {
	if (previousItems == null || nextItems.length <= previousItems.length) return false;
	if (previousItems.length === 0) return true;
	for (let index = 0; index < previousItems.length; index++) if (nextItems[index] !== previousItems[index]) return false;
	return true;
}
function areItemListsEqual(previousItems, nextItems) {
	if (previousItems == null || previousItems.length !== nextItems.length) return false;
	for (let index = 0; index < previousItems.length; index++) if (previousItems[index] !== nextItems[index]) return false;
	return true;
}
function assertUncontrolledCodeViewAction(controlled, action) {
	if (!controlled) return;
	throw new Error(`CodeView.${action} cannot be used when CodeView is controlled. Use initialItems for imperative item updates.`);
}
function createSlotContentStore() {
	let snapshot;
	const listeners = /* @__PURE__ */ new Set();
	return {
		getSnapshot() {
			return snapshot;
		},
		publish(nextSnapshot) {
			if (areManagedSnapshotsEqual(snapshot, nextSnapshot)) return;
			snapshot = nextSnapshot;
			for (const listener of listeners) listener();
		},
		subscribe(listener) {
			listeners.add(listener);
			return () => {
				listeners.delete(listener);
			};
		}
	};
}
function createManagedCodeViewOptions({ options, hasCustomHeader, hasGutterRenderer, hasCodeViewHeader, hasCodeViewFooter, onSelectedLinesChange, controlledSelection, createEditor, onItemEditChange, onItemEditComplete }) {
	const managedOptions = {
		...options,
		controlledSelection,
		onSelectedLinesChange,
		createEditor
	};
	if (onItemEditChange != null) managedOptions.onItemEditChange = onItemEditChange;
	if (onItemEditComplete != null) managedOptions.onItemEditComplete = onItemEditComplete;
	if (hasCustomHeader) managedOptions.renderCustomHeader = noopRender;
	if (hasGutterRenderer) managedOptions.renderGutterUtility = noopRender;
	if (hasCodeViewHeader) managedOptions.renderCodeViewHeader = noopRender;
	if (hasCodeViewFooter) managedOptions.renderCodeViewFooter = noopRender;
	return managedOptions;
}
const SlotPortals = memo(function SlotPortals({ managedContentStore, renderCustomHeader, renderHeaderPrefix, renderHeaderFilenameSuffix, renderHeaderMetadata, renderAnnotation, renderGutterUtility, renderCodeViewHeader, renderCodeViewFooter }) {
	"use no memo";
	const subscribe = useStableCallback((listener) => managedContentStore.subscribe(listener));
	const getSnapshot = useStableCallback(() => managedContentStore.getSnapshot());
	const snapshot = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
	let itemKeys = "";
	for (const item of snapshot?.items ?? []) itemKeys += `${item.id}:${item.version}:${item.type}`;
	return /* @__PURE__ */ jsxs(Fragment, { children: [
		useMemo(() => {
			return snapshot?.items?.map((renderedItem) => createPortal(renderCodeViewItemChildren({
				renderedItem,
				renderCustomHeader,
				renderHeaderPrefix,
				renderHeaderFilenameSuffix,
				renderHeaderMetadata,
				renderAnnotation,
				renderGutterUtility
			}), renderedItem.element, renderedItem.id));
		}, [
			renderCustomHeader,
			renderHeaderPrefix,
			renderHeaderFilenameSuffix,
			renderHeaderMetadata,
			renderAnnotation,
			renderGutterUtility,
			itemKeys
		]),
		useMemo(() => {
			return renderCodeViewHeader != null && snapshot?.header != null ? createPortal(renderCodeViewHeader(), snapshot.header) : null;
		}, [renderCodeViewHeader, snapshot?.header]),
		useMemo(() => {
			return renderCodeViewFooter != null && snapshot?.footer != null ? createPortal(renderCodeViewFooter(), snapshot.footer) : null;
		}, [renderCodeViewFooter, snapshot?.footer])
	] });
});
function renderCodeViewItemChildren({ renderedItem, renderCustomHeader, renderHeaderPrefix, renderHeaderFilenameSuffix, renderHeaderMetadata, renderAnnotation, renderGutterUtility }) {
	if (renderedItem.type === "diff") {
		const { item, instance } = renderedItem;
		return renderDiffChildren({
			fileDiff: item.fileDiff,
			renderCustomHeader: renderCustomHeader != null ? () => renderCustomHeader(item) : void 0,
			renderHeaderPrefix: renderHeaderPrefix != null ? () => renderHeaderPrefix(item) : void 0,
			renderHeaderFilenameSuffix: renderHeaderFilenameSuffix != null ? () => renderHeaderFilenameSuffix(item) : void 0,
			renderHeaderMetadata: renderHeaderMetadata != null ? () => renderHeaderMetadata(item) : void 0,
			renderAnnotation: renderAnnotation != null ? (annotation) => renderAnnotation(annotation, item) : void 0,
			lineAnnotations: item.annotations,
			renderGutterUtility: renderGutterUtility != null ? (getHoveredLine) => renderGutterUtility(getHoveredLine, item) : void 0,
			getHoveredLine: instance.getHoveredLine
		});
	} else {
		const { item, instance } = renderedItem;
		return renderFileChildren({
			file: item.file,
			renderCustomHeader: renderCustomHeader != null ? () => renderCustomHeader(item) : void 0,
			renderHeaderPrefix: renderHeaderPrefix != null ? () => renderHeaderPrefix(item) : void 0,
			renderHeaderFilenameSuffix: renderHeaderFilenameSuffix != null ? () => renderHeaderFilenameSuffix(item) : void 0,
			renderHeaderMetadata: renderHeaderMetadata != null ? () => renderHeaderMetadata(item) : void 0,
			renderAnnotation: renderAnnotation != null ? (annotation) => renderAnnotation(annotation, item) : void 0,
			lineAnnotations: item.annotations,
			renderGutterUtility: renderGutterUtility != null ? (getHoveredLine) => renderGutterUtility(getHoveredLine, item) : void 0,
			getHoveredLine: instance.getHoveredLine
		});
	}
}
function noopRender() {}
//#endregion
export { CodeView };

//# sourceMappingURL=CodeView.js.map