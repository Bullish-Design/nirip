"""Shared base model for all nirip types."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class NiripModel(BaseModel):
    """Base for all nirip models.

    Rejects unknown fields and is immutable by default.
    Subclasses that need mutability override model_config explicitly.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        use_enum_values=True,
    )
