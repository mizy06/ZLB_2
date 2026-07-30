"""Pilot quality evaluation with source-group and worst-slice guards."""

from .evaluator import (
    default_redesign_pilot_policy,
    evaluate_pilot,
)

__all__ = [
    "default_redesign_pilot_policy",
    "evaluate_pilot",
]
