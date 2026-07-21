import pytest
from workshop_geometry.bin_engine import (
    BASE_HEIGHT_MM,
    HEIGHT_UNIT_MM,
    LIP_HEIGHT_MM,
    BinParameters,
    calculate_metrics,
    generate_bin,
    generation_manifest,
)


def expected_dims(p: BinParameters) -> tuple[float, float, float]:
    width = 42 * p.grid_width_units - 0.5
    depth = 42 * p.grid_depth_units - 0.5
    height = BASE_HEIGHT_MM + p.height_units * HEIGHT_UNIT_MM + (LIP_HEIGHT_MM if p.include_stacking_lip else 0.0)
    return width, depth, height


@pytest.mark.parametrize(
    "params",
    [
        BinParameters(grid_width_units=1, grid_depth_units=1, height_units=3),
        BinParameters(grid_width_units=1, grid_depth_units=1, height_units=3, include_stacking_lip=False),
        BinParameters(grid_width_units=2, grid_depth_units=3, height_units=4),
        BinParameters(grid_width_units=2, grid_depth_units=3, height_units=4, include_stacking_lip=False),
        BinParameters(
            grid_width_units=2, grid_depth_units=3, height_units=4, compartments_x=2, compartments_y=3
        ),
        BinParameters(
            grid_width_units=2,
            grid_depth_units=2,
            height_units=3,
            magnet_diameter_mm=6.0,
            magnet_thickness_mm=2.0,
        ),
        BinParameters(
            grid_width_units=2,
            grid_depth_units=2,
            height_units=3,
            include_stacking_lip=False,
            magnet_diameter_mm=6.0,
            magnet_thickness_mm=2.0,
            compartments_x=2,
        ),
    ],
)
def test_bin_is_watertight_and_dimensionally_correct(params: BinParameters) -> None:
    model = generate_bin(params)
    body = model.body
    assert body.is_watertight
    assert body.is_winding_consistent

    expected_w, expected_d, expected_h = expected_dims(params)
    bounds = body.bounds
    actual_w = bounds[1][0] - bounds[0][0]
    actual_d = bounds[1][1] - bounds[0][1]
    actual_h = bounds[1][2] - bounds[0][2]

    assert actual_w == pytest.approx(expected_w, abs=0.2)
    assert actual_d == pytest.approx(expected_d, abs=0.2)
    assert actual_h == pytest.approx(expected_h, abs=0.2)

    # Bottom sits flush on the build plate, top rim at the full nominal height.
    assert bounds[0][2] == pytest.approx(0.0, abs=0.01)


def test_metrics_match_bounds_formula() -> None:
    params = BinParameters(grid_width_units=3, grid_depth_units=2, height_units=5, include_stacking_lip=True)
    metrics = calculate_metrics(params)
    assert metrics.width_mm == pytest.approx(125.5)
    assert metrics.depth_mm == pytest.approx(83.5)
    assert metrics.height_mm == pytest.approx(4.75 + 5 * 7 + LIP_HEIGHT_MM)


def test_magnet_hole_count() -> None:
    params = BinParameters(
        grid_width_units=2, grid_depth_units=3, height_units=1, magnet_diameter_mm=6.0, magnet_thickness_mm=2.0
    )
    metrics = calculate_metrics(params)
    assert metrics.magnet_hole_count == 4 * 2 * 3


def test_validate_rejects_uneven_compartments() -> None:
    with pytest.raises(ValueError, match="compartments_x"):
        BinParameters(grid_width_units=2, grid_depth_units=1, height_units=1, compartments_x=3).validate()


def test_validate_rejects_nonpositive_units() -> None:
    with pytest.raises(ValueError):
        BinParameters(grid_width_units=0, grid_depth_units=1, height_units=1).validate()


def test_validate_rejects_oversized_magnet_hole() -> None:
    with pytest.raises(ValueError, match="base profile"):
        BinParameters(
            grid_width_units=1, grid_depth_units=1, height_units=1, magnet_diameter_mm=6.0, magnet_thickness_mm=10.0
        ).validate()


def test_manifest_orientation_and_checksum() -> None:
    model = generate_bin(BinParameters(grid_width_units=1, grid_depth_units=1, height_units=2))
    manifest = generation_manifest(model)
    assert manifest["orientation"]["build_plate_plane"] == "z=0"
    assert manifest["body_roles"] == ["bin_body"]
    assert len(manifest["parameter_checksum_sha256"]) == 64
    int(manifest["parameter_checksum_sha256"], 16)
