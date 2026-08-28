//#region src/editor/stateStorage.ts
function cloneEditorState(state) {
	return {
		selections: state.selections?.map((selection) => ({
			start: { ...selection.start },
			end: { ...selection.end },
			direction: selection.direction
		})),
		view: state.view === void 0 ? void 0 : { ...state.view }
	};
}
function createStateStorage(storage) {
	return typeof storage === "object" ? storage : storage === "indexedDB" ? new IndexedDBStateStorage() : new InMemoryStateStorage();
}
var InMemoryStateStorage = class {
	#states = /* @__PURE__ */ new Map();
	get(cacheKey) {
		const state = this.#states.get(cacheKey);
		return state === void 0 ? void 0 : cloneEditorState(state);
	}
	set(cacheKey, state) {
		this.#states.set(cacheKey, cloneEditorState(state));
	}
};
const DATABASE_NAME = "pierre-diffs-editor-state";
const DATABASE_VERSION = 1;
const STORE_NAME = "states";
var IndexedDBStateStorage = class {
	#database = openDatabase();
	async get(cacheKey) {
		const database = await this.#database;
		if (database === void 0) return;
		const state = await requestToPromise(database.transaction(STORE_NAME, "readonly").objectStore(STORE_NAME).get(cacheKey));
		return state === void 0 ? void 0 : cloneEditorState(state);
	}
	async set(cacheKey, state) {
		const database = await this.#database;
		if (database === void 0) return;
		await requestToPromise(database.transaction(STORE_NAME, "readwrite").objectStore(STORE_NAME).put(cloneEditorState(state), cacheKey));
	}
};
function openDatabase() {
	try {
		const factory = globalThis.indexedDB;
		if (factory === void 0) return Promise.resolve(void 0);
		const request = factory.open(DATABASE_NAME, DATABASE_VERSION);
		request.onupgradeneeded = () => {
			const database = request.result;
			if (!database.objectStoreNames.contains(STORE_NAME)) database.createObjectStore(STORE_NAME);
		};
		return requestToPromise(request);
	} catch {
		return Promise.resolve(void 0);
	}
}
function requestToPromise(request) {
	return new Promise((resolve, reject) => {
		request.onsuccess = () => resolve(request.result);
		request.onerror = () => reject(request.error);
	});
}
//#endregion
export { cloneEditorState, createStateStorage };

//# sourceMappingURL=stateStorage.js.map