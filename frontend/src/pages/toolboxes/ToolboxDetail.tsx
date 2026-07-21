import * as React from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { useForm } from "react-hook-form";
import { Link, useNavigate, useParams } from "react-router-dom";
import { z } from "zod";

import { FormDialog } from "@/components/FormDialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { drawerProfilesApi, drawersApi, toolboxesApi } from "@/lib/api";

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
      drawersApi.create(shopId as string, toolboxId as string, values),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["drawers", { toolbox_id: toolboxId }] });
      setDrawerDialogOpen(false);
      drawerForm.reset();
    },
  });

  const profileNameById = React.useMemo(() => {
    const map = new Map<string, string>();
    (drawerProfilesQuery.data ?? []).forEach((p) => map.set(p.id, p.name));
    return map;
  }, [drawerProfilesQuery.data]);

  if (toolboxQuery.isLoading) {
    return <p className="p-4 text-sm text-muted-foreground">Loading toolbox…</p>;
  }
  if (toolboxQuery.isError || !toolboxQuery.data) {
    return <p className="p-4 text-sm text-destructive">Toolbox not found.</p>;
  }

  const noProfiles = drawerProfilesQuery.isSuccess && drawerProfilesQuery.data.length === 0;

  return (
    <div className="flex flex-col gap-6 p-4">
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
                <Select
                  onValueChange={(v) => drawerForm.setValue("drawer_profile_id", v)}
                >
                  <SelectTrigger id="dr-profile">
                    <SelectValue placeholder="Select a profile…" />
                  </SelectTrigger>
                  <SelectContent>
                    {(drawerProfilesQuery.data ?? []).map((p) => (
                      <SelectItem key={p.id} value={p.id}>
                        {p.name} ({p.inside_width_mm}×{p.inside_depth_mm}×
                        {p.inside_height_mm}mm)
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
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
    </div>
  );
}
