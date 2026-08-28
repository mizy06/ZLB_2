import { DiffFileInput, FileContents } from "../types.js";
import { DiffBasePropsReact } from "./types.js";

//#region src/react/MultiFileDiff.d.ts
interface MultiFileDiffBaseProps<LAnnotation> extends DiffBasePropsReact<LAnnotation> {
  disableWorkerPool?: boolean;
}
type MultiFileDiffProps<LAnnotation> = MultiFileDiffBaseProps<LAnnotation> & DiffFileInput;
declare function MultiFileDiff<LAnnotation = undefined>({
  oldFile,
  newFile,
  options,
  editorOptions,
  metrics,
  lineAnnotations,
  selectedLines,
  className,
  style,
  prerenderedHTML,
  renderAnnotation,
  renderCustomHeader,
  renderHeaderPrefix,
  renderHeaderFilenameSuffix,
  renderHeaderMetadata,
  renderGutterUtility,
  disableWorkerPool,
  edit
}: MultiFileDiffProps<LAnnotation>): React.JSX.Element;
//#endregion
export { type FileContents, MultiFileDiff, MultiFileDiffProps };
//# sourceMappingURL=MultiFileDiff.d.ts.map