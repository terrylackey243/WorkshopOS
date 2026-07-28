from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

from anthropic import AsyncAnthropic

from ..models import DrawerProfile, LabelStyleProfile, MagnetProfile, MaterialProfile, PrinterProfile

MM_PER_INCH = Decimal("25.4")

CLAUDE_MODEL = "claude-sonnet-5"

_TOOL_NAME = "extract_profiles"


@dataclass(frozen=True)
class FieldSpec:
    key: str  # unit-agnostic name the LLM sees, e.g. "build_width"
    target: str  # real Create-schema field name, e.g. "build_width_mm"
    description: str
    kind: Literal["number", "text", "enum"]
    convert: bool  # apply in -> mm conversion when unit == "in"
    required: bool
    enum_values: tuple[str, ...] | None = None


# One entry per existing profile type (see app/schemas/profiles.py /
# app/models/profiles.py). Only the fields actually named in the approved
# per-type placeholder copy are exposed to the LLM -- everything else keeps
# the real Create schema's own default, which keeps the tool schema small
# and matches exactly what the prompt box tells the user it accepts.
PROFILE_TYPE_SPECS: dict[str, tuple[type, list[FieldSpec]]] = {
    "printer": (
        PrinterProfile,
        [
            FieldSpec("build_width", "build_width_mm", "Build plate width", "number", convert=True, required=True),
            FieldSpec("build_depth", "build_depth_mm", "Build plate depth", "number", convert=True, required=True),
            FieldSpec("build_height", "build_height_mm", "Build plate height", "number", convert=True, required=True),
            FieldSpec(
                "nozzle_diameter",
                "nozzle_diameter_mm",
                "Nozzle diameter in mm -- always mm regardless of the chosen unit, nozzle sizes are never given in inches",
                "number",
                convert=False,
                required=False,
            ),
            FieldSpec(
                "usable_margin",
                "usable_margin_mm",
                "Usable print-margin in mm -- always mm regardless of the chosen unit",
                "number",
                convert=False,
                required=False,
            ),
            FieldSpec("manufacturer", "manufacturer", "Manufacturer", "text", convert=False, required=False),
            FieldSpec("model", "model", "Model", "text", convert=False, required=False),
        ],
    ),
    "magnet": (
        MagnetProfile,
        [
            FieldSpec("diameter", "diameter_mm", "Magnet diameter", "number", convert=True, required=True),
            FieldSpec("thickness", "thickness_mm", "Magnet thickness", "number", convert=True, required=True),
            FieldSpec(
                "diameter_clearance",
                "diameter_clearance_mm",
                "Diameter clearance in mm -- always mm regardless of the chosen unit",
                "number",
                convert=False,
                required=False,
            ),
            FieldSpec(
                "depth_clearance",
                "depth_clearance_mm",
                "Depth clearance in mm -- always mm regardless of the chosen unit",
                "number",
                convert=False,
                required=False,
            ),
            FieldSpec(
                "fit_type",
                "fit_type",
                "How the magnet fits its pocket",
                "enum",
                convert=False,
                required=False,
                enum_values=("press", "glue", "sealed"),
            ),
        ],
    ),
    "material": (
        MaterialProfile,
        [
            FieldSpec(
                "material_type", "material_type", "Material type, e.g. PLA, PETG, ABS", "text", convert=False, required=True
            ),
            FieldSpec(
                "xy_compensation",
                "xy_compensation_mm",
                "XY compensation in mm, between -2 and 2 -- always mm regardless of the chosen unit",
                "number",
                convert=False,
                required=False,
            ),
            FieldSpec("notes", "notes", "Freeform notes", "text", convert=False, required=False),
        ],
    ),
    "drawer_profile": (
        DrawerProfile,
        [
            FieldSpec("inside_width", "inside_width_mm", "Inside width", "number", convert=True, required=True),
            FieldSpec("inside_depth", "inside_depth_mm", "Inside depth", "number", convert=True, required=True),
            FieldSpec("inside_height", "inside_height_mm", "Inside height", "number", convert=True, required=True),
            FieldSpec(
                "grid_unit",
                "grid_unit_mm",
                "Gridfinity grid unit in mm, typically 42 -- always mm regardless of the chosen unit, this is a fixed physical standard",
                "number",
                convert=False,
                required=False,
            ),
        ],
    ),
    "label_style": (
        LabelStyleProfile,
        [
            FieldSpec("minimum_width", "minimum_width_mm", "Minimum label width", "number", convert=True, required=False),
            FieldSpec("magnet_count", "magnet_count", "Number of magnets embedded in the label", "number", convert=False, required=False),
        ],
    ),
}


def _field_json_schema(spec: FieldSpec) -> dict[str, Any]:
    if spec.kind == "number":
        schema: dict[str, Any] = {"type": "number"}
    elif spec.kind == "enum":
        schema = {"type": "string", "enum": list(spec.enum_values or ())}
    else:
        schema = {"type": "string"}
    schema["description"] = spec.description
    return schema


def build_tool_schema(profile_type: str) -> dict[str, Any]:
    _, specs = PROFILE_TYPE_SPECS[profile_type]
    properties: dict[str, Any] = {
        "name": {
            "type": "string",
            "description": (
                "The name for this profile, exactly as the user wrote it. Never invent or "
                "guess a name -- if the prompt didn't give this row a name, omit this field, "
                "unless the user explicitly asked you to name rows based on their dimensions."
            ),
        }
    }
    for spec in specs:
        properties[spec.key] = _field_json_schema(spec)

    return {
        "name": _TOOL_NAME,
        "description": f"Extract a list of {profile_type} profiles described in the user's prompt.",
        "input_schema": {
            "type": "object",
            "properties": {
                "rows": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": properties,
                        "required": [s.key for s in specs if s.required],
                    },
                }
            },
            "required": ["rows"],
        },
    }


def _system_prompt(profile_type: str, unit: str) -> str:
    unit_label = "inches" if unit == "in" else "millimeters"
    return (
        f"You extract {profile_type} profile presets from a shop owner's free-text description. "
        f"They are describing dimensions in {unit_label} unless a field's description says otherwise "
        "(some fields are always in millimeters regardless of the chosen unit -- read each field's "
        "description). Extract the numbers exactly as written; do not convert units yourself. "
        "Never invent a value for `name` -- if a row has no name in the prompt, omit `name` for that "
        "row entirely, unless the user explicitly asks you to name rows based on their dimensions. "
        "One prompt may describe multiple rows; extract every row you can find."
    )


async def extract_rows(api_key: str, profile_type: str, unit: str, prompt: str) -> list[dict[str, Any]]:
    """Call Claude with forced tool-use to extract structured rows from `prompt`.

    Uses the async Anthropic client (unlike services/billing.py's sync Stripe
    calls) because an extraction call can take several seconds -- long enough
    that blocking this app's async event loop for it would stall other
    requests, unlike Stripe's sub-second calls.
    """
    tool = build_tool_schema(profile_type)
    client = AsyncAnthropic(api_key=api_key)
    response = await client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=8192,
        system=_system_prompt(profile_type, unit),
        tools=[tool],
        tool_choice={"type": "tool", "name": _TOOL_NAME},
        messages=[{"role": "user", "content": prompt}],
    )
    for block in response.content:
        if block.type == "tool_use" and block.name == _TOOL_NAME:
            return list(block.input.get("rows", []))
    return []


def convert_and_map(rows: list[dict[str, Any]], profile_type: str, unit: str) -> list[dict[str, Any]]:
    """Remap LLM field keys onto real Create-schema field names, converting
    `convert=True` fields from inches to millimeters in plain Python -- the
    LLM never does this arithmetic itself (see the design discussion this
    implements)."""
    _, specs = PROFILE_TYPE_SPECS[profile_type]
    mapped_rows: list[dict[str, Any]] = []
    for row in rows:
        mapped: dict[str, Any] = {"name": row.get("name")}
        for spec in specs:
            value = row.get(spec.key)
            if value is None:
                continue
            if spec.kind == "number" and spec.convert and unit == "in":
                value = Decimal(str(value)) * MM_PER_INCH
            elif spec.kind == "number":
                value = Decimal(str(value))
            mapped[spec.target] = value
        mapped_rows.append(mapped)
    return mapped_rows
