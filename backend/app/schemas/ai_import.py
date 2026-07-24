from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

# The 5 existing profile types (see app/schemas/profiles.py), spelled the
# same way the frontend's profile-type dropdown and `PROFILE_TYPE_SPECS`
# registry (app/services/ai_profile_extraction.py) use them.
ProfileTypeKey = Literal["printer", "magnet", "material", "drawer_profile", "label_style"]


class AiSettingsUpdate(BaseModel):
    anthropic_api_key: str = Field(min_length=1)


class AiExtractRequest(BaseModel):
    profile_type: ProfileTypeKey
    unit: Literal["in", "mm"]
    prompt: str = Field(min_length=1, max_length=20000)


class AiExtractedRow(BaseModel):
    # None when the prompt didn't specify a name for this row -- the LLM is
    # instructed to never invent one (see ai_profile_extraction.py), and a
    # blank name is surfaced to the user as "needs fixing", not silently filled in.
    name: str | None
    # Already unit-converted (in -> mm) and remapped to the real Create-schema
    # field names (e.g. "inside_width_mm"), ready to hand to the existing
    # */profiles/* create endpoint once the user confirms this row.
    fields: dict[str, Decimal | str | int | None]
    # True if `name` collides with an existing profile of this type for this org.
    name_conflict: bool


class AiExtractResponse(BaseModel):
    rows: list[AiExtractedRow]
