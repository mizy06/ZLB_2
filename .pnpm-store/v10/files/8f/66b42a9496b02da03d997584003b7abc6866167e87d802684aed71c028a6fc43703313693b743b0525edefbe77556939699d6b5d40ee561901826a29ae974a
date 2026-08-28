import { addEventListener } from "./utils.js";
//#region src/editor/popover.ts
const POPOVER_BOUNDARY_LINES = 3;
const POPOVER_FLIP_HYSTERESIS_PX = 4;
/**
* Shared placement logic for the editor's overlay popovers: each anchors below
* or above a document position, flipping to the opposite side only when the
* preferred side would be clipped by the visible scrollport.
*/
var PopoverManager = class {
	#fileContainer;
	#codeElement;
	#scrollContainer;
	#scrollContainerSource;
	#cachedCodeRect;
	#cachedScrollContainerRect;
	#cachedCodeScrollLeft = 0;
	#cachedCodeScrollTop = 0;
	#cachedCodeClientWidth = 0;
	#viewportRectsDirty = true;
	#viewportRectListenersDisposes;
	#placements = /* @__PURE__ */ new Map();
	#hasActivePopover;
	#updateActivePopover;
	constructor(options) {
		this.#hasActivePopover = options.hasActivePopover;
		this.#updateActivePopover = options.updateActivePopover;
	}
	setViewportElements(fileContainer, codeElement) {
		const viewportElementChanged = this.#fileContainer !== fileContainer || this.#codeElement !== codeElement;
		this.#fileContainer = fileContainer;
		if (!viewportElementChanged) return;
		this.#codeElement = codeElement;
		this.#viewportRectsDirty = true;
		this.#viewportRectListenersDisposes?.forEach((dispose) => dispose());
		this.#viewportRectListenersDisposes = void 0;
	}
	cleanUp() {
		this.#codeElement = void 0;
		this.#fileContainer = void 0;
		this.#scrollContainer = void 0;
		this.#scrollContainerSource = void 0;
		this.#cachedCodeRect = void 0;
		this.#cachedScrollContainerRect = void 0;
		this.#cachedCodeScrollLeft = 0;
		this.#cachedCodeScrollTop = 0;
		this.#cachedCodeClientWidth = 0;
		this.#viewportRectsDirty = true;
		this.#viewportRectListenersDisposes?.forEach((dispose) => dispose());
		this.#viewportRectListenersDisposes = void 0;
		this.#placements.clear();
	}
	resetPlacement(placementKey = "default") {
		this.#placements.delete(placementKey);
	}
	setPlacement(placement, placementKey = "default") {
		this.#placements.set(placementKey, placement);
	}
	choosePlacement(input) {
		const { preferred, fallback, viewport, popoverHeight, atDocumentEdge, placementKey = "default" } = input;
		const previousPlacement = this.#placements.get(placementKey);
		let placement;
		if (viewport !== void 0 && popoverHeight > 0) {
			const fits = (bounds, margin = 0) => bounds.top >= viewport.top + margin && bounds.bottom <= viewport.bottom - margin;
			if (previousPlacement === "fallback" && fits(fallback) && !fits(preferred, 4)) placement = "fallback";
			else if (!fits(preferred) && fits(fallback)) placement = "fallback";
			else placement = "preferred";
		} else placement = atDocumentEdge ? "fallback" : "preferred";
		this.#placements.set(placementKey, placement);
		return placement;
	}
	/**
	* Returns the bounds of the popover in overlay coordinate space.
	*/
	getPlacementBounds() {
		const codeRect = this.#getCodeRect();
		if (codeRect === void 0) return;
		const scrollContainerRect = this.#getScrollContainerRect();
		let topScreen;
		let bottomScreen;
		if (scrollContainerRect !== void 0) {
			topScreen = scrollContainerRect.top;
			bottomScreen = scrollContainerRect.bottom;
		} else {
			topScreen = 0;
			bottomScreen = window.innerHeight;
		}
		topScreen = Math.max(topScreen, codeRect.top);
		bottomScreen = Math.min(bottomScreen, codeRect.bottom);
		if (bottomScreen <= topScreen) return;
		const codeScrollLeft = this.#cachedCodeScrollLeft;
		const codeScrollTop = this.#cachedCodeScrollTop;
		const codeViewportWidth = this.#cachedCodeClientWidth > 0 ? this.#cachedCodeClientWidth : codeRect.width;
		const leftScreen = scrollContainerRect !== void 0 ? scrollContainerRect.left : 0;
		const rightScreen = scrollContainerRect !== void 0 ? scrollContainerRect.right : window.innerWidth;
		const codeViewportLeft = codeScrollLeft;
		const codeViewportRight = codeScrollLeft + codeViewportWidth;
		const visibleLeft = Math.max(codeViewportLeft, leftScreen - codeRect.left + codeScrollLeft);
		const visibleRight = Math.min(codeViewportRight, rightScreen - codeRect.left + codeScrollLeft);
		return {
			top: topScreen - codeRect.top + codeScrollTop,
			bottom: bottomScreen - codeRect.top + codeScrollTop,
			left: visibleLeft,
			right: Math.max(visibleLeft, visibleRight)
		};
	}
	#getScrollContainer() {
		const fileContainer = this.#fileContainer;
		if (fileContainer === void 0) return;
		if (this.#scrollContainerSource === fileContainer) {
			if (this.#scrollContainer === void 0 || this.#scrollContainer.isConnected) return this.#scrollContainer;
		}
		let element = fileContainer.parentElement;
		while (element !== null) {
			const overflowY = getComputedStyle(element).overflowY;
			if (overflowY === "auto" || overflowY === "scroll" || overflowY === "overlay") {
				this.#scrollContainer = element;
				this.#scrollContainerSource = fileContainer;
				return element;
			}
			element = element.parentElement;
		}
		this.#scrollContainer = void 0;
		this.#scrollContainerSource = fileContainer;
	}
	#refreshViewportRectsIfNeeded() {
		if (!this.#viewportRectsDirty) return;
		this.#ensureViewportRectListeners();
		const codeElement = this.#codeElement;
		this.#cachedCodeRect = codeElement?.getBoundingClientRect();
		this.#cachedCodeScrollLeft = codeElement?.scrollLeft ?? 0;
		this.#cachedCodeScrollTop = codeElement?.scrollTop ?? 0;
		this.#cachedCodeClientWidth = codeElement?.clientWidth ?? 0;
		this.#cachedScrollContainerRect = this.#getScrollContainer()?.getBoundingClientRect();
		this.#viewportRectsDirty = false;
	}
	#getCodeRect() {
		this.#refreshViewportRectsIfNeeded();
		return this.#cachedCodeRect;
	}
	#getScrollContainerRect() {
		this.#refreshViewportRectsIfNeeded();
		return this.#cachedScrollContainerRect;
	}
	#ensureViewportRectListeners() {
		if (this.#viewportRectListenersDisposes !== void 0) return;
		let repositionRafId;
		const markDirty = () => {
			this.#viewportRectsDirty = true;
			if (!this.#hasActivePopover() || repositionRafId !== void 0) return;
			repositionRafId = requestAnimationFrame(() => {
				repositionRafId = void 0;
				this.#updateActivePopover();
			});
		};
		const scroller = this.#getScrollContainer();
		const codeElement = this.#codeElement;
		this.#viewportRectListenersDisposes = [
			scroller !== void 0 ? addEventListener(scroller, "scroll", markDirty, { passive: true }) : addEventListener(window, "scroll", markDirty, { passive: true }),
			...codeElement !== void 0 ? [addEventListener(codeElement, "scroll", markDirty, { passive: true })] : [],
			addEventListener(window, "resize", markDirty, { passive: true }),
			() => {
				if (repositionRafId !== void 0) {
					cancelAnimationFrame(repositionRafId);
					repositionRafId = void 0;
				}
			}
		];
	}
};
function setPopoverPositionStyles(popover, { gutterWidth, placeAbove, viewport, x, y }) {
	popover.style.setProperty("--gutter-width", gutterWidth + "px");
	popover.style.setProperty("--popover-x", x + "px");
	popover.style.setProperty("--popover-y", y + "px");
	popover.style.setProperty("--popover-y-shift", placeAbove ? "-100%" : "0px");
	if (viewport === void 0) {
		popover.style.removeProperty("--popover-viewport-left");
		popover.style.removeProperty("--popover-viewport-right");
		popover.style.removeProperty("--popover-viewport-top");
		popover.style.removeProperty("--popover-viewport-bottom");
		return;
	}
	popover.style.setProperty("--popover-viewport-left", viewport.left + "px");
	popover.style.setProperty("--popover-viewport-right", viewport.right + "px");
	popover.style.setProperty("--popover-viewport-top", viewport.top + "px");
	popover.style.setProperty("--popover-viewport-bottom", viewport.bottom + "px");
}
//#endregion
export { POPOVER_BOUNDARY_LINES, POPOVER_FLIP_HYSTERESIS_PX, PopoverManager, setPopoverPositionStyles };

//# sourceMappingURL=popover.js.map