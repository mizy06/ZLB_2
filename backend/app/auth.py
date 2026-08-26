from __future__ import annotations

from dataclasses import dataclass

from .config import Settings, settings


@dataclass(frozen=True)
class Principal:
    id: str


def workbench_principal(config: Settings) -> Principal:
    return Principal(id=config.workbench_owner_id)


async def require_api_principal() -> Principal:
    return workbench_principal(settings)
