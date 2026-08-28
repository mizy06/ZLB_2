import { h } from "./utils.js";
import { setPopoverPositionStyles } from "./popover.js";
//#region src/editor/selectionAction.ts
/**
* Selection action widget.
*/
var SelectionActionWidget = class {
	#root;
	#height;
	#resizeObserver;
	constructor(selectionActionElement, overlayElement, onHeightChange) {
		this.#root = h("div", {
			dataset: {
				editorWidget: "",
				selectionActionPopover: ""
			},
			contentEditable: "false",
			children: [selectionActionElement]
		}, overlayElement);
		this.#height = this.#root.offsetHeight;
		this.#resizeObserver = new ResizeObserver(() => {
			const height = this.#root.offsetHeight;
			if (height !== this.#height) {
				this.#height = height;
				onHeightChange();
			}
		});
		this.#resizeObserver.observe(this.#root);
	}
	/**
	* Repositions the selection action widget.
	* @param left - The left position of the selection action widget.
	* @param top - The top position of the selection action widget.
	* @param gutterWidth - The width of the gutter.
	* @param placeAbove - Whether the selection action widget should be placed above the anchor.
	* @param visible - Whether the selection intersects the viewport.
	*/
	reposition(left, top, gutterWidth, placeAbove, visible, viewport) {
		this.#root.style.visibility = visible ? "" : "hidden";
		setPopoverPositionStyles(this.#root, {
			gutterWidth,
			placeAbove,
			viewport,
			x: left,
			y: top
		});
	}
	/**
	* Gets the height of the selection action widget.
	* @returns The height of the selection action widget.
	*/
	get height() {
		return this.#height;
	}
	/**
	* Cleans up the selection action widget.
	*/
	cleanup() {
		this.#resizeObserver.disconnect();
		this.#root.remove();
	}
};
//#endregion
export { SelectionActionWidget };

//# sourceMappingURL=selectionAction.js.map