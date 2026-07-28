from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import Any

from workshop_geometry.label_engine import ENGINE_VERSION, LabelParameters, MagnetPocketParameters, calculate_metrics

from ..models import LabelStyleProfile, MagnetProfile

# Assembles a JSON-safe dict shaped exactly like `LabelParameters` (with a
# nested `MagnetPocketParameters` dict under "magnets") from the two source
# profiles + the design's own text. This dict becomes `Design.parameters_json`
# -- the immutable snapshot the worker later reconstructs a dataclass from to
# call `generate_label()`.


def build_label_parameters(
    label_style: LabelStyleProfile, magnet: MagnetProfile | None, text: str, qr_url: str | None = None
) -> dict[str, Any]:
    magnets: dict[str, Any] | None = None
    if magnet is not None and label_style.magnet_count:
        magnets = {
            "diameter_mm": float(magnet.diameter_mm),
            "thickness_mm": float(magnet.thickness_mm),
            "diameter_clearance_mm": float(magnet.diameter_clearance_mm),
            "depth_clearance_mm": float(magnet.depth_clearance_mm),
            "seal_cap_mm": float(magnet.seal_cap_mm) if magnet.seal_cap_mm is not None else 0.0,
            "count": label_style.magnet_count,
            "edge_offset_mm": float(label_style.magnet_edge_offset_mm),
            "minimum_bridge_mm": float(label_style.magnet_minimum_bridge_mm),
            "support_extra_mm": float(label_style.magnet_support_extra_mm),
        }

    return {
        "text": text,
        "text_height_mm": float(label_style.text_height_mm),
        "body_depth_mm": float(label_style.body_depth_mm),
        "outline_offset_mm": float(label_style.outline_offset_mm),
        "font_family": label_style.font_family,
        "font_weight": label_style.font_weight,
        "font_style": label_style.font_style,
        "horizontal_scale": float(label_style.horizontal_scale),
        "minimum_width_mm": float(label_style.minimum_width_mm),
        "fixed_width_mm": float(label_style.fixed_width_mm) if label_style.fixed_width_mm is not None else None,
        "magnets": magnets,
        "qr_url": qr_url,
    }


def label_parameters_from_dict(params_dict: dict[str, Any]) -> LabelParameters:
    """Reconstruct the `LabelParameters` dataclass (with nested
    `MagnetPocketParameters`) from a dict shaped like `build_label_parameters`'s
    output -- used both here (for the early hash) and by the worker (for the
    real generation)."""
    magnets_dict = params_dict.get("magnets")
    magnets = MagnetPocketParameters(**magnets_dict) if magnets_dict else None
    kwargs = {k: v for k, v in params_dict.items() if k != "magnets"}
    return LabelParameters(**kwargs, magnets=magnets)


def compute_manifest_fields(params_dict: dict[str, Any]) -> tuple[str, str]:
    """Returns `(engine_version, content_hash)`.

    Calls `calculate_metrics()` (which internally validates the parameters,
    raising `ValueError` on a bad combo -- e.g. magnet count that doesn't fit
    the label width) and hashes `{parameters, metrics}` with the identical
    `json.dumps(..., sort_keys=True)` + SHA-256 formula `generation_manifest()`
    in `workshop_geometry.label_engine` uses, so this early hash is
    byte-identical to what generation later confirms.
    """
    parameters = label_parameters_from_dict(params_dict)
    metrics = calculate_metrics(parameters)
    pdata = asdict(parameters)
    mdata = asdict(metrics)
    digest = hashlib.sha256(json.dumps({"parameters": pdata, "metrics": mdata}, sort_keys=True).encode()).hexdigest()
    return ENGINE_VERSION, digest
