import * as React from "react";
import { Link } from "react-router-dom";
import { X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { fetchFailedJobs } from "@/lib/api";
import { handleJobFailureDetected, onJobFailureDetected } from "@/lib/jobFailures";
import type { FailedJob } from "@/lib/types";

const POLL_INTERVAL_MS = 30_000;

const KIND_LABEL: Record<FailedJob["kind"], string> = {
  label: "Label generation failed",
  insert: "Bin generation failed",
  plate: "Plate export failed",
};

/**
 * Global background-job-failure notifier -- mounted once in AppShell.tsx
 * alongside <UpgradeDialog />/<CommandPalette />. Unlike UpgradeDialog
 * (interceptor-detected, one HTTP response = one event), failures here are
 * poll-detected: `Design`/`InsertDesign` have a real `status` column but
 * plate failures live inside a JSONB blob, so there's no single response to
 * hook -- see app/routers/failed_jobs.py. Polls GET .../failed-jobs every
 * 30s and diffs against a locally-tracked (in-memory, not persisted) set of
 * already-notified failure ids so the same failure doesn't re-toast on
 * every tick. No "notification inbox" -- a dismissed toast is just gone
 * until a genuinely new failure appears (deliberate scope limit).
 */
export function JobFailureToast() {
  const [toasts, setToasts] = React.useState<FailedJob[]>([]);
  // In-memory only, reset on page load -- so a failure that happened while
  // the user was away still surfaces once on the first poll after they
  // return (the whole point of this feature is not requiring a manual
  // status check), it just won't repeat on every subsequent 30s tick.
  const seenIds = React.useRef<Set<string>>(new Set());

  React.useEffect(() => {
    return onJobFailureDetected((job) => {
      setToasts((current) => [...current, job]);
    });
  }, []);

  React.useEffect(() => {
    let cancelled = false;

    const poll = async () => {
      try {
        const jobs = await fetchFailedJobs();
        if (cancelled) return;
        for (const job of jobs) {
          const key = `${job.kind}:${job.id}`;
          if (seenIds.current.has(key)) continue;
          seenIds.current.add(key);
          handleJobFailureDetected(job);
        }
      } catch {
        // Transient network/auth hiccups shouldn't crash the poll loop --
        // just try again next tick.
      }
    };

    void poll();
    const interval = window.setInterval(poll, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, []);

  if (toasts.length === 0) return null;

  return (
    <div className="fixed bottom-4 right-4 z-50 flex w-80 flex-col gap-2">
      {toasts.map((job, index) => (
        <div
          key={`${job.kind}:${job.id}:${index}`}
          className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm shadow-lg"
        >
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <p className="font-semibold text-destructive">{KIND_LABEL[job.kind]}</p>
              <p className="truncate text-xs text-muted-foreground">{job.name}</p>
              {job.error_message && (
                <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">{job.error_message}</p>
              )}
              {job.link && (
                <Link
                  to={job.link}
                  className="mt-1 inline-block text-xs font-medium text-primary hover:underline"
                  onClick={() => setToasts((current) => current.filter((_, i) => i !== index))}
                >
                  View
                </Link>
              )}
            </div>
            <Button
              size="icon"
              variant="ghost"
              className="h-5 w-5 shrink-0"
              onClick={() => setToasts((current) => current.filter((_, i) => i !== index))}
            >
              <X className="h-3 w-3" />
            </Button>
          </div>
        </div>
      ))}
    </div>
  );
}
