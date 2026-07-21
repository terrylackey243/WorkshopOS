import { Box } from "lucide-react";

// Detail-panel empty state shown at the bare `/inserts` index route (no
// insert selected yet) -- mirrors LabelDesignerEmptyState.
export function InsertsEmptyState() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 p-8 text-center">
      <div className="flex h-12 w-12 items-center justify-center rounded-md border border-dashed border-border text-muted-foreground">
        <Box className="h-5 w-5" />
      </div>
      <h1 className="text-base font-semibold">Inserts</h1>
      <p className="max-w-sm text-sm text-muted-foreground">
        Select an insert on the left, or create a new one -- generate a
        parametric Gridfinity-compatible bin from grid dimensions and
        compartment counts, or upload an STL file you already have.
      </p>
    </div>
  );
}
