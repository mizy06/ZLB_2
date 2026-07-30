from __future__ import annotations

import json
import re
import statistics
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import urlsplit


QUALITY_ORACLE_SCHEMA_VERSION = "pdf-page-quality-oracle-v1"
QWEN_PRODUCTION_PROFILE_STANDARD = "standard"
QWEN_PRODUCTION_PROFILE_APPROVED_CN_TOKEN_PLAN_PREVIEW = (
    "approved_cn_token_plan_preview"
)
APPROVED_CN_TOKEN_PLAN_PREVIEW_BASE_URL = (
    "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
)
APPROVED_CN_TOKEN_PLAN_PREVIEW_MODEL = "qwen3.8-max-preview"
_RUNTIME_VERSION_KEYS = {
    "python",
    "pypdf",
    "pdfplumber",
    "pdfminer.six",
    "pylatexenc",
    "poppler",
}

_SUPERSCRIPT_TRANSLATION = str.maketrans(
    "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼",
    "0123456789+-=",
)
_SUBSCRIPT_TRANSLATION = str.maketrans(
    "₀₁₂₃₄₅₆₇₈₉₊₋₌",
    "0123456789+-=",
)
_SUPERSCRIPT_SEQUENCE = re.compile(r"[⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼]+")
_SUBSCRIPT_SEQUENCE = re.compile(r"[₀₁₂₃₄₅₆₇₈₉₊₋₌]+")
_DERIVATIVE_OPERATOR = re.compile(
    r"(?P<operator>d|∂)\s*/\s*(?P=operator)\s*"
    r"(?P<variable>[A-Za-zΑ-ω]+)\s*"
    r"(?P<function>[A-Za-zΑ-ω]+(?:_[A-Za-z0-9]+)?)"
    r"\s*\(\s*(?P=variable)\s*\)"
)
_RELATION_OPERATOR = re.compile(r"[=≈≤≥<>≠→⇒]")


class QualityOracleError(ValueError):
    """Raised when a page-quality oracle cannot be used safely."""


def qwen_manifest_profile_issues(
    manifest: dict[str, Any],
) -> list[str]:
    profile = manifest.get("qwen_production_profile")
    if profile == QWEN_PRODUCTION_PROFILE_STANDARD:
        return []
    if (
        profile
        != QWEN_PRODUCTION_PROFILE_APPROVED_CN_TOKEN_PLAN_PREVIEW
    ):
        return ["manifest_qwen_production_profile_mismatch"]

    issues: list[str] = []
    if (
        manifest.get("provider_endpoint")
        != APPROVED_CN_TOKEN_PLAN_PREVIEW_BASE_URL
    ):
        issues.append("manifest_approved_profile_endpoint_mismatch")
    if (
        manifest.get("text_model")
        != APPROVED_CN_TOKEN_PLAN_PREVIEW_MODEL
    ):
        issues.append("manifest_approved_profile_text_model_mismatch")
    if (
        manifest.get("vision_model")
        != APPROVED_CN_TOKEN_PLAN_PREVIEW_MODEL
    ):
        issues.append("manifest_approved_profile_vision_model_mismatch")
    return issues


def canonicalize(value: str) -> str:
    value = _DERIVATIVE_OPERATOR.sub(
        lambda match: (
            f"{match.group('operator')}{match.group('function')}"
            f"({match.group('variable')})/"
            f"{match.group('operator')}{match.group('variable')}"
        ),
        value,
    )
    normalized = _SUPERSCRIPT_SEQUENCE.sub(
        lambda match: "^" + match.group(0).translate(
            _SUPERSCRIPT_TRANSLATION
        ),
        value,
    )
    normalized = _SUBSCRIPT_SEQUENCE.sub(
        lambda match: "_" + match.group(0).translate(
            _SUBSCRIPT_TRANSLATION
        ),
        normalized,
    )
    normalized = unicodedata.normalize("NFKC", normalized)
    normalized = re.sub(
        r"\bsqrt\s*\(",
        "√(",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = (
        normalized.replace("−", "-")
        .replace("–", "-")
        .replace("—", "-")
        .replace("′", "'")
        .replace("’", "'")
        .replace("、", ",")
        .replace("≅", "≈")
        .replace("≃", "≈")
        .replace("∼", "~")
        .replace("×", "*")
        .replace("·", "")
        .replace(r"\times", "*")
        .replace(r"\approx", "≈")
        .replace(r"\cong", "≈")
        .replace(r"\hbar", "ℏ")
        .replace(r"\nu", "ν")
        .replace(r"\lambda", "λ")
        .replace(r"\Delta", "Δ")
        .replace(r"\partial", "∂")
        .replace(r"\pm", "±")
    )
    normalized = re.sub(r"\\(?:mathrm|text)\{([^{}]*)\}", r"\1", normalized)
    normalized = re.sub(
        r"\\(?:frac|dfrac)\{([^{}]*)\}\{([^{}]*)\}",
        r"\1/\2",
        normalized,
    )
    normalized = re.sub(r"\\sqrt\{([^{}]*)\}", r"√\1", normalized)
    normalized = re.sub(r"\\[a-zA-Z]+", "", normalized)
    return "".join(
        character
        for character in normalized
        if not character.isspace()
        and character not in "()[]{}_,.;:，。；："
    ).casefold()


def audit_formulas(
    observed: Sequence[str],
    expected: Sequence[str],
) -> dict[str, Any]:
    observed_keys = [
        (canonicalize(item), item)
        for item in observed
        if isinstance(item, str) and item
    ]
    rows: list[dict[str, Any]] = []
    for formula in expected:
        expected_key = canonicalize(formula)
        best_score = 0.0
        best_observed = ""
        exact = False
        for observed_key, original in observed_keys:
            contains = bool(expected_key) and expected_key in observed_key
            score = SequenceMatcher(
                None,
                expected_key,
                observed_key,
            ).ratio()
            if contains:
                score = 1.0
            if score > best_score:
                best_score = score
                best_observed = original
                exact = contains
        clauses = [
            clause.strip()
            for clause in re.split(r"[,，]", formula)
            if clause.strip()
        ]
        if (
            not exact
            and len(clauses) > 1
            and all(_RELATION_OPERATOR.search(clause) for clause in clauses)
        ):
            matched: list[str] = []
            for clause in clauses:
                clause_key = canonicalize(clause)
                original = next(
                    (
                        observed_original
                        for observed_key, observed_original in observed_keys
                        if clause_key and clause_key in observed_key
                    ),
                    "",
                )
                if not original:
                    break
                matched.append(original)
            if len(matched) == len(clauses):
                best_score = 1.0
                best_observed = " | ".join(dict.fromkeys(matched))
                exact = True
        rows.append(
            {
                "expected": formula,
                "exact": exact,
                "character_accuracy": round(best_score, 4),
                "best_observed": best_observed,
            }
        )
    exact_count = sum(1 for row in rows if row["exact"])
    return {
        "expected_count": len(rows),
        "exact_count": exact_count,
        "exact_rate": (
            round(exact_count / len(rows), 4) if rows else 1.0
        ),
        "mean_character_accuracy": (
            round(
                statistics.fmean(
                    row["character_accuracy"] for row in rows
                ),
                4,
            )
            if rows
            else 1.0
        ),
        "details": rows,
    }


def audit_required_text(
    evidence: Sequence[str],
    required: Sequence[str],
) -> dict[str, Any]:
    corpus = canonicalize("\n".join(evidence))
    rows = [
        {
            "required": item,
            "covered": canonicalize(item) in corpus,
        }
        for item in required
    ]
    covered_count = sum(1 for row in rows if row["covered"])
    return {
        "required_count": len(rows),
        "covered_count": covered_count,
        "rate": (
            round(covered_count / len(rows), 4) if rows else 1.0
        ),
        "details": rows,
    }


def _string_list(value: Any, *, field: str) -> list[str]:
    if value is None:
        return []
    if (
        not isinstance(value, list)
        or any(not isinstance(item, str) or not item.strip() for item in value)
    ):
        raise QualityOracleError(
            f"{field} must be a list of non-empty strings"
        )
    if len(value) != len(set(value)):
        raise QualityOracleError(f"{field} contains duplicate assertions")
    return list(value)


def validate_quality_oracle(
    payload: Any,
    *,
    source_sha256: str,
    selected_pages: Sequence[int],
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise QualityOracleError("quality oracle must be a JSON object")
    if payload.get("schema_version") != QUALITY_ORACLE_SCHEMA_VERSION:
        raise QualityOracleError(
            "quality oracle schema_version is unsupported"
        )
    if payload.get("source_sha256") != source_sha256:
        raise QualityOracleError(
            "quality oracle source_sha256 does not match the canary report"
        )
    expected_pages = list(selected_pages)
    if payload.get("selected_pages") != expected_pages:
        raise QualityOracleError(
            "quality oracle selected_pages must exactly match the canary report"
        )
    pages = payload.get("pages")
    if not isinstance(pages, dict):
        raise QualityOracleError("quality oracle pages must be an object")
    expected_keys = {str(page) for page in expected_pages}
    if set(pages) != expected_keys:
        raise QualityOracleError(
            "quality oracle pages must contain exactly the selected_pages"
        )

    normalized_pages: dict[str, dict[str, Any]] = {}
    for page in expected_pages:
        key = str(page)
        assertions = pages[key]
        if not isinstance(assertions, dict):
            raise QualityOracleError(f"pages.{key} must be an object")
        formulas = _string_list(
            assertions.get("canonical_formulas"),
            field=f"pages.{key}.canonical_formulas",
        )
        required = _string_list(
            assertions.get("required_text"),
            field=f"pages.{key}.required_text",
        )
        has_knowledge_present = "expected_has_knowledge" in assertions
        has_knowledge = assertions.get("expected_has_knowledge")
        if has_knowledge_present and not isinstance(has_knowledge, bool):
            raise QualityOracleError(
                f"pages.{key}.expected_has_knowledge must be boolean"
            )
        if not formulas and not required and not has_knowledge_present:
            raise QualityOracleError(
                f"pages.{key} must contain at least one assertion"
            )
        normalized_pages[key] = {
            "canonical_formulas": formulas,
            "required_text": required,
        }
        if has_knowledge_present:
            normalized_pages[key]["expected_has_knowledge"] = has_knowledge

    return {
        "schema_version": QUALITY_ORACLE_SCHEMA_VERSION,
        "source_sha256": source_sha256,
        "selected_pages": expected_pages,
        "pages": normalized_pages,
    }


def load_quality_oracle(
    path: Path,
    *,
    source_sha256: str,
    selected_pages: Sequence[int],
) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise QualityOracleError(
            f"quality oracle is missing: {path}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise QualityOracleError(
            f"quality oracle is not valid JSON: {exc.msg}"
        ) from exc
    return validate_quality_oracle(
        payload,
        source_sha256=source_sha256,
        selected_pages=selected_pages,
    )


def _artifact_identity_issues(
    report: dict[str, Any],
    *,
    source_sha256: str,
    selected_pages: Sequence[int],
) -> list[str]:
    manifest = report.get("manifest")
    if not isinstance(manifest, dict):
        return ["manifest_missing"]

    issues: list[str] = []
    expected_values = {
        "kind": "pdf_page_knowledge_canary",
        "source_sha256": source_sha256,
        "original_pages": list(selected_pages),
        "provider": "qwen",
        "credential_source": "age",
        "extraction_profile": "direct_layout_fallback",
    }
    for field, expected in expected_values.items():
        if manifest.get(field) != expected:
            issues.append(f"manifest_{field}_mismatch")

    issues.extend(qwen_manifest_profile_issues(manifest))

    for field in ("image_digest", "git_sha", "text_model", "vision_model"):
        value = manifest.get(field)
        if (
            not isinstance(value, str)
            or not value.strip()
            or value.strip().casefold() == "unknown"
        ):
            issues.append(f"manifest_{field}_missing")

    endpoint = manifest.get("provider_endpoint")
    if not isinstance(endpoint, str):
        issues.append("manifest_provider_endpoint_invalid")
    else:
        try:
            parsed = urlsplit(endpoint)
        except ValueError:
            parsed = None
        if (
            parsed is None
            or parsed.scheme.casefold() != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            issues.append("manifest_provider_endpoint_invalid")

    prompt = manifest.get("prompt")
    if not isinstance(prompt, dict):
        issues.append("manifest_prompt_missing")
    else:
        prompt_version = prompt.get("version")
        prompt_sha = prompt.get("sha256")
        if not isinstance(prompt_version, str) or not prompt_version.strip():
            issues.append("manifest_prompt_version_missing")
        if (
            not isinstance(prompt_sha, str)
            or not re.fullmatch(r"[0-9a-f]{64}", prompt_sha)
        ):
            issues.append("manifest_prompt_sha256_invalid")

    schema_versions = manifest.get("schema_versions")
    if not isinstance(schema_versions, dict) or any(
        not isinstance(schema_versions.get(field), str)
        or not schema_versions[field].strip()
        for field in (
            "page_knowledge",
            "page_layout",
            "page_layout_nodes",
        )
    ):
        issues.append("manifest_schema_versions_incomplete")

    runner = manifest.get("runner")
    if (
        not isinstance(runner, dict)
        or runner.get("module")
        != "backend.tools.pdf_page_knowledge_canary"
        or not isinstance(runner.get("sha256"), str)
        or not re.fullmatch(r"[0-9a-f]{64}", runner["sha256"])
    ):
        issues.append("manifest_runner_identity_invalid")

    runtime_versions = manifest.get("runtime_versions")
    if not isinstance(runtime_versions, dict):
        issues.append("manifest_runtime_versions_missing")
    else:
        for field in sorted(_RUNTIME_VERSION_KEYS):
            value = runtime_versions.get(field)
            if (
                not isinstance(value, str)
                or not value.strip()
                or value.strip().casefold()
                in {"unknown", "not-installed"}
            ):
                issues.append(f"manifest_runtime_{field}_missing")

    report_manifest_fields = {
        "provider": "provider",
        "provider_endpoint": "provider_endpoint",
        "text_model": "text_model",
        "vision_model": "vision_model",
        "qwen_production_profile": "qwen_production_profile",
        "extraction_profile": "extraction_profile",
    }
    for report_field, manifest_field in report_manifest_fields.items():
        if report.get(report_field) != manifest.get(manifest_field):
            issues.append(f"report_{report_field}_mismatch")
    return list(dict.fromkeys(issues))


def evaluate_canary_report(
    report: dict[str, Any],
    oracle: dict[str, Any],
) -> dict[str, Any]:
    source_sha256 = str(report.get("source_sha256") or "")
    selected_pages = report.get("selected_original_pages")
    if not isinstance(selected_pages, list) or any(
        not isinstance(page, int) for page in selected_pages
    ):
        raise QualityOracleError(
            "canary report selected_original_pages is invalid"
        )
    oracle = validate_quality_oracle(
        oracle,
        source_sha256=source_sha256,
        selected_pages=selected_pages,
    )

    report_pages = report.get("pages")
    if not isinstance(report_pages, list):
        raise QualityOracleError("canary report pages is invalid")
    pages_by_number: dict[int, dict[str, Any]] = {}
    for page_report in report_pages:
        if not isinstance(page_report, dict):
            raise QualityOracleError("canary report page must be an object")
        page = page_report.get("original_page")
        if not isinstance(page, int) or page in pages_by_number:
            raise QualityOracleError(
                "canary report page numbers are invalid or duplicated"
            )
        pages_by_number[page] = page_report
    if set(pages_by_number) != set(selected_pages):
        raise QualityOracleError(
            "canary report pages do not match selected_original_pages"
        )

    evaluated_pages: list[dict[str, Any]] = []
    for page in selected_pages:
        page_report = pages_by_number[page]
        assertions = oracle["pages"][str(page)]
        nodes = page_report.get("nodes")
        if not isinstance(nodes, list):
            raise QualityOracleError(
                f"canary report page {page} nodes is invalid"
            )
        evidence = [
            str(node.get("evidence_text") or "")
            for node in nodes
            if isinstance(node, dict)
        ]
        formulas = [
            str(node.get("formula_text") or "")
            for node in nodes
            if isinstance(node, dict) and node.get("formula_text")
        ]
        formula_audit = audit_formulas(
            formulas,
            assertions["canonical_formulas"],
        )
        required_coverage = audit_required_text(
            evidence,
            assertions["required_text"],
        )
        expected_has_knowledge = assertions.get(
            "expected_has_knowledge"
        )
        has_knowledge_match = (
            True
            if expected_has_knowledge is None
            else page_report.get("has_knowledge")
            is expected_has_knowledge
        )
        evaluated_pages.append(
            {
                "page": page,
                "status": page_report.get("status"),
                "expected_has_knowledge": expected_has_knowledge,
                "observed_has_knowledge": page_report.get(
                    "has_knowledge"
                ),
                "has_knowledge_match": has_knowledge_match,
                "formula_audit": formula_audit,
                "required_coverage": required_coverage,
            }
        )

    expected_formula_count = sum(
        page["formula_audit"]["expected_count"]
        for page in evaluated_pages
    )
    exact_formula_count = sum(
        page["formula_audit"]["exact_count"]
        for page in evaluated_pages
    )
    required_count = sum(
        page["required_coverage"]["required_count"]
        for page in evaluated_pages
    )
    covered_count = sum(
        page["required_coverage"]["covered_count"]
        for page in evaluated_pages
    )
    knowledge_passed = all(
        page["has_knowledge_match"] for page in evaluated_pages
    )
    clean_pages = report.get("clean_accepted_original_pages")
    degraded_pages = report.get("degraded_original_pages")
    failed_pages = report.get("failed_original_pages")
    all_clean = (
        report.get("complete") is True
        and isinstance(clean_pages, list)
        and set(clean_pages) == set(selected_pages)
        and len(clean_pages) == len(selected_pages)
        and degraded_pages == []
        and failed_pages == []
        and all(
            page["status"] == "accepted"
            for page in evaluated_pages
        )
    )
    model_calls = report.get("model_calls")
    if not isinstance(model_calls, dict):
        model_calls = {}
    request_policy_count = model_calls.get("request_policy_count")
    model_policy_passed = (
        model_calls.get("request_policy_all_match") is True
        and isinstance(request_policy_count, int)
        and request_policy_count > 0
    )
    artifact_identity_issues = _artifact_identity_issues(
        report,
        source_sha256=source_sha256,
        selected_pages=selected_pages,
    )
    artifact_identity_passed = not artifact_identity_issues
    formulas_passed = exact_formula_count == expected_formula_count
    required_passed = covered_count == required_count
    passed = (
        all_clean
        and model_policy_passed
        and artifact_identity_passed
        and formulas_passed
        and required_passed
        and knowledge_passed
    )
    return {
        "passed": passed,
        "page_state": {
            "passed": all_clean,
            "all_clean": all_clean,
            "selected_page_count": len(selected_pages),
            "clean_page_count": (
                len(clean_pages) if isinstance(clean_pages, list) else 0
            ),
            "degraded_pages": degraded_pages,
            "failed_pages": failed_pages,
        },
        "model_call_policy": {
            "passed": model_policy_passed,
            "request_policy_all_match": model_calls.get(
                "request_policy_all_match"
            ),
            "request_policy_count": request_policy_count,
        },
        "artifact_identity": {
            "passed": artifact_identity_passed,
            "issues": artifact_identity_issues,
        },
        "canonical_formulas": {
            "passed": formulas_passed,
            "expected_count": expected_formula_count,
            "exact_count": exact_formula_count,
            "exact_rate": (
                round(
                    exact_formula_count / expected_formula_count,
                    4,
                )
                if expected_formula_count
                else 1.0
            ),
        },
        "required_coverage": {
            "passed": required_passed,
            "required_count": required_count,
            "covered_count": covered_count,
            "rate": (
                round(covered_count / required_count, 4)
                if required_count
                else 1.0
            ),
        },
        "has_knowledge": {
            "passed": knowledge_passed,
            "assertion_count": sum(
                page["expected_has_knowledge"] is not None
                for page in evaluated_pages
            ),
        },
        "pages": evaluated_pages,
    }
