import * as React from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { Link, useParams } from "react-router-dom";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { fetchToolPhoto, toolsApi } from "@/lib/api";

const toolSchema = z.object({
  name: z.string().min(1, "Required"),
  category: z.string().optional(),
  manufacturer: z.string().optional(),
  sku: z.string().optional(),
  notes: z.string().optional(),
  quantity: z.coerce.number().int().min(1).default(1),
  // Same "" -> undefined preprocess as ToolsPage.tsx's create form, so an
  // empty field stays genuinely optional instead of coercing to 0 and
  // failing `.min(1)`.
  maintenance_interval_days: z.preprocess(
    (val) => (val === "" ? undefined : val),
    z.coerce.number().int().min(1).optional(),
  ),
});
type ToolFormValues = z.infer<typeof toolSchema>;

/**
 * Also the QR-code-on-labels deep-link target (`{app_public_url}/tools/{id}`,
 * see `backend/app/routers/designs.py::create_design`) -- the read-only
 * photo + location breadcrumb below stay as-is for that use case. Drawer/
 * insert reassignment is deliberately left off this form -- that already
 * has a working control on `ToolsPage.tsx`'s table row, and duplicating it
 * here would just create two places to update the same field.
 */
export function ToolDetail() {
  const { toolId } = useParams();
  const queryClient = useQueryClient();

  const toolQuery = useQuery({
    queryKey: ["tools", toolId],
    queryFn: () => toolsApi.get(toolId as string),
    enabled: !!toolId,
  });
  const tool = toolQuery.data;

  const photoQuery = useQuery({
    queryKey: ["tool-photo", toolId],
    queryFn: () => fetchToolPhoto(toolId as string),
    enabled: !!toolId && !!tool?.has_photo,
  });
  const photoUrl = React.useMemo(
    () => (photoQuery.data ? URL.createObjectURL(photoQuery.data) : null),
    [photoQuery.data],
  );
  React.useEffect(() => {
    return () => {
      if (photoUrl) URL.revokeObjectURL(photoUrl);
    };
  }, [photoUrl]);

  const form = useForm<ToolFormValues>({ resolver: zodResolver(toolSchema) });
  React.useEffect(() => {
    if (tool) {
      form.reset({
        name: tool.name,
        category: tool.category ?? "",
        manufacturer: tool.manufacturer ?? "",
        sku: tool.sku ?? "",
        notes: tool.notes ?? "",
        quantity: tool.quantity,
        maintenance_interval_days: tool.maintenance_interval_days ?? undefined,
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tool]);

  const updateMutation = useMutation({
    mutationFn: (values: ToolFormValues) =>
      toolsApi.update(toolId as string, {
        ...values,
        maintenance_interval_days: values.maintenance_interval_days ?? null,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["tools"] });
    },
  });

  if (toolQuery.isLoading) {
    return <p className="p-4 text-sm text-muted-foreground">Loading tool…</p>;
  }
  if (toolQuery.isError || !tool) {
    return <p className="p-4 text-sm text-destructive">Tool not found.</p>;
  }

  return (
    <div className="flex h-full flex-col gap-6 overflow-auto scrollbar-thin p-4">
      <section>
        <div className="mb-3">
          <h1 className="text-base font-semibold">{tool.name}</h1>
          <p className="text-xs text-muted-foreground">
            {tool.location ? (
              <Link
                to={`/shops/${tool.location.shop_id}/toolboxes/${tool.location.toolbox_id}/drawers/${tool.location.drawer_id}`}
                className="text-primary hover:underline"
              >
                {tool.location.shop_name} / {tool.location.toolbox_name} / {tool.location.drawer_label}
              </Link>
            ) : (
              "Unassigned"
            )}
          </p>
        </div>

        {photoUrl && (
          <img
            src={photoUrl}
            alt={tool.name}
            className="mb-3 h-48 w-48 rounded-md border border-border object-cover"
          />
        )}

        <form
          onSubmit={form.handleSubmit((v) => updateMutation.mutate(v))}
          className="grid max-w-lg grid-cols-2 gap-3"
        >
          <div className="col-span-2 flex flex-col gap-1">
            <Label htmlFor="name">Name</Label>
            <Input id="name" {...form.register("name")} />
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="category">Category</Label>
            <Input id="category" {...form.register("category")} />
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="manufacturer">Manufacturer</Label>
            <Input id="manufacturer" {...form.register("manufacturer")} />
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="sku">SKU</Label>
            <Input id="sku" {...form.register("sku")} />
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="quantity">Quantity</Label>
            <Input id="quantity" type="number" min={1} {...form.register("quantity")} />
          </div>
          <div className="col-span-2 flex flex-col gap-1">
            <Label htmlFor="maintenance-interval">Maintenance interval (days, optional)</Label>
            <Input
              id="maintenance-interval"
              type="number"
              min={1}
              placeholder="e.g. 90"
              {...form.register("maintenance_interval_days")}
            />
          </div>
          <div className="col-span-2 flex flex-col gap-1">
            <Label htmlFor="notes">Notes</Label>
            <Input id="notes" {...form.register("notes")} />
          </div>
          <div className="col-span-2">
            <Button type="submit" size="sm" disabled={updateMutation.isPending}>
              {updateMutation.isPending ? "Saving…" : "Save changes"}
            </Button>
          </div>
        </form>
      </section>
    </div>
  );
}
