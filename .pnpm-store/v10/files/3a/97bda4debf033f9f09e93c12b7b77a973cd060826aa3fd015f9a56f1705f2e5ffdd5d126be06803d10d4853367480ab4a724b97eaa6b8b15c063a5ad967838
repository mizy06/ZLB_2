import { DiffLineAnnotation, LineAnnotation } from "../types.js";

//#region src/utils/annotationHelpers.d.ts
/** Narrow an annotation to the side-tagged diff shape. */
declare function isDiffAnnotation<LAnnotation = undefined>(annotation: LineAnnotation<LAnnotation> | DiffLineAnnotation<LAnnotation>): annotation is DiffLineAnnotation<LAnnotation>;
/** Narrow an annotation to the side-less file shape. */
declare function isFileAnnotation<LAnnotation = undefined>(annotation: LineAnnotation<LAnnotation> | DiffLineAnnotation<LAnnotation>): annotation is LineAnnotation<LAnnotation>;
/**
 * Narrow a homogeneous editor annotation collection to diff annotations.
 * Empty collections return true because they are valid for either shape.
 */
declare function isDiffAnnotationCollection<LAnnotation = undefined>(annotations: LineAnnotation<LAnnotation>[] | DiffLineAnnotation<LAnnotation>[]): annotations is DiffLineAnnotation<LAnnotation>[];
/**
 * Narrow a homogeneous editor annotation collection to file annotations.
 * Empty collections return true because they are valid for either shape.
 */
declare function isFileAnnotationCollection<LAnnotation = undefined>(annotations: LineAnnotation<LAnnotation>[] | DiffLineAnnotation<LAnnotation>[]): annotations is LineAnnotation<LAnnotation>[];
//#endregion
export { isDiffAnnotation, isDiffAnnotationCollection, isFileAnnotation, isFileAnnotationCollection };
//# sourceMappingURL=annotationHelpers.d.ts.map