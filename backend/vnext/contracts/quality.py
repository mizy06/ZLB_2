from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator, model_validator

from .base import FrozenContract
from .common import Sha256Digest, StringValue


PilotDatasetId = Annotated[
    str,
    StringConstraints(pattern=r"^pilot_[A-Za-z0-9._-]{1,96}$"),
]
PilotReportId = Annotated[
    str,
    StringConstraints(pattern=r"^pilot_report_[0-9a-f]{32}$"),
]


class PilotSplit(StrEnum):
    DEVELOPMENT = "development"
    CALIBRATION = "calibration"
    SEALED_BLIND = "sealed_blind"


class PilotMetric(StrEnum):
    CLAIM_PRECISION = "claim_precision"
    EVIDENCE_ALIGNMENT = "evidence_alignment"
    MUST_HAVE_RECALL = "must_have_recall"
    REGION_ACCOUNTING = "region_accounting"
    REPLAN_SERIOUS_ERROR_RECALL = "replan_serious_error_recall"
    AUTHORITY_COMPLIANCE = "authority_compliance"
    DIRECT_PARENT_PRECISION = "direct_parent_precision"
    DIRECT_PARENT_RECALL = "direct_parent_recall"
    ANCESTOR_F1 = "ancestor_f1"
    SOURCE_ORDER_SCORE = "source_order_score"
    BRANCH_PURITY = "branch_purity"
    BRANCH_THEME_CLEAN_RATE = "branch_theme_clean_rate"
    SIBLING_GRANULARITY_CONSISTENCY = (
        "sibling_granularity_consistency"
    )
    FRAGMENT_ROOT_FREE_RATE = "fragment_root_free_rate"
    PUBLISHED_CLAIM_COVERAGE = "published_claim_coverage"
    HIGH_VALUE_RESOLUTION_RATE = "high_value_resolution_rate"


class PilotGateDecision(StrEnum):
    PASS = "pass"
    BLOCK = "block"
    INCOMPLETE = "incomplete"


class SplitRequirement(FrozenContract):
    split: PilotSplit
    minimum_documents: int = Field(ge=0)


class PilotMetricThreshold(FrozenContract):
    metric: PilotMetric
    minimum: float | None = Field(default=None, ge=0, le=1)
    per_document_hard_gate: bool = False
    per_slice_hard_gate: bool = False


class PilotEvaluationPolicy(FrozenContract):
    policy_version: Annotated[
        str,
        StringConstraints(min_length=1, max_length=128),
    ]
    minimum_document_count: int = Field(ge=1)
    split_requirements: tuple[SplitRequirement, ...]
    metric_thresholds: tuple[PilotMetricThreshold, ...] = Field(
        min_length=1
    )
    minimum_stability_runs: int = Field(default=5, ge=2)
    minimum_node_jaccard: float | None = Field(
        default=None,
        ge=0,
        le=1,
    )
    minimum_edge_jaccard: float | None = Field(
        default=None,
        ge=0,
        le=1,
    )
    minimum_slice_documents: int = Field(default=2, ge=1)
    worst_document_fraction: float = Field(default=0.1, gt=0, le=1)
    risk_coverage_targets: tuple[float, ...] = (
        0.25,
        0.5,
        0.75,
        1.0,
    )

    @model_validator(mode="after")
    def validate_policy(self) -> "PilotEvaluationPolicy":
        splits = [item.split for item in self.split_requirements]
        if len(splits) != len(set(splits)):
            raise ValueError("pilot split requirements must be unique")
        if splits != sorted(splits, key=str):
            raise ValueError(
                "pilot split requirements must use deterministic order"
            )
        metrics = [item.metric for item in self.metric_thresholds]
        if len(metrics) != len(set(metrics)):
            raise ValueError("pilot metric thresholds must be unique")
        if metrics != sorted(metrics, key=str):
            raise ValueError(
                "pilot metric thresholds must use deterministic order"
            )
        targets = self.risk_coverage_targets
        if (
            not targets
            or any(
                isinstance(value, bool)
                or value <= 0
                or value > 1
                for value in targets
            )
            or tuple(sorted(set(targets))) != targets
        ):
            raise ValueError(
                "risk coverage targets must be unique, sorted, and in (0, 1]"
            )
        return self


class MetricObservation(FrozenContract):
    metric: PilotMetric
    success_weight: float = Field(ge=0)
    total_weight: float = Field(gt=0)

    @model_validator(mode="after")
    def validate_weights(self) -> "MetricObservation":
        if self.success_weight > self.total_weight:
            raise ValueError(
                "metric success_weight cannot exceed total_weight"
            )
        return self


class RiskItemObservation(FrozenContract):
    item_id: Annotated[
        str,
        StringConstraints(min_length=1, max_length=256),
    ]
    predicted_risk: float = Field(ge=0, le=1)
    is_error: bool
    importance_weight: float = Field(default=1.0, gt=0)


class StabilityRunObservation(FrozenContract):
    run_key: Annotated[
        str,
        StringConstraints(min_length=1, max_length=256),
    ]
    concept_keys: tuple[
        Annotated[str, StringConstraints(min_length=1, max_length=512)],
        ...,
    ] = ()
    direct_parent_keys: tuple[
        Annotated[str, StringConstraints(min_length=1, max_length=1024)],
        ...,
    ] = ()

    @model_validator(mode="after")
    def validate_keys(self) -> "StabilityRunObservation":
        for field_name, values in (
            ("concept_keys", self.concept_keys),
            ("direct_parent_keys", self.direct_parent_keys),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"{field_name} must not contain duplicates")
            if values != tuple(sorted(values)):
                raise ValueError(
                    f"{field_name} must use deterministic order"
                )
        return self


class PilotDocumentObservation(FrozenContract):
    document_id: Annotated[
        str,
        StringConstraints(min_length=1, max_length=256),
    ]
    source_group_id: Annotated[
        str,
        StringConstraints(min_length=1, max_length=256),
    ]
    split: PilotSplit
    strata: tuple[StringValue, ...] = ()
    metrics: tuple[MetricObservation, ...] = Field(min_length=1)
    risk_items: tuple[RiskItemObservation, ...] = ()
    stability_runs: tuple[StabilityRunObservation, ...] = ()
    serious_error_codes: tuple[
        Annotated[str, StringConstraints(min_length=1, max_length=128)],
        ...,
    ] = ()

    @model_validator(mode="after")
    def validate_document(self) -> "PilotDocumentObservation":
        strata_keys = [item.key for item in self.strata]
        if len(strata_keys) != len(set(strata_keys)):
            raise ValueError("document strata keys must be unique")
        if self.strata != tuple(
            sorted(self.strata, key=lambda item: (item.key, item.value))
        ):
            raise ValueError(
                "document strata must use deterministic order"
            )
        metrics = [item.metric for item in self.metrics]
        if len(metrics) != len(set(metrics)):
            raise ValueError("document metrics must be unique")
        if metrics != sorted(metrics, key=str):
            raise ValueError(
                "document metrics must use deterministic order"
            )
        risk_ids = [item.item_id for item in self.risk_items]
        if len(risk_ids) != len(set(risk_ids)):
            raise ValueError("risk item IDs must be unique per document")
        if risk_ids != sorted(risk_ids):
            raise ValueError(
                "risk items must use deterministic item_id order"
            )
        run_keys = [item.run_key for item in self.stability_runs]
        if len(run_keys) != len(set(run_keys)):
            raise ValueError("stability run keys must be unique")
        if run_keys != sorted(run_keys):
            raise ValueError(
                "stability runs must use deterministic run_key order"
            )
        if len(self.serious_error_codes) != len(
            set(self.serious_error_codes)
        ):
            raise ValueError("serious error codes must be unique")
        if self.serious_error_codes != tuple(
            sorted(self.serious_error_codes)
        ):
            raise ValueError(
                "serious error codes must use deterministic order"
            )
        return self


class PilotDataset(FrozenContract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    dataset_id: PilotDatasetId
    frozen_at: datetime
    policy: PilotEvaluationPolicy
    documents: tuple[PilotDocumentObservation, ...] = Field(min_length=1)

    @field_validator("frozen_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("pilot dataset timestamp requires timezone")
        return value

    @model_validator(mode="after")
    def validate_documents(self) -> "PilotDataset":
        document_ids = [item.document_id for item in self.documents]
        if len(document_ids) != len(set(document_ids)):
            raise ValueError("pilot document IDs must be unique")
        if document_ids != sorted(document_ids):
            raise ValueError(
                "pilot documents must use deterministic document_id order"
            )
        return self


class PilotMetricResult(FrozenContract):
    metric: PilotMetric
    success_weight: float = Field(ge=0)
    total_weight: float = Field(gt=0)
    value: float = Field(ge=0, le=1)
    threshold: float | None = Field(default=None, ge=0, le=1)
    passed: bool | None = None


class DocumentEvaluationResult(FrozenContract):
    document_id: str
    source_group_id: str
    split: PilotSplit
    metrics: tuple[PilotMetricResult, ...]
    stability_decision: PilotGateDecision
    minimum_node_jaccard: float | None = Field(
        default=None,
        ge=0,
        le=1,
    )
    mean_node_jaccard: float | None = Field(
        default=None,
        ge=0,
        le=1,
    )
    minimum_edge_jaccard: float | None = Field(
        default=None,
        ge=0,
        le=1,
    )
    mean_edge_jaccard: float | None = Field(
        default=None,
        ge=0,
        le=1,
    )
    gate_decision: PilotGateDecision
    findings: tuple[str, ...] = ()


class SliceEvaluationResult(FrozenContract):
    slice_key: Annotated[
        str,
        StringConstraints(min_length=1, max_length=512),
    ]
    document_count: int = Field(ge=1)
    metrics: tuple[PilotMetricResult, ...]
    gate_decision: PilotGateDecision
    worst_document_ids: tuple[str, ...] = ()
    findings: tuple[str, ...] = ()


class RiskCoveragePoint(FrozenContract):
    target_coverage: float = Field(gt=0, le=1)
    realized_coverage: float = Field(gt=0, le=1)
    selective_risk: float = Field(ge=0, le=1)
    retained_weight: float = Field(gt=0)
    retained_item_count: int = Field(ge=1)
    maximum_included_risk: float = Field(ge=0, le=1)


class SourceGroupLeakage(FrozenContract):
    source_group_id: str
    splits: tuple[PilotSplit, ...] = Field(min_length=2)
    document_ids: tuple[str, ...] = Field(min_length=2)


class PilotEvaluationReport(FrozenContract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    report_id: PilotReportId
    dataset_id: PilotDatasetId
    dataset_digest: Sha256Digest
    policy_digest: Sha256Digest
    evaluated_at: datetime
    document_count: int = Field(ge=1)
    split_counts: tuple[StringValue, ...]
    overall_metrics: tuple[PilotMetricResult, ...]
    documents: tuple[DocumentEvaluationResult, ...]
    slices: tuple[SliceEvaluationResult, ...]
    worst_document_ids: tuple[str, ...]
    worst_slice_keys: tuple[str, ...]
    risk_coverage: tuple[RiskCoveragePoint, ...]
    source_group_leakage: tuple[SourceGroupLeakage, ...]
    gate_decision: PilotGateDecision
    blockers: tuple[str, ...] = ()
    incomplete_reasons: tuple[str, ...] = ()

    @field_validator("evaluated_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("pilot report timestamp requires timezone")
        return value

    @model_validator(mode="after")
    def validate_report(self) -> "PilotEvaluationReport":
        if self.gate_decision is PilotGateDecision.PASS and (
            self.blockers or self.incomplete_reasons
        ):
            raise ValueError(
                "passing pilot report cannot retain blockers or "
                "incomplete reasons"
            )
        if (
            self.gate_decision is PilotGateDecision.BLOCK
            and not self.blockers
        ):
            raise ValueError("blocked pilot report requires blockers")
        if (
            self.gate_decision is PilotGateDecision.INCOMPLETE
            and not self.incomplete_reasons
        ):
            raise ValueError(
                "incomplete pilot report requires incomplete reasons"
            )
        return self
