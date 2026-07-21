import pytest
from workshop_geometry.label_engine import LabelParameters,MagnetPocketParameters,QR_SIZE_MM,calculate_metrics,generate_label,generation_manifest

def params(): return LabelParameters(text="Wrenches",magnets=MagnetPocketParameters())

def test_pockets_begin_at_zero():
    model=generate_label(params())
    for tool in model.magnet_tools:
        assert tool.bounds[0][2]==pytest.approx(0.0,abs=0.01)
        assert tool.bounds[1][2]==pytest.approx(2.5,abs=0.01)

def test_top_skin_remains():
    metrics=calculate_metrics(params())
    assert all(p.remaining_top_skin_mm==pytest.approx(2.05) for p in metrics.magnet_pockets)

def test_bodies_watertight():
    model=generate_label(params())
    assert model.outline_body.is_watertight and model.text_body.is_watertight

def test_manifest_orientation():
    manifest=generation_manifest(generate_label(params()))
    assert manifest["orientation"]["design_view"]=="face_up"
    assert manifest["orientation"]["magnet_opening_plane"]=="z=0"

def test_unlinked_label_has_no_qr_body():
    """Regression check: a label with no qr_url must produce exactly the
    same two bodies as before this feature existed -- QR generation must
    never trigger unless explicitly requested."""
    model = generate_label(params())
    assert model.qr_body is None
    manifest = generation_manifest(model)
    assert "qr_code" not in manifest["body_roles"]

def test_qr_body_produced_when_linked():
    model = generate_label(LabelParameters(text="Wrenches", qr_url="http://localhost:3027/tools/abc"))
    assert model.qr_body is not None
    assert model.qr_body.is_watertight
    manifest = generation_manifest(model)
    assert "qr_code" in manifest["body_roles"]

def test_qr_body_matches_target_footprint():
    model = generate_label(LabelParameters(text="Wrenches", qr_url="http://localhost:3027/tools/abc"))
    bounds = model.qr_body.bounds
    width = bounds[1][0] - bounds[0][0]
    depth = bounds[1][1] - bounds[0][1]
    assert width == pytest.approx(QR_SIZE_MM, abs=0.1)
    assert depth == pytest.approx(QR_SIZE_MM, abs=0.1)

def test_qr_body_actually_decodes_to_the_right_url():
    """Not just "some geometry was produced" -- an independent real QR
    decoder (zxing-cpp, a test-only dependency, see pyproject.toml) must
    read the extruded body's footprint back to the exact URL it was built
    from. This is the direct regression test for _qr_geometry's row/column
    -> Cartesian-y mapping: get that mapping backwards and the pattern is
    mirrored (not just rotated) and silently fails to scan -- nothing above
    this layer would ever catch that without decoding for real."""
    zxingcpp = pytest.importorskip("zxingcpp")
    from PIL import Image
    import numpy as np

    url = "http://localhost:3027/tools/9f8c9b1e-real-tool-id"
    model = generate_label(LabelParameters(text="Wrenches", qr_url=url))
    body = model.qr_body

    # Rasterize the QR body's own footprint (top-down, z doesn't matter --
    # this is a uniform-height extrusion) directly from its triangle mesh,
    # independent of qrcode's own matrix -- this tests the actual exported
    # geometry, not a re-derivation of the encoding step.
    minx, miny = body.bounds[0][0], body.bounds[0][1]
    maxx, maxy = body.bounds[1][0], body.bounds[1][1]
    res = 200
    xs = np.linspace(minx, maxx, res)
    ys = np.linspace(miny, maxy, res)
    grid_x, grid_y = np.meshgrid(xs, ys)
    z = (body.bounds[0][2] + body.bounds[1][2]) / 2
    points = np.column_stack([grid_x.ravel(), grid_y.ravel(), np.full(grid_x.size, z)])
    inside = body.contains(points).reshape(res, res)

    # Image row 0 = top = max Cartesian y (standard image<->Cartesian flip).
    img = np.where(inside[::-1, :], 0, 255).astype(np.uint8)
    pil_img = Image.fromarray(img, mode="L")

    results = zxingcpp.read_barcodes(pil_img)
    assert len(results) == 1, "QR body did not decode to exactly one barcode"
    assert results[0].text == url
