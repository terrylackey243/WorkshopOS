import * as React from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Plus, Printer, Trash2 } from "lucide-react";
import { useForm } from "react-hook-form";
import { Link, useNavigate, useParams } from "react-router-dom";
import { z } from "zod";

import { FormDialog } from "@/components/FormDialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { SearchableSelect } from "@/components/ui/searchable-select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { drawerProfilesApi, drawersApi, toolboxesApi } from "@/lib/api";
import { colorForIndex } from "@/lib/drawerLayoutGeometry";
import type { Drawer, DrawerProfile } from "@/lib/types";
import {
  computeToolboxLayout,
  groupDrawersByRow,
  SECTION_BREAK_PX,
  type RowDrawerInput,
} from "@/lib/toolboxLayoutGeometry";

// Same "fit to a pixel budget" role as DrawerDetail.tsx's LAYOUT_PIXEL_BUDGET.
const CANVAS_WIDTH_PX = 560;
const HEIGHT_PIXEL_BUDGET = 560;

const toolboxSchema = z.object({
  name: z.string().min(1, "Required"),
  kind: z.string().optional(),
  notes: z.string().optional(),
});
type ToolboxFormValues = z.infer<typeof toolboxSchema>;

const drawerSchema = z.object({
  drawer_profile_id: z.string().min(1, "Required"),
  name: z.string().optional(),
  position_label: z.string().optional(),
  notes: z.string().optional(),
  row: z.string().optional(),
});
type DrawerFormValues = z.infer<typeof drawerSchema>;

export function ToolboxDetail() {
  const { shopId, toolboxId } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [drawerDialogOpen, setDrawerDialogOpen] = React.useState(false);

  const toolboxQuery = useQuery({
    queryKey: ["toolboxes", toolboxId],
    queryFn: () => toolboxesApi.get(shopId as string, toolboxId as string),
    enabled: !!shopId && !!toolboxId,
  });
  const drawersQuery = useQuery({
    queryKey: ["drawers", { toolbox_id: toolboxId }],
    queryFn: () => drawersApi.list(shopId as string, toolboxId as string),
    enabled: !!shopId && !!toolboxId,
  });
  const drawerProfilesQuery = useQuery({
    queryKey: ["profiles", "drawer-profiles"],
    queryFn: () => drawerProfilesApi.list(),
  });

  const toolboxForm = useForm<ToolboxFormValues>({ resolver: zodResolver(toolboxSchema) });
  React.useEffect(() => {
    if (toolboxQuery.data) {
      toolboxForm.reset({
        name: toolboxQuery.data.name,
        kind: toolboxQuery.data.kind ?? "",
        notes: toolboxQuery.data.notes ?? "",
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [toolboxQuery.data]);

  const updateMutation = useMutation({
    mutationFn: (values: ToolboxFormValues) =>
      toolboxesApi.update(shopId as string, toolboxId as string, values),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["toolboxes"] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: () => toolboxesApi.remove(shopId as string, toolboxId as string),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["toolboxes"] });
      navigate(`/shops/${shopId}`);
    },
  });

  const drawerForm = useForm<DrawerFormValues>({ resolver: zodResolver(drawerSchema) });
  const createDrawerMutation = useMutation({
    mutationFn: (values: DrawerFormValues) =>
      drawersApi.create(shopId as string, toolboxId as string, {
        ...values,
        row: values.row ? Number(values.row) : undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["drawers", { toolbox_id: toolboxId }] });
      setDrawerDialogOpen(false);
      drawerForm.reset();
    },
  });

  const moveLeftMutation = useMutation({
    mutationFn: (drawerId: string) =>
      drawersApi.moveLeft(shopId as string, toolboxId as string, drawerId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["drawers", { toolbox_id: toolboxId }] });
    },
  });
  const moveRightMutation = useMutation({
    mutationFn: (drawerId: string) =>
      drawersApi.moveRight(shopId as string, toolboxId as string, drawerId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["drawers", { toolbox_id: toolboxId }] });
    },
  });

  const profileNameById = React.useMemo(() => {
    const map = new Map<string, string>();
    (drawerProfilesQuery.data ?? []).forEach((p) => map.set(p.id, p.name));
    return map;
  }, [drawerProfilesQuery.data]);
  const profileById = React.useMemo(() => {
    const map = new Map<string, DrawerProfile>();
    (drawerProfilesQuery.data ?? []).forEach((p) => map.set(p.id, p));
    return map;
  }, [drawerProfilesQuery.data]);

  const { placed: drawersByRow, unplaced: unplacedDrawers } = React.useMemo(
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

  if (toolboxQuery.isLoading) {
    return <p className="p-4 text-sm text-muted-foreground">Loading toolbox…</p>;
  }
  if (toolboxQuery.isError || !toolboxQuery.data) {
    return <p className="p-4 text-sm text-destructive">Toolbox not found.</p>;
  }

  const noProfiles = drawerProfilesQuery.isSuccess && drawerProfilesQuery.data.length === 0;

  return (
    <div className="scrollbar-thin flex h-full flex-col gap-6 overflow-y-auto p-4">
      <section>
        <div className="mb-3 flex items-center justify-between">
          <h1 className="text-base font-semibold">{toolboxQuery.data.name}</h1>
          <Button
            size="sm"
            variant="destructive"
            onClick={() => {
              if (confirm(`Delete toolbox "${toolboxQuery.data?.name}"?`)) {
                deleteMutation.mutate();
              }
            }}
          >
            <Trash2 />
            Delete toolbox
          </Button>
        </div>
        <form
          onSubmit={toolboxForm.handleSubmit((v) => updateMutation.mutate(v))}
          className="grid max-w-lg grid-cols-2 gap-3"
        >
          <div className="flex flex-col gap-1">
            <Label htmlFor="name">Name</Label>
            <Input id="name" {...toolboxForm.register("name")} />
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="kind">Kind</Label>
            <Input id="kind" {...toolboxForm.register("kind")} />
          </div>
          <div className="col-span-2 flex flex-col gap-1">
            <Label htmlFor="notes">Notes</Label>
            <Input id="notes" {...toolboxForm.register("notes")} />
          </div>
          <div className="col-span-2">
            <Button type="submit" size="sm" disabled={updateMutation.isPending}>
              {updateMutation.isPending ? "Saving…" : "Save changes"}
            </Button>
          </div>
        </form>
      </section>

      <section>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold">Drawers</h2>
          <FormDialog
            open={drawerDialogOpen}
            onOpenChange={setDrawerDialogOpen}
            trigger={
              <Button size="sm" variant="outline" disabled={noProfiles}>
                <Plus />
                New drawer
              </Button>
            }
            title="New drawer"
            description={
              noProfiles
                ? "Create a drawer profile first (Profiles → Drawer Profiles)."
                : undefined
            }
            formId="create-drawer"
            submitting={createDrawerMutation.isPending}
          >
            <form
              id="create-drawer"
              onSubmit={drawerForm.handleSubmit((v) => createDrawerMutation.mutate(v))}
              className="flex flex-col gap-3"
            >
              <div className="flex flex-col gap-1">
                <Label htmlFor="dr-profile">Drawer profile</Label>
                <SearchableSelect
                  id="dr-profile"
                  placeholder="Select a profile…"
                  searchPlaceholder="Search profiles…"
                  value={drawerForm.watch("drawer_profile_id")}
                  onValueChange={(v) => drawerForm.setValue("drawer_profile_id", v)}
                  options={(drawerProfilesQuery.data ?? []).map((p) => ({
                    value: p.id,
                    label: `${p.name} (${p.inside_width_mm}×${p.inside_depth_mm}×${p.inside_height_mm}mm)`,
                  }))}
                />
              </div>
              <div className="flex flex-col gap-1">
                <Label htmlFor="dr-name">Name</Label>
                <Input id="dr-name" {...drawerForm.register("name")} />
              </div>
              <div className="flex flex-col gap-1">
                <Label htmlFor="dr-position">Position label</Label>
                <Input
                  id="dr-position"
                  placeholder="top-left"
                  {...drawerForm.register("position_label")}
                />
              </div>
              <div className="flex flex-col gap-1">
                <Label htmlFor="dr-row">Row</Label>
                <Input
                  id="dr-row"
                  type="number"
                  placeholder="1"
                  {...drawerForm.register("row")}
                />
                <p className="text-xs text-muted-foreground">
                  Which physical row this drawer sits in (top = 1). Leave blank to skip
                  the visual layout for now. Skip a number (e.g. 1, 2, 3, 5) to mark a
                  stack/section break for stackable toolboxes.
                </p>
              </div>
              <div className="flex flex-col gap-1">
                <Label htmlFor="dr-notes">Notes</Label>
                <Input id="dr-notes" {...drawerForm.register("notes")} />
              </div>
            </form>
          </FormDialog>
        </div>

        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Position</TableHead>
              <TableHead>Profile</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(drawersQuery.data ?? []).map((drawer) => (
              <TableRow key={drawer.id}>
                <TableCell>
                  <Link
                    to={`/shops/${shopId}/toolboxes/${toolboxId}/drawers/${drawer.id}`}
                    className="font-medium hover:underline"
                  >
                    {drawer.name || "Untitled drawer"}
                  </Link>
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {drawer.position_label || "—"}
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {profileNameById.get(drawer.drawer_profile_id) ?? "—"}
                </TableCell>
              </TableRow>
            ))}
            {drawersQuery.isSuccess && drawersQuery.data.length === 0 && (
              <TableRow>
                <TableCell colSpan={3} className="py-6 text-center text-muted-foreground">
                  No drawers yet.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </section>

      <section>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold">Layout</h2>
          {toolboxLayout.rows.length > 0 && (
            <Button size="sm" variant="outline" asChild>
              <Link to={`/shops/${shopId}/toolboxes/${toolboxId}/print`} target="_blank">
                <Printer />
                Print inventory sheet
              </Link>
            </Button>
          )}
        </div>

        {toolboxLayout.rows.length === 0 ? (
          <p className="text-xs text-muted-foreground">
            No drawers have a Row assigned yet. Set a Row when creating or editing a drawer
            to see it here.
          </p>
        ) : (
          <div className="flex flex-col gap-4 lg:flex-row">
            <div className="overflow-auto rounded-md border border-border bg-muted/20 p-2">
              <svg
                width={toolboxLayout.canvasWidthPx}
                height={toolboxLayout.canvasHeightPx}
                viewBox={`0 0 ${toolboxLayout.canvasWidthPx} ${toolboxLayout.canvasHeightPx}`}
                className="block"
                role="img"
                aria-label="Toolbox layout"
              >
                <rect
                  x={0}
                  y={0}
                  width={toolboxLayout.canvasWidthPx}
                  height={toolboxLayout.canvasHeightPx}
                  fill="none"
                  stroke="currentColor"
                  className="text-border"
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
                      fill="currentColor"
                      className="text-muted-foreground/20"
                    />
                  ))}
                {toolboxLayout.rows
                  .flatMap((rowLayout) =>
                    rowLayout.drawers.map((placed) => ({ rowLayout, placed })),
                  )
                  .map(({ rowLayout, placed }, i) => {
                    const drawer = drawerById.get(placed.id);
                    const label = drawer?.name || drawer?.position_label || "Drawer";
                    const target = `/shops/${shopId}/toolboxes/${toolboxId}/drawers/${placed.id}`;
                    return (
                      <g
                        key={placed.id}
                        role="link"
                        tabIndex={0}
                        aria-label={label}
                        className="cursor-pointer"
                        onClick={() => navigate(target)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" || e.key === " ") navigate(target);
                        }}
                      >
                        <rect
                          x={placed.xPx}
                          y={rowLayout.yPx}
                          width={placed.widthPx}
                          height={rowLayout.heightPx}
                          fill={colorForIndex(i)}
                          stroke="currentColor"
                          className="text-foreground/50"
                          strokeWidth={1}
                        />
                        <text
                          x={placed.xPx + 4}
                          y={rowLayout.yPx + 13}
                          fontSize={10}
                          className="fill-foreground"
                        >
                          {label}
                        </text>
                      </g>
                    );
                  })}
              </svg>
            </div>

            <div className="min-w-[220px] flex-1">
              <h3 className="mb-1 text-xs font-semibold">Rows</h3>
              <ul className="flex flex-col gap-2">
                {toolboxLayout.rows.map((rowLayout) => {
                  const rowDrawers = (drawersByRow.get(rowLayout.row) ?? [])
                    .slice()
                    .sort((a, b) => (a.order_in_row ?? 0) - (b.order_in_row ?? 0));
                  return (
                    <li
                      key={rowLayout.row}
                      className="rounded-sm border border-border bg-muted/20 px-2 py-1.5 text-xs"
                    >
                      <div className="mb-1 font-medium text-muted-foreground">
                        Row {rowLayout.row}
                      </div>
                      <div className="flex flex-col gap-1">
                        {rowDrawers.map((drawer, i) => (
                          <div key={drawer.id} className="flex items-center justify-between gap-2">
                            <Link
                              to={`/shops/${shopId}/toolboxes/${toolboxId}/drawers/${drawer.id}`}
                              className="hover:underline"
                            >
                              {drawer.name || drawer.position_label || "Drawer"}
                            </Link>
                            <div className="flex items-center gap-1">
                              <button
                                type="button"
                                className="flex h-4 w-4 items-center justify-center text-muted-foreground hover:text-foreground disabled:opacity-30"
                                disabled={i === 0 || moveLeftMutation.isPending}
                                onClick={() => moveLeftMutation.mutate(drawer.id)}
                                title="Move left"
                              >
                                <ChevronLeft className="h-3.5 w-3.5" />
                              </button>
                              <button
                                type="button"
                                className="flex h-4 w-4 items-center justify-center text-muted-foreground hover:text-foreground disabled:opacity-30"
                                disabled={i === rowDrawers.length - 1 || moveRightMutation.isPending}
                                onClick={() => moveRightMutation.mutate(drawer.id)}
                                title="Move right"
                              >
                                <ChevronRight className="h-3.5 w-3.5" />
                              </button>
                            </div>
                          </div>
                        ))}
                      </div>
                    </li>
                  );
                })}
              </ul>
            </div>
          </div>
        )}

        {/* Always visible, not just when non-empty -- same reasoning as
            DrawerDetail.tsx's "Unplaced" section: a permanent, hard-to-miss
            spot rather than a banner that's easy to scroll past. */}
        <div className="mt-3">
          <h3 className="mb-1 text-xs font-semibold">
            Not yet placed ({unplacedDrawers.length})
          </h3>
          {unplacedDrawers.length === 0 ? (
            <p className="rounded-sm border border-border bg-muted/20 px-2 py-1.5 text-xs text-muted-foreground">
              Every drawer has a Row assigned.
            </p>
          ) : (
            <ul className="flex flex-col gap-1">
              {unplacedDrawers.map((drawer) => (
                <li
                  key={drawer.id}
                  className="rounded-sm border border-border bg-muted/20 px-2 py-1.5 text-xs"
                >
                  <Link
                    to={`/shops/${shopId}/toolboxes/${toolboxId}/drawers/${drawer.id}`}
                    className="font-medium hover:underline"
                  >
                    {drawer.name || drawer.position_label || "Untitled drawer"}
                  </Link>
                  <span className="text-muted-foreground">
                    {" "}
                    — set a Row to include it in the layout.
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>
    </div>
  );
}
