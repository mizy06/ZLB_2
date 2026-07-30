export type ReviewAction =
  | "keep"
  | "delete"
  | "change_parent"
  | "rename"
  | "accept_root";

const REVIEW_ACTIONS: Record<string, readonly ReviewAction[]> = {
  root_choice: ["keep", "accept_root"],
  competing_parent: ["keep", "change_parent", "rename"],
  abstract_parent: ["keep", "delete", "rename"],
  uncovered_content: ["keep", "rename"],
  cross_link: ["keep"],
};

export function reviewActionsForType(type: string): ReviewAction[] {
  return [...(REVIEW_ACTIONS[type] || ["keep"])];
}

export function reviewSupportsAction(
  type: string,
  action: ReviewAction,
): boolean {
  return reviewActionsForType(type).includes(action);
}
