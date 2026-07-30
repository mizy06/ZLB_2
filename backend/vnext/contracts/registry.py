from __future__ import annotations

from dataclasses import dataclass

from .artifacts import ArtifactEnvelope
from .base import FrozenContract
from .claims import ClaimLedger, OmissionAudit
from .common import ArtifactType
from .control import (
    ModelPortfolioManifest,
    QualityAttestation,
    RunManifest,
    StageCommit,
    TaskEnvelope,
)
from .crosslinks import (
    CrossLinkProposalLedger,
    CrossLinkResolutionLedger,
)
from .graph import (
    CanonicalExplicitGraph,
    RelationAssessmentLedger,
    RelationProposalLedger,
)
from .inventory import SourceInventory
from .integrations import (
    EvidenceBundle,
    RecordedInteraction,
    SearchIntent,
)
from .model_semantics import (
    ClaimProposalBatch,
    RegionDecisionVerification,
    RegionPlannerProposal,
)
from .projection import DiagnosticProjection
from .presentation import (
    ProjectionMediaBundle,
    RenderedPresentationBundle,
)
from .quality import PilotDataset, PilotEvaluationReport
from .release import (
    CanaryPolicy,
    CanaryTransitionDecision,
    ReleaseEvent,
    RollbackRecord,
)
from .review import AffectedReplayPlan, ReviewDecision, ReviewTask
from .regions import RegionPlan, RegionSplitCertificate, ReplanRequest
from .source import SourceObservationIR


@dataclass(frozen=True, slots=True)
class ContractRegistration:
    name: str
    artifact_type: ArtifactType | None
    model: type[FrozenContract]
    schema_id: str
    version: str
    filename: str


def _registration(
    name: str,
    artifact_type: ArtifactType | None,
    model: type[FrozenContract],
    slug: str,
    version: str,
) -> ContractRegistration:
    return ContractRegistration(
        name=name,
        artifact_type=artifact_type,
        model=model,
        schema_id=f"urn:zlb:vnext:schema:{slug}:{version}",
        version=version,
        filename=f"{slug}-{version}.schema.json",
    )


CONTRACTS: tuple[ContractRegistration, ...] = (
    _registration(
        "SourceObservationIR",
        ArtifactType.SOURCE_OBSERVATION_IR,
        SourceObservationIR,
        "source-observation-ir",
        "1.0.0",
    ),
    _registration(
        "SourceInventory",
        ArtifactType.SOURCE_INVENTORY,
        SourceInventory,
        "source-inventory",
        "1.0.0",
    ),
    _registration(
        "RegionPlan",
        ArtifactType.REGION_PLAN,
        RegionPlan,
        "region-plan",
        "1.0.0",
    ),
    _registration(
        "RegionSplitCertificate",
        ArtifactType.REGION_SPLIT_CERTIFICATE,
        RegionSplitCertificate,
        "region-split-certificate",
        "1.0.0",
    ),
    _registration(
        "ReplanRequest",
        ArtifactType.REPLAN_REQUEST,
        ReplanRequest,
        "replan-request",
        "1.0.0",
    ),
    _registration(
        "ClaimLedger",
        ArtifactType.CLAIM_LEDGER,
        ClaimLedger,
        "claim-ledger",
        "1.0.0",
    ),
    _registration(
        "ClaimProposalBatch",
        None,
        ClaimProposalBatch,
        "claim-proposal-batch",
        "1.0.0",
    ),
    _registration(
        "RegionPlannerProposal",
        None,
        RegionPlannerProposal,
        "region-planner-proposal",
        "1.0.0",
    ),
    _registration(
        "RegionDecisionVerification",
        None,
        RegionDecisionVerification,
        "region-decision-verification",
        "1.0.0",
    ),
    _registration(
        "OmissionAudit",
        ArtifactType.OMISSION_AUDIT,
        OmissionAudit,
        "omission-audit",
        "1.0.0",
    ),
    _registration(
        "RelationProposalLedger",
        ArtifactType.RELATION_PROPOSAL_LEDGER,
        RelationProposalLedger,
        "relation-proposal-ledger",
        "1.0.0",
    ),
    _registration(
        "RelationAssessmentLedger",
        ArtifactType.RELATION_ASSESSMENT_LEDGER,
        RelationAssessmentLedger,
        "relation-assessment-ledger",
        "1.0.0",
    ),
    _registration(
        "CanonicalExplicitGraph",
        ArtifactType.CANONICAL_EXPLICIT_GRAPH,
        CanonicalExplicitGraph,
        "canonical-explicit-graph",
        "0.1.0",
    ),
    _registration(
        "DiagnosticProjection",
        ArtifactType.DIAGNOSTIC_PROJECTION,
        DiagnosticProjection,
        "diagnostic-projection",
        "0.1.0",
    ),
    _registration(
        "ArtifactEnvelope",
        None,
        ArtifactEnvelope,
        "artifact-envelope",
        "1.0.0",
    ),
    _registration(
        "RunManifest",
        None,
        RunManifest,
        "run-manifest",
        "1.0.0",
    ),
    _registration(
        "StageCommit",
        None,
        StageCommit,
        "stage-commit",
        "1.0.0",
    ),
    _registration(
        "QualityAttestation",
        None,
        QualityAttestation,
        "quality-attestation",
        "1.0.0",
    ),
    _registration(
        "TaskEnvelope",
        None,
        TaskEnvelope,
        "task-envelope",
        "1.0.0",
    ),
    _registration(
        "ModelPortfolioManifest",
        None,
        ModelPortfolioManifest,
        "model-portfolio-manifest",
        "1.0.0",
    ),
    _registration(
        "RecordedInteraction",
        None,
        RecordedInteraction,
        "recorded-interaction",
        "1.0.0",
    ),
    _registration(
        "SearchIntent",
        None,
        SearchIntent,
        "search-intent",
        "1.0.0",
    ),
    _registration(
        "EvidenceBundle",
        None,
        EvidenceBundle,
        "evidence-bundle",
        "1.0.0",
    ),
    _registration(
        "PilotDataset",
        None,
        PilotDataset,
        "pilot-dataset",
        "1.0.0",
    ),
    _registration(
        "PilotEvaluationReport",
        None,
        PilotEvaluationReport,
        "pilot-evaluation-report",
        "1.0.0",
    ),
    _registration(
        "ReviewTask",
        None,
        ReviewTask,
        "review-task",
        "1.0.0",
    ),
    _registration(
        "ReviewDecision",
        None,
        ReviewDecision,
        "review-decision",
        "1.0.0",
    ),
    _registration(
        "AffectedReplayPlan",
        None,
        AffectedReplayPlan,
        "affected-replay-plan",
        "1.0.0",
    ),
    _registration(
        "CrossLinkProposalLedger",
        None,
        CrossLinkProposalLedger,
        "cross-link-proposal-ledger",
        "1.0.0",
    ),
    _registration(
        "CrossLinkResolutionLedger",
        None,
        CrossLinkResolutionLedger,
        "cross-link-resolution-ledger",
        "1.0.0",
    ),
    _registration(
        "CanaryPolicy",
        None,
        CanaryPolicy,
        "canary-policy",
        "1.0.0",
    ),
    _registration(
        "CanaryTransitionDecision",
        None,
        CanaryTransitionDecision,
        "canary-transition-decision",
        "1.0.0",
    ),
    _registration(
        "RollbackRecord",
        None,
        RollbackRecord,
        "rollback-record",
        "1.0.0",
    ),
    _registration(
        "ReleaseEvent",
        None,
        ReleaseEvent,
        "release-event",
        "1.0.0",
    ),
    _registration(
        "ProjectionMediaBundle",
        None,
        ProjectionMediaBundle,
        "projection-media-bundle",
        "1.0.0",
    ),
    _registration(
        "RenderedPresentationBundle",
        None,
        RenderedPresentationBundle,
        "rendered-presentation-bundle",
        "1.0.0",
    ),
)

CONTRACT_BY_NAME = {item.name: item for item in CONTRACTS}
CONTRACT_BY_ARTIFACT_TYPE = {
    item.artifact_type: item
    for item in CONTRACTS
    if item.artifact_type is not None
}
CONTRACT_BY_MODEL = {item.model: item for item in CONTRACTS}


def registration_for_model(
    model: FrozenContract | type[FrozenContract],
) -> ContractRegistration:
    model_type = model if isinstance(model, type) else type(model)
    try:
        return CONTRACT_BY_MODEL[model_type]
    except KeyError as exc:
        raise ValueError(
            f"unregistered vNext contract model: {model_type.__name__}"
        ) from exc
