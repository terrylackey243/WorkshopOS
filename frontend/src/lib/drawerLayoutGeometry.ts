// Pure geometry helpers for the drawer auto-layout SVG visualization
// (Milestone 3 Phase 3, `DrawerDetail.tsx`). Kept dependency-free and
// side-effect-free on purpose so the placement/scaling math can be sanity
// checked in isolation (no overlaps, everything in-bounds) without needing
// to render React or hit the backend -- see scratchpad validation script
// used during development.

export interface InsertBoundsMm {
  width_mm: number;
  depth_mm: number;
}

/**
 * Pulls `{width_mm, depth_mm}` out of an `InsertDesign.bounds_json` blob,
 * which is typed opaquely (`Record<string, unknown> | null`) since most
 * consumers never look inside it. Returns null if the shape isn't what we
 * expect (e.g. a design that hasn't finished generating) so callers can
 * skip rendering that placement instead of drawing garbage geometry.
 */
export function getInsertBounds(
  boundsJson: Record<string, unknown> | null | undefined,
): InsertBoundsMm | null {
  if (!boundsJson) return null;
  const width = boundsJson["width_mm"];
  const depth = boundsJson["depth_mm"];
  if (typeof width !== "number" || typeof depth !== "number") return null;
  if (!Number.isFinite(width) || !Number.isFinite(depth)) return null;
  return { width_mm: width, depth_mm: depth };
}

/**
 * A placement's on-screen footprint is width x depth, EXCEPT when
 * `rotation_deg === 90`, where the effective footprint is depth x width
 * (swapped) per the backend contract.
 *
 * `rotationDeg` accepts `number | string` on purpose: `InsertPlacement` maps
 * to a SQLAlchemy `Numeric` column, and this codebase's established (if
 * unfortunate) pattern is that `Numeric`/`Decimal` fields serialize as JSON
 * *strings* over the wire (confirmed live: the backend returns
 * `"rotation_deg": "90"`, not `90`) -- unlike `bounds_json`, which is a raw
 * JSONB dict of real Python floats and arrives as actual JSON numbers. A
 * strict `rotationDeg === 90` check silently fails against the string form
 * (JS strict equality doesn't coerce), which would make every rotated
 * placement render unrotated with no error -- coerce explicitly instead of
 * relying on the `number` type annotation callers see.
 */
export function effectiveFootprintMm(
  bounds: InsertBoundsMm,
  rotationDeg: number | string,
): InsertBoundsMm {
  if (Number(rotationDeg) === 90) {
    return { width_mm: bounds.depth_mm, depth_mm: bounds.width_mm };
  }
  return bounds;
}

/**
 * Uniform scale factor (px per mm) that fits the drawer's usable interior
 * into a `pixelBudget`-sized square-ish panel without distorting aspect
 * ratio. Uses the larger drawer dimension so neither axis overflows.
 */
export function computeScale(
  insideWidthMm: number,
  insideDepthMm: number,
  pixelBudget: number,
): number {
  const largestDimensionMm = Math.max(insideWidthMm, insideDepthMm, 1);
  return pixelBudget / largestDimensionMm;
}

export interface PlacementRectPx {
  x: number;
  y: number;
  width: number;
  height: number;
}

/**
 * Converts one placement's real-mm position + rotated footprint into SVG
 * pixel-space rect coordinates at the given scale. `x_mm`/`y_mm` are the
 * origin corner of the rect (not center), matching the backend's MaxRects
 * placement convention.
 *
 * `xMm`/`yMm`/`rotationDeg` accept `number | string` for the same reason as
 * `effectiveFootprintMm` above -- these come straight from `InsertPlacement`
 * API fields, which serialize as JSON strings. Multiplication (`*`) happens
 * to auto-coerce a numeric string correctly in JS, so `xMm`/`yMm` would have
 * silently "worked" either way -- coerced explicitly anyway so this function
 * doesn't depend on that operator-specific coercion quirk to stay correct.
 */
export function placementRectPx(
  xMm: number | string,
  yMm: number | string,
  bounds: InsertBoundsMm,
  rotationDeg: number | string,
  scale: number,
): PlacementRectPx {
  const footprint = effectiveFootprintMm(bounds, rotationDeg);
  return {
    x: Number(xMm) * scale,
    y: Number(yMm) * scale,
    width: footprint.width_mm * scale,
    height: footprint.depth_mm * scale,
  };
}

// Small fixed palette cycled by placement index -- matches the app's dense/
// dark aesthetic (muted, desaturated), doesn't need to be fancy, just
// visually distinct enough to tell adjacent rects apart.
export const PLACEMENT_COLORS = [
  "#3b82f680", // blue
  "#22c55e80", // green
  "#f59e0b80", // amber
  "#ec489980", // pink
  "#8b5cf680", // violet
  "#14b8a680", // teal
  "#ef444480", // red
  "#84cc1680", // lime
];

export function colorForIndex(index: number): string {
  return PLACEMENT_COLORS[index % PLACEMENT_COLORS.length];
}
