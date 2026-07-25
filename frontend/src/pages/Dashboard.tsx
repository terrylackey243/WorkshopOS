import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { dashboardApi, markMaintenanceDone, returnTool } from "@/lib/api";
import type { Tool } from "@/lib/types";

/**
 * This app's first dashboard-style page (confirmed via research: `/` used
 * to redirect straight to `/shops`, no home/dashboard route existed
 * before). Three always-visible lists -- rendered even when empty, with an
 * explicit "nothing here" message rather than being conditionally hidden.
 * This mirrors `DrawerDetail.tsx`'s Unplaced-list idiom exactly: this
 * codebase has hit real silent-failure UX bugs before (Milestone 2's
 * profile-form bug), so "things needing attention" surfaces here follow
 * the same "permanent, hard-to-miss spot" convention deliberately, not a
 * banner that's easy to scroll past.
 */
export function Dashboard() {
  const queryClient = useQueryClient();
  const dashboardQuery = useQuery({ queryKey: ["dashboard"], queryFn: () => dashboardApi.get() });

  const returnMutation = useMutation({
    mutationFn: (toolId: string) => returnTool(toolId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      queryClient.invalidateQueries({ queryKey: ["tools"] });
    },
  });

  const markMaintenanceMutation = useMutation({
    mutationFn: (toolId: string) => markMaintenanceDone(toolId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      queryClient.invalidateQueries({ queryKey: ["tools"] });
    },
  });

  const renderToolRow = (tool: Tool, destructive: boolean) => (
    <li
      key={tool.id}
      className={`flex items-center justify-between gap-2 rounded-sm border px-2.5 py-1.5 text-sm ${
        destructive ? "border-destructive/40 bg-destructive/10" : "border-border"
      }`}
    >
      <div className="min-w-0">
        <Link to={`/tools/${tool.id}`} className="font-medium hover:underline">
          {tool.name}
        </Link>
        <span className="ml-2 text-xs text-muted-foreground">
          checked out to {tool.checked_out_to}
          {tool.checkout_due_at && ` — due ${new Date(tool.checkout_due_at).toLocaleDateString()}`}
        </span>
      </div>
      <Button
        size="sm"
        variant="ghost"
        className="h-6 shrink-0 px-1.5 text-xs"
        disabled={returnMutation.isPending}
        onClick={() => returnMutation.mutate(tool.id)}
      >
        Return
      </Button>
    </li>
  );

  const renderMaintenanceRow = (tool: Tool) => (
    <li
      key={tool.id}
      className="flex items-center justify-between gap-2 rounded-sm border border-border px-2.5 py-1.5 text-sm"
    >
      <div className="min-w-0">
        <Link to={`/tools/${tool.id}`} className="font-medium hover:underline">
          {tool.name}
        </Link>
        <span className="ml-2 text-xs text-muted-foreground">
          {tool.last_maintained_at
            ? `last maintained ${new Date(tool.last_maintained_at).toLocaleDateString()}`
            : "never maintained"}
          {" — every "}
          {tool.maintenance_interval_days}
          {" days"}
        </span>
      </div>
      <Button
        size="sm"
        variant="ghost"
        className="h-6 shrink-0 px-1.5 text-xs"
        disabled={markMaintenanceMutation.isPending}
        onClick={() => markMaintenanceMutation.mutate(tool.id)}
      >
        Mark done
      </Button>
    </li>
  );

  return (
    <div className="flex h-full flex-col gap-6 overflow-auto scrollbar-thin p-4">
      <div>
        <h1 className="text-base font-semibold">Dashboard</h1>
        <p className="text-xs text-muted-foreground">Things needing attention across your org.</p>
      </div>

      <section>
        <h2 className="mb-2 text-sm font-semibold text-destructive">
          Overdue checkouts ({dashboardQuery.data?.overdue_checkouts.length ?? 0})
        </h2>
        <ul className="flex flex-col gap-1.5">
          {(dashboardQuery.data?.overdue_checkouts ?? []).map((t) => renderToolRow(t, true))}
          {dashboardQuery.isSuccess && dashboardQuery.data.overdue_checkouts.length === 0 && (
            <li className="rounded-sm border border-border px-2.5 py-1.5 text-sm text-muted-foreground">
              Nothing overdue.
            </li>
          )}
        </ul>
      </section>

      <section>
        <h2 className="mb-2 text-sm font-semibold">
          Active checkouts ({dashboardQuery.data?.active_checkouts.length ?? 0})
        </h2>
        <ul className="flex flex-col gap-1.5">
          {(dashboardQuery.data?.active_checkouts ?? []).map((t) => renderToolRow(t, false))}
          {dashboardQuery.isSuccess && dashboardQuery.data.active_checkouts.length === 0 && (
            <li className="rounded-sm border border-border px-2.5 py-1.5 text-sm text-muted-foreground">
              Nothing checked out.
            </li>
          )}
        </ul>
      </section>

      <section>
        <h2 className="mb-2 text-sm font-semibold">
          Maintenance due ({dashboardQuery.data?.maintenance_due.length ?? 0})
        </h2>
        <ul className="flex flex-col gap-1.5">
          {(dashboardQuery.data?.maintenance_due ?? []).map((t) => renderMaintenanceRow(t))}
          {dashboardQuery.isSuccess && dashboardQuery.data.maintenance_due.length === 0 && (
            <li className="rounded-sm border border-border px-2.5 py-1.5 text-sm text-muted-foreground">
              Nothing due for maintenance.
            </li>
          )}
        </ul>
      </section>
    </div>
  );
}
