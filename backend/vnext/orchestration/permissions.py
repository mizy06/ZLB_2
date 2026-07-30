from __future__ import annotations

from backend.vnext.contracts.base import FrozenContract
from backend.vnext.contracts.common import (
    ARTIFACT_WRITERS,
    ArtifactType,
    RuntimeRole,
)
from backend.vnext.contracts.registry import registration_for_model


class PermissionDenied(ValueError):
    pass


WRITE_PERMISSIONS: dict[RuntimeRole, frozenset[ArtifactType]] = {
    role: frozenset(
        artifact_type
        for artifact_type, writers in ARTIFACT_WRITERS.items()
        if role in writers
    )
    for role in RuntimeRole
}

STRUCTURE_WRITERS = frozenset(
    {
        RuntimeRole.GLOBAL_STRUCTURE_PLANNER,
        RuntimeRole.RECURSIVE_REGION_PLANNER,
    }
)


def assert_write_allowed(
    role: RuntimeRole,
    artifact_type: ArtifactType,
) -> None:
    if artifact_type not in WRITE_PERMISSIONS[role]:
        raise PermissionDenied(
            f"{role.value} cannot write {artifact_type.value}"
        )
    if (
        artifact_type is ArtifactType.REGION_PLAN
        and role not in STRUCTURE_WRITERS
    ):
        raise PermissionDenied(
            "RegionPlan has a single top-down write authority"
        )


def assert_submission_allowed(
    role: RuntimeRole,
    payload: FrozenContract,
) -> ArtifactType:
    registration = registration_for_model(payload)
    if registration.artifact_type is None:
        raise PermissionDenied("metadata contracts cannot be stored as payload")
    assert_write_allowed(role, registration.artifact_type)
    if (
        role is RuntimeRole.BOTTOM_UP_REGION_AUDITOR
        and registration.artifact_type is not ArtifactType.REPLAN_REQUEST
    ):
        raise PermissionDenied(
            "bottom-up agents may submit only ReplanRequest"
        )
    return registration.artifact_type
