import zipfile
from pathlib import Path
from workshop_geometry import inspect_3mf

MODEL="""<?xml version="1.0"?><model unit="millimeter" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"><resources><object id="1" name="Label"><mesh><vertices><vertex x="0" y="0" z="0"/><vertex x="10" y="0" z="0"/><vertex x="0" y="5" z="0"/><vertex x="0" y="0" z="2"/></vertices><triangles><triangle v1="0" v2="1" v3="2"/></triangles></mesh></object></resources><build><item objectid="1"/></build></model>"""
def test_inspect_3mf(tmp_path:Path):
    p=tmp_path/"sample.3mf"
    with zipfile.ZipFile(p,"w") as z: z.writestr("3D/model.model",MODEL)
    r=inspect_3mf(p)
    assert r.object_count==1 and r.build_item_count==1
    b=r.objects[0].bounds_mm
    assert b and b.width==10 and b.depth==5 and b.height==2
