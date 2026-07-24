import * as React from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useForm } from "react-hook-form";
import { Link } from "react-router-dom";
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
import { shopsApi } from "@/lib/api";

const schema = z.object({
  name: z.string().min(1, "Required"),
  slug: z.string().min(1, "Required"),
  location: z.string().optional(),
});
type FormValues = z.infer<typeof schema>;

// Lowercase, hyphen-separated, no leading/trailing/duplicate hyphens --
// mirrors the shape of the existing "main-garage" placeholder. Backend only
// enforces length (see DrawerCreate/ToolboxCreate schemas' pattern), no
// format constraint, so this is purely a client-side UX default.
function slugify(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

export function ShopsIndex() {
  const queryClient = useQueryClient();
  const [open, setOpen] = React.useState(false);
  const [slugTouched, setSlugTouched] = React.useState(false);
  const shopsQuery = useQuery({ queryKey: ["shops"], queryFn: () => shopsApi.list() });

  const { register, handleSubmit, reset, formState, watch, setValue } = useForm<FormValues>({
    resolver: zodResolver(schema),
  });
  const slugField = register("slug");
  const nameValue = watch("name");

  // Auto-derives the slug from the name as the user types, until they
  // manually edit the slug field themselves -- then their edit wins and
  // further name changes stop overwriting it.
  React.useEffect(() => {
    if (!slugTouched) {
      setValue("slug", slugify(nameValue ?? ""), { shouldValidate: true });
    }
  }, [nameValue, slugTouched, setValue]);

  const createMutation = useMutation({
    mutationFn: (values: FormValues) => shopsApi.create(values),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["shops"] });
      setOpen(false);
      setSlugTouched(false);
      reset();
    },
  });

  return (
    <div className="p-4">
      <div className="mb-3 flex items-center justify-between">
        <div>
          <h1 className="text-base font-semibold">Shops</h1>
          <p className="text-xs text-muted-foreground">
            Physical locations that contain toolboxes and drawers.
          </p>
        </div>
        <FormDialog
          open={open}
          onOpenChange={setOpen}
          trigger={
            <Button size="sm">
              <Plus />
              New shop
            </Button>
          }
          title="New shop"
          formId="create-shop"
          submitting={createMutation.isPending}
        >
          <form
            id="create-shop"
            onSubmit={handleSubmit((v) => createMutation.mutate(v))}
            className="flex flex-col gap-3"
          >
            <div className="flex flex-col gap-1">
              <Label htmlFor="name">Name</Label>
              <Input id="name" {...register("name")} />
            </div>
            <div className="flex flex-col gap-1">
              <Label htmlFor="slug">Slug</Label>
              <Input
                id="slug"
                placeholder="main-garage"
                {...slugField}
                onChange={(e) => {
                  setSlugTouched(true);
                  slugField.onChange(e);
                }}
              />
            </div>
            <div className="flex flex-col gap-1">
              <Label htmlFor="location">Location</Label>
              <Input id="location" {...register("location")} />
            </div>
            {formState.errors.name || formState.errors.slug ? (
              <p className="text-xs text-destructive">Name and slug are required.</p>
            ) : null}
          </form>
        </FormDialog>
      </div>

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Name</TableHead>
            <TableHead>Slug</TableHead>
            <TableHead>Location</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {(shopsQuery.data ?? []).map((shop) => (
            <TableRow key={shop.id}>
              <TableCell>
                <Link to={`/shops/${shop.id}`} className="font-medium hover:underline">
                  {shop.name}
                </Link>
              </TableCell>
              <TableCell className="font-mono text-xs text-muted-foreground">
                {shop.slug}
              </TableCell>
              <TableCell className="text-muted-foreground">
                {shop.location || "—"}
              </TableCell>
            </TableRow>
          ))}
          {shopsQuery.isSuccess && shopsQuery.data.length === 0 && (
            <TableRow>
              <TableCell colSpan={3} className="py-6 text-center text-muted-foreground">
                No shops yet. Create your first one above.
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
    </div>
  );
}
