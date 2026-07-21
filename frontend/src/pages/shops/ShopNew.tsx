import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { useNavigate } from "react-router-dom";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { shopsApi } from "@/lib/api";

const schema = z.object({
  name: z.string().min(1, "Required"),
  slug: z.string().min(1, "Required"),
  location: z.string().optional(),
});
type FormValues = z.infer<typeof schema>;

export function ShopNew() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { register, handleSubmit, formState } = useForm<FormValues>({
    resolver: zodResolver(schema),
  });

  const createMutation = useMutation({
    mutationFn: (values: FormValues) => shopsApi.create(values),
    onSuccess: (shop) => {
      queryClient.invalidateQueries({ queryKey: ["shops"] });
      navigate(`/shops/${shop.id}`);
    },
  });

  return (
    <div className="p-4">
      <h1 className="mb-3 text-base font-semibold">New shop</h1>
      <form
        onSubmit={handleSubmit((v) => createMutation.mutate(v))}
        className="flex max-w-md flex-col gap-3"
      >
        <div className="flex flex-col gap-1">
          <Label htmlFor="name">Name</Label>
          <Input id="name" {...register("name")} />
        </div>
        <div className="flex flex-col gap-1">
          <Label htmlFor="slug">Slug</Label>
          <Input id="slug" placeholder="main-garage" {...register("slug")} />
        </div>
        <div className="flex flex-col gap-1">
          <Label htmlFor="location">Location</Label>
          <Input id="location" {...register("location")} />
        </div>
        {(formState.errors.name || formState.errors.slug) && (
          <p className="text-xs text-destructive">Name and slug are required.</p>
        )}
        <Button type="submit" size="sm" disabled={createMutation.isPending}>
          {createMutation.isPending ? "Creating…" : "Create shop"}
        </Button>
      </form>
    </div>
  );
}
