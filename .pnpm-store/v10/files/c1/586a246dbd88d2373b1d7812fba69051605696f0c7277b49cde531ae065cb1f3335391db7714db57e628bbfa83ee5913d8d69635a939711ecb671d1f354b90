//#region src/managers/ResizeManager.d.ts
type ResizeManagerColumnVariableMode = 'apply' | 'measure';
interface ResizeManagerSetupOptions {
  disableAnnotations: boolean;
  columnVariables?: ResizeManagerColumnVariableMode;
}
declare class ResizeManager {
  private static resizeObserver;
  private static managersByElement;
  private static getResizeObserver;
  private static handleSharedResizeEntries;
  private observedNodes;
  setup(pre: HTMLPreElement, {
    disableAnnotations,
    columnVariables
  }: ResizeManagerSetupOptions): void;
  cleanUp(): void;
  private observe;
  private unobserve;
  private handleResizeEntries;
  private applyAnnotationUpdates;
  private applyColumnUpdates;
  private applyNewHeight;
}
//#endregion
export { ResizeManager, ResizeManagerColumnVariableMode, ResizeManagerSetupOptions };
//# sourceMappingURL=ResizeManager.d.ts.map