from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import UTC, datetime
from pathlib import Path

from backend.vnext.cli import main
from backend.vnext.contracts.common import StringValue
from backend.vnext.contracts.quality import (
    MetricObservation,
    PilotDataset,
    PilotEvaluationPolicy,
    PilotGateDecision,
    PilotMetric,
    PilotMetricThreshold,
    PilotSplit,
    PilotDocumentObservation,
    RiskItemObservation,
    SplitRequirement,
    StabilityRunObservation,
)
from backend.vnext.quality import (
    default_redesign_pilot_policy,
    evaluate_pilot,
)


NOW = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)


def _policy(
    thresholds: tuple[PilotMetricThreshold, ...],
    *,
    minimum_documents: int = 1,
    split_requirements: tuple[SplitRequirement, ...] = (),
    minimum_stability_runs: int = 2,
    minimum_node_jaccard: float | None = 0.8,
    minimum_edge_jaccard: float | None = 0.8,
    minimum_slice_documents: int = 1,
    risk_targets: tuple[float, ...] = (0.5, 1.0),
) -> PilotEvaluationPolicy:
    return PilotEvaluationPolicy(
        policy_version="test-policy-v1",
        minimum_document_count=minimum_documents,
        split_requirements=tuple(
            sorted(split_requirements, key=lambda item: str(item.split))
        ),
        metric_thresholds=tuple(
            sorted(thresholds, key=lambda item: str(item.metric))
        ),
        minimum_stability_runs=minimum_stability_runs,
        minimum_node_jaccard=minimum_node_jaccard,
        minimum_edge_jaccard=minimum_edge_jaccard,
        minimum_slice_documents=minimum_slice_documents,
        worst_document_fraction=0.5,
        risk_coverage_targets=risk_targets,
    )


def _metric(
    name: PilotMetric,
    success: float,
    total: float = 1,
) -> MetricObservation:
    return MetricObservation(
        metric=name,
        success_weight=success,
        total_weight=total,
    )


def _runs(
    edge_sets: tuple[tuple[str, ...], ...],
    *,
    concept_sets: tuple[tuple[str, ...], ...] | None = None,
) -> tuple[StabilityRunObservation, ...]:
    if concept_sets is None:
        concept_sets = tuple(("a", "b", "root") for _ in edge_sets)
    return tuple(
        StabilityRunObservation(
            run_key=f"run-{index:02d}",
            concept_keys=tuple(sorted(concepts)),
            direct_parent_keys=tuple(sorted(edges)),
        )
        for index, (concepts, edges) in enumerate(
            zip(concept_sets, edge_sets, strict=True),
            start=1,
        )
    )


def _document(
    document_id: str,
    *,
    source_group: str,
    split: PilotSplit = PilotSplit.DEVELOPMENT,
    metrics: tuple[MetricObservation, ...],
    strata: tuple[StringValue, ...] = (),
    risk_items: tuple[RiskItemObservation, ...] | None = None,
    runs: tuple[StabilityRunObservation, ...] | None = None,
    serious_errors: tuple[str, ...] = (),
) -> PilotDocumentObservation:
    if risk_items is None:
        risk_items = (
            RiskItemObservation(
                item_id=f"{document_id}-item",
                predicted_risk=0.1,
                is_error=False,
            ),
        )
    if runs is None:
        runs = _runs((("root>a", "root>b"),) * 2)
    return PilotDocumentObservation(
        document_id=document_id,
        source_group_id=source_group,
        split=split,
        strata=tuple(sorted(strata, key=lambda item: (item.key, item.value))),
        metrics=tuple(sorted(metrics, key=lambda item: str(item.metric))),
        risk_items=tuple(
            sorted(risk_items, key=lambda item: item.item_id)
        ),
        stability_runs=tuple(
            sorted(runs, key=lambda item: item.run_key)
        ),
        serious_error_codes=tuple(sorted(serious_errors)),
    )


def _dataset(
    policy: PilotEvaluationPolicy,
    documents: tuple[PilotDocumentObservation, ...],
) -> PilotDataset:
    return PilotDataset(
        dataset_id="pilot_unit-test",
        frozen_at=NOW,
        policy=policy,
        documents=tuple(
            sorted(documents, key=lambda item: item.document_id)
        ),
    )


class VNextPilotQualityTests(unittest.TestCase):
    def test_complete_small_fixture_can_pass_explicit_test_policy(self):
        policy = _policy(
            (
                PilotMetricThreshold(
                    metric=PilotMetric.CLAIM_PRECISION,
                    minimum=0.9,
                    per_document_hard_gate=True,
                    per_slice_hard_gate=True,
                ),
                PilotMetricThreshold(
                    metric=PilotMetric.MUST_HAVE_RECALL,
                    minimum=0.9,
                    per_document_hard_gate=True,
                    per_slice_hard_gate=True,
                ),
            ),
            minimum_documents=2,
            split_requirements=(
                SplitRequirement(
                    split=PilotSplit.DEVELOPMENT,
                    minimum_documents=2,
                ),
            ),
        )
        documents = (
            _document(
                "doc-a",
                source_group="group-a",
                metrics=(
                    _metric(PilotMetric.CLAIM_PRECISION, 9, 10),
                    _metric(PilotMetric.MUST_HAVE_RECALL, 10, 10),
                ),
            ),
            _document(
                "doc-b",
                source_group="group-b",
                metrics=(
                    _metric(PilotMetric.CLAIM_PRECISION, 10, 10),
                    _metric(PilotMetric.MUST_HAVE_RECALL, 9, 10),
                ),
            ),
        )

        report = evaluate_pilot(
            _dataset(policy, documents),
            evaluated_at=NOW,
        )

        self.assertEqual(report.gate_decision, PilotGateDecision.PASS)
        self.assertEqual(report.blockers, ())
        self.assertEqual(report.incomplete_reasons, ())
        self.assertEqual(report.document_count, 2)
        self.assertEqual(len(report.risk_coverage), 2)

    def test_source_group_cannot_cross_dataset_partitions(self):
        policy = _policy(
            (
                PilotMetricThreshold(
                    metric=PilotMetric.CLAIM_PRECISION,
                    minimum=0.8,
                ),
            ),
            minimum_documents=2,
        )
        documents = (
            _document(
                "doc-a",
                source_group="shared-course",
                split=PilotSplit.DEVELOPMENT,
                metrics=(
                    _metric(PilotMetric.CLAIM_PRECISION, 1),
                ),
            ),
            _document(
                "doc-b",
                source_group="shared-course",
                split=PilotSplit.SEALED_BLIND,
                metrics=(
                    _metric(PilotMetric.CLAIM_PRECISION, 1),
                ),
            ),
        )

        report = evaluate_pilot(
            _dataset(policy, documents),
            evaluated_at=NOW,
        )

        self.assertEqual(report.gate_decision, PilotGateDecision.BLOCK)
        self.assertEqual(len(report.source_group_leakage), 1)
        self.assertIn(
            "source_group_split_leakage:shared-course",
            report.blockers,
        )

    def test_pooled_average_cannot_hide_a_bad_document_or_slice(self):
        policy = _policy(
            (
                PilotMetricThreshold(
                    metric=PilotMetric.MUST_HAVE_RECALL,
                    minimum=0.8,
                    per_document_hard_gate=True,
                    per_slice_hard_gate=True,
                ),
            ),
            minimum_documents=2,
        )
        documents = (
            _document(
                "doc-bad",
                source_group="group-bad",
                metrics=(
                    _metric(PilotMetric.MUST_HAVE_RECALL, 7, 10),
                ),
                strata=(StringValue(key="object", value="formula"),),
            ),
            _document(
                "doc-good",
                source_group="group-good",
                metrics=(
                    _metric(PilotMetric.MUST_HAVE_RECALL, 100, 100),
                ),
                strata=(StringValue(key="object", value="text"),),
            ),
        )

        report = evaluate_pilot(
            _dataset(policy, documents),
            evaluated_at=NOW,
        )

        overall = report.overall_metrics[0]
        self.assertGreater(overall.value, 0.8)
        self.assertTrue(overall.passed)
        self.assertEqual(report.gate_decision, PilotGateDecision.BLOCK)
        self.assertEqual(report.worst_document_ids[0], "doc-bad")
        self.assertEqual(report.worst_slice_keys[0], "object:formula")
        self.assertIn(
            "document_metric_failed:doc-bad:must_have_recall",
            report.blockers,
        )

    def test_risk_coverage_curve_exposes_error_concentration(self):
        policy = _policy(
            (
                PilotMetricThreshold(
                    metric=PilotMetric.CLAIM_PRECISION,
                    minimum=0.5,
                ),
            ),
        )
        risk_items = (
            RiskItemObservation(
                item_id="item-a",
                predicted_risk=0.1,
                is_error=False,
            ),
            RiskItemObservation(
                item_id="item-b",
                predicted_risk=0.2,
                is_error=False,
            ),
            RiskItemObservation(
                item_id="item-c",
                predicted_risk=0.8,
                is_error=True,
            ),
            RiskItemObservation(
                item_id="item-d",
                predicted_risk=0.9,
                is_error=True,
            ),
        )
        document = _document(
            "doc-risk",
            source_group="group-risk",
            metrics=(_metric(PilotMetric.CLAIM_PRECISION, 1),),
            risk_items=risk_items,
        )

        report = evaluate_pilot(
            _dataset(policy, (document,)),
            evaluated_at=NOW,
        )

        self.assertEqual(
            report.risk_coverage[0].target_coverage,
            0.5,
        )
        self.assertEqual(
            report.risk_coverage[0].selective_risk,
            0,
        )
        self.assertEqual(
            report.risk_coverage[-1].selective_risk,
            0.5,
        )
        self.assertEqual(
            report.risk_coverage[-1].maximum_included_risk,
            0.9,
        )

    def test_five_run_parent_instability_blocks_even_with_stable_nodes(self):
        policy = _policy(
            (
                PilotMetricThreshold(
                    metric=PilotMetric.CLAIM_PRECISION,
                    minimum=0.8,
                ),
            ),
            minimum_stability_runs=5,
            minimum_node_jaccard=1.0,
            minimum_edge_jaccard=0.75,
        )
        runs = _runs(
            (
                ("root>a", "root>b"),
                ("root>a", "root>b"),
                ("root>a", "root>b"),
                ("root>a", "a>b"),
                ("root>a", "b>a"),
            )
        )
        document = _document(
            "doc-unstable",
            source_group="group-unstable",
            metrics=(_metric(PilotMetric.CLAIM_PRECISION, 1),),
            runs=runs,
        )

        report = evaluate_pilot(
            _dataset(policy, (document,)),
            evaluated_at=NOW,
        )

        result = report.documents[0]
        self.assertEqual(
            result.stability_decision,
            PilotGateDecision.BLOCK,
        )
        self.assertEqual(result.minimum_node_jaccard, 1)
        self.assertLess(result.minimum_edge_jaccard, 0.75)
        self.assertEqual(report.gate_decision, PilotGateDecision.BLOCK)

    def test_default_redesign_policy_stays_incomplete_without_real_pilot(self):
        policy = default_redesign_pilot_policy()
        metrics = tuple(
            _metric(threshold.metric, 1)
            for threshold in policy.metric_thresholds
        )
        document = _document(
            "doc-only",
            source_group="group-only",
            metrics=metrics,
            runs=_runs((("root>a",),) * 5),
        )

        report = evaluate_pilot(
            _dataset(policy, (document,)),
            evaluated_at=NOW,
        )

        self.assertEqual(
            report.gate_decision,
            PilotGateDecision.INCOMPLETE,
        )
        self.assertTrue(
            any(
                reason.startswith("document_count_below_policy_minimum")
                for reason in report.incomplete_reasons
            )
        )
        self.assertIn(
            "threshold_unfrozen:published_claim_coverage",
            report.incomplete_reasons,
        )

    def test_pilot_cli_returns_distinct_incomplete_exit_status(self):
        policy = _policy(
            (
                PilotMetricThreshold(
                    metric=PilotMetric.CLAIM_PRECISION,
                    minimum=None,
                ),
            ),
        )
        document = _document(
            "doc-cli",
            source_group="group-cli",
            metrics=(_metric(PilotMetric.CLAIM_PRECISION, 1),),
        )
        dataset = _dataset(policy, (document,))

        with tempfile.TemporaryDirectory() as tmp:
            input_path = Path(tmp) / "pilot.json"
            input_path.write_text(
                dataset.model_dump_json(),
                encoding="utf-8",
            )
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main(
                    ["pilot-evaluate", "--input", str(input_path)]
                )

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 3)
        self.assertEqual(payload["gate_decision"], "incomplete")
        self.assertTrue(payload["report_id"].startswith("pilot_report_"))


if __name__ == "__main__":
    unittest.main()
