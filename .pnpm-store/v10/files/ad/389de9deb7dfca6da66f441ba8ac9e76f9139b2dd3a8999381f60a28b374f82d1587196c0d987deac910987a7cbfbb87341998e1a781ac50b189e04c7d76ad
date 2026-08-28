import { DiffsEditor } from "../types.js";
import { EditorOptions } from "../editor/editor.js";
import { Context, PropsWithChildren } from "react";

//#region src/react/EditContext.d.ts
/** Creates an Editor. Components manage the instance lifecycle. */
type CreateEditor<LAnnotation> = (options: EditorOptions<LAnnotation>) => DiffsEditor<LAnnotation>;
interface EditProviderProps<LAnnotation> {
  /** Combines shared defaults with the supplied per-surface options. */
  createEditor: CreateEditor<LAnnotation>;
}
declare const EditContext: Context<CreateEditor<any> | undefined>;
declare function EditProvider<LAnnotation>({
  children,
  createEditor
}: PropsWithChildren<EditProviderProps<LAnnotation>>): React.JSX.Element;
declare function useCreateEditor<LAnnotation>(): CreateEditor<LAnnotation> | undefined;
//#endregion
export { CreateEditor, EditContext, EditProvider, EditProviderProps, useCreateEditor };
//# sourceMappingURL=EditContext.d.ts.map