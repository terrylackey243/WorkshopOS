import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import { fetchToolPhoto, toolsApi } from "@/lib/api";

/**
 * Minimal read-only tool page -- the prerequisite this app didn't have
 * before the QR-code-on-labels milestone: a stable URL a QR code can
 * deep-link to (`{app_public_url}/tools/{id}`, see
 * `backend/app/routers/designs.py::create_design`). Deliberately no edit
 * form here -- editing still happens on `ToolsPage.tsx`'s table; this page
 * exists to answer "what is this tool and where does it live" for someone
 * scanning a label while in the workshop, not to be a second CRUD surface.
 */
export function ToolDetail() {
  const { toolId } = useParams();

  const toolQuery = useQuery({
    queryKey: ["tools", toolId],
    queryFn: () => toolsApi.get(toolId as string),
    enabled: !!toolId,
  });
  const tool = toolQuery.data;

  const photoQuery = useQuery({
    queryKey: ["tool-photo", toolId],
    queryFn: () => fetchToolPhoto(toolId as string),
    enabled: !!toolId && !!tool?.has_photo,
  });
  const photoUrl = React.useMemo(
    () => (photoQuery.data ? URL.createObjectURL(photoQuery.data) : null),
    [photoQuery.data],
  );
  React.useEffect(() => {
    return () => {
      if (photoUrl) URL.revokeObjectURL(photoUrl);
    };
  }, [photoUrl]);

  if (toolQuery.isLoading) {
    return <p className="p-4 text-sm text-muted-foreground">Loading tool…</p>;
  }
  if (toolQuery.isError || !tool) {
    return <p className="p-4 text-sm text-destructive">Tool not found.</p>;
  }

  const rows: [string, React.ReactNode][] = [
    ["Category", tool.category || "—"],
    ["Manufacturer", tool.manufacturer || "—"],
    ["SKU", tool.sku || "—"],
    ["Quantity", tool.quantity],
    ["Notes", tool.notes || "—"],
  ];

  return (
    <div className="flex flex-col gap-4 p-4">
      <div>
        <h1 className="text-base font-semibold">{tool.name}</h1>
        <p className="text-xs text-muted-foreground">
          {tool.location ? (
            <Link
              to={`/shops/${tool.location.shop_id}/toolboxes/${tool.location.toolbox_id}/drawers/${tool.location.drawer_id}`}
              className="text-primary hover:underline"
            >
              {tool.location.shop_name} / {tool.location.toolbox_name} / {tool.location.drawer_label}
            </Link>
          ) : (
            "Unassigned"
          )}
        </p>
      </div>

      {photoUrl && (
        <img
          src={photoUrl}
          alt={tool.name}
          className="h-48 w-48 rounded-md border border-border object-cover"
        />
      )}

      <div className="max-w-md rounded-md border border-border">
        {rows.map(([label, value]) => (
          <div key={label} className="flex justify-between border-b border-border px-3 py-2 text-sm last:border-b-0">
            <span className="text-muted-foreground">{label}</span>
            <span className="text-foreground">{value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
