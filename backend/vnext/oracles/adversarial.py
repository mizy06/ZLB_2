from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.vnext.contracts.common import ArtifactType, RuntimeRole
from backend.vnext.orchestration.permissions import (
    PermissionDenied,
    assert_write_allowed,
)


@dataclass(frozen=True, slots=True)
class OracleMismatch:
    case_id: str
    expected: str
    actual: str


_FORBIDDEN_STRUCTURE_LABELS = frozenset(
    {
        "well-established",
        "few reports",
        "another proton is removed",
        "(neutral conditions)",
        "course content",
        "other topics",
    }
)


def _permission_outcome(parameters: dict[str, Any]) -> str:
    try:
        assert_write_allowed(
            RuntimeRole(parameters["role"]),
            ArtifactType(parameters["artifact_type"]),
        )
    except PermissionDenied:
        return "reject"
    return "allow"


def _split_outcome(parameters: dict[str, Any]) -> str:
    required = (
        parameters.get("child_count", 0) >= 2,
        parameters.get("parent_supported", False),
        parameters.get("children_self_contained", False),
        parameters.get("children_supported", False),
        parameters.get("sibling_separation", False),
        parameters.get("within_region_cohesion", False),
        parameters.get("comparable_granularity", False),
        parameters.get("boundaries_explainable", False),
        parameters.get("inventory_reconciled", False),
        not parameters.get("capacity_as_semantics", False),
    )
    return "allow" if all(required) else "reject"


def _stop_outcome(parameters: dict[str, Any]) -> str:
    required = (
        parameters.get("single_intent", False),
        parameters.get("no_subheading", False),
        parameters.get("comparable_granularity", False),
        parameters.get("inventory_reconciled", False),
        parameters.get("would_fragment", False),
        parameters.get("no_high_omission", False),
        parameters.get("no_mixed_theme", False),
    )
    return "allow" if all(required) else "unresolved"


def _canonical_outcome(parameters: dict[str, Any]) -> str:
    status = parameters.get("status")
    authority = parameters.get("authority")
    if status != "accepted":
        return "retain_audit"
    if authority not in {"courseware_direct", "outline_structural"}:
        return "reject"
    if (
        authority == "outline_structural"
        and parameters.get("relation") != "topic_contains"
    ):
        return "reject"
    if not parameters.get("relation_evidence", False):
        return "reject"
    return "allow"


def _actual_outcome(case: dict[str, Any]) -> str:
    probe = case["probe"]
    parameters = case.get("parameters", {})
    if probe == "permission":
        return _permission_outcome(parameters)
    if probe == "split_gate":
        return _split_outcome(parameters)
    if probe == "stop_gate":
        return _stop_outcome(parameters)
    if probe == "structure_label":
        return (
            "reject"
            if parameters["label"].strip().casefold()
            in _FORBIDDEN_STRUCTURE_LABELS
            else "allow"
        )
    if probe == "source_retention":
        return "retain" if parameters.get("represented") else "reject"
    if probe == "interpretation_layer":
        return (
            "reject"
            if parameters.get("recorded_as_observation")
            else "retain_hypothesis"
        )
    if probe == "claim_role":
        return (
            "retain"
            if parameters.get("retained")
            and not parameters.get("role_used_to_delete")
            else "reject"
        )
    if probe == "source_accounting":
        inventory = set(parameters.get("inventory", ()))
        partitions = set().union(
            parameters.get("accounted", ()),
            parameters.get("nonclaim", ()),
            parameters.get("unresolved", ()),
            parameters.get("omitted", ()),
        )
        return "allow" if inventory == partitions else "reject"
    if probe == "veto_reopen":
        novel = parameters.get("new_digest") not in set(
            parameters.get("old_digests", ())
        )
        return (
            "allow"
            if parameters.get("supersedes") and novel
            else "reject"
        )
    if probe == "canonical_policy":
        return _canonical_outcome(parameters)
    if probe == "parentless":
        return (
            "unresolved"
            if parameters.get("disposition") == "unresolved"
            else "reject"
        )
    if probe == "multiple_parents":
        return (
            "allow_dag"
            if parameters.get("all_edges_accepted")
            else "reject"
        )
    if probe == "relation_cycle":
        return (
            "reject"
            if parameters.get("hierarchical")
            else "retain_audit"
        )
    if probe == "small_perfect_graph":
        return (
            "reject"
            if parameters.get("high_importance_omitted", 0) > 0
            else "allow"
        )
    if probe == "evidence_namespace":
        namespace = parameters["namespace"]
        ref_id = parameters["ref_id"]
        prefixes = {
            "courseware": "src:",
            "external": "ext:",
            "human": "human:",
            "system": "sys:",
        }
        return (
            "allow"
            if ref_id.startswith(prefixes[namespace])
            else "reject"
        )
    if probe == "owner_isolation":
        owners = parameters.get("owners", ())
        scopes = {
            hashlib.sha256(
                ("zlb-vnext-owner-v1\0" + owner).encode()
            ).hexdigest()
            for owner in owners
        }
        return "allow" if len(scopes) == len(owners) else "reject"
    if probe == "projection_parent":
        return (
            "allow"
            if parameters.get("canonical_status") == "accepted"
            and parameters.get("direct", False)
            else "reject"
        )
    if probe == "explicit_unresolved":
        return (
            "unresolved"
            if parameters.get("selective_coverage")
            and parameters.get("unresolved_preserved")
            else "reject"
        )
    if probe == "state_separation":
        values = (
            parameters.get("extraction_status"),
            parameters.get("source_entailment_status"),
            parameters.get("external_validity_status"),
            parameters.get("publication_status"),
        )
        return "allow" if all(values) and len(set(values)) > 1 else "reject"
    if probe == "future_stage":
        return "blocked_pending_stage"
    raise ValueError(f"unknown adversarial probe: {probe}")


def run_adversarial_oracle(path: Path) -> tuple[OracleMismatch, ...]:
    fixture = json.loads(path.read_text(encoding="utf-8"))
    mismatches: list[OracleMismatch] = []
    for case in fixture["cases"]:
        actual = _actual_outcome(case)
        if actual != case["expected"]:
            mismatches.append(
                OracleMismatch(
                    case_id=case["id"],
                    expected=case["expected"],
                    actual=actual,
                )
            )
    return tuple(mismatches)
