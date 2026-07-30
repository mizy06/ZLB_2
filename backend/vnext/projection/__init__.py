"""Diagnostic view projection contract and graph-bound validation."""

from backend.vnext.contracts.projection import DiagnosticProjection

from .builder import build_diagnostic_projection
from .validation import (
    compute_projection_hash,
    validate_projection_against_graph,
)

__all__ = [
    "DiagnosticProjection",
    "build_diagnostic_projection",
    "compute_projection_hash",
    "validate_projection_against_graph",
]
