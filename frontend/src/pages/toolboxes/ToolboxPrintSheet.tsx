import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import { Printer } from "lucide-react";
import { Link, Navigate, useParams } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { useAuth } from "@/hooks/useAuth";
import { drawerProfilesApi, drawersApi, toolboxesApi } from "@/lib/api";
import type { Drawer, DrawerProfile } from "@/lib/types";
import {
  computeToolboxLayout,
  groupDrawersByRow,
  SECTION_BREAK_PX,
  type RowDrawerInput,
} from "@/lib/toolboxLayoutGeometry";

// Bigger than ToolboxDetail's on-screen budget (560/560) since this renders
// at print resolution, not inside a scrollable panel -- same to-scale logic,
// just a larger pixel budget so handwriting has room inside each box.
const CANVAS_WIDTH_PX = 700;
const HEIGHT_PIXEL_BUDGET = 900;

/**
 * Standalone (outside AppShell) print-friendly view of a toolbox's drawer
 * layout: same to-scale box geometry as ToolboxDetail's "Layout" section,
 * but each box is left blank inside (no color fill, no existing tool list)
 * so it can be handwritten over with a pen out in the shop, then transcribed
 * later. Deliberately not nested under AppShell so the sidebar/topbar chrome
 * never has to be fought with print CSS -- this route renders only the
 * printable content plus a screen-only print button.
 */
export function ToolboxPrintSheet() {
  const { shopId, toolboxId } = useParams();
  const { isAuthed, isLoading: authLoading } = useAuth();

  const toolboxQuery = useQuery({
    queryKey: ["toolboxes", toolboxId],
    queryFn: () => toolboxesApi.get(shopId as string, toolboxId as string),
    enabled: !!shopId && !!toolboxId && isAuthed,
  });
  const drawersQuery = useQuery({
    queryKey: ["drawers", { toolbox_id: toolboxId }],
    queryFn: () => drawersApi.list(shopId as string, toolboxId as string),
    enabled: !!shopId && !!toolboxId && isAuthed,
  });
  const drawerProfilesQuery = useQuery({
    queryKey: ["profiles", "drawer-profiles"],
    queryFn: () => drawerProfilesApi.list(),
    enabled: isAuthed,
  });

  const profileById = React.useMemo(() => {
    const map = new Map<string, DrawerProfile>();
    (drawerProfilesQuery.data ?? []).forEach((p) => map.set(p.id, p));
    return map;
  }, [drawerProfilesQuery.data]);

  const { placed: drawersByRow } = React.useMemo(
    () => groupDrawersByRow(drawersQuery.data ?? []),
    [drawersQuery.data],
  );

  const rowsInput = React.useMemo(() => {
    const map = new Map<number, RowDrawerInput[]>();
    drawersByRow.forEach((drawers, row) => {
      const inputs = drawers
        .map((d): RowDrawerInput | null => {
          const profile = profileById.get(d.drawer_profile_id);
          if (!profile) return null;
          return {
            id: d.id,
            orderInRow: d.order_in_row ?? 0,
            widthMm: profile.inside_width_mm,
            heightMm: profile.inside_height_mm,
          };
        })
        .filter((x): x is RowDrawerInput => x !== null);
      if (inputs.length > 0) map.set(row, inputs);
    });
    return map;
  }, [drawersByRow, profileById]);

  const toolboxLayout = React.useMemo(
    () => computeToolboxLayout(rowsInput, CANVAS_WIDTH_PX, HEIGHT_PIXEL_BUDGET),
    [rowsInput],
  );

  const drawerById = React.useMemo(() => {
    const map = new Map<string, Drawer>();
    (drawersQuery.data ?? []).forEach((d) => map.set(d.id, d));
    return map;
  }, [drawersQuery.data]);

  if (!authLoading && !isAuthed) {
    return <Navigate to="/login" replace />;
  }
  if (toolboxQuery.isLoading || drawersQuery.isLoading || drawerProfilesQuery.isLoading) {
    return <p className="p-6 text-sm text-muted-foreground">Loading…</p>;
  }
  if (toolboxQuery.isError || !toolboxQuery.data) {
    return <p className="p-6 text-sm text-destructive">Toolbox not found.</p>;
  }

  const toolbox = toolboxQuery.data;

  return (
    <div className="mx-auto max-w-3xl p-6 text-foreground print:max-w-none print:p-0">
      <div className="mb-4 flex items-center justify-between print:hidden">
        <Link
          to={`/shops/${shopId}/toolboxes/${toolboxId}`}
          className="text-sm text-muted-foreground hover:underline"
        >
          ← Back to {toolbox.name}
        </Link>
        <Button size="sm" onClick={() => window.print()}>
          <Printer />
          Print
        </Button>
      </div>

      <div className="mb-4 print:mb-3">
        <h1 className="text-lg font-semibold">{toolbox.name} — Inventory Sheet</h1>
        <p className="text-xs text-muted-foreground">
          Write tool names / quantities directly on each drawer's box, then enter into
          WorkshopOS later.
        </p>
      </div>

      {toolboxLayout.rows.length === 0 ? (
        <p className="text-xs text-muted-foreground">
          No drawers have a Row assigned yet, so there's nothing to lay out.
        </p>
      ) : (
        <svg
          width={toolboxLayout.canvasWidthPx}
          height={toolboxLayout.canvasHeightPx}
          viewBox={`0 0 ${toolboxLayout.canvasWidthPx} ${toolboxLayout.canvasHeightPx}`}
          className="block max-w-full"
          role="img"
          aria-label="Toolbox layout, blank for handwritten inventory"
        >
          <rect
            x={0}
            y={0}
            width={toolboxLayout.canvasWidthPx}
            height={toolboxLayout.canvasHeightPx}
            fill="none"
            stroke="black"
            strokeWidth={1}
          />
          {toolboxLayout.rows
            .filter((rowLayout) => rowLayout.hasBreakBefore)
            .map((rowLayout) => (
              <rect
                key={`break-${rowLayout.row}`}
                x={0}
                y={rowLayout.yPx - SECTION_BREAK_PX}
                width={toolboxLayout.canvasWidthPx}
                height={SECTION_BREAK_PX}
                fill="#e5e5e5"
              />
            ))}
          {toolboxLayout.rows.flatMap((rowLayout) =>
            rowLayout.drawers.map((placed) => {
              const drawer = drawerById.get(placed.id);
              const profile = drawer ? profileById.get(drawer.drawer_profile_id) : undefined;
              const name = drawer?.name || drawer?.position_label || "Drawer";
              const dims = profile
                ? `${profile.inside_width_mm}×${profile.inside_depth_mm}×${profile.inside_height_mm}mm`
                : "";
              return (
                <g key={placed.id}>
                  <rect
                    x={placed.xPx}
                    y={rowLayout.yPx}
                    width={placed.widthPx}
                    height={rowLayout.heightPx}
                    fill="none"
                    stroke="black"
                    strokeWidth={1}
                  />
                  <text x={placed.xPx + 6} y={rowLayout.yPx + 16} fontSize={12} fontWeight={600} fill="black">
                    {name}
                  </text>
                  <text x={placed.xPx + 6} y={rowLayout.yPx + 30} fontSize={10} fill="#555">
                    {dims}
                  </text>
                </g>
              );
            }),
          )}
        </svg>
      )}
    </div>
  );
}
