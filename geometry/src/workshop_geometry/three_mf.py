from __future__ import annotations
import io, json, math, zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

import trimesh

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

# --- Colored multi-body export -----------------------------------------------
#
# 3MF Core Specification namespace. `basematerials` (and the `pid`/`pindex`
# attributes objects use to reference a color within it) are part of the
# *core* spec, not a material extension -- no separate namespace needed.
_MODEL_NS = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
_RELS_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_CONTENT_TYPES_NS = "http://schemas.openxmlformats.org/package/2006/content-types"

def _q(tag: str, ns: str = _MODEL_NS) -> str:
    """Clark-notation qualified tag (`{ns}tag`) -- paired with
    `ET.register_namespace("", _MODEL_NS)` in `export_colored_3mf`, this
    makes ElementTree serialize every core-namespace element with a bare
    `xmlns="..."` default namespace and no prefix, matching how real-world
    3MF files (and every slicer's own writer) are actually formatted."""
    return f"{{{ns}}}{tag}"

def export_colored_3mf(bodies: list[tuple[trimesh.Trimesh, str, str]], include_colors: bool = True) -> bytes:
    """Combine multiple trimesh bodies into a single 3MF file.

    `bodies` is `[(mesh, object_name, hex_color), ...]`, e.g.
    `[(outline_body, "outline", "#9ca3af"), (text_body, "text", "#22c55e")]`.
    Every body is written with an identity transform (no repositioning) --
    correct here because label bodies are already co-located in one shared
    coordinate frame by `generate_label()`, the same reason the browser
    preview overlays their STLs directly with no transform of its own.

    With `include_colors=True` (the default), each object's color is baked
    in via a `<basematerials>` resource + `pid`/`pindex`, so a slicer
    (Bambu Studio, PrusaSlicer, OrcaSlicer) auto-assigns a filament/color
    per object on import instead of requiring the user to manually recolor
    each part. `include_colors=False` skips all of that, writing bare,
    uncolored geometry only -- confirmed (empirically, against a real
    third-party slicer with an unusually strict/limited 3MF reader) to be
    the more broadly-compatible option: some slicers reject `basematerials`
    outright even though it's core-spec, not an extension. Every color in
    `bodies` is still required for API consistency even when unused, so
    swapping `include_colors` doesn't change the call site.

    Hand-rolled rather than trimesh's own `export_3MF`: that exporter
    writes valid multi-object 3MF (each body as its own `<object>`/`<item>`,
    correctly positioned) but has no support for `<basematerials>` or the
    `pid`/`pindex` attributes an object needs to reference a color -- see
    trimesh/exchange/threemf.py. This only implements the minimal subset of
    the 3MF core spec every mainstream slicer actually reads for
    color-per-object, confirmed structurally valid in this package's test
    suite by round-tripping through both `inspect_3mf` above and trimesh's
    own (unrelated, color-blind) 3MF *importer*.
    """
    ET.register_namespace("", _MODEL_NS)
    model = ET.Element(_q("model"), {"unit": "millimeter"})
    resources = ET.SubElement(model, _q("resources"))

    if include_colors:
        basematerials = ET.SubElement(resources, _q("basematerials"), {"id": "1"})
        for _, name, hex_color in bodies:
            rgb = hex_color.lstrip("#").upper()
            ET.SubElement(basematerials, _q("base"), {"name": name, "displaycolor": f"#{rgb}FF"})

    build = ET.SubElement(model, _q("build"))
    for index, (mesh, name, _) in enumerate(bodies):
        object_id = index + 2  # id 1 is already taken by the basematerials resource (if present)
        attribs = {"id": str(object_id), "name": name, "type": "model"}
        if include_colors:
            attribs["pid"] = "1"
            attribs["pindex"] = str(index)
        obj = ET.SubElement(resources, _q("object"), attribs)
        mesh_el = ET.SubElement(obj, _q("mesh"))
        vertices_el = ET.SubElement(mesh_el, _q("vertices"))
        for x, y, z in mesh.vertices:
            ET.SubElement(vertices_el, _q("vertex"), {"x": f"{x:.6f}", "y": f"{y:.6f}", "z": f"{z:.6f}"})
        triangles_el = ET.SubElement(mesh_el, _q("triangles"))
        for a, b, c in mesh.faces:
            ET.SubElement(triangles_el, _q("triangle"), {"v1": str(int(a)), "v2": str(int(b)), "v3": str(int(c))})
        ET.SubElement(build, _q("item"), {"objectid": str(object_id)})

    model_xml = b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(model, encoding="utf-8")

    rels = ET.Element(_q("Relationships", _RELS_NS))
    ET.SubElement(
        rels,
        _q("Relationship", _RELS_NS),
        {
            "Id": "rel0",
            "Type": "http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel",
            "Target": "/3D/3dmodel.model",
        },
    )
    rels_xml = b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(rels, encoding="utf-8")

    content_types = ET.Element(_q("Types", _CONTENT_TYPES_NS))
    ET.SubElement(
        content_types,
        _q("Default", _CONTENT_TYPES_NS),
        {"Extension": "rels", "ContentType": "application/vnd.openxmlformats-package.relationships+xml"},
    )
    ET.SubElement(
        content_types,
        _q("Default", _CONTENT_TYPES_NS),
        {"Extension": "model", "ContentType": "application/vnd.ms-package.3dmanufacturing-3dmodel+xml"},
    )
    content_types_xml = b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(content_types, encoding="utf-8")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types_xml)
        zf.writestr("_rels/.rels", rels_xml)
        zf.writestr("3D/3dmodel.model", model_xml)
    return buffer.getvalue()
