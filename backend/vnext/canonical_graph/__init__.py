"""Explicit-only canonical graph contract and assembler."""

from backend.vnext.contracts.graph import CanonicalExplicitGraph
from .builder import build_canonical_explicit_graph

__all__ = [
    "CanonicalExplicitGraph",
    "build_canonical_explicit_graph",
]
from .cross_links import (
    CrossLinkBuildResult,
    attach_verified_cross_links,
)

__all__ = [
    "CrossLinkBuildResult",
    "attach_verified_cross_links",
]
