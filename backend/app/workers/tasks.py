import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path

import dramatiq
import numpy as np
import structlog
import trimesh
from sqlalchemy import select
from workshop_geometry.bin_engine import export_bin, generate_bin
from workshop_geometry.label_engine import export_label, generate_label

# Importing broker registers the RedisBroker as the active dramatiq broker
# before any actor is declared below.
from . import broker  # noqa: F401
from .db import WorkerSessionFactory
from ..config import get_settings
from ..models import Design, DrawerLayout, InsertDesign
from ..services.bin_params import bin_parameters_from_dict
from ..services.label_params import label_parameters_from_dict

logger = structlog.get_logger()
settings = get_settings()


@dramatiq.actor(max_retries=3)
def ping(message: str = "pong") -> None:
    """Placeholder actor so `workshopos-worker` boots and proves the plumbing."""
    logger.info("worker_task_ran", message=message)


@dramatiq.actor(max_retries=1, time_limit=120_000)
def generate_design(design_id: str) -> None:
    """Dramatiq actor entrypoint for label generation.

    Stays synchronous internally via `asyncio.run()`, reusing the existing
    async `SessionFactory` from `app/db.py` directly (NOT the `get_session`
    FastAPI dependency, which is request-scoped). `max_retries=1` and a
    generous 120s `time_limit` account for the CSG boolean union/difference
    step, which is the one part of this pipeline that's actually expensive.
    """
    asyncio.run(_generate_design(design_id))


async def _generate_design(design_id: str) -> None:
    logger.info("generate_design_started", design_id=design_id)

    async with WorkerSessionFactory() as session:
        design = await session.get(Design, uuid.UUID(design_id))
        if design is None:
            logger.warning("generate_design_missing", design_id=design_id)
            return

        try:
            parameters = label_parameters_from_dict(design.parameters_json)
            model = generate_label(parameters)
            output_dir = Path(settings.generated_files_dir) / str(design.organization_id) / str(design.id)
            paths = export_label(model, output_dir, stem="label")

            design.status = "generated"
            design.outline_stl_path = str(paths["outline"])
            design.text_stl_path = str(paths["text"])
            design.qr_stl_path = str(paths["qr"]) if "qr" in paths else None
            design.generated_at = datetime.now(timezone.utc)
            design.error_message = None
            logger.info(
                "generate_design_succeeded",
                design_id=design_id,
                outline_stl_path=design.outline_stl_path,
                text_stl_path=design.text_stl_path,
                qr_stl_path=design.qr_stl_path,
            )
        except Exception as exc:  # noqa: BLE001 -- worker boundary must not crash the process
            logger.exception("generate_design_failed", design_id=design_id)
            design.status = "failed"
            design.error_message = str(exc)[:2000]

        await session.commit()


@dramatiq.actor(max_retries=1, time_limit=300_000)
def generate_bin_design(insert_design_id: str) -> None:
    """Dramatiq actor entrypoint for Gridfinity bin generation.

    Same `asyncio.run()` + direct `SessionFactory` pattern as
    `generate_design`. `time_limit=300_000` (5 minutes, vs. the label
    engine's 2) -- unioning many small lofted per-cell feet is real geometry
    work, slower than the label engine's handful of bodies.
    """
    asyncio.run(_generate_bin_design(insert_design_id))


async def _generate_bin_design(insert_design_id: str) -> None:
    logger.info("generate_bin_design_started", insert_design_id=insert_design_id)

    async with WorkerSessionFactory() as session:
        insert_design = await session.get(InsertDesign, uuid.UUID(insert_design_id))
        if insert_design is None:
            logger.warning("generate_bin_design_missing", insert_design_id=insert_design_id)
            return

        try:
            parameters = bin_parameters_from_dict(insert_design.parameters_json)
            model = generate_bin(parameters)
            output_dir = Path(settings.generated_files_dir) / str(insert_design.organization_id) / str(
                insert_design.id
            )
            paths = export_bin(model, output_dir, stem="bin")

            insert_design.status = "generated"
            insert_design.stl_path = str(paths["body"])
            insert_design.generated_at = datetime.now(timezone.utc)
            insert_design.error_message = None
            logger.info(
                "generate_bin_design_succeeded",
                insert_design_id=insert_design_id,
                stl_path=insert_design.stl_path,
            )
        except Exception as exc:  # noqa: BLE001 -- worker boundary must not crash the process
            logger.exception("generate_bin_design_failed", insert_design_id=insert_design_id)
            insert_design.status = "failed"
            insert_design.error_message = str(exc)[:2000]

        await session.commit()


@dramatiq.actor(max_retries=1, time_limit=60_000)
def process_uploaded_insert(insert_design_id: str) -> None:
    """Dramatiq actor entrypoint for uploaded-STL bounds computation.

    Same `asyncio.run()` + `WorkerSessionFactory` pattern as
    `generate_bin_design` (see `app/workers/db.py` for why the dedicated
    NullPool session factory is required here, not `app.db.SessionFactory`).
    Parsing an already-on-disk file is much cheaper than the bin engine's CSG
    boolean ops, so `time_limit=60_000` (1 minute, vs. the bin engine's 5) is
    plenty even for an unusually large or malformed untrusted upload.
    """
    asyncio.run(_process_uploaded_insert(insert_design_id))


async def _process_uploaded_insert(insert_design_id: str) -> None:
    logger.info("process_uploaded_insert_started", insert_design_id=insert_design_id)

    async with WorkerSessionFactory() as session:
        insert_design = await session.get(InsertDesign, uuid.UUID(insert_design_id))
        if insert_design is None:
            logger.warning("process_uploaded_insert_missing", insert_design_id=insert_design_id)
            return

        try:
            if not insert_design.stl_path:
                raise ValueError("No uploaded file is associated with this insert design.")

            # force="mesh" concatenates every geometry in the loaded file
            # into a single Trimesh, so a multi-object file never comes back
            # as a Scene (which has no simple `.bounds`).
            mesh = trimesh.load(insert_design.stl_path, force="mesh")
            if not isinstance(mesh, trimesh.Trimesh) or mesh.vertices is None or len(mesh.vertices) == 0:
                raise ValueError("The uploaded file did not contain any usable mesh geometry.")

            bounds = mesh.bounds
            if bounds is None:
                raise ValueError("The uploaded file did not contain any usable mesh geometry.")

            width_mm = float(bounds[1][0] - bounds[0][0])
            depth_mm = float(bounds[1][1] - bounds[0][1])
            height_mm = float(bounds[1][2] - bounds[0][2])

            insert_design.status = "generated"
            insert_design.bounds_json = {"width_mm": width_mm, "depth_mm": depth_mm, "height_mm": height_mm}
            insert_design.generated_at = datetime.now(timezone.utc)
            insert_design.error_message = None
            logger.info(
                "process_uploaded_insert_succeeded",
                insert_design_id=insert_design_id,
                bounds_json=insert_design.bounds_json,
            )
        except Exception as exc:  # noqa: BLE001 -- worker boundary must not crash the process
            logger.exception("process_uploaded_insert_failed", insert_design_id=insert_design_id)
            insert_design.status = "failed"
            detail = str(exc).strip()
            message = "Could not read this file as an STL mesh."
            if detail:
                message = f"{message} ({detail[:300]})"
            insert_design.error_message = message[:2000]

        await session.commit()


@dramatiq.actor(max_retries=1, time_limit=300_000)
def generate_plate_stl(drawer_layout_id: str, plate_index: int) -> None:
    """Dramatiq actor entrypoint for M3 Phase 5 (print-bed panelization)
    per-plate STL generation. Same `asyncio.run()` + `WorkerSessionFactory`
    pattern as every other actor in this file (mandatory -- see
    `app/workers/db.py` for the two previously-debugged production bugs
    this pattern exists to prevent). `time_limit=300_000` (same ceiling as
    `generate_bin_design`) -- concatenating multiple already-generated
    meshes is cheaper per-mesh than the CSG union that builds one bin from
    scratch, but N meshes' file I/O can still add up.
    """
    asyncio.run(_generate_plate_stl(drawer_layout_id, plate_index))


async def _generate_plate_stl(drawer_layout_id: str, plate_index: int) -> None:
    logger.info("generate_plate_stl_started", drawer_layout_id=drawer_layout_id, plate_index=plate_index)

    # Phase 1: load the plate's assignments and do the (expensive, per-plate
    # independent) mesh work WITHOUT holding a row lock -- concurrent plate
    # actors for the same export should run their mesh work in parallel, not
    # serialize on it.
    async with WorkerSessionFactory() as session:
        layout = await session.get(DrawerLayout, uuid.UUID(drawer_layout_id))
        if layout is None:
            logger.warning("generate_plate_stl_missing_layout", drawer_layout_id=drawer_layout_id)
            return

        plates = (layout.layout_json or {}).get("plates", [])
        plate = next((p for p in plates if p.get("plate_index") == plate_index), None)
        if plate is None:
            logger.warning(
                "generate_plate_stl_missing_plate", drawer_layout_id=drawer_layout_id, plate_index=plate_index
            )
            return

        error_message: str | None = None
        stl_path: str | None = None
        try:
            assignments = plate.get("assignments", [])
            if not assignments:
                raise ValueError("Plate has no assignments to generate.")

            design_ids = {uuid.UUID(a["insert_design_id"]) for a in assignments}
            designs_by_id = {
                design.id: design
                for design in await session.scalars(
                    select(InsertDesign).where(InsertDesign.id.in_(design_ids))
                )
            }

            bodies: list[trimesh.Trimesh] = []
            for assignment in assignments:
                design = designs_by_id.get(uuid.UUID(assignment["insert_design_id"]))
                # Don't trust the router's export-time snapshot -- a design
                # could still be mid-generation or have failed since export;
                # re-validate at worker-run time.
                if design is None or design.status != "generated" or not design.stl_path:
                    raise ValueError(f"Insert design {assignment['insert_design_id']} is not generated.")
                if not Path(design.stl_path).is_file():
                    raise ValueError(
                        f"Insert design {assignment['insert_design_id']}'s STL file is missing on disk."
                    )

                # Same force="mesh" call `process_uploaded_insert` already uses.
                mesh = trimesh.load(design.stl_path, force="mesh")
                if not isinstance(mesh, trimesh.Trimesh) or mesh.vertices is None or len(mesh.vertices) == 0:
                    raise ValueError(f"Insert design {assignment['insert_design_id']} has no usable mesh geometry.")

                # Transform pipeline, in this exact order (verified necessary
                # against bin_engine.py: generated bins are built CENTERED AT
                # THE ORIGIN in XY -- `_rounded_rect`/`_cell_centers` are
                # explicitly "centered at the origin", not bounds-min-rooted --
                # so this normalization is required for generated bins too,
                # not just arbitrary-origin uploads):
                mesh.apply_translation(-mesh.bounds[0])  # 1. normalize bounds-min to origin
                if assignment.get("rotation_deg") == 90:
                    mesh.apply_transform(
                        trimesh.transformations.rotation_matrix(np.radians(90), [0, 0, 1])
                    )  # 2. rotate for this plate's assignment
                # 3. Re-normalize. Rotating about the post-step-1 origin (a
                # bounds-min corner, not a centroid) can shift the bounding
                # box into negative space -- skipping this step produces
                # geometry that "looks right" in isolation but sits offset
                # from where the packer says it is. This is NOT a redundant
                # duplicate of step 1 -- do not simplify it away.
                mesh.apply_translation(-mesh.bounds[0])
                mesh.apply_translation((assignment["x_mm"], assignment["y_mm"], 0))  # 4. final plate placement
                bodies.append(mesh)

            # Plate bins are disjoint/non-touching (the packer guarantees no
            # overlap) -- they don't need to form one watertight solid the way
            # a single bin's own parts do in `generate_bin()`. `concatenate`
            # is cheaper and matches the same "just combine, don't need one
            # solid" choice `bin_engine.py::_difference()` already makes for
            # an analogous case. NOT `trimesh.boolean.union`.
            combined = trimesh.util.concatenate(bodies)

            # Every design on a layout belongs to the same org, enforced
            # transitively at export time -- avoids an extra
            # Drawer->Toolbox->Shop join chain in the worker.
            first_design = designs_by_id[uuid.UUID(assignments[0]["insert_design_id"])]
            output_dir = Path(settings.generated_files_dir) / str(first_design.organization_id) / drawer_layout_id
            output_dir.mkdir(parents=True, exist_ok=True)
            path = output_dir / f"plate-{plate_index}.stl"
            combined.export(path)
            stl_path = str(path)

            logger.info(
                "generate_plate_stl_succeeded",
                drawer_layout_id=drawer_layout_id,
                plate_index=plate_index,
                stl_path=stl_path,
            )
        except Exception as exc:  # noqa: BLE001 -- worker boundary must not crash the process
            logger.exception(
                "generate_plate_stl_failed", drawer_layout_id=drawer_layout_id, plate_index=plate_index
            )
            error_message = str(exc)[:2000]

    # Phase 2: N plates from the same export enqueue as N independent actor
    # invocations that all read-modify-write the *same* DrawerLayout.
    # layout_json JSONB column. Two plates finishing close together will race
    # (classic read-modify-write clobber) unless serialized -- load the row
    # via `with_for_update()` in a fresh transaction right before mutating,
    # so concurrent plate actors for the same layout serialize on just this
    # brief write, not on the (already independently expensive) mesh work
    # above.
    async with WorkerSessionFactory() as session:
        result = await session.execute(
            select(DrawerLayout).where(DrawerLayout.id == uuid.UUID(drawer_layout_id)).with_for_update()
        )
        locked_layout = result.scalar_one_or_none()
        if locked_layout is None:
            logger.warning("generate_plate_stl_missing_layout_on_write", drawer_layout_id=drawer_layout_id)
            return

        current_plates = list((locked_layout.layout_json or {}).get("plates", []))
        new_plates = []
        for p in current_plates:
            if p.get("plate_index") == plate_index:
                p = {
                    **p,
                    "status": "failed" if error_message else "generated",
                    "stl_path": stl_path,
                    "error_message": error_message,
                }
            new_plates.append(p)

        # Whole-dict reassignment, not an in-place nested mutation -- this
        # model has no MutableDict/MutableList wrapper on `layout_json`, so an
        # in-place nested mutation would not be flagged dirty by SQLAlchemy
        # and `commit()` would silently write nothing back for this field.
        locked_layout.layout_json = {**(locked_layout.layout_json or {}), "plates": new_plates}
        await session.commit()
