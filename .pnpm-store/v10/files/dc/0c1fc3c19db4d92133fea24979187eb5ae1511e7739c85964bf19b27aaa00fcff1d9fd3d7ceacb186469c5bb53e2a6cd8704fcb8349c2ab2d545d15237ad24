import { DiffLineAnnotation, FileDiffMetadata, SelectedLineRange, VirtualFileMetrics } from "../../types.js";
import { GetHoveredLineResult } from "../../managers/InteractionManager.js";
import { FileDiffOptions } from "../../components/FileDiff.js";
import { EditorOptions } from "../../editor/editor.js";
//#region src/react/utils/useFileDiffInstance.d.ts
interface UseFileDiffInstanceProps<LAnnotation> {
  fileDiff: FileDiffMetadata;
  options: FileDiffOptions<LAnnotation> | undefined;
  editorOptions: EditorOptions<LAnnotation> | undefined;
  lineAnnotations: DiffLineAnnotation<LAnnotation>[] | undefined;
  selectedLines: SelectedLineRange | null | undefined;
  prerenderedHTML: string | undefined;
  metrics?: VirtualFileMetrics;
  hasGutterRenderUtility: boolean;
  hasCustomHeader: boolean;
  disableWorkerPool: boolean;
  edit: boolean;
}
interface UseFileDiffInstanceReturn {
  ref(node: HTMLElement | null): void;
  getHoveredLine(): GetHoveredLineResult<'diff'> | undefined;
}
declare function useFileDiffInstance<LAnnotation>({
  fileDiff,
  options,
  editorOptions,
  lineAnnotations,
  selectedLines,
  prerenderedHTML,
  metrics,
  hasGutterRenderUtility,
  hasCustomHeader,
  disableWorkerPool,
  edit
}: UseFileDiffInstanceProps<LAnnotation>): UseFileDiffInstanceReturn;
//#endregion
export { useFileDiffInstance };
//# sourceMappingURL=useFileDiffInstance.d.ts.map