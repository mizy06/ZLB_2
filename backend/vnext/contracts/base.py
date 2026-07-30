from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class FrozenContract(BaseModel):
    """Strict immutable language binding for an archived JSON contract."""

    model_config = ConfigDict(
        allow_inf_nan=False,
        extra="forbid",
        frozen=True,
        validate_default=True,
    )
