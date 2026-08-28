//#region src/managers/UniversalRenderingManager.ts
const callbacks = /* @__PURE__ */ new Set();
let frameId = null;
function queueRender(callback) {
	callbacks.add(callback);
	frameId ??= requestAnimationFrame(render);
}
function dequeueRender(callback) {
	if (callbacks.delete(callback) && callbacks.size === 0 && frameId != null) {
		cancelAnimationFrame(frameId);
		frameId = null;
	}
}
function clearRenderQueue() {
	callbacks.clear();
	if (frameId != null && typeof cancelAnimationFrame === "function") cancelAnimationFrame(frameId);
	frameId = null;
}
function render(time) {
	const toIterate = new Set(callbacks);
	callbacks.clear();
	for (const callback of toIterate) try {
		callback(time);
	} catch (error) {
		console.error(error);
	}
	if (callbacks.size > 0) frameId = requestAnimationFrame(render);
	else frameId = null;
}
//#endregion
export { clearRenderQueue, dequeueRender, queueRender };

//# sourceMappingURL=UniversalRenderingManager.js.map