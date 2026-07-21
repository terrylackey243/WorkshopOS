from __future__ import annotations

import uuid
from dataclasses import dataclass

# Real 2D rectangle bin-packing (MaxRects, free-rectangle-list algorithm) --
# the algorithm underlying M3 Phase 3 (drawer auto-layout). This is
# well-established CS (Jukka Jylanki's "A Thousand Ways to Pack the Bin",
# 2010) -- correctness is verified computationally (no two placements
# overlap, every placement is fully within the bin bounds; see
# `tests/test_drawer_layouts.py`), not by citing/copying a reference
# implementation.
#
# Heuristic choice: Best Area Fit (BAF), tied-broken by Best Short Side Fit.
# For each item, among every (free rectangle x orientation) combination the
# item fits into, we pick the one that leaves the least leftover area; ties
# are broken by the one that leaves the smallest leftover on its shorter
# side. Items are tried in their original (w, h) orientation before the
# rotated (h, w) orientation, so a square (or already-fitting) item is never
# reported as `rotated` just to break a tie.
#
# `pack()` is deliberately a pure 2D function -- it knows nothing about
# drawer height. Height is a per-item pass/fail check against the drawer's
# `inside_height_mm` (see `filter_by_height`), not part of 2D placement; the
# router runs that filter before calling `pack()` so oversized items are
# never attempted in the 2D pack at all.

EPS = 1e-6

Rect = tuple[float, float, float, float]  # (x, y, width, height)


@dataclass
class PackItem:
    tool_id: uuid.UUID
    insert_design_id: uuid.UUID
    width_mm: float
    depth_mm: float
    height_mm: float
    label: str


@dataclass
class Placement:
    tool_id: uuid.UUID
    insert_design_id: uuid.UUID
    x_mm: float
    y_mm: float
    width_mm: float
    depth_mm: float
    rotated: bool


@dataclass
class Unplaced:
    tool_id: uuid.UUID
    insert_design_id: uuid.UUID
    reason: str


@dataclass
class PackResult:
    placements: list[Placement]
    unplaced: list[Unplaced]
    utilization_pct: float


def filter_by_height(items: list[PackItem], inside_height_mm: float) -> tuple[list[PackItem], list[Unplaced]]:
    """Split `items` into (eligible for 2D packing, unplaced for height reasons).

    Called by the router *before* `pack()` -- items that can never fit
    (regardless of how good the packing is) are never attempted in the 2D
    algorithm.
    """
    eligible: list[PackItem] = []
    unplaced: list[Unplaced] = []
    for item in items:
        if item.height_mm > inside_height_mm + EPS:
            unplaced.append(
                Unplaced(tool_id=item.tool_id, insert_design_id=item.insert_design_id, reason="exceeds drawer height")
            )
        else:
            eligible.append(item)
    return eligible, unplaced


def _rects_intersect(a: Rect, b: Rect) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return not (ax >= bx + bw - EPS or ax + aw <= bx + EPS or ay >= by + bh - EPS or ay + ah <= by + EPS)


def _contains(outer: Rect, inner: Rect) -> bool:
    ox, oy, ow, oh = outer
    ix, iy, iw, ih = inner
    return ix >= ox - EPS and iy >= oy - EPS and ix + iw <= ox + ow + EPS and iy + ih <= oy + oh + EPS


def _split_free_rect(free_rect: Rect, placed: Rect) -> list[Rect]:
    """Standard MaxRects free-rectangle split: subtract `placed` from
    `free_rect`, producing up to 4 leftover candidate free rectangles (top,
    bottom, left, right slices). Callers must run `_prune_contained()`
    afterwards to drop rectangles fully contained within another."""
    fx, fy, fw, fh = free_rect
    px, py, pw, ph = placed

    if not _rects_intersect(free_rect, placed):
        return [free_rect]

    results: list[Rect] = []
    if px < fx + fw and px + pw > fx:
        if py > fy and py < fy + fh:
            results.append((fx, fy, fw, py - fy))  # slice above the placed rect
        if py + ph < fy + fh:
            results.append((fx, py + ph, fw, (fy + fh) - (py + ph)))  # slice below
    if py < fy + fh and py + ph > fy:
        if px > fx and px < fx + fw:
            results.append((fx, fy, px - fx, fh))  # slice left of the placed rect
        if px + pw < fx + fw:
            results.append((px + pw, fy, (fx + fw) - (px + pw), fh))  # slice right
    return [r for r in results if r[2] > EPS and r[3] > EPS]


def _prune_contained(rects: list[Rect]) -> list[Rect]:
    kept: list[Rect] = []
    for i, a in enumerate(rects):
        contained = False
        for j, b in enumerate(rects):
            if i == j:
                continue
            if _contains(b, a) and not (a == b and j < i):
                contained = True
                break
        if not contained:
            kept.append(a)
    return kept


def _find_best_placement(
    item_w: float, item_h: float, free_rects: list[Rect]
) -> tuple[float, float, float, float, bool] | None:
    """Best Area Fit (tie-broken by Best Short Side Fit) over every
    (free rectangle x orientation) combination the item fits into. Returns
    (x, y, placed_w, placed_h, rotated) for the winner, or None if the item
    fits nowhere."""
    best_score: tuple[float, float] | None = None
    best: tuple[float, float, float, float, bool] | None = None

    for fx, fy, fw, fh in free_rects:
        for pw, ph, rotated in ((item_w, item_h, False), (item_h, item_w, True)):
            if pw <= fw + EPS and ph <= fh + EPS:
                leftover_area = fw * fh - pw * ph
                short_side_leftover = min(fw - pw, fh - ph)
                score = (leftover_area, short_side_leftover)
                if best_score is None or score < best_score:
                    best_score = score
                    best = (fx, fy, pw, ph, rotated)

    return best


def pack(items: list[PackItem], bin_width_mm: float, bin_depth_mm: float) -> PackResult:
    """Classic MaxRects free-rectangle-list 2D bin packing, 90-degree
    rotation allowed. Items are sorted by descending area first (a standard,
    effective heuristic for this class of algorithm) so large items claim
    space while the free-rectangle list is still simple."""
    sorted_items = sorted(items, key=lambda i: i.width_mm * i.depth_mm, reverse=True)

    free_rects: list[Rect] = [(0.0, 0.0, bin_width_mm, bin_depth_mm)]
    placements: list[Placement] = []
    unplaced: list[Unplaced] = []

    for item in sorted_items:
        best = _find_best_placement(item.width_mm, item.depth_mm, free_rects)
        if best is None:
            unplaced.append(Unplaced(tool_id=item.tool_id, insert_design_id=item.insert_design_id, reason="no space"))
            continue

        x, y, pw, ph, rotated = best
        placements.append(
            Placement(
                tool_id=item.tool_id,
                insert_design_id=item.insert_design_id,
                x_mm=x,
                y_mm=y,
                width_mm=pw,
                depth_mm=ph,
                rotated=rotated,
            )
        )

        placed_rect: Rect = (x, y, pw, ph)
        new_free_rects: list[Rect] = []
        for free_rect in free_rects:
            new_free_rects.extend(_split_free_rect(free_rect, placed_rect))
        free_rects = _prune_contained(new_free_rects)

    bin_area = bin_width_mm * bin_depth_mm
    placed_area = sum(p.width_mm * p.depth_mm for p in placements)
    utilization_pct = (placed_area / bin_area * 100.0) if bin_area > EPS else 0.0

    return PackResult(placements=placements, unplaced=unplaced, utilization_pct=utilization_pct)
