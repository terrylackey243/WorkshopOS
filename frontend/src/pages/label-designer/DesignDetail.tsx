import * as React from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import axios from "axios";
import { Download, Loader2, Pencil, RefreshCw } from "lucide-react";
import { useForm } from "react-hook-form";
import { useParams } from "react-router-dom";

import { FormDialog } from "@/components/FormDialog";
import { StlPreview } from "@/components/StlPreview";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { designsApi, fetchDesignFile, triggerBlobDownload } from "@/lib/api";
import type { Design } from "@/lib/types";
import { designSchema, DesignLinkFields, type DesignFormValues } from "@/pages/label-designer/DesignFormFields";

/**
 * For a "sealed" (print-in-place) magnet profile, the Z height -- measured
 * from the print bed, after the slicer flip called out in the generation
 * manifest's orientation note -- at which the recess is fully formed and
 * ready for the magnet, right before the seal cap's layers begin. Not a
 * layer *number*: this app has no notion of a printer's layer height, and
 * every slicer's own "pause at height" feature takes a Z value in mm
 * directly, so there's nothing to convert.
 *
 * `body_depth_mm - seal_cap_mm`: parameters_json's `magnets.seal_cap_mm` is
 * how much solid material sits *above* the pocket opening (see
 * label_engine.py's MagnetPocketParameters) in the *design's* coordinate
 * frame, where the opening faces down (z=0). The physical print is that
 * design flipped face-down against the bed, so a design-frame height above
 * the opening becomes a bed-frame height *below* the top of the print --
 * i.e. print_height = body_depth_mm - design_z, evaluated at the seal
 * cap's start.
 */
function sealedMagnetPauseHeightMm(design: Design): { pauseHeightMm: number; count: number } | null {
  const params = design.parameters_json as
    | { body_depth_mm?: number; magnets?: { seal_cap_mm?: number; count?: number } | null }
    | undefined;
  const magnets = params?.magnets;
  const bodyDepthMm = params?.body_depth_mm;
  if (!magnets || !magnets.seal_cap_mm || magnets.seal_cap_mm <= 0 || bodyDepthMm == null) return null;
  return { pauseHeightMm: bodyDepthMm - magnets.seal_cap_mm, count: magnets.count ?? 1 };
}

/**
 * Turns an object into a filesystem-safe filename stem (`Drawer Labels` ->
 * `drawer-labels`), matching the naming convention already used by the real
 * geometry engine's `.outline.stl` / `.text.stl` fixture pairs.
 */
function slugForFilename(name: string): string {
  const slug = name
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/(^-|-$)/g, "");
  return slug || "label";
}

export function DesignDetail() {
  const { designId } = useParams();
  const queryClient = useQueryClient();

  const designQuery = useQuery({
    queryKey: ["designs", designId],
    queryFn: () => designsApi.get(designId as string),
    enabled: !!designId,
    // Poll while the Dramatiq worker is still generating the STL pair;
    // TanStack Query v5's callback form receives the `Query` object, not
    // just the data, so read status off `query.state.data`.
    refetchInterval: (query) => (query.state.data?.status === "queued" ? 1500 : false),
  });

  const design = designQuery.data;
  const isGenerated = design?.status === "generated";

  // Regenerating overwrites the STL files at the exact same on-disk paths
  // (see routers/designs.py), so the request URL alone can't tell a fresh
  // file from a stale cached one. Keying on `generated_at` (which gets a
  // new value every time generation completes) forces a real refetch on
  // every regeneration instead of depending on the `enabled` flag's
  // false->true transition to trigger one -- that transition doesn't
  // reliably cause TanStack Query to refetch an already-invalidated query,
  // which is why regenerating previously left the old STL showing until a
  // full page reload. Same fix, same reasoning as the Tool Photos feature's
  // `tool.id, tool.updated_at` query key.
  const outlineBlobQuery = useQuery({
    queryKey: ["design-file", designId, "outline", design?.generated_at],
    queryFn: () => fetchDesignFile(designId as string, "outline", design?.content_hash),
    enabled: !!designId && isGenerated,
  });
  const textBlobQuery = useQuery({
    queryKey: ["design-file", designId, "text", design?.generated_at],
    queryFn: () => fetchDesignFile(designId as string, "text", design?.content_hash),
    enabled: !!designId && isGenerated,
  });
  // Only present when this design is linked to a Tool (`design.tool_id` set)
  // -- an unlinked label never produces a qr_stl_path, so this query simply
  // never runs for the common case.
  const qrBlobQuery = useQuery({
    queryKey: ["design-file", designId, "qr", design?.generated_at],
    queryFn: () => fetchDesignFile(designId as string, "qr", design?.content_hash),
    enabled: !!designId && isGenerated && !!design?.tool_id,
  });

  const [outlineUrl, setOutlineUrl] = React.useState<string | null>(null);
  const [textUrl, setTextUrl] = React.useState<string | null>(null);
  const [qrUrl, setQrUrl] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!outlineBlobQuery.data) return;
    const url = URL.createObjectURL(outlineBlobQuery.data);
    setOutlineUrl(url);
    return () => {
      URL.revokeObjectURL(url);
    };
  }, [outlineBlobQuery.data]);

  React.useEffect(() => {
    if (!textBlobQuery.data) return;
    const url = URL.createObjectURL(textBlobQuery.data);
    setTextUrl(url);
    return () => {
      URL.revokeObjectURL(url);
    };
  }, [textBlobQuery.data]);

  React.useEffect(() => {
    if (!qrBlobQuery.data) return;
    const url = URL.createObjectURL(qrBlobQuery.data);
    setQrUrl(url);
    return () => {
      URL.revokeObjectURL(url);
    };
  }, [qrBlobQuery.data]);

  const regenerateMutation = useMutation({
    mutationFn: () => designsApi.regenerate(designId as string),
    onSuccess: () => {
      // Regenerating re-derives parameters from the label style / magnet
      // profile's *current* values and re-enqueues generation server-side
      // (see routers/designs.py) -- the design flips back to "queued".
      // Invalidating this drives the polling refetch below, which picks up
      // the new `generated_at` once done; the blob queries above are keyed
      // on that value, so they refetch fresh automatically -- no separate
      // invalidation of them needed here.
      queryClient.invalidateQueries({ queryKey: ["designs", designId] });
    },
  });

  const regenerateError =
    regenerateMutation.isError && axios.isAxiosError(regenerateMutation.error) &&
    typeof regenerateMutation.error.response?.data?.detail === "string"
      ? regenerateMutation.error.response.data.detail
      : regenerateMutation.isError
        ? "Failed to regenerate label."
        : null;

  const [editOpen, setEditOpen] = React.useState(false);
  const [editError, setEditError] = React.useState<string | null>(null);
  const editForm = useForm<DesignFormValues>({
    resolver: zodResolver(designSchema),
    defaultValues: { name: "", text: "", label_style_profile_id: "" },
  });

  // Reset the form to the design's current values each time the dialog
  // opens, rather than on every `design` refetch -- otherwise a background
  // poll while the dialog is open (e.g. status flipping to "generated")
  // would blow away whatever the user is mid-typing.
  React.useEffect(() => {
    if (design && editOpen) {
      editForm.reset({
        name: design.name,
        text: design.text,
        label_style_profile_id: design.label_style_profile_id ?? "",
        magnet_profile_id: design.magnet_profile_id ?? undefined,
        shop_id: design.shop_id ?? undefined,
        tool_id: design.tool_id ?? undefined,
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editOpen]);

  const updateMutation = useMutation({
    mutationFn: (values: DesignFormValues) =>
      designsApi.update(designId as string, {
        name: values.name,
        text: values.text,
        label_style_profile_id: values.label_style_profile_id,
        magnet_profile_id: values.magnet_profile_id || undefined,
        shop_id: values.shop_id || undefined,
        tool_id: values.tool_id || undefined,
      }),
    onSuccess: () => {
      // Editing re-enqueues generation server-side just like regenerate
      // does, so the same invalidation drives the polling refetch below.
      queryClient.invalidateQueries({ queryKey: ["designs", designId] });
      queryClient.invalidateQueries({ queryKey: ["designs"] });
      setEditOpen(false);
      setEditError(null);
    },
    onError: (error: unknown) => {
      if (axios.isAxiosError(error) && error.response?.status === 422) {
        const detail = error.response.data?.detail;
        setEditError(typeof detail === "string" ? detail : "Invalid design parameters.");
      } else {
        setEditError("Failed to save design. Please try again.");
      }
    },
  });

  if (designQuery.isLoading) {
    return <p className="p-4 text-sm text-muted-foreground">Loading design…</p>;
  }
  if (designQuery.isError || !design) {
    return <p className="p-4 text-sm text-destructive">Design not found.</p>;
  }

  const stem = slugForFilename(design.name);
  const isRegenerating = design.status === "queued" || regenerateMutation.isPending;

  return (
    <div className="flex h-full flex-col gap-4 p-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-base font-semibold">{design.name}</h1>
          <p className="text-sm text-muted-foreground">"{design.text}"</p>
        </div>
        <div className="flex shrink-0 gap-2">
          <FormDialog
            open={editOpen}
            onOpenChange={(o) => {
              setEditOpen(o);
              if (!o) setEditError(null);
            }}
            trigger={
              <Button size="sm" variant="outline">
                <Pencil />
                Edit
              </Button>
            }
            title="Edit design"
            description="Changes re-derive the STL parameters and re-enqueue generation."
            formId="edit-design"
            submitting={updateMutation.isPending}
          >
            <form
              id="edit-design"
              onSubmit={editForm.handleSubmit((v) => {
                setEditError(null);
                updateMutation.mutate(v);
              })}
              className="flex flex-col gap-3"
            >
              <div className="flex flex-col gap-1">
                <Label htmlFor="edit-design-name">Name</Label>
                <Input id="edit-design-name" {...editForm.register("name")} />
              </div>
              <div className="flex flex-col gap-1">
                <Label htmlFor="edit-design-text">Text</Label>
                <Textarea id="edit-design-text" {...editForm.register("text")} />
              </div>
              <DesignLinkFields form={editForm} />
              {editError && (
                <p className="rounded-sm border border-destructive/30 bg-destructive/10 px-2.5 py-1.5 text-xs text-destructive">
                  {editError}
                </p>
              )}
            </form>
          </FormDialog>
          <Button
            size="sm"
            variant="outline"
            disabled={isRegenerating}
            onClick={() => regenerateMutation.mutate()}
          >
            <RefreshCw className={isRegenerating ? "animate-spin" : undefined} />
            {isRegenerating ? "Regenerating…" : "Regenerate"}
          </Button>
        </div>
      </div>
      {regenerateError && (
        <p className="text-xs text-destructive">{regenerateError}</p>
      )}

      {(() => {
        const sealed = sealedMagnetPauseHeightMm(design);
        if (!sealed) return null;
        return (
          <div className="rounded-sm border border-sky-500/30 bg-sky-500/10 px-3 py-2 text-sm">
            <p className="font-medium">Print-in-place magnet{sealed.count > 1 ? "s" : ""}</p>
            <p className="text-muted-foreground">
              Pause the print at <span className="font-mono">Z = {sealed.pauseHeightMm.toFixed(2)}mm</span>, drop
              the magnet{sealed.count > 1 ? "s" : ""} in, then resume -- the print seals{" "}
              {sealed.count > 1 ? "them" : "it"} in from there.
            </p>
          </div>
        );
      })()}

      {design.status === "queued" && (
        <div className="flex flex-1 flex-col items-center justify-center gap-2 text-muted-foreground">
          <Loader2 className="h-5 w-5 animate-spin" />
          <p className="text-sm">Generating…</p>
        </div>
      )}

      {design.status === "failed" && (
        <div className="rounded-sm border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
          <p className="font-medium">Generation failed</p>
          <p className="mt-1">{design.error_message ?? "An unknown error occurred."}</p>
        </div>
      )}

      {design.status === "draft" && (
        <p className="text-sm text-muted-foreground">This design has not been generated yet.</p>
      )}

      {isGenerated && (
        <>
          <div className="min-h-0 flex-1 overflow-hidden rounded-md border border-border bg-muted/20">
            <StlPreview
              bodies={[
                ...(outlineUrl ? [{ url: outlineUrl, color: "#9ca3af" }] : []),
                ...(textUrl ? [{ url: textUrl, color: "#22c55e" }] : []),
                ...(qrUrl ? [{ url: qrUrl, color: "#3b82f6" }] : []),
              ]}
            />
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              variant="outline"
              disabled={!outlineBlobQuery.data}
              onClick={() =>
                outlineBlobQuery.data &&
                triggerBlobDownload(outlineBlobQuery.data, `${stem}.outline.stl`)
              }
            >
              <Download />
              Download outline.stl
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={!textBlobQuery.data}
              onClick={() =>
                textBlobQuery.data && triggerBlobDownload(textBlobQuery.data, `${stem}.text.stl`)
              }
            >
              <Download />
              Download text.stl
            </Button>
            {design.tool_id && (
              <Button
                size="sm"
                variant="outline"
                disabled={!qrBlobQuery.data}
                onClick={() =>
                  qrBlobQuery.data && triggerBlobDownload(qrBlobQuery.data, `${stem}.qr.stl`)
                }
              >
                <Download />
                Download qr.stl
              </Button>
            )}
          </div>
        </>
      )}
    </div>
  );
}
