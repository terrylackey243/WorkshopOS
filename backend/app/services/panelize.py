from __future__ import annotations

import uuid
from dataclasses import dataclass

from .drawer_layout import PackItem, Unplaced, pack

# M3 Phase 5 (Print-Bed Panelization) algorithm. Reuses `drawer_layout.py`'s
# `pack()` unmodified -- panelization is the same 2D MaxRects problem `pack()`
# already solves, just run against a printer bed instead of a drawer interior,
# and iterated across as many plates as it takes instead of stopping after
# one. See `bin_merge.py` for the sibling M3 Phase 4 service this module's
# style (pure functions, dataclasses, docstrings explaining WHY) mirrors.
#
# `pack()`/`Unplaced` are reused directly rather than re-implemented; this
# module only adds the "iterate across N plates, pre-filter, cap the loop"
# orchestration around them. `PackItem.tool_id` is reused to carry
# `placement_id` through -- confirmed safe: it's just a UUID field on the
# dataclass with no FK/type coupling to a real `Tool`, and `Placement`/
# `Unplaced` already echo it straight back unchanged.

MAX_PLATES = 50  # safety cap against runaway loops


@dataclass
class PanelizeItem:
    placement_id: uuid.UUID
    insert_design_id: uuid.UUID
    width_mm: float
    depth_mm: float
    label: str


@dataclass
class PlateAssignment:
    plate_index: int
    placement_id: uuid.UUID
    insert_design_id: uuid.UUID
    x_mm: float  # plate-local, not drawer-local
    y_mm: float
    rotated: bool


@dataclass
class PanelizeResult:
    plates: list[list[PlateAssignment]]
    unplaced: list[Unplaced]  # reused from drawer_layout.py


def _to_pack_item(item: PanelizeItem) -> PackItem:
    # `height_mm` is irrelevant to panelization (a printer bed has no
    # "inside height" ceiling the way a drawer does -- that's a slicer/Z-axis
    # concern, out of scope per the plan) -- 0.0 is an inert placeholder,
    # never read by `pack()` itself (only by `filter_by_height`, which this
    # module deliberately never calls).
    return PackItem(
        tool_id=item.placement_id,
        insert_design_id=item.insert_design_id,
        width_mm=item.width_mm,
        depth_mm=item.depth_mm,
        height_mm=0.0,
        label=item.label,
    )


def panelize(items: list[PanelizeItem], bed_width_mm: float, bed_depth_mm: float) -> PanelizeResult:
    """Packs `items` onto as many `bed_width_mm` x `bed_depth_mm` plates as it
    takes, reusing `pack()`'s existing MaxRects heuristic per plate (first-fit
    sequential plate assignment, not a bin-count-minimizing global optimizer
    -- same "well-established heuristic, not globally optimal" stance
    `drawer_layout.py` already takes for the single-bin case).

    1. Pre-filter: any item whose footprint (either orientation) exceeds the
       bed even alone goes straight to `unplaced` with reason "exceeds
       printer bed" -- permanently unplaceable, never retried on a later
       plate (same "can never fit regardless of packing" logic
       `filter_by_height` already uses for drawer height).
    2. Loop up to `MAX_PLATES`: `pack(remaining, ...)` -> that round's
       placements become the next plate; `remaining` becomes the "no space"
       unplaced items fed into the next round. If a round places nothing but
       items remain (defensive -- shouldn't happen given step 1), stop and
       dump `remaining` as "no space" rather than looping forever.
    3. If `MAX_PLATES` is exhausted with items left, dump the rest as
       "exceeds max plate count" -- never silently truncate.
    """
    eligible: list[PanelizeItem] = []
    unplaced: list[Unplaced] = []

    for item in items:
        fits_upright = item.width_mm <= bed_width_mm and item.depth_mm <= bed_depth_mm
        fits_rotated = item.depth_mm <= bed_width_mm and item.width_mm <= bed_depth_mm
        if not fits_upright and not fits_rotated:
            unplaced.append(
                Unplaced(tool_id=item.placement_id, insert_design_id=item.insert_design_id, reason="exceeds printer bed")
            )
        else:
            eligible.append(item)

    by_placement_id = {item.placement_id: item for item in eligible}
    remaining = [_to_pack_item(item) for item in eligible]
    plates: list[list[PlateAssignment]] = []

    while remaining and len(plates) < MAX_PLATES:
        result = pack(remaining, bed_width_mm, bed_depth_mm)

        if not result.placements:
            # Defensive: step 1 already filtered out anything that can never
            # fit a blank plate, so an empty-plate result with items still
            # remaining shouldn't happen -- but never loop forever if it does.
            for u in result.unplaced:
                unplaced.append(Unplaced(tool_id=u.tool_id, insert_design_id=u.insert_design_id, reason="no space"))
            remaining = []
            break

        plate_index = len(plates)
        plates.append(
            [
                PlateAssignment(
                    plate_index=plate_index,
                    placement_id=p.tool_id,
                    insert_design_id=p.insert_design_id,
                    x_mm=p.x_mm,
                    y_mm=p.y_mm,
                    rotated=p.rotated,
                )
                for p in result.placements
            ]
        )

        remaining = [_to_pack_item(by_placement_id[u.tool_id]) for u in result.unplaced]

    if remaining:
        for pack_item in remaining:
            unplaced.append(
                Unplaced(
                    tool_id=pack_item.tool_id,
                    insert_design_id=pack_item.insert_design_id,
                    reason="exceeds max plate count",
                )
            )

    return PanelizeResult(plates=plates, unplaced=unplaced)
