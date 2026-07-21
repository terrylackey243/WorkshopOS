// Simple pub/sub so the API client can surface a plan-limit-exceeded (402)
// response without importing React or the router -- mirrors lib/auth.ts's
// `handleUnauthorized` pattern exactly (keeps lib/ dependency-free of UI).

type Listener = (message: string) => void;
const listeners = new Set<Listener>();

/** Called by the api client on a 402 response. */
export function handlePlanLimitExceeded(message: string): void {
  listeners.forEach((l) => l(message));
}

export function onPlanLimitExceeded(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
