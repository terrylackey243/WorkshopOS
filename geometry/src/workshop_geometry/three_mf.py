from __future__ import annotations
import json, math, zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

@dataclass(frozen=True)
class Bounds3D:
    min_x: float; min_y: float; min_z: float
    max_x: float; max_y: float; max_z: float
    @property
    def width(self): return self.max_x-self.min_x
    @property
    def depth(self): return self.max_y-self.min_y
    @property
    def height(self): return self.max_z-self.min_z

@dataclass(frozen=True)
class ObjectReport:
    object_id: str
    name: str|None
    vertex_count: int
    triangle_count: int
    bounds_mm: Bounds3D|None

@dataclass(frozen=True)
class ThreeMFReport:
    source_file: str
    unit: str
    scale_to_mm: float
    metadata: dict[str,str]
    object_count: int
    build_item_count: int
    objects: list[ObjectReport]

UNIT_TO_MM={"micron":0.001,"millimeter":1.0,"centimeter":10.0,"inch":25.4,"foot":304.8,"meter":1000.0}

def _ns(tag:str)->str:
    return tag.split("}",1)[0]+"}" if tag.startswith("{") else ""

def _bounds(vertices,scale):
    if not vertices: return None
    xs=[x*scale for x,_,_ in vertices]; ys=[y*scale for _,y,_ in vertices]; zs=[z*scale for _,_,z in vertices]
    if not all(math.isfinite(v) for v in (*xs,*ys,*zs)): raise ValueError("Non-finite vertex coordinate.")
    return Bounds3D(min(xs),min(ys),min(zs),max(xs),max(ys),max(zs))

def inspect_3mf(path:str|Path)->ThreeMFReport:
    source=Path(path)
    with zipfile.ZipFile(source) as archive:
        models=sorted(n for n in archive.namelist() if n.lower().endswith(".model"))
        if not models: raise ValueError("No 3MF model document found.")
        root=ET.fromstring(archive.read(models[0]))
    ns=_ns(root.tag); unit=root.attrib.get("unit","millimeter").lower()
    scale=UNIT_TO_MM.get(unit)
    if scale is None: raise ValueError(f"Unsupported 3MF unit: {unit}")
    metadata={n.attrib["name"]:(n.text or "") for n in root.findall(f"{ns}metadata") if "name" in n.attrib}
    objects=[]
    resources=root.find(f"{ns}resources")
    if resources is not None:
        for obj in resources.findall(f"{ns}object"):
            mesh=obj.find(f"{ns}mesh"); vertices=[]; triangles=0
            if mesh is not None:
                vn=mesh.find(f"{ns}vertices")
                if vn is not None:
                    vertices=[(float(v.attrib["x"]),float(v.attrib["y"]),float(v.attrib["z"])) for v in vn.findall(f"{ns}vertex")]
                tn=mesh.find(f"{ns}triangles")
                triangles=0 if tn is None else len(tn.findall(f"{ns}triangle"))
            objects.append(ObjectReport(obj.attrib.get("id",""),obj.attrib.get("name"),len(vertices),triangles,_bounds(vertices,scale)))
    build=root.find(f"{ns}build")
    build_count=0 if build is None else len(build.findall(f"{ns}item"))
    return ThreeMFReport(str(source),unit,scale,metadata,len(objects),build_count,objects)

def report_to_dict(report): return asdict(report)
def write_json_report(report,path): Path(path).write_text(json.dumps(report_to_dict(report),indent=2)+"\n",encoding="utf-8")
