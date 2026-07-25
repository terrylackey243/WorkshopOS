import * as React from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import axios from "axios";
import { ChevronDown, ChevronUp, Plus, Trash2 } from "lucide-react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { FormDialog } from "@/components/FormDialog";
import { Badge, type BadgeProps } from "@/components/ui/badge";
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
import { Textarea } from "@/components/ui/textarea";
import { useAuth } from "@/hooks/useAuth";
import { roadmapApi } from "@/lib/api";
import type { RoadmapItem, RoadmapStatus } from "@/lib/types";

const STATUS_VARIANT: Record<RoadmapStatus, BadgeProps["variant"]> = {
  done: "default",
  in_progress: "secondary",
  planned: "outline",
};

const STATUS_LABEL: Record<RoadmapStatus, string> = {
  done: "Done",
  in_progress: "In progress",
  planned: "Planned",
};

const STATUS_OPTIONS: RoadmapStatus[] = ["planned", "in_progress", "done"];

const itemSchema = z.object({
  title: z.string().min(1, "Required"),
  description: z.string().optional(),
  status: z.enum(["planned", "in_progress", "done"]),
});
type ItemFormValues = z.infer<typeof itemSchema>;

/**
 * Product roadmap -- what WorkshopOS has built and what's still ahead.
 * Deliberately not org-scoped (see lib/api.ts's roadmapApi): every
 * authenticated user sees the same shared list, but only a superadmin can
 * add/edit/reorder/delete entries (backend-enforced via
 * deps.require_superadmin -- the controls here are hidden for non-admins
 * purely so they don't see buttons that would just 403, not as the actual
 * gate). Ordering is a plain integer `position`, moved via dedicated
 * move-up/move-down endpoints (atomic server-side swaps) rather than
 * drag-and-drop, which keeps reordering simple and avoids a new drag
 * library dependency for a page that's edited occasionally, not constantly.
 */
export function RoadmapPage() {
  const { isSuperadmin } = useAuth();
  const queryClient = useQueryClient();
  const [open, setOpen] = React.useState(false);
  const [formError, setFormError] = React.useState<string | null>(null);

  const itemsQuery = useQuery({ queryKey: ["roadmap"], queryFn: () => roadmapApi.list() });

  const form = useForm<ItemFormValues>({
    resolver: zodResolver(itemSchema),
    defaultValues: { title: "", description: "", status: "planned" },
  });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["roadmap"] });

  const createMutation = useMutation({
    mutationFn: (values: ItemFormValues) =>
      roadmapApi.create({
        title: values.title,
        description: values.description || undefined,
        status: values.status,
      }),
    onSuccess: () => {
      invalidate();
      setOpen(false);
      setFormError(null);
      form.reset({ title: "", description: "", status: "planned" });
    },
    onError: (error: unknown) => {
      const detail = axios.isAxiosError(error) ? error.response?.data?.detail : undefined;
      setFormError(typeof detail === "string" ? detail : "Failed to add roadmap item. Please try again.");
    },
  });

  const statusMutation = useMutation({
    mutationFn: ({ id, status }: { id: string; status: RoadmapStatus }) =>
      roadmapApi.update(id, { status }),
    onSuccess: invalidate,
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => roadmapApi.remove(id),
    onSuccess: invalidate,
  });

  const moveUpMutation = useMutation({
    mutationFn: (id: string) => roadmapApi.moveUp(id),
    onSuccess: invalidate,
  });

  const moveDownMutation = useMutation({
    mutationFn: (id: string) => roadmapApi.moveDown(id),
    onSuccess: invalidate,
  });

  const items = itemsQuery.data ?? [];
  const doneCount = items.filter((i) => i.status === "done").length;

  return (
    <div className="flex h-full flex-col overflow-auto scrollbar-thin p-4">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="text-base font-semibold">Roadmap</h1>
          <p className="text-xs text-muted-foreground">
            {doneCount} of {items.length} done. Reorder, edit status, or add new items as plans change.
          </p>
        </div>
        {isSuperadmin && (
        <FormDialog
          open={open}
          onOpenChange={(o) => {
            setOpen(o);
            if (!o) setFormError(null);
          }}
          trigger={
            <Button size="sm">
              <Plus />
              Add item
            </Button>
          }
          title="Add roadmap item"
          formId="create-roadmap-item"
          submitting={createMutation.isPending}
        >
          <form
            id="create-roadmap-item"
            onSubmit={form.handleSubmit(
              (v) => {
                setFormError(null);
                createMutation.mutate(v);
              },
              () => setFormError("Check the highlighted fields -- one or more values are invalid."),
            )}
            className="flex flex-col gap-3"
          >
            <div className="flex flex-col gap-1">
              <Label htmlFor="roadmap-title">Title</Label>
              <Input id="roadmap-title" {...form.register("title")} />
            </div>
            <div className="flex flex-col gap-1">
              <Label htmlFor="roadmap-description">Description</Label>
              <Textarea id="roadmap-description" rows={3} {...form.register("description")} />
            </div>
            <div className="flex flex-col gap-1">
              <Label>Status</Label>
              <Select
                value={form.watch("status")}
                onValueChange={(v) => form.setValue("status", v as RoadmapStatus)}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {STATUS_OPTIONS.map((s) => (
                    <SelectItem key={s} value={s}>
                      {STATUS_LABEL[s]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            {formError && (
              <p className="rounded-sm border border-destructive/30 bg-destructive/10 px-2.5 py-1.5 text-xs text-destructive">
                {formError}
              </p>
            )}
          </form>
        </FormDialog>
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        {items.map((item: RoadmapItem, index: number) => (
          <div
            key={item.id}
            className="flex items-start gap-3 rounded-md border border-border bg-card px-3 py-2.5"
          >
            {isSuperadmin && (
            <div className="flex flex-col pt-0.5">
              <button
                type="button"
                className="flex h-4 w-4 items-center justify-center text-muted-foreground hover:text-foreground disabled:opacity-30"
                disabled={index === 0 || moveUpMutation.isPending}
                onClick={() => moveUpMutation.mutate(item.id)}
                title="Move up"
              >
                <ChevronUp className="h-3.5 w-3.5" />
              </button>
              <button
                type="button"
                className="flex h-4 w-4 items-center justify-center text-muted-foreground hover:text-foreground disabled:opacity-30"
                disabled={index === items.length - 1 || moveDownMutation.isPending}
                onClick={() => moveDownMutation.mutate(item.id)}
                title="Move down"
              >
                <ChevronDown className="h-3.5 w-3.5" />
              </button>
            </div>
            )}

            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium">{item.title}</span>
                <Badge variant={STATUS_VARIANT[item.status]}>{STATUS_LABEL[item.status]}</Badge>
              </div>
              {item.description && (
                <p className="mt-0.5 text-xs text-muted-foreground">{item.description}</p>
              )}
            </div>

            {isSuperadmin && (
            <Select
              value={item.status}
              onValueChange={(v) => statusMutation.mutate({ id: item.id, status: v as RoadmapStatus })}
            >
              <SelectTrigger className="h-7 w-32 shrink-0 text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {STATUS_OPTIONS.map((s) => (
                  <SelectItem key={s} value={s}>
                    {STATUS_LABEL[s]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            )}

            {isSuperadmin && (
            <Button
              size="icon"
              variant="ghost"
              className="shrink-0"
              onClick={() => {
                if (confirm(`Delete "${item.title}"?`)) deleteMutation.mutate(item.id);
              }}
            >
              <Trash2 className="h-3.5 w-3.5" />
            </Button>
            )}
          </div>
        ))}
        {itemsQuery.isSuccess && items.length === 0 && (
          <p className="py-8 text-center text-sm text-muted-foreground">
            No roadmap items yet. Add the first one above.
          </p>
        )}
      </div>
    </div>
  );
}
