import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import { Download, Loader2 } from "lucide-react";
import { useParams } from "react-router-dom";

import { StlPreview } from "@/components/StlPreview";
import { Button } from "@/components/ui/button";
import { fetchInsertDesignFile, insertDesignsApi, triggerBlobDownload } from "@/lib/api";

/**
 * Turns an object into a filesystem-safe filename stem (`Small Parts Bin` ->
 * `small-parts-bin`), matching the naming convention already used for the
 * real geometry engine's fixture STLs. Duplicated from DesignDetail.tsx
 * rather than shared, mirroring how the geometry engine itself keeps small
 * per-generator helpers local instead of a shared utils module.
 */
function slugForFilename(name: string): string {
  const slug = name
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/(^-|-$)/g, "");
  return slug || "insert";
}

/**
 * Detail panel for a single InsertDesign, regardless of `source` -- a
 * generated Gridfinity bin and an uploaded STL both flow through the
 * identical draft/queued -> generated|failed lifecycle (Phase 1's polling
 * logic is unchanged here, see plan Phase 2 §"BinDetail.tsx"), so this
 * component's queries and status handling stay entirely source-agnostic.
 * Only the copy below is worded generically ("Processing…" rather than
 * "Generating…") so it reads correctly for both creation paths.
 */
export function InsertDetail() {
  const { insertDesignId } = useParams();

  const insertQuery = useQuery({
    queryKey: ["insert-designs", insertDesignId],
    queryFn: () => insertDesignsApi.get(insertDesignId as string),
    enabled: !!insertDesignId,
    // Poll while the Dramatiq worker is still generating/parsing the STL;
    // TanStack Query v5's callback form receives the `Query` object, not
    // just the data, so read status off `query.state.data`.
    refetchInterval: (query) => (query.state.data?.status === "queued" ? 1500 : false),
  });

  const insertDesign = insertQuery.data;
  const isGenerated = insertDesign?.status === "generated";

  const fileBlobQuery = useQuery({
    queryKey: ["insert-design-file", insertDesignId],
    queryFn: () => fetchInsertDesignFile(insertDesignId as string),
    enabled: !!insertDesignId && isGenerated,
  });

  const [fileUrl, setFileUrl] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!fileBlobQuery.data) return;
    const url = URL.createObjectURL(fileBlobQuery.data);
    setFileUrl(url);
    return () => {
      URL.revokeObjectURL(url);
    };
  }, [fileBlobQuery.data]);

  if (insertQuery.isLoading) {
    return <p className="p-4 text-sm text-muted-foreground">Loading insert…</p>;
  }
  if (insertQuery.isError || !insertDesign) {
    return <p className="p-4 text-sm text-destructive">Insert not found.</p>;
  }

  const stem = slugForFilename(insertDesign.name);

  return (
    <div className="flex h-full flex-col gap-4 p-4">
      <div>
        <h1 className="text-base font-semibold">{insertDesign.name}</h1>
      </div>

      {insertDesign.status === "queued" && (
        <div className="flex flex-1 flex-col items-center justify-center gap-2 text-muted-foreground">
          <Loader2 className="h-5 w-5 animate-spin" />
          <p className="text-sm">Processing…</p>
        </div>
      )}

      {insertDesign.status === "failed" && (
        <div className="rounded-sm border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
          <p className="font-medium">Processing failed</p>
          <p className="mt-1">{insertDesign.error_message ?? "An unknown error occurred."}</p>
        </div>
      )}

      {insertDesign.status === "draft" && (
        <p className="text-sm text-muted-foreground">
          This insert has not been generated yet.
        </p>
      )}

      {isGenerated && (
        <>
          <div className="min-h-0 flex-1 overflow-hidden rounded-md border border-border bg-muted/20">
            <StlPreview bodies={fileUrl ? [{ url: fileUrl, color: "#9ca3af" }] : []} />
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              variant="outline"
              disabled={!fileBlobQuery.data}
              onClick={() =>
                fileBlobQuery.data && triggerBlobDownload(fileBlobQuery.data, `${stem}.stl`)
              }
            >
              <Download />
              Download {stem}.stl
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
