//#region src/utils/annotationHelpers.ts
/** Narrow an annotation to the side-tagged diff shape. */
function isDiffAnnotation(annotation) {
	return "side" in annotation;
}
/** Narrow an annotation to the side-less file shape. */
function isFileAnnotation(annotation) {
	return !isDiffAnnotation(annotation);
}
/**
* Narrow a homogeneous editor annotation collection to diff annotations.
* Empty collections return true because they are valid for either shape.
*/
function isDiffAnnotationCollection(annotations) {
	const first = annotations[0];
	return first == null || isDiffAnnotation(first);
}
/**
* Narrow a homogeneous editor annotation collection to file annotations.
* Empty collections return true because they are valid for either shape.
*/
function isFileAnnotationCollection(annotations) {
	const first = annotations[0];
	return first == null || isFileAnnotation(first);
}
//#endregion
export { isDiffAnnotation, isDiffAnnotationCollection, isFileAnnotation, isFileAnnotationCollection };

//# sourceMappingURL=annotationHelpers.js.map