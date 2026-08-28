import { isMacLike } from "../utils/platform.js";
import { isPrimaryModifier } from "./platform.js";
//#region src/editor/command.ts
const compiledEditorKeymaps = /* @__PURE__ */ new WeakMap();
const compiledDefaultKeymap = getCompiledEditorKeymap([
	{ bindings: {
		Tab: "indent",
		"shift+Tab": "outdent",
		"cmdOrCtrl+[": "indentLess",
		"cmdOrCtrl+]": "indentMore",
		"cmdOrCtrl+z": "undo",
		"cmdOrCtrl+shift+z": "redo",
		"cmdOrCtrl+a": "selectAll",
		"cmdOrCtrl+d": "findNextMatch",
		"cmdOrCtrl+f": "openSearchPanel",
		"cmdOrCtrl+alt+f": "openSearchReplacePanel",
		"alt+ArrowUp": "moveLineUp",
		"alt+ArrowDown": "moveLineDown",
		"shift+alt+ArrowUp": "copyLineUp",
		"shift+alt+ArrowDown": "copyLineDown",
		Escape: "simplifySelection",
		"cmdOrCtrl+Enter": "insertBlankLine",
		"cmdOrCtrl+/": "toggleComment",
		"shift+alt+a": "toggleBlockComment",
		"cmdOrCtrl+Home": "moveCursorToDocStart",
		"cmdOrCtrl+End": "moveCursorToDocEnd",
		"cmdOrCtrl+shift+Home": "expandSelectionDocStart",
		"cmdOrCtrl+shift+End": "expandSelectionDocEnd"
	} },
	{
		platform: "mac",
		bindings: {
			"ctrl+k": "deleteHardLineForward",
			"ctrl+alt+p": "moveLineUp",
			"ctrl+alt+n": "moveLineDown",
			"cmd+ArrowUp": "moveCursorToDocStart",
			"cmd+ArrowDown": "moveCursorToDocEnd",
			"cmd+shift+ArrowUp": "expandSelectionDocStart",
			"cmd+shift+ArrowDown": "expandSelectionDocEnd"
		}
	},
	{
		platform: "windows",
		bindings: { "ctrl+y": "redo" }
	},
	{
		platform: "linux",
		bindings: {
			"ctrl+y": "redo",
			"ctrl+alt+p": "moveLineUp",
			"ctrl+alt+n": "moveLineDown"
		}
	}
]);
const keyboardCodeKeys = {
	Backquote: "`",
	Minus: "-",
	Equal: "=",
	Comma: ",",
	Period: ".",
	Slash: "/",
	Semicolon: ";",
	Quote: "'",
	BracketLeft: "[",
	BracketRight: "]",
	Backslash: "\\",
	Space: "Space"
};
function getCompiledEditorKeymap(keymap) {
	let compiledKeymap = compiledEditorKeymaps.get(keymap);
	if (compiledKeymap === void 0) {
		compiledKeymap = {
			mac: /* @__PURE__ */ new Map(),
			windows: /* @__PURE__ */ new Map(),
			linux: /* @__PURE__ */ new Map()
		};
		for (const entry of keymap) for (const shortcut of Object.keys(entry.bindings)) {
			const command = entry.bindings[shortcut];
			if (command === void 0) continue;
			const parts = shortcut.split("+");
			const shortcutKey = parts.pop();
			for (const platform of [
				"mac",
				"windows",
				"linux"
			]) {
				if (entry.platform !== void 0 && entry.platform !== platform) continue;
				let modifiers = 0;
				for (const modifier of parts) if (modifier === "alt") modifiers |= 1;
				else if (modifier === "ctrl") modifiers |= 2;
				else if (modifier === "cmd") modifiers |= 4;
				else if (modifier === "shift") modifiers |= 8;
				else if (modifier === "cmdOrCtrl") modifiers |= platform === "mac" ? 4 : 2;
				let bindings = compiledKeymap[platform].get(modifiers);
				if (bindings === void 0) {
					bindings = /* @__PURE__ */ new Map();
					compiledKeymap[platform].set(modifiers, bindings);
				}
				bindings.set(shortcutKey, command);
			}
		}
		compiledEditorKeymaps.set(keymap, compiledKeymap);
	}
	return compiledKeymap;
}
function resolveEditorCommandFromKeyboardEvent(event, keymap, isMac = isMacLike()) {
	const eventKey = event.key === " " ? "Space" : event.key.length === 1 ? event.key.toLowerCase() : event.key;
	const code = event.code ?? "";
	const codeKey = code.startsWith("Key") && code.length === 4 ? code.slice(3).toLowerCase() : code.startsWith("Digit") && code.length === 6 ? code.slice(5) : keyboardCodeKeys[code];
	const platform = isMac ? "mac" : globalThis.navigator?.platform.includes("Linux") === true ? "linux" : "windows";
	const modifiers = (event.altKey ? 1 : 0) | (event.ctrlKey ? 2 : 0) | (event.metaKey ? 4 : 0) | (event.shiftKey ? 8 : 0);
	if (keymap !== void 0) {
		const bindings = getCompiledEditorKeymap(keymap)[platform].get(modifiers);
		const command = bindings?.get(eventKey) ?? (codeKey === void 0 ? void 0 : bindings?.get(codeKey));
		if (command !== void 0) return command;
	}
	const bindings = compiledDefaultKeymap[platform].get(modifiers);
	return bindings?.get(eventKey) ?? (codeKey === void 0 ? void 0 : bindings?.get(codeKey));
}
function resolveFindAgainShortcut(event, isMac = isMacLike()) {
	if (event.altKey) return;
	if (!isPrimaryModifier(event, isMac)) return;
	if ((event.key.length === 1 ? event.key.toLowerCase() : event.key) === "g" || event.code === "KeyG") return event.shiftKey ? "previous" : "next";
}
//#endregion
export { resolveEditorCommandFromKeyboardEvent, resolveFindAgainShortcut };

//# sourceMappingURL=command.js.map