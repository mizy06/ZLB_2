"use client";
import { useStableCallback } from "./utils/useStableCallback.js";
import { createContext, useContext, useRef } from "react";
import { jsx } from "react/jsx-runtime";
//#region src/react/EditContext.tsx
const EditContext = createContext(void 0);
function EditProvider({ children, createEditor }) {
	const editorCacheRef = useRef(/* @__PURE__ */ new WeakMap());
	const stableCreateEditor = useStableCallback((options) => {
		const cached = editorCacheRef.current.get(options);
		if (cached != null) return cached;
		const editor = createEditor(options);
		editorCacheRef.current.set(options, editor);
		return editor;
	});
	return /* @__PURE__ */ jsx(EditContext.Provider, {
		value: stableCreateEditor,
		children
	});
}
function useCreateEditor() {
	return useContext(EditContext);
}
//#endregion
export { EditContext, EditProvider, useCreateEditor };

//# sourceMappingURL=EditContext.js.map