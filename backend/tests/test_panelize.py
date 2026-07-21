from __future__ import annotations

import uuid

from app.services.panelize import MAX_PLATES, PanelizeItem, panelize

# M3 Phase 5 (Print-Bed Panelization) pure unit tests -- no DB, mirrors
# `drawer_layout.py`'s own test style (computational invariant checks, not
# golden output): no overlap within a plate, every assignment within
# [0, bed_width] x [0, bed_depth], every input item appears in exactly one
# plate or in `unplaced`, never both/neither.


def _item(width_mm: float = 10.0, depth_mm: float = 10.0, label: str = "item") -> PanelizeItem:
    return PanelizeItem(
        placement_id=uuid.uuid4(),
        insert_design_id=uuid.uuid4(),
        width_mm=width_mm,
        depth_mm=depth_mm,
        label=label,
    )


def _rects_overlap(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    eps = 1e-6
    return not (ax >= bx + bw - eps or ax + aw <= bx + eps or ay >= by + bh - eps or ay + ah <= by + eps)


def _assert_no_overlap_within_plate(plate, bed_width_mm: float, bed_depth_mm: float) -> None:
    """`PlateAssignment` deliberately carries no width/depth (plate-local
    x/y + rotated flag only, see `panelize.py`) -- this helper is only valid
    for callers that build every item as a 10x10 square (rotation is a no-op
    for a square, so the placed footprint is always 10x10 regardless)."""
    rects = []
    for a in plate:
        w, h = (10.0, 10.0)
        rects.append((a.x_mm, a.y_mm, w, h))
    for i in range(len(rects)):
        for j in range(i + 1, len(rects)):
            assert not _rects_overlap(rects[i], rects[j]), f"overlap between assignment {i} and {j}"
        x, y, w, h = rects[i]
        assert x >= -1e-6 and y >= -1e-6
        assert x + w <= bed_width_mm + 1e-6
        assert y + h <= bed_depth_mm + 1e-6


def test_all_items_fit_one_plate() -> None:
    items = [_item(10.0, 10.0, f"item-{i}") for i in range(4)]
    result = panelize(items, bed_width_mm=25.0, bed_depth_mm=25.0)

    assert result.unplaced == []
    assert len(result.plates) == 1
    assert len(result.plates[0]) == 4
    _assert_no_overlap_within_plate(result.plates[0], 25.0, 25.0)

    placed_ids = {a.placement_id for a in result.plates[0]}
    assert placed_ids == {item.placement_id for item in items}


def test_every_item_appears_exactly_once_plate_or_unplaced() -> None:
    items = [_item(10.0, 10.0, f"item-{i}") for i in range(9)]
    # 20x20 bed only fits 4 of these 10x10 items per plate.
    result = panelize(items, bed_width_mm=20.0, bed_depth_mm=20.0)

    all_input_ids = {item.placement_id for item in items}
    placed_ids: set[uuid.UUID] = set()
    for plate in result.plates:
        for a in plate:
            assert a.placement_id not in placed_ids, "item placed on more than one plate"
            placed_ids.add(a.placement_id)

    unplaced_ids = {u.tool_id for u in result.unplaced}
    assert not (placed_ids & unplaced_ids), "item is both placed and unplaced"
    assert placed_ids | unplaced_ids == all_input_ids, "some item is neither placed nor unplaced"


def test_multi_plate_five_items_four_per_plate() -> None:
    # 5 items that fit 4-per-plate on a 20x20 bed (10x10 items) -> 2 plates.
    items = [_item(10.0, 10.0, f"item-{i}") for i in range(5)]
    result = panelize(items, bed_width_mm=20.0, bed_depth_mm=20.0)

    assert result.unplaced == []
    assert len(result.plates) == 2
    total_placed = sum(len(p) for p in result.plates)
    assert total_placed == 5
    # First plate should be full (4), second should have the leftover (1).
    plate_sizes = sorted(len(p) for p in result.plates)
    assert plate_sizes == [1, 4]

    for plate in result.plates:
        _assert_no_overlap_within_plate(plate, 20.0, 20.0)


def test_item_bigger_than_bed_in_either_orientation_is_unplaced_immediately() -> None:
    huge = _item(width_mm=500.0, depth_mm=500.0, label="huge")
    small = _item(width_mm=10.0, depth_mm=10.0, label="small")
    result = panelize([huge, small], bed_width_mm=100.0, bed_depth_mm=100.0)

    assert len(result.unplaced) == 1
    assert result.unplaced[0].tool_id == huge.placement_id
    assert result.unplaced[0].reason == "exceeds printer bed"

    # The small item still gets placed normally, on its own plate.
    assert len(result.plates) == 1
    assert len(result.plates[0]) == 1
    assert result.plates[0][0].placement_id == small.placement_id


def test_item_fitting_only_when_rotated_is_not_pre_filtered() -> None:
    # 15mm x 5mm item on a 10mm x 20mm bed: doesn't fit upright (15 > 10) but
    # does fit rotated (5 <= 10, 15 <= 20) -- must NOT be pre-filtered as
    # "exceeds printer bed".
    item = _item(width_mm=15.0, depth_mm=5.0, label="long-thin")
    result = panelize([item], bed_width_mm=10.0, bed_depth_mm=20.0)

    assert result.unplaced == []
    assert len(result.plates) == 1
    assert len(result.plates[0]) == 1


def test_max_plates_cap_ends_in_exceeds_max_plate_count_not_hang() -> None:
    # Each item takes a whole plate to itself (bed is exactly one item big),
    # so N items always need N plates -- comfortably exceed MAX_PLATES to
    # force the cap.
    items = [_item(10.0, 10.0, f"item-{i}") for i in range(MAX_PLATES + 5)]
    result = panelize(items, bed_width_mm=10.0, bed_depth_mm=10.0)

    assert len(result.plates) == MAX_PLATES
    assert len(result.unplaced) == 5
    assert all(u.reason == "exceeds max plate count" for u in result.unplaced)

    # Total accounted for exactly once.
    placed_ids = {a.placement_id for plate in result.plates for a in plate}
    unplaced_ids = {u.tool_id for u in result.unplaced}
    assert len(placed_ids) == MAX_PLATES
    assert not (placed_ids & unplaced_ids)
    assert placed_ids | unplaced_ids == {item.placement_id for item in items}


def test_empty_items_produces_empty_result() -> None:
    result = panelize([], bed_width_mm=100.0, bed_depth_mm=100.0)
    assert result.plates == []
    assert result.unplaced == []
