from __future__ import annotations

import hashlib
from collections import defaultdict

from backend.vnext.artifacts.canonical import canonical_json_bytes
from backend.vnext.contracts.claims import OmissionAudit
from backend.vnext.contracts.inventory import SourceInventory
from backend.vnext.contracts.regions import (
    ReplanAction,
    ReplanRequest,
)

from .planner import RegionPlanningResult


def _stable_request_id(value: object) -> str:
    digest = hashlib.sha256(
        b"zlb-vnext-replan-request-v1\0" + canonical_json_bytes(value)
    ).hexdigest()
    return "replan_" + digest[:32]


def audit_regions_bottom_up(
    planning: RegionPlanningResult,
    inventory: SourceInventory,
    omission_audit: OmissionAudit,
) -> tuple[ReplanRequest, ...]:
    """Return requests only; this auditor has no RegionPlan write path."""

    if not omission_audit.omitted_source_ids:
        return ()
    entry_by_id = {
        entry.source_id: entry for entry in inventory.all_entries()
    }
    omitted_by_region: dict[str, list[str]] = defaultdict(list)
    for source_id in omission_audit.omitted_source_ids:
        region_id = planning.source_to_leaf_region.get(
            source_id,
            planning.root_region_id,
        )
        omitted_by_region[region_id].append(source_id)

    requests: list[ReplanRequest] = []
    for affected_region_id, source_ids in sorted(
        omitted_by_region.items()
    ):
        evidence = tuple(
            ref
            for source_id in sorted(source_ids)
            for ref in entry_by_id[source_id].evidence_refs
        )
        requests.append(
            ReplanRequest(
                request_id=_stable_request_id(
                    {
                        "affected_region_id": affected_region_id,
                        "omitted_source_ids": sorted(source_ids),
                    }
                ),
                affected_region_id=affected_region_id,
                minimum_replan_ancestor_id=affected_region_id,
                omitted_source_ids=tuple(sorted(source_ids)),
                requested_action=ReplanAction.RESPLIT,
                evidence_refs=evidence,
            )
        )
    return tuple(requests)
