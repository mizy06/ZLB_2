import { addEventListener, getLineNumberAttr, h } from "./utils.js";
import { setPopoverPositionStyles } from "./popover.js";
import { selectionIntersects } from "./selection.js";
//#region src/editor/marker.ts
const MARKER_POPOVER_SHOW_DELAY_MS = 300;
const MARKER_POPOVER_HIDE_DELAY_MS = 100;
const MARKER_POPOVER_PLACEMENT_KEY = "marker-popover";
var MarkerRenderer = class {
	#options;
	#markers = [];
	#lineCount = 0;
	#markerPopoverElement;
	#markerPopoverEventDisposes;
	#markerEventDisposes;
	#markerPopoverShowTimeout;
	#markerPopoverHideTimeout;
	#pendingMarkerPopoverIndex;
	#hoveredMarkerIndex;
	#isMarkerPopoverHovered = false;
	constructor(editor) {
		this.#options = editor;
	}
	get markers() {
		return this.#markers;
	}
	isPopoverVisible() {
		return this.#hoveredMarkerIndex !== void 0;
	}
	updatePopoverPosition() {
		const hoveredMarkerIndex = this.#hoveredMarkerIndex;
		const popover = this.#markerPopoverElement;
		if (hoveredMarkerIndex === void 0 || popover === void 0) return;
		const marker = this.#markers[hoveredMarkerIndex];
		if (marker === void 0) {
			this.removePopover();
			return;
		}
		this.#positionMarkerPopover(popover, marker.start.line, marker.start.character);
	}
	setMarkers(markers, textDocument) {
		this.#lineCount = textDocument.lineCount;
		this.#markers = markers.map((marker) => ({
			...marker,
			start: textDocument.normalizePosition(marker.start),
			end: textDocument.normalizePosition(marker.end)
		}));
		this.removePopover();
	}
	listenHover(contentEl) {
		this.#markerEventDisposes?.forEach((dispose) => dispose());
		this.#markerEventDisposes = void 0;
		if (this.#markers.length === 0) return;
		this.#markerEventDisposes = [addEventListener(contentEl, "mouseover", (e) => {
			if (this.#options.isMouseDown()) return;
			const target = e.composedPath()[0];
			if (target === void 0) return;
			const hoverMarkerIndex = this.#findHoveredMarkerIndex(target);
			if (hoverMarkerIndex !== void 0) this.#scheduleMarkerPopover(hoverMarkerIndex);
			else {
				this.#cancelMarkerPopoverShow();
				this.#scheduleMarkerPopoverHide();
			}
		}), addEventListener(contentEl, "mouseleave", () => {
			this.#cancelMarkerPopoverShow();
			this.#scheduleMarkerPopoverHide();
		})];
	}
	removePopover() {
		this.#cancelMarkerPopoverShow();
		this.#cancelMarkerPopoverHide();
		this.#dismissMarkerPopover();
	}
	cleanup() {
		this.#markerEventDisposes?.forEach((dispose) => dispose());
		this.#markerEventDisposes = void 0;
		this.removePopover();
		this.#markers = [];
	}
	#findHoveredMarkerIndex(target) {
		const lineElement = target.closest("[data-line]");
		if (lineElement == null) return;
		const lineNumber = getLineNumberAttr(lineElement);
		if (lineNumber === void 0) return;
		let character;
		if (target.tagName === "SPAN") {
			const char = target.dataset.char;
			if (char === void 0) return;
			character = parseInt(char, 10);
			if (Number.isNaN(character)) return;
		} else if (target.tagName === "BR") character = 0;
		else return;
		const position = {
			line: lineNumber - 1,
			character
		};
		for (let i = this.#markers.length - 1; i >= 0; i--) if (selectionIntersects({
			start: position,
			end: position
		}, this.#markers[i])) return i;
	}
	#cancelMarkerPopoverShow() {
		if (this.#markerPopoverShowTimeout !== void 0) {
			clearTimeout(this.#markerPopoverShowTimeout);
			this.#markerPopoverShowTimeout = void 0;
		}
		this.#pendingMarkerPopoverIndex = void 0;
	}
	#cancelMarkerPopoverHide() {
		if (this.#markerPopoverHideTimeout !== void 0) {
			clearTimeout(this.#markerPopoverHideTimeout);
			this.#markerPopoverHideTimeout = void 0;
		}
	}
	#scheduleMarkerPopover(markerIndex) {
		if (markerIndex === this.#hoveredMarkerIndex || markerIndex === this.#pendingMarkerPopoverIndex) {
			this.#cancelMarkerPopoverHide();
			return;
		}
		this.#cancelMarkerPopoverShow();
		this.#cancelMarkerPopoverHide();
		if (this.#markerPopoverElement !== void 0) {
			this.#renderMarkerPopover(markerIndex);
			return;
		}
		this.#pendingMarkerPopoverIndex = markerIndex;
		this.#markerPopoverShowTimeout = setTimeout(() => {
			this.#markerPopoverShowTimeout = void 0;
			this.#pendingMarkerPopoverIndex = void 0;
			this.#renderMarkerPopover(markerIndex);
		}, MARKER_POPOVER_SHOW_DELAY_MS);
	}
	#scheduleMarkerPopoverHide() {
		if (this.#isMarkerPopoverHovered) return;
		this.#cancelMarkerPopoverHide();
		this.#markerPopoverHideTimeout = setTimeout(() => {
			this.#markerPopoverHideTimeout = void 0;
			if (!this.#isMarkerPopoverHovered) this.removePopover();
		}, MARKER_POPOVER_HIDE_DELAY_MS);
	}
	#setMarkerPopoverPosition(popover, x, y, placeAbove, viewport = this.#options.popoverManager.getPlacementBounds()) {
		setPopoverPositionStyles(popover, {
			gutterWidth: this.#options.getGutterWidth(),
			placeAbove,
			viewport,
			x,
			y
		});
	}
	#positionMarkerPopover(popover, line, character) {
		const { getCharX, getLineY, getLineHeight, popoverManager } = this.#options;
		const [left, wrapLine] = getCharX(line, character);
		const lineHeight = getLineHeight();
		const rowTop = getLineY(line) + wrapLine * lineHeight;
		const popoverHeight = popover.offsetHeight;
		const preferred = {
			top: rowTop + lineHeight,
			bottom: rowTop + lineHeight + popoverHeight
		};
		const fallback = {
			top: rowTop - popoverHeight,
			bottom: rowTop
		};
		const atDocumentEdge = line >= this.#lineCount - 3;
		const viewport = popoverManager.getPlacementBounds();
		const placeAbove = popoverManager.choosePlacement({
			preferred,
			fallback,
			viewport,
			popoverHeight,
			atDocumentEdge,
			placementKey: MARKER_POPOVER_PLACEMENT_KEY
		}) === "fallback";
		this.#setMarkerPopoverPosition(popover, left, placeAbove ? rowTop : rowTop + lineHeight, placeAbove, viewport);
	}
	#dismissMarkerPopover() {
		this.#markerPopoverEventDisposes?.forEach((dispose) => dispose());
		this.#markerPopoverEventDisposes = void 0;
		this.#markerPopoverElement?.remove();
		this.#markerPopoverElement = void 0;
		this.#hoveredMarkerIndex = void 0;
		this.#isMarkerPopoverHovered = false;
		this.#options.popoverManager.resetPlacement(MARKER_POPOVER_PLACEMENT_KEY);
	}
	#renderMarkerPopover(hoveredMarkerIndex) {
		if (hoveredMarkerIndex === this.#hoveredMarkerIndex) return;
		const overlayElement = this.#options.getOverlayElement();
		if (hoveredMarkerIndex >= this.#markers.length || overlayElement == null) return;
		const { start, message, severity } = this.#markers[hoveredMarkerIndex];
		const { line, character } = start;
		const popover = this.#markerPopoverElement;
		this.#options.popoverManager.resetPlacement(MARKER_POPOVER_PLACEMENT_KEY);
		if (popover !== void 0) {
			setMarkerPopoverSeverity(popover, severity);
			const content = popover.firstElementChild;
			if (content?.dataset.markerMessage !== void 0) if (typeof message === "string") content.textContent = message;
			else if (message instanceof HTMLElement) content.replaceChildren(message);
			else content.innerHTML = message.html;
			this.#positionMarkerPopover(popover, line, character);
			this.#hoveredMarkerIndex = hoveredMarkerIndex;
			return;
		}
		this.#markerPopoverElement = h("div", {
			dataset: {
				editorWidget: "",
				markerPopover: "",
				[markerSeverityDatasetKey(severity)]: ""
			},
			children: [h("div", {
				dataset: "markerMessage",
				...typeof message === "string" ? { textContent: message } : message instanceof HTMLElement ? { children: [message] } : { innerHTML: message.html }
			})]
		}, overlayElement);
		this.#positionMarkerPopover(this.#markerPopoverElement, line, character);
		this.#hoveredMarkerIndex = hoveredMarkerIndex;
		this.#markerPopoverEventDisposes = [addEventListener(this.#markerPopoverElement, "mouseenter", () => {
			this.#isMarkerPopoverHovered = true;
			this.#cancelMarkerPopoverHide();
		}), addEventListener(this.#markerPopoverElement, "mouseleave", () => {
			this.#isMarkerPopoverHovered = false;
			this.#scheduleMarkerPopoverHide();
		})];
	}
};
const MARKER_SEVERITIES = [
	"error",
	"warning",
	"info",
	"hint"
];
function setMarkerPopoverSeverity(popover, severity) {
	for (const candidate of MARKER_SEVERITIES) delete popover.dataset[markerSeverityDatasetKey(candidate)];
	popover.dataset[markerSeverityDatasetKey(severity)] = "";
}
function markerSeverityDatasetKey(severity) {
	switch (severity) {
		case "error": return "markerError";
		case "warning": return "markerWarning";
		case "info": return "markerInfo";
		case "hint": return "markerHint";
	}
}
//#endregion
export { MarkerRenderer, markerSeverityDatasetKey };

//# sourceMappingURL=marker.js.map