from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from backend.vnext.artifacts.local_store import LocalArtifactStore
from backend.vnext.cli import main
from backend.vnext.contracts.control import (
    ExecutionStatus,
    PublicationStatus,
    QualityStatus,
    StageCommitStatus,
)
from backend.vnext.orchestration.control_store import SQLiteControlStore
from backend.vnext.orchestration.durable_pipeline import (
    SimulatedWorkerCrash,
    run_durable_shadow_pipeline,
)


VALID_SOURCE = (
    "# Carbonyl Chemistry\n"
    "## Foundations\n"
    "Aldehydes are terminal carbonyl compounds.\n"
    "## Applications\n"
    "Ketones are used in synthesis.\n"
)

NESTED_SOURCE = (
    "# Carbonyl Chemistry\n"
    "## Foundations\n"
    "### Aldehydes\n"
    "Aldehydes are terminal carbonyl compounds.\n"
    "### Ketones\n"
    "Ketones contain internal carbonyl groups.\n"
    "## Applications\n"
    "### Oxidation\n"
    "Aldehydes can be oxidized.\n"
    "### Synthesis\n"
    "Ketones are used in synthesis.\n"
)


class VNextDurablePipelineTests(unittest.TestCase):
    def test_pipeline_commits_and_reuses_all_stages_across_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / "course.md"
            source_path.write_text(VALID_SOURCE, encoding="utf-8")
            artifacts = LocalArtifactStore(root / "artifacts")
            control = SQLiteControlStore(root / "control.sqlite3")

            first = run_durable_shadow_pipeline(
                source_path,
                owner_id="tenant-a",
                artifact_store=artifacts,
                control_store=control,
                worker_id="worker-a",
                run_id=f"run_{'1' * 32}",
            )
            second = run_durable_shadow_pipeline(
                source_path,
                owner_id="tenant-a",
                artifact_store=artifacts,
                control_store=control,
                worker_id="worker-b",
                run_id=f"run_{'2' * 32}",
            )

            expected_stages = {
                "source-shadow",
                "explicit-region-planning",
                "claim-ledger",
                "omission-and-region-audit",
                "canonical-explicit-graph",
                "diagnostic-projection",
            }
            self.assertEqual(
                first.run_manifest.execution_status,
                ExecutionStatus.SUCCEEDED,
            )
            self.assertEqual(
                first.run_manifest.quality_status,
                QualityStatus.PASSED,
            )
            self.assertEqual(
                first.run_manifest.publication_status,
                PublicationStatus.DRAFT,
            )
            self.assertEqual(first.reused_stages, ())
            self.assertEqual(set(second.reused_stages), expected_stages)
            self.assertEqual(
                first.shadow.projection_envelope.artifact_id,
                second.shadow.projection_envelope.artifact_id,
            )
            first_commits = control.list_run_commits(
                run_id=first.run_manifest.run_id,
                owner_id="tenant-a",
            )
            second_commits = control.list_run_commits(
                run_id=second.run_manifest.run_id,
                owner_id="tenant-a",
            )
            self.assertEqual(
                {commit.stage_key for commit in first_commits},
                expected_stages,
            )
            self.assertTrue(
                all(
                    commit.status is StageCommitStatus.COMMITTED
                    for commit in first_commits
                )
            )
            self.assertEqual(
                {commit.stage_key for commit in second_commits},
                expected_stages,
            )
            self.assertTrue(
                all(
                    commit.status is StageCommitStatus.REUSED
                    for commit in second_commits
                )
            )
            self.assertEqual(
                control.find_orphan_artifacts(
                    owner_id="tenant-a",
                    artifact_store=artifacts,
                ),
                (),
            )

    def test_nested_region_replay_keeps_preorder_and_reuses_all_stages(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / "nested-course.md"
            source_path.write_text(NESTED_SOURCE, encoding="utf-8")
            artifacts = LocalArtifactStore(root / "artifacts")
            control = SQLiteControlStore(root / "control.sqlite3")

            first = run_durable_shadow_pipeline(
                source_path,
                owner_id="tenant-a",
                artifact_store=artifacts,
                control_store=control,
                worker_id="worker-a",
                run_id=f"run_{'a' * 32}",
            )
            second = run_durable_shadow_pipeline(
                source_path,
                owner_id="tenant-a",
                artifact_store=artifacts,
                control_store=control,
                worker_id="worker-b",
                run_id=f"run_{'b' * 32}",
            )

            expected_stages = {
                "source-shadow",
                "explicit-region-planning",
                "claim-ledger",
                "omission-and-region-audit",
                "canonical-explicit-graph",
                "diagnostic-projection",
            }
            first_region_order = tuple(
                plan.region_id
                for plan in first.shadow.planning.final_plans
            )
            second_region_order = tuple(
                plan.region_id
                for plan in second.shadow.planning.final_plans
            )

            self.assertEqual(second_region_order, first_region_order)
            self.assertEqual(set(second.reused_stages), expected_stages)
            self.assertEqual(
                second.shadow.projection_envelope.artifact_id,
                first.shadow.projection_envelope.artifact_id,
            )

    def test_crash_after_object_write_resumes_and_quarantines_orphans(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / "course.md"
            source_path.write_text(VALID_SOURCE, encoding="utf-8")
            artifacts = LocalArtifactStore(root / "artifacts")
            control = SQLiteControlStore(root / "control.sqlite3")
            run_id = f"run_{'3' * 32}"

            with self.assertRaises(SimulatedWorkerCrash):
                run_durable_shadow_pipeline(
                    source_path,
                    owner_id="tenant-a",
                    artifact_store=artifacts,
                    control_store=control,
                    worker_id="worker-a",
                    run_id=run_id,
                    crash_after_stage="source-shadow",
                )
            crashed_artifacts = {
                envelope.artifact_id
                for envelope in artifacts.list_envelopes(
                    owner_id="tenant-a"
                )
            }
            self.assertEqual(len(crashed_artifacts), 2)
            self.assertEqual(
                control.load_run(
                    run_id,
                    owner_id="tenant-a",
                ).execution_status,
                ExecutionStatus.RUNNING,
            )

            resumed = run_durable_shadow_pipeline(
                source_path,
                owner_id="tenant-a",
                artifact_store=artifacts,
                control_store=control,
                worker_id="worker-a",
                run_id=run_id,
            )

            self.assertEqual(
                resumed.run_manifest.execution_status,
                ExecutionStatus.SUCCEEDED,
            )
            orphan_ids = set(
                control.find_orphan_artifacts(
                    owner_id="tenant-a",
                    artifact_store=artifacts,
                )
            )
            self.assertTrue(crashed_artifacts <= orphan_ids)
            self.assertEqual(
                len(
                    control.list_run_commits(
                        run_id=run_id,
                        owner_id="tenant-a",
                    )
                ),
                6,
            )

    def test_unresolved_run_succeeds_execution_but_fails_quality(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / "course.md"
            source_path.write_text(
                "## First\nA fact.\n## Second\nAnother fact.\n",
                encoding="utf-8",
            )

            result = run_durable_shadow_pipeline(
                source_path,
                owner_id="tenant-a",
                artifact_store=LocalArtifactStore(root / "artifacts"),
                control_store=SQLiteControlStore(
                    root / "control.sqlite3"
                ),
                worker_id="worker-a",
                run_id=f"run_{'4' * 32}",
            )

            self.assertEqual(
                result.run_manifest.execution_status,
                ExecutionStatus.SUCCEEDED,
            )
            self.assertEqual(
                result.run_manifest.quality_status,
                QualityStatus.BLOCKED_SEMANTIC,
            )
            self.assertEqual(
                result.run_manifest.publication_status,
                PublicationStatus.DRAFT,
            )

    def test_owner_scope_prevents_cross_tenant_reuse(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / "course.md"
            source_path.write_text(VALID_SOURCE, encoding="utf-8")
            artifacts = LocalArtifactStore(root / "artifacts")
            control = SQLiteControlStore(root / "control.sqlite3")
            run_durable_shadow_pipeline(
                source_path,
                owner_id="tenant-a",
                artifact_store=artifacts,
                control_store=control,
                worker_id="worker-a",
                run_id=f"run_{'5' * 32}",
            )

            other = run_durable_shadow_pipeline(
                source_path,
                owner_id="tenant-b",
                artifact_store=artifacts,
                control_store=control,
                worker_id="worker-b",
                run_id=f"run_{'6' * 32}",
            )

            self.assertEqual(other.reused_stages, ())

    def test_durable_shadow_cli_reports_control_plane_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / "course.md"
            source_path.write_text(VALID_SOURCE, encoding="utf-8")
            output = io.StringIO()
            run_id = f"run_{'7' * 32}"

            with redirect_stdout(output):
                exit_code = main(
                    [
                        "durable-shadow",
                        "--input",
                        str(source_path),
                        "--owner",
                        "tenant-a",
                        "--root",
                        str(root / "artifacts"),
                        "--control-db",
                        str(root / "control.sqlite3"),
                        "--run-id",
                        run_id,
                        "--worker",
                        "cli-worker-a",
                    ]
                )

            payload = json.loads(output.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["run_id"], run_id)
            self.assertEqual(payload["execution_status"], "succeeded")
            self.assertEqual(payload["quality_status"], "passed")
            self.assertEqual(payload["publication_status"], "draft")
            self.assertEqual(payload["reused_stages"], [])
            self.assertRegex(
                payload["projection_artifact_id"],
                r"^art_[0-9a-f]{32}$",
            )


if __name__ == "__main__":
    unittest.main()
