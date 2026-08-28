//#region src/editor/command.d.ts
type EditorCommand = 'indent' | 'outdent' | 'indentLess' | 'indentMore' | 'undo' | 'redo' | 'selectAll' | 'findNextMatch' | 'openSearchPanel' | 'openSearchReplacePanel' | 'moveLineUp' | 'moveLineDown' | 'copyLineUp' | 'copyLineDown' | 'simplifySelection' | 'insertBlankLine' | 'deleteHardLineForward' | 'toggleComment' | 'toggleBlockComment' | 'moveCursorToDocStart' | 'moveCursorToDocEnd' | 'expandSelectionDocStart' | 'expandSelectionDocEnd';
type KeyboardKey = 'a' | 'b' | 'c' | 'd' | 'e' | 'f' | 'g' | 'h' | 'i' | 'j' | 'k' | 'l' | 'm' | 'n' | 'o' | 'p' | 'q' | 'r' | 's' | 't' | 'u' | 'v' | 'w' | 'x' | 'y' | 'z' | '0' | '1' | '2' | '3' | '4' | '5' | '6' | '7' | '8' | '9' | '`' | '-' | '=' | ',' | '.' | '/' | ';' | "'" | '[' | ']' | '\\' | 'Space' | 'Tab' | 'Enter' | 'Escape' | 'Backspace' | 'Delete' | 'ArrowUp' | 'ArrowDown' | 'ArrowLeft' | 'ArrowRight' | 'Home' | 'End' | 'PageUp' | 'PageDown' | 'F1' | 'F2' | 'F3' | 'F4' | 'F5' | 'F6' | 'F7' | 'F8' | 'F9' | 'F10' | 'F11' | 'F12';
type KeyboardModifier = 'cmdOrCtrl' | 'shift' | 'alt' | 'ctrl' | 'cmd';
type EditorShortcut = KeyboardKey | `${KeyboardModifier}+${KeyboardKey}` | `${KeyboardModifier}+${KeyboardModifier}+${KeyboardKey}`;
/** Later groups take precedence when bindings overlap. */
type EditorKeymap = ReadonlyArray<{
  /** Undefined applies on every platform. */readonly platform?: 'mac' | 'windows' | 'linux';
  readonly bindings: Readonly<Partial<Record<EditorShortcut, EditorCommand>>>;
}>;
declare function resolveEditorCommandFromKeyboardEvent(event: KeyboardEvent, keymap?: EditorKeymap, isMac?: boolean): EditorCommand | undefined;
declare function resolveFindAgainShortcut(event: KeyboardEvent, isMac?: boolean): 'next' | 'previous' | undefined;
//#endregion
export { EditorCommand, EditorKeymap, EditorShortcut, KeyboardKey, KeyboardModifier, resolveEditorCommandFromKeyboardEvent, resolveFindAgainShortcut };
//# sourceMappingURL=command.d.ts.map