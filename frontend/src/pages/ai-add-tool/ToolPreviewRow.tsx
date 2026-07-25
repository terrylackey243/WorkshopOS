import { forwardRef, useImperativeHandle } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { z } from "zod";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { NumberField, TextField } from "@/pages/profiles/fields";
import type { AiToolExtractedRow } from "@/lib/types";
import type { DrawerOption } from "@/lib/api";

const toolPreviewSchema = z.object({
  name: z.string().min(1, "Required"),
  category: z.string().optional(),
  manufacturer: z.string().optional(),
  notes: z.string().optional(),
  quantity: z.coerce.number().int().min(1).default(1),
  drawer_id: z.string().optional(),
});
type ToolPreviewValues = z.infer<typeof toolPreviewSchema>;

export interface PreviewRowHandle {
  getValidatedValues: () => Promise<ToolPreviewValues | null>;
}

interface ToolPreviewRowProps {
  row: AiToolExtractedRow;
  drawerOptions: DrawerOption[];
  defaultDrawerId?: string;
  onRemove: () => void;
}

// 0-100, self-reported by the model -- a UI hint only, never a gate. Every
// row stays fully editable regardless of color (see the design discussion
// this implements: the user always has final say).
function confidenceColorClass(confidence: number): string {
  if (confidence >= 85) return "text-emerald-600 dark:text-emerald-400";
  if (confidence >= 60) return "text-amber-600 dark:text-amber-400";
  return "text-destructive";
}

export const ToolPreviewRow = forwardRef<PreviewRowHandle, ToolPreviewRowProps>(
  function ToolPreviewRow({ row, drawerOptions, defaultDrawerId, onRemove }, ref) {
    const form = useForm<ToolPreviewValues>({
      resolver: zodResolver(toolPreviewSchema),
      defaultValues: {
        name: row.name ?? "",
        category: row.category ?? "",
        manufacturer: row.manufacturer ?? "",
        notes: row.notes ?? "",
        quantity: row.quantity || 1,
        drawer_id: defaultDrawerId,
      },
    });

    useImperativeHandle(ref, () => ({
      getValidatedValues: async () => {
        const valid = await form.trigger();
        return valid ? form.getValues() : null;
      },
    }));

    const name = form.watch("name");
    const nameMissing = !name || !name.trim();

    return (
      <div className="flex flex-col gap-2 rounded-sm border border-border p-3">
        <div className="flex items-start justify-between gap-2">
          <div className="max-w-xs flex-1">
            <TextField form={form} name="name" label="Name" />
            {nameMissing && <p className="mt-1 text-xs text-destructive">Name required</p>}
          </div>
          <span
            className={`mt-5 shrink-0 text-xs font-medium ${confidenceColorClass(row.confidence)}`}
            title="AI-reported confidence -- always editable, this is just a cue to look closer."
          >
            {row.confidence}% confidence
          </span>
          <button
            type="button"
            onClick={onRemove}
            className="mt-5 shrink-0 text-xs text-muted-foreground hover:text-destructive"
          >
            Remove
          </button>
        </div>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <TextField form={form} name="category" label="Category" />
          <TextField form={form} name="manufacturer" label="Manufacturer" />
          <TextField form={form} name="notes" label="Notes" />
          <NumberField form={form} name="quantity" label="Quantity" step="1" />
        </div>
        <div className="max-w-xs">
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-sm font-medium leading-none">Drawer</span>
            <Select
              value={form.watch("drawer_id") ?? "__unassigned__"}
              onValueChange={(v) =>
                form.setValue("drawer_id", v === "__unassigned__" ? undefined : v)
              }
            >
              <SelectTrigger>
                <SelectValue placeholder="Unassigned" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="__unassigned__">Unassigned</SelectItem>
                {drawerOptions.map((d) => (
                  <SelectItem key={d.id} value={d.id}>
                    {d.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </label>
        </div>
      </div>
    );
  },
);
