import { Layers } from "lucide-react";

// Detail-panel empty state shown at the bare `/label-designer` index route
// (no design selected yet) -- repurposed from the M1 "coming soon" stub now
// that Label Designer is wired up (see DesignsList/DesignDetail).
export function LabelDesignerEmptyState() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 p-8 text-center">
      <div className="flex h-12 w-12 items-center justify-center rounded-md border border-dashed border-border text-muted-foreground">
        <Layers className="h-5 w-5" />
      </div>
      <h1 className="text-base font-semibold">Label Designer</h1>
      <p className="max-w-sm text-sm text-muted-foreground">
        Select a design on the left, or create a new one to generate a parametric
        magnet-backed drawer label from your Label Style and Magnet profiles.
      </p>
    </div>
  );
}
