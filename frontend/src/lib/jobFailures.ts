import type { FailedJob } from "@/lib/types";

// Same plain listener-`Set` pub/sub shape as lib/billing.ts -- zero coupling
// to axios/HTTP status codes there, so it's equally reusable for a
// poll-detected trigger instead of an interceptor-detected one.

type Listener = (job: FailedJob) => void;
const listeners = new Set<Listener>();

/** Called by the AppShell poll for each newly-seen failure. */
export function handleJobFailureDetected(job: FailedJob): void {
  listeners.forEach((l) => l(job));
}

export function onJobFailureDetected(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
