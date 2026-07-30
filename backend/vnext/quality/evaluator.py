from __future__ import annotations

import hashlib
import math
from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from itertools import combinations

from backend.vnext.artifacts.canonical import payload_digest
from backend.vnext.contracts.common import StringValue
from backend.vnext.contracts.quality import (
    DocumentEvaluationResult,
    MetricObservation,
    PilotDataset,
    PilotEvaluationPolicy,
    PilotEvaluationReport,
    PilotGateDecision,
    PilotMetric,
    PilotMetricResult,
    PilotMetricThreshold,
    PilotSplit,
    RiskCoveragePoint,
    SliceEvaluationResult,
    SourceGroupLeakage,
    SplitRequirement,
    StabilityRunObservation,
)


def default_redesign_pilot_policy() -> PilotEvaluationPolicy:
    """Return the July 29 redesign gates without inventing unset thresholds."""

    minimums: dict[PilotMetric, float | None] = {
        PilotMetric.CLAIM_PRECISION: 0.92,
        PilotMetric.EVIDENCE_ALIGNMENT: 0.95,
        PilotMetric.MUST_HAVE_RECALL: 0.95,
        PilotMetric.REGION_ACCOUNTING: 1.0,
        PilotMetric.REPLAN_SERIOUS_ERROR_RECALL: 0.95,
        PilotMetric.AUTHORITY_COMPLIANCE: 1.0,
        PilotMetric.DIRECT_PARENT_PRECISION: 0.90,
        PilotMetric.DIRECT_PARENT_RECALL: 0.85,
        PilotMetric.ANCESTOR_F1: 0.93,
        PilotMetric.SOURCE_ORDER_SCORE: 0.80,
        PilotMetric.BRANCH_PURITY: 0.85,
        PilotMetric.BRANCH_THEME_CLEAN_RATE: 0.95,
        PilotMetric.SIBLING_GRANULARITY_CONSISTENCY: 0.90,
        PilotMetric.FRAGMENT_ROOT_FREE_RATE: 1.0,
        PilotMetric.PUBLISHED_CLAIM_COVERAGE: None,
        PilotMetric.HIGH_VALUE_RESOLUTION_RATE: 1.0,
    }
    per_document = {
        PilotMetric.MUST_HAVE_RECALL,
        PilotMetric.REGION_ACCOUNTING,
        PilotMetric.AUTHORITY_COMPLIANCE,
        PilotMetric.FRAGMENT_ROOT_FREE_RATE,
        PilotMetric.HIGH_VALUE_RESOLUTION_RATE,
    }
    thresholds = tuple(
        sorted(
            (
                PilotMetricThreshold(
                    metric=metric,
                    minimum=minimum,
                    per_document_hard_gate=metric in per_document,
                    per_slice_hard_gate=True,
                )
                for metric, minimum in minimums.items()
            ),
            key=lambda item: str(item.metric),
        )
    )
    split_requirements = tuple(
        sorted(
            (
                SplitRequirement(
                    split=PilotSplit.DEVELOPMENT,
                    minimum_documents=12,
                ),
                SplitRequirement(
                    split=PilotSplit.CALIBRATION,
                    minimum_documents=18,
                ),
                SplitRequirement(
                    split=PilotSplit.SEALED_BLIND,
                    minimum_documents=30,
                ),
            ),
            key=lambda item: str(item.split),
        )
    )
    return PilotEvaluationPolicy(
        policy_version="redesign-2026-07-29-pilot-v1",
        minimum_document_count=60,
        split_requirements=split_requirements,
        metric_thresholds=thresholds,
        minimum_stability_runs=5,
        minimum_node_jaccard=None,
        minimum_edge_jaccard=None,
        minimum_slice_documents=2,
        worst_document_fraction=0.1,
        risk_coverage_targets=(0.25, 0.5, 0.75, 1.0),
    )


def evaluate_pilot(
    dataset: PilotDataset,
    *,
    evaluated_at: datetime | None = None,
) -> PilotEvaluationReport:
    if evaluated_at is None:
        evaluated_at = datetime.now(UTC)
    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        raise ValueError("evaluated_at must include a timezone")

    policy = dataset.policy
    thresholds = {
        item.metric: item for item in policy.metric_thresholds
    }
    blockers: set[str] = set()
    incomplete: set[str] = set()

    split_counts_map = {
        split: sum(
            document.split is split for document in dataset.documents
        )
        for split in PilotSplit
    }
    if len(dataset.documents) < policy.minimum_document_count:
        incomplete.add(
            "document_count_below_policy_minimum:"
            f"{len(dataset.documents)}/{policy.minimum_document_count}"
        )
    for requirement in policy.split_requirements:
        observed = split_counts_map[requirement.split]
        if observed < requirement.minimum_documents:
            incomplete.add(
                f"split_count_below_minimum:{requirement.split.value}:"
                f"{observed}/{requirement.minimum_documents}"
            )
    for threshold in policy.metric_thresholds:
        if threshold.minimum is None:
            incomplete.add(
                f"threshold_unfrozen:{threshold.metric.value}"
            )
    if policy.minimum_node_jaccard is None:
        incomplete.add("threshold_unfrozen:minimum_node_jaccard")
    if policy.minimum_edge_jaccard is None:
        incomplete.add("threshold_unfrozen:minimum_edge_jaccard")

    leakage = _source_group_leakage(dataset)
    for finding in leakage:
        blockers.add(
            f"source_group_split_leakage:{finding.source_group_id}"
        )

    document_results: list[DocumentEvaluationResult] = []
    document_rank: dict[str, float] = {}
    for document in dataset.documents:
        result, rank, document_blockers, document_incomplete = (
            _evaluate_document(
                document,
                policy=policy,
                thresholds=thresholds,
            )
        )
        document_results.append(result)
        document_rank[document.document_id] = rank
        blockers.update(document_blockers)
        incomplete.update(document_incomplete)

    overall_metrics, missing_overall = _aggregate_metrics(
        dataset.documents,
        thresholds=thresholds,
    )
    incomplete.update(
        f"overall_metric_missing:{metric.value}"
        for metric in missing_overall
    )
    for metric in overall_metrics:
        if metric.passed is False:
            blockers.add(f"overall_metric_failed:{metric.metric.value}")

    slice_results = _evaluate_slices(
        dataset,
        policy=policy,
        thresholds=thresholds,
        document_rank=document_rank,
    )
    for result in slice_results:
        if result.gate_decision is PilotGateDecision.BLOCK:
            blockers.add(f"slice_failed:{result.slice_key}")
        elif result.gate_decision is PilotGateDecision.INCOMPLETE:
            incomplete.add(f"slice_incomplete:{result.slice_key}")

    risk_coverage, risk_missing = _risk_coverage(dataset, policy)
    incomplete.update(risk_missing)

    worst_count = max(
        1,
        math.ceil(
            len(dataset.documents) * policy.worst_document_fraction
        ),
    )
    worst_document_ids = tuple(
        document_id
        for document_id, _ in sorted(
            document_rank.items(),
            key=lambda item: (item[1], item[0]),
        )[:worst_count]
    )
    worst_slice_keys = tuple(
        result.slice_key
        for result in sorted(
            slice_results,
            key=lambda item: (
                _decision_rank(item.gate_decision),
                _minimum_metric_margin(item.metrics),
                item.slice_key,
            ),
        )[: min(10, len(slice_results))]
    )

    if blockers:
        gate_decision = PilotGateDecision.BLOCK
    elif incomplete:
        gate_decision = PilotGateDecision.INCOMPLETE
    else:
        gate_decision = PilotGateDecision.PASS

    dataset_digest = payload_digest(dataset)
    policy_digest = payload_digest(policy)
    report_digest = hashlib.sha256(
        (
            "zlb-vnext-pilot-report-v1\0"
            + dataset_digest
            + "\0"
            + policy_digest
        ).encode("utf-8")
    ).hexdigest()
    split_counts = tuple(
        StringValue(
            key=split.value,
            value=str(split_counts_map[split]),
        )
        for split in sorted(PilotSplit, key=str)
    )
    return PilotEvaluationReport(
        report_id="pilot_report_" + report_digest[:32],
        dataset_id=dataset.dataset_id,
        dataset_digest=dataset_digest,
        policy_digest=policy_digest,
        evaluated_at=evaluated_at,
        document_count=len(dataset.documents),
        split_counts=split_counts,
        overall_metrics=overall_metrics,
        documents=tuple(document_results),
        slices=slice_results,
        worst_document_ids=worst_document_ids,
        worst_slice_keys=worst_slice_keys,
        risk_coverage=risk_coverage,
        source_group_leakage=leakage,
        gate_decision=gate_decision,
        blockers=tuple(sorted(blockers)),
        incomplete_reasons=tuple(sorted(incomplete)),
    )


def _evaluate_document(
    document,
    *,
    policy: PilotEvaluationPolicy,
    thresholds: dict[PilotMetric, PilotMetricThreshold],
) -> tuple[
    DocumentEvaluationResult,
    float,
    set[str],
    set[str],
]:
    blockers: set[str] = set()
    incomplete: set[str] = set()
    observations = {item.metric: item for item in document.metrics}
    metrics = tuple(
        _metric_result(observation, thresholds.get(metric))
        for metric, observation in sorted(
            observations.items(),
            key=lambda item: str(item[0]),
        )
    )
    for metric, threshold in thresholds.items():
        if metric not in observations:
            incomplete.add(
                f"document_metric_missing:{document.document_id}:"
                f"{metric.value}"
            )
            continue
        result = next(item for item in metrics if item.metric is metric)
        if (
            threshold.per_document_hard_gate
            and result.passed is False
        ):
            blockers.add(
                f"document_metric_failed:{document.document_id}:"
                f"{metric.value}"
            )
        if (
            threshold.per_document_hard_gate
            and threshold.minimum is None
        ):
            incomplete.add(
                f"document_threshold_unfrozen:{document.document_id}:"
                f"{metric.value}"
            )
    for code in document.serious_error_codes:
        blockers.add(
            f"serious_error:{document.document_id}:{code}"
        )

    (
        stability_decision,
        minimum_node,
        mean_node,
        minimum_edge,
        mean_edge,
        stability_findings,
    ) = _evaluate_stability(document.stability_runs, policy)
    for finding in stability_findings:
        if stability_decision is PilotGateDecision.BLOCK:
            blockers.add(
                f"stability_failed:{document.document_id}:{finding}"
            )
        else:
            incomplete.add(
                f"stability_incomplete:{document.document_id}:{finding}"
            )

    if blockers:
        decision = PilotGateDecision.BLOCK
    elif incomplete:
        decision = PilotGateDecision.INCOMPLETE
    else:
        decision = PilotGateDecision.PASS
    findings = tuple(
        sorted(
            {
                *document.serious_error_codes,
                *stability_findings,
                *(
                    item.split(":", 2)[-1]
                    for item in blockers | incomplete
                    if document.document_id in item
                ),
            }
        )
    )
    rank = _minimum_metric_margin(metrics)
    if decision is PilotGateDecision.BLOCK:
        rank -= 2
    elif decision is PilotGateDecision.INCOMPLETE:
        rank -= 1
    return (
        DocumentEvaluationResult(
            document_id=document.document_id,
            source_group_id=document.source_group_id,
            split=document.split,
            metrics=metrics,
            stability_decision=stability_decision,
            minimum_node_jaccard=minimum_node,
            mean_node_jaccard=mean_node,
            minimum_edge_jaccard=minimum_edge,
            mean_edge_jaccard=mean_edge,
            gate_decision=decision,
            findings=findings,
        ),
        rank,
        blockers,
        incomplete,
    )


def _aggregate_metrics(
    documents: Sequence,
    *,
    thresholds: dict[PilotMetric, PilotMetricThreshold],
) -> tuple[tuple[PilotMetricResult, ...], tuple[PilotMetric, ...]]:
    totals: dict[PilotMetric, list[float]] = defaultdict(
        lambda: [0.0, 0.0]
    )
    presence: dict[PilotMetric, int] = defaultdict(int)
    for document in documents:
        for observation in document.metrics:
            totals[observation.metric][0] += observation.success_weight
            totals[observation.metric][1] += observation.total_weight
            presence[observation.metric] += 1
    results = tuple(
        _metric_result(
            MetricObservation(
                metric=metric,
                success_weight=values[0],
                total_weight=values[1],
            ),
            thresholds.get(metric),
        )
        for metric, values in sorted(
            totals.items(),
            key=lambda item: str(item[0]),
        )
    )
    missing = tuple(
        metric
        for metric in sorted(thresholds, key=str)
        if presence[metric] != len(documents)
    )
    return results, missing


def _metric_result(
    observation: MetricObservation,
    threshold: PilotMetricThreshold | None,
) -> PilotMetricResult:
    value = observation.success_weight / observation.total_weight
    minimum = threshold.minimum if threshold else None
    return PilotMetricResult(
        metric=observation.metric,
        success_weight=observation.success_weight,
        total_weight=observation.total_weight,
        value=value,
        threshold=minimum,
        passed=None if minimum is None else value >= minimum,
    )


def _evaluate_slices(
    dataset: PilotDataset,
    *,
    policy: PilotEvaluationPolicy,
    thresholds: dict[PilotMetric, PilotMetricThreshold],
    document_rank: dict[str, float],
) -> tuple[SliceEvaluationResult, ...]:
    grouped: dict[str, list] = defaultdict(list)
    for document in dataset.documents:
        grouped[f"split:{document.split.value}"].append(document)
        for stratum in document.strata:
            grouped[f"{stratum.key}:{stratum.value}"].append(document)
    results: list[SliceEvaluationResult] = []
    for slice_key, documents in sorted(grouped.items()):
        metrics, missing = _aggregate_metrics(
            documents,
            thresholds=thresholds,
        )
        findings: set[str] = set()
        blocked = False
        incomplete = False
        if len(documents) < policy.minimum_slice_documents:
            incomplete = True
            findings.add(
                "slice_document_count_below_minimum:"
                f"{len(documents)}/{policy.minimum_slice_documents}"
            )
        for metric in missing:
            incomplete = True
            findings.add(f"metric_missing:{metric.value}")
        for metric in metrics:
            threshold = thresholds.get(metric.metric)
            if threshold is None:
                continue
            if threshold.minimum is None:
                incomplete = True
                findings.add(
                    f"threshold_unfrozen:{metric.metric.value}"
                )
            elif (
                threshold.per_slice_hard_gate
                and metric.passed is False
            ):
                blocked = True
                findings.add(f"metric_failed:{metric.metric.value}")
        if blocked:
            decision = PilotGateDecision.BLOCK
        elif incomplete:
            decision = PilotGateDecision.INCOMPLETE
        else:
            decision = PilotGateDecision.PASS
        worst_ids = tuple(
            document.document_id
            for document in sorted(
                documents,
                key=lambda item: (
                    document_rank[item.document_id],
                    item.document_id,
                ),
            )[: min(3, len(documents))]
        )
        results.append(
            SliceEvaluationResult(
                slice_key=slice_key,
                document_count=len(documents),
                metrics=metrics,
                gate_decision=decision,
                worst_document_ids=worst_ids,
                findings=tuple(sorted(findings)),
            )
        )
    return tuple(results)


def _risk_coverage(
    dataset: PilotDataset,
    policy: PilotEvaluationPolicy,
) -> tuple[tuple[RiskCoveragePoint, ...], set[str]]:
    missing = {
        f"risk_items_missing:{document.document_id}"
        for document in dataset.documents
        if not document.risk_items
    }
    items = sorted(
        (
            (
                item.predicted_risk,
                document.document_id,
                item.item_id,
                item.is_error,
                item.importance_weight,
            )
            for document in dataset.documents
            for item in document.risk_items
        ),
        key=lambda item: (item[0], item[1], item[2]),
    )
    if not items:
        return (), missing | {"risk_coverage_unavailable"}
    total_weight = sum(item[4] for item in items)
    points: list[RiskCoveragePoint] = []
    for target in policy.risk_coverage_targets:
        target_weight = total_weight * target
        retained_weight = 0.0
        error_weight = 0.0
        retained_count = 0
        maximum_risk = 0.0
        for risk, _, _, is_error, weight in items:
            retained_weight += weight
            error_weight += weight if is_error else 0.0
            retained_count += 1
            maximum_risk = risk
            if retained_weight >= target_weight:
                break
        points.append(
            RiskCoveragePoint(
                target_coverage=target,
                realized_coverage=min(
                    retained_weight / total_weight,
                    1.0,
                ),
                selective_risk=error_weight / retained_weight,
                retained_weight=retained_weight,
                retained_item_count=retained_count,
                maximum_included_risk=maximum_risk,
            )
        )
    return tuple(points), missing


def _evaluate_stability(
    runs: Sequence[StabilityRunObservation],
    policy: PilotEvaluationPolicy,
) -> tuple[
    PilotGateDecision,
    float | None,
    float | None,
    float | None,
    float | None,
    tuple[str, ...],
]:
    if len(runs) < policy.minimum_stability_runs:
        return (
            PilotGateDecision.INCOMPLETE,
            None,
            None,
            None,
            None,
            (
                "run_count_below_minimum:"
                f"{len(runs)}/{policy.minimum_stability_runs}",
            ),
        )
    node_scores = tuple(
        _jaccard(left.concept_keys, right.concept_keys)
        for left, right in combinations(runs, 2)
    )
    edge_scores = tuple(
        _jaccard(left.direct_parent_keys, right.direct_parent_keys)
        for left, right in combinations(runs, 2)
    )
    minimum_node = min(node_scores)
    mean_node = sum(node_scores) / len(node_scores)
    minimum_edge = min(edge_scores)
    mean_edge = sum(edge_scores) / len(edge_scores)
    findings: list[str] = []
    incomplete = False
    blocked = False
    if policy.minimum_node_jaccard is None:
        incomplete = True
        findings.append("node_jaccard_threshold_unfrozen")
    elif minimum_node < policy.minimum_node_jaccard:
        blocked = True
        findings.append("node_jaccard_below_threshold")
    if policy.minimum_edge_jaccard is None:
        incomplete = True
        findings.append("edge_jaccard_threshold_unfrozen")
    elif minimum_edge < policy.minimum_edge_jaccard:
        blocked = True
        findings.append("edge_jaccard_below_threshold")
    if blocked:
        decision = PilotGateDecision.BLOCK
    elif incomplete:
        decision = PilotGateDecision.INCOMPLETE
    else:
        decision = PilotGateDecision.PASS
    return (
        decision,
        minimum_node,
        mean_node,
        minimum_edge,
        mean_edge,
        tuple(findings),
    )


def _source_group_leakage(
    dataset: PilotDataset,
) -> tuple[SourceGroupLeakage, ...]:
    splits: dict[str, set[PilotSplit]] = defaultdict(set)
    documents: dict[str, list[str]] = defaultdict(list)
    for document in dataset.documents:
        splits[document.source_group_id].add(document.split)
        documents[document.source_group_id].append(document.document_id)
    return tuple(
        SourceGroupLeakage(
            source_group_id=source_group,
            splits=tuple(sorted(group_splits, key=str)),
            document_ids=tuple(sorted(documents[source_group])),
        )
        for source_group, group_splits in sorted(splits.items())
        if len(group_splits) > 1
    )


def _jaccard(left: Iterable[str], right: Iterable[str]) -> float:
    left_set = set(left)
    right_set = set(right)
    union = left_set | right_set
    if not union:
        return 1.0
    return len(left_set & right_set) / len(union)


def _minimum_metric_margin(
    metrics: Sequence[PilotMetricResult],
) -> float:
    margins = [
        item.value - item.threshold
        for item in metrics
        if item.threshold is not None
    ]
    return min(margins) if margins else -1.0


def _decision_rank(decision: PilotGateDecision) -> int:
    return {
        PilotGateDecision.BLOCK: 0,
        PilotGateDecision.INCOMPLETE: 1,
        PilotGateDecision.PASS: 2,
    }[decision]
