import * as React from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import axios from "axios";
import { ArrowUpDown, Camera, Plus, Search, Trash2, Upload, X } from "lucide-react";
import { useForm } from "react-hook-form";
import { Link } from "react-router-dom";
import { z } from "zod";

import { FormDialog } from "@/components/FormDialog";
import { Badge } from "@/components/ui/badge";
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
import {
  checkoutTool,
  deleteToolPhoto,
  fetchAllDrawerOptions,
  fetchToolPhoto,
  importTools,
  insertDesignsApi,
  markMaintenanceDone,
  returnTool,
  toolsApi,
  triggerBlobDownload,
  uploadToolPhoto,
  type ToolImportRowError,
} from "@/lib/api";
import type { Tool } from "@/lib/types";

const IMPORT_TEMPLATE_CSV =
  "name,category,manufacturer,sku,notes,quantity\nCordless Drill,Power Tools,DeWalt,DCD771,,1\n";

const toolSchema = z.object({
  name: z.string().min(1, "Required"),
  category: z.string().optional(),
  manufacturer: z.string().optional(),
  sku: z.string().optional(),
  notes: z.string().optional(),
  quantity: z.coerce.number().int().min(1).default(1),
  drawer_id: z.string().optional(),
  insert_design_id: z.string().optional(),
  // Meaningful only when `insert_design_id` is set -- how many of this
  // tool's owned `quantity` should get a packed slot in a generated drawer
  // layout (Milestone 3 Phase 3). Mirrors `quantity`'s style.
  insert_quantity: z.coerce.number().int().min(0).optional(),
  // `z.coerce.number()` alone turns an empty input into `Number("") === 0`,
  // which then fails `.min(1)` -- blocking submission on a field labeled
  // optional. Preprocessing "" to undefined first lets `.optional()` short
  // -circuit before coercion runs, same as leaving the field untouched.
  maintenance_interval_days: z.preprocess(
    (val) => (val === "" ? undefined : val),
    z.coerce.number().int().min(1).optional(),
  ),
});
type ToolFormValues = z.infer<typeof toolSchema>;

function isMaintenanceDue(tool: Tool): boolean {
  if (tool.maintenance_interval_days == null) return false;
  if (tool.last_maintained_at == null) return true;
  const dueAt = new Date(tool.last_maintained_at).getTime() + tool.maintenance_interval_days * 86_400_000;
  return dueAt < Date.now();
}

type SortKey = "name" | "category" | "manufacturer" | "quantity";

/**
 * One tool's photo thumbnail + upload/replace/delete controls. Lazily
 * fetches the photo blob only when `tool.has_photo` (no wasted requests for
 * the common no-photo case). `ToolRead` doesn't expose `updated_at`
 * (confirmed: neither it nor `ShopRead` return timestamps at all today,
 * despite the frontend `Tool`/`Shop` types declaring them -- a pre-existing
 * gap, not something to key cache-busting on), so instead of a
 * timestamp-keyed query, the upload/delete mutations explicitly invalidate
 * this exact `["tool-photo", tool.id]` key on success to force a refetch.
 */
function ToolPhotoCell({ tool }: { tool: Tool }) {
  const queryClient = useQueryClient();
  const fileInputRef = React.useRef<HTMLInputElement>(null);
  const photoQueryKey = ["tool-photo", tool.id];

  const photoQuery = useQuery({
    queryKey: photoQueryKey,
    queryFn: () => fetchToolPhoto(tool.id),
    enabled: tool.has_photo,
  });

  const objectUrl = React.useMemo(() => {
    if (!photoQuery.data) return null;
    return URL.createObjectURL(photoQuery.data);
  }, [photoQuery.data]);
  React.useEffect(() => {
    return () => {
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [objectUrl]);

  const uploadMutation = useMutation({
    mutationFn: (file: File) => uploadToolPhoto(tool.id, file),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["tools"] });
      queryClient.invalidateQueries({ queryKey: photoQueryKey });
    },
  });
  const deleteMutation = useMutation({
    mutationFn: () => deleteToolPhoto(tool.id),
    // No photoQueryKey invalidation needed here (unlike upload/replace) --
    // once `["tools"]` refetches and `has_photo` flips false, the photo
    // query's `enabled` condition goes false and it's simply never fetched
    // again. Invalidating it anyway would race a refetch against the
    // just-deleted file before the re-render lands, producing a harmless
    // but noisy 404 in the console.
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["tools"] }),
  });

  return (
    <div className="flex items-center gap-1.5">
      <input
        ref={fileInputRef}
        type="file"
        accept="image/*"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) uploadMutation.mutate(file);
          e.target.value = "";
        }}
      />
      {tool.has_photo && objectUrl ? (
        <>
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            title="Replace photo"
            className="h-9 w-9 shrink-0 overflow-hidden rounded-sm border border-border"
          >
            <img src={objectUrl} alt={tool.name} className="h-full w-full object-cover" />
          </button>
          <Button
            size="icon"
            variant="ghost"
            className="h-6 w-6"
            title="Delete photo"
            onClick={() => deleteMutation.mutate()}
          >
            <X className="h-3 w-3" />
          </Button>
        </>
      ) : (
        <Button
          size="icon"
          variant="ghost"
          title="Add photo"
          disabled={uploadMutation.isPending}
          onClick={() => fileInputRef.current?.click()}
        >
          <Camera className="h-3.5 w-3.5 text-muted-foreground" />
        </Button>
      )}
    </div>
  );
}

/**
 * Per-row status cell: checkout state (checkout/return controls, a tiny
 * local dialog mirroring `ToolPhotoCell`'s "one self-contained cell
 * component per tool" shape) or maintenance-due state, whichever applies --
 * never both at once, to keep the table compact (see the Dashboard for the
 * full breakdown).
 */
function ToolCheckoutCell({ tool }: { tool: Tool }) {
  const queryClient = useQueryClient();
  const [dialogOpen, setDialogOpen] = React.useState(false);
  const [checkedOutTo, setCheckedOutTo] = React.useState("");
  const [dueDate, setDueDate] = React.useState("");

  const checkoutMutation = useMutation({
    mutationFn: () =>
      checkoutTool(tool.id, {
        checked_out_to: checkedOutTo,
        // <input type="date"> gives "YYYY-MM-DD"; the backend expects a
        // real datetime, midnight UTC on that date is a reasonable
        // "due by end of this day" interpretation.
        checkout_due_at: dueDate ? `${dueDate}T00:00:00Z` : undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["tools"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      setDialogOpen(false);
      setCheckedOutTo("");
      setDueDate("");
    },
  });

  const returnMutation = useMutation({
    mutationFn: () => returnTool(tool.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["tools"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });

  const markMaintenanceMutation = useMutation({
    mutationFn: () => markMaintenanceDone(tool.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["tools"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });

  // Checkout state always wins over maintenance-due -- a tool can only show
  // one badge here (keeps the table compact); the Dashboard is the place
  // to see the full breakdown when both happen to apply at once.
  if (tool.checked_out_to) {
    const overdue = tool.checkout_due_at ? new Date(tool.checkout_due_at) < new Date() : false;
    return (
      <div className="flex items-center gap-1.5">
        <Badge variant={overdue ? "destructive" : "outline"} className="whitespace-nowrap">
          Out: {tool.checked_out_to}
        </Badge>
        <Button
          size="sm"
          variant="ghost"
          className="h-6 px-1.5 text-xs"
          disabled={returnMutation.isPending}
          onClick={() => returnMutation.mutate()}
        >
          Return
        </Button>
      </div>
    );
  }

  if (isMaintenanceDue(tool)) {
    return (
      <div className="flex items-center gap-1.5">
        <Badge variant="outline" className="whitespace-nowrap">
          Maintenance due
        </Badge>
        <Button
          size="sm"
          variant="ghost"
          className="h-6 px-1.5 text-xs"
          disabled={markMaintenanceMutation.isPending}
          onClick={() => markMaintenanceMutation.mutate()}
        >
          Mark done
        </Button>
      </div>
    );
  }

  return (
    <FormDialog
      open={dialogOpen}
      onOpenChange={setDialogOpen}
      trigger={
        <Button size="sm" variant="outline" className="h-7 text-xs">
          Check out
        </Button>
      }
      title={`Check out "${tool.name}"`}
      formId={`checkout-${tool.id}`}
      submitLabel="Check out"
      submitting={checkoutMutation.isPending}
    >
      <form
        id={`checkout-${tool.id}`}
        onSubmit={(e) => {
          e.preventDefault();
          if (checkedOutTo.trim()) checkoutMutation.mutate();
        }}
        className="flex flex-col gap-3"
      >
        <div className="flex flex-col gap-1">
          <Label htmlFor={`checkout-to-${tool.id}`}>Checked out to</Label>
          <Input
            id={`checkout-to-${tool.id}`}
            value={checkedOutTo}
            onChange={(e) => setCheckedOutTo(e.target.value)}
            placeholder="Name"
          />
        </div>
        <div className="flex flex-col gap-1">
          <Label htmlFor={`checkout-due-${tool.id}`}>Due date (optional)</Label>
          <Input
            id={`checkout-due-${tool.id}`}
            type="date"
            value={dueDate}
            onChange={(e) => setDueDate(e.target.value)}
          />
        </div>
      </form>
    </FormDialog>
  );
}

export function ToolsPage() {
  const queryClient = useQueryClient();
  const [open, setOpen] = React.useState(false);
  const [search, setSearch] = React.useState("");
  const [sortKey, setSortKey] = React.useState<SortKey>("name");
  const [unassignedOnly, setUnassignedOnly] = React.useState(false);

  const [importOpen, setImportOpen] = React.useState(false);
  const [importFile, setImportFile] = React.useState<File | null>(null);
  const [importErrors, setImportErrors] = React.useState<ToolImportRowError[] | null>(null);
  const [importSuccessCount, setImportSuccessCount] = React.useState<number | null>(null);

  const toolsQuery = useQuery({ queryKey: ["tools"], queryFn: () => toolsApi.list() });
  const drawerOptionsQuery = useQuery({
    queryKey: ["drawers", "all-with-path"],
    queryFn: fetchAllDrawerOptions,
  });
  const drawerLabelById = React.useMemo(() => {
    const map = new Map<string, string>();
    (drawerOptionsQuery.data ?? []).forEach((d) => map.set(d.id, d.label));
    return map;
  }, [drawerOptionsQuery.data]);

  const insertDesignsQuery = useQuery({
    queryKey: ["insert-designs"],
    queryFn: () => insertDesignsApi.list(),
  });
  const insertLabelById = React.useMemo(() => {
    const map = new Map<string, string>();
    (insertDesignsQuery.data ?? []).forEach((d) =>
      map.set(d.id, `${d.name} (${d.source === "generated" ? "Generated" : "Uploaded"})`),
    );
    return map;
  }, [insertDesignsQuery.data]);

  const { register, handleSubmit, reset, setValue, watch, formState } = useForm<ToolFormValues>({
    resolver: zodResolver(toolSchema),
    defaultValues: { quantity: 1, insert_quantity: 1 },
  });
  const selectedInsertId = watch("insert_design_id");

  const createMutation = useMutation({
    mutationFn: (values: ToolFormValues) =>
      toolsApi.create({
        ...values,
        drawer_id: values.drawer_id || null,
        insert_design_id: values.insert_design_id || null,
        // Only meaningful alongside a linked insert -- omit (null) rather
        // than send a stray quantity with nothing to attach it to.
        insert_quantity: values.insert_design_id ? (values.insert_quantity ?? 1) : null,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["tools"] });
      setOpen(false);
      reset({ quantity: 1, insert_quantity: 1 });
    },
  });

  const reassignMutation = useMutation({
    mutationFn: ({ id, drawer_id }: { id: string; drawer_id: string | null }) =>
      toolsApi.update(id, { drawer_id }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["tools"] }),
  });

  const reassignInsertMutation = useMutation({
    mutationFn: ({ id, insert_design_id }: { id: string; insert_design_id: string | null }) =>
      toolsApi.update(id, { insert_design_id }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["tools"] }),
  });

  const updateInsertQuantityMutation = useMutation({
    mutationFn: ({ id, insert_quantity }: { id: string; insert_quantity: number }) =>
      toolsApi.update(id, { insert_quantity }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["tools"] }),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => toolsApi.remove(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["tools"] }),
  });

  const importMutation = useMutation({
    mutationFn: (file: File) => importTools(file),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ["tools"] });
      setImportErrors(null);
      setImportSuccessCount(result.imported);
      setImportFile(null);
    },
    onError: (error: unknown) => {
      // A row-validation failure returns {detail, errors: [...]} instead of
      // this app's usual single-string {detail} -- surface the structured
      // list so the user sees exactly which rows are wrong, not just "it
      // failed" (this app's established anti-silent-failure convention).
      if (axios.isAxiosError(error) && Array.isArray(error.response?.data?.errors)) {
        setImportErrors(error.response.data.errors as ToolImportRowError[]);
      } else {
        setImportErrors([{ row: null, message: "Import failed. Please try again." }]);
      }
      setImportSuccessCount(null);
    },
  });

  const downloadTemplate = () => {
    triggerBlobDownload(new Blob([IMPORT_TEMPLATE_CSV], { type: "text/csv" }), "tools-template.csv");
  };

  const filtered = React.useMemo(() => {
    let rows: Tool[] = toolsQuery.data ?? [];
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      rows = rows.filter((t) =>
        [t.name, t.category, t.manufacturer, t.sku]
          .filter(Boolean)
          .some((f) => f!.toLowerCase().includes(q)),
      );
    }
    if (unassignedOnly) {
      rows = rows.filter((t) => !t.drawer_id);
    }
    return [...rows].sort((a, b) => {
      const av = (a[sortKey] ?? "") as string | number;
      const bv = (b[sortKey] ?? "") as string | number;
      if (typeof av === "number" && typeof bv === "number") return av - bv;
      return String(av).localeCompare(String(bv));
    });
  }, [toolsQuery.data, search, sortKey, unassignedOnly]);

  const toggleSort = (key: SortKey) => setSortKey(key);

  return (
    <div className="flex h-full flex-col p-4">
      <div className="mb-3 flex items-center justify-between">
        <div>
          <h1 className="text-base font-semibold">Tools</h1>
          <p className="text-xs text-muted-foreground">
            Org-wide inventory across every shop and drawer.
          </p>
        </div>
        <div className="flex items-center gap-2">
        <FormDialog
          open={importOpen}
          onOpenChange={(v) => {
            setImportOpen(v);
            if (!v) {
              setImportFile(null);
              setImportErrors(null);
              setImportSuccessCount(null);
            }
          }}
          trigger={
            <Button size="sm" variant="outline">
              <Upload />
              Import CSV
            </Button>
          }
          title="Import tools from CSV"
          description="Columns: name (required), category, manufacturer, sku, notes, quantity. Imported tools are unassigned -- organize them into drawers afterward."
          formId="import-tools"
          submitLabel="Import"
          submitting={importMutation.isPending}
        >
          <form
            id="import-tools"
            onSubmit={(e) => {
              e.preventDefault();
              if (importFile) importMutation.mutate(importFile);
            }}
            className="flex flex-col gap-3"
          >
            <div className="flex flex-col gap-1">
              <Label htmlFor="t-import-file">CSV file</Label>
              <input
                id="t-import-file"
                type="file"
                accept=".csv"
                onChange={(e) => {
                  setImportFile(e.target.files?.[0] ?? null);
                  setImportErrors(null);
                  setImportSuccessCount(null);
                }}
                className="text-sm text-foreground file:mr-3 file:rounded-sm file:border-0 file:bg-secondary file:px-2.5 file:py-1.5 file:text-xs file:text-secondary-foreground"
              />
            </div>
            <button
              type="button"
              onClick={downloadTemplate}
              className="self-start text-xs text-primary hover:underline"
            >
              Download template
            </button>
            {importSuccessCount !== null && (
              <p className="text-xs text-muted-foreground">
                Imported <span className="font-mono text-foreground">{importSuccessCount}</span> tools.
              </p>
            )}
            {importErrors && importErrors.length > 0 && (
              <div className="max-h-40 overflow-auto rounded-sm border border-destructive/40 bg-destructive/5 p-2">
                <p className="mb-1 text-xs font-medium text-destructive">
                  Import failed — no tools were created:
                </p>
                <ul className="flex flex-col gap-0.5 text-xs text-destructive">
                  {/* `err.message` already embeds "Row N: " for row-specific
                      errors (see backend's _parse_import_row) -- don't
                      re-prepend `err.row` here, or it renders doubled. */}
                  {importErrors.map((err, i) => (
                    <li key={i}>{err.message}</li>
                  ))}
                </ul>
              </div>
            )}
          </form>
        </FormDialog>
        <FormDialog
          open={open}
          onOpenChange={setOpen}
          trigger={
            <Button size="sm">
              <Plus />
              New tool
            </Button>
          }
          title="New tool"
          formId="create-tool"
          submitting={createMutation.isPending}
        >
          <form
            id="create-tool"
            onSubmit={handleSubmit((v) => createMutation.mutate(v))}
            className="flex flex-col gap-3"
          >
            <div className="flex flex-col gap-1">
              <Label htmlFor="t-name">Name</Label>
              <Input id="t-name" {...register("name")} />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="flex flex-col gap-1">
                <Label htmlFor="t-category">Category</Label>
                <Input id="t-category" {...register("category")} />
              </div>
              <div className="flex flex-col gap-1">
                <Label htmlFor="t-manufacturer">Manufacturer</Label>
                <Input id="t-manufacturer" {...register("manufacturer")} />
              </div>
              <div className="flex flex-col gap-1">
                <Label htmlFor="t-sku">SKU</Label>
                <Input id="t-sku" {...register("sku")} />
              </div>
              <div className="flex flex-col gap-1">
                <Label htmlFor="t-quantity">Quantity</Label>
                <Input id="t-quantity" type="number" min={1} {...register("quantity")} />
              </div>
            </div>
            <div className="flex flex-col gap-1">
              <Label htmlFor="t-notes">Notes</Label>
              <Input id="t-notes" {...register("notes")} />
            </div>
            <div className="flex flex-col gap-1">
              <Label htmlFor="t-maintenance-interval">Maintenance interval (days, optional)</Label>
              <Input
                id="t-maintenance-interval"
                type="number"
                min={1}
                placeholder="e.g. 90"
                {...register("maintenance_interval_days")}
              />
            </div>
            <div className="flex flex-col gap-1">
              <Label htmlFor="t-drawer">Drawer (optional)</Label>
              <Select onValueChange={(v) => setValue("drawer_id", v)}>
                <SelectTrigger id="t-drawer">
                  <SelectValue placeholder="Unassigned" />
                </SelectTrigger>
                <SelectContent>
                  {(drawerOptionsQuery.data ?? []).map((d) => (
                    <SelectItem key={d.id} value={d.id}>
                      {d.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="grid grid-cols-[1fr_110px] gap-3">
              <div className="flex flex-col gap-1">
                <Label htmlFor="t-insert">Insert / STL (optional)</Label>
                <Select onValueChange={(v) => setValue("insert_design_id", v)}>
                  <SelectTrigger id="t-insert">
                    <SelectValue placeholder="No insert linked" />
                  </SelectTrigger>
                  <SelectContent>
                    {(insertDesignsQuery.data ?? []).map((d) => (
                      <SelectItem key={d.id} value={d.id}>
                        {insertLabelById.get(d.id) ?? d.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="flex flex-col gap-1">
                <Label htmlFor="t-insert-qty">Insert copies</Label>
                <Input
                  id="t-insert-qty"
                  type="number"
                  min={0}
                  disabled={!selectedInsertId}
                  {...register("insert_quantity")}
                />
              </div>
            </div>
            {formState.errors.name && (
              <p className="text-xs text-destructive">Name is required.</p>
            )}
          </form>
        </FormDialog>
        </div>
      </div>

      <div className="mb-2 flex items-center gap-2">
        <div className="relative w-64">
          <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            className="pl-7"
            placeholder="Search tools…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <input
            type="checkbox"
            checked={unassignedOnly}
            onChange={(e) => setUnassignedOnly(e.target.checked)}
            className="h-3 w-3"
          />
          Unassigned only
        </label>
      </div>

      <div className="min-h-0 flex-1 overflow-auto scrollbar-thin rounded-md border border-border">
        <Table>
          <TableHeader>
            <TableRow>
              {(
                [
                  ["name", "Name"],
                  ["category", "Category"],
                  ["manufacturer", "Manufacturer"],
                  ["quantity", "Qty"],
                ] as [SortKey, string][]
              ).map(([key, label]) => (
                <TableHead key={key}>
                  <button
                    type="button"
                    onClick={() => toggleSort(key)}
                    className="flex items-center gap-1 hover:text-foreground"
                  >
                    {label}
                    <ArrowUpDown className="h-3 w-3" />
                  </button>
                </TableHead>
              ))}
              <TableHead>Photo</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Drawer</TableHead>
              <TableHead>Insert</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {filtered.map((tool) => (
              <TableRow key={tool.id}>
                <TableCell className="font-medium">
                  <Link to={`/tools/${tool.id}`} className="hover:underline">
                    {tool.name}
                  </Link>
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {tool.category || "—"}
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {tool.manufacturer || "—"}
                </TableCell>
                <TableCell className="font-mono">{tool.quantity}</TableCell>
                <TableCell>
                  <ToolPhotoCell tool={tool} />
                </TableCell>
                <TableCell>
                  <ToolCheckoutCell tool={tool} />
                </TableCell>
                <TableCell>
                  <Select
                    value={tool.drawer_id ?? "__unassigned__"}
                    onValueChange={(v) =>
                      reassignMutation.mutate({
                        id: tool.id,
                        drawer_id: v === "__unassigned__" ? null : v,
                      })
                    }
                  >
                    <SelectTrigger className="h-7 w-56 text-xs">
                      <SelectValue placeholder="Unassigned" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="__unassigned__">Unassigned</SelectItem>
                      {(drawerOptionsQuery.data ?? []).map((d) => (
                        <SelectItem key={d.id} value={d.id}>
                          {d.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  {tool.drawer_id && !drawerLabelById.has(tool.drawer_id) && (
                    <span className="ml-1 text-[11px] text-muted-foreground">
                      (loading…)
                    </span>
                  )}
                </TableCell>
                <TableCell>
                  <div className="flex items-center gap-1.5">
                    <Select
                      value={tool.insert_design_id ?? "__none__"}
                      onValueChange={(v) =>
                        reassignInsertMutation.mutate({
                          id: tool.id,
                          insert_design_id: v === "__none__" ? null : v,
                        })
                      }
                    >
                      <SelectTrigger className="h-7 w-56 text-xs">
                        <SelectValue placeholder="No insert linked" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="__none__">No insert linked</SelectItem>
                        {(insertDesignsQuery.data ?? []).map((d) => (
                          <SelectItem key={d.id} value={d.id}>
                            {insertLabelById.get(d.id) ?? d.name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    {/* Uncontrolled + keyed on the current server value so it
                        remounts (and re-syncs) whenever the tool's insert
                        link or quantity changes elsewhere -- avoids needing
                        per-row controlled state just for this one field. */}
                    <Input
                      key={`${tool.id}-${tool.insert_design_id}-${tool.insert_quantity}`}
                      type="number"
                      min={0}
                      max={tool.quantity}
                      title="Insert copies"
                      aria-label="Insert copies"
                      className="h-7 w-14 text-xs"
                      disabled={!tool.insert_design_id}
                      defaultValue={tool.insert_design_id ? (tool.insert_quantity ?? 1) : ""}
                      onBlur={(e) => {
                        if (!tool.insert_design_id) return;
                        const value = Number(e.target.value);
                        if (!Number.isFinite(value) || value < 0) return;
                        if (value === (tool.insert_quantity ?? 1)) return;
                        updateInsertQuantityMutation.mutate({ id: tool.id, insert_quantity: value });
                      }}
                    />
                  </div>
                </TableCell>
                <TableCell>
                  <Button
                    size="icon"
                    variant="ghost"
                    onClick={() => {
                      if (confirm(`Delete tool "${tool.name}"?`)) {
                        deleteMutation.mutate(tool.id);
                      }
                    }}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </TableCell>
              </TableRow>
            ))}
            {toolsQuery.isSuccess && filtered.length === 0 && (
              <TableRow>
                <TableCell colSpan={9} className="py-6 text-center text-muted-foreground">
                  No tools match.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
