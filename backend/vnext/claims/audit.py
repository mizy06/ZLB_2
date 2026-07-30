from __future__ import annotations

from dataclasses import dataclass

from backend.vnext.contracts.claims import OmissionAudit
from backend.vnext.contracts.inventory import SourceInventory


@dataclass(frozen=True, slots=True)
class OmissionGateResult:
    accepted: bool
    reason_codes: tuple[str, ...]


def evaluate_omission_audit(
    inventory: SourceInventory,
    audit: OmissionAudit,
) -> OmissionGateResult:
    inventory_ids = {entry.source_id for entry in inventory.all_entries()}
    accounted = set(audit.accounted_source_ids)
    omitted = set(audit.omitted_source_ids)
    nonclaim = set(audit.explicitly_nonclaim_source_ids)
    unresolved = set(audit.unresolved_source_ids)
    reconciled = accounted | omitted | nonclaim | unresolved
    reasons: list[str] = []
    if reconciled != inventory_ids:
        reasons.append("source_inventory_partition_mismatch")
    if audit.high_importance_omitted_source_ids:
        reasons.append("high_importance_source_omitted")
    must_have_ids = {
        source_id
        for must_have in inventory.human_must_have_refs
        for source_id in must_have.source_ids
    }
    expected_recall = (
        1.0
        if not must_have_ids
        else len(must_have_ids & accounted) / len(must_have_ids)
    )
    if abs(expected_recall - audit.must_have_recall) > 1e-9:
        reasons.append("must_have_recall_mismatch")
    if expected_recall < 1:
        reasons.append("must_have_source_not_accounted")
    return OmissionGateResult(not reasons, tuple(reasons))
