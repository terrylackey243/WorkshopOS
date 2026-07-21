from __future__ import annotations
import hashlib, json
from dataclasses import asdict, dataclass
from pathlib import Path
import numpy as np, qrcode, trimesh
from matplotlib.font_manager import FontProperties, findfont
from matplotlib.textpath import TextPath
from shapely import affinity
from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union

ENGINE_VERSION="0.5.3"

# Fixed physical footprint for a label's QR body -- independent of the text
# label's own width/height (the QR is exported as its own separate STL body,
# not fused into the text/outline geometry, so it never affects the text
# label's existing width formula in calculate_metrics()). 15mm is comfortably
# scannable at typical phone-camera range for a workshop drawer/bin label.
QR_SIZE_MM = 15.0
# Fraction of body_depth_mm given to the QR body's solid base plate, with
# the rest as raised-module bump height. See _qr_body's docstring for why
# this is a solid base + bumps, not modules extruded standalone.
_QR_BASE_FRACTION = 0.3

@dataclass(frozen=True)
class MagnetPocketParameters:
    diameter_mm: float=10.0
    thickness_mm: float=2.3
    diameter_clearance_mm: float=0.2
    depth_clearance_mm: float=0.2
    count: int=2
    edge_offset_mm: float=8.0
    minimum_bridge_mm: float=0.6
    support_extra_mm: float=0.0
    @property
    def pocket_diameter_mm(self): return self.diameter_mm+self.diameter_clearance_mm
    @property
    def pocket_depth_mm(self): return self.thickness_mm+self.depth_clearance_mm
    @property
    def support_diameter_mm(self): return self.pocket_diameter_mm+2*self.minimum_bridge_mm+self.support_extra_mm
    def validate(self,body_depth_mm):
        if self.count<0 or self.count>8: raise ValueError("Magnet count must be between 0 and 8.")
        if self.pocket_depth_mm>=body_depth_mm: raise ValueError("Magnet pocket depth must leave material above the pocket.")

@dataclass(frozen=True)
class LabelParameters:
    text: str
    text_height_mm: float=15.843
    body_depth_mm: float=4.55
    outline_offset_mm: float=1.25
    font_family: str="DejaVu Sans"
    font_weight: str="bold"
    font_style: str="italic"
    horizontal_scale: float=1.0
    minimum_width_mm: float=24.0
    fixed_width_mm: float|None=None
    magnets: MagnetPocketParameters|None=None
    # Set only when this label is linked to a Tool -- generates a third,
    # independent QR-code body encoding this URL. None (the common case)
    # produces no QR body at all; existing two-body labels are unaffected.
    qr_url: str|None=None
    def validate(self):
        if not self.text.strip(): raise ValueError("Label text cannot be empty.")
        if self.magnets: self.magnets.validate(self.body_depth_mm)

@dataclass(frozen=True)
class MagnetPocket:
    x_mm: float
    y_mm: float
    diameter_mm: float
    depth_mm: float
    support_diameter_mm: float
    remaining_top_skin_mm: float

@dataclass(frozen=True)
class LabelMetrics:
    width_mm: float
    height_mm: float
    body_depth_mm: float
    text_width_mm: float
    text_height_mm: float
    outline_offset_mm: float
    font_path: str
    magnet_pockets: tuple[MagnetPocket,...]

@dataclass
class LabelModel:
    parameters: LabelParameters
    metrics: LabelMetrics
    outline_body: trimesh.Trimesh
    text_body: trimesh.Trimesh
    magnet_tools: list[trimesh.Trimesh]
    qr_body: trimesh.Trimesh|None=None

def _text_geometry(p):
    fp=str(findfont(FontProperties(family=p.font_family,weight=p.font_weight,style=p.font_style),fallback_to_default=True))
    path=TextPath((0,0),p.text,size=1.0,prop=FontProperties(fname=fp))
    polys=[Polygon(points) for points in path.to_polygons() if len(points)>=3]
    polys=[x for x in polys if x.is_valid and x.area>0]
    g=unary_union(polys); minx,miny,maxx,maxy=g.bounds
    s=p.text_height_mm/(maxy-miny)
    g=affinity.scale(g,xfact=s*p.horizontal_scale,yfact=s,origin=(0,0))
    minx,miny,_,_=g.bounds
    return affinity.translate(g,xoff=-minx,yoff=-miny),fp

def _qr_body(url,body_depth_mm):
    """A solid base plate (the full QR_SIZE_MM square) with each dark QR
    module raised as a bump on top, unioned into one watertight body via
    the same `trimesh.boolean.union(engine="manifold")` CSG this file
    already relies on elsewhere (see `_union`) -- NOT a 2D-shapely-polygon-
    then-extrude approach (what this function replaced during development).

    Two real problems ruled that approach out, not a style preference:
    (1) extruding the dark modules ALONE, with no shared base, produces
    hundreds of small disconnected floating cubes -- printable in the
    literal STL-file sense, but not a coherent single object, unlike every
    other body this engine produces. (2) a QR code's finder-pattern squares
    are topological rings (a dark square with a white square hole with a
    smaller dark square inside it) -- shapely's `unary_union` correctly
    produces valid polygons-with-holes for these, but `trimesh.creation.
    extrude_polygon`'s earcut triangulation of that specific donut-plus-
    island shape was confirmed (via this package's own test suite failing
    with `ValueError: Generated mesh is not watertight`) to produce
    non-manifold meshes for it, even after fixing a separate, real
    diagonal-corner-touch topology bug with a small module overlap. Building
    each module as its own 3D box and letting `manifold3d`'s boolean union
    (a purpose-built, robust CSG engine, not a 2D-triangulation library)
    merge everything sidesteps both problems at once and is the same
    solid-body-with-a-base construction a real physical QR plaque needs
    anyway.

    Row 0 of `get_matrix()` is conventionally the TOP of the code (standard
    image/matrix row-major order); mapping it to the MAXIMUM y (not y=0)
    keeps the pattern in its correct, scannable orientation -- flipping this
    mapping mirrors the pattern and silently breaks scanning (the finder
    squares are asymmetric, so a mirrored QR is not just rotated, it's a
    different, undecodable pattern). Verified by an independent decode
    round-trip in this package's test suite, not just by inspection -- get
    this wrong and nothing above the geometry layer would ever tell you.

    `border=4` is the QR spec's standard quiet zone (module count on each
    side with no data) -- real scanners rely on it, skipping it is a common
    cause of a QR that decodes fine in a debugger but fails to scan in
    practice. Medium error correction (~15% of modules can be damaged/
    obscured and still decode) is a reasonable default for a 3D-printed
    surface, which never renders as cleanly as a flat printout.
    """
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=4)
    qr.add_data(url)
    qr.make(fit=True)
    matrix = qr.get_matrix()
    n = len(matrix)
    cell = QR_SIZE_MM / n
    base_thickness = body_depth_mm * _QR_BASE_FRACTION
    bump_height = body_depth_mm - base_thickness
    base = trimesh.creation.box(extents=(QR_SIZE_MM, QR_SIZE_MM, base_thickness))
    base.apply_translation((QR_SIZE_MM / 2, QR_SIZE_MM / 2, base_thickness / 2))
    bumps = []
    for row, cells in enumerate(matrix):
        for col, dark in enumerate(cells):
            if not dark:
                continue
            x0, y0 = col * cell, (n - 1 - row) * cell
            bump = trimesh.creation.box(extents=(cell, cell, bump_height))
            bump.apply_translation((x0 + cell / 2, y0 + cell / 2, base_thickness + bump_height / 2))
            bumps.append(bump)
    return _union([base, *bumps], "qr_code")


def _parts(g):
    return [g] if isinstance(g,Polygon) else [p for p in g.geoms if isinstance(p,Polygon) and not p.is_empty]

def _extrude(g,h):
    meshes=[trimesh.creation.extrude_polygon(part,height=h) for part in _parts(g)]
    r=meshes[0] if len(meshes)==1 else trimesh.util.concatenate(meshes)
    r.remove_unreferenced_vertices()
    if not r.is_watertight: raise ValueError("Generated mesh is not watertight.")
    return r

def _cylinder(d,h,x,y,zmin):
    m=trimesh.creation.cylinder(radius=d/2,height=h,sections=128)
    m.apply_translation((x,y,zmin+h/2))
    return m

def _difference(body,tools,role):
    if not tools:
        body.metadata["body_role"]=role; return body
    tool=tools[0] if len(tools)==1 else trimesh.util.concatenate(tools)
    r=trimesh.boolean.difference([body,tool],engine="manifold")
    if r is None or not r.is_watertight: raise ValueError(f"Boolean subtraction failed for {role}.")
    r.metadata["body_role"]=role; return r

def _union(bodies,role):
    r=trimesh.boolean.union(bodies,engine="manifold")
    if r is None or not r.is_watertight: raise ValueError(f"Boolean union failed for {role}.")
    r.metadata["body_role"]=role; return r

def calculate_metrics(p):
    p.validate(); text,fp=_text_geometry(p)
    minx,miny,maxx,maxy=text.bounds; tw=maxx-minx; th=maxy-miny
    width=max(p.minimum_width_mm,tw+2*p.outline_offset_mm)
    pockets=[]
    if p.magnets and p.magnets.count:
        m=p.magnets; sr=m.support_diameter_mm/2; cy=(miny+maxy)/2
        left=minx+m.edge_offset_mm+sr; right=maxx-m.edge_offset_mm-sr
        if right<left: raise ValueError("Label is too narrow for the requested magnet supports.")
        xs=[(left+right)/2] if m.count==1 else np.linspace(left,right,m.count).tolist()
        skin=p.body_depth_mm-m.pocket_depth_mm
        pockets=[MagnetPocket(round(float(x),3),round(float(cy),3),round(m.pocket_diameter_mm,3),round(m.pocket_depth_mm,3),round(m.support_diameter_mm,3),round(skin,3)) for x in xs]
    return LabelMetrics(round(width,3),round(th+2*p.outline_offset_mm,3),round(p.body_depth_mm,3),round(tw,3),round(th,3),round(p.outline_offset_mm,3),fp,tuple(pockets))

def generate_label(p):
    metrics=calculate_metrics(p); text,_=_text_geometry(p)
    ring=text.buffer(p.outline_offset_mm,join_style=2,quad_segs=16).difference(text)
    outline=_extrude(ring,p.body_depth_mm); outline.metadata["body_role"]="text_outline"
    text_body=_extrude(text,p.body_depth_mm); text_body.metadata["body_role"]="face_up_text"
    # Independent third body -- not positioned relative to the text/outline,
    # not combined with them, and doesn't affect calculate_metrics()'s width
    # formula. Same physical depth as the label for consistent print
    # settings, but otherwise a standalone plaque.
    qr_body=None
    if p.qr_url:
        qr_body=_qr_body(p.qr_url,p.body_depth_mm)
    if not metrics.magnet_pockets: return LabelModel(p,metrics,outline,text_body,[],qr_body)
    supports=[]; pockets=[]
    for pocket in metrics.magnet_pockets:
        supports.append(_cylinder(pocket.support_diameter_mm,pocket.depth_mm,pocket.x_mm,pocket.y_mm,0.0))
        pockets.append(_cylinder(pocket.diameter_mm,pocket.depth_mm,pocket.x_mm,pocket.y_mm,0.0))
    text_body=_difference(text_body,supports,"face_up_text")
    outline=_union([outline,*supports],"text_outline_with_bottom_magnet_supports")
    outline=_difference(outline,pockets,"text_outline_with_bottom_magnet_supports")
    return LabelModel(p,metrics,outline,text_body,pockets,qr_body)

def generation_manifest(model):
    pdata=asdict(model.parameters); mdata=asdict(model.metrics)
    digest=hashlib.sha256(json.dumps({"parameters":pdata,"metrics":mdata},sort_keys=True).encode()).hexdigest()
    body_roles=[model.outline_body.metadata["body_role"],model.text_body.metadata["body_role"]]
    if model.qr_body is not None: body_roles.append(model.qr_body.metadata["body_role"])
    return {"engine_version":ENGINE_VERSION,"generator":"BottomOriginMagneticLabelGenerator","parameters":pdata,"metrics":mdata,"orientation":{"design_view":"face_up","magnet_opening_plane":"z=0","visible_face_plane":"z=body_depth_mm","slicer_instruction":"Assign colors face up, group the bodies, then flip the assembled model onto the print bed."},"parameter_checksum_sha256":digest,"body_roles":body_roles}

def export_label(model,output_dir,stem):
    output=Path(output_dir); output.mkdir(parents=True,exist_ok=True)
    safe="".join(c if c.isalnum() or c in "-_" else "_" for c in stem).strip("_") or "label"
    op=output/f"{safe}.outline.stl"; tp=output/f"{safe}.text.stl"; mp=output/f"{safe}.manifest.json"
    model.outline_body.export(op); model.text_body.export(tp); mp.write_text(json.dumps(generation_manifest(model),indent=2)+"\n")
    paths={"outline":op,"text":tp,"manifest":mp}
    if model.qr_body is not None:
        qp=output/f"{safe}.qr.stl"; model.qr_body.export(qp); paths["qr"]=qp
    return paths
