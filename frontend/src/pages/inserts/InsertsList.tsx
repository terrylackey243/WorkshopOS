import * as React from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import axios from "axios";
import { Plus, Upload } from "lucide-react";
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
import { insertDesignsApi, magnetProfilesApi, uploadInsertDesign } from "@/lib/api";
import type { InsertDesign, InsertDesignStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

// An empty `type="number"` input's `valueAsNumber` is `NaN`, not `undefined`
// -- z.coerce.number() alone doesn't treat NaN as absent, which either fails
// validation with no visible error (optional fields) or produces a cryptic
// "Expected number, received nan" message (required fields). Preprocess
// empty-string/NaN uniformly before coercion (see ProfilesPage.tsx's
// fixed_width_mm fix, the origin of this pattern).
const requiredGridNumber = (label: string) =>
  z.preprocess(
    (v) => (v === "" || (typeof v === "number" && Number.isNaN(v)) ? undefined : v),
    z.coerce.number({ invalid_type_error: `${label} is required` }).int(`${label} must be a whole number`).min(1, `${label} must be at least 1`),
  );

// Compartments have a sensible default (1) per the plan, so an emptied
// input falls back to that default rather than surfacing a validation error.
const compartmentNumber = () =>
  z.preprocess(
    (v) => (v === "" || (typeof v === "number" && Number.isNaN(v)) ? 1 : v),
    z.coerce.number().int("Must be a whole number").min(1, "Must be at least 1"),
  );

const binSchema = z.object({
  name: z.string().min(1, "Required"),
  grid_width_units: requiredGridNumber("Grid width"),
  grid_depth_units: requiredGridNumber("Grid depth"),
  height_units: requiredGridNumber("Height"),
  compartments_x: compartmentNumber(),
  compartments_y: compartmentNumber(),
  include_stacking_lip: z.boolean(),
  magnet_profile_id: z.string().optional(),
});
type BinFormValues = z.infer<typeof binSchema>;

const DEFAULT_VALUES: BinFormValues = {
  name: "",
  grid_width_units: 1,
  grid_depth_units: 1,
  height_units: 1,
  compartments_x: 1,
  compartments_y: 1,
  include_stacking_lip: true,
};

const STATUS_VARIANT: Record<InsertDesignStatus, BadgeProps["variant"]> = {
  queued: "secondary",
  generated: "default",
  failed: "destructive",
  draft: "outline",
};

const STATUS_LABEL: Record<InsertDesignStatus, string> = {
  queued: "Generating…",
  generated: "Generated",
  failed: "Failed",
  draft: "Draft",
};

function StatusBadge({ status }: { status: InsertDesignStatus }) {
  return <Badge variant={STATUS_VARIANT[status]}>{STATUS_LABEL[status]}</Badge>;
}

// Distinguishes the two (soon three, once tooltrace.ai integration lands)
// creation paths that feed the unified InsertDesign list -- see plan
// Phase 2 §"Naming".
const SOURCE_VARIANT: Record<InsertDesign["source"], BadgeProps["variant"]> = {
  generated: "secondary",
  upload: "outline",
  tooltrace: "outline",
};

const SOURCE_LABEL: Record<InsertDesign["source"], string> = {
  generated: "Generated",
  upload: "Uploaded",
  tooltrace: "Tooltrace",
};

function SourceBadge({ source }: { source: InsertDesign["source"] }) {
  return <Badge variant={SOURCE_VARIANT[source]}>{SOURCE_LABEL[source]}</Badge>;
}

// react-hook-form's `register()` doesn't manage `<input type="file">` well
// with zod (FileList isn't a great fit for zod's schema types across
// environments), so the selected File lives in its own bit of component
// state instead -- name/source_reference are the only fields RHF/zod
// actually validate for this form.
const uploadSchema = z.object({
  name: z.string().min(1, "Required"),
  source_reference: z.string().optional(),
});
type UploadFormValues = z.infer<typeof uploadSchema>;

const UPLOAD_DEFAULT_VALUES: UploadFormValues = {
  name: "",
  source_reference: "",
};

/**
 * List panel for the Inserts section: every InsertDesign in the active org
 * (both parametrically generated bins and uploaded STLs) plus the two
 * creation entry points, "New bin" and "Upload STL". InsertDesigns are
 * immutable once created (no edit), same as Designs, so this only ever
 * creates + lists.
 */
export function InsertsList() {
  const { insertDesignId: activeInsertDesignId } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [open, setOpen] = React.useState(false);
  const [formError, setFormError] = React.useState<string | null>(null);
  const [uploadOpen, setUploadOpen] = React.useState(false);
  const [uploadFormError, setUploadFormError] = React.useState<string | null>(null);
  const [uploadFile, setUploadFile] = React.useState<File | null>(null);

  const insertsQuery = useQuery({
    queryKey: ["insert-designs"],
    queryFn: () => insertDesignsApi.list(),
  });
  const magnetProfilesQuery = useQuery({
    queryKey: ["profiles-magnets"],
    queryFn: () => magnetProfilesApi.list(),
  });

  const form = useForm<BinFormValues>({
    resolver: zodResolver(binSchema),
    defaultValues: DEFAULT_VALUES,
  });

  const uploadForm = useForm<UploadFormValues>({
    resolver: zodResolver(uploadSchema),
    defaultValues: UPLOAD_DEFAULT_VALUES,
  });

  const createMutation = useMutation({
    mutationFn: (values: BinFormValues) =>
      insertDesignsApi.create({
        name: values.name,
        grid_width_units: values.grid_width_units,
        grid_depth_units: values.grid_depth_units,
        height_units: values.height_units,
        compartments_x: values.compartments_x,
        compartments_y: values.compartments_y,
        include_stacking_lip: values.include_stacking_lip,
        magnet_profile_id: values.magnet_profile_id || undefined,
      }),
    onSuccess: (bin) => {
      queryClient.invalidateQueries({ queryKey: ["insert-designs"] });
      setOpen(false);
      setFormError(null);
      form.reset(DEFAULT_VALUES);
      navigate(`/inserts/${bin.id}`);
    },
    onError: (error: unknown) => {
      // generate-bin is the one place bin creation surfaces structured
      // 422s from bad parameters (e.g. compartment counts that don't divide
      // evenly) -- show `detail` verbatim instead of a generic message.
      if (axios.isAxiosError(error) && error.response?.status === 422) {
        const detail = error.response.data?.detail;
        setFormError(typeof detail === "string" ? detail : "Invalid bin parameters.");
      } else {
        setFormError("Failed to create bin. Please try again.");
      }
    },
  });

  const uploadMutation = useMutation({
    mutationFn: (values: UploadFormValues) => {
      // Belt-and-suspenders: the submit handler below already refuses to
      // call `mutate` without a file selected, but TypeScript can't see
      // that from here since the file lives outside the zod-validated form.
      if (!uploadFile) {
        return Promise.reject(new Error("No file selected."));
      }
      return uploadInsertDesign({
        name: values.name,
        file: uploadFile,
        source_reference: values.source_reference || undefined,
      });
    },
    onSuccess: (insertDesign) => {
      queryClient.invalidateQueries({ queryKey: ["insert-designs"] });
      setUploadOpen(false);
      setUploadFormError(null);
      uploadForm.reset(UPLOAD_DEFAULT_VALUES);
      setUploadFile(null);
      navigate(`/inserts/${insertDesign.id}`);
    },
    onError: (error: unknown) => {
      // Upload is the one place InsertDesign creation surfaces both 422
      // (non-.stl filename) and 413 (over the 25MB cap) -- show `detail`
      // verbatim for either instead of a generic message, same pattern as
      // the New bin dialog's 422 handling above.
      if (
        axios.isAxiosError(error) &&
        (error.response?.status === 422 || error.response?.status === 413)
      ) {
        const detail = error.response.data?.detail;
        setUploadFormError(
          typeof detail === "string"
            ? detail
            : error.response.status === 413
              ? "File is too large (25MB max)."
              : "Invalid upload.",
        );
      } else {
        setUploadFormError("Failed to upload file. Please try again.");
      }
    },
  });

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-border px-3 py-2">
        <div>
          <h1 className="text-sm font-semibold">Inserts</h1>
          <p className="text-xs text-muted-foreground">
            {(insertsQuery.data ?? []).length} insert
            {(insertsQuery.data ?? []).length === 1 ? "" : "s"}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <FormDialog
            open={uploadOpen}
            onOpenChange={(o) => {
              setUploadOpen(o);
              if (!o) {
                setUploadFormError(null);
                setUploadFile(null);
                uploadForm.reset(UPLOAD_DEFAULT_VALUES);
              }
            }}
            trigger={
              <Button size="sm" variant="outline">
                <Upload />
                Upload STL
              </Button>
            }
            title="Upload STL"
            description="Import an STL file you already have (a community download, a tooltrace.ai export, etc.) as an insert. WorkshopOS computes its footprint from the mesh."
            formId="upload-insert-design"
            submitLabel="Upload"
            submitting={uploadMutation.isPending}
          >
            <form
              id="upload-insert-design"
              onSubmit={uploadForm.handleSubmit(
                (v) => {
                  if (!uploadFile) {
                    setUploadFormError("Select an STL file to upload.");
                    return;
                  }
                  setUploadFormError(null);
                  uploadMutation.mutate(v);
                },
                () =>
                  setUploadFormError(
                    "Check the highlighted fields -- one or more values are invalid.",
                  ),
              )}
              className="flex flex-col gap-3"
            >
              <div className="flex flex-col gap-1">
                <Label htmlFor="upload-name">Name</Label>
                <Input id="upload-name" {...uploadForm.register("name")} />
                {uploadForm.formState.errors.name && (
                  <p className="text-xs text-destructive">
                    {uploadForm.formState.errors.name.message}
                  </p>
                )}
              </div>
              <div className="flex flex-col gap-1">
                <Label htmlFor="upload-file">STL file</Label>
                <input
                  id="upload-file"
                  type="file"
                  accept=".stl"
                  className="text-sm text-foreground file:mr-2 file:rounded-sm file:border-0 file:bg-secondary file:px-2 file:py-1 file:text-xs file:font-medium file:text-secondary-foreground"
                  onChange={(e) => setUploadFile(e.target.files?.[0] ?? null)}
                />
              </div>
              <div className="flex flex-col gap-1">
                <Label htmlFor="upload-source-reference">Source note (optional)</Label>
                <Input
                  id="upload-source-reference"
                  placeholder="e.g. tooltrace.ai, or a URL"
                  {...uploadForm.register("source_reference")}
                />
              </div>
              {uploadFormError && (
                <p className="rounded-sm border border-destructive/30 bg-destructive/10 px-2.5 py-1.5 text-xs text-destructive">
                  {uploadFormError}
                </p>
              )}
            </form>
          </FormDialog>
          <FormDialog
            open={open}
            onOpenChange={(o) => {
              setOpen(o);
              if (!o) setFormError(null);
            }}
            trigger={
              <Button size="sm">
                <Plus />
                New bin
              </Button>
            }
            title="New bin"
            description="Generates a single-body Gridfinity-compatible bin STL from grid dimensions and compartment counts."
            formId="create-bin"
            submitting={createMutation.isPending}
          >
          <form
            id="create-bin"
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
              <Label htmlFor="bin-name">Name</Label>
              <Input id="bin-name" {...form.register("name")} />
              {form.formState.errors.name && (
                <p className="text-xs text-destructive">{form.formState.errors.name.message}</p>
              )}
            </div>
            <div className="grid grid-cols-3 gap-3">
              <div className="flex flex-col gap-1">
                <Label htmlFor="bin-grid-width">Grid width (units)</Label>
                <Input
                  id="bin-grid-width"
                  type="number"
                  step="1"
                  min="1"
                  {...form.register("grid_width_units", { valueAsNumber: true })}
                />
                {form.formState.errors.grid_width_units && (
                  <p className="text-xs text-destructive">
                    {form.formState.errors.grid_width_units.message}
                  </p>
                )}
              </div>
              <div className="flex flex-col gap-1">
                <Label htmlFor="bin-grid-depth">Grid depth (units)</Label>
                <Input
                  id="bin-grid-depth"
                  type="number"
                  step="1"
                  min="1"
                  {...form.register("grid_depth_units", { valueAsNumber: true })}
                />
                {form.formState.errors.grid_depth_units && (
                  <p className="text-xs text-destructive">
                    {form.formState.errors.grid_depth_units.message}
                  </p>
                )}
              </div>
              <div className="flex flex-col gap-1">
                <Label htmlFor="bin-height">Height (units)</Label>
                <Input
                  id="bin-height"
                  type="number"
                  step="1"
                  min="1"
                  {...form.register("height_units", { valueAsNumber: true })}
                />
                {form.formState.errors.height_units && (
                  <p className="text-xs text-destructive">
                    {form.formState.errors.height_units.message}
                  </p>
                )}
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="flex flex-col gap-1">
                <Label htmlFor="bin-compartments-x">Compartments (X)</Label>
                <Input
                  id="bin-compartments-x"
                  type="number"
                  step="1"
                  min="1"
                  {...form.register("compartments_x", { valueAsNumber: true })}
                />
                {form.formState.errors.compartments_x && (
                  <p className="text-xs text-destructive">
                    {form.formState.errors.compartments_x.message}
                  </p>
                )}
              </div>
              <div className="flex flex-col gap-1">
                <Label htmlFor="bin-compartments-y">Compartments (Y)</Label>
                <Input
                  id="bin-compartments-y"
                  type="number"
                  step="1"
                  min="1"
                  {...form.register("compartments_y", { valueAsNumber: true })}
                />
                {form.formState.errors.compartments_y && (
                  <p className="text-xs text-destructive">
                    {form.formState.errors.compartments_y.message}
                  </p>
                )}
              </div>
            </div>
            <label className="flex items-center gap-2 text-sm text-foreground">
              <input
                type="checkbox"
                className="h-3.5 w-3.5"
                {...form.register("include_stacking_lip")}
              />
              Include stacking lip
            </label>
            <div className="flex flex-col gap-1">
              <Label>Magnet profile</Label>
              <Select
                value={form.watch("magnet_profile_id")}
                onValueChange={(v) => form.setValue("magnet_profile_id", v)}
              >
                <SelectTrigger>
                  <SelectValue placeholder="No magnets" />
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
            {formError && (
              <p className="rounded-sm border border-destructive/30 bg-destructive/10 px-2.5 py-1.5 text-xs text-destructive">
                {formError}
              </p>
            )}
          </form>
          </FormDialog>
        </div>
      </div>

      <div className="flex-1 overflow-auto scrollbar-thin">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Source</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Created</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(insertsQuery.data ?? []).map((bin) => (
              <TableRow
                key={bin.id}
                className={cn(activeInsertDesignId === bin.id && "bg-accent")}
              >
                <TableCell>
                  <Link to={`/inserts/${bin.id}`} className="font-medium hover:underline">
                    {bin.name}
                  </Link>
                </TableCell>
                <TableCell>
                  <SourceBadge source={bin.source} />
                </TableCell>
                <TableCell>
                  <StatusBadge status={bin.status} />
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {new Date(bin.created_at).toLocaleDateString()}
                </TableCell>
              </TableRow>
            ))}
            {insertsQuery.isSuccess && insertsQuery.data.length === 0 && (
              <TableRow>
                <TableCell colSpan={4} className="py-6 text-center text-muted-foreground">
                  No inserts yet. Create or upload your first one above.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
