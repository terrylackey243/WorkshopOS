from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

# M3 Phase 4 (Bin Merging) detection algorithm. Pure 2D geometry + grouping
# logic operating on already-loaded placement/design data -- no DB I/O here,
# mirroring `drawer_layout.py`'s `pack()` being a pure function the router
# feeds and reads back. See `backend/app/routers/drawer_layouts.py`'s
# `POST /{layout_id}/merge` for the orchestration (loading data in, creating
# new `InsertDesign`/`InsertPlacement` rows out).

GRID_PITCH_MM = 42.0

# Two rectangles are "touching" if an edge of one lands within this many mm
# of the facing edge of the other (the packer places bins with best-fit
# floats, not grid-snapped, so exact float equality isn't a safe test -- same
# reasoning as `drawer_layout.py`'s EPS, just a coarser tolerance since this
# is comparing independently-rounded `Decimal(8,3)` DB values instead of the
# packer's own in-memory floats).
ADJACENCY_TOLERANCE_MM = 0.1

# A shared border must have positive length to count as an adjacency (pure
# corner touches don't count) -- this is the "positive length" analog of
# `drawer_layout.py`'s EPS for overlap tests.
EPS = 1e-6

# Sum-of-areas vs. bounding-box-area must match within this many mm^2 to call
# a connected component a clean, gap-free rectangle (see `find_merge_clusters`
# docstring for why this single check catches both gaps and L-shapes).
AREA_TOLERANCE_MM2 = 1.0

# A resolved grid size must reproduce the bounding box's mm dimensions
# (via the bin engine's `42 * units - 0.5` footprint formula) within this
# many mm, or the cluster is rejected as not grid-aligned.
#
# Deliberately wider than a naive "should be near-exact" figure: the bin
# engine's `-0.5` offset (see `bin_engine.py::_outer_footprint`) is applied
# ONCE per generated body, not once per grid unit. N *separately* generated
# 1-unit-wide bins packed flush (zero gap, which is exactly what
# `drawer_layout.py::pack()` produces -- it has no notion of a per-cell
# grid-pitch reservation) bounding-box to `N * (42 - 0.5)` mm, which is
# `0.5 * (N - 1)` mm *short* of what one real merged N-unit body's footprint
# (`42 * N - 0.5`) would measure -- each additional touching seam "loses" the
# 0.5mm clearance that bin would have carried as a standalone body. Worst
# case within this app's `MAX_GRID_UNITS = 6` cap is `0.5 * (6 - 1) = 2.5mm`;
# 3.0mm covers that with margin. The tight `AREA_TOLERANCE_MM2` check above
# remains the actual gatekeeper against real gaps/overlaps/L-shapes -- this
# is a coarser secondary sanity check that the resolved integer grid size is
# plausible, not a claim of sub-mm precision.
GRID_ALIGNMENT_TOLERANCE_MM = 3.0


def effective_footprint(bounds_json: dict[str, Any], rotation_deg: Decimal | float) -> tuple[float, float]:
    """Effective (width_mm, depth_mm) footprint for a placement, derived from
    its `InsertDesign.bounds_json` + `InsertPlacement.rotation_deg` -- the DB
    only stores pre-rotation bounds and a rotation angle, not the post-
    rotation footprint (see `drawer_layout.py`'s `Placement.width_mm`/
    `depth_mm` for the in-memory analog this reconstructs). Swaps width/depth
    on a 90-degree rotation, same derivation the frontend's
    `drawerLayoutGeometry.ts` uses and the same `>45` threshold convention
    `test_drawer_layouts.py::_placement_rect` already uses -- `rotation_deg`
    is only ever 0 or 90 in this codebase (see `drawer_layout.py::pack()`)."""
    width_mm = float(bounds_json["width_mm"])
    depth_mm = float(bounds_json["depth_mm"])
    if abs(float(rotation_deg)) > 45.0:
        return depth_mm, width_mm
    return width_mm, depth_mm


@dataclass
class PlacementForMerge:
    """One placement's already-resolved data, as gathered by the router from
    `InsertPlacement` + its `InsertDesign`. `width_mm`/`depth_mm` must already
    be the effective (post-rotation) footprint -- see `effective_footprint()`.
    """

    placement_id: uuid.UUID
    insert_design_id: uuid.UUID
    x_mm: float
    y_mm: float
    width_mm: float
    depth_mm: float
    source: str
    status: str
    parameters_json: dict[str, Any]


@dataclass
class MergeCluster:
    """One valid merge: the source placements it replaces, the resolved grid
    size of the combined bin, the bounding-box origin to place it at, and the
    shared compatible parameters to carry into the new bin's `parameters_json`."""

    placement_ids: list[uuid.UUID]
    x_mm: float
    y_mm: float
    grid_width_units: int
    grid_depth_units: int
    height_units: int
    include_stacking_lip: bool
    magnet_diameter_mm: float | None
    magnet_thickness_mm: float | None
    magnet_diameter_clearance_mm: float
    magnet_depth_clearance_mm: float
    source_placement_count: int


Rect = tuple[float, float, float, float]  # (x, y, width, height)


def _is_eligible(p: PlacementForMerge) -> bool:
    """Only parametrically-generated, fully-generated, single-cell (no
    internal dividers) bins are merge candidates -- see the plan's explicit
    scope limits (uploaded/tooltrace STLs have no removable shared wall;
    bins with dividers have no well-defined merged divider layout)."""
    if p.source != "generated" or p.status != "generated":
        return False
    params = p.parameters_json or {}
    return params.get("compartments_x") == 1 and params.get("compartments_y") == 1


def _compat_key(p: PlacementForMerge) -> tuple[Any, ...]:
    params = p.parameters_json or {}
    return (
        params.get("height_units"),
        params.get("include_stacking_lip"),
        params.get("magnet_diameter_mm"),
        params.get("magnet_thickness_mm"),
        params.get("magnet_diameter_clearance_mm"),
        params.get("magnet_depth_clearance_mm"),
    )


def _rects_touch(a: Rect, b: Rect, tol: float = ADJACENCY_TOLERANCE_MM) -> bool:
    """The "touching" counterpart to `drawer_layout.py`'s `_rects_intersect`:
    two rectangles are adjacent if they share a border segment of positive
    length -- one pair of facing edges lands within `tol` of each other AND
    the other axis's ranges overlap by a positive amount (a shared corner
    alone does not count)."""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b

    # Vertical shared edge (side by side in x): facing x-edges close together,
    # y-ranges overlap by a positive length.
    x_edge_touch = abs((ax + aw) - bx) <= tol or abs((bx + bw) - ax) <= tol
    y_overlap = ay < by + bh - EPS and ay + ah > by + EPS
    if x_edge_touch and y_overlap:
        return True

    # Horizontal shared edge (stacked in y): facing y-edges close together,
    # x-ranges overlap by a positive length.
    y_edge_touch = abs((ay + ah) - by) <= tol or abs((by + bh) - ay) <= tol
    x_overlap = ax < bx + bw - EPS and ax + aw > bx + EPS
    if y_edge_touch and x_overlap:
        return True

    return False


def find_merge_clusters(placements: list[PlacementForMerge]) -> list[MergeCluster]:
    """Detects mergeable clusters of adjacent, compatible, single-cell
    generated bins.

    1. Filter to eligible placements (`_is_eligible`).
    2. Group by compatibility key (`_compat_key`) -- only identically-keyed
       placements can ever merge together.
    3. Within each group, build an edge-adjacency graph (`_rects_touch`) and
       find connected components (union-find).
    4. For each component with 2+ members, verify sum-of-member-areas equals
       the component's bounding-box area within tolerance -- a gap OR an
       L-shaped/non-rectangular union both break this equality (an L-shape's
       bounding box always has strictly more area than its members' rects
       sum to), so this single check rejects both cases at once without full
       polygon math.
    5. Resolve the bounding box's mm dimensions to whole grid units by
       inverting the bin engine's `width_mm = 42 * units - 0.5` footprint
       formula, then re-validate that inversion lands within tolerance --
       rejects arrangements that are geometrically flush but not grid-unit
       aligned.

    Any component that fails step 4 or 5 is rejected as a whole (none of its
    members merge) -- this deliberately does not attempt partial merges
    within a rejected component, matching the plan's explicit scope limit
    (not solving general rectilinear-polygon decomposition).
    """
    eligible = [p for p in placements if _is_eligible(p)]

    groups: dict[tuple[Any, ...], list[PlacementForMerge]] = {}
    for p in eligible:
        groups.setdefault(_compat_key(p), []).append(p)

    clusters: list[MergeCluster] = []

    for key, group in groups.items():
        n = len(group)
        rects: list[Rect] = [(p.x_mm, p.y_mm, p.width_mm, p.depth_mm) for p in group]

        parent = list(range(n))

        def find(i: int) -> int:
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        def union(i: int, j: int) -> None:
            ri, rj = find(i), find(j)
            if ri != rj:
                parent[ri] = rj

        for i in range(n):
            for j in range(i + 1, n):
                if _rects_touch(rects[i], rects[j]):
                    union(i, j)

        components: dict[int, list[int]] = {}
        for i in range(n):
            components.setdefault(find(i), []).append(i)

        height_units, include_stacking_lip, magnet_diameter_mm, magnet_thickness_mm, magnet_diameter_clearance_mm, magnet_depth_clearance_mm = key

        for member_idxs in components.values():
            if len(member_idxs) < 2:
                continue

            member_rects = [rects[i] for i in member_idxs]
            min_x = min(r[0] for r in member_rects)
            min_y = min(r[1] for r in member_rects)
            max_x = max(r[0] + r[2] for r in member_rects)
            max_y = max(r[1] + r[3] for r in member_rects)
            bbox_w = max_x - min_x
            bbox_h = max_y - min_y
            bbox_area = bbox_w * bbox_h
            sum_area = sum(r[2] * r[3] for r in member_rects)

            if abs(sum_area - bbox_area) > AREA_TOLERANCE_MM2:
                continue  # gap or non-rectangular (e.g. L-shaped) union -- reject the whole component

            grid_width_units = round((bbox_w + 0.5) / GRID_PITCH_MM)
            grid_depth_units = round((bbox_h + 0.5) / GRID_PITCH_MM)
            if grid_width_units < 1 or grid_depth_units < 1:
                continue

            expected_w = GRID_PITCH_MM * grid_width_units - 0.5
            expected_h = GRID_PITCH_MM * grid_depth_units - 0.5
            if (
                abs(expected_w - bbox_w) > GRID_ALIGNMENT_TOLERANCE_MM
                or abs(expected_h - bbox_h) > GRID_ALIGNMENT_TOLERANCE_MM
            ):
                continue  # geometrically flush but not grid-unit-aligned -- reject

            clusters.append(
                MergeCluster(
                    placement_ids=[group[i].placement_id for i in member_idxs],
                    x_mm=min_x,
                    y_mm=min_y,
                    grid_width_units=grid_width_units,
                    grid_depth_units=grid_depth_units,
                    height_units=height_units,
                    include_stacking_lip=include_stacking_lip,
                    magnet_diameter_mm=magnet_diameter_mm,
                    magnet_thickness_mm=magnet_thickness_mm,
                    magnet_diameter_clearance_mm=magnet_diameter_clearance_mm,
                    magnet_depth_clearance_mm=magnet_depth_clearance_mm,
                    source_placement_count=len(member_idxs),
                )
            )

    return clusters
