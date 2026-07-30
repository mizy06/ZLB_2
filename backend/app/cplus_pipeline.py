from __future__ import annotations

import asyncio
import hashlib
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Awaitable, Callable, TypedDict

import networkx as nx
from langgraph.graph import END, START, StateGraph

from .agents import (
    BranchTeamResult,
    ParentVerificationRunStats,
    RoleRuntime,
    ThemePlanOutput,
    _plan_seed_node_routes,
    audit_coverage,
    build_branch_plans,
    build_content_units,
    build_global_parent_candidates,
    canonicalize_semantic_duplicates,
    coverage_statistics,
    fuse_visual_media,
    run_branch_teams,
    stable_id,
    synthesize_themes,
    theme_nodes,
    verify_parent_candidates,
)
from .architecture_schemas import (
    BranchPlan,
    ContentUnit,
    CoverageSummary,
    DecisionRecord,
    MindMapCrossLink,
    MindMapNode,
    MindMapQualityReport,
    MindMapResult,
    MindMapTreeEdge,
    ModelSelection,
    ReviewItemView,
    RunMode,
)
from .blackboard import SQLiteBlackboard, utc_now
from .chunking import chunk_document
from .config import settings
from .document_parser import parse_document
from .mindmap_engine.normalize import (
    is_publishable_node_label,
    normalize_graph,
)
from .mindmap_engine.schemas import (
    CrossLinkCandidateIn,
    NodeCandidateIn,
    NormalizeRequest,
    NormalizedGraph,
    ParentCandidateIn,
    SolveRequest,
    SolveResponse,
    VisualAsset,
)
from .mindmap_engine.topology import (
    DEFAULT_TOPOLOGY_LIMITS,
    STRICT_PAGE_TOPOLOGY_LIMITS,
    solve_topology,
)
from .mindmap_engine.visuals import render_document
from .model_provider import (
    ModelCallContext,
    OpenAICompatibleClient,
    model_call_context,
    set_model_call_stage,
)
from .pdf_page_knowledge import (
    PDF_KNOWLEDGE_DEGRADED,
    extract_pdf_page_knowledge,
)
from .pdf_page_transcription import (
    PDF_TRANSCRIPTION_DEGRADED,
    transcribe_pdf_pages,
)
from .qwen_provider import QwenClient
from .schemas import Chunk, ParsedDocument
from .visual_analysis import analyze_visual_pages


ProgressCallback = Callable[[str, int, str], Awaitable[None]]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _merge_content_units(
    base_units: list[ContentUnit],
    additions: list[ContentUnit],
) -> list[ContentUnit]:
    merged = list(base_units)
    index_by_id = {
        unit.id: index
        for index, unit in enumerate(merged)
    }
    for addition in additions:
        index = index_by_id.get(addition.id)
        if index is None:
            index_by_id[addition.id] = len(merged)
            merged.append(addition)
            continue
        existing = merged[index]
        if not (
            existing.kind == addition.kind == "visual"
            and existing.asset_id
            and existing.asset_id == addition.asset_id
        ):
            raise ValueError(
                f"内容单元 ID 冲突且不能安全归并：{addition.id}"
            )
        merged[index] = addition
    return merged


def _build_planning_projection(
    units: list[ContentUnit],
    seed_nodes: list[NodeCandidateIn],
) -> tuple[list[ContentUnit], dict[str, str]]:
    """Collapse seed-covered page atoms for planning without changing evidence."""

    active_ids = {
        unit.id
        for unit in units
        if unit.status in {"uncovered", "covered"}
    }
    seeded_ids = {
        unit_id
        for candidate in seed_nodes
        if candidate.origin == "explicit"
        for evidence in candidate.evidence
        if (
            unit_id := evidence.unit_id or evidence.chunk_id
        ) in active_ids
    }
    if not seeded_ids:
        return list(units), {}

    grouped: dict[tuple[str, int], list[ContentUnit]] = defaultdict(list)
    ordered_entries: list[tuple[str, object]] = []
    seen_groups: set[tuple[str, int]] = set()
    for unit in units:
        coordinate: tuple[str, int] | None = None
        if unit.id in seeded_ids and unit.kind == "text":
            if unit.page is not None:
                coordinate = ("page", unit.page)
            elif unit.slide is not None:
                coordinate = ("slide", unit.slide)
        if coordinate is None:
            ordered_entries.append(("unit", unit))
            continue
        grouped[coordinate].append(unit)
        if coordinate not in seen_groups:
            ordered_entries.append(("group", coordinate))
            seen_groups.add(coordinate)

    projection: list[ContentUnit] = []
    seed_unit_projection: dict[str, str] = {}
    for entry_kind, value in ordered_entries:
        if entry_kind == "unit":
            unit = value
            if not isinstance(unit, ContentUnit):
                raise TypeError("planning projection unit type is invalid")
            projection.append(unit)
            if unit.id in seeded_ids:
                seed_unit_projection[unit.id] = unit.id
            continue

        coordinate = value
        if not isinstance(coordinate, tuple):
            raise TypeError("planning projection coordinate is invalid")
        source_units = grouped[coordinate]
        representative = source_units[0]
        source_texts = list(
            dict.fromkeys(
                text.strip()
                for unit in source_units
                if (
                    text := (
                        unit.evidence_excerpt
                        or unit.text
                        or unit.summary
                        or unit.ocr_text
                    )
                ).strip()
            )
        )
        combined = "\n".join(source_texts)
        projected = representative.model_copy(
            update={
                "importance": max(unit.importance for unit in source_units),
                "text": combined[:2600],
                "evidence_excerpt": combined[:480],
                "summary": combined[:480],
                "bbox": None,
            }
        )
        projection.append(projected)
        for unit in source_units:
            seed_unit_projection[unit.id] = projected.id

    return projection, seed_unit_projection


def _planning_unit_node_weights(
    planning_units: list[ContentUnit],
    seed_nodes: list[NodeCandidateIn],
    seed_unit_projection: dict[str, str],
) -> dict[str, int]:
    """Estimate direct leaf load from routed seeds and unseeded units."""

    planning_ids = [unit.id for unit in planning_units]
    _, seeded_ids, owner_counts = _plan_seed_node_routes(
        planning_ids,
        seed_nodes,
        seed_unit_projection,
    )
    return {
        unit_id: (
            max(1, owner_counts[unit_id])
            if unit_id in seeded_ids
            else 2
        )
        for unit_id in planning_ids
    }


class CPlusState(TypedDict, total=False):
    task_id: str
    run_id: str
    file_path: str
    filename: str
    mode: RunMode
    use_ai: bool
    generator_runtime: RoleRuntime
    verifier_runtime: RoleRuntime
    vision_runtime: RoleRuntime
    second_verifier_runtime: RoleRuntime | None
    arbiter_runtime: RoleRuntime | None
    model_selection: ModelSelection
    blackboard: SQLiteBlackboard
    document: ParsedDocument
    chunks: list[Chunk]
    assets: list[VisualAsset]
    content_units: list[ContentUnit]
    page_node_candidates: list[NodeCandidateIn]
    planning_content_units: list[ContentUnit]
    seed_unit_projection: dict[str, str]
    planning_unit_node_weights: dict[str, int]
    strict_page_topology: bool
    theme_plan: ThemePlanOutput
    branch_plans: list[BranchPlan]
    branch_results: list[BranchTeamResult]
    node_candidates: list[NodeCandidateIn]
    parent_candidates: list[ParentCandidateIn]
    cross_link_candidates: list[CrossLinkCandidateIn]
    normalized_graph: NormalizedGraph
    parent_votes: dict
    parent_verification_stats: ParentVerificationRunStats
    solve_response: SolveResponse
    extraction_mode: str
    warnings: list[str]
    degraded_components: list[str]
    result: MindMapResult


def _client(provider: str) -> OpenAICompatibleClient:
    if provider == "qwen":
        return QwenClient(settings)
    raise ValueError(f"Unsupported provider: {provider}")


async def _runtime(
    provider: str,
    model: str,
    use_ai: bool,
    *,
    client: OpenAICompatibleClient | None = None,
) -> RoleRuntime:
    client = client or _client(provider)
    if not use_ai:
        return RoleRuntime(
            provider=provider,
            model=model,
            client=client,
            available=False,
            unavailable_reason="用户关闭了模型调用",
        )
    if not client.api_key:
        return RoleRuntime(
            provider=provider,
            model=model,
            client=client,
            available=False,
            unavailable_reason="未配置 API Key",
        )
    ok, message = await client.check_model(model)
    return RoleRuntime(
        provider=provider,
        model=model,
        client=client,
        available=ok,
        unavailable_reason="" if ok else message,
    )


async def build_role_runtimes(
    *,
    provider: str,
    model: str,
    mode: RunMode,
    use_ai: bool,
) -> tuple[
    RoleRuntime,
    RoleRuntime,
    RoleRuntime,
    RoleRuntime | None,
    RoleRuntime | None,
    ModelSelection,
    list[str],
]:
    if provider != "qwen":
        raise ValueError(f"Unsupported provider: {provider}")
    client = _client("qwen")
    checked_runtime = await _runtime(
        "qwen",
        model,
        use_ai,
        client=client,
    )
    checked_vision_runtime = (
        checked_runtime
        if settings.qwen_vision_model == model
        else await _runtime(
            "qwen",
            settings.qwen_vision_model,
            use_ai,
            client=client,
        )
    )

    def role_runtime(
        checked: RoleRuntime = checked_runtime,
    ) -> RoleRuntime:
        return RoleRuntime(
            provider=checked.provider,
            model=checked.model,
            client=checked.client,
            available=checked.available,
            unavailable_reason=checked.unavailable_reason,
        )

    generator = role_runtime()
    verifier = role_runtime()
    vision = role_runtime(checked_vision_runtime)

    warnings: list[str] = []
    if use_ai and not vision.available:
        warnings.append(
            "页级视觉转录模型不可用："
            + (vision.unavailable_reason or vision.model)
        )

    second: RoleRuntime | None = None
    arbiter: RoleRuntime | None = None
    if mode == "precision":
        second = role_runtime()
        arbiter = role_runtime()

    selection = ModelSelection(
        generator_provider=generator.provider,
        generator_model=generator.model if generator.available else None,
        verifier_provider=verifier.provider,
        verifier_model=verifier.model if verifier.available else None,
        vision_provider=vision.provider,
        vision_model=vision.model if vision.available else None,
        arbiter_provider=arbiter.provider if arbiter else None,
        arbiter_model=(arbiter.model if arbiter and arbiter.available else None),
    )
    return generator, verifier, vision, second, arbiter, selection, warnings


def _pages_as_assets(response) -> list[VisualAsset]:
    return [
        VisualAsset(
            asset_id=page.asset_id,
            render_id=page.render_id,
            filename=page.filename,
            url=page.url,
            source_page=page.page,
            width=page.width,
            height=page.height,
            visual_kind="full_page",
            status="ready",
        )
        for page in response.pages
    ]


def _render_warning_degraded_components(
    warnings: list[str],
) -> list[str]:
    component_by_code = {
        "render_budget": "visual_render_budget",
        "render_failure": "visual_rendering",
        "native_extraction": "visual_native_extraction",
    }
    components: list[str] = []
    marker = "[visual_degraded:"
    for warning in warnings:
        if marker not in warning:
            continue
        code = warning.split(marker, 1)[1].split("]", 1)[0].strip()
        if not code:
            continue
        component = component_by_code.get(code, f"visual_{code}")
        if component not in components:
            components.append(component)
    return components


def _create_decision_records(
    run_id: str,
    normalized: NormalizedGraph,
    solved: SolveResponse,
) -> list[DecisionRecord]:
    now = utc_now()
    active_ids = {node.id for node in solved.nodes}
    records: list[DecisionRecord] = [
        DecisionRecord(
            id=stable_id("decision", run_id, "root", solved.root_id),
            run_id=run_id,
            subject_type="root",
            subject_id=solved.root_id,
            actor="code",
            actor_version="cplus-supervisor-v1",
            decision="selected",
            reason_codes=["solver_unique_root"],
            evidence_unit_ids=next(
                (
                    node.support_unit_ids
                    for node in solved.nodes
                    if node.id == solved.root_id
                ),
                [],
            ),
            timestamp=now,
        )
    ]
    for node in normalized.nodes:
        records.append(
            DecisionRecord(
                id=stable_id("decision", run_id, "node", node.id),
                run_id=run_id,
                subject_type="node",
                subject_id=node.id,
                actor="code",
                actor_version="cplus-supervisor-v1",
                decision="accepted" if node.id in active_ids else "rejected",
                reason_codes=[
                    "solver_active" if node.id in active_ids else "solver_inactive"
                ],
                evidence_unit_ids=sorted(
                    {
                        *node.support_unit_ids,
                        *[
                            evidence.unit_id or evidence.chunk_id
                            for evidence in node.evidence
                            if evidence.unit_id or evidence.chunk_id
                        ],
                    }
                ),
                timestamp=now,
            )
        )
    for edge in solved.tree_edges:
        records.append(
            DecisionRecord(
                id=stable_id("decision", run_id, "tree_edge", edge.id),
                run_id=run_id,
                subject_type="tree_edge",
                subject_id=edge.id,
                actor="code",
                actor_version=f"topology:{solved.solver_status}",
                decision="selected",
                reason_codes=[
                    "provisional_fallback"
                    if edge.provisional
                    else "maximized_parent_score"
                ],
                evidence_unit_ids=sorted(
                    {
                        evidence.unit_id or evidence.chunk_id
                        for evidence in edge.evidence
                        if evidence.unit_id or evidence.chunk_id
                    }
                ),
                timestamp=now,
            )
        )
    return records


def quality_gate_failures(
    *,
    topology_valid: bool,
    evidence_coverage: float,
    provisional_edge_count: int,
    weighted_coverage: float,
    required_coverage: float,
    nodes,
    edge_classifications: list[str],
    edge_evidence: list[list],
    pending_review_count: int,
    degraded_components: list[str],
    max_nodes: int = 150,
) -> list[str]:
    failures: list[str] = []
    if not topology_valid:
        failures.append("invalid_topology")
    if evidence_coverage < 1:
        failures.append("incomplete_node_evidence")
    if provisional_edge_count:
        failures.append("provisional_edge")
    if weighted_coverage < required_coverage:
        failures.append("insufficient_content_coverage")
    if len(nodes) > max_nodes:
        failures.append("node_budget_exceeded")
    if any(
        not is_publishable_node_label(node)
        for node in nodes
    ):
        failures.append("illegal_label")
    if any(
        classification != "direct_parent"
        for classification in edge_classifications
    ):
        failures.append("non_direct_parent_edge")
    if any(not evidence for evidence in edge_evidence):
        failures.append("missing_edge_evidence")
    if pending_review_count:
        failures.append("pending_review")
    if degraded_components:
        failures.append("degraded_components")
    return failures


def verifier_degraded_components(
    existing: list[str],
    *,
    mode: RunMode,
    verifier: RoleRuntime,
    second_verifier: RoleRuntime | None,
    arbiter: RoleRuntime | None,
    stats: ParentVerificationRunStats,
) -> list[str]:
    """Map structured runtime outcomes to publish-blocking degradation."""

    components = list(dict.fromkeys(existing))

    def add(component: str) -> None:
        if component not in components:
            components.append(component)

    def add_runtime_fallback(
        role_stats,
        *,
        partial_component: str,
        failed_component: str,
    ) -> None:
        if not role_stats.fallback_batches:
            return
        add(
            partial_component
            if role_stats.succeeded_batches
            else failed_component
        )

    if stats.primary.requested_batches:
        if not verifier.available:
            add("independent_parent_verifier")
        else:
            add_runtime_fallback(
                stats.primary,
                partial_component="independent_parent_verifier_partial",
                failed_component="independent_parent_verifier_failed",
            )

    if mode != "precision":
        return components

    if stats.secondary.requested_batches:
        if second_verifier is None or not second_verifier.available:
            add("second_parent_verifier")
        else:
            add_runtime_fallback(
                stats.secondary,
                partial_component="second_parent_verifier_partial",
                failed_component="second_parent_verifier_failed",
            )

    if stats.arbiter.requested_batches:
        if arbiter is None or not arbiter.available:
            add("parent_verifier_arbiter")
        else:
            add_runtime_fallback(
                stats.arbiter,
                partial_component="parent_verifier_arbiter_partial",
                failed_component="parent_verifier_arbiter_failed",
            )
    return components


def _review_subject(
    review,
    solved: SolveResponse,
) -> tuple[str, str]:
    if review.type == "root_choice":
        return solved.root_id, "root"
    if review.type == "competing_parent":
        selected_targets = {
            edge.target
            for edge in solved.tree_edges
            if edge.source in review.subject_ids
            and edge.target in review.subject_ids
        }
        if len(selected_targets) == 1:
            return next(iter(selected_targets)), "tree_edge"
    if review.type == "cross_link":
        subject_id = next(iter(review.subject_ids), solved.root_id)
        return subject_id, "cross_link"
    subject_id = next(iter(review.subject_ids), solved.root_id)
    return subject_id, "node"


def _enrich_result(
    state: CPlusState,
) -> MindMapResult:
    solved = state["solve_response"]
    normalized = state["normalized_graph"]
    votes_by_pair = state.get("parent_votes", {})
    units = state["content_units"]
    node_by_id = {node.id: node for node in solved.nodes}
    parent_by_child = {
        edge.target: edge.source
        for edge in solved.tree_edges
    }
    graph = nx.DiGraph()
    graph.add_nodes_from(node_by_id)
    graph.add_edges_from(
        (edge.source, edge.target)
        for edge in solved.tree_edges
    )
    depths = (
        nx.single_source_shortest_path_length(graph, solved.root_id)
        if solved.root_id in graph
        else {}
    )

    risk_by_node: dict[str, float] = defaultdict(float)
    for review in solved.review_items:
        subject_id, _ = _review_subject(review, solved)
        risk_by_node[subject_id] = max(
            risk_by_node[subject_id],
            review.risk_score,
        )

    nodes = [
        MindMapNode(
            **node.model_dump(),
            depth=int(depths.get(node.id, 0)),
            parent_id=parent_by_child.get(node.id),
            status="needs_review" if risk_by_node[node.id] else "accepted",
            risk_score=round(risk_by_node[node.id], 4),
        )
        for node in solved.nodes
    ]
    tree_edges = [
        MindMapTreeEdge(
            **edge.model_dump(),
            classification=next(
                (
                    candidate.classification
                    for candidate in normalized.parent_candidates
                    if candidate.parent_id == edge.source
                    and candidate.child_id == edge.target
                ),
                "uncertain",
            ),
            verifier_votes=votes_by_pair.get((edge.source, edge.target), []),
        )
        for edge in solved.tree_edges
    ]
    cross_links = [
        MindMapCrossLink(**edge.model_dump(), verifier_votes=[])
        for edge in solved.cross_links
    ]

    review_views: list[ReviewItemView] = []
    for review in solved.review_items:
        subject_id, subject_type = _review_subject(review, solved)
        evidence_unit_ids: set[str] = set()
        review_votes = []
        preview_nodes = []
        for member_id in review.subject_ids:
            node = node_by_id.get(member_id)
            if node:
                preview_nodes.append(
                    {"id": node.id, "name": node.name, "role": node.role}
                )
                evidence_unit_ids.update(node.support_unit_ids)
                evidence_unit_ids.update(
                    item.unit_id or item.chunk_id
                    for item in node.evidence
                    if item.unit_id or item.chunk_id
                )
        for edge in tree_edges:
            if edge.source in review.subject_ids or edge.target in review.subject_ids:
                review_votes.extend(edge.verifier_votes)
        review_views.append(
            ReviewItemView(
                **review.model_dump(),
                subject_id=subject_id,
                subject_type=subject_type,
                evidence_unit_ids=sorted(evidence_unit_ids),
                model_votes=review_votes,
                local_subtree_preview={
                    "nodes": preview_nodes,
                    "tree_edges": [
                        edge.model_dump(mode="json")
                        for edge in tree_edges
                        if edge.source in review.subject_ids
                        or edge.target in review.subject_ids
                    ],
                },
            )
        )

    covered, weighted_coverage, branch_coverage = coverage_statistics(
        units,
        solved.nodes,
    )
    units = [
        unit
        if unit.status == "rejected"
        else unit.model_copy(update={"status": "covered"})
        if unit.id in covered
        else unit.model_copy(update={"status": "deferred"})
        if unit.status == "covered"
        else unit
        for unit in units
    ]
    eligible_units = [
        unit
        for unit in units
        if unit.status != "rejected" and unit.importance > 0.15
    ]
    abstract_nodes = [
        node
        for node in solved.nodes
        if node.origin in {"abstractive", "structural"}
    ]
    supported_abstract = [
        node
        for node in abstract_nodes
        if len(
            {
                *node.support_unit_ids,
                *[
                    item.unit_id or item.chunk_id
                    for item in node.evidence
                    if item.unit_id or item.chunk_id
                ],
            }
        )
        >= 2
    ]
    abstraction_rate = (
        len(supported_abstract) / len(abstract_nodes)
        if abstract_nodes
        else 1
    )
    direct_parent_confidence = (
        sum(edge.score for edge in solved.tree_edges) / len(solved.tree_edges)
        if solved.tree_edges
        else 1
    )
    required_coverage = 0.86 if state["mode"] == "precision" else 0.78
    topology_limits = (
        STRICT_PAGE_TOPOLOGY_LIMITS
        if state.get("strict_page_topology", False)
        else DEFAULT_TOPOLOGY_LIMITS
    )
    gate_failures = quality_gate_failures(
        topology_valid=solved.quality.topology_valid,
        evidence_coverage=solved.quality.evidence_coverage,
        provisional_edge_count=solved.quality.provisional_edge_count,
        weighted_coverage=weighted_coverage,
        required_coverage=required_coverage,
        nodes=nodes,
        edge_classifications=[
            edge.classification for edge in tree_edges
        ],
        edge_evidence=[edge.evidence for edge in tree_edges],
        pending_review_count=sum(
            review.status == "pending" for review in review_views
        ),
        degraded_components=state.get("degraded_components", []),
        max_nodes=topology_limits.max_active_nodes,
    )
    quality_gate = not gate_failures
    quality_warnings = list(
        dict.fromkeys(
            [
                *solved.quality.warnings,
                *[
                    f"质量门未通过：{reason}"
                    for reason in gate_failures
                ],
            ]
        )
    )
    base_quality = solved.quality.model_dump()
    base_quality["warnings"] = quality_warnings
    quality = MindMapQualityReport(
        **base_quality,
        weighted_content_coverage=weighted_coverage,
        direct_parent_confidence=round(direct_parent_confidence, 4),
        abstraction_support_rate=round(abstraction_rate, 4),
        review_item_count=len(review_views),
        structural_gate_passed=solved.quality.topology_valid,
        publish_gate_passed=quality_gate,
        quality_gate_passed=quality_gate,
        coverage=CoverageSummary(
            total_units=len(eligible_units),
            covered_units=sum(1 for unit in eligible_units if unit.id in covered),
            weighted_coverage=weighted_coverage,
            uncovered_unit_ids=[
                unit.id for unit in eligible_units if unit.id not in covered
            ],
            branch_coverage=branch_coverage,
        ),
    )
    decisions = _create_decision_records(
        state["run_id"],
        normalized,
        solved,
    )
    return MindMapResult(
        task_id=state["task_id"],
        run_id=state["run_id"],
        graph_version=0,
        document=state["document"],
        chunks=state["chunks"],
        content_units=units,
        root_id=solved.root_id,
        nodes=nodes,
        tree_edges=tree_edges,
        cross_links=cross_links,
        assets=state.get("assets", []),
        quality_report=quality,
        review_items=review_views,
        decision_records=decisions,
        mode=state["mode"],
        extraction_mode=state["extraction_mode"],
        model_selection=state["model_selection"],
        degraded_components=state.get("degraded_components", []),
        warnings=list(
            dict.fromkeys(
                [
                    *state.get("warnings", []),
                    *solved.warnings,
                    *quality.warnings,
                ]
            )
        ),
        solver_status=solved.solver_status,
    )


def create_cplus_supervisor(progress: ProgressCallback):
    async def parse_node(state: CPlusState):
        await progress("parse", 8, "正在解析文档结构")
        document = await asyncio.to_thread(
            parse_document,
            Path(state["file_path"]),
            state["filename"],
        )
        state["blackboard"].update_run(
            state["run_id"],
            document_id=document.document_id,
            stage="parse",
        )
        state["blackboard"].checkpoint(
            state["run_id"],
            "parse",
            document,
        )
        return {
            "document": document,
            "warnings": [
                *state.get("warnings", []),
                *document.warnings,
            ],
        }

    async def ledger_node(state: CPlusState):
        await progress("ledger", 18, "正在建立文本与视觉内容单元账本")
        document = state["document"]
        effective_document = document
        file_path = Path(state["file_path"])
        pdf_mode = settings.pdf_transcription_mode.casefold()
        strict_pdf_knowledge = bool(
            state["use_ai"]
            and file_path.suffix.lower() == ".pdf"
            and pdf_mode == "vision_nodes_strict"
        )
        strict_pdf_transcription = bool(
            state["use_ai"]
            and file_path.suffix.lower() == ".pdf"
            and pdf_mode == "vision_strict"
        )
        strict_pdf_vision = (
            strict_pdf_knowledge or strict_pdf_transcription
        )

        async def render():
            if file_path.suffix.lower() not in {".pdf", ".pptx"}:
                return None
            return await asyncio.to_thread(
                render_document,
                file_path,
                state["filename"],
                settings.mindmap_data_dir,
                settings.asset_public_base_url,
                settings.asset_access_token,
                max_pages=(
                    None
                    if strict_pdf_vision
                    else settings.vision_max_pages
                ),
                pdf_dpi=(
                    settings.pdf_transcription_dpi
                    if strict_pdf_vision
                    else 144
                ),
            )

        rendered = await render()
        assets: list[VisualAsset] = []
        warnings = list(state.get("warnings", []))
        degraded = list(state.get("degraded_components", []))
        knowledge_units: list[ContentUnit] | None = None
        page_node_candidates: list[NodeCandidateIn] = []
        if strict_pdf_vision:
            if rendered and rendered.pages:
                manifest = (
                    state["blackboard"].load_run_manifest(
                        state["task_id"]
                    )
                    or {}
                )
                source_sha256 = str(
                    manifest.get("source_sha256")
                    or await asyncio.to_thread(
                        _sha256_file,
                        file_path,
                    )
                )
                if strict_pdf_knowledge:
                    knowledge = await extract_pdf_page_knowledge(
                        document=document,
                        rendered=rendered,
                        runtime=state["vision_runtime"],
                        data_root=settings.mindmap_data_dir,
                        checkpoint_store=state["blackboard"],
                        run_id=state["run_id"],
                        source_sha256=source_sha256,
                        prompt_version=(
                            settings.pdf_page_knowledge_prompt_version
                        ),
                        render_dpi=settings.pdf_transcription_dpi,
                        min_confidence=(
                            settings.pdf_transcription_min_confidence
                        ),
                        concurrency=(
                            settings.pdf_transcription_concurrency
                        ),
                        max_page_attempts=(
                            settings.pdf_transcription_max_attempts
                        ),
                        extraction_profile=(
                            settings.pdf_page_extraction_mode
                        ),
                    )
                    effective_document = knowledge.document
                    knowledge_units = list(knowledge.content_units)
                    page_node_candidates = list(
                        knowledge.node_candidates
                    )
                    warnings.extend(knowledge.warnings)
                    if (
                        not knowledge.complete
                        or knowledge.degraded_pages
                    ):
                        degraded.append("pdf_page_knowledge")
                else:
                    transcription = await transcribe_pdf_pages(
                        document=document,
                        rendered=rendered,
                        runtime=state["vision_runtime"],
                        data_root=settings.mindmap_data_dir,
                        checkpoint_store=state["blackboard"],
                        run_id=state["run_id"],
                        source_sha256=source_sha256,
                        prompt_version=(
                            settings.pdf_page_transcription_prompt_version
                        ),
                        render_dpi=settings.pdf_transcription_dpi,
                        min_confidence=(
                            settings.pdf_transcription_min_confidence
                        ),
                        concurrency=(
                            settings.pdf_transcription_concurrency
                        ),
                        max_page_attempts=(
                            settings.pdf_transcription_max_attempts
                        ),
                    )
                    effective_document = transcription.document
                    warnings.extend(transcription.warnings)
                    if not transcription.complete:
                        degraded.append("pdf_page_transcription")
            else:
                degraded_component = (
                    "pdf_page_knowledge"
                    if strict_pdf_knowledge
                    else "pdf_page_transcription"
                )
                degraded_marker = (
                    PDF_KNOWLEDGE_DEGRADED
                    if strict_pdf_knowledge
                    else PDF_TRANSCRIPTION_DEGRADED
                )
                operation = (
                    "严格页面知识节点抽取"
                    if strict_pdf_knowledge
                    else "严格视觉转录"
                )
                warning = (
                    f"{degraded_marker} "
                    f"PDF 页面未成功渲染，{operation}没有可用输入。"
                )
                effective_document = document.model_copy(
                    update={
                        "blocks": [],
                        "warnings": list(
                            dict.fromkeys(
                                [*document.warnings, warning]
                            )
                        ),
                    }
                )
                warnings.append(warning)
                degraded.append(degraded_component)

        chunks = await asyncio.to_thread(
            chunk_document,
            effective_document,
            settings.max_chunk_chars,
            settings.chunk_overlap_chars,
        )
        units = (
            list(knowledge_units)
            if knowledge_units is not None
            else build_content_units(effective_document, chunks, [])
        )
        if rendered:
            page_assets = _pages_as_assets(rendered)
            native_assets = list(rendered.native_visuals)
            if strict_pdf_knowledge:
                assets = [*page_assets, *native_assets]
                native_units = build_content_units(
                    effective_document,
                    [],
                    native_assets,
                )
                units = _merge_content_units(units, native_units)
            else:
                units = build_content_units(
                    effective_document,
                    chunks,
                    native_assets,
                )
                (
                    cropped_assets,
                    visual_units,
                    visual_used_model,
                    visual_warnings,
                ) = await analyze_visual_pages(
                    document_id=effective_document.document_id,
                    rendered=rendered,
                    text_units=[
                        unit
                        for unit in units
                        if unit.kind == "text"
                    ],
                    runtime=state["vision_runtime"],
                    data_root=settings.mindmap_data_dir,
                    max_pages=settings.vision_max_pages,
                    public_base_url=settings.asset_public_base_url,
                    asset_token=settings.asset_access_token,
                )
                assets = [*page_assets, *native_assets, *cropped_assets]
                units = _merge_content_units(units, visual_units)
                warnings.extend(visual_warnings)
                if rendered.pages and not visual_used_model:
                    degraded.append("visual_understanding_model")
            warnings.extend(rendered.warnings)
            degraded.extend(
                _render_warning_degraded_components(rendered.warnings)
            )
        degraded = list(dict.fromkeys(degraded))
        state["blackboard"].save_content_units(state["run_id"], units)
        state["blackboard"].checkpoint(
            state["run_id"],
            "ledger",
            {
                "chunks": chunks,
                "assets": assets,
                "content_units": units,
                "page_node_candidates": page_node_candidates,
            },
        )
        return {
            "document": effective_document,
            "chunks": chunks,
            "assets": assets,
            "content_units": units,
            "page_node_candidates": page_node_candidates,
            "strict_page_topology": strict_pdf_knowledge,
            "warnings": warnings,
            "degraded_components": degraded,
        }

    async def theme_node(state: CPlusState):
        await progress("themes", 28, "正在生成全局主题与一级分支")
        planning_units, seed_unit_projection = _build_planning_projection(
            state["content_units"],
            state.get("page_node_candidates", []),
        )
        planning_unit_node_weights = _planning_unit_node_weights(
            planning_units,
            state.get("page_node_candidates", []),
            seed_unit_projection,
        )
        plan, used_model, warnings = await synthesize_themes(
            state["document"],
            planning_units,
            state["generator_runtime"],
        )
        state["blackboard"].checkpoint(state["run_id"], "themes", plan)
        degraded = list(state.get("degraded_components", []))
        if not used_model:
            degraded.append("global_theme_model")
        return {
            "planning_content_units": planning_units,
            "seed_unit_projection": seed_unit_projection,
            "planning_unit_node_weights": planning_unit_node_weights,
            "theme_plan": plan,
            "warnings": [*state.get("warnings", []), *warnings],
            "degraded_components": degraded,
        }

    async def branch_plan_node(state: CPlusState):
        await progress("branch_plan", 35, "正在规划递归分支团队")
        strict_page_topology = state.get("strict_page_topology", False)
        plans = build_branch_plans(
            state["theme_plan"],
            state.get("planning_content_units", state["content_units"]),
            unit_node_weights=(
                state.get("planning_unit_node_weights", {})
                if strict_page_topology
                else None
            ),
            max_node_weight_per_leaf=(
                STRICT_PAGE_TOPOLOGY_LIMITS.max_node_fanout
                if strict_page_topology
                else None
            ),
        )
        state["blackboard"].checkpoint(
            state["run_id"],
            "branch_plan",
            plans,
        )
        return {"branch_plans": plans}

    async def branch_team_node(state: CPlusState):
        await progress("branches", 42, "正在并行运行分支团队")
        results = await run_branch_teams(
            state["branch_plans"],
            state.get("planning_content_units", state["content_units"]),
            state["chunks"],
            state["generator_runtime"],
            concurrency=settings.extraction_concurrency,
            seed_nodes=state.get("page_node_candidates", []),
            seed_unit_projection=state.get("seed_unit_projection", {}),
        )
        warnings = list(state.get("warnings", []))
        warnings.extend(
            warning
            for result in results
            for warning in result.warnings
        )
        used_count = sum(1 for result in results if result.used_model)
        leaf_count = sum(1 for plan in state["branch_plans"] if plan.leaf)
        if used_count == leaf_count and leaf_count:
            extraction_mode = state["generator_runtime"].provider
        elif used_count:
            extraction_mode = "mixed"
        else:
            extraction_mode = "heuristic"
        degraded = list(state.get("degraded_components", []))
        if used_count < leaf_count:
            degraded.append("branch_extraction_model")
        state["blackboard"].checkpoint(
            state["run_id"],
            "branches",
            results,
        )
        return {
            "branch_results": results,
            "extraction_mode": extraction_mode,
            "warnings": warnings,
            "degraded_components": degraded,
        }

    async def merge_audit_node(state: CPlusState):
        await progress("merge_audit", 60, "正在合并候选并审计内容覆盖")
        base_nodes = theme_nodes(
            state["theme_plan"],
            state["branch_plans"],
        )
        branch_nodes = [
            node
            for result in state["branch_results"]
            for node in result.nodes
        ]
        nodes = canonicalize_semantic_duplicates([*base_nodes, *branch_nodes])
        nodes = fuse_visual_media(nodes, state["content_units"])
        updated_units, additions, coverage_warnings = audit_coverage(
            state["content_units"],
            nodes,
            state["branch_plans"],
        )
        nodes = canonicalize_semantic_duplicates([*nodes, *additions])
        local_parents = [
            candidate
            for result in state["branch_results"]
            for candidate in result.parent_candidates
        ]
        parents = build_global_parent_candidates(
            state["theme_plan"],
            state["branch_plans"],
            nodes,
            local_parents,
        )
        cross_links = [
            candidate
            for result in state["branch_results"]
            for candidate in result.cross_links
        ]
        state["blackboard"].save_content_units(state["run_id"], updated_units)
        state["blackboard"].save_node_claims(state["run_id"], nodes)
        state["blackboard"].save_parent_candidates(state["run_id"], parents)
        state["blackboard"].save_cross_link_candidates(
            state["run_id"],
            cross_links,
        )
        state["blackboard"].checkpoint(
            state["run_id"],
            "merge_audit",
            {
                "nodes": nodes,
                "parents": parents,
                "cross_links": cross_links,
            },
        )
        return {
            "content_units": updated_units,
            "node_candidates": nodes,
            "parent_candidates": parents,
            "cross_link_candidates": cross_links,
            "warnings": [
                *state.get("warnings", []),
                *coverage_warnings,
            ],
        }

    async def normalize_node(state: CPlusState):
        await progress("normalize", 70, "正在归一节点并召回 Top-k 父候选")
        normalized = normalize_graph(
            NormalizeRequest(
                document_id=state["document"].document_id,
                document_title=state["document"].title,
                nodes=state["node_candidates"],
                parent_candidates=state["parent_candidates"],
                cross_links=state["cross_link_candidates"],
                max_parents_per_node=8,
            )
        )
        state["blackboard"].save_node_claims(
            state["run_id"],
            normalized.nodes,
        )
        state["blackboard"].save_parent_candidates(
            state["run_id"],
            normalized.parent_candidates,
        )
        state["blackboard"].checkpoint(
            state["run_id"],
            "normalize",
            normalized,
        )
        return {
            "normalized_graph": normalized,
            "warnings": [
                *state.get("warnings", []),
                *normalized.warnings,
            ],
        }

    async def verify_node(state: CPlusState):
        await progress("verify", 78, "正在独立校验竞争父边")
        verification = await verify_parent_candidates(
            state["normalized_graph"],
            verifier=state["verifier_runtime"],
            second_verifier=state.get("second_verifier_runtime"),
            arbiter=state.get("arbiter_runtime"),
            mode=state["mode"],
            concurrency=max(settings.extraction_concurrency * 2, 4),
        )
        verified, votes, warnings = verification
        degraded = verifier_degraded_components(
            state.get("degraded_components", []),
            mode=state["mode"],
            verifier=state["verifier_runtime"],
            second_verifier=state.get("second_verifier_runtime"),
            arbiter=state.get("arbiter_runtime"),
            stats=verification.stats,
        )
        state["blackboard"].save_parent_candidates(
            state["run_id"],
            verified.parent_candidates,
        )
        state["blackboard"].checkpoint(
            state["run_id"],
            "verify",
            {
                "graph": verified,
                "votes": {
                    f"{parent}:{child}": [
                        vote.model_dump(mode="json")
                        for vote in pair_votes
                    ]
                    for (parent, child), pair_votes in votes.items()
                },
                "stats": verification.stats,
            },
        )
        return {
            "normalized_graph": verified,
            "parent_votes": votes,
            "parent_verification_stats": verification.stats,
            "warnings": [*state.get("warnings", []), *warnings],
            "degraded_components": degraded,
        }

    async def solve_node(state: CPlusState):
        await progress("solve", 88, "正在求解唯一根、唯一父的合法主树")
        request = SolveRequest(
            graph=state["normalized_graph"],
            mode=state["mode"],
            max_depth=6,
            time_limit_seconds=settings.solver_timeout_seconds,
        )
        solved = (
            solve_topology(
                request,
                limits=STRICT_PAGE_TOPOLOGY_LIMITS,
            )
            if state.get("strict_page_topology", False)
            else solve_topology(request)
        )
        state["blackboard"].checkpoint(
            state["run_id"],
            "solve",
            solved,
        )
        degraded = list(
            dict.fromkeys(state.get("degraded_components", []))
        )
        if (
            solved.solver_status.upper() == "GREEDY_FALLBACK"
            and "topology_solver_fallback" not in degraded
        ):
            degraded.append("topology_solver_fallback")
        return {
            "solve_response": solved,
            "degraded_components": degraded,
        }

    async def finalize_node(state: CPlusState):
        await progress("finalize", 96, "正在生成质量报告与图版本")
        result = _enrich_result(state)
        state["blackboard"].save_decision_records(
            state["run_id"],
            result.decision_records,
        )
        state["blackboard"].save_review_items(
            state["run_id"],
            result.review_items,
        )
        version = state["blackboard"].save_graph_version(
            state["run_id"],
            result,
        )
        result = result.model_copy(
            update={
                "graph_version": version,
                "run_manifest": (
                    state["blackboard"].load_run_manifest(
                        state["task_id"]
                    )
                    or {}
                ),
            }
        )
        state["blackboard"].update_run(
            state["run_id"],
            status="completed",
            stage="complete",
            degraded_components=result.degraded_components,
        )
        await progress("complete", 100, "思维导图已生成")
        return {"result": result}

    builder = StateGraph(CPlusState)
    builder.add_node("parse", parse_node)
    builder.add_node("ledger", ledger_node)
    builder.add_node("themes", theme_node)
    builder.add_node("branch_plan", branch_plan_node)
    builder.add_node("branches", branch_team_node)
    builder.add_node("merge_audit", merge_audit_node)
    builder.add_node("normalize", normalize_node)
    builder.add_node("verify", verify_node)
    builder.add_node("solve", solve_node)
    builder.add_node("finalize", finalize_node)
    builder.add_edge(START, "parse")
    builder.add_edge("parse", "ledger")
    builder.add_edge("ledger", "themes")
    builder.add_edge("themes", "branch_plan")
    builder.add_edge("branch_plan", "branches")
    builder.add_edge("branches", "merge_audit")
    builder.add_edge("merge_audit", "normalize")
    builder.add_edge("normalize", "verify")
    builder.add_edge("verify", "solve")
    builder.add_edge("solve", "finalize")
    builder.add_edge("finalize", END)
    return builder.compile()


async def run_cplus_pipeline(
    *,
    task_id: str,
    file_path: Path,
    filename: str,
    model: str,
    provider: str,
    mode: RunMode,
    use_ai: bool,
    progress: ProgressCallback,
    blackboard: SQLiteBlackboard,
) -> MindMapResult:
    run_id = f"run_{uuid.uuid4().hex[:16]}"
    run_id = blackboard.start_run(
        run_id=run_id,
        task_id=task_id,
        mode=mode,
    )

    async def tracked_progress(
        stage: str,
        value: int,
        message: str,
    ) -> None:
        set_model_call_stage(stage)
        await progress(stage, value, message)

    call_context = ModelCallContext(
        run_id=run_id,
        recorder=blackboard.record_model_call,
        role="cplus_pipeline",
    )
    try:
        with model_call_context(call_context):
            await tracked_progress(
                "model_check",
                3,
                "正在准备生成、校验和仲裁模型",
            )
            (
                generator,
                verifier,
                vision,
                second,
                arbiter,
                selection,
                runtime_warnings,
            ) = await build_role_runtimes(
                provider=provider,
                model=model,
                mode=mode,
                use_ai=use_ai,
            )
            supervisor = create_cplus_supervisor(tracked_progress)
            state = await supervisor.ainvoke(
                {
                    "task_id": task_id,
                    "run_id": run_id,
                    "file_path": str(file_path),
                    "filename": filename,
                    "mode": mode,
                    "use_ai": use_ai,
                    "generator_runtime": generator,
                    "verifier_runtime": verifier,
                    "vision_runtime": vision,
                    "second_verifier_runtime": second,
                    "arbiter_runtime": arbiter,
                    "model_selection": selection,
                    "blackboard": blackboard,
                    "warnings": runtime_warnings,
                    "degraded_components": [],
                }
            )
    except Exception:
        blackboard.update_run(run_id, status="failed", stage="failed")
        raise
    return state["result"]
