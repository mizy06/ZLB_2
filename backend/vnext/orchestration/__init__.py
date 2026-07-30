"""Role-scoped orchestration policy for immutable artifacts."""

from .permissions import (
    PermissionDenied,
    WRITE_PERMISSIONS,
    assert_submission_allowed,
    assert_write_allowed,
)

__all__ = [
    "PermissionDenied",
    "WRITE_PERMISSIONS",
    "assert_submission_allowed",
    "assert_write_allowed",
]
