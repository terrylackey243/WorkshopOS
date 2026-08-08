import { useQuery } from "@tanstack/react-query";
import type { UseFormReturn } from "react-hook-form";
import { z } from "zod";

import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { labelStyleProfilesApi, magnetProfilesApi, shopsApi, toolsApi } from "@/lib/api";

export const designSchema = z.object({
  name: z.string().min(1, "Required"),
  text: z.string().min(1, "Required"),
  label_style_profile_id: z.string().min(1, "Choose a label style"),
  magnet_profile_id: z.string().optional(),
  shop_id: z.string().optional(),
  tool_id: z.string().optional(),
});
export type DesignFormValues = z.infer<typeof designSchema>;

/**
 * Label style / magnet profile / shop / tool selects shared between the
 * "New design" form (DesignsList) and the "Edit design" form (DesignDetail)
 * -- both submit the same field shape to the backend, which re-derives
 * `parameters_json` and re-enqueues generation from whatever these resolve
 * to.
 */
export function DesignLinkFields({ form }: { form: UseFormReturn<DesignFormValues> }) {
  const labelStylesQuery = useQuery({
    queryKey: ["profiles-label-styles"],
    queryFn: () => labelStyleProfilesApi.list(),
  });
  const magnetProfilesQuery = useQuery({
    queryKey: ["profiles-magnets"],
    queryFn: () => magnetProfilesApi.list(),
  });
  const shopsQuery = useQuery({ queryKey: ["shops"], queryFn: () => shopsApi.list() });
  const toolsQuery = useQuery({ queryKey: ["tools"], queryFn: () => toolsApi.list() });

  const selectedLabelStyle = (labelStylesQuery.data ?? []).find(
    (ls) => ls.id === form.watch("label_style_profile_id"),
  );
  // A label style with magnet_count===0 is adhesive-mount (see ProfilesPage's
  // "Mount type" selector) -- the backend ignores magnet_profile_id entirely
  // in that case (build_label_parameters), so offering the picker here would
  // just be a dead control that silently does nothing.
  const isAdhesive = selectedLabelStyle?.magnet_count === 0;

  return (
    <>
      <div className="flex flex-col gap-1">
        <Label>Label style</Label>
        <Select
          value={form.watch("label_style_profile_id")}
          onValueChange={(v) => form.setValue("label_style_profile_id", v, { shouldValidate: true })}
        >
          <SelectTrigger>
            <SelectValue placeholder="Choose a label style" />
          </SelectTrigger>
          <SelectContent>
            {(labelStylesQuery.data ?? []).map((ls) => (
              <SelectItem key={ls.id} value={ls.id}>
                {ls.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {form.formState.errors.label_style_profile_id && (
          <p className="text-xs text-destructive">
            {form.formState.errors.label_style_profile_id.message}
          </p>
        )}
      </div>
      {isAdhesive ? (
        <p className="text-xs text-muted-foreground">
          This label style is adhesive (no embedded magnets) -- no magnet profile needed.
        </p>
      ) : (
        <div className="flex flex-col gap-1">
          <Label>Magnet profile</Label>
          <Select
            value={form.watch("magnet_profile_id")}
            onValueChange={(v) => form.setValue("magnet_profile_id", v)}
          >
            <SelectTrigger>
              <SelectValue placeholder="Use label style default" />
            </SelectTrigger>
            <SelectContent>
              {(magnetProfilesQuery.data ?? []).map((m) => (
                <SelectItem key={m.id} value={m.id}>
                  {m.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}
      <div className="flex flex-col gap-1">
        <Label>Shop</Label>
        <Select value={form.watch("shop_id")} onValueChange={(v) => form.setValue("shop_id", v)}>
          <SelectTrigger>
            <SelectValue placeholder="None" />
          </SelectTrigger>
          <SelectContent>
            {(shopsQuery.data ?? []).map((shop) => (
              <SelectItem key={shop.id} value={shop.id}>
                {shop.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div className="flex flex-col gap-1">
        <Label>Link to tool (optional)</Label>
        <Select value={form.watch("tool_id")} onValueChange={(v) => form.setValue("tool_id", v)}>
          <SelectTrigger>
            <SelectValue placeholder="No tool linked -- plain label" />
          </SelectTrigger>
          <SelectContent>
            {(toolsQuery.data ?? []).map((tool) => (
              <SelectItem key={tool.id} value={tool.id}>
                {tool.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <p className="text-[11px] text-muted-foreground">
          Adds a scannable QR code that deep-links to the tool's page.
        </p>
      </div>
    </>
  );
}
