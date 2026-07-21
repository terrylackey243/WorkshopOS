import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import { Download, Loader2 } from "lucide-react";
import { useParams } from "react-router-dom";

import { StlPreview } from "@/components/StlPreview";
import { Button } from "@/components/ui/button";
import { designsApi, fetchDesignFile, triggerBlobDownload } from "@/lib/api";

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

  const outlineBlobQuery = useQuery({
    queryKey: ["design-file", designId, "outline"],
    queryFn: () => fetchDesignFile(designId as string, "outline"),
    enabled: !!designId && isGenerated,
  });
  const textBlobQuery = useQuery({
    queryKey: ["design-file", designId, "text"],
    queryFn: () => fetchDesignFile(designId as string, "text"),
    enabled: !!designId && isGenerated,
  });
  // Only present when this design is linked to a Tool (`design.tool_id` set)
  // -- an unlinked label never produces a qr_stl_path, so this query simply
  // never runs for the common case.
  const qrBlobQuery = useQuery({
    queryKey: ["design-file", designId, "qr"],
    queryFn: () => fetchDesignFile(designId as string, "qr"),
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

  if (designQuery.isLoading) {
    return <p className="p-4 text-sm text-muted-foreground">Loading design…</p>;
  }
  if (designQuery.isError || !design) {
    return <p className="p-4 text-sm text-destructive">Design not found.</p>;
  }

  const stem = slugForFilename(design.name);

  return (
    <div className="flex h-full flex-col gap-4 p-4">
      <div>
        <h1 className="text-base font-semibold">{design.name}</h1>
        <p className="text-sm text-muted-foreground">"{design.text}"</p>
      </div>

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
