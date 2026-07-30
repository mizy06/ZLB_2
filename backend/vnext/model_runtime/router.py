from __future__ import annotations

from collections.abc import Sequence

from backend.vnext.contracts.control import (
    ModelPortfolioManifest,
    ModelSlot,
)


class PortfolioRouteError(ValueError):
    pass


def _slot(
    portfolio: ModelPortfolioManifest,
    slot_name: str,
) -> ModelSlot:
    for item in portfolio.slots:
        if item.slot == slot_name:
            return item
    raise PortfolioRouteError(
        f"model portfolio does not define slot {slot_name!r}"
    )


def require_independent_pair(
    left: ModelSlot,
    right: ModelSlot,
    *,
    require_calibrated: bool,
) -> None:
    if (
        left.provider == right.provider
        and left.model_revision == right.model_revision
    ):
        raise PortfolioRouteError(
            "independent roles cannot use the same provider model revision"
        )
    if left.model_family == right.model_family:
        raise PortfolioRouteError(
            "independent roles cannot use the same model family"
        )
    if (
        left.independence_group
        and right.independence_group
        and left.independence_group == right.independence_group
    ):
        raise PortfolioRouteError(
            "independent roles cannot share an independence group"
        )
    if require_calibrated and (
        not left.independence_calibrated
        or not right.independence_calibrated
        or left.independence_group is None
        or right.independence_group is None
    ):
        raise PortfolioRouteError(
            "precision routing requires calibrated independence groups"
        )


def select_independent_verifier(
    portfolio: ModelPortfolioManifest,
    *,
    proposer_slot: str,
    verifier_slots: Sequence[str] = ("verifier_a", "verifier_b"),
    require_calibrated: bool = False,
) -> ModelSlot:
    proposer = _slot(portfolio, proposer_slot)
    failures: list[str] = []
    for verifier_slot in verifier_slots:
        try:
            verifier = _slot(portfolio, verifier_slot)
            require_independent_pair(
                proposer,
                verifier,
                require_calibrated=require_calibrated,
            )
        except PortfolioRouteError as exc:
            failures.append(f"{verifier_slot}: {exc}")
            continue
        return verifier
    raise PortfolioRouteError(
        "no independent verifier route is available"
        + (": " + "; ".join(failures) if failures else "")
    )


def select_precision_verifier_pair(
    portfolio: ModelPortfolioManifest,
    *,
    verifier_slots: Sequence[str] = ("verifier_a", "verifier_b"),
) -> tuple[ModelSlot, ModelSlot]:
    if len(verifier_slots) < 2:
        raise PortfolioRouteError(
            "precision routing requires two verifier slots"
        )
    left = _slot(portfolio, verifier_slots[0])
    right = _slot(portfolio, verifier_slots[1])
    require_independent_pair(
        left,
        right,
        require_calibrated=True,
    )
    return left, right
