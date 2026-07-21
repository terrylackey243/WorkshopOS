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
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { shopsApi, toolboxesApi } from "@/lib/api";

const shopSchema = z.object({
  name: z.string().min(1, "Required"),
  slug: z.string().min(1, "Required"),
  location: z.string().optional(),
});
type ShopFormValues = z.infer<typeof shopSchema>;

const toolboxSchema = z.object({
  name: z.string().min(1, "Required"),
  kind: z.string().optional(),
  notes: z.string().optional(),
});
type ToolboxFormValues = z.infer<typeof toolboxSchema>;

export function ShopDetail() {
  const { shopId } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [toolboxDialogOpen, setToolboxDialogOpen] = React.useState(false);

  const shopQuery = useQuery({
    queryKey: ["shops", shopId],
    queryFn: () => shopsApi.get(shopId as string),
    enabled: !!shopId,
  });
  const toolboxesQuery = useQuery({
    queryKey: ["toolboxes", { shop_id: shopId }],
    queryFn: () => toolboxesApi.list(shopId as string),
    enabled: !!shopId,
  });

  const shopForm = useForm<ShopFormValues>({ resolver: zodResolver(shopSchema) });
  React.useEffect(() => {
    if (shopQuery.data) {
      shopForm.reset({
        name: shopQuery.data.name,
        slug: shopQuery.data.slug,
        location: shopQuery.data.location ?? "",
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shopQuery.data]);

  const updateMutation = useMutation({
    mutationFn: (values: ShopFormValues) => shopsApi.update(shopId as string, values),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["shops"] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: () => shopsApi.remove(shopId as string),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["shops"] });
      navigate("/shops");
    },
  });

  const toolboxForm = useForm<ToolboxFormValues>({ resolver: zodResolver(toolboxSchema) });
  const createToolboxMutation = useMutation({
    mutationFn: (values: ToolboxFormValues) =>
      toolboxesApi.create(shopId as string, values),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["toolboxes", { shop_id: shopId }] });
      setToolboxDialogOpen(false);
      toolboxForm.reset();
    },
  });

  if (shopQuery.isLoading) {
    return <p className="p-4 text-sm text-muted-foreground">Loading shop…</p>;
  }
  if (shopQuery.isError || !shopQuery.data) {
    return <p className="p-4 text-sm text-destructive">Shop not found.</p>;
  }

  return (
    <div className="flex flex-col gap-6 p-4">
      <section>
        <div className="mb-3 flex items-center justify-between">
          <h1 className="text-base font-semibold">{shopQuery.data.name}</h1>
          <Button
            size="sm"
            variant="destructive"
            onClick={() => {
              if (confirm(`Delete shop "${shopQuery.data?.name}"? This cannot be undone.`)) {
                deleteMutation.mutate();
              }
            }}
          >
            <Trash2 />
            Delete shop
          </Button>
        </div>
        <form
          onSubmit={shopForm.handleSubmit((v) => updateMutation.mutate(v))}
          className="grid max-w-lg grid-cols-2 gap-3"
        >
          <div className="flex flex-col gap-1">
            <Label htmlFor="name">Name</Label>
            <Input id="name" {...shopForm.register("name")} />
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="slug">Slug</Label>
            <Input id="slug" {...shopForm.register("slug")} />
          </div>
          <div className="col-span-2 flex flex-col gap-1">
            <Label htmlFor="location">Location</Label>
            <Input id="location" {...shopForm.register("location")} />
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
          <h2 className="text-sm font-semibold">Toolboxes</h2>
          <FormDialog
            open={toolboxDialogOpen}
            onOpenChange={setToolboxDialogOpen}
            trigger={
              <Button size="sm" variant="outline">
                <Plus />
                New toolbox
              </Button>
            }
            title="New toolbox"
            formId="create-toolbox"
            submitting={createToolboxMutation.isPending}
          >
            <form
              id="create-toolbox"
              onSubmit={toolboxForm.handleSubmit((v) => createToolboxMutation.mutate(v))}
              className="flex flex-col gap-3"
            >
              <div className="flex flex-col gap-1">
                <Label htmlFor="tb-name">Name</Label>
                <Input id="tb-name" {...toolboxForm.register("name")} />
              </div>
              <div className="flex flex-col gap-1">
                <Label htmlFor="tb-kind">Kind</Label>
                <Input id="tb-kind" placeholder="rolling cart, wall cabinet…" {...toolboxForm.register("kind")} />
              </div>
              <div className="flex flex-col gap-1">
                <Label htmlFor="tb-notes">Notes</Label>
                <Input id="tb-notes" {...toolboxForm.register("notes")} />
              </div>
            </form>
          </FormDialog>
        </div>

        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Kind</TableHead>
              <TableHead>Notes</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(toolboxesQuery.data ?? []).map((toolbox) => (
              <TableRow key={toolbox.id}>
                <TableCell>
                  <Link
                    to={`/shops/${shopId}/toolboxes/${toolbox.id}`}
                    className="font-medium hover:underline"
                  >
                    {toolbox.name}
                  </Link>
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {toolbox.kind || "—"}
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {toolbox.notes || "—"}
                </TableCell>
              </TableRow>
            ))}
            {toolboxesQuery.isSuccess && toolboxesQuery.data.length === 0 && (
              <TableRow>
                <TableCell colSpan={3} className="py-6 text-center text-muted-foreground">
                  No toolboxes yet.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </section>
    </div>
  );
}
