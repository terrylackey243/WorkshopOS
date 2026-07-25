from __future__ import annotations

import base64
import io
from typing import Any

import pillow_heif
from anthropic import AsyncAnthropic
from PIL import Image

from .ai_profile_extraction import CLAUDE_MODEL

# Lets PIL's Image.open() decode .heic/.heif -- the format iPhones shoot by
# default, which isn't one Anthropic's vision API accepts (see
# _ANTHROPIC_SUPPORTED_MEDIA_TYPES below). Registered once at import time.
pillow_heif.register_heif_opener()

_TOOL_NAME = "extract_tools"

# Anthropic's vision API only accepts these; anything else (HEIC/HEIF off a
# phone camera, TIFF, BMP, ...) must be re-encoded before it's sent.
_ANTHROPIC_SUPPORTED_MEDIA_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}

# Anthropic hard-rejects any image over 8000px on either dimension, and
# recommends staying at or below ~1568px on the long edge anyway (larger
# images get downscaled server-side before tokenization, so sending one
# pre-resized saves upload time/cost for no quality loss). A full-resolution
# phone-camera photo (e.g. a 6048x8064 iPhone portrait shot) blows past both
# limits -- found by hand testing this feature against real camera photos,
# which came back as a 502 (Anthropic's 400 invalid_request_error, caught by
# `extract_tool_rows`'s broad `except anthropic.APIError` and re-raised as a
# 502 Bad Gateway) instead of ever reaching the model.
_MAX_LONG_EDGE_PX = 1568


def _prepare_image(image_bytes: bytes, media_type: str) -> tuple[bytes, str]:
    """Re-encodes `image_bytes` as JPEG when Anthropic wouldn't accept it as-is
    -- either because its format isn't one of the four Anthropic supports
    (e.g. HEIC) or because it's larger than Anthropic's size limits. Returns
    the original bytes/media_type unchanged when neither applies."""
    needs_conversion = media_type not in _ANTHROPIC_SUPPORTED_MEDIA_TYPES
    with Image.open(io.BytesIO(image_bytes)) as img:
        oversized = max(img.size) > _MAX_LONG_EDGE_PX
        if not needs_conversion and not oversized:
            return image_bytes, media_type
        img = img.convert("RGB")
        if oversized:
            img.thumbnail((_MAX_LONG_EDGE_PX, _MAX_LONG_EDGE_PX), Image.LANCZOS)
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=85)
        return buffer.getvalue(), "image/jpeg"


_SYSTEM_PROMPT = (
    "You are looking at a photo of one or more tools laid on or around a standard US Letter "
    "(8.5x11in) sheet of paper, used as a size reference. Identify every distinct tool visible.\n\n"
    "Sizing: prefer reading any size printed or stamped directly on the tool (e.g. a wrench's "
    "jaw size, a socket's drive size) over estimating from the paper -- stamped text is far more "
    "reliable than a geometric guess. Fall back to comparing the tool against the sheet of paper "
    "only when no legible size marking exists. If you cannot determine a size either way, leave "
    "it out rather than guessing. Fold any determined size into `name` the way a person would "
    'write it by hand, e.g. "10mm Combination Wrench" or "1/2in Drive Socket".\n\n'
    "Grouping: if the photo shows multiple visually-identical tools (same type, size, and "
    "finish), report them as a single row with `quantity` set to how many you count, rather than "
    "one row per item. Distinct tools (different size or type) always get their own row.\n\n"
    "`manufacturer` and `category` are best-effort guesses -- only set `manufacturer` when a "
    "brand name or logo is actually legible in the photo, never invent one. `category` is a "
    "short freeform guess at what kind of tool this is (e.g. \"Wrench\", \"Pliers\", \"Screwdriver\").\n\n"
    "`confidence` is your own integer estimate from 0 to 100 of how sure you are about this row's "
    "identification as a whole (name, size, and category together) -- a plainly labeled, "
    "unambiguous tool should score high; a partially obscured or ambiguous one should score low.\n\n"
    "Skip objects you cannot identify as tools at all rather than inventing a row for them."
)


def _tool_schema() -> dict[str, Any]:
    return {
        "name": _TOOL_NAME,
        "description": "Report every distinct tool identified in the photo.",
        "input_schema": {
            "type": "object",
            "properties": {
                "rows": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Tool name, with any determined size folded in.",
                            },
                            "category": {
                                "type": "string",
                                "description": "Short freeform guess at the tool's category.",
                            },
                            "manufacturer": {
                                "type": "string",
                                "description": "Brand name, only if legible in the photo.",
                            },
                            "notes": {
                                "type": "string",
                                "description": "Anything worth flagging for the user's review, e.g. uncertainty.",
                            },
                            "quantity": {
                                "type": "integer",
                                "description": "How many identical instances of this tool are visible.",
                            },
                            "confidence": {
                                "type": "integer",
                                "description": "0-100 self-rated confidence in this row's identification.",
                            },
                        },
                        "required": ["name", "quantity", "confidence"],
                    },
                }
            },
            "required": ["rows"],
        },
    }


async def extract_tool_rows(api_key: str, image_bytes: bytes, media_type: str) -> list[dict[str, Any]]:
    """Call Claude with forced tool-use over a vision input to identify tools
    in a reference-sheet photo. Uses the async client for the same reason as
    `ai_profile_extraction.extract_rows` -- a vision call is slow enough to
    stall the event loop if made synchronously."""
    image_bytes, media_type = _prepare_image(image_bytes, media_type)
    tool = _tool_schema()
    client = AsyncAnthropic(api_key=api_key)
    response = await client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=8192,
        system=_SYSTEM_PROMPT,
        tools=[tool],
        tool_choice={"type": "tool", "name": _TOOL_NAME},
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": base64.b64encode(image_bytes).decode("ascii"),
                        },
                    },
                    {"type": "text", "text": "Identify every tool in this photo."},
                ],
            }
        ],
    )
    for block in response.content:
        if block.type == "tool_use" and block.name == _TOOL_NAME:
            return list(block.input.get("rows", []))
    return []
