//#region src/utils/awaitWithTimeout.ts
async function awaitWithTimeout(callback, timeout = 300) {
	let timeoutId;
	try {
		await Promise.race([callback(), new Promise((resolve) => {
			timeoutId = setTimeout(resolve, timeout);
		})]);
	} finally {
		if (timeoutId != null) clearTimeout(timeoutId);
	}
}
//#endregion
export { awaitWithTimeout };

//# sourceMappingURL=awaitWithTimeout.js.map