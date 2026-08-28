import { InteractionManagerMode, OnTokenEventProps } from "../managers/InteractionManager.js";

//#region src/utils/shouldUseTokenTransformer.d.ts
interface ShouldUseTokenTransformerProps<TMode extends InteractionManagerMode> {
  onTokenClick?(props: OnTokenEventProps<TMode>, event: MouseEvent): unknown;
  onTokenEnter?(props: OnTokenEventProps<TMode>, event: PointerEvent): unknown;
  onTokenLeave?(props: OnTokenEventProps<TMode>, event: PointerEvent): unknown;
  useTokenTransformer?: boolean;
}
declare function shouldUseTokenTransformer<TMode extends 'file' | 'diff' = 'file'>(options: ShouldUseTokenTransformerProps<TMode> | undefined): boolean;
//#endregion
export { shouldUseTokenTransformer };
//# sourceMappingURL=shouldUseTokenTransformer.d.ts.map