from __future__ import annotations
import math, zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

@dataclass(frozen=True)
class Bounds3D:
    min_x:float; min_y:float; min_z:float; max_x:float; max_y:float; max_z:float
    @property
    def width(self): return self.max_x-self.min_x
    @property
    def depth(self): return self.max_y-self.min_y
    @property
    def height(self): return self.max_z-self.min_z

@dataclass(frozen=True)
class ObjectStructure:
    object_id:str; name:str|None; vertex_count:int; triangle_count:int; component_count:int
    bounds_mm:Bounds3D|None; z_levels_mm:list[float]; property_ids:list[str]; likely_role:str

@dataclass(frozen=True)
class MeshStructureReport:
    source_file:str; unit:str; object_count:int; build_item_count:int
    metadata:dict[str,str]; objects:list[ObjectStructure]; likely_relationship:str

UNIT_TO_MM={'micron':0.001,'millimeter':1.0,'centimeter':10.0,'inch':25.4,'foot':304.8,'meter':1000.0}

def _ns(tag:str)->str: return tag.split('}',1)[0]+'}' if tag.startswith('{') else ''

def _bounds(vertices,scale):
    if not vertices:return None
    pts=[(x*scale,y*scale,z*scale) for x,y,z in vertices]
    vals=[v for p in pts for v in p]
    if not all(math.isfinite(v) for v in vals): raise ValueError('Non-finite coordinate')
    xs=[p[0] for p in pts]; ys=[p[1] for p in pts]; zs=[p[2] for p in pts]
    return Bounds3D(min(xs),min(ys),min(zs),max(xs),max(ys),max(zs))

def _role(bounds):
    if bounds is None:return 'non-mesh object'
    if bounds.height<=2.6:return 'likely secondary color/text/inlay object'
    if bounds.height>=4.0:return 'likely main label body'
    return 'undetermined mesh'

def inspect_mesh_structure(path:str|Path)->MeshStructureReport:
    source=Path(path)
    with zipfile.ZipFile(source) as z:
        models=sorted(n for n in z.namelist() if n.lower().endswith('.model'))
        if not models: raise ValueError('No 3MF model document found')
        root=ET.fromstring(z.read(models[0]))
    ns=_ns(root.tag); unit=root.attrib.get('unit','millimeter').lower(); scale=UNIT_TO_MM.get(unit)
    if scale is None: raise ValueError(f'Unsupported 3MF unit: {unit}')
    metadata={n.attrib['name']:(n.text or '') for n in root.findall(f'{ns}metadata') if 'name' in n.attrib}
    objects=[]
    resources=root.find(f'{ns}resources')
    if resources is not None:
        for obj in resources.findall(f'{ns}object'):
            mesh=obj.find(f'{ns}mesh'); comps=obj.find(f'{ns}components'); vertices=[]; triangles=0; pids=set()
            if mesh is not None:
                vn=mesh.find(f'{ns}vertices')
                if vn is not None:
                    vertices=[(float(v.attrib['x']),float(v.attrib['y']),float(v.attrib['z'])) for v in vn.findall(f'{ns}vertex')]
                tn=mesh.find(f'{ns}triangles')
                if tn is not None:
                    ts=tn.findall(f'{ns}triangle'); triangles=len(ts); pids={t.attrib['pid'] for t in ts if 'pid' in t.attrib}
            comp_count=0 if comps is None else len(comps.findall(f'{ns}component'))
            b=_bounds(vertices,scale)
            objects.append(ObjectStructure(obj.attrib.get('id',''),obj.attrib.get('name'),len(vertices),triangles,comp_count,b,sorted({round(v[2]*scale,4) for v in vertices}),sorted(pids),_role(b)))
    build=root.find(f'{ns}build'); build_count=0 if build is None else len(build.findall(f'{ns}item'))
    relation='No two-object relationship could be inferred.'
    meshes=[o for o in objects if o.bounds_mm]
    if len(meshes)==2:
        a,b=sorted(meshes,key=lambda o:o.bounds_mm.height,reverse=True)
        if abs(a.bounds_mm.width-b.bounds_mm.width)<3 and abs(a.bounds_mm.depth-b.bounds_mm.depth)<3:
            relation='Likely main body plus separate color/text/inlay body.'
    return MeshStructureReport(str(source),unit,len(objects),build_count,metadata,objects,relation)

def report_to_dict(report): return asdict(report)
