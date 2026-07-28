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

def test_sealed_pocket_shifts_cavity_up_and_shrinks_skin():
    """seal_cap_mm>0 (the print-in-place "sealed" fit type) must move the
    cavity up by exactly that much, leaving room for a solid cap below
    z=0 -- the opposite side from the unsealed case's open recess."""
    p=LabelParameters(text="Wrenches",magnets=MagnetPocketParameters(seal_cap_mm=1.0))
    metrics=calculate_metrics(p)
    assert all(pocket.seal_cap_mm==pytest.approx(1.0) for pocket in metrics.magnet_pockets)
    assert all(pocket.remaining_top_skin_mm==pytest.approx(1.05) for pocket in metrics.magnet_pockets)
    model=generate_label(p)
    for tool in model.magnet_tools:
        assert tool.bounds[0][2]==pytest.approx(1.0,abs=0.01)
        assert tool.bounds[1][2]==pytest.approx(3.5,abs=0.01)

def test_sealed_pocket_caps_the_opening_with_solid_material():
    """The whole point of seal_cap_mm: unlike the default open recess,
    there must actually be solid outline material directly over the
    pocket (z in [0, seal_cap_mm)), not empty space -- otherwise pausing
    and resuming a print wouldn't actually seal the magnet in."""
    p=LabelParameters(text="Wrenches",magnets=MagnetPocketParameters(seal_cap_mm=1.0))
    model=generate_label(p)
    assert model.outline_body.is_watertight and model.text_body.is_watertight
    pocket=model.metrics.magnet_pockets[0]
    point=[[pocket.x_mm,pocket.y_mm,0.5]]
    assert model.outline_body.contains(point)[0]

def test_sealed_pocket_rejects_cap_plus_depth_exceeding_body():
    p=LabelParameters(text="Wrenches",body_depth_mm=3.0,magnets=MagnetPocketParameters(depth_clearance_mm=0.2,thickness_mm=2.3,seal_cap_mm=0.6))
    with pytest.raises(ValueError,match="leave material above the pocket"):
        calculate_metrics(p)

def _outline_component_count(mesh):
    """Connected-component count over face adjacency via plain union-find --
    trimesh's own `mesh.split()` needs scipy or networkx, neither of which
    is a dependency of this package, so this avoids adding one just for a
    test."""
    n=len(mesh.faces); parent=list(range(n))
    def find(x):
        while parent[x]!=x: parent[x]=parent[parent[x]]; x=parent[x]
        return x
    for a,b in mesh.face_adjacency:
        ra,rb=find(a),find(b)
        if ra!=rb: parent[ra]=rb
    return len({find(i) for i in range(n)})

@pytest.mark.parametrize("text",["1/2","13/16","3/8 -- 1/4","Wrenches","1/2 Drive","3/8 Ratchet","Pliers - Needle Nose","o","B"])
def test_outline_component_count_matches_border_plus_holes(text):
    """Regression test covering two fixes at once.

    Border bridging: a label's outline is its physical backing plate, so
    its outer border must come out as one connected piece even when the
    text buffers into several disjoint islands -- confirmed to happen not
    just across a space between words, but even within a single "word" or
    number (e.g. the italic slash in "1/2" sits far enough from both digits
    to buffer into its own island). Before the fix, each of these produced
    multiple disconnected border fragments -- physically several floating
    pieces, not one label.

    Hole filling: the outline body is that one-piece border plus one filled
    disc per letter/digit counter (the "6", "8", "9", "o", "B", ... hole
    fix). Each hole-fill disc is its own disconnected piece within this
    mesh, same as how individual letters are already disconnected pieces
    within `text_body` -- it doesn't need to touch the border directly
    because it's fully enclosed by the letter's own stroke (`text_body`) on
    every side, which locks it in place physically. So the right invariant
    isn't "exactly one piece" once holes are involved -- it's exactly
    1 + (hole count), computed fresh per case rather than assumed, since
    which digits/letters have a hole depends on this engine's exact font.
    """
    from workshop_geometry.label_engine import _parts,_text_geometry
    p=LabelParameters(text=text)
    text_geom,_=_text_geometry(p)
    hole_count=sum(len(part.interiors) for part in _parts(text_geom))
    model=generate_label(p)
    assert model.outline_body.is_watertight
    assert _outline_component_count(model.outline_body)==1+hole_count

def test_text_geometry_cuts_letter_counters():
    """Regression test: letters with an enclosed counter (the hole in "o",
    "e", "a", ...) must come back with that area as a real shapely interior
    ring, not filled-in solid area. `TextPath.to_polygons()` returns every
    closed contour of every glyph as a bare point loop with no hole/winding
    flag -- naively unioning them (the previous behavior here) treats a
    counter's contour as more solid fill instead of a subtraction, so "for
    the" printed both counters ("o", "e") in solid, no hole at all.
    """
    from workshop_geometry.label_engine import _parts,_text_geometry
    text,_=_text_geometry(LabelParameters(text="for the"))
    assert sum(len(part.interiors) for part in _parts(text))==2

def test_letter_holes_are_filled_with_outline_not_void_or_text():
    """A letter's counter (the hole in "o", "e", ...) must show up as
    outline-colored fill -- not the letter's own color (that's still just
    the original "solid letter" bug) and not an actual void either (a real
    physical gap -- this label is a flat two-color plate that should tile
    its whole footprint, not one with punched-through holes in some
    letters). So the hole center must be inside `outline_body` and outside
    `text_body`.
    """
    pytest.importorskip("rtree")  # trimesh.Trimesh.contains() needs it for ray queries
    from workshop_geometry.label_engine import _parts,_text_geometry
    from shapely.geometry import Polygon
    p=LabelParameters(text="Wrenches")
    text,_=_text_geometry(p)
    hole_part=next(part for part in _parts(text) if part.interiors)
    hole_center=Polygon(hole_part.interiors[0]).centroid
    model=generate_label(p)
    z=model.parameters.body_depth_mm/2
    point=[[hole_center.x,hole_center.y,z]]
    assert not model.text_body.contains(point)[0]
    assert model.outline_body.contains(point)[0]

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
