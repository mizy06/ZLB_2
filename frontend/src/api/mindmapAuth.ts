type AuthRequiredListener = () => void;

const listeners = new Set<AuthRequiredListener>();

export function onMindmapAuthRequired(
  listener: AuthRequiredListener,
): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function markMindmapAuthRequired(): void {
  for (const listener of listeners) {
    try {
      listener();
    } catch {
      // A UI listener must not break the request that discovered the 401.
    }
  }
}
