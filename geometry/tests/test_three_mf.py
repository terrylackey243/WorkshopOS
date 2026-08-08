import io
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import trimesh

from workshop_geometry import export_colored_3mf, inspect_3mf

MODEL="""<?xml version="1.0"?><model unit="millimeter" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"><resources><object id="1" name="Label"><mesh><vertices><vertex x="0" y="0" z="0"/><vertex x="10" y="0" z="0"/><vertex x="0" y="5" z="0"/><vertex x="0" y="0" z="2"/></vertices><triangles><triangle v1="0" v2="1" v3="2"/></triangles></mesh></object></resources><build><item objectid="1"/></build></model>"""
def test_inspect_3mf(tmp_path:Path):
    p=tmp_path/"sample.3mf"
    with zipfile.ZipFile(p,"w") as z: z.writestr("3D/model.model",MODEL)
    r=inspect_3mf(p)
    assert r.object_count==1 and r.build_item_count==1
    b=r.objects[0].bounds_mm
    assert b and b.width==10 and b.depth==5 and b.height==2

def _colored_bodies():
    outline = trimesh.creation.box(extents=(20, 10, 4))
    text = trimesh.creation.box(extents=(5, 5, 4))
    return [(outline, "outline", "#9ca3af"), (text, "text", "#22c55e")]

def test_export_colored_3mf_structurally_valid(tmp_path: Path):
    """Independent structural check via this package's own `inspect_3mf`
    reader (which doesn't know or care about the color/material XML this
    export adds) -- confirms the geometry itself round-trips correctly."""
    bodies = _colored_bodies()
    data = export_colored_3mf(bodies)
    p = tmp_path / "label.3mf"
    p.write_bytes(data)
    r = inspect_3mf(p)
    assert r.object_count == 2
    assert r.build_item_count == 2
    for obj, (mesh, name, _) in zip(r.objects, bodies):
        assert obj.name == name
        assert obj.vertex_count == len(mesh.vertices)
        assert obj.triangle_count == len(mesh.faces)

def test_export_colored_3mf_loads_in_trimesh(tmp_path: Path):
    """Round-trip through trimesh's own (independent, unrelated) 3MF
    *importer* -- a second, differently-implemented parser confirming this
    isn't just valid against this package's own reader."""
    bodies = _colored_bodies()
    data = export_colored_3mf(bodies)
    p = tmp_path / "label.3mf"
    p.write_bytes(data)
    scene = trimesh.load(p)
    assert isinstance(scene, trimesh.Scene)
    assert len(scene.geometry) == 2
    loaded = {name: len(mesh.faces) for name, mesh in scene.geometry.items()}
    for mesh, name, _ in bodies:
        assert loaded[name] == len(mesh.faces)

def test_export_colored_3mf_encodes_per_object_color():
    """The whole point of hand-rolling this instead of using trimesh's own
    export_3MF: each object must reference the right color via pid/pindex,
    not just contain valid geometry."""
    bodies = _colored_bodies()
    data = export_colored_3mf(bodies)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        root = ET.fromstring(z.read("3D/3dmodel.model"))
    ns = "{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"
    bases = root.findall(f"{ns}resources/{ns}basematerials/{ns}base")
    assert [b.attrib["displaycolor"] for b in bases] == ["#9CA3AFFF", "#22C55EFF"]
    objects = root.findall(f"{ns}resources/{ns}object")
    assert [o.attrib["pid"] for o in objects] == ["1", "1"]
    assert [o.attrib["pindex"] for o in objects] == ["0", "1"]

def test_export_colored_3mf_include_colors_false_omits_materials(tmp_path: Path):
    """label_engine.py ships with EXPORT_3MF_INCLUDE_COLORS=False, since a
    real third-party slicer with an unusually strict/limited 3MF reader
    rejected any file containing a `<basematerials>` resource outright.
    Geometry must still round-trip correctly with colors turned off."""
    bodies = _colored_bodies()
    data = export_colored_3mf(bodies, include_colors=False)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        root = ET.fromstring(z.read("3D/3dmodel.model"))
    ns = "{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"
    assert root.findall(f"{ns}resources/{ns}basematerials") == []
    objects = root.findall(f"{ns}resources/{ns}object")
    assert len(objects) == 2
    for obj in objects:
        assert "pid" not in obj.attrib
        assert "pindex" not in obj.attrib

    p = tmp_path / "label.3mf"
    p.write_bytes(data)
    r = inspect_3mf(p)
    assert r.object_count == 2
    assert r.build_item_count == 2
