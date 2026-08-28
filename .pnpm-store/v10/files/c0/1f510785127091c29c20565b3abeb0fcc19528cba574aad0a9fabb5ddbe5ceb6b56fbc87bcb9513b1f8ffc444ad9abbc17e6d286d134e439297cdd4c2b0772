import "../constants.js";
import { areObjectsEqual } from "../utils/areObjectsEqual.js";
import { areOptionsEqual } from "../utils/areOptionsEqual.js";
import { parseDiffFromFile } from "../utils/parseDiffFromFile.js";
import { computeVirtualFileMetrics, getVirtualFileHeaderRegion, getVirtualFilePaddingBottom } from "../utils/computeVirtualFileMetrics.js";
import { getExpandedRegion, getLeadingHunkSeparatorLayout, getTrailingExpandedRegion, getTrailingHunkSeparatorLayout, isAdditionLineRenderable } from "../utils/virtualDiffLayout.js";
import { areFilesEqual } from "../utils/areFilesEqual.js";
import { FILE_ANNOTATION_DOM_KEY, includesFileAnnotations, shouldRenderFileAnnotations } from "../utils/includesFileAnnotations.js";
import { areDiffTargetsEqual } from "../utils/areDiffTargetsEqual.js";
import { awaitWithTimeout } from "../utils/awaitWithTimeout.js";
import { computeEstimatedDiffHeights } from "../utils/computeEstimatedDiffHeights.js";
import { getDiffFileInput } from "../utils/getDiffFileInput.js";
import { hydratePartialDiff } from "../utils/hydratePartialDiff.js";
import { iterateOverDiff } from "../utils/iterateOverDiff.js";
import { FileDiff } from "./FileDiff.js";
//#region src/components/VirtualizedFileDiff.ts
const VIRTUALIZED_FILE_DIFF_LAYOUT_CHECKPOINT_INTERVAL = 3e3;
let instanceId = -1;
var VirtualizedFileDiff = class extends FileDiff {
	__id = `little-virtualized-file-diff:${++instanceId}`;
	top;
	height = 0;
	metrics;
	cache = {
		heightDeltas: /* @__PURE__ */ new Map(),
		measuredHeightDeltaTotal: 0,
		estimatedSplitHeight: void 0,
		estimatedUnifiedHeight: void 0,
		checkpoints: [],
		totalLines: 0,
		fileAnnotationHeight: 0
	};
	isVisible = false;
	isSetup = false;
	virtualizer;
	layoutDirty = true;
	forceRenderOverride;
	currentCollapsed;
	currentExpandUnchanged;
	pendingHydratedDiff;
	pendingExpansions;
	constructor(options, virtualizer, metrics, workerManager, isContainerManaged = false) {
		super(options, workerManager, isContainerManaged);
		this.virtualizer = virtualizer;
		this.metrics = computeVirtualFileMetrics(metrics);
	}
	setMetrics(metrics, force = false) {
		const nextMetrics = computeVirtualFileMetrics(metrics);
		if (!force && areObjectsEqual(this.metrics, nextMetrics)) return;
		this.metrics = nextMetrics;
		this.resetLayoutCache({ includeEstimatedHeights: true });
	}
	setLineAnnotations(lineAnnotations) {
		if (this.syncLineAnnotations(lineAnnotations)) this.resetLayoutCache({ includeEstimatedHeights: false });
	}
	syncLineAnnotations(lineAnnotations) {
		if (lineAnnotations == null || lineAnnotations === this.lineAnnotations || lineAnnotations.length === 0 && this.lineAnnotations.length === 0) return false;
		super.setLineAnnotations(lineAnnotations);
		return true;
	}
	setFileAnnotationHeight(nextHeight) {
		const previousHeight = this.cache.fileAnnotationHeight;
		if (nextHeight === previousHeight) return false;
		this.cache.fileAnnotationHeight = nextHeight;
		this.cache.measuredHeightDeltaTotal += nextHeight - previousHeight;
		return true;
	}
	hasFileAnnotations(fileDiff = this.fileDiff) {
		if (fileDiff == null || !includesFileAnnotations(this.lineAnnotations)) return false;
		return this.lineAnnotations.some((annotation) => {
			if (annotation.lineNumber !== 0) return false;
			if (fileDiff.type === "new") return annotation.side === "additions";
			if (fileDiff.type === "deleted") return annotation.side === "deletions";
			return true;
		});
	}
	getLineHeight(lineIndex, hasMetadataLine = false) {
		return this.getEstimatedLineHeight(hasMetadataLine) + (this.cache.heightDeltas.get(lineIndex) ?? 0);
	}
	getEstimatedLineHeight(hasMetadataLine = false) {
		const multiplier = hasMetadataLine ? 2 : 1;
		return this.metrics.lineHeight * multiplier;
	}
	setOptions(options) {
		if (this.isAdvancedMode()) throw new Error("VirtualizedFileDiff.setOptions cannot be used inside CodeView. Update CodeView options instead.");
		if (options == null) return;
		const { options: previousOptions } = this;
		const optionsChanged = !areOptionsEqual(previousOptions, options);
		const layoutChanged = optionsChanged && hasDiffLayoutOptionChanged(previousOptions, options);
		super.setOptions(options);
		if (layoutChanged) this.resetLayoutCache({
			forceSimpleRecompute: true,
			includeEstimatedHeights: hasDiffEstimateOptionChanged(previousOptions, options)
		});
		if (optionsChanged) this.forceRenderOverride = true;
		if (optionsChanged && this.isSimpleMode()) this.virtualizer.instanceChanged(this, layoutChanged);
	}
	setThemeType(themeType) {
		if (this.isAdvancedMode()) throw new Error("VirtualizedFileDiff.setThemeType cannot be used inside CodeView. Update CodeView options instead.");
		super.setThemeType(themeType);
	}
	resetLayoutCache({ forceSimpleRecompute = false, includeEstimatedHeights = false, resetRenderRange = true } = {}) {
		this.layoutDirty = true;
		this.cache.fileAnnotationHeight = 0;
		if (this.cache.heightDeltas.size > 0) this.cache.heightDeltas.clear();
		if (this.cache.measuredHeightDeltaTotal !== 0) this.cache.measuredHeightDeltaTotal = 0;
		this.invalidateDerivedLayoutCache(includeEstimatedHeights, resetRenderRange);
		if (forceSimpleRecompute && this.isSimpleMode()) this.computeApproximateSize();
	}
	invalidateDerivedLayoutCache(includeEstimatedHeights, resetRenderRange = true) {
		this.layoutDirty = true;
		if (this.cache.checkpoints.length > 0) this.cache.checkpoints.length = 0;
		if (this.cache.totalLines !== 0) this.cache.totalLines = 0;
		if (includeEstimatedHeights) {
			this.cache.estimatedSplitHeight = void 0;
			this.cache.estimatedUnifiedHeight = void 0;
		}
		if (this.renderRange != null && resetRenderRange) this.renderRange = void 0;
	}
	reconcileHeights() {
		let hasHeightChange = false;
		const { overflow = "scroll" } = this.options;
		if (this.fileContainer == null || this.fileDiff == null) {
			if (this.height !== 0) hasHeightChange = true;
			this.height = 0;
			return hasHeightChange;
		}
		this.top = this.getVirtualizedTop();
		if (overflow === "scroll" && this.lineAnnotations.length === 0 && !this.isResizeDebuggingEnabled()) return hasHeightChange;
		const diffStyle = this.getDiffStyle();
		const codeGroups = diffStyle === "split" ? [this.codeDeletions, this.codeAdditions] : [this.codeUnified];
		const hasFileAnnotations = this.hasFileAnnotations(this.fileDiff);
		if (this.renderRange != null && hasFileAnnotations && shouldRenderFileAnnotations(this.renderRange)) {
			const nextFileAnnotationHeight = measureFileAnnotationHeight(codeGroups) ?? 0;
			if (this.setFileAnnotationHeight(nextFileAnnotationHeight)) hasHeightChange = true;
		} else if (!hasFileAnnotations && this.setFileAnnotationHeight(0)) hasHeightChange = true;
		for (const codeGroup of codeGroups) {
			if (codeGroup == null) continue;
			const content = codeGroup.children[1];
			if (!(content instanceof HTMLElement)) continue;
			for (const line of content.children) {
				if (!(line instanceof HTMLElement)) continue;
				const lineIndexAttr = line.dataset.lineIndex;
				if (lineIndexAttr == null) continue;
				const lineIndex = parseLineIndex(lineIndexAttr, diffStyle);
				let measuredHeight = line.getBoundingClientRect().height;
				let hasMetadata = false;
				if (line.nextElementSibling instanceof HTMLElement && ("lineAnnotation" in line.nextElementSibling.dataset || "noNewline" in line.nextElementSibling.dataset)) {
					if ("noNewline" in line.nextElementSibling.dataset) hasMetadata = true;
					measuredHeight += line.nextElementSibling.getBoundingClientRect().height;
				}
				const estimatedHeight = this.getEstimatedLineHeight(hasMetadata);
				const previousDelta = this.cache.heightDeltas.get(lineIndex) ?? 0;
				const nextDelta = measuredHeight - estimatedHeight;
				if (nextDelta === previousDelta) continue;
				hasHeightChange = true;
				this.cache.measuredHeightDeltaTotal += nextDelta - previousDelta;
				if (nextDelta === 0) this.cache.heightDeltas.delete(lineIndex);
				else this.cache.heightDeltas.set(lineIndex, nextDelta);
			}
		}
		if (hasHeightChange || this.isResizeDebuggingEnabled()) this.computeApproximateSize(true);
		return hasHeightChange;
	}
	onRender = (dirty) => {
		if (this.fileContainer == null) return false;
		if (dirty) this.top = this.getVirtualizedTop();
		return this.render();
	};
	flushManagers() {
		super.flushManagers();
		if (this.lineStateRefreshPending) this.flushDeferredLineState();
	}
	prepareCodeViewItem(fileDiff, top, reset, lineAnnotations) {
		const targetChanged = !areDiffTargetsEqual(this.fileDiff, fileDiff);
		const annotationsChanged = this.syncLineAnnotations(lineAnnotations);
		let shouldResetLayoutCache = reset?.resetDiffLayoutCache === true || targetChanged || annotationsChanged;
		let includeEstimatedHeights = targetChanged || reset?.resetDiffLayoutCache === true && reset.includeEstimatedDiffHeights;
		if (reset?.metrics != null) {
			this.metrics = computeVirtualFileMetrics(reset.metrics);
			shouldResetLayoutCache = true;
			includeEstimatedHeights = true;
		}
		const { collapsed = false, expandUnchanged = false } = this.options;
		if (this.currentCollapsed !== collapsed) {
			this.currentCollapsed = collapsed;
			shouldResetLayoutCache = true;
		}
		if (this.currentExpandUnchanged !== expandUnchanged) {
			this.currentExpandUnchanged = expandUnchanged;
			shouldResetLayoutCache = true;
			includeEstimatedHeights = true;
		}
		if (shouldResetLayoutCache) this.resetLayoutCache({ includeEstimatedHeights });
		this.fileDiff = fileDiff;
		this.top = top;
		this.computeApproximateSize();
		return this.height;
	}
	getLinePosition(lineNumber, side = "additions") {
		if (this.fileDiff == null || lineNumber < 1) return;
		const targetLineIndexes = this.getLineIndex(lineNumber, side);
		if (targetLineIndexes == null) return;
		const { disableFileHeader = false, expandUnchanged = false, collapsed = false, collapsedContextThreshold = 1 } = this.options;
		const diffStyle = this.getDiffStyle();
		const hunkSeparators = this.getHunkSeparatorType();
		const targetLineIndex = diffStyle === "split" ? targetLineIndexes[1] : targetLineIndexes[0];
		this.approximateLayoutCheckpoints();
		const headerRegion = getVirtualFileHeaderRegion(this.metrics, disableFileHeader);
		const checkpoint = this.getLayoutCheckpointBeforeLineIndex(targetLineIndex);
		let top = checkpoint?.top ?? headerRegion + this.cache.fileAnnotationHeight;
		if (collapsed) return {
			top: headerRegion,
			height: 0
		};
		let position;
		iterateOverDiff({
			diff: this.fileDiff,
			diffStyle,
			startingLine: checkpoint?.renderedLineIndex ?? 0,
			expandedHunks: expandUnchanged ? true : this.hunksRenderer.getExpandedHunksMap(),
			collapsedContextThreshold,
			callback: ({ hunkIndex, hunk, collapsedBefore, collapsedAfter, deletionLine, additionLine }) => {
				const lineIndex = diffStyle === "split" ? additionLine?.splitLineIndex ?? deletionLine?.splitLineIndex : additionLine?.unifiedLineIndex ?? deletionLine?.unifiedLineIndex;
				if (lineIndex == null) throw new Error("VirtualizedFileDiff.getLinePosition: missing line index data");
				if (collapsedBefore > 0) {
					const separator = getLeadingHunkSeparatorLayout({
						type: hunkSeparators,
						metrics: this.metrics,
						hunkIndex,
						hunkSpecs: hunk?.hunkSpecs
					});
					if (separator != null) {
						top += separator.gapBefore;
						if (targetLineIndex >= lineIndex - collapsedBefore && targetLineIndex < lineIndex) {
							position = {
								top,
								height: separator.height
							};
							return true;
						}
						top += separator.height + separator.gapAfter;
					}
				}
				const lineHeight = this.getLineHeight(lineIndex, (additionLine?.noEOFCR ?? false) || (deletionLine?.noEOFCR ?? false));
				if (lineIndex === targetLineIndex) {
					position = {
						top,
						height: lineHeight
					};
					return true;
				}
				top += lineHeight;
				if (collapsedAfter > 0) {
					const separator = getTrailingHunkSeparatorLayout({
						type: hunkSeparators,
						metrics: this.metrics
					});
					if (separator != null) {
						if (targetLineIndex > lineIndex && targetLineIndex <= lineIndex + collapsedAfter) {
							position = {
								top: top + separator.gapBefore,
								height: separator.height
							};
							return true;
						}
						top += separator.totalHeight;
					}
				}
				return false;
			}
		});
		return position;
	}
	getEditorViewport() {
		return this.virtualizer.type === "simple" ? this.virtualizer.getRoot() : this.virtualizer.getContainerElement();
	}
	getNumericScrollAnchor(localViewportTop) {
		if (this.fileDiff == null) return;
		const { disableFileHeader = false, expandUnchanged = false, collapsed = false, collapsedContextThreshold = 1 } = this.options;
		if (collapsed) return;
		const diffStyle = this.getDiffStyle();
		const hunkSeparators = this.getHunkSeparatorType();
		this.approximateLayoutCheckpoints();
		const checkpoint = this.getLayoutCheckpointBeforeTop(localViewportTop);
		let top = checkpoint?.top ?? getVirtualFileHeaderRegion(this.metrics, disableFileHeader) + this.cache.fileAnnotationHeight;
		let anchor;
		iterateOverDiff({
			diff: this.fileDiff,
			diffStyle,
			startingLine: checkpoint?.renderedLineIndex ?? 0,
			expandedHunks: expandUnchanged ? true : this.hunksRenderer.getExpandedHunksMap(),
			collapsedContextThreshold,
			callback: ({ hunkIndex, hunk, collapsedBefore, collapsedAfter, deletionLine, additionLine }) => {
				const lineIndex = diffStyle === "split" ? additionLine?.splitLineIndex ?? deletionLine?.splitLineIndex : additionLine?.unifiedLineIndex ?? deletionLine?.unifiedLineIndex;
				if (lineIndex == null) throw new Error("VirtualizedFileDiff.getNumericScrollAnchor: missing line index data");
				if (collapsedBefore > 0) {
					const separator = getLeadingHunkSeparatorLayout({
						type: hunkSeparators,
						metrics: this.metrics,
						hunkIndex,
						hunkSpecs: hunk?.hunkSpecs
					});
					if (separator != null) top += separator.totalHeight;
				}
				if (top >= localViewportTop) {
					if (deletionLine != null) anchor = {
						lineNumber: deletionLine.lineNumber,
						side: "deletions",
						top
					};
					else if (additionLine != null) anchor = {
						lineNumber: additionLine.lineNumber,
						side: "additions",
						top
					};
					if (anchor != null) return true;
				}
				const lineHeight = this.getLineHeight(lineIndex, (additionLine?.noEOFCR ?? false) || (deletionLine?.noEOFCR ?? false));
				top += lineHeight;
				if (collapsedAfter > 0) {
					const separator = getTrailingHunkSeparatorLayout({
						type: hunkSeparators,
						metrics: this.metrics
					});
					if (separator != null) top += separator.totalHeight;
				}
				return false;
			}
		});
		return anchor;
	}
	getVirtualizedHeight() {
		return this.height;
	}
	getAdvancedStickySpecs(windowSpecs) {
		if (this.top == null || this.fileDiff == null) return;
		if (this.options.collapsed === true) return {
			topOffset: this.top,
			height: this.height
		};
		const renderRange = windowSpecs != null ? this.computeRenderRangeFromWindow(this.fileDiff, this.top, windowSpecs) : this.renderRange;
		if (renderRange == null) return;
		const { bufferBefore, bufferAfter, totalLines } = renderRange;
		let headerOnlyOffset = 0;
		if (totalLines === 0) {
			const activeWindow = windowSpecs ?? this.virtualizer.getWindowSpecs();
			if (this.top < activeWindow.top) headerOnlyOffset = bufferAfter;
		}
		return {
			topOffset: this.top + bufferBefore + headerOnlyOffset,
			height: this.height - (bufferBefore + bufferAfter)
		};
	}
	cleanUp(recycle = false) {
		if (this.fileContainer != null && this.isSimpleMode()) this.getSimpleVirtualizer()?.disconnect(this.fileContainer);
		if (!recycle) {
			this.resetLayoutCache({ includeEstimatedHeights: true });
			this.pendingExpansions = void 0;
			this.pendingHydratedDiff = void 0;
		}
		this.isSetup = false;
		super.cleanUp(recycle);
	}
	expandHunk = (hunkIndex, direction, expansionLineCountOverride) => {
		if (this.fileDiff == null) return;
		if (this.isAdvancedMode()) {
			this.pendingExpansions ??= [];
			this.pendingExpansions.push({
				hunkIndex,
				direction,
				expansionLineCountOverride
			});
		} else {
			this.hunksRenderer.expandHunk(hunkIndex, direction, expansionLineCountOverride);
			this.resetLayoutCache({ includeEstimatedHeights: true });
			this.computeApproximateSize();
		}
		this.loadFilesIfNecessary();
		this.forceRenderOverride = true;
		this.virtualizer.instanceChanged(this, true);
	};
	async handleFilesLoaded(expectedDiff, files) {
		if (this.fileDiff !== expectedDiff || !expectedDiff.isPartial) return;
		if (this.isAdvancedMode()) {
			const nextDiff = hydratePartialDiff("clone", expectedDiff, files);
			await awaitWithTimeout(() => this.primeHighlightCache(nextDiff));
			if (!this.enabled || this.fileDiff !== expectedDiff) return;
			this.pendingHydratedDiff = {
				expectedDiff,
				nextDiff,
				files
			};
		} else {
			hydratePartialDiff("merge", expectedDiff, files);
			this.setHydratedState(files);
			await awaitWithTimeout(() => this.primeHighlightCache(expectedDiff));
			if (!this.enabled || this.fileDiff !== expectedDiff) return;
			this.resetLayoutCache({ includeEstimatedHeights: true });
			this.computeApproximateSize();
		}
		this.forceRenderOverride = true;
		this.virtualizer.instanceChanged(this, true);
	}
	consumeCodeViewLayoutChanges(expectedFileDiff) {
		let hasLayoutChange = false;
		let nextDiff;
		const { pendingExpansions, pendingHydratedDiff } = this;
		if (pendingExpansions != null) {
			this.pendingExpansions = void 0;
			for (const pendingExpansion of pendingExpansions) {
				this.hunksRenderer.expandHunk(pendingExpansion.hunkIndex, pendingExpansion.direction, pendingExpansion.expansionLineCountOverride);
				hasLayoutChange = true;
			}
		}
		if (pendingHydratedDiff != null) {
			this.pendingHydratedDiff = void 0;
			if (pendingHydratedDiff.expectedDiff === expectedFileDiff) {
				this.setHydratedState(pendingHydratedDiff.files);
				nextDiff = pendingHydratedDiff.nextDiff;
			}
		}
		if (nextDiff != null) {
			this.forceRenderOverride = true;
			this.resetLayoutCache({ includeEstimatedHeights: true });
		} else if (hasLayoutChange) {
			this.forceRenderOverride = true;
			this.invalidateDerivedLayoutCache(true);
		}
		return nextDiff;
	}
	loadFilesIfNecessary() {
		if (this.pendingHydratedDiff != null) {
			if (this.pendingHydratedDiff.expectedDiff === this.fileDiff) return;
			this.pendingHydratedDiff = void 0;
		}
		super.loadFilesIfNecessary();
	}
	isLineRenderable(lineNumber) {
		if (super.isLineRenderable(lineNumber)) return true;
		const { pendingExpansions } = this;
		const fileDiff = this.fileDiffCache;
		if (pendingExpansions == null || pendingExpansions.length === 0 || fileDiff == null) return false;
		const { expansionLineCount = 100, collapsedContextThreshold = 1 } = this.options;
		const staged = new Map(this.hunksRenderer.getExpandedHunksMap());
		for (const expansion of pendingExpansions) {
			const region = { ...staged.get(expansion.hunkIndex) ?? {
				fromStart: 0,
				fromEnd: 0
			} };
			const count = expansion.expansionLineCountOverride ?? expansionLineCount;
			if (expansion.direction === "up" || expansion.direction === "both") region.fromStart += count;
			if (expansion.direction === "down" || expansion.direction === "both") region.fromEnd += count;
			staged.set(expansion.hunkIndex, region);
		}
		return isAdditionLineRenderable({
			fileDiff,
			lineNumber,
			expandedHunks: staged,
			collapsedContextThreshold
		});
	}
	/**
	* Invalidate layout after an edit session changed the rendered row set
	* without a line-count change (a mid-session region change or the exit
	* recompute): estimated heights bake the hunk shapes in, and nothing else
	* invalidates them now that editing does not flip expandUnchanged. Public
	* so CodeView can run it when reaping a session whose instance was already
	* released.
	*/
	invalidateEditSessionLayout() {
		this.getSimpleVirtualizer()?.markDOMDirty();
		this.resetLayoutCache({
			forceSimpleRecompute: this.isSimpleMode(),
			includeEstimatedHeights: true,
			resetRenderRange: false
		});
		if (!this.isSimpleMode()) this.computeApproximateSize(true);
		this.getSimpleVirtualizer()?.requestHeightReconcile(this);
	}
	escalateEditSessionRender() {
		this.invalidateEditSessionLayout();
		if (!this.enabled || this.fileDiff == null) return;
		this.forceRenderOverride = true;
		this.virtualizer.instanceChanged(this, true);
	}
	shouldSelfHealEditSession() {
		return !this.isAdvancedMode() && super.shouldSelfHealEditSession();
	}
	setVisibility(visible) {
		if (this.isAdvancedMode() || this.fileContainer == null) return;
		this.renderRange = void 0;
		if (visible && !this.isVisible) {
			this.top = this.getVirtualizedTop();
			this.isVisible = true;
		} else if (!visible && this.isVisible) {
			this.isVisible = false;
			this.rerender();
		}
	}
	rerender() {
		if (!this.enabled || this.fileDiff == null && this.additionFile == null && this.deletionFile == null) return;
		this.forceRenderOverride = true;
		this.virtualizer.instanceChanged(this, false);
	}
	applyDocumentChange(textDocument, newLineAnnotations, shouldUpdateBuffer = false) {
		const { renderRange: previousRenderRange } = this;
		this.getAdvancedVirtualizer()?.capturePendingLayoutAnchor();
		super.applyDocumentChange(textDocument, newLineAnnotations);
		this.getSimpleVirtualizer()?.markDOMDirty();
		this.resetLayoutCache({
			forceSimpleRecompute: this.isSimpleMode(),
			includeEstimatedHeights: true,
			resetRenderRange: false
		});
		if (!this.isSimpleMode()) this.computeApproximateSize(true);
		else if (shouldUpdateBuffer && previousRenderRange !== void 0 && this.fileDiff !== void 0) {
			const windowSpecs = this.virtualizer.getWindowSpecs();
			const renderRange = this.computeRenderRangeFromWindow(this.fileDiff, this.top ?? 0, windowSpecs);
			if (renderRange.bufferAfter !== previousRenderRange.bufferAfter) this.updateBuffers(renderRange);
		}
		this.forceRenderOverride = true;
		this.virtualizer.instanceChanged(this, true);
	}
	computeApproximateSize(force = false, fileDiff = this.fileDiff) {
		const shouldValidateSize = this.isResizeDebuggingEnabled();
		if (!force && !this.layoutDirty && !shouldValidateSize) return;
		const isFirstCompute = this.height === 0;
		this.height = 0;
		this.cache.checkpoints = [];
		this.cache.totalLines = 0;
		if (fileDiff == null) {
			this.layoutDirty = false;
			return;
		}
		const { disableFileHeader = false, collapsed = false } = this.options;
		const headerRegion = getVirtualFileHeaderRegion(this.metrics, disableFileHeader);
		this.height += headerRegion;
		if (collapsed) {
			this.layoutDirty = false;
			return;
		}
		this.height = this.getActiveEstimatedHeight(fileDiff) + this.cache.measuredHeightDeltaTotal;
		if (shouldValidateSize && !isFirstCompute) this.validateComputedHeight(fileDiff);
		this.layoutDirty = false;
	}
	getActiveEstimatedHeight(fileDiff = this.fileDiff) {
		this.ensureEstimatedDiffHeights(fileDiff);
		const estimatedHeight = this.getDiffStyle() === "split" ? this.cache.estimatedSplitHeight : this.cache.estimatedUnifiedHeight;
		if (estimatedHeight == null) throw new Error("VirtualizedFileDiff.getActiveEstimatedHeight: missing estimated height");
		return estimatedHeight;
	}
	ensureEstimatedDiffHeights(fileDiff = this.fileDiff) {
		if (fileDiff == null) {
			this.cache.estimatedSplitHeight = void 0;
			this.cache.estimatedUnifiedHeight = void 0;
			return;
		}
		if (this.cache.estimatedSplitHeight != null && this.cache.estimatedUnifiedHeight != null) return;
		const { disableFileHeader = false, expandUnchanged = false, collapsedContextThreshold = 1 } = this.options;
		const { splitHeight, unifiedHeight } = computeEstimatedDiffHeights({
			fileDiff,
			metrics: this.metrics,
			disableFileHeader,
			hunkSeparators: this.getHunkSeparatorType(),
			expandUnchanged,
			expandedHunks: this.hunksRenderer.getExpandedHunksMap(),
			collapsedContextThreshold,
			canHydratePartialDiff: canHydrateCollapsedContext(fileDiff, this.options.loadDiffFiles != null)
		});
		this.cache.estimatedSplitHeight = splitHeight;
		this.cache.estimatedUnifiedHeight = unifiedHeight;
	}
	validateComputedHeight(fileDiff = this.fileDiff) {
		if (this.fileContainer == null || fileDiff == null) return;
		const rect = this.fileContainer.getBoundingClientRect();
		if (rect.height !== this.height) console.log("VirtualizedFileDiff.computeApproximateSize: computed height doesnt match", {
			name: fileDiff.name,
			elementHeight: rect.height,
			computedHeight: this.height
		});
		else console.log("VirtualizedFileDiff.computeApproximateSize: computed height IS CORRECT");
	}
	render({ fileContainer, fileDiff, forceRender = false, lineAnnotations, ...fileInputProps } = {}) {
		const fileInput = getDiffFileInput(fileInputProps, "VirtualizedFileDiff.render");
		const hasFileInput = fileInput != null;
		const oldFile = fileInput?.oldFile;
		const newFile = fileInput?.newFile;
		const filesDidChange = hasFileInput && (!areOptionalFilesEqual(oldFile, this.deletionFile) || !areOptionalFilesEqual(newFile, this.additionFile));
		let nextFileDiff = fileDiff ?? this.fileDiff;
		if (fileDiff == null && hasFileInput && (filesDidChange || this.fileDiff == null)) nextFileDiff = parseDiffFromFile(fileInput.oldFile, fileInput.newFile, this.options.parseDiffOptions);
		const { forceRenderOverride, isSetup } = this;
		this.forceRenderOverride = void 0;
		const annotationsChanged = this.syncLineAnnotations(lineAnnotations);
		if (annotationsChanged) this.resetLayoutCache({ includeEstimatedHeights: false });
		const diffInputChanged = fileDiff != null && fileDiff !== this.fileDiff;
		const targetChanged = nextFileDiff != null && !areDiffTargetsEqual(this.fileDiff, nextFileDiff);
		const dataChanged = diffInputChanged || filesDidChange;
		if (targetChanged) this.resetLayoutCache({ includeEstimatedHeights: true });
		fileContainer = this.getOrCreateFileContainer(fileContainer);
		if (nextFileDiff == null) {
			console.error("VirtualizedFileDiff.render: attempting to virtually render when we dont have the correct data");
			return false;
		}
		if (!isSetup) {
			this.computeApproximateSize(false, nextFileDiff);
			const virtualizer = this.getSimpleVirtualizer();
			this.top ??= this.getVirtualizedTop();
			if (this.isAdvancedMode()) this.isVisible = true;
			else {
				if (virtualizer == null) throw new Error("VirtualizedFileDiff.render: simple virtualizer is not available");
				virtualizer.connect(fileContainer, this);
				this.isVisible = virtualizer.isInstanceVisible(this.top ?? 0, this.height);
			}
			this.isSetup = true;
		} else {
			this.top ??= this.getVirtualizedTop();
			if (targetChanged) {
				this.getSimpleVirtualizer()?.markDOMDirty();
				this.computeApproximateSize(false, nextFileDiff);
			}
		}
		if (!this.isVisible && this.isSimpleMode() && (!dataChanged || !isSetup)) {
			this.fileDiff = nextFileDiff;
			if (fileInput != null) {
				this.deletionFile = oldFile;
				this.additionFile = newFile;
			}
			if (targetChanged) this.cachedHeaderHTML = void 0;
			return this.renderPlaceholder(this.height);
		}
		const windowSpecs = this.virtualizer.getWindowSpecs();
		const fileTop = this.top ?? 0;
		const renderRange = this.computeRenderRangeFromWindow(nextFileDiff, fileTop, windowSpecs);
		const rendered = super.render({
			fileDiff: nextFileDiff,
			fileContainer,
			renderRange,
			lineAnnotations,
			forceRender: (forceRenderOverride ?? forceRender) || annotationsChanged || targetChanged,
			...fileInput,
			...fileInputProps
		});
		if (this.isSimpleMode() && rendered) this.getSimpleVirtualizer()?.requestHeightReconcile(this);
		return rendered;
	}
	syncVirtualizedTop() {
		this.top = this.getVirtualizedTop();
	}
	shouldDisableVirtualizationBuffers() {
		return this.isAdvancedMode() || super.shouldDisableVirtualizationBuffers();
	}
	shouldGuardRebuildScroll() {
		return false;
	}
	isSimpleMode() {
		return this.virtualizer.type === "simple";
	}
	isAdvancedMode() {
		return this.virtualizer.type === "advanced";
	}
	getVirtualizedTop() {
		if (this.virtualizer.type === "advanced") return this.virtualizer.getLocalTopForInstance(this);
		return this.fileContainer != null ? this.virtualizer.getOffsetInScrollContainer(this.fileContainer) : 0;
	}
	getSimpleVirtualizer() {
		return this.virtualizer.type === "simple" ? this.virtualizer : void 0;
	}
	getAdvancedVirtualizer() {
		return this.virtualizer.type === "advanced" ? this.virtualizer : void 0;
	}
	isResizeDebuggingEnabled() {
		return this.getSimpleVirtualizer()?.config.resizeDebugging ?? false;
	}
	getDiffStyle() {
		return this.options.diffStyle ?? "split";
	}
	getHunkSeparatorType() {
		return getOptionHunkSeparatorType(this.options.hunkSeparators);
	}
	approximateLayoutCheckpoints(fileDiff = this.fileDiff) {
		if (!this.layoutDirty && this.cache.checkpoints.length > 0 || fileDiff == null || fileDiff.hunks.length === 0 || this.options.collapsed === true) return;
		const { disableFileHeader = false, expandUnchanged = false, collapsedContextThreshold = 1 } = this.options;
		const finalHunkIndex = fileDiff.hunks.length - 1;
		const canHydratePartialDiff = canHydrateCollapsedContext(fileDiff, this.options.loadDiffFiles != null);
		const diffStyle = this.getDiffStyle();
		const hunkSeparators = this.getHunkSeparatorType();
		const expandedHunks = expandUnchanged ? true : this.hunksRenderer.getExpandedHunksMap();
		const heightDeltaPrefix = createHeightDeltaPrefix(this.cache.heightDeltas);
		let top = getVirtualFileHeaderRegion(this.metrics, disableFileHeader) + this.cache.fileAnnotationHeight;
		let renderedLineIndex = 0;
		const processRows = ({ rowCount, startLineIndex, preSeparatorHeight = 0, postSeparatorHeight = 0, metadataOffsets = [] }) => {
			if (rowCount <= 0) return;
			const blockStart = renderedLineIndex;
			const blockEnd = renderedLineIndex + rowCount;
			let nextCheckpoint = getNextCheckpointIndex(blockStart);
			while (nextCheckpoint < blockEnd) {
				const offset = nextCheckpoint - blockStart;
				const checkpointTop = top + (offset > 0 ? preSeparatorHeight : 0) + offset * this.metrics.lineHeight + countMetadataOffsetsBefore(metadataOffsets, offset) * this.metrics.lineHeight + sumHeightDeltas(heightDeltaPrefix, startLineIndex, startLineIndex + offset);
				this.cache.checkpoints.push({
					renderedLineIndex: nextCheckpoint,
					lineIndex: startLineIndex + offset,
					top: checkpointTop
				});
				nextCheckpoint += VIRTUALIZED_FILE_DIFF_LAYOUT_CHECKPOINT_INTERVAL;
			}
			top += preSeparatorHeight + rowCount * this.metrics.lineHeight + metadataOffsets.length * this.metrics.lineHeight + sumHeightDeltas(heightDeltaPrefix, startLineIndex, startLineIndex + rowCount) + postSeparatorHeight;
			renderedLineIndex = blockEnd;
		};
		for (let hunkIndex = 0; hunkIndex < fileDiff.hunks.length; hunkIndex++) {
			const hunk = fileDiff.hunks[hunkIndex];
			if (hunk == null) throw new Error("VirtualizedFileDiff.approximateLayoutCheckpoints: invalid hunk index");
			const leadingRegion = getExpandedRegion({
				isPartial: fileDiff.isPartial,
				rangeSize: hunk.collapsedBefore,
				expandedHunks,
				hunkIndex,
				collapsedContextThreshold
			});
			const leadingSeparatorHeight = leadingRegion.collapsedLines > 0 ? getLeadingHunkSeparatorLayout({
				type: hunkSeparators,
				metrics: this.metrics,
				hunkIndex,
				hunkSpecs: hunk.hunkSpecs
			})?.totalHeight ?? 0 : 0;
			processRows({
				rowCount: leadingRegion.fromStart,
				startLineIndex: (diffStyle === "split" ? hunk.splitLineStart : hunk.unifiedLineStart) - leadingRegion.rangeSize
			});
			let pendingLeadingSeparatorHeight = leadingSeparatorHeight;
			processRows({
				rowCount: leadingRegion.fromEnd,
				startLineIndex: (diffStyle === "split" ? hunk.splitLineStart : hunk.unifiedLineStart) - leadingRegion.fromEnd,
				preSeparatorHeight: pendingLeadingSeparatorHeight
			});
			if (leadingRegion.fromEnd > 0) pendingLeadingSeparatorHeight = 0;
			const trailingRegion = hunkIndex === finalHunkIndex ? getTrailingExpandedRegion({
				fileDiff,
				hunkIndex,
				expandedHunks,
				collapsedContextThreshold,
				errorPrefix: "VirtualizedFileDiff"
			}) : void 0;
			const trailingSeparatorHeight = trailingRegion != null && trailingRegion.collapsedLines > 0 ? getTrailingHunkSeparatorLayout({
				type: hunkSeparators,
				metrics: this.metrics
			})?.totalHeight ?? 0 : hunkIndex === finalHunkIndex && canHydratePartialDiff ? getTrailingHunkSeparatorLayout({
				type: hunkSeparators,
				metrics: this.metrics
			})?.totalHeight ?? 0 : 0;
			const trailingExpandedCount = trailingRegion != null ? trailingRegion.fromStart + trailingRegion.fromEnd : 0;
			const hunkBodyRowCount = diffStyle === "split" ? hunk.splitLineCount : hunk.unifiedLineCount;
			const hunkBodyStartLineIndex = diffStyle === "split" ? hunk.splitLineStart : hunk.unifiedLineStart;
			processRows({
				rowCount: hunkBodyRowCount,
				startLineIndex: hunkBodyStartLineIndex,
				preSeparatorHeight: pendingLeadingSeparatorHeight,
				postSeparatorHeight: trailingExpandedCount === 0 ? trailingSeparatorHeight : 0,
				metadataOffsets: getHunkMetadataOffsets({
					diffStyle,
					hunk,
					rowCount: hunkBodyRowCount
				})
			});
			if (trailingRegion != null && trailingExpandedCount > 0) processRows({
				rowCount: trailingExpandedCount,
				startLineIndex: hunkBodyStartLineIndex + hunkBodyRowCount,
				postSeparatorHeight: trailingSeparatorHeight
			});
		}
		this.cache.totalLines = renderedLineIndex;
	}
	getLayoutCheckpointBeforeLineIndex(lineIndex) {
		if (lineIndex <= 0 || this.cache.checkpoints.length === 0) return;
		let low = 0;
		let high = this.cache.checkpoints.length - 1;
		let result;
		while (low <= high) {
			const mid = low + high >> 1;
			const checkpoint = this.cache.checkpoints[mid];
			if (checkpoint == null) throw new Error("VirtualizedFileDiff: invalid checkpoint index");
			if (checkpoint.lineIndex <= lineIndex) {
				result = checkpoint;
				low = mid + 1;
			} else high = mid - 1;
		}
		return result;
	}
	getLayoutCheckpointBeforeTop(top, hunkLineCount) {
		let low = 0;
		let high = this.cache.checkpoints.length - 1;
		let resultIndex = -1;
		while (low <= high) {
			const mid = low + high >> 1;
			const checkpoint = this.cache.checkpoints[mid];
			if (checkpoint == null) throw new Error("VirtualizedFileDiff: invalid checkpoint index");
			if (checkpoint.top <= top) {
				resultIndex = mid;
				low = mid + 1;
			} else high = mid - 1;
		}
		if (hunkLineCount == null) return resultIndex >= 0 ? this.cache.checkpoints[resultIndex] : void 0;
		for (let index = resultIndex; index >= 0; index--) {
			const checkpoint = this.cache.checkpoints[index];
			if (checkpoint == null) throw new Error("VirtualizedFileDiff: invalid checkpoint index");
			if (checkpoint.renderedLineIndex % hunkLineCount === 0) return checkpoint;
		}
	}
	getExpandedLineCount(fileDiff, diffStyle) {
		let count = 0;
		if (fileDiff.isPartial) {
			for (const hunk of fileDiff.hunks) count += diffStyle === "split" ? hunk.splitLineCount : hunk.unifiedLineCount;
			return count;
		}
		const { expandUnchanged = false, collapsedContextThreshold = 1 } = this.options;
		const expandedHunks = expandUnchanged ? true : this.hunksRenderer.getExpandedHunksMap();
		for (const [hunkIndex, hunk] of fileDiff.hunks.entries()) {
			const hunkCount = diffStyle === "split" ? hunk.splitLineCount : hunk.unifiedLineCount;
			count += hunkCount;
			const collapsedBefore = Math.max(hunk.collapsedBefore, 0);
			const { fromStart, fromEnd, renderAll } = getExpandedRegion({
				isPartial: fileDiff.isPartial,
				rangeSize: collapsedBefore,
				expandedHunks,
				hunkIndex,
				collapsedContextThreshold
			});
			if (collapsedBefore > 0) count += renderAll ? collapsedBefore : fromStart + fromEnd;
		}
		const trailingRegion = getTrailingExpandedRegion({
			fileDiff,
			hunkIndex: fileDiff.hunks.length - 1,
			expandedHunks,
			collapsedContextThreshold,
			errorPrefix: "VirtualizedFileDiff"
		});
		if (trailingRegion != null) count += trailingRegion.fromStart + trailingRegion.fromEnd;
		return count;
	}
	getLayoutLineCount(fileDiff, diffStyle) {
		const expandedLineCount = this.getExpandedLineCount(fileDiff, diffStyle);
		const metadataLineCount = diffStyle === "split" ? fileDiff.splitLineCount : fileDiff.unifiedLineCount;
		return Math.max(expandedLineCount, metadataLineCount, fileDiff.additionLines.length, fileDiff.deletionLines.length, this.cache.totalLines);
	}
	computeRenderRangeFromWindow(fileDiff, fileTop, { top, bottom }) {
		const { disableFileHeader = false, expandUnchanged = false, collapsedContextThreshold = 1 } = this.options;
		const { hunkLineCount, lineHeight } = this.metrics;
		const diffStyle = this.getDiffStyle();
		const hunkSeparators = this.getHunkSeparatorType();
		const canHydratePartialDiff = canHydrateCollapsedContext(fileDiff, this.options.loadDiffFiles != null);
		const fileHeight = this.height;
		let lineCount = this.getLayoutLineCount(fileDiff, diffStyle);
		const headerRegion = getVirtualFileHeaderRegion(this.metrics, disableFileHeader);
		const paddingBottom = fileDiff.hunks.length > 0 ? getVirtualFilePaddingBottom(this.metrics) : 0;
		const { fileAnnotationHeight } = this.cache;
		const codeRegionTop = headerRegion + fileAnnotationHeight;
		const codeHeight = Math.max(0, fileHeight - headerRegion - fileAnnotationHeight - paddingBottom);
		const hasFileAnnotations = this.hasFileAnnotations(fileDiff);
		const fileAnnotationTop = fileTop + headerRegion;
		const measuredFileAnnotationVisible = fileAnnotationHeight > 0 && hasFileAnnotations && fileAnnotationTop < bottom && fileAnnotationTop + fileAnnotationHeight > top;
		if (fileTop < top - fileHeight || fileTop > bottom) return {
			startingLine: 0,
			totalLines: 0,
			bufferBefore: 0,
			bufferAfter: fileHeight - headerRegion - paddingBottom
		};
		if (lineCount <= hunkLineCount || fileDiff.hunks.length === 0) return {
			startingLine: 0,
			totalLines: hunkLineCount,
			bufferBefore: 0,
			bufferAfter: 0
		};
		this.approximateLayoutCheckpoints(fileDiff);
		lineCount = this.getLayoutLineCount(fileDiff, diffStyle);
		const estimatedTargetLines = Math.ceil(Math.max(bottom - top, 0) / lineHeight);
		const totalLines = Math.ceil(estimatedTargetLines / hunkLineCount) * hunkLineCount + hunkLineCount;
		const totalHunks = totalLines / hunkLineCount;
		const overflowHunks = totalHunks;
		const hunkOffsets = [];
		const viewportCenter = (top + bottom) / 2;
		const checkpoint = this.getLayoutCheckpointBeforeTop(Math.max(0, top - fileTop - totalLines * lineHeight * 2), hunkLineCount);
		let absoluteLineTop = fileTop + (checkpoint?.top ?? codeRegionTop);
		let currentLine = checkpoint?.renderedLineIndex ?? 0;
		let firstVisibleHunk;
		let centerHunk;
		let overflowCounter;
		iterateOverDiff({
			diff: fileDiff,
			diffStyle,
			startingLine: checkpoint?.renderedLineIndex ?? 0,
			expandedHunks: expandUnchanged ? true : this.hunksRenderer.getExpandedHunksMap(),
			collapsedContextThreshold,
			callback: ({ hunkIndex, hunk, collapsedBefore, collapsedAfter, deletionLine, additionLine }) => {
				const splitLineIndex = additionLine != null ? additionLine.splitLineIndex : deletionLine.splitLineIndex;
				const unifiedLineIndex = additionLine != null ? additionLine.unifiedLineIndex : deletionLine.unifiedLineIndex;
				const hasMetadata = (additionLine?.noEOFCR ?? false) || (deletionLine?.noEOFCR ?? false);
				const isFinalHunkRow = hunkIndex === fileDiff.hunks.length - 1 && hunk != null && (diffStyle === "split" ? splitLineIndex === hunk.splitLineStart + hunk.splitLineCount - 1 : unifiedLineIndex === hunk.unifiedLineStart + hunk.unifiedLineCount - 1);
				const gapAdjustment = (collapsedBefore > 0 ? getLeadingHunkSeparatorLayout({
					type: hunkSeparators,
					metrics: this.metrics,
					hunkIndex,
					hunkSpecs: hunk?.hunkSpecs
				}) : void 0)?.totalHeight ?? 0;
				absoluteLineTop += gapAdjustment;
				const isAtHunkBoundary = currentLine % hunkLineCount === 0;
				const currentHunk = Math.floor(currentLine / hunkLineCount);
				if (isAtHunkBoundary) {
					hunkOffsets[currentHunk] = absoluteLineTop - (fileTop + codeRegionTop + gapAdjustment);
					if (overflowCounter != null) {
						if (overflowCounter <= 0) return true;
						overflowCounter--;
					}
				}
				const lineHeight = this.getLineHeight(diffStyle === "split" ? splitLineIndex : unifiedLineIndex, hasMetadata);
				if (absoluteLineTop > top - lineHeight && absoluteLineTop < bottom) firstVisibleHunk ??= currentHunk;
				if (centerHunk == null && absoluteLineTop + lineHeight > viewportCenter) centerHunk = currentHunk;
				if (overflowCounter == null && absoluteLineTop >= bottom && isAtHunkBoundary) overflowCounter = overflowHunks;
				currentLine++;
				absoluteLineTop += lineHeight;
				if (collapsedAfter > 0 || isFinalHunkRow && canHydratePartialDiff) {
					const trailingSeparator = getTrailingHunkSeparatorLayout({
						type: hunkSeparators,
						metrics: this.metrics
					});
					if (trailingSeparator != null) {
						if (absoluteLineTop < bottom && absoluteLineTop + trailingSeparator.totalHeight > top) firstVisibleHunk ??= currentHunk;
						if (centerHunk == null && absoluteLineTop + trailingSeparator.totalHeight > viewportCenter) centerHunk = currentHunk;
						absoluteLineTop += trailingSeparator.totalHeight;
					}
				}
				return false;
			}
		});
		if (firstVisibleHunk == null) if (measuredFileAnnotationVisible) {
			firstVisibleHunk = 0;
			centerHunk = 0;
		} else return {
			startingLine: 0,
			totalLines: 0,
			bufferBefore: 0,
			bufferAfter: fileHeight - headerRegion - paddingBottom
		};
		centerHunk ??= firstVisibleHunk;
		const idealStartHunk = Math.round(centerHunk - totalHunks / 2);
		const maxStartHunk = Math.max(0, Math.ceil(lineCount / hunkLineCount) - totalHunks);
		const startHunk = Math.max(0, Math.min(idealStartHunk, maxStartHunk));
		const startingLine = startHunk * hunkLineCount;
		const clampedTotalLines = idealStartHunk < 0 ? totalLines + idealStartHunk * hunkLineCount : totalLines;
		const codeBufferBefore = hunkOffsets[startHunk] ?? 0;
		const bufferBefore = startingLine === 0 ? 0 : fileAnnotationHeight + codeBufferBefore;
		const finalHunkIndex = startHunk + clampedTotalLines / hunkLineCount;
		const bufferAfter = finalHunkIndex < hunkOffsets.length ? codeHeight - hunkOffsets[finalHunkIndex] : codeHeight - (absoluteLineTop - fileTop - codeRegionTop);
		return {
			startingLine,
			totalLines: clampedTotalLines,
			bufferBefore,
			bufferAfter: Math.max(0, bufferAfter)
		};
	}
};
function measureFileAnnotationHeight(codeGroups) {
	let height;
	for (const codeGroup of codeGroups) {
		if (codeGroup == null) continue;
		const content = codeGroup.children[1];
		if (!(content instanceof HTMLElement)) continue;
		for (const child of content.children) {
			if (!(child instanceof HTMLElement)) continue;
			if (child.dataset.lineAnnotation !== FILE_ANNOTATION_DOM_KEY) continue;
			height = Math.max(height ?? 0, child.getBoundingClientRect().height);
		}
	}
	return height;
}
function createHeightDeltaPrefix(heightDeltas) {
	const entries = Array.from(heightDeltas).sort((a, b) => a[0] - b[0]);
	const lineIndexes = [];
	const prefixTotals = [0];
	let total = 0;
	for (const [lineIndex, delta] of entries) {
		lineIndexes.push(lineIndex);
		total += delta;
		prefixTotals.push(total);
	}
	return {
		lineIndexes,
		prefixTotals
	};
}
function sumHeightDeltas({ lineIndexes, prefixTotals }, startLineIndex, endLineIndex) {
	if (startLineIndex >= endLineIndex || lineIndexes.length === 0) return 0;
	const start = lowerBound(lineIndexes, startLineIndex);
	return (prefixTotals[lowerBound(lineIndexes, endLineIndex)] ?? 0) - (prefixTotals[start] ?? 0);
}
function lowerBound(values, target) {
	let low = 0;
	let high = values.length;
	while (low < high) {
		const mid = low + high >> 1;
		const value = values[mid];
		if (value == null) throw new Error("VirtualizedFileDiff: invalid prefix index");
		if (value < target) low = mid + 1;
		else high = mid;
	}
	return low;
}
function getNextCheckpointIndex(renderedLineIndex) {
	return Math.ceil(renderedLineIndex / VIRTUALIZED_FILE_DIFF_LAYOUT_CHECKPOINT_INTERVAL) * VIRTUALIZED_FILE_DIFF_LAYOUT_CHECKPOINT_INTERVAL;
}
function countMetadataOffsetsBefore(metadataOffsets, offset) {
	let count = 0;
	for (const metadataOffset of metadataOffsets) if (metadataOffset < offset) count++;
	return count;
}
function getHunkMetadataOffsets({ diffStyle, hunk, rowCount }) {
	if (rowCount <= 0 || !hunk.noEOFCRAdditions && !hunk.noEOFCRDeletions) return [];
	const lastContent = hunk.hunkContent.at(-1);
	if (lastContent == null) return [];
	if (lastContent.type === "context") return [rowCount - 1];
	const splitCount = Math.max(lastContent.deletions, lastContent.additions);
	const unifiedCount = lastContent.deletions + lastContent.additions;
	if (diffStyle === "split") return splitCount > 0 && (hunk.noEOFCRAdditions || hunk.noEOFCRDeletions) ? [rowCount - 1] : [];
	const offsets = [];
	const contentStartOffset = rowCount - unifiedCount;
	if (lastContent.deletions > 0 && hunk.noEOFCRDeletions) offsets.push(contentStartOffset + lastContent.deletions - 1);
	if (lastContent.additions > 0 && hunk.noEOFCRAdditions) offsets.push(rowCount - 1);
	return offsets;
}
function hasDiffLayoutOptionChanged(previousOptions, nextOptions) {
	return (previousOptions.diffStyle ?? "split") !== (nextOptions.diffStyle ?? "split") || (previousOptions.overflow ?? "scroll") !== (nextOptions.overflow ?? "scroll") || (previousOptions.collapsed ?? false) !== (nextOptions.collapsed ?? false) || (previousOptions.disableLineNumbers ?? false) !== (nextOptions.disableLineNumbers ?? false) || (previousOptions.disableFileHeader ?? false) !== (nextOptions.disableFileHeader ?? false) || (previousOptions.diffIndicators ?? "bars") !== (nextOptions.diffIndicators ?? "bars") || (previousOptions.hunkSeparators ?? "line-info") !== (nextOptions.hunkSeparators ?? "line-info") || Boolean(previousOptions.loadDiffFiles) !== Boolean(nextOptions.loadDiffFiles) || (previousOptions.expandUnchanged ?? false) !== (nextOptions.expandUnchanged ?? false) || (previousOptions.collapsedContextThreshold ?? 1) !== (nextOptions.collapsedContextThreshold ?? 1) || previousOptions.unsafeCSS !== nextOptions.unsafeCSS;
}
function hasDiffEstimateOptionChanged(previousOptions, nextOptions) {
	return (previousOptions.disableFileHeader ?? false) !== (nextOptions.disableFileHeader ?? false) || (previousOptions.hunkSeparators ?? "line-info") !== (nextOptions.hunkSeparators ?? "line-info") || Boolean(previousOptions.loadDiffFiles) !== Boolean(nextOptions.loadDiffFiles) || (previousOptions.expandUnchanged ?? false) !== (nextOptions.expandUnchanged ?? false) || (previousOptions.collapsedContextThreshold ?? 1) !== (nextOptions.collapsedContextThreshold ?? 1);
}
function canHydrateCollapsedContext(fileDiff, hasFileLoader) {
	return fileDiff.isPartial && hasFileLoader && (fileDiff.type === "change" || fileDiff.type === "rename-changed");
}
function getOptionHunkSeparatorType(hunkSeparators) {
	return typeof hunkSeparators === "function" ? "custom" : hunkSeparators ?? "line-info";
}
function areOptionalFilesEqual(fileA, fileB) {
	if (fileA == null || fileB == null) return fileA == null && fileB == null;
	return areFilesEqual(fileA, fileB);
}
function parseLineIndex(lineIndexAttr, diffStyle) {
	const [unifiedIndex, splitIndex] = lineIndexAttr.split(",").map(Number);
	return diffStyle === "split" ? splitIndex : unifiedIndex;
}
//#endregion
export { VIRTUALIZED_FILE_DIFF_LAYOUT_CHECKPOINT_INTERVAL, VirtualizedFileDiff };

//# sourceMappingURL=VirtualizedFileDiff.js.map