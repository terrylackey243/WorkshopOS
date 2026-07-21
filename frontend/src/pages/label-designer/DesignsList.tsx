import * as React from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import axios from "axios";
import { Plus } from "lucide-react";
import { useForm } from "react-hook-form";
import { Link, useNavigate, useParams } from "react-router-dom";
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import {
  designsApi,
  labelStyleProfilesApi,
  magnetProfilesApi,
  shopsApi,
  toolsApi,
} from "@/lib/api";
import type { DesignStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

const designSchema = z.object({
  name: z.string().min(1, "Required"),
  text: z.string().min(1, "Required"),
  label_style_profile_id: z.string().min(1, "Choose a label style"),
  magnet_profile_id: z.string().optional(),
  shop_id: z.string().optional(),
  tool_id: z.string().optional(),
});
type DesignFormValues = z.infer<typeof designSchema>;

const STATUS_VARIANT: Record<DesignStatus, BadgeProps["variant"]> = {
  queued: "secondary",
  generated: "default",
  failed: "destructive",
  draft: "outline",
};

const STATUS_LABEL: Record<DesignStatus, string> = {
  queued: "Generating…",
  generated: "Generated",
  failed: "Failed",
  draft: "Draft",
};

function StatusBadge({ status }: { status: DesignStatus }) {
  return <Badge variant={STATUS_VARIANT[status]}>{STATUS_LABEL[status]}</Badge>;
}

/**
 * List panel for the Label Designer section: every design in the active org
 * plus a "New design" dialog. Designs are immutable once created (no edit),
 * so unlike ProfileCrudTab this only ever creates + lists.
 */
export function DesignsList() {
  const { designId: activeDesignId } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [open, setOpen] = React.useState(false);
  const [formError, setFormError] = React.useState<string | null>(null);

  const designsQuery = useQuery({ queryKey: ["designs"], queryFn: () => designsApi.list() });
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

  const form = useForm<DesignFormValues>({
    resolver: zodResolver(designSchema),
    defaultValues: { name: "", text: "", label_style_profile_id: "" },
  });

  const createMutation = useMutation({
    mutationFn: (values: DesignFormValues) =>
      designsApi.create({
        name: values.name,
        text: values.text,
        label_style_profile_id: values.label_style_profile_id,
        magnet_profile_id: values.magnet_profile_id || undefined,
        shop_id: values.shop_id || undefined,
        tool_id: values.tool_id || undefined,
      }),
    onSuccess: (design) => {
      queryClient.invalidateQueries({ queryKey: ["designs"] });
      setOpen(false);
      setFormError(null);
      form.reset({ name: "", text: "", label_style_profile_id: "" });
      navigate(`/label-designer/${design.id}`);
    },
    onError: (error: unknown) => {
      // The create-design endpoint is the one place in the app that returns
      // structured 422s from user input (bad magnet/label geometry
      // combinations) -- surface `detail` verbatim instead of a generic
      // "something went wrong" message.
      if (axios.isAxiosError(error) && error.response?.status === 422) {
        const detail = error.response.data?.detail;
        setFormError(typeof detail === "string" ? detail : "Invalid design parameters.");
      } else {
        setFormError("Failed to create design. Please try again.");
      }
    },
  });

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-border px-3 py-2">
        <div>
          <h1 className="text-sm font-semibold">Label Designer</h1>
          <p className="text-xs text-muted-foreground">
            {(designsQuery.data ?? []).length} design
            {(designsQuery.data ?? []).length === 1 ? "" : "s"}
          </p>
        </div>
        <FormDialog
          open={open}
          onOpenChange={(o) => {
            setOpen(o);
            if (!o) setFormError(null);
          }}
          trigger={
            <Button size="sm">
              <Plus />
              New design
            </Button>
          }
          title="New design"
          description="Generates a two-body (outline + text) STL pair off a Label Style and Magnet profile."
          formId="create-design"
          submitting={createMutation.isPending}
        >
          <form
            id="create-design"
            onSubmit={form.handleSubmit((v) => {
              setFormError(null);
              createMutation.mutate(v);
            })}
            className="flex flex-col gap-3"
          >
            <div className="flex flex-col gap-1">
              <Label htmlFor="design-name">Name</Label>
              <Input id="design-name" {...form.register("name")} />
            </div>
            <div className="flex flex-col gap-1">
              <Label htmlFor="design-text">Text</Label>
              <Textarea id="design-text" placeholder="WRENCHES" {...form.register("text")} />
            </div>
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
            <div className="flex flex-col gap-1">
              <Label>Shop</Label>
              <Select
                value={form.watch("shop_id")}
                onValueChange={(v) => form.setValue("shop_id", v)}
              >
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
              <Select
                value={form.watch("tool_id")}
                onValueChange={(v) => form.setValue("tool_id", v)}
              >
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
            {formError && (
              <p className="rounded-sm border border-destructive/30 bg-destructive/10 px-2.5 py-1.5 text-xs text-destructive">
                {formError}
              </p>
            )}
          </form>
        </FormDialog>
      </div>

      <div className="flex-1 overflow-auto scrollbar-thin">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Text</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Created</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(designsQuery.data ?? []).map((design) => (
              <TableRow
                key={design.id}
                className={cn(activeDesignId === design.id && "bg-accent")}
              >
                <TableCell>
                  <Link
                    to={`/label-designer/${design.id}`}
                    className="font-medium hover:underline"
                  >
                    {design.name}
                  </Link>
                </TableCell>
                <TableCell className="max-w-[10rem] truncate text-muted-foreground">
                  {design.text}
                </TableCell>
                <TableCell>
                  <StatusBadge status={design.status} />
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {new Date(design.created_at).toLocaleDateString()}
                </TableCell>
              </TableRow>
            ))}
            {designsQuery.isSuccess && designsQuery.data.length === 0 && (
              <TableRow>
                <TableCell colSpan={4} className="py-6 text-center text-muted-foreground">
                  No designs yet. Create your first one above.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
