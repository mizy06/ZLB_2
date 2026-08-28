import { isPrimaryModifier } from "./platform.js";
import { resolveFindAgainShortcut } from "./command.js";
import { h } from "./utils.js";
import { buildSearchReplacementText } from "./pieceTable.js";
import { getEditorIconSvg } from "./sprite.js";
//#region src/editor/searchPanel.ts
var SearchPanelWidget = class {
	#container;
	#inputElement;
	#updateMatches;
	#applyMode;
	#navigate;
	#close;
	constructor(options) {
		const { textDocument, containerElement, defaultQuery, mode = "find", initialMatch, scrollToMatch, applyReplace, onUpdate, onClose } = options;
		const searchParams = {
			text: defaultQuery,
			replaceText: "",
			caseSensitive: false,
			wholeWord: false,
			regex: false
		};
		const matches = {
			all: [],
			current: void 0
		};
		const matchResultElement = h("div", {
			dataset: {
				matches: "",
				noMatches: ""
			},
			textContent: "No results"
		});
		const updateMatches = (options) => {
			matches.all = searchParams.text !== "" ? textDocument.search(searchParams) : [];
			const noMatches = matches.all.length === 0;
			prevButton.disabled = noMatches;
			nextButton.disabled = noMatches;
			if (noMatches) {
				matchResultElement.textContent = "No results";
				matchResultElement.dataset.noMatches = "";
				matches.current = void 0;
				onUpdate([]);
				return;
			}
			delete matchResultElement.dataset.noMatches;
			if (options?.syncSelection === false) {
				updateCurrentMatch(onUpdate(matches.all, { syncSelection: false }));
				return;
			}
			updateCurrentMatch(onUpdate(matches.all));
		};
		this.#updateMatches = updateMatches;
		const updateCurrentMatch = (currentMatch) => {
			if (currentMatch === void 0) matchResultElement.textContent = `${matches.all.length} results`;
			else {
				const [start, end] = currentMatch;
				matchResultElement.textContent = `${matches.all.findIndex((m) => m[0] === start && m[1] === end) + 1} of ${matches.all.length}`;
			}
			matches.current = currentMatch;
		};
		const updateSearchParam = (key, value) => {
			searchParams[key] = value;
			updateMatches();
		};
		const findNextMatch = (findPrevious = false, retainFocus = false) => {
			const allMatches = matches.all;
			let nextMatch = allMatches[0];
			if (allMatches.length > 0) if (findPrevious) {
				const searchOffset = matches.current?.[0] ?? 0;
				nextMatch = allMatches.at(-1);
				for (const m of allMatches) if (m[1] <= searchOffset) nextMatch = m;
				else break;
			} else {
				const searchOffset = matches.current?.[1] ?? 0;
				for (const m of allMatches) if (m[0] >= searchOffset) {
					nextMatch = m;
					break;
				}
			}
			if (nextMatch !== void 0) {
				updateCurrentMatch(nextMatch);
				scrollToMatch(nextMatch, retainFocus);
			}
			matches.current = nextMatch;
		};
		this.#navigate = (findPrevious) => findNextMatch(findPrevious, true);
		const buildReplacementEdit = (matchStart, matchEnd) => ({
			start: matchStart,
			end: matchEnd,
			text: buildSearchReplacementText((offset) => textDocument.positionAt(offset), (position) => textDocument.offsetAt(position), (line) => textDocument.getLineText(line), searchParams, matchStart, matchEnd)
		});
		const replace = () => {
			if (searchParams.text === "" || matches.all.length === 0) return;
			let currentMatch = matches.current;
			if (currentMatch === void 0) {
				findNextMatch(false, true);
				currentMatch = matches.current;
				if (currentMatch === void 0) return;
			}
			const [start, end] = currentMatch;
			const edit = buildReplacementEdit(start, end);
			applyReplace([edit]);
			scrollToMatch([start + edit.text.length, start + edit.text.length], true);
			matches.current = void 0;
			updateMatches();
		};
		const replaceAll = () => {
			if (searchParams.text === "" || matches.all.length === 0) return;
			applyReplace(matches.all.map(([start, end]) => buildReplacementEdit(start, end)));
			matches.current = void 0;
			updateMatches();
		};
		const close = () => {
			this.cleanup();
			onClose();
		};
		this.#close = close;
		const iconButton = (opts) => h("button", {
			type: "button",
			title: opts.label,
			ariaLabel: opts.label,
			dataset: {
				searchIcon: "",
				...opts.dataset
			},
			innerHTML: getEditorIconSvg(opts.icon, opts.size ?? 16),
			onclick: opts.onClick
		});
		const makeToggle = (icon, title, key) => {
			const button = iconButton({
				icon,
				label: title,
				size: 14,
				onClick: () => {
					const next = !searchParams[key];
					button.ariaPressed = String(next);
					updateSearchParam(key, next);
				}
			});
			button.ariaPressed = String(searchParams[key]);
			return button;
		};
		const caseSensitiveToggle = makeToggle("case", "Match Case", "caseSensitive");
		const wholeWordToggle = makeToggle("whole-word", "Whole Word", "wholeWord");
		const regexToggle = makeToggle("regex", "Regexp", "regex");
		const replaceInputElement = h("input", {
			type: "text",
			placeholder: "Replace",
			dataset: "replace",
			value: "",
			oninput: (e) => {
				searchParams.replaceText = e.target.value;
			},
			onkeydown: (e) => {
				if (e.isComposing) return;
				const findAgain = resolveFindAgainShortcut(e);
				if (e.key === "Escape") {
					e.preventDefault();
					close();
				} else if (e.key === "Enter") {
					e.preventDefault();
					replace();
				} else if (findAgain !== void 0) {
					e.preventDefault();
					findNextMatch(findAgain === "previous", true);
				}
			}
		});
		this.#inputElement = h("input", {
			type: "text",
			placeholder: "Search",
			dataset: "search",
			value: defaultQuery,
			oninput: (e) => {
				searchParams.text = e.target.value;
				matches.current = void 0;
				updateMatches();
			},
			onkeydown: (e) => {
				const findAgain = resolveFindAgainShortcut(e);
				if (e.key === "Escape") {
					e.preventDefault();
					close();
				} else if (e.key === "Enter") {
					e.preventDefault();
					findNextMatch(e.shiftKey, true);
				} else if (findAgain !== void 0) {
					e.preventDefault();
					findNextMatch(findAgain === "previous", true);
				} else if (isPrimaryModifier(e) && (e.key === "f" || e.code === "KeyF")) {
					e.preventDefault();
					applyMode(e.altKey ? "replace" : "find");
				}
			}
		});
		const searchTogglesElement = h("div", {
			dataset: "searchToggles",
			children: [
				caseSensitiveToggle,
				wholeWordToggle,
				regexToggle
			]
		});
		const findInputBox = h("div", {
			dataset: {
				inputBox: "",
				find: ""
			},
			children: [this.#inputElement, searchTogglesElement]
		});
		const replaceInputBox = h("div", {
			dataset: {
				inputBox: "",
				replace: "",
				replaceCell: ""
			},
			children: [replaceInputElement]
		});
		const replaceActionsElement = h("div", {
			dataset: {
				replaceActions: "",
				replaceCell: ""
			},
			children: [iconButton({
				icon: "replace",
				label: "Replace",
				onClick: replace
			}), iconButton({
				icon: "replace-all",
				label: "Replace All",
				onClick: replaceAll
			})]
		});
		const prevButton = iconButton({
			icon: "arrow-up",
			label: "Previous",
			onClick: () => {
				findNextMatch(true);
			}
		});
		const nextButton = iconButton({
			icon: "arrow-down",
			label: "Next",
			onClick: () => {
				findNextMatch();
			}
		});
		prevButton.disabled = true;
		nextButton.disabled = true;
		const navElement = h("div", {
			dataset: "searchNav",
			children: [prevButton, nextButton]
		});
		const closeElement = iconButton({
			icon: "close",
			label: "Close",
			onClick: close,
			dataset: { searchClose: "" }
		});
		const gridElement = h("div", {
			dataset: {
				searchGrid: "",
				mode
			},
			children: [
				findInputBox,
				replaceInputBox,
				replaceActionsElement,
				matchResultElement,
				navElement,
				closeElement
			]
		});
		const applyMode = (next) => {
			gridElement.dataset.mode = next;
			this.#inputElement.focus();
			this.#inputElement.select();
		};
		this.#applyMode = applyMode;
		this.#container = h("div", {
			dataset: "searchPanel",
			children: [h("div", {
				dataset: "editorWidget",
				children: [gridElement]
			})]
		});
		matches.current = initialMatch;
		containerElement.before(this.#container);
		requestAnimationFrame(() => {
			if (initialMatch !== void 0) updateMatches();
			else onUpdate([]);
			this.#inputElement.select();
		});
	}
	focus() {
		this.#inputElement.focus();
	}
	navigate(findPrevious) {
		this.#navigate?.(findPrevious);
	}
	updateMatches(options) {
		this.#updateMatches?.(options);
	}
	setMode(mode) {
		this.#applyMode?.(mode);
	}
	close() {
		this.#close?.();
	}
	cleanup() {
		this.#container.remove();
	}
};
//#endregion
export { SearchPanelWidget };

//# sourceMappingURL=searchPanel.js.map