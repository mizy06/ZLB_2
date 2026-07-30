from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class IncidentFinding:
    code: str
    message: str


def evaluate_aldehydes_ketones(
    candidate: dict[str, Any],
    oracle: dict[str, Any],
) -> tuple[IncidentFinding, ...]:
    findings: list[IncidentFinding] = []
    outline_labels = tuple(candidate.get("outline_labels", ()))
    if candidate.get("outline_entry_count", 0) < oracle[
        "minimum_outline_entry_count"
    ]:
        findings.append(
            IncidentFinding(
                "outline_count_incomplete",
                "not all source outline entries were retained",
            )
        )
    if not candidate.get("outline_matches_section_titles", False):
        findings.append(
            IncidentFinding(
                "outline_title_alignment_missing",
                "outline entries were not aligned to section titles",
            )
        )
    for prefix in oracle["required_outline_prefixes"]:
        if not any(label.startswith(prefix) for label in outline_labels):
            findings.append(
                IncidentFinding(
                    "missing_outline",
                    f"outline prefix {prefix} was not retained",
                )
            )
    forbidden = {
        label.casefold() for label in oracle["forbidden_top_level_labels"]
    }
    for label in candidate.get("top_level_labels", ()):
        if label.strip().casefold() in forbidden:
            findings.append(
                IncidentFinding(
                    "fragmentary_top_level_label",
                    f"forbidden top-level label: {label}",
                )
            )
    role_hypotheses = candidate.get("role_hypotheses", {})
    for page, roles in oracle["required_role_hypotheses"].items():
        observed = set(role_hypotheses.get(page, ()))
        missing = set(roles) - observed
        if missing:
            findings.append(
                IncidentFinding(
                    "missing_role_hypothesis",
                    f"page {page} is missing roles: {sorted(missing)}",
                )
            )
    continuities = {
        (
            item["from_page"],
            item["relation"],
            item["to_page"],
        )
        for item in candidate.get("continuity_hypotheses", ())
    }
    for expected in oracle["required_continuity_hypotheses"]:
        key = (
            expected["from_page"],
            expected["relation"],
            expected["to_page"],
        )
        if key not in continuities:
            findings.append(
                IncidentFinding(
                    "missing_continuity_hypothesis",
                    f"continuity hypothesis not retained: {key}",
                )
            )
    review_pages = {
        item["page"]
        for item in candidate.get("review_hypotheses", ())
        if item.get("relation") == "review_of" and item.get("target_ref")
    }
    for page in oracle["required_review_hypothesis_pages"]:
        if page not in review_pages:
            findings.append(
                IncidentFinding(
                    "missing_review_hypothesis",
                    f"page {page} is missing review_of provenance",
                )
            )
    reaction_by_page = {
        item["page"]: set(item.get("preserved_fields", ()))
        for item in candidate.get("reaction_regions", ())
    }
    required_reaction_fields = set(oracle["required_reaction_fields"])
    for page in oracle["reaction_pages"]:
        missing = required_reaction_fields - reaction_by_page.get(page, set())
        if missing:
            findings.append(
                IncidentFinding(
                    "reaction_provenance_incomplete",
                    f"page {page} reaction is missing: {sorted(missing)}",
                )
            )
    for claim in candidate.get("claims", ()):
        if claim.get("page") not in oracle["instruction_pages"]:
            continue
        source_text = claim.get("source_text", "")
        if any(
            fragment in source_text
            for fragment in oracle["instruction_fragments"]
        ) and (
            claim.get("claim_type") != "instruction"
            or claim.get("publication_status") == "core"
        ):
            findings.append(
                IncidentFinding(
                    "instruction_promoted_to_fact",
                    f"instruction was promoted on page {claim.get('page')}",
                )
            )
    if not candidate.get("table_rows_preserve_header_context", False):
        findings.append(
            IncidentFinding(
                "table_header_context_lost",
                "table rows were detached from their headers",
            )
        )
    if not candidate.get("catalyst_ee_claim_retained", False):
        findings.append(
            IncidentFinding(
                "catalyst_ee_claim_missing",
                "catalyst and ee data were not retained in the claim ledger",
            )
        )
    if candidate.get("vetoed_parent_reintroduced", False):
        findings.append(
            IncidentFinding(
                "veto_reintroduced",
                "a vetoed parent relation was reintroduced",
            )
        )
    if candidate.get("parentless_claim_disposition") != "unresolved":
        findings.append(
            IncidentFinding(
                "parentless_claim_forced",
                "parentless claim must remain unresolved",
            )
        )
    return tuple(findings)
