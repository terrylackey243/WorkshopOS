from __future__ import annotations
import hashlib, json
from dataclasses import asdict, dataclass
from pathlib import Path
import numpy as np, qrcode, trimesh
from matplotlib.font_manager import FontProperties, findfont
from matplotlib.textpath import TextPath
from shapely import affinity
from shapely.geometry import LineString, MultiPolygon, Polygon
from shapely.ops import nearest_points, unary_union

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

def _fill_glyph_contours(polys):
    """Combines raw glyph contours (from `TextPath.to_polygons()`) into one
    shape with counters -- the enclosed holes in letters like "o", "e", "a",
    "d" -- actually cut out, instead of filled in solid.

    `to_polygons()` returns every closed contour of every glyph as a bare,
    independent point loop: a letter like "o" comes back as *two* contours
    (its outer ring and its inner counter), with no flag saying which is
    which. Wrapping each one in `Polygon(points)` and `unary_union`-ing them
    (the previous approach here) treats every contour as solid fill, so the
    counter adds area instead of subtracting it -- every hole in every
    letter silently filled in.

    The fix is polygon-nesting depth, not winding order: a contour that is
    itself fully enclosed by an odd number of other contours is a hole
    (it's one level deeper than the solid ring it's cutting into); an even
    count (usually zero) is solid. This is correct for arbitrarily nested
    glyphs (a hole could itself contain an island, in principle) and, just
    as importantly, for *adjacent* letters that happen to touch or overlap
    (common in this engine's default bold-italic font) -- neither contains
    the other, so both stay at depth 0 and simply union together, unlike a
    global even-odd XOR of all contours, which would misread that overlap
    as a hole between two unrelated letters.

    Nesting is tested via whole-polygon containment (`other.contains(poly)`),
    not a representative point of `poly` tested against `other` -- a raw
    outer glyph contour (no hole cut into it yet) renders as a solid disc,
    so a representative point near its centroid can itself fall inside the
    smaller hole-designate contour it encloses. That made both contours look
    like they contained each other (confirmed via the single letter "o":
    both its 2 raw contours came back at depth 1, canceling out to an empty
    shape) -- containment of the full polygon, not a sampled point, is
    unambiguous.
    """
    solids,holes=[],[]
    for i,poly in enumerate(polys):
        depth=sum(1 for j,other in enumerate(polys) if j!=i and other.contains(poly))
        (holes if depth%2 else solids).append(poly)
    g=unary_union(solids)
    return g.difference(unary_union(holes)) if holes else g

def _hole_regions(text):
    """The hole/counter regions already cut into `text` by
    `_fill_glyph_contours`, re-extracted as their own polygons so the
    outline ring can claim them (see `generate_label`).

    A label is a flat two-color plate, not a plate with punched-through
    holes: `outline` and `text_body` are extruded to the exact same
    `body_depth_mm` z-range and, together, are meant to tile the label's
    entire footprint -- there's no third "nothing here" region anywhere
    else on the label, so a letter's counter shouldn't be one either. Left
    out of both bodies (an earlier version of this function did exactly
    that, to fix a *different* bug -- see git history), a counter is a
    genuine void: an actual gap you can see or push a pin through, not a
    background-colored letter counter like the reference design calls for.
    Adding these regions into `ring` makes that area outline-colored fill
    instead, matching every other non-letter region of the label.
    """
    parts=text.geoms if hasattr(text,'geoms') else [text]
    holes=[Polygon(interior) for part in parts for interior in part.interiors]
    return unary_union(holes) if holes else None

def _text_geometry(p):
    fp=str(findfont(FontProperties(family=p.font_family,weight=p.font_weight,style=p.font_style),fallback_to_default=True))
    path=TextPath((0,0),p.text,size=1.0,prop=FontProperties(fname=fp))
    polys=[Polygon(points) for points in path.to_polygons() if len(points)>=3]
    polys=[x for x in polys if x.is_valid and x.area>0]
    g=_fill_glyph_contours(polys); minx,miny,maxx,maxy=g.bounds
    s=p.text_height_mm/(maxy-miny)
    g=affinity.scale(g,xfact=s*p.horizontal_scale,yfact=s,origin=(0,0))
    minx,miny,_,_=g.bounds
    return affinity.translate(g,xoff=-minx,yoff=-miny),fp

def _outline_bridges(buffered,width_mm):
    """2D footprints (simple capsules, no holes) connecting every
    disconnected piece of `buffered` -- the dilated-but-not-yet-holed basis
    for the outline ring -- to its neighbour.

    A label's outline is its physical backing plate, so it must always come
    out as a single piece -- but buffering per-glyph text can leave it in
    several: not just across a space between words, but even within one
    word, whenever a glyph's own silhouette doesn't reach its neighbour at
    this offset (confirmed via `_text_geometry("1/2 Drive")`: the italic
    slash sits far enough from both digits that "1/2" alone buffers into two
    pieces, on top of the word gap before "Drive" -- three disconnected
    outline islands from one two-word label, not the two you'd guess).

    Deliberately returned as separate 2D shapes to be extruded and
    3D-boolean-unioned onto the outline body by the caller, NOT merged into
    `ring` before extrusion: `extrude_polygon`'s earcut triangulation of one
    complex polygon combining the letter-shaped holes with a thin connecting
    neck was confirmed (empirically, on this exact label) to yield a
    non-watertight mesh -- the same class of triangulation limitation
    already documented on `_qr_body` above. Unioning simple, hole-free
    primitives via `manifold3d` CSG sidesteps it entirely, the same way
    magnet supports are welded onto the outline below.

    Bridges each adjacent piece (sorted left to right by its leftmost x) to
    the next through their two closest points -- a round cap (not the
    mitred joins used elsewhere in this file) is what guarantees the
    resulting capsule actually overlaps both pieces' interiors rather than
    just grazing their boundary at a single point, which the boolean union
    could then leave unwelded. Chaining every adjacent pair this way always
    yields one connected result regardless of how many pieces there are or
    how the gaps are arranged.
    """
    if isinstance(buffered,Polygon): return []
    parts=sorted((g for g in buffered.geoms if isinstance(g,Polygon)),key=lambda g:g.bounds[0])
    return [LineString([*nearest_points(a,b)]).buffer(width_mm,cap_style=1) for a,b in zip(parts,parts[1:])]

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
    buffered=text.buffer(p.outline_offset_mm,join_style=2,quad_segs=16)
    ring=buffered.difference(text)
    holes=_hole_regions(text)
    if holes is not None: ring=ring.union(holes)
    outline=_extrude(ring,p.body_depth_mm)
    bridges=[_extrude(b,p.body_depth_mm) for b in _outline_bridges(buffered,p.outline_offset_mm)]
    if bridges: outline=_union([outline,*bridges],"text_outline")
    outline.metadata["body_role"]="text_outline"
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
