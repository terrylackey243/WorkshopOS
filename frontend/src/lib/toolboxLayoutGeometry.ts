// Pure geometry helpers for the toolbox front-view layout SVG (drawers
// grouped by physical row, split left-to-right within a row). Sibling to
// `drawerLayoutGeometry.ts` (which lays out inserts *inside* one drawer) --
// this is the same "fit real-world mm into a pixel budget" idea one level
// up, but a fixed per-row grid instead of bin-packing, since drawers in a
// chest sit in fixed slots rather than being freely arranged. Kept
// dependency-free and side-effect-free for the same reason as that file.

export interface RowDrawerInput {
  id: string;
  orderInRow: number;
  // `number | string` because these come from `DrawerProfile.inside_width_mm`
  // / `inside_height_mm`, which map to SQLAlchemy `Numeric` columns and
  // serialize as JSON strings over the wire (same quirk documented at
  // length in `drawerLayoutGeometry.ts`). Unlike that file's `*`/`Math.max`
  // usages, which coerce a string operand safely either way, this module
  // sums widths with `+` across multiple drawers in a row -- `+` on a
  // string operand does concatenation, not addition, so coercion here is
  // load-bearing, not just defensive.
  widthMm: number | string;
  heightMm: number | string;
}

export interface PlacedDrawerPx {
  id: string;
  xPx: number;
  widthPx: number;
}

export interface RowLayoutPx {
  row: number;
  yPx: number;
  heightPx: number;
  drawers: PlacedDrawerPx[];
  // True when this row's number isn't immediately after the previous row's
  // (e.g. row 4 after row 2) -- lets the renderer draw a divider band for a
  // stacked toolbox's physical section break, without needing any new
  // schema field: users mark a break just by leaving a gap in the numbers.
  hasBreakBefore: boolean;
}

export interface ToolboxLayoutPx {
  rows: RowLayoutPx[];
  canvasWidthPx: number;
  canvasHeightPx: number;
}

// Fixed height for a section-break divider band -- not derived from any
// real measurement (we don't know the stacked units' actual frame gap), just
// a visually-clear-enough constant, consistent with the rest of this module
// being an approximation rather than to-scale.
export const SECTION_BREAK_PX = 14;

/**
 * Lays out a toolbox's drawers, grouped by `row`, into pixel-space rects.
 * A row's width is always the FULL `canvasWidthPx`, split among that row's
 * drawers proportionally by their own `widthMm` -- a lone drawer in a row
 * fills the whole width, which is what makes an irregular chest (one
 * full-width top drawer, two columns below it) render correctly with no
 * extra config. This is explicitly an approximation, not to-scale: a row's
 * width is never compared against another row's in real mm, only against
 * itself.
 *
 * Row height comes from the tallest drawer sharing that row (guards against
 * mismatched profiles in the same row), scaled so the full stack of rows
 * fits `heightPixelBudget`.
 */
export function computeToolboxLayout(
  rowsByNumber: Map<number, RowDrawerInput[]>,
  canvasWidthPx: number,
  heightPixelBudget: number,
): ToolboxLayoutPx {
  const sortedRowNumbers = Array.from(rowsByNumber.keys()).sort((a, b) => a - b);

  const rowHeightsMm = sortedRowNumbers.map((row) => {
    const drawers = rowsByNumber.get(row) ?? [];
    return Math.max(...drawers.map((d) => Number(d.heightMm)), 1);
  });
  const totalHeightMm = rowHeightsMm.reduce((sum, h) => sum + h, 0);
  const heightScale = heightPixelBudget / Math.max(totalHeightMm, 1);

  let yPx = 0;
  let previousRow: number | null = null;
  const rows: RowLayoutPx[] = sortedRowNumbers.map((row, i) => {
    const hasBreakBefore = previousRow !== null && row - previousRow > 1;
    if (hasBreakBefore) yPx += SECTION_BREAK_PX;
    previousRow = row;

    const drawers = [...(rowsByNumber.get(row) ?? [])].sort(
      (a, b) => a.orderInRow - b.orderInRow,
    );
    const rowWidthMm = Math.max(
      drawers.reduce((sum, d) => sum + Number(d.widthMm), 0),
      1,
    );
    const heightPx = rowHeightsMm[i] * heightScale;

    let xPx = 0;
    const placedDrawers: PlacedDrawerPx[] = drawers.map((d) => {
      const widthPx = (Number(d.widthMm) / rowWidthMm) * canvasWidthPx;
      const placed = { id: d.id, xPx, widthPx };
      xPx += widthPx;
      return placed;
    });

    const rowLayout: RowLayoutPx = { row, yPx, heightPx, drawers: placedDrawers, hasBreakBefore };
    yPx += heightPx;
    return rowLayout;
  });

  return { rows, canvasWidthPx, canvasHeightPx: yPx };
}

/** Splits a drawer list into row-number -> drawers buckets, plus the ones with no row assigned yet. */
export function groupDrawersByRow<T extends { row: number | null }>(
  drawers: T[],
): { placed: Map<number, T[]>; unplaced: T[] } {
  const placed = new Map<number, T[]>();
  const unplaced: T[] = [];
  for (const drawer of drawers) {
    if (drawer.row === null) {
      unplaced.push(drawer);
      continue;
    }
    const bucket = placed.get(drawer.row) ?? [];
    bucket.push(drawer);
    placed.set(drawer.row, bucket);
  }
  return { placed, unplaced };
}
