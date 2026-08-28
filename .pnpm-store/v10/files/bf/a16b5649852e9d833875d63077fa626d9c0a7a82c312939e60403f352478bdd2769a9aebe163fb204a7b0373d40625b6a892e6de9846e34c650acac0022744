import { EditorState } from "../types.js";

//#region src/editor/stateStorage.d.ts
interface IStateStorage {
  /** Read the editor state stored for a file cache key. */
  get(cacheKey: string): EditorState | undefined | Promise<EditorState | undefined>;
  /** Store the editor state for a file cache key. */
  set(cacheKey: string, state: EditorState): void | Promise<void>;
}
type PersistStateStorage = 'inMemory' | 'indexedDB' | IStateStorage;
declare function cloneEditorState(state: EditorState): EditorState;
declare function createStateStorage(storage: PersistStateStorage): IStateStorage;
//#endregion
export { IStateStorage, PersistStateStorage, cloneEditorState, createStateStorage };
//# sourceMappingURL=stateStorage.d.ts.map