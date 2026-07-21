import zipfile
from pathlib import Path
from workshop_geometry.mesh_structure import inspect_mesh_structure
MODEL="""<?xml version="1.0"?><model unit="millimeter" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"><resources><object id="2" name="Main"><mesh><vertices><vertex x="0" y="0" z="0"/><vertex x="50" y="0" z="0"/><vertex x="0" y="16" z="0"/><vertex x="0" y="0" z="4.55"/></vertices><triangles><triangle v1="0" v2="1" v3="2" pid="7"/></triangles></mesh></object><object id="3" name="Text"><mesh><vertices><vertex x="1.2" y="1.1" z="2.2"/><vertex x="48.8" y="1.1" z="2.2"/><vertex x="1.2" y="14.9" z="2.2"/><vertex x="1.2" y="1.1" z="4.55"/></vertices><triangles><triangle v1="0" v2="1" v3="2" pid="8"/></triangles></mesh></object></resources><build><item objectid="2"/><item objectid="3"/></build></model>"""
def test_structure(tmp_path:Path):
 p=tmp_path/"sample.3mf"
 with zipfile.ZipFile(p,"w") as z:z.writestr("3D/model.model",MODEL)
 r=inspect_mesh_structure(p)
 assert r.object_count==2 and r.build_item_count==2
 assert r.objects[0].likely_role=="likely main label body"
 assert r.objects[1].likely_role=="likely secondary color/text/inlay object"
 assert r.objects[0].property_ids==["7"]
