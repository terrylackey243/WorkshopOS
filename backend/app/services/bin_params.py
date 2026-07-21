from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import Any

from workshop_geometry.bin_engine import ENGINE_VERSION, BinParameters, calculate_metrics

from ..models import MagnetProfile

# Assembles a JSON-safe dict shaped exactly like `BinParameters` from the
# create-request fields + the optional magnet profile. This dict becomes
# `InsertDesign.parameters_json` -- the immutable snapshot the worker later
# reconstructs a dataclass from to call `generate_bin()`. Mirrors
# `label_params.py`'s exact approach from Milestone 2.


def build_bin_parameters(
    *,
    grid_width_units: int,
    grid_depth_units: int,
    height_units: int,
    compartments_x: int,
    compartments_y: int,
    include_stacking_lip: bool,
    magnet: MagnetProfile | None,
) -> dict[str, Any]:
    return {
        "grid_width_units": grid_width_units,
        "grid_depth_units": grid_depth_units,
        "height_units": height_units,
        "compartments_x": compartments_x,
        "compartments_y": compartments_y,
        "include_stacking_lip": include_stacking_lip,
        "magnet_diameter_mm": float(magnet.diameter_mm) if magnet is not None else None,
        "magnet_thickness_mm": float(magnet.thickness_mm) if magnet is not None else None,
        "magnet_diameter_clearance_mm": float(magnet.diameter_clearance_mm) if magnet is not None else 0.2,
        "magnet_depth_clearance_mm": float(magnet.depth_clearance_mm) if magnet is not None else 0.2,
    }


def bin_parameters_from_dict(params_dict: dict[str, Any]) -> BinParameters:
    """Reconstruct the `BinParameters` dataclass from a dict shaped like
    `build_bin_parameters`'s output -- used both here (for the early hash)
    and by the worker (for the real generation)."""
    return BinParameters(**params_dict)


def compute_manifest_fields(params_dict: dict[str, Any]) -> tuple[str, str, dict[str, float]]:
    """Returns `(engine_version, content_hash, bounds)`.

    Calls `calculate_metrics()` (which internally validates the parameters,
    raising `ValueError` on a bad combo -- e.g. compartment counts that don't
    divide the grid evenly) and hashes `{parameters, metrics}` with the
    identical `json.dumps(..., sort_keys=True)` + SHA-256 formula
    `generation_manifest()` in `workshop_geometry.bin_engine` uses, so this
    early hash is byte-identical to what generation later confirms. This is a
    cheap dimension-check -- it does NOT run the full boolean CSG pipeline.

    `bounds` is the `{width_mm, depth_mm, height_mm}` shape stored on
    `InsertDesign.bounds_json`.
    """
    parameters = bin_parameters_from_dict(params_dict)
    metrics = calculate_metrics(parameters)
    pdata = asdict(parameters)
    mdata = asdict(metrics)
    digest = hashlib.sha256(json.dumps({"parameters": pdata, "metrics": mdata}, sort_keys=True).encode()).hexdigest()
    bounds = {"width_mm": metrics.width_mm, "depth_mm": metrics.depth_mm, "height_mm": metrics.height_mm}
    return ENGINE_VERSION, digest, bounds
