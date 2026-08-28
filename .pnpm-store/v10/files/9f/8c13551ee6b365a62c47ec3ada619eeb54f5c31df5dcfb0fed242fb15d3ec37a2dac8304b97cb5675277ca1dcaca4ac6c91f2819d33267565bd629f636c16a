//#region src/utils/areManagedSnapshotsEqual.ts
function areManagedSnapshotsEqual(previous, next) {
	if (previous == null || next == null) return previous === next;
	if (previous.header !== next.header || previous.footer !== next.footer) return false;
	return areRenderedItemsEqual(previous.items, next.items);
}
function areRenderedItemsEqual(previous, next) {
	if (previous == null || next == null) return previous === next;
	if (previous.length !== next.length) return false;
	for (let index = 0; index < previous.length; index++) {
		const previousItem = previous[index];
		const nextItem = next[index];
		if (previousItem == null || nextItem == null || previousItem.id !== nextItem.id || previousItem.type !== nextItem.type || previousItem.element !== nextItem.element || previousItem.instance !== nextItem.instance || previousItem.version !== nextItem.version) return false;
	}
	return true;
}
//#endregion
export { areManagedSnapshotsEqual };

//# sourceMappingURL=areManagedSnapshotsEqual.js.map