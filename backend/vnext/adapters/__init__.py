"""Compatibility adapters live here and may only depend outward on legacy."""
from .legacy_result import LegacyAdaptationBlocked, to_legacy_result

__all__ = [
    "LegacyAdaptationBlocked",
    "to_legacy_result",
]
