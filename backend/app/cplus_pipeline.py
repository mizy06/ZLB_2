from __future__ import annotations

import asyncio
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Awaitable, Callable, TypedDict

import networkx as nx
from langgraph.graph import END, START, StateGraph

from .agents import (
    BranchTeamResult,
    RoleRuntime,
    ThemePlanOutput,
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
from .kimi_provider import KimiClient, OpenAICompatibleClient
from .blackboard import SQLiteBlackboard, utc_now
from .chunking import chunk_document
from .config import settings
from .document_parser import parse_document
from .mindmap_engine.normalize import normalize_graph
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
from .mindmap_engine.topology import solve_topology
from .mindmap_engine.visuals import render_document
from .schemas import Chunk, ParsedDocument
from .visual_analysis import analyze_visual_pages


ProgressCallback = Callable[[str, int, str], Awaitable[None]]


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
    theme_plan: ThemePlanOutput
    branch_plans: list[BranchPlan]
    branch_results: list[BranchTeamResult]
    node_candidates: list[NodeCandidateIn]
    parent_candidates: list[ParentCandidateIn]
    cross_link_candidates: list[CrossLinkCandidateIn]
    normalized_graph: NormalizedGraph
    parent_votes: dict
    solve_response: SolveResponse
    extraction_mode: str
    warnings: list[str]
    degraded_components: list[str]
    result: MindMapResult


def _client(provider: str) -> OpenAICompatibleClient:
    if provider != "kimi":
        raise ValueError(f"Unsupported provider: {provider}")
    return KimiClient(settings)


async def _runtime(
    provider: str,
    model: str,
    use_ai: bool,
) -> RoleRuntime:
    client = _client(provider)
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
    if provider != "kimi":
        raise ValueError(f"Unsupported provider: {provider}")
    generator_task = _runtime("kimi", model, use_ai)
    verifier_task = _runtime("kimi", model, use_ai)
    vision_task = _runtime("kimi", model, use_ai)
    generator, verifier, vision = await asyncio.gather(
        generator_task,
        verifier_task,
        vision_task,
    )

    warnings: list[str] = []

    second: RoleRuntime | None = None
    arbiter: RoleRuntime | None = None
    if mode == "precision":
        second, arbiter = await asyncio.gather(
            _runtime("kimi", model, use_ai),
            _runtime("kimi", model, use_ai),
        )

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
        for subject_id in review.subject_ids:
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
                "direct_parent",
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
        evidence_unit_ids: set[str] = set()
        review_votes = []
        preview_nodes = []
        for subject_id in review.subject_ids:
            node = node_by_id.get(subject_id)
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
        if len(node.support_unit_ids) + len(node.evidence) >= 2
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
    quality_gate = (
        solved.quality.topology_valid
        and solved.quality.evidence_coverage == 1
        and solved.quality.provisional_edge_count == 0
        and weighted_coverage >= required_coverage
    )
    quality = MindMapQualityReport(
        **solved.quality.model_dump(),
        weighted_content_coverage=weighted_coverage,
        direct_parent_confidence=round(direct_parent_confidence, 4),
        abstraction_support_rate=round(abstraction_rate, 4),
        review_item_count=len(review_views),
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
        return {"document": document}

    async def ledger_node(state: CPlusState):
        await progress("ledger", 18, "正在建立文本与视觉内容单元账本")
        document = state["document"]
        file_path = Path(state["file_path"])
        chunks_task = asyncio.to_thread(
            chunk_document,
            document,
            settings.max_chunk_chars,
            settings.chunk_overlap_chars,
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
            )

        chunks, rendered = await asyncio.gather(chunks_task, render())
        assets: list[VisualAsset] = []
        warnings = list(state.get("warnings", []))
        degraded = list(state.get("degraded_components", []))
        units = build_content_units(document, chunks, [])
        if rendered:
            page_assets = _pages_as_assets(rendered)
            native_assets = list(rendered.native_visuals)
            units = build_content_units(document, chunks, native_assets)
            (
                cropped_assets,
                visual_units,
                visual_used_model,
                visual_warnings,
            ) = await analyze_visual_pages(
                document_id=document.document_id,
                rendered=rendered,
                text_units=[unit for unit in units if unit.kind == "text"],
                runtime=state["vision_runtime"],
                data_root=settings.mindmap_data_dir,
                max_pages=settings.vision_max_pages,
                public_base_url=settings.asset_public_base_url,
                asset_token=settings.asset_access_token,
            )
            assets = [*page_assets, *native_assets, *cropped_assets]
            units.extend(visual_units)
            warnings.extend(rendered.warnings)
            warnings.extend(visual_warnings)
            if rendered.warnings:
                degraded.append("visual_rendering")
            if rendered.pages and not visual_used_model:
                degraded.append("visual_understanding_model")
        state["blackboard"].save_content_units(state["run_id"], units)
        state["blackboard"].checkpoint(
            state["run_id"],
            "ledger",
            {
                "chunks": chunks,
                "assets": assets,
                "content_units": units,
            },
        )
        return {
            "chunks": chunks,
            "assets": assets,
            "content_units": units,
            "warnings": warnings,
            "degraded_components": degraded,
        }

    async def theme_node(state: CPlusState):
        await progress("themes", 28, "正在生成全局主题与一级分支")
        plan, used_model, warnings = await synthesize_themes(
            state["document"],
            state["content_units"],
            state["generator_runtime"],
        )
        state["blackboard"].checkpoint(state["run_id"], "themes", plan)
        degraded = list(state.get("degraded_components", []))
        if not used_model:
            degraded.append("global_theme_model")
        return {
            "theme_plan": plan,
            "warnings": [*state.get("warnings", []), *warnings],
            "degraded_components": degraded,
        }

    async def branch_plan_node(state: CPlusState):
        await progress("branch_plan", 35, "正在规划递归分支团队")
        plans = build_branch_plans(
            state["theme_plan"],
            state["content_units"],
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
            state["content_units"],
            state["chunks"],
            state["generator_runtime"],
            concurrency=settings.extraction_concurrency,
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
        verified, votes, warnings = await verify_parent_candidates(
            state["normalized_graph"],
            verifier=state["verifier_runtime"],
            second_verifier=state.get("second_verifier_runtime"),
            arbiter=state.get("arbiter_runtime"),
            mode=state["mode"],
            concurrency=max(settings.extraction_concurrency * 2, 4),
        )
        degraded = list(state.get("degraded_components", []))
        if not state["verifier_runtime"].available:
            degraded.append("independent_parent_verifier")
        if state["mode"] == "precision" and (
            not state.get("second_verifier_runtime")
            or not state["second_verifier_runtime"].available
        ):
            degraded.append("second_parent_verifier")
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
            },
        )
        return {
            "normalized_graph": verified,
            "parent_votes": votes,
            "warnings": [*state.get("warnings", []), *warnings],
            "degraded_components": degraded,
        }

    async def solve_node(state: CPlusState):
        await progress("solve", 88, "正在求解唯一根、唯一父的合法主树")
        solved = solve_topology(
            SolveRequest(
                graph=state["normalized_graph"],
                mode=state["mode"],
                max_depth=6,
                time_limit_seconds=settings.solver_timeout_seconds,
            )
        )
        state["blackboard"].checkpoint(
            state["run_id"],
            "solve",
            solved,
        )
        return {"solve_response": solved}

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
        result = result.model_copy(update={"graph_version": version})
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
    blackboard.start_run(
        run_id=run_id,
        task_id=task_id,
        mode=mode,
    )
    await progress("model_check", 3, "正在准备生成、校验和仲裁模型")
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
    supervisor = create_cplus_supervisor(progress)
    try:
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
