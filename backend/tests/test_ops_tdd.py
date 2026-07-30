from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import httpx

from backend.app.architecture_schemas import (
    ContentUnit,
    CoverageSummary,
    JobView,
    MindMapCrossLink,
    MindMapNode,
    MindMapQualityReport,
    MindMapResult,
    MindMapTreeEdge,
    ModelSelection,
    ReviewItemView,
    ReviewResolutionRequest,
)
from backend.app.blackboard import SQLiteBlackboard
from backend.app.config import Settings
from backend.app.mindmap_engine.schemas import EvidenceRef, NodeCandidateIn
from backend.app.mindmap_engine.validate import build_quality_report
from backend.app.model_provider import (
    ModelCallContext,
    ModelProviderError,
    OpenAICompatibleClient,
    model_call_scope,
    model_call_context,
)
from backend.app.review_service import resolve_review_item
from backend.app.schemas import ParsedDocument


def _test_settings(root: Path) -> Settings:
    return Settings(
        qwen_api_key="test-key",
        qwen_base_url="https://provider.invalid/v1",
        qwen_model="qwen3.8-max-preview",
        qwen_temperature=0.1,
        qwen_secret_source="test",
        qwen_secret_error="",
        workspace_name="test",
        workspace_id="",
        vision_max_pages=24,
        external_engine_token="",
        asset_public_base_url="",
        asset_access_token="",
        mindmap_data_dir=root,
        blackboard_path=root / "blackboard.sqlite3",
    )


class SequencedAsyncClient:
    def __init__(self, responses: list[httpx.Response]):
        self.responses = list(responses)
        self.calls = 0

    async def post(self, *args, **kwargs) -> httpx.Response:
        self.calls += 1
        if not self.responses:
            raise AssertionError("unexpected provider request")
        return self.responses.pop(0)

    async def get(self, *args, **kwargs) -> httpx.Response:
        return await self.post(*args, **kwargs)


def provider_response(
    status: int,
    payload: dict,
    *,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    return httpx.Response(
        status,
        json=payload,
        headers=headers,
        request=httpx.Request("POST", "https://provider.invalid/v1/chat/completions"),
    )


def chat_success(content: str = '{"ok": true}') -> httpx.Response:
    return provider_response(
        200,
        {"choices": [{"message": {"content": content}}]},
    )


class ProviderReliabilityTDDTests(unittest.IsolatedAsyncioTestCase):
    async def test_retry_after_is_honored_and_every_attempt_is_recorded(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fake = SequencedAsyncClient(
                [
                    provider_response(
                        429,
                        {"error": {"message": "rate limited"}},
                        headers={"Retry-After": "2"},
                    ),
                    chat_success(),
                ]
            )
            sleeps: list[float] = []
            records: list[dict] = []

            async def fake_sleep(delay: float) -> None:
                sleeps.append(delay)

            client = OpenAICompatibleClient(
                settings=_test_settings(Path(temp_dir)),
                api_key="test-key",
                base_url="https://provider.invalid/v1",
                provider_name="retry-provider",
                api_key_env_name="TEST_KEY",
                temperature=0.1,
                http_client=fake,
                max_attempts=3,
                retry_sleep=fake_sleep,
                attempt_recorder=records.append,
            )
            payload = await client.complete_json(
                model="test-model",
                system_prompt="system",
                user_prompt="user",
            )

        self.assertEqual(payload, {"ok": True})
        self.assertEqual(fake.calls, 2)
        self.assertEqual(sleeps, [2.0])
        self.assertEqual(
            [record["status"] for record in records],
            ["retryable_error", "success"],
        )
        self.assertEqual([record["attempt"] for record in records], [1, 2])

    async def test_permanent_auth_error_opens_circuit_without_second_request(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            secret = "PRIVATE-SOURCE-TEXT test-key"
            fake = SequencedAsyncClient(
                [
                    provider_response(
                        401,
                        {
                            "error": {
                                "message": secret,
                                "code": "InvalidApiKey",
                            }
                        },
                    )
                ]
            )
            client = OpenAICompatibleClient(
                settings=_test_settings(Path(temp_dir)),
                api_key="test-key",
                base_url="https://provider.invalid/v1",
                provider_name="auth-provider",
                api_key_env_name="TEST_KEY",
                temperature=0.1,
                http_client=fake,
                max_attempts=3,
            )

            with self.assertRaisesRegex(
                ModelProviderError,
                r"HTTP 401.*InvalidApiKey",
            ) as first_error:
                await client.complete_json(
                    model="test-model",
                    system_prompt="system",
                    user_prompt="first",
                )
            self.assertNotIn(secret, str(first_error.exception))
            with self.assertRaisesRegex(ModelProviderError, "熔断") as circuit_error:
                await client.complete_json(
                    model="test-model",
                    system_prompt="system",
                    user_prompt="second",
                )
            self.assertNotIn(secret, str(circuit_error.exception))

        self.assertEqual(fake.calls, 1)

    async def test_permanent_quota_error_opens_circuit_without_leaking_message(
        self,
    ):
        with tempfile.TemporaryDirectory() as temp_dir:
            secret = "PRIVATE-SOURCE-TEXT test-key"
            fake = SequencedAsyncClient(
                [
                    provider_response(
                        429,
                        {
                            "error": {
                                "message": f"insufficient balance {secret}",
                                "code": "Arrearage",
                            }
                        },
                    )
                ]
            )
            client = OpenAICompatibleClient(
                settings=_test_settings(Path(temp_dir)),
                api_key="test-key",
                base_url="https://provider.invalid/v1",
                provider_name="quota-provider",
                api_key_env_name="TEST_KEY",
                temperature=0.1,
                http_client=fake,
                max_attempts=3,
            )

            with self.assertRaisesRegex(
                ModelProviderError,
                r"HTTP 429.*Arrearage",
            ) as first_error:
                await client.complete_json(
                    model="test-model",
                    system_prompt="system",
                    user_prompt="first",
                )
            self.assertNotIn(secret, str(first_error.exception))
            with self.assertRaisesRegex(ModelProviderError, "熔断") as circuit_error:
                await client.complete_json(
                    model="test-model",
                    system_prompt="system",
                    user_prompt="second",
                )
            self.assertNotIn(secret, str(circuit_error.exception))

        self.assertEqual(fake.calls, 1)

    async def test_non_retryable_400_is_attempted_once(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fake = SequencedAsyncClient(
                [
                    provider_response(
                        400,
                        {"error": {"message": "invalid request"}},
                    )
                ]
            )
            client = OpenAICompatibleClient(
                settings=_test_settings(Path(temp_dir)),
                api_key="test-key",
                base_url="https://provider.invalid/v1",
                provider_name="bad-request-provider",
                api_key_env_name="TEST_KEY",
                temperature=0.1,
                http_client=fake,
                max_attempts=3,
            )
            with self.assertRaisesRegex(ModelProviderError, "HTTP 400"):
                await client.complete_json(
                    model="test-model",
                    system_prompt="system",
                    user_prompt="user",
                )

        self.assertEqual(fake.calls, 1)

    async def test_request_specific_400_does_not_block_the_next_model_call(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fake = SequencedAsyncClient(
                [
                    provider_response(
                        400,
                        {"error": {"message": "prompt is too long"}},
                    ),
                    chat_success('{"recovered": true}'),
                ]
            )
            client = OpenAICompatibleClient(
                settings=_test_settings(Path(temp_dir)),
                api_key="test-key",
                base_url="https://provider.invalid/v1",
                provider_name="request-error-provider",
                api_key_env_name="TEST_KEY",
                temperature=0.1,
                http_client=fake,
                max_attempts=3,
            )

            with self.assertRaisesRegex(ModelProviderError, "HTTP 400"):
                await client.complete_json(
                    model="test-model",
                    system_prompt="system",
                    user_prompt="oversized",
                )
            recovered = await client.complete_json(
                model="test-model",
                system_prompt="system",
                user_prompt="small",
            )

        self.assertEqual(recovered, {"recovered": True})
        self.assertEqual(fake.calls, 2)

    async def test_pipeline_context_persists_actual_attempt_to_blackboard(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            board = SQLiteBlackboard(root / "blackboard.sqlite3")
            board.start_run(
                run_id="run_calls",
                task_id="task_calls",
                mode="standard",
            )
            fake = SequencedAsyncClient([chat_success()])
            client = OpenAICompatibleClient(
                settings=_test_settings(root),
                api_key="test-key",
                base_url="https://context-provider.invalid/v1",
                provider_name="context-provider",
                api_key_env_name="TEST_KEY",
                temperature=0.1,
                http_client=fake,
            )
            with model_call_context(
                ModelCallContext(
                    run_id="run_calls",
                    recorder=board.record_model_call,
                    role="branch_extraction",
                )
            ):
                await client.complete_json(
                    model="test-model",
                    system_prompt="system",
                    user_prompt="user",
                )
            calls = board.list_model_calls("run_calls")

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["role"], "branch_extraction")
        self.assertEqual(calls[0]["status"], "success")

    async def test_nested_model_call_scope_records_branch_and_input_units(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            board = SQLiteBlackboard(root / "blackboard.sqlite3")
            board.start_run(
                run_id="run_scope",
                task_id="task_scope",
                mode="standard",
            )
            client = OpenAICompatibleClient(
                settings=_test_settings(root),
                api_key="test-key",
                base_url="https://scope-provider.invalid/v1",
                provider_name="scope-provider",
                api_key_env_name="TEST_KEY",
                temperature=0.1,
                http_client=SequencedAsyncClient([chat_success()]),
            )
            with model_call_context(
                ModelCallContext(
                    run_id="run_scope",
                    recorder=board.record_model_call,
                    role="branches",
                )
            ):
                with model_call_scope(
                    branch_id="branch-7",
                    input_unit_ids=("u1", "u2"),
                ):
                    await client.complete_json(
                        model="test-model",
                        system_prompt="system",
                        user_prompt="user",
                    )
            calls = board.list_model_calls("run_scope")

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["branch_id"], "branch-7")
        self.assertEqual(calls[0]["input_unit_ids"], ["u1", "u2"])


class BlackboardRecoveryTDDTests(unittest.TestCase):
    def test_checkpoint_round_trip_and_stage_collections_are_replaced(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "blackboard.sqlite3"
            board = SQLiteBlackboard(database)
            board.start_run(
                run_id="run_test",
                task_id="task_test",
                mode="standard",
            )
            board.checkpoint("run_test", "parse", {"pages": 7})
            self.assertEqual(
                board.load_checkpoint("run_test", "parse"),
                {"pages": 7},
            )

            board.save_node_claims(
                "run_test",
                [
                    NodeCandidateIn(temp_id="old", name="旧候选"),
                    NodeCandidateIn(temp_id="keep", name="保留候选"),
                ],
            )
            board.save_node_claims(
                "run_test",
                [NodeCandidateIn(temp_id="keep", name="更新后的候选")],
            )
            with sqlite3.connect(database) as connection:
                rows = connection.execute(
                    "SELECT item_id, payload_json FROM node_claims "
                    "WHERE run_id = ? ORDER BY item_id",
                    ("run_test",),
                ).fetchall()

        self.assertEqual([row[0] for row in rows], ["keep"])
        self.assertEqual(json.loads(rows[0][1])["name"], "更新后的候选")

    def test_model_calls_and_non_terminal_jobs_survive_reopen(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "blackboard.sqlite3"
            board = SQLiteBlackboard(database)
            board.upsert_job(
                task_id="task_running",
                status="running",
                stage="verify",
                progress=78,
                message="正在校验",
                mode="precision",
                source_path="/tmp/source.pdf",
                filename="source.pdf",
                model="test-model",
                provider="qwen",
                use_ai=True,
                owner_id="owner-a",
                manifest={"source_sha256": "abc123"},
            )
            board.start_run(
                run_id="run_running",
                task_id="task_running",
                mode="precision",
            )
            board.record_model_call(
                run_id="run_running",
                item_id="call-1:attempt-1",
                role="parent_verifier",
                status="success",
                provider="qwen",
                model="test-model",
                latency_ms=123,
                input_unit_ids=["u1"],
                details={"attempt": 1},
            )

            reopened = SQLiteBlackboard(database)
            job = reopened.load_job("task_running", owner_id="owner-a")
            calls = reopened.list_model_calls("run_running")

        self.assertIsNotNone(job)
        self.assertEqual(job["status"], "running")
        self.assertEqual(job["progress"], 78)
        self.assertEqual(job["manifest"]["source_sha256"], "abc123")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["details"]["attempt"], 1)

    def test_cancelled_is_a_persistable_job_status(self):
        job = JobView(
            id="cancelled-task",
            status="cancelled",
            stage="cancelled",
            progress=41,
            message="用户已取消",
        )
        self.assertEqual(job.status, "cancelled")


def node(
    node_id: str,
    name: str,
    *,
    depth: int,
    parent_id: str | None,
    origin: str = "explicit",
) -> MindMapNode:
    return MindMapNode(
        id=node_id,
        temp_ids=[node_id],
        name=name,
        type="concept",
        role="concept",
        definition=name,
        aliases=[],
        origin=origin,
        confidence=0.8,
        optional=False,
        activation_score=0.8,
        activation_cost=0,
        is_root_candidate=node_id == "root",
        evidence=[EvidenceRef(unit_id=f"unit-{node_id}", excerpt=name)],
        support_unit_ids=[],
        media_asset_ids=[],
        depth=depth,
        parent_id=parent_id,
    )


def edge(
    source: str,
    target: str,
    *,
    score: float,
    provisional: bool = False,
) -> MindMapTreeEdge:
    return MindMapTreeEdge(
        id=f"edge-{source}-{target}",
        source=source,
        target=target,
        score=score,
        provisional=provisional,
        evidence=[
            EvidenceRef(
                unit_id=f"edge-unit-{source}-{target}",
                excerpt=f"{source}->{target}",
            )
        ],
        classification="uncertain" if provisional else "direct_parent",
    )


def result_with_review(
    *,
    review: ReviewItemView,
    nodes: list[MindMapNode],
    edges: list[MindMapTreeEdge],
    cross_links: list[MindMapCrossLink] | None = None,
) -> MindMapResult:
    return MindMapResult(
        task_id="task_review",
        run_id="run_review",
        graph_version=0,
        document=ParsedDocument(
            document_id="doc",
            filename="source.md",
            file_type="md",
            title="课程",
            blocks=[],
        ),
        chunks=[],
        content_units=[],
        root_id="root",
        nodes=nodes,
        tree_edges=edges,
        cross_links=cross_links or [],
        quality_report=MindMapQualityReport(
            node_count=len(nodes),
            tree_edge_count=len(edges),
            cross_link_count=len(cross_links or []),
            root_count=1,
            orphan_count=0,
            conflict_count=0,
            provisional_edge_count=sum(item.provisional for item in edges),
            evidence_coverage=1,
            topology_valid=True,
            weighted_content_coverage=1,
            direct_parent_confidence=0.8,
            abstraction_support_rate=1,
            review_item_count=1,
            quality_gate_passed=False,
            coverage=CoverageSummary(),
        ),
        review_items=[review],
        decision_records=[],
        mode="standard",
        extraction_mode="heuristic",
        model_selection=ModelSelection(
            generator_provider="heuristic",
            verifier_provider="deterministic",
        ),
    )


class ReviewTransactionTDDTests(unittest.TestCase):
    def save_result(
        self,
        board: SQLiteBlackboard,
        result: MindMapResult,
    ) -> MindMapResult:
        board.start_run(
            run_id=result.run_id,
            task_id=result.task_id,
            mode=result.mode,
        )
        board.save_review_items(result.run_id, result.review_items)
        version = board.save_graph_version(result.run_id, result)
        return result.model_copy(update={"graph_version": version})

    def test_explicit_review_subject_wins_over_tree_membership_order(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            board = SQLiteBlackboard(Path(temp_dir) / "blackboard.sqlite3")
            review = ReviewItemView(
                id="review-provisional",
                type="competing_parent",
                risk_score=1,
                subject_ids=["parent", "child"],
                subject_id="child",
                reason="临时边",
            )
            original = self.save_result(
                board,
                result_with_review(
                    review=review,
                    nodes=[
                        node("root", "课程", depth=0, parent_id=None),
                        node("parent", "父主题", depth=1, parent_id="root"),
                        node("child", "子主题", depth=2, parent_id="parent"),
                    ],
                    edges=[
                        edge("root", "parent", score=0.9),
                        edge("parent", "child", score=0.4, provisional=True),
                    ],
                ),
            )

            updated = resolve_review_item(
                blackboard=board,
                task_id=original.task_id,
                review_id=review.id,
                request=ReviewResolutionRequest(
                    action="rename",
                    label="明确的子主题",
                    expected_graph_version=original.graph_version,
                ),
            )

        names = {item.id: item.name for item in updated.nodes}
        self.assertEqual(names["child"], "明确的子主题")
        self.assertEqual(names["parent"], "父主题")

    def test_stale_graph_version_is_rejected_without_partial_resolution(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            board = SQLiteBlackboard(Path(temp_dir) / "blackboard.sqlite3")
            review = ReviewItemView(
                id="review-rename",
                type="abstract_parent",
                risk_score=0.8,
                subject_ids=["child"],
                subject_id="child",
                reason="名称不明确",
            )
            original = self.save_result(
                board,
                result_with_review(
                    review=review,
                    nodes=[
                        node("root", "课程", depth=0, parent_id=None),
                        node("child", "旧名称", depth=1, parent_id="root"),
                    ],
                    edges=[edge("root", "child", score=0.8)],
                ),
            )

            with self.assertRaisesRegex(ValueError, "版本"):
                resolve_review_item(
                    blackboard=board,
                    task_id=original.task_id,
                    review_id=review.id,
                    request=ReviewResolutionRequest(
                        action="rename",
                        label="新名称",
                        expected_graph_version=original.graph_version + 1,
                    ),
                )

            latest = board.load_latest_result(original.task_id)
            with sqlite3.connect(board.path) as connection:
                status = connection.execute(
                    "SELECT status FROM review_items "
                    "WHERE run_id = ? AND item_id = ?",
                    (original.run_id, review.id),
                ).fetchone()[0]

        self.assertEqual(latest.graph_version, original.graph_version)
        self.assertEqual(status, "pending")

    def test_delete_cleans_cross_links_and_never_fabricates_perfect_edges(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            board = SQLiteBlackboard(Path(temp_dir) / "blackboard.sqlite3")
            review = ReviewItemView(
                id="review-delete",
                type="abstract_parent",
                risk_score=0.9,
                subject_ids=["abstract"],
                subject_id="abstract",
                reason="抽象层级缺少支持",
            )
            original = self.save_result(
                board,
                result_with_review(
                    review=review,
                    nodes=[
                        node("root", "课程", depth=0, parent_id=None),
                        node(
                            "abstract",
                            "薄弱抽象",
                            depth=1,
                            parent_id="root",
                            origin="abstractive",
                        ),
                        node("child", "证据节点", depth=2, parent_id="abstract"),
                    ],
                    edges=[
                        edge("root", "abstract", score=0.7),
                        edge("abstract", "child", score=0.6),
                    ],
                    cross_links=[
                        MindMapCrossLink(
                            id="cross-1",
                            source="abstract",
                            target="child",
                            relation="depends_on",
                            score=0.6,
                            evidence=[],
                        )
                    ],
                ),
            )

            updated = resolve_review_item(
                blackboard=board,
                task_id=original.task_id,
                review_id=review.id,
                request=ReviewResolutionRequest(
                    action="delete",
                    expected_graph_version=original.graph_version,
                ),
            )

        self.assertEqual({item.id for item in updated.nodes}, {"root", "child"})
        self.assertEqual(updated.cross_links, [])
        self.assertEqual(len(updated.tree_edges), 1)
        replacement = updated.tree_edges[0]
        self.assertEqual((replacement.source, replacement.target), ("root", "child"))
        self.assertLess(replacement.score, 1)
        self.assertTrue(replacement.provisional)
        self.assertNotEqual(replacement.classification, "direct_parent")
        self.assertFalse(updated.quality_report.quality_gate_passed)

    def test_rename_rejects_an_unpublishable_fragment_without_partial_write(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            board = SQLiteBlackboard(Path(temp_dir) / "blackboard.sqlite3")
            review = ReviewItemView(
                id="review-invalid-rename",
                type="abstract_parent",
                risk_score=0.8,
                subject_ids=["child"],
                subject_id="child",
                reason="名称不明确",
            )
            original = self.save_result(
                board,
                result_with_review(
                    review=review,
                    nodes=[
                        node("root", "课程", depth=0, parent_id=None),
                        node("child", "旧名称", depth=1, parent_id="root"),
                    ],
                    edges=[edge("root", "child", score=0.8)],
                ),
            )

            with self.assertRaisesRegex(ValueError, "标签|名称"):
                resolve_review_item(
                    blackboard=board,
                    task_id=original.task_id,
                    review_id=review.id,
                    request=ReviewResolutionRequest(
                        action="rename",
                        label="但是",
                        expected_graph_version=original.graph_version,
                    ),
                )

            latest = board.load_latest_result(original.task_id)
            with sqlite3.connect(board.path) as connection:
                status = connection.execute(
                    "SELECT status FROM review_items "
                    "WHERE run_id = ? AND item_id = ?",
                    (original.run_id, review.id),
                ).fetchone()[0]

        self.assertEqual(latest.graph_version, original.graph_version)
        self.assertEqual(status, "pending")
        self.assertEqual(
            next(item.name for item in latest.nodes if item.id == "child"),
            "旧名称",
        )

    def test_rename_rejects_a_duplicate_name_in_the_same_branch(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            board = SQLiteBlackboard(Path(temp_dir) / "blackboard.sqlite3")
            review = ReviewItemView(
                id="review-duplicate-rename",
                type="abstract_parent",
                risk_score=0.8,
                subject_ids=["child"],
                subject_id="child",
                reason="名称不明确",
            )
            original = self.save_result(
                board,
                result_with_review(
                    review=review,
                    nodes=[
                        node("root", "课程", depth=0, parent_id=None),
                        node("child", "旧名称", depth=1, parent_id="root"),
                        node("sibling", "重复主题", depth=1, parent_id="root"),
                    ],
                    edges=[
                        edge("root", "child", score=0.8),
                        edge("root", "sibling", score=0.8),
                    ],
                ),
            )

            with self.assertRaisesRegex(ValueError, "重复|同名"):
                resolve_review_item(
                    blackboard=board,
                    task_id=original.task_id,
                    review_id=review.id,
                    request=ReviewResolutionRequest(
                        action="rename",
                        label="重复主题",
                        expected_graph_version=original.graph_version,
                    ),
                )

            latest = board.load_latest_result(original.task_id)

        self.assertEqual(latest.graph_version, original.graph_version)
        self.assertEqual(
            next(item.name for item in latest.nodes if item.id == "child"),
            "旧名称",
        )

    def test_cross_link_review_cannot_delete_its_source_node(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            board = SQLiteBlackboard(Path(temp_dir) / "blackboard.sqlite3")
            review = ReviewItemView(
                id="review-cross-link",
                type="cross_link",
                risk_score=0.8,
                subject_ids=["source", "target"],
                subject_id="source",
                subject_type="cross_link",
                reason="跨链缺少证据",
            )
            original = self.save_result(
                board,
                result_with_review(
                    review=review,
                    nodes=[
                        node("root", "课程", depth=0, parent_id=None),
                        node("source", "来源概念", depth=1, parent_id="root"),
                        node("target", "目标概念", depth=1, parent_id="root"),
                    ],
                    edges=[
                        edge("root", "source", score=0.8),
                        edge("root", "target", score=0.8),
                    ],
                    cross_links=[
                        MindMapCrossLink(
                            id="cross-source-target",
                            source="source",
                            target="target",
                            relation="depends_on",
                            score=0.7,
                            evidence=[
                                EvidenceRef(
                                    unit_id="unit-source",
                                    excerpt="来源概念依赖目标概念",
                                )
                            ],
                        )
                    ],
                ),
            )

            with self.assertRaisesRegex(ValueError, "复核类型|不支持"):
                resolve_review_item(
                    blackboard=board,
                    task_id=original.task_id,
                    review_id=review.id,
                    request=ReviewResolutionRequest(
                        action="delete",
                        expected_graph_version=original.graph_version,
                    ),
                )

            latest = board.load_latest_result(original.task_id)

        self.assertEqual(
            {item.id for item in latest.nodes},
            {"root", "source", "target"},
        )
        self.assertEqual(latest.graph_version, original.graph_version)

    def test_keep_cannot_certify_a_parent_edge_without_relation_evidence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            board = SQLiteBlackboard(Path(temp_dir) / "blackboard.sqlite3")
            review = ReviewItemView(
                id="review-empty-edge",
                type="competing_parent",
                risk_score=1,
                subject_ids=["root", "child"],
                subject_id="child",
                subject_type="tree_edge",
                reason="临时父边",
            )
            empty_edge = edge(
                "root",
                "child",
                score=0.2,
                provisional=True,
            ).model_copy(
                update={"evidence": [], "classification": "uncertain"}
            )
            original = self.save_result(
                board,
                result_with_review(
                    review=review,
                    nodes=[
                        node("root", "课程", depth=0, parent_id=None),
                        node("child", "子主题", depth=1, parent_id="root"),
                    ],
                    edges=[empty_edge],
                ),
            )

            with self.assertRaisesRegex(ValueError, "证据"):
                resolve_review_item(
                    blackboard=board,
                    task_id=original.task_id,
                    review_id=review.id,
                    request=ReviewResolutionRequest(
                        action="keep",
                        expected_graph_version=original.graph_version,
                    ),
                )

            latest = board.load_latest_result(original.task_id)

        self.assertTrue(latest.tree_edges[0].provisional)
        self.assertEqual(latest.review_items[0].status, "pending")
        self.assertEqual(latest.graph_version, original.graph_version)

    def test_change_parent_requires_a_direct_candidate_with_relation_evidence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            board = SQLiteBlackboard(Path(temp_dir) / "blackboard.sqlite3")
            review = ReviewItemView(
                id="review-change-parent-without-evidence",
                type="competing_parent",
                risk_score=0.9,
                subject_ids=["old-parent", "new-parent", "child"],
                subject_id="child",
                subject_type="tree_edge",
                reason="父节点候选接近",
                alternatives=[
                    {
                        "parent_id": "new-parent",
                        "score": 0.85,
                        "classification": "direct_parent",
                        "evidence": [],
                    }
                ],
            )
            original = self.save_result(
                board,
                result_with_review(
                    review=review,
                    nodes=[
                        node("root", "课程", depth=0, parent_id=None),
                        node(
                            "old-parent",
                            "旧父主题",
                            depth=1,
                            parent_id="root",
                        ),
                        node(
                            "new-parent",
                            "新父主题",
                            depth=1,
                            parent_id="root",
                        ),
                        node(
                            "child",
                            "子主题",
                            depth=2,
                            parent_id="old-parent",
                        ),
                    ],
                    edges=[
                        edge("root", "old-parent", score=0.8),
                        edge("root", "new-parent", score=0.8),
                        edge("old-parent", "child", score=0.7),
                    ],
                ),
            )

            with self.assertRaisesRegex(ValueError, "证据"):
                resolve_review_item(
                    blackboard=board,
                    task_id=original.task_id,
                    review_id=review.id,
                    request=ReviewResolutionRequest(
                        action="change_parent",
                        parent_id="new-parent",
                        expected_graph_version=original.graph_version,
                    ),
                )

            latest = board.load_latest_result(original.task_id)

        self.assertEqual(latest.graph_version, original.graph_version)
        self.assertEqual(
            next(
                item.source
                for item in latest.tree_edges
                if item.target == "child"
            ),
            "old-parent",
        )

    def test_change_parent_inherits_relation_evidence_and_records_new_edge(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            board = SQLiteBlackboard(Path(temp_dir) / "blackboard.sqlite3")
            relation_evidence = EvidenceRef(
                unit_id="unit-relation",
                excerpt="新父主题包含子主题",
            )
            review = ReviewItemView(
                id="review-change-parent-with-evidence",
                type="competing_parent",
                risk_score=0.9,
                subject_ids=["old-parent", "new-parent", "child"],
                subject_id="child",
                subject_type="tree_edge",
                reason="父节点候选接近",
                alternatives=[
                    {
                        "parent_id": "new-parent",
                        "score": 0.85,
                        "classification": "direct_parent",
                        "evidence": [
                            relation_evidence.model_dump(mode="json")
                        ],
                    }
                ],
            )
            original = self.save_result(
                board,
                result_with_review(
                    review=review,
                    nodes=[
                        node("root", "课程", depth=0, parent_id=None),
                        node(
                            "old-parent",
                            "旧父主题",
                            depth=1,
                            parent_id="root",
                        ),
                        node(
                            "new-parent",
                            "新父主题",
                            depth=1,
                            parent_id="root",
                        ),
                        node(
                            "child",
                            "子主题",
                            depth=2,
                            parent_id="old-parent",
                        ).model_copy(
                            update={
                                "status": "needs_review",
                                "risk_score": 0.9,
                            }
                        ),
                    ],
                    edges=[
                        edge("root", "old-parent", score=0.8),
                        edge("root", "new-parent", score=0.8),
                        edge("old-parent", "child", score=0.7),
                    ],
                ),
            )

            updated = resolve_review_item(
                blackboard=board,
                task_id=original.task_id,
                review_id=review.id,
                request=ReviewResolutionRequest(
                    action="change_parent",
                    parent_id="new-parent",
                    expected_graph_version=original.graph_version,
                ),
            )

        selected_edge = next(
            item for item in updated.tree_edges if item.target == "child"
        )
        resolved_child = next(
            item for item in updated.nodes if item.id == "child"
        )
        self.assertEqual(selected_edge.source, "new-parent")
        self.assertEqual(selected_edge.classification, "direct_parent")
        self.assertFalse(selected_edge.provisional)
        self.assertEqual(selected_edge.evidence, [relation_evidence])
        self.assertEqual(resolved_child.status, "accepted")
        self.assertEqual(resolved_child.risk_score, 0)
        self.assertEqual(
            updated.decision_records[-1].subject_id,
            selected_edge.id,
        )

    def test_resolving_review_refreshes_node_risk_and_records_the_edge(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            board = SQLiteBlackboard(Path(temp_dir) / "blackboard.sqlite3")
            review = ReviewItemView(
                id="review-confirm-edge",
                type="competing_parent",
                risk_score=0.8,
                subject_ids=["root", "child"],
                subject_id="child",
                subject_type="tree_edge",
                reason="确认当前直接父边",
            )
            child = node(
                "child",
                "子主题",
                depth=1,
                parent_id="root",
            ).model_copy(
                update={"status": "needs_review", "risk_score": 0.8}
            )
            original = self.save_result(
                board,
                result_with_review(
                    review=review,
                    nodes=[
                        node("root", "课程", depth=0, parent_id=None),
                        child,
                    ],
                    edges=[
                        edge(
                            "root",
                            "child",
                            score=0.8,
                            provisional=True,
                        )
                    ],
                ),
            )

            updated = resolve_review_item(
                blackboard=board,
                task_id=original.task_id,
                review_id=review.id,
                request=ReviewResolutionRequest(
                    action="keep",
                    expected_graph_version=original.graph_version,
                ),
            )

        resolved_child = next(item for item in updated.nodes if item.id == "child")
        self.assertEqual(resolved_child.status, "accepted")
        self.assertEqual(resolved_child.risk_score, 0)
        self.assertFalse(updated.tree_edges[0].provisional)
        self.assertEqual(updated.decision_records[-1].subject_type, "tree_edge")
        self.assertEqual(
            updated.decision_records[-1].subject_id,
            updated.tree_edges[0].id,
        )

    def test_review_recomputes_derived_quality_and_blocks_conflicts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            board = SQLiteBlackboard(Path(temp_dir) / "blackboard.sqlite3")
            review = ReviewItemView(
                id="review-recompute",
                type="abstract_parent",
                risk_score=0.7,
                subject_ids=["child"],
                subject_id="child",
                reason="确认节点",
            )
            root = node("root", "课程", depth=0, parent_id=None).model_copy(
                update={
                    "origin": "structural",
                    "support_unit_ids": ["u1", "u2"],
                }
            )
            child = node(
                "child",
                "量子态演化",
                depth=1,
                parent_id="root",
            ).model_copy(
                update={
                    "evidence": [
                        EvidenceRef(
                            unit_id="u1",
                            excerpt="量子态随时间按薛定谔方程连续演化。",
                        )
                    ]
                }
            )
            malformed = node(
                "bad",
                "但是",
                depth=1,
                parent_id="root",
            ).model_copy(
                update={
                    "evidence": [
                        EvidenceRef(
                            unit_id="u2",
                            excerpt="测量会使量子态投影到某一本征态。",
                        )
                    ]
                }
            )
            base = result_with_review(
                review=review,
                nodes=[root, child, malformed],
                edges=[
                    edge("root", "child", score=0.4),
                    edge("root", "bad", score=0.6),
                ],
            )
            base = base.model_copy(
                update={
                    "content_units": [
                        ContentUnit(
                            id="u1",
                            document_id="doc",
                            kind="text",
                            importance=0.5,
                            text="量子态随时间按薛定谔方程连续演化。",
                        ),
                        ContentUnit(
                            id="u2",
                            document_id="doc",
                            kind="text",
                            importance=0.5,
                            text="测量会使量子态投影到某一本征态。",
                        ),
                    ],
                    "quality_report": base.quality_report.model_copy(
                        update={
                            "weighted_content_coverage": 1,
                            "direct_parent_confidence": 1,
                            "abstraction_support_rate": 0,
                            "quality_gate_passed": False,
                        }
                    ),
                }
            )
            original = self.save_result(board, base)

            updated = resolve_review_item(
                blackboard=board,
                task_id=original.task_id,
                review_id=review.id,
                request=ReviewResolutionRequest(
                    action="keep",
                    expected_graph_version=original.graph_version,
                ),
            )

        self.assertEqual(
            updated.quality_report.direct_parent_confidence,
            0.5,
        )
        self.assertEqual(
            updated.quality_report.weighted_content_coverage,
            0.5,
        )
        self.assertEqual(
            updated.quality_report.abstraction_support_rate,
            1,
        )
        self.assertEqual(updated.quality_report.conflict_count, 1)
        self.assertFalse(updated.quality_report.publish_gate_passed)


class GraphConflictTDDTests(unittest.TestCase):
    def test_quality_report_rejects_normalized_duplicate_names_in_one_branch(self):
        root = node("root", "课程", depth=0, parent_id=None)
        first = node(
            "first",
            "重复主题",
            depth=1,
            parent_id="root",
        ).model_copy(update={"branch_id": "branch-a"})
        duplicate = node(
            "duplicate",
            "重复 主题",
            depth=1,
            parent_id="root",
        ).model_copy(update={"branch_id": "branch-a"})

        report = build_quality_report(
            [root, first, duplicate],
            [
                edge("root", "first", score=0.8),
                edge("root", "duplicate", score=0.8),
            ],
        )

        self.assertGreaterEqual(report.conflict_count, 1)
        self.assertTrue(
            any("同名" in warning or "重复" in warning for warning in report.warnings)
        )


if __name__ == "__main__":
    unittest.main()
