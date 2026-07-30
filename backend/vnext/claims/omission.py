from __future__ import annotations

import hashlib

from backend.vnext.artifacts.canonical import (
    canonical_json_bytes,
    payload_digest,
)
from backend.vnext.contracts.claims import (
    AuditorAttempt,
    ClaimLedger,
    ExtractionStatus,
    OmissionAudit,
    OmissionReason,
)
from backend.vnext.contracts.common import (
    ArtifactProducerRef,
    ArtifactRef,
    RuntimeRole,
)
from backend.vnext.contracts.inventory import (
    InventoryEntry,
    InventoryEntryKind,
    InventoryImportance,
    InventoryInspectionStatus,
    SourceInventory,
)


OMISSION_AUDITOR_VERSION = "1.0.0"
_AUDITOR = ArtifactProducerRef(
    producer_id="vnext-source-omission-auditor",
    producer_version=OMISSION_AUDITOR_VERSION,
    role=RuntimeRole.OMISSION_AUDITOR,
)


def _stable_id(prefix: str, value: object) -> str:
    digest = hashlib.sha256(
        b"zlb-vnext-omission-audit-v1\0" + canonical_json_bytes(value)
    ).hexdigest()
    return prefix + digest[:32]


def _entry_evidence(entry: InventoryEntry):
    return entry.evidence_refs


def audit_claim_omissions(
    inventory: SourceInventory,
    ledger: ClaimLedger,
    *,
    source_inventory_ref: ArtifactRef,
    claim_ledger_ref: ArtifactRef,
    attempt: int = 1,
    structurally_accounted_source_ids: tuple[str, ...] = (),
    explicitly_nonclaim_source_ids: tuple[str, ...] = (),
    forced_unresolved_source_ids: tuple[str, ...] = (),
) -> OmissionAudit:
    """Reconcile every inventory entry independently from atomizer intent."""

    claim_source_ids = {
        evidence.ref_id
        for claim in ledger.claims
        if claim.extraction_status
        in {ExtractionStatus.EXTRACTED, ExtractionStatus.PARTIAL}
        for evidence in claim.source_evidence_refs
    }
    entries = inventory.all_entries()
    entry_by_id = {entry.source_id: entry for entry in entries}
    inventory_ids = set(entry_by_id)
    supplied_ids = {
        *structurally_accounted_source_ids,
        *explicitly_nonclaim_source_ids,
        *forced_unresolved_source_ids,
    }
    unknown_supplied = supplied_ids - inventory_ids
    if unknown_supplied:
        raise ValueError(
            "omission audit received unknown source IDs: "
            + ", ".join(sorted(unknown_supplied))
        )
    accounted = {
        source_id
        for source_id in claim_source_ids
        if source_id in entry_by_id
    }
    accounted.update(structurally_accounted_source_ids)
    explicitly_nonclaim = set(explicitly_nonclaim_source_ids) - accounted
    unresolved = {
        entry.source_id
        for entry in entries
        if entry.source_kind is InventoryEntryKind.UNRESOLVED
        or (
            entry.inspection_status
            is InventoryInspectionStatus.UNRESOLVED
            and entry.source_id not in accounted
        )
    }
    unresolved.update(forced_unresolved_source_ids)
    unresolved.update(ledger.unresolved_source_ids)
    unresolved.difference_update(accounted)
    unresolved.difference_update(explicitly_nonclaim)

    entries_by_page: dict[str, list[InventoryEntry]] = {}
    for entry in entries:
        if entry.page_id is None or entry.source_kind is InventoryEntryKind.PAGE:
            continue
        entries_by_page.setdefault(entry.page_id, []).append(entry)
    for page_entry in inventory.page_entries:
        if (
            page_entry.source_id in unresolved
            or page_entry.source_id in explicitly_nonclaim
        ):
            continue
        children = entries_by_page.get(page_entry.source_id, [])
        reconciled_children = accounted | unresolved
        if children and all(
            child.source_id in reconciled_children for child in children
        ):
            accounted.add(page_entry.source_id)
        elif not children and page_entry.source_id not in accounted:
            unresolved.add(page_entry.source_id)

    omitted = {
        entry.source_id for entry in entries
    } - accounted - unresolved - explicitly_nonclaim
    high_importance = {
        entry.source_id
        for entry in entries
        if entry.source_id in omitted
        and entry.importance
        in {InventoryImportance.HIGH, InventoryImportance.MUST_HAVE}
    }
    must_have_ids = {
        source_id
        for item in inventory.human_must_have_refs
        for source_id in item.source_ids
    }
    must_have_recall = (
        1.0
        if not must_have_ids
        else len(must_have_ids & accounted) / len(must_have_ids)
    )
    reasons = tuple(
        OmissionReason(
            source_id=source_id,
            reason_code="claim_missing",
            explanation=(
                "No source-only claim, structural accounting, or explicit "
                "unresolved decision references this inventory entry."
            ),
            evidence_refs=_entry_evidence(entry_by_id[source_id]),
        )
        for source_id in sorted(omitted)
    )
    input_digest = payload_digest(
        {
            "claim_ledger": claim_ledger_ref.payload_digest,
            "source_inventory": source_inventory_ref.payload_digest,
        }
    )
    outcome = (
        "omission_found"
        if omitted
        else ("unresolved" if unresolved else "pass")
    )
    return OmissionAudit(
        audit_id=_stable_id(
            "omission_audit_",
            {
                "attempt": attempt,
                "claim_ledger": claim_ledger_ref.payload_digest,
                "source_inventory": source_inventory_ref.payload_digest,
            },
        ),
        source_inventory_ref=source_inventory_ref,
        claim_ledger_ref=claim_ledger_ref,
        accounted_source_ids=tuple(sorted(accounted)),
        omitted_source_ids=tuple(sorted(omitted)),
        explicitly_nonclaim_source_ids=tuple(sorted(explicitly_nonclaim)),
        unresolved_source_ids=tuple(sorted(unresolved)),
        high_importance_omitted_source_ids=tuple(
            sorted(high_importance)
        ),
        must_have_recall=must_have_recall,
        omission_reasons=reasons,
        auditor_attempts=(
            AuditorAttempt(
                attempt=attempt,
                producer=_AUDITOR,
                input_digest=input_digest,
                outcome=outcome,
            ),
        ),
    )
