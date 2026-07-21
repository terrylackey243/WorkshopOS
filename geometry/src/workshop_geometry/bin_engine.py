from __future__ import annotations
import hashlib, json
from dataclasses import asdict, dataclass
from pathlib import Path
import numpy as np, trimesh
from shapely.geometry import Polygon, box
from shapely.geometry.polygon import orient

ENGINE_VERSION = "0.1.0"

# --- Researched Gridfinity constants (see plan's "Geometry algorithm" section
# for sourcing -- cq-gridfinity + community wiki corroboration). Kept as
# module constants rather than parameters because they define baseplate
# *compatibility*, not user-tunable design choices.
GRID_PITCH_MM = 42.0
CELL_FOOTPRINT_MM = 41.5  # 0.25mm clearance per side vs. the 42mm grid pitch
CELL_CORNER_RADIUS_MM = 4.0
OUTER_CORNER_RADIUS_MM = 4.0
HEIGHT_UNIT_MM = 7.0
EXTERIOR_WALL_THICKNESS_MM = 1.0
DIVIDER_THICKNESS_MM = 1.2
FLOOR_THICKNESS_MM = 1.0

# Base foot profile, bottom -> top, each a 45 degree chamfer unless noted
# (rise == horizontal inset change, since 45 degrees). Sums to the 4.75mm
# total base height at which the footprint reaches CELL_FOOTPRINT_MM/
# CELL_CORNER_RADIUS_MM and the vertical wall begins.
FOOT_BOTTOM_CHAMFER_MM = 0.7
FOOT_STRAIGHT_MM = 1.8
FOOT_TOP_CHAMFER_MM = 2.25
BASE_HEIGHT_MM = FOOT_BOTTOM_CHAMFER_MM + FOOT_STRAIGHT_MM + FOOT_TOP_CHAMFER_MM  # 4.75

# Stacking lip: community sources disagree on the precise figure (plan cites
# ~4.4-6.6mm); we take the low end as a deliberately conservative, precisely-
# reproducible approximation and call this out in generation_manifest().
# The lip is modeled as an *additional* rim on top of the full height_units
# stack (not carved out of it) -- see bin_engine module docstring in the repo
# report for why this reading was chosen over a superficially different
# phrase elsewhere in the plan.
LIP_HEIGHT_MM = 4.4
# Inward step depth of the lip's *interior* groove (the outer footprint never
# changes -- see `_stacking_lip`).
LIP_BULGE_MM = 1.0

# Magnets: 4 per grid cell, at the corners, inset from the cell center along
# both axes. 13mm matches the common real-world Gridfinity "26mm square"
# magnet hole spacing and (checked against BASE_HEIGHT_MM's chamfer numbers
# above) leaves comfortable clearance to the tapered foot's side at every Z
# level a magnet hole can reach.
MAGNET_CORNER_OFFSET_MM = 13.0

MAX_GRID_UNITS = 6
MAX_HEIGHT_UNITS = 12


@dataclass(frozen=True)
class BinParameters:
    grid_width_units: int
    grid_depth_units: int
    height_units: int
    compartments_x: int = 1
    compartments_y: int = 1
    include_stacking_lip: bool = True
    magnet_diameter_mm: float | None = None
    magnet_thickness_mm: float | None = None
    magnet_diameter_clearance_mm: float = 0.2
    magnet_depth_clearance_mm: float = 0.2

    def validate(self) -> None:
        if self.grid_width_units < 1 or self.grid_depth_units < 1:
            raise ValueError("Grid width and depth must each be at least 1 unit.")
        if self.grid_width_units > MAX_GRID_UNITS or self.grid_depth_units > MAX_GRID_UNITS:
            raise ValueError(f"Grid width/depth is capped at {MAX_GRID_UNITS} units in this phase.")
        if self.height_units < 1 or self.height_units > MAX_HEIGHT_UNITS:
            raise ValueError(f"height_units must be between 1 and {MAX_HEIGHT_UNITS}.")
        if self.compartments_x < 1 or self.compartments_y < 1:
            raise ValueError("Compartment counts must be at least 1.")
        if self.grid_width_units % self.compartments_x != 0:
            raise ValueError("compartments_x must divide grid_width_units evenly.")
        if self.grid_depth_units % self.compartments_y != 0:
            raise ValueError("compartments_y must divide grid_depth_units evenly.")
        if (self.magnet_diameter_mm is None) != (self.magnet_thickness_mm is None):
            raise ValueError("magnet_diameter_mm and magnet_thickness_mm must be provided together.")
        if self.magnet_diameter_mm is not None:
            if self.magnet_diameter_mm <= 0 or self.magnet_thickness_mm <= 0:
                raise ValueError("Magnet diameter and thickness must be positive.")
            hole_depth = self.magnet_thickness_mm + self.magnet_depth_clearance_mm
            if hole_depth >= BASE_HEIGHT_MM:
                raise ValueError(f"Magnet hole depth must be less than the {BASE_HEIGHT_MM}mm base profile.")


@dataclass(frozen=True)
class BinMetrics:
    width_mm: float
    depth_mm: float
    height_mm: float
    grid_width_units: int
    grid_depth_units: int
    height_units: int
    compartments_x: int
    compartments_y: int
    include_stacking_lip: bool
    magnet_hole_count: int


@dataclass
class BinModel:
    parameters: BinParameters
    metrics: BinMetrics
    body: trimesh.Trimesh


# --- Small local geometry helpers -------------------------------------------------
# Deliberately NOT imported from label_engine.py (per plan) -- kept as small,
# self-contained equivalents so this module has no coupling to the label
# generator's internals.


def _rounded_rect(width: float, depth: float, radius: float, quad_segs: int = 16) -> Polygon:
    """A rectangle of the given width/depth, centered at the origin, with
    round corners of the given radius -- built by insetting a sharp box by
    `radius` on all sides then regrowing it with a round-join buffer. Two
    calls with the same quad_segs always produce rings with the same vertex
    count, which is what makes `_loft`/`_tapered_pillar` below able to
    connect two different-sized copies of this shape cleanly."""
    if radius <= 0:
        raise ValueError("Rounded-rect corner radius must stay positive.")
    hw, hd = width / 2 - radius, depth / 2 - radius
    if hw < 0 or hd < 0:
        raise ValueError("Rounded-rect corner radius is too large for the given width/depth.")
    return box(-hw, -hd, hw, hd).buffer(radius, join_style=1, quad_segs=quad_segs)


def _extrude(poly: Polygon, height: float) -> trimesh.Trimesh:
    if not isinstance(poly, Polygon):
        raise ValueError("Cannot extrude a non-simple (multi-part) polygon in the bin engine.")
    mesh = trimesh.creation.extrude_polygon(poly, height=height)
    mesh.remove_unreferenced_vertices()
    if not mesh.is_watertight:
        raise ValueError("Generated mesh is not watertight.")
    return mesh


def _cylinder(diameter: float, height: float, x: float, y: float, z_min: float) -> trimesh.Trimesh:
    mesh = trimesh.creation.cylinder(radius=diameter / 2, height=height, sections=64)
    mesh.apply_translation((x, y, z_min + height / 2))
    return mesh


def _union(bodies: list[trimesh.Trimesh]) -> trimesh.Trimesh:
    result = bodies[0] if len(bodies) == 1 else trimesh.boolean.union(bodies, engine="manifold")
    if result is None or not result.is_watertight:
        raise ValueError("Boolean union failed while assembling the bin.")
    return result


def _difference(body: trimesh.Trimesh, tools: list[trimesh.Trimesh]) -> trimesh.Trimesh:
    if not tools:
        return body
    tool = tools[0] if len(tools) == 1 else trimesh.util.concatenate(tools)
    result = trimesh.boolean.difference([body, tool], engine="manifold")
    if result is None or not result.is_watertight:
        raise ValueError("Boolean subtraction (magnet holes) failed.")
    return result


def _boundary_loops(poly: Polygon, z: float) -> list[np.ndarray]:
    """Exterior ring first, then any interior (hole) rings, each as an
    (n, 3) array at the given Z, oriented exterior-CCW/interior-CW."""
    oriented = orient(poly, sign=1.0)
    loops = [np.array([(x, y, z) for x, y in oriented.exterior.coords[:-1]])]
    for interior in oriented.interiors:
        loops.append(np.array([(x, y, z) for x, y in interior.coords[:-1]]))
    return loops


def _tapered_pillar(levels: list[tuple[Polygon, float]]) -> trimesh.Trimesh:
    """Builds one closed, watertight solid from an ordered bottom-to-top list
    of (polygon, z) cross-sections: a flat cap at the first and last level,
    plus a manually-triangulated "loft" side wall connecting every
    consecutive pair of levels. This is the module's core new technique --
    trimesh has no tapered-extrude primitive, so each side wall is built by
    hand from the two polygons' exterior (and, for a ring/annulus
    cross-section, interior) coordinate rings.

    All levels must share the same boundary-loop *topology* (same number of
    loops, same vertex count per loop) -- true by construction here, since
    every level is produced by `_rounded_rect` (or a difference of two of
    them) with the same quad_segs.
    """
    loop_sets = [_boundary_loops(poly, z) for poly, z in levels]
    loop_counts = {len(loops) for loops in loop_sets}
    if len(loop_counts) != 1:
        raise ValueError(f"Inconsistent boundary-loop counts across pillar levels: {[len(l) for l in loop_sets]}")
    n_loops = loop_counts.pop()
    for loop_idx in range(n_loops):
        vcounts = {len(loops[loop_idx]) for loops in loop_sets}
        if len(vcounts) != 1:
            raise ValueError(
                f"Inconsistent vertex counts for loop {loop_idx} across pillar levels: "
                f"{[len(loops[loop_idx]) for loops in loop_sets]}"
            )

    vertices: list[tuple[float, float, float]] = []
    faces: list[list[int]] = []

    def add_block(new_vertices, new_faces) -> None:
        base = len(vertices)
        vertices.extend(new_vertices)
        faces.extend([[a + base, b + base, c + base] for a, b, c in new_faces])

    # Side walls: loft each boundary loop independently between every
    # consecutive pair of Z levels.
    for loop_idx in range(n_loops):
        for lvl in range(len(levels) - 1):
            ring_a = loop_sets[lvl][loop_idx]
            ring_b = loop_sets[lvl + 1][loop_idx]
            n = len(ring_a)
            block_verts = list(ring_a) + list(ring_b)
            block_faces = []
            for i in range(n):
                j = (i + 1) % n
                block_faces.append((i, j, n + j))
                block_faces.append((i, n + j, n + i))
            add_block(block_verts, block_faces)

    # End caps (triangulated -- handles a ring/annulus cross-section's hole
    # via the same earcut-based triangulation trimesh uses for extrude_polygon).
    bottom_poly, bottom_z = levels[0]
    top_poly, top_z = levels[-1]
    for poly, z, flip in ((bottom_poly, bottom_z, True), (top_poly, top_z, False)):
        v2d, f2d = trimesh.creation.triangulate_polygon(poly, engine="earcut")
        cap_verts = [(x, y, z) for x, y in v2d]
        cap_faces = [((f[0], f[2], f[1]) if flip else (f[0], f[1], f[2])) for f in f2d]
        add_block(cap_verts, cap_faces)

    mesh = trimesh.Trimesh(vertices=np.array(vertices), faces=np.array(faces), process=True)
    trimesh.repair.fix_normals(mesh)
    if not mesh.is_watertight:
        raise ValueError("Tapered pillar (loft) mesh is not watertight.")
    return mesh


def _cell_centers(count: int) -> list[float]:
    """X (or Y) centers of `count` grid cells at 42mm pitch, centered as a
    group on the origin."""
    return [GRID_PITCH_MM * i - GRID_PITCH_MM / 2 * (count - 1) for i in range(count)]


def _foot_template() -> trimesh.Trimesh:
    """Builds ONE per-cell base foot at the origin as a 3-segment tapered
    pillar (bottom chamfer -> straight -> top chamfer), per the researched
    profile. Callers translate-copy this mesh per grid cell rather than
    re-lofting per cell (the main perf risk for larger grids)."""
    total_inset = FOOT_BOTTOM_CHAMFER_MM + FOOT_TOP_CHAMFER_MM
    mid_inset = FOOT_TOP_CHAMFER_MM

    def ring(inset: float) -> Polygon:
        return _rounded_rect(
            CELL_FOOTPRINT_MM - 2 * inset, CELL_FOOTPRINT_MM - 2 * inset, CELL_CORNER_RADIUS_MM - inset
        )

    levels = [
        (ring(total_inset), 0.0),
        (ring(mid_inset), FOOT_BOTTOM_CHAMFER_MM),
        (ring(mid_inset), FOOT_BOTTOM_CHAMFER_MM + FOOT_STRAIGHT_MM),
        (ring(0.0), BASE_HEIGHT_MM),
    ]
    mesh = _tapered_pillar(levels)
    mesh.metadata["body_role"] = "base_foot"
    return mesh


def _outer_footprint(p: BinParameters) -> tuple[float, float]:
    return (GRID_PITCH_MM * p.grid_width_units - 0.5, GRID_PITCH_MM * p.grid_depth_units - 0.5)


def _floor_slab(p: BinParameters) -> trimesh.Trimesh:
    width, depth = _outer_footprint(p)
    poly = _rounded_rect(width, depth, OUTER_CORNER_RADIUS_MM)
    mesh = _extrude(poly, FLOOR_THICKNESS_MM)
    mesh.apply_translation((0, 0, BASE_HEIGHT_MM))
    return mesh


def _wall_inner_polygon(p: BinParameters) -> Polygon:
    width, depth = _outer_footprint(p)
    return _rounded_rect(
        width - 2 * EXTERIOR_WALL_THICKNESS_MM,
        depth - 2 * EXTERIOR_WALL_THICKNESS_MM,
        OUTER_CORNER_RADIUS_MM - EXTERIOR_WALL_THICKNESS_MM,
    )


def _wall(p: BinParameters, z_bottom: float, height: float) -> trimesh.Trimesh:
    width, depth = _outer_footprint(p)
    outer = _rounded_rect(width, depth, OUTER_CORNER_RADIUS_MM)
    inner = _wall_inner_polygon(p)
    ring = outer.difference(inner)
    mesh = _extrude(ring, height)
    mesh.apply_translation((0, 0, z_bottom))
    return mesh


def _feet(p: BinParameters) -> list[trimesh.Trimesh]:
    template = _foot_template()
    xs = _cell_centers(p.grid_width_units)
    ys = _cell_centers(p.grid_depth_units)
    return [template.copy().apply_translation((x, y, 0)) for x in xs for y in ys]


def _dividers(p: BinParameters, z_bottom: float, height: float) -> list[trimesh.Trimesh]:
    width, depth = _outer_footprint(p)
    bodies = []
    if p.compartments_x > 1:
        cells_per = p.grid_width_units // p.compartments_x
        for k in range(1, p.compartments_x):
            x = GRID_PITCH_MM * k * cells_per - GRID_PITCH_MM * p.grid_width_units / 2
            rect = box(x - DIVIDER_THICKNESS_MM / 2, -depth / 2, x + DIVIDER_THICKNESS_MM / 2, depth / 2)
            mesh = _extrude(rect, height)
            mesh.apply_translation((0, 0, z_bottom))
            bodies.append(mesh)
    if p.compartments_y > 1:
        cells_per = p.grid_depth_units // p.compartments_y
        for k in range(1, p.compartments_y):
            y = GRID_PITCH_MM * k * cells_per - GRID_PITCH_MM * p.grid_depth_units / 2
            rect = box(-width / 2, y - DIVIDER_THICKNESS_MM / 2, width / 2, y + DIVIDER_THICKNESS_MM / 2)
            mesh = _extrude(rect, height)
            mesh.apply_translation((0, 0, z_bottom))
            bodies.append(mesh)
    return bodies


def _stacking_lip(p: BinParameters, z_bottom: float) -> trimesh.Trimesh:
    """A small hollow tapered-pillar rim: the OUTER boundary stays flush with
    the plain wall's outer face throughout the lip (so the bin's overall
    footprint -- the precisely-targeted base-to-baseplate dimension -- is
    unaffected by whether a lip is present at all). The INNER boundary steps
    inward (thicker wall) partway up then back out to the plain wall's
    interior opening at the very top rim, forming the groove a stacked bin's
    tapered base can seat into -- approximating the researched stacking-lip
    step profile (see module constants above for the exact figures chosen;
    community sources disagree on the precise shape)."""
    width, depth = _outer_footprint(p)
    outer = _rounded_rect(width, depth, OUTER_CORNER_RADIUS_MM)

    def inner(shrink: float) -> Polygon:
        return _rounded_rect(
            width - 2 * (EXTERIOR_WALL_THICKNESS_MM + shrink),
            depth - 2 * (EXTERIOR_WALL_THICKNESS_MM + shrink),
            OUTER_CORNER_RADIUS_MM - EXTERIOR_WALL_THICKNESS_MM - shrink,
        )

    z_mid = z_bottom + LIP_HEIGHT_MM * 0.35
    z_top = z_bottom + LIP_HEIGHT_MM
    levels = [
        (outer.difference(inner(0.0)), z_bottom),
        (outer.difference(inner(LIP_BULGE_MM)), z_mid),
        (outer.difference(inner(0.0)), z_top),
    ]
    mesh = _tapered_pillar(levels)
    mesh.metadata["body_role"] = "stacking_lip"
    return mesh


def _magnet_tools(p: BinParameters) -> list[trimesh.Trimesh]:
    if p.magnet_diameter_mm is None:
        return []
    diameter = p.magnet_diameter_mm + p.magnet_diameter_clearance_mm
    height = p.magnet_thickness_mm + p.magnet_depth_clearance_mm
    xs = _cell_centers(p.grid_width_units)
    ys = _cell_centers(p.grid_depth_units)
    tools = []
    for cx in xs:
        for cy in ys:
            for dx in (-MAGNET_CORNER_OFFSET_MM, MAGNET_CORNER_OFFSET_MM):
                for dy in (-MAGNET_CORNER_OFFSET_MM, MAGNET_CORNER_OFFSET_MM):
                    tools.append(_cylinder(diameter, height, cx + dx, cy + dy, 0.0))
    return tools


def calculate_metrics(p: BinParameters) -> BinMetrics:
    p.validate()
    width, depth = _outer_footprint(p)
    lip_height = LIP_HEIGHT_MM if p.include_stacking_lip else 0.0
    height = BASE_HEIGHT_MM + p.height_units * HEIGHT_UNIT_MM + lip_height
    magnet_count = 4 * p.grid_width_units * p.grid_depth_units if p.magnet_diameter_mm is not None else 0
    return BinMetrics(
        round(width, 3),
        round(depth, 3),
        round(height, 3),
        p.grid_width_units,
        p.grid_depth_units,
        p.height_units,
        p.compartments_x,
        p.compartments_y,
        p.include_stacking_lip,
        magnet_count,
    )


def generate_bin(p: BinParameters) -> BinModel:
    metrics = calculate_metrics(p)

    body_top = BASE_HEIGHT_MM + p.height_units * HEIGHT_UNIT_MM
    wall_height = body_top - BASE_HEIGHT_MM

    solids = [*_feet(p), _floor_slab(p), _wall(p, BASE_HEIGHT_MM, wall_height)]
    solids.extend(_dividers(p, BASE_HEIGHT_MM, wall_height))
    if p.include_stacking_lip:
        solids.append(_stacking_lip(p, body_top))

    body = _union(solids)
    body = _difference(body, _magnet_tools(p))
    body.metadata["body_role"] = "bin_body"

    return BinModel(p, metrics, body)


def generation_manifest(model: BinModel) -> dict:
    pdata = asdict(model.parameters)
    mdata = asdict(model.metrics)
    digest = hashlib.sha256(json.dumps({"parameters": pdata, "metrics": mdata}, sort_keys=True).encode()).hexdigest()
    return {
        "engine_version": ENGINE_VERSION,
        "generator": "ParametricGridfinityBinGenerator",
        "parameters": pdata,
        "metrics": mdata,
        "orientation": {
            "design_view": "as_generated",
            "build_plate_plane": "z=0",
            "top_rim_plane": f"z={mdata['height_mm']}",
            "slicer_instruction": "Single-body, single-color print -- place directly on the build plate at z=0, no reorientation or color grouping needed.",
        },
        "notes": {
            "stacking_lip": (
                "Stacking lip geometry approximates the researched step profile "
                f"(height={LIP_HEIGHT_MM}mm, interior groove depth={LIP_BULGE_MM}mm); base-to-baseplate fit "
                "is dimensionally precise to the researched figures, but lip-to-lip stacking "
                "compatibility against third-party Gridfinity bins is not guaranteed "
                "byte-for-byte given source disagreement on the exact lip profile."
            ),
        },
        "parameter_checksum_sha256": digest,
        "body_roles": [model.body.metadata.get("body_role", "bin_body")],
    }


def export_bin(model: BinModel, output_dir: str | Path, stem: str) -> dict[str, Path]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in stem).strip("_") or "bin"
    body_path = output / f"{safe}.stl"
    manifest_path = output / f"{safe}.manifest.json"
    model.body.export(body_path)
    manifest_path.write_text(json.dumps(generation_manifest(model), indent=2) + "\n")
    return {"body": body_path, "manifest": manifest_path}
