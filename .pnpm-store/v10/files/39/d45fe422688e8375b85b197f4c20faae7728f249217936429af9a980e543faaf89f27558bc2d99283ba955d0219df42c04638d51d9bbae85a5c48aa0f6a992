//#region src/utils/platform.ts
let _isMacLike = void 0;
let _isLinux = void 0;
let _isSafari = void 0;
/**
* Clears the cached platform/browser detection. Detection is memoized on first
* call, so a test process that swaps `navigator` (e.g. to exercise Linux or
* Safari behavior) must reset it; otherwise the value cached by an earlier test
* leaks across tests and no longer matches the active navigator.
*/
function resetPlatformDetection() {
	_isMacLike = void 0;
	_isLinux = void 0;
	_isSafari = void 0;
}
function isMacLike() {
	return _isMacLike ??= /macOS|MacIntel|iPhone|iPad|iPod/i.test(getPlatform());
}
function isLinux() {
	return _isLinux ??= /Linux/i.test(getPlatform());
}
function isSafari() {
	return _isSafari ??= "safari" in window && "pushNotification" in window.safari || /^((?!chrome|android).)*safari/i.test(navigator.userAgent);
}
function getPlatform() {
	const navigator = globalThis.navigator;
	return navigator?.platform ?? navigator?.userAgentData?.platform ?? "unknown";
}
//#endregion
export { isLinux, isMacLike, isSafari, resetPlatformDetection };

//# sourceMappingURL=platform.js.map