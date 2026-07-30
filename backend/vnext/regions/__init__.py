"""Top-down region planning contracts and deterministic gates."""

from backend.vnext.contracts.regions import (
    RegionPlan,
    RegionSplitCertificate,
    ReplanRequest,
)

from .gates import (
    GateResult,
    evaluate_split_certificate,
    evaluate_stop_proposal,
    validate_replan_scope,
)
from .auditor import audit_regions_bottom_up
from .model_stage import (
    ModelRegionStageError,
    RecordedRegionModelStage,
    prepare_region_planner_tasks,
    prepare_region_verifier_task,
)
from .planner import (
    ExplicitRegionDecisionContext,
    ExplicitRegionDecisionProvider,
    RegionPlanningResult,
    RegionSemanticDecision,
    enumerate_explicit_region_decision_contexts,
    load_region_planning_result,
    plan_explicit_regions,
)

__all__ = [
    "ExplicitRegionDecisionContext",
    "ExplicitRegionDecisionProvider",
    "GateResult",
    "ModelRegionStageError",
    "RecordedRegionModelStage",
    "RegionPlan",
    "RegionPlanningResult",
    "RegionSemanticDecision",
    "RegionSplitCertificate",
    "ReplanRequest",
    "audit_regions_bottom_up",
    "enumerate_explicit_region_decision_contexts",
    "evaluate_split_certificate",
    "evaluate_stop_proposal",
    "load_region_planning_result",
    "plan_explicit_regions",
    "prepare_region_planner_tasks",
    "prepare_region_verifier_task",
    "validate_replan_scope",
]
