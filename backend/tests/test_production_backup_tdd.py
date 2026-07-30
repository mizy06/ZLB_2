from __future__ import annotations

import base64
import copy
import hashlib
import io
import json
import os
import socket
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)

from backend.tools import pdf_page_knowledge_evaluator
from backend.tools import pdf_quality_oracle
from backend.tools.pdf_page_knowledge_evaluator import (
    sign_evaluation_artifact,
)
from backend.tools.production_backup import (
    BLACKBOARD_FILENAME,
    ProductionBackupError,
    _optional_inspect_json,
    _parser,
    create_backup,
    cutover_to_candidate,
    freeze_production,
    prepare_restored_volumes,
    rollback_to_preserved_container,
    restore_backup,
    verify_candidate_quality_evaluation,
    verify_backup,
    verify_quality_evaluation_signature,
)


def _module_sha256(module) -> str:
    return hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()


def _public_key_sha256(path: Path) -> str:
    public_key = serialization.load_pem_public_key(path.read_bytes())
    public_key_der = public_key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return hashlib.sha256(public_key_der).hexdigest()


def _quality_evaluation_payload(
    *,
    image_id: str = "sha256:v11",
    passed: bool = True,
) -> dict:
    source_sha256 = "a" * 64
    return {
        "schema_version": "pdf-page-knowledge-evaluation-v1",
        "canary_report": {
            "sha256": "b" * 64,
            "run_id": "run-canary",
            "task_id": "task-canary",
            "source_sha256": source_sha256,
            "selected_original_pages": [2, 6],
            "manifest": {
                "kind": "pdf_page_knowledge_canary",
                "source_sha256": source_sha256,
                "original_pages": [2, 6],
                "image_digest": image_id,
                "provider": "qwen",
                "credential_source": "age",
                "qwen_production_profile": "standard",
                "extraction_profile": "direct_layout_fallback",
            },
        },
        "quality_oracle": {
            "schema_version": "pdf-page-quality-oracle-v1",
            "sha256": "c" * 64,
        },
        "evaluator": {
            "schema_version": "pdf-page-knowledge-evaluation-v1",
            "module_sha256": _module_sha256(
                pdf_page_knowledge_evaluator
            ),
            "quality_module_sha256": _module_sha256(pdf_quality_oracle),
        },
        "evaluation": {
            "passed": passed,
            "page_state": {
                "passed": passed,
                "all_clean": passed,
                "selected_page_count": 2,
                "clean_page_count": 2 if passed else 1,
                "degraded_pages": [] if passed else [6],
                "failed_pages": [],
            },
            "model_call_policy": {
                "passed": passed,
                "request_policy_all_match": passed,
                "request_policy_count": 4,
            },
            "artifact_identity": {
                "passed": passed,
                "issues": [] if passed else ["manifest_image_digest_missing"],
            },
            "canonical_formulas": {
                "passed": passed,
                "expected_count": 2,
                "exact_count": 2 if passed else 1,
                "exact_rate": 1.0 if passed else 0.5,
            },
            "required_coverage": {
                "passed": passed,
                "required_count": 2,
                "covered_count": 2 if passed else 1,
                "rate": 1.0 if passed else 0.5,
            },
            "has_knowledge": {
                "passed": passed,
                "assertion_count": 2,
            },
        },
    }


def _write_quality_evaluation(
    root: Path,
    *,
    image_id: str = "sha256:v11",
    passed: bool = True,
) -> Path:
    path = root / "quality-evaluation.json"
    path.write_text(
        json.dumps(
            _quality_evaluation_payload(
                image_id=image_id,
                passed=passed,
            )
        ),
        encoding="utf-8",
    )
    return path


def _write_evaluation_signature(
    evaluation_path: Path,
) -> tuple[Path, Path]:
    private_key = Ed25519PrivateKey.generate()
    public_key_path = evaluation_path.with_name("attestation-public.pem")
    signature_path = evaluation_path.with_suffix(".sig.json")
    private_key_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_key_path.write_bytes(
        private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    sign_evaluation_artifact(
        evaluation_path=evaluation_path,
        private_key_pem=private_key_pem,
        signature_path=signature_path,
    )
    return signature_path, public_key_path


def _write_signed_quality_evaluation(
    root: Path,
    *,
    image_id: str = "sha256:v11",
    passed: bool = True,
) -> tuple[Path, Path, Path]:
    evaluation_path = _write_quality_evaluation(
        root,
        image_id=image_id,
        passed=passed,
    )
    signature_path, public_key_path = _write_evaluation_signature(
        evaluation_path
    )
    return evaluation_path, signature_path, public_key_path


class ProductionBackupTDDTests(unittest.TestCase):
    def _source_tree(self, root: Path) -> tuple[Path, Path]:
        data_dir = root / "data"
        uploads_dir = root / "uploads"
        (data_dir / "assets" / "render-a").mkdir(parents=True)
        uploads_dir.mkdir()
        with sqlite3.connect(data_dir / BLACKBOARD_FILENAME) as database:
            database.execute(
                "CREATE TABLE jobs (id TEXT PRIMARY KEY, status TEXT)"
            )
            database.execute(
                "INSERT INTO jobs VALUES ('job-a', 'completed')"
            )
            database.commit()
        (data_dir / "assets" / "render-a" / "page_0001.png").write_bytes(
            b"png-source"
        )
        (data_dir / "run-manifest.json").write_text(
            '{"run":"a"}\n',
            encoding="utf-8",
        )
        (uploads_dir / "source.pdf").write_bytes(b"pdf-source")
        return data_dir, uploads_dir

    def test_create_verify_and_restore_preserve_database_and_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir, uploads_dir = self._source_tree(root)
            backup_dir = root / "backup"

            manifest = create_backup(
                data_dir=data_dir,
                uploads_dir=uploads_dir,
                destination=backup_dir,
                metadata={"candidate_image_id": "sha256:candidate"},
            )
            verified = verify_backup(backup_dir)

            with sqlite3.connect(data_dir / BLACKBOARD_FILENAME) as database:
                database.execute(
                    "UPDATE jobs SET status='mutated' WHERE id='job-a'"
                )
                database.commit()
            (uploads_dir / "source.pdf").write_bytes(b"mutated")

            restored_data = root / "restored-data"
            restored_uploads = root / "restored-uploads"
            restore_backup(
                backup_dir=backup_dir,
                data_dir=restored_data,
                uploads_dir=restored_uploads,
                owner_uid=os.getuid(),
                owner_gid=os.getgid(),
            )

            with sqlite3.connect(
                restored_data / BLACKBOARD_FILENAME
            ) as database:
                status = database.execute(
                    "SELECT status FROM jobs WHERE id='job-a'"
                ).fetchone()[0]

            self.assertEqual(manifest, verified)
            self.assertEqual(status, "completed")
            self.assertEqual(
                (
                    restored_data
                    / "assets"
                    / "render-a"
                    / "page_0001.png"
                ).read_bytes(),
                b"png-source",
            )
            self.assertEqual(
                (restored_data / "run-manifest.json").read_text(
                    encoding="utf-8"
                ),
                '{"run":"a"}\n',
            )
            self.assertEqual(
                (restored_uploads / "source.pdf").read_bytes(),
                b"pdf-source",
            )
            self.assertEqual(
                manifest["metadata"]["candidate_image_id"],
                "sha256:candidate",
            )

    def test_verify_rejects_a_tampered_archive(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir, uploads_dir = self._source_tree(root)
            backup_dir = root / "backup"
            create_backup(
                data_dir=data_dir,
                uploads_dir=uploads_dir,
                destination=backup_dir,
            )
            with (backup_dir / "uploads.tar.gz").open("ab") as archive:
                archive.write(b"tampered")

            with self.assertRaisesRegex(
                ProductionBackupError,
                "(?:size|SHA-256) mismatch",
            ):
                verify_backup(backup_dir)

    def test_restore_rejects_nonempty_destinations(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir, uploads_dir = self._source_tree(root)
            backup_dir = root / "backup"
            create_backup(
                data_dir=data_dir,
                uploads_dir=uploads_dir,
                destination=backup_dir,
            )
            restored_data = root / "restored-data"
            restored_data.mkdir()
            (restored_data / "existing").write_text(
                "do not overwrite",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ProductionBackupError,
                "empty directory",
            ):
                restore_backup(
                    backup_dir=backup_dir,
                    data_dir=restored_data,
                    uploads_dir=root / "restored-uploads",
                )

    def test_manifest_contains_no_secret_values(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir, uploads_dir = self._source_tree(root)
            backup_dir = root / "backup"
            create_backup(
                data_dir=data_dir,
                uploads_dir=uploads_dir,
                destination=backup_dir,
                metadata={
                    "candidate_image": "candidate-v11",
                    "rollback_image": "rollback-v4",
                },
            )
            manifest = json.loads(
                (backup_dir / "manifest.json").read_text(encoding="utf-8")
            )
            serialized = json.dumps(manifest)

            self.assertNotIn("TOKEN", serialized)
            self.assertNotIn("API_KEY", serialized)
            self.assertNotIn("PASSWORD", serialized)

    def test_quality_evaluation_binds_passed_gates_to_candidate_image(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path, signature_path, public_key_path = (
                _write_signed_quality_evaluation(Path(temp_dir))
            )

            identity = verify_candidate_quality_evaluation(
                path,
                expected_image_id="sha256:v11",
                signature_path=signature_path,
                public_key_path=public_key_path,
                expected_public_key_sha256=_public_key_sha256(
                    public_key_path
                ),
            )
            trusted_public_key_sha256 = _public_key_sha256(public_key_path)

        self.assertEqual(identity["image_id"], "sha256:v11")
        self.assertEqual(identity["run_id"], "run-canary")
        self.assertEqual(identity["selected_page_count"], 2)
        self.assertEqual(len(identity["sha256"]), 64)
        self.assertEqual(identity["signature"]["algorithm"], "ed25519")
        self.assertEqual(
            identity["signature"]["trust_anchor_sha256"],
            trusted_public_key_sha256,
        )
        self.assertEqual(
            identity["signature"]["artifact_sha256"],
            identity["sha256"],
        )

    def test_quality_evaluation_accepts_only_exact_approved_qwen_profile(self):
        approved_endpoint = (
            "https://token-plan.cn-beijing.maas.aliyuncs.com/"
            "compatible-mode/v1"
        )
        approved_model = "qwen3.8-max-preview"

        def approved_payload() -> dict:
            payload = _quality_evaluation_payload()
            manifest = payload["canary_report"]["manifest"]
            manifest.update(
                {
                    "qwen_production_profile": (
                        "approved_cn_token_plan_preview"
                    ),
                    "provider_endpoint": approved_endpoint,
                    "text_model": approved_model,
                    "vision_model": approved_model,
                }
            )
            return payload

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            accepted_path = root / "accepted.json"
            accepted_path.write_text(
                json.dumps(approved_payload()),
                encoding="utf-8",
            )
            accepted_signature, accepted_public_key = (
                _write_evaluation_signature(accepted_path)
            )

            identity = verify_candidate_quality_evaluation(
                accepted_path,
                expected_image_id="sha256:v11",
                signature_path=accepted_signature,
                public_key_path=accepted_public_key,
                expected_public_key_sha256=_public_key_sha256(
                    accepted_public_key
                ),
            )
            self.assertEqual(identity["image_id"], "sha256:v11")

            deviations = (
                ("provider_endpoint", approved_endpoint + "/other"),
                ("text_model", "qwen3.7-max"),
                ("vision_model", "qwen3.7-plus"),
            )
            for field, value in deviations:
                with self.subTest(field=field):
                    rejected_path = root / f"rejected-{field}.json"
                    payload = approved_payload()
                    payload["canary_report"]["manifest"][field] = value
                    rejected_path.write_text(
                        json.dumps(payload),
                        encoding="utf-8",
                    )
                    signature_path, public_key_path = (
                        _write_evaluation_signature(rejected_path)
                    )
                    with self.assertRaisesRegex(
                        ProductionBackupError,
                        "Qwen production profile is not eligible",
                    ):
                        verify_candidate_quality_evaluation(
                            rejected_path,
                            expected_image_id="sha256:v11",
                            signature_path=signature_path,
                            public_key_path=public_key_path,
                            expected_public_key_sha256=_public_key_sha256(
                                public_key_path
                            ),
                        )

    def test_quality_signature_rejects_missing_modified_bad_and_wrong_key(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            evaluation_path = _write_quality_evaluation(root)
            original_evaluation = evaluation_path.read_bytes()
            signature_path, public_key_path = _write_evaluation_signature(
                evaluation_path
            )

            identity = verify_quality_evaluation_signature(
                evaluation_path=evaluation_path,
                signature_path=signature_path,
                public_key_path=public_key_path,
                expected_public_key_sha256=_public_key_sha256(
                    public_key_path
                ),
            )

            self.assertEqual(identity["algorithm"], "ed25519")
            self.assertEqual(len(identity["public_key_sha256"]), 64)
            evaluation_path.write_text(
                evaluation_path.read_text(encoding="utf-8") + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(ProductionBackupError):
                verify_quality_evaluation_signature(
                    evaluation_path=evaluation_path,
                    signature_path=signature_path,
                    public_key_path=public_key_path,
                    expected_public_key_sha256=_public_key_sha256(
                        public_key_path
                    ),
                )

            evaluation_path.write_bytes(original_evaluation)
            trusted_public_key_sha256 = _public_key_sha256(public_key_path)
            other_private_key = Ed25519PrivateKey.generate()
            public_key_path.write_bytes(
                other_private_key.public_key().public_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PublicFormat.SubjectPublicKeyInfo,
                )
            )
            with self.assertRaises(ProductionBackupError):
                verify_quality_evaluation_signature(
                    evaluation_path=evaluation_path,
                    signature_path=signature_path,
                    public_key_path=public_key_path,
                    expected_public_key_sha256=trusted_public_key_sha256,
                )

            signature_path, public_key_path = _write_evaluation_signature(
                evaluation_path
            )
            signature_payload = json.loads(
                signature_path.read_text(encoding="utf-8")
            )
            signature = bytearray(
                base64.b64decode(signature_payload["signature_base64"])
            )
            signature[0] ^= 1
            signature_payload["signature_base64"] = base64.b64encode(
                signature
            ).decode("ascii")
            signature_path.write_text(
                json.dumps(signature_payload),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                ProductionBackupError,
                "signature verification failed",
            ):
                verify_quality_evaluation_signature(
                    evaluation_path=evaluation_path,
                    signature_path=signature_path,
                    public_key_path=public_key_path,
                    expected_public_key_sha256=_public_key_sha256(
                        public_key_path
                    ),
                )

            with self.assertRaisesRegex(
                ProductionBackupError,
                "signature does not exist",
            ):
                verify_quality_evaluation_signature(
                    evaluation_path=evaluation_path,
                    signature_path=root / "missing.sig.json",
                    public_key_path=public_key_path,
                    expected_public_key_sha256=_public_key_sha256(
                        public_key_path
                    ),
                )

    def test_quality_signature_rejects_unapproved_signer_fingerprint(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            evaluation_path = _write_quality_evaluation(root)
            signature_path, public_key_path = _write_evaluation_signature(
                evaluation_path
            )

            with self.assertRaisesRegex(
                ProductionBackupError,
                "public key is not trusted",
            ):
                verify_quality_evaluation_signature(
                    evaluation_path=evaluation_path,
                    signature_path=signature_path,
                    public_key_path=public_key_path,
                    expected_public_key_sha256="0" * 64,
                )

    def test_quality_evaluation_rejects_failed_or_wrong_image(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            failed_path = _write_quality_evaluation(
                root,
                passed=False,
            )
            failed_signature, public_key_path = _write_evaluation_signature(
                failed_path
            )
            with self.assertRaisesRegex(
                ProductionBackupError,
                "quality evaluation did not pass",
            ):
                verify_candidate_quality_evaluation(
                    failed_path,
                    expected_image_id="sha256:v11",
                    signature_path=failed_signature,
                    public_key_path=public_key_path,
                    expected_public_key_sha256=_public_key_sha256(
                        public_key_path
                    ),
                )

            wrong_image_path = _write_quality_evaluation(
                root,
                image_id="sha256:other",
            )
            wrong_signature, public_key_path = _write_evaluation_signature(
                wrong_image_path
            )
            with self.assertRaisesRegex(
                ProductionBackupError,
                "candidate image identity",
            ):
                verify_candidate_quality_evaluation(
                    wrong_image_path,
                    expected_image_id="sha256:v11",
                    signature_path=wrong_signature,
                    public_key_path=public_key_path,
                    expected_public_key_sha256=_public_key_sha256(
                        public_key_path
                    ),
                )

    def test_quality_evaluation_rejects_wrong_evaluator_identity(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "quality-evaluation.json"
            payload = _quality_evaluation_payload()
            payload["evaluator"]["module_sha256"] = "f" * 64
            path.write_text(json.dumps(payload), encoding="utf-8")
            signature_path, public_key_path = _write_evaluation_signature(
                path
            )

            with self.assertRaisesRegex(
                ProductionBackupError,
                "evaluator identity is invalid",
            ):
                verify_candidate_quality_evaluation(
                    path,
                    expected_image_id="sha256:v11",
                    signature_path=signature_path,
                    public_key_path=public_key_path,
                    expected_public_key_sha256=_public_key_sha256(
                        public_key_path
                    ),
                )

    def test_quality_evaluation_rejects_missing_gates_and_empty_proofs(self):
        gate_names = (
            "page_state",
            "model_call_policy",
            "artifact_identity",
            "canonical_formulas",
            "required_coverage",
            "has_knowledge",
        )
        proof_mutations = {
            "page_state": {
                "selected_page_count": 0,
                "clean_page_count": 0,
            },
            "model_call_policy": {"request_policy_count": 0},
            "artifact_identity": {"issues": ["missing_identity"]},
            "canonical_formulas": {
                "expected_count": 0,
                "exact_count": 0,
            },
            "required_coverage": {
                "required_count": 0,
                "covered_count": 0,
            },
            "has_knowledge": {"assertion_count": 0},
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for gate_name in gate_names:
                with self.subTest(gate=gate_name, case="missing"):
                    payload = copy.deepcopy(_quality_evaluation_payload())
                    payload["evaluation"].pop(gate_name)
                    path = root / f"missing-{gate_name}.json"
                    path.write_text(json.dumps(payload), encoding="utf-8")
                    signature_path, public_key_path = (
                        _write_evaluation_signature(path)
                    )
                    with self.assertRaises(ProductionBackupError):
                        verify_candidate_quality_evaluation(
                            path,
                            expected_image_id="sha256:v11",
                            signature_path=signature_path,
                            public_key_path=public_key_path,
                            expected_public_key_sha256=_public_key_sha256(
                                public_key_path
                            ),
                        )

                with self.subTest(gate=gate_name, case="empty-proof"):
                    payload = copy.deepcopy(_quality_evaluation_payload())
                    payload["evaluation"][gate_name].update(
                        proof_mutations[gate_name]
                    )
                    path = root / f"empty-{gate_name}.json"
                    path.write_text(json.dumps(payload), encoding="utf-8")
                    signature_path, public_key_path = (
                        _write_evaluation_signature(path)
                    )
                    with self.assertRaisesRegex(
                        ProductionBackupError,
                        "(?:proof is incomplete|artifact identity is incomplete)",
                    ):
                        verify_candidate_quality_evaluation(
                            path,
                            expected_image_id="sha256:v11",
                            signature_path=signature_path,
                            public_key_path=public_key_path,
                            expected_public_key_sha256=_public_key_sha256(
                                public_key_path
                            ),
                        )

    @patch("backend.tools.production_backup.create_backup")
    @patch(
        "backend.tools.production_backup."
        "verify_candidate_quality_evaluation"
    )
    @patch("backend.tools.production_backup._inspect_json")
    def test_freeze_requires_an_explicit_stop_for_a_running_container(
        self,
        inspect_json,
        verify_quality,
        create_backup_mock,
    ):
        inspect_json.side_effect = [
            {
                "Image": "sha256:v4",
                "State": {"Running": True},
                "Mounts": [],
            },
            {"Id": "sha256:v4"},
            {"Id": "sha256:v11"},
        ]
        verify_quality.return_value = {
            "sha256": "quality-sha",
            "image_id": "sha256:v11",
            "signature": {
                "algorithm": "ed25519",
                "sha256": "signature-sha",
                "artifact_sha256": "quality-sha",
                "public_key_sha256": "public-key-sha",
            },
        }

        with self.assertRaisesRegex(
            ProductionBackupError,
            "pass --stop-container",
        ):
            freeze_production(
                container_name="zlb-mindmap",
                rollback_image="rollback-v4",
                candidate_image="candidate-v11",
                quality_evaluation_path=Path("/quality.json"),
                quality_signature_path=Path("/quality.sig.json"),
                quality_public_key_path=Path("/quality-public.pem"),
                expected_quality_public_key_sha256="public-key-sha",
                destination=Path("/backup"),
                stop_container=False,
                stop_timeout_seconds=60,
            )

        create_backup_mock.assert_not_called()

    @patch("backend.tools.production_backup.create_backup")
    @patch("backend.tools.production_backup._run_command")
    @patch(
        "backend.tools.production_backup."
        "verify_candidate_quality_evaluation"
    )
    @patch("backend.tools.production_backup._inspect_json")
    def test_freeze_rejects_invalid_signature_before_stopping_service(
        self,
        inspect_json,
        verify_quality,
        run_command,
        create_backup_mock,
    ):
        inspect_json.side_effect = [
            {
                "Image": "sha256:v4",
                "State": {"Running": True},
                "Mounts": [],
            },
            {"Id": "sha256:v4"},
            {"Id": "sha256:v11"},
        ]
        verify_quality.side_effect = ProductionBackupError(
            "Candidate quality signature verification failed"
        )

        with self.assertRaisesRegex(
            ProductionBackupError,
            "signature verification failed",
        ):
            freeze_production(
                container_name="zlb-mindmap",
                rollback_image="rollback-v4",
                candidate_image="candidate-v11",
                quality_evaluation_path=Path("/quality.json"),
                quality_signature_path=Path("/quality.sig.json"),
                quality_public_key_path=Path("/quality-public.pem"),
                expected_quality_public_key_sha256="public-key-sha",
                destination=Path("/backup"),
                stop_container=True,
                stop_timeout_seconds=60,
            )

        run_command.assert_not_called()
        create_backup_mock.assert_not_called()

    @patch("backend.tools.production_backup.create_backup")
    @patch(
        "backend.tools.production_backup."
        "verify_candidate_quality_evaluation"
    )
    @patch("backend.tools.production_backup._run_command")
    @patch("backend.tools.production_backup._inspect_json")
    def test_freeze_stops_service_and_records_exact_images_and_volumes(
        self,
        inspect_json,
        run_command,
        verify_quality,
        create_backup_mock,
    ):
        running = {
            "Image": "sha256:v4",
            "State": {"Running": True},
            "Mounts": [],
        }
        stopped = {
            "Image": "sha256:v4",
            "State": {"Running": False},
            "Mounts": [
                {
                    "Destination": "/app/.data/mindmap_engine",
                    "Source": "/volumes/data",
                    "Name": "prod-data",
                },
                {
                    "Destination": "/app/backend/uploads",
                    "Source": "/volumes/uploads",
                    "Name": "prod-uploads",
                },
            ],
        }
        inspect_json.side_effect = [
            running,
            {"Id": "sha256:v4"},
            {"Id": "sha256:v11"},
            stopped,
        ]
        verify_quality.return_value = {
            "schema_version": "pdf-page-knowledge-evaluation-v1",
            "sha256": "quality-sha",
            "image_id": "sha256:v11",
            "run_id": "run-canary",
            "source_sha256": "source-sha",
            "selected_page_count": 2,
            "signature": {
                "schema_version": "zlb-quality-evaluation-signature-v1",
                "algorithm": "ed25519",
                "sha256": "signature-sha",
                "artifact_sha256": "quality-sha",
                "public_key_sha256": "public-key-sha",
            },
        }
        create_backup_mock.return_value = {
            "schema_version": "zlb-production-backup-v1",
            "created_at": "2026-07-26T00:00:00+00:00",
        }

        manifest = freeze_production(
            container_name="zlb-mindmap",
            rollback_image="rollback-v4",
            candidate_image="candidate-v11",
            quality_evaluation_path=Path("/quality.json"),
            quality_signature_path=Path("/quality.sig.json"),
            quality_public_key_path=Path("/quality-public.pem"),
            expected_quality_public_key_sha256="public-key-sha",
            destination=Path("/backup"),
            stop_container=True,
            stop_timeout_seconds=60,
        )

        self.assertEqual(
            run_command.call_args_list[0].args[0],
            ["docker", "update", "--restart=no", "zlb-mindmap"],
        )
        self.assertEqual(
            run_command.call_args_list[1].args[0],
            [
                "docker",
                "stop",
                "--time",
                "60",
                "zlb-mindmap",
            ],
        )
        kwargs = create_backup_mock.call_args.kwargs
        self.assertEqual(kwargs["data_dir"], Path("/volumes/data"))
        self.assertEqual(
            kwargs["uploads_dir"],
            Path("/volumes/uploads"),
        )
        self.assertEqual(
            kwargs["metadata"]["candidate_image_id"],
            "sha256:v11",
        )
        self.assertEqual(
            kwargs["metadata"]["rollback_image_id"],
            "sha256:v4",
        )
        self.assertEqual(
            kwargs["metadata"]["quality_evaluation"]["sha256"],
            "quality-sha",
        )
        self.assertEqual(
            kwargs["metadata"]["quality_evaluation"]["signature"],
            verify_quality.return_value["signature"],
        )
        verify_quality.assert_called_once_with(
            Path("/quality.json"),
            expected_image_id="sha256:v11",
            signature_path=Path("/quality.sig.json"),
            public_key_path=Path("/quality-public.pem"),
            expected_public_key_sha256="public-key-sha",
        )
        self.assertEqual(kwargs["metadata"]["data_volume"], "prod-data")
        self.assertEqual(
            kwargs["metadata"]["uploads_volume"],
            "prod-uploads",
        )
        self.assertEqual(
            manifest["schema_version"],
            "zlb-production-backup-v1",
        )

    @patch("backend.tools.production_backup.restore_backup")
    @patch("backend.tools.production_backup._backup_manifest_sha256")
    @patch("backend.tools.production_backup._run_command")
    @patch("backend.tools.production_backup._optional_inspect_json")
    @patch("backend.tools.production_backup._inspect_json")
    def test_prepare_volumes_restores_only_new_labeled_volumes(
        self,
        inspect_json,
        optional_inspect_json,
        run_command,
        backup_manifest_sha256,
        restore_backup_mock,
    ):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_mountpoint = root / "data"
            uploads_mountpoint = root / "uploads"
            data_mountpoint.mkdir()
            uploads_mountpoint.mkdir()
            optional_inspect_json.return_value = None
            backup_manifest_sha256.return_value = "manifest-sha"
            inspect_json.side_effect = [
                {"Mountpoint": str(data_mountpoint)},
                {"Mountpoint": str(uploads_mountpoint)},
            ]

            result = prepare_restored_volumes(
                backup_dir=Path("/backup"),
                data_volume="candidate-data",
                uploads_volume="candidate-uploads",
            )

        self.assertEqual(
            result["backup_manifest_sha256"],
            "manifest-sha",
        )
        self.assertEqual(run_command.call_count, 2)
        self.assertIn(
            "zlb.backup_sha256=manifest-sha",
            run_command.call_args_list[0].args[0],
        )
        restore_backup_mock.assert_called_once_with(
            backup_dir=Path("/backup"),
            data_dir=data_mountpoint,
            uploads_dir=uploads_mountpoint,
            owner_uid=10001,
            owner_gid=10001,
        )

    @patch(
        "backend.tools.production_backup._assert_tcp_port_available"
    )
    @patch(
        "backend.tools.production_backup."
        "verify_candidate_quality_evaluation"
    )
    @patch(
        "backend.tools.production_backup.rollback_to_preserved_container"
    )
    @patch("backend.tools.production_backup.deploy_compose_candidate")
    @patch("backend.tools.production_backup._run_command")
    @patch("backend.tools.production_backup._optional_inspect_json")
    @patch("backend.tools.production_backup._inspect_json")
    @patch("backend.tools.production_backup.verify_backup")
    def test_cutover_failure_restores_the_preserved_container(
        self,
        verify_backup_mock,
        inspect_json,
        optional_inspect_json,
        run_command,
        deploy_candidate,
        rollback,
        verify_quality,
        assert_tcp_port_available,
    ):
        verify_backup_mock.return_value = {
            "metadata": {
                "rollback_image_id": "sha256:v4",
                "candidate_image_id": "sha256:v11",
                "quality_evaluation": {
                    "sha256": "quality-sha",
                    "image_id": "sha256:v11",
                    "signature": {
                        "sha256": "signature-sha",
                        "public_key_sha256": "public-key-sha",
                    },
                },
            }
        }
        verify_quality.return_value = {
            "sha256": "quality-sha",
            "image_id": "sha256:v11",
            "signature": {
                "sha256": "signature-sha",
                "public_key_sha256": "public-key-sha",
            },
        }
        inspect_json.return_value = {
            "Image": "sha256:v4",
            "State": {"Running": False},
        }
        optional_inspect_json.return_value = None
        deploy_candidate.side_effect = ProductionBackupError("health failed")

        with self.assertRaisesRegex(
            ProductionBackupError,
            "preserved production container was restored",
        ):
            cutover_to_candidate(
                backup_dir=Path("/backup"),
                compose_file=Path("/compose.prod.yml"),
                project_name="zlb-production",
                active_container="zlb-mindmap",
                rollback_container="zlb-rollback-v4",
                image_ref="candidate-v11",
                expected_image_id="sha256:v11",
                quality_evaluation_path=Path("/quality.json"),
                quality_signature_path=Path("/quality.sig.json"),
                quality_public_key_path=Path("/quality-public.pem"),
                expected_quality_public_key_sha256="public-key-sha",
                data_volume="candidate-data",
                uploads_volume="candidate-uploads",
                bind_host="127.0.0.1",
                public_port=5173,
                health_url="http://127.0.0.1:5173/api/health",
                health_timeout_seconds=60,
            )

        run_command.assert_called_once_with(
            [
                "docker",
                "rename",
                "zlb-mindmap",
                "zlb-rollback-v4",
            ]
        )
        rollback.assert_called_once_with(
            active_container="zlb-mindmap",
            rollback_container="zlb-rollback-v4",
            expected_rollback_image_id="sha256:v4",
        )
        assert_tcp_port_available.assert_called_once_with(
            "127.0.0.1",
            5173,
        )
        verify_quality.assert_called_once_with(
            Path("/quality.json"),
            expected_image_id="sha256:v11",
            signature_path=Path("/quality.sig.json"),
            public_key_path=Path("/quality-public.pem"),
            expected_public_key_sha256="public-key-sha",
        )

    @patch(
        "backend.tools.production_backup.rollback_to_preserved_container"
    )
    @patch(
        "backend.tools.production_backup."
        "verify_candidate_quality_evaluation"
    )
    @patch("backend.tools.production_backup.deploy_compose_candidate")
    @patch("backend.tools.production_backup._run_command")
    @patch("backend.tools.production_backup._optional_inspect_json")
    @patch("backend.tools.production_backup._inspect_json")
    @patch("backend.tools.production_backup.verify_backup")
    def test_cutover_rejects_occupied_port_before_renaming(
        self,
        verify_backup_mock,
        inspect_json,
        optional_inspect_json,
        run_command,
        deploy_candidate,
        verify_quality,
        rollback,
    ):
        verify_backup_mock.return_value = {
            "metadata": {
                "rollback_image_id": "sha256:v4",
                "candidate_image_id": "sha256:v11",
                "quality_evaluation": {
                    "sha256": "quality-sha",
                    "image_id": "sha256:v11",
                    "signature": {
                        "sha256": "signature-sha",
                        "public_key_sha256": "public-key-sha",
                    },
                },
            }
        }
        verify_quality.return_value = {
            "sha256": "quality-sha",
            "image_id": "sha256:v11",
            "signature": {
                "sha256": "signature-sha",
                "public_key_sha256": "public-key-sha",
            },
        }
        inspect_json.return_value = {
            "Image": "sha256:v4",
            "State": {"Running": False},
        }
        optional_inspect_json.return_value = None

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            occupied_port = listener.getsockname()[1]

            with self.assertRaisesRegex(
                ProductionBackupError,
                "already in use",
            ):
                cutover_to_candidate(
                    backup_dir=Path("/backup"),
                    compose_file=Path("/compose.prod.yml"),
                    project_name="zlb-production",
                    active_container="zlb-mindmap",
                    rollback_container="zlb-rollback-v4",
                    image_ref="candidate-v11",
                    expected_image_id="sha256:v11",
                    quality_evaluation_path=Path("/quality.json"),
                    quality_signature_path=Path("/quality.sig.json"),
                    quality_public_key_path=Path("/quality-public.pem"),
                    expected_quality_public_key_sha256="public-key-sha",
                    data_volume="candidate-data",
                    uploads_volume="candidate-uploads",
                    bind_host="127.0.0.1",
                    public_port=occupied_port,
                    health_url=(
                        f"http://127.0.0.1:{occupied_port}/api/health"
                    ),
                    health_timeout_seconds=60,
                )

        run_command.assert_not_called()
        deploy_candidate.assert_not_called()
        rollback.assert_not_called()

    @patch("backend.tools.production_backup._run_command")
    @patch("backend.tools.production_backup._inspect_json")
    @patch("backend.tools.production_backup.verify_backup")
    @patch(
        "backend.tools.production_backup."
        "verify_candidate_quality_evaluation"
    )
    def test_cutover_rejects_unbound_quality_before_renaming(
        self,
        verify_quality,
        verify_backup_mock,
        inspect_json,
        run_command,
    ):
        verify_backup_mock.return_value = {
            "metadata": {
                "rollback_image_id": "sha256:v4",
                "candidate_image_id": "sha256:v11",
                "quality_evaluation": {
                    "sha256": "quality-sha",
                    "image_id": "sha256:v11",
                    "signature": {
                        "sha256": "frozen-signature-sha",
                        "public_key_sha256": "public-key-sha",
                    },
                },
            }
        }
        verify_quality.return_value = {
            "sha256": "quality-sha",
            "image_id": "sha256:v11",
            "signature": {
                "sha256": "current-signature-sha",
                "public_key_sha256": "public-key-sha",
            },
        }

        with self.assertRaisesRegex(
            ProductionBackupError,
            "quality evaluation identity",
        ):
            cutover_to_candidate(
                backup_dir=Path("/backup"),
                compose_file=Path("/compose.prod.yml"),
                project_name="zlb-production",
                active_container="zlb-mindmap",
                rollback_container="zlb-rollback-v4",
                image_ref="candidate-v11",
                expected_image_id="sha256:v11",
                quality_evaluation_path=Path("/quality.json"),
                quality_signature_path=Path("/quality.sig.json"),
                quality_public_key_path=Path("/quality-public.pem"),
                expected_quality_public_key_sha256="public-key-sha",
                data_volume="candidate-data",
                uploads_volume="candidate-uploads",
                bind_host="127.0.0.1",
                public_port=5173,
                health_url="http://127.0.0.1:5173/api/health",
                health_timeout_seconds=60,
            )

        inspect_json.assert_not_called()
        run_command.assert_not_called()

    @patch("backend.tools.production_backup._run_command")
    @patch("backend.tools.production_backup._inspect_json")
    @patch(
        "backend.tools.production_backup."
        "verify_candidate_quality_evaluation"
    )
    @patch("backend.tools.production_backup.verify_backup")
    def test_cutover_rejects_invalid_signature_before_inspect(
        self,
        verify_backup_mock,
        verify_quality,
        inspect_json,
        run_command,
    ):
        verify_backup_mock.return_value = {
            "metadata": {
                "rollback_image_id": "sha256:v4",
                "candidate_image_id": "sha256:v11",
                "quality_evaluation": {
                    "sha256": "quality-sha",
                    "image_id": "sha256:v11",
                },
            }
        }
        verify_quality.side_effect = ProductionBackupError(
            "Candidate quality signature verification failed"
        )

        with self.assertRaisesRegex(
            ProductionBackupError,
            "signature verification failed",
        ):
            cutover_to_candidate(
                backup_dir=Path("/backup"),
                compose_file=Path("/compose.prod.yml"),
                project_name="zlb-production",
                active_container="zlb-mindmap",
                rollback_container="zlb-rollback-v4",
                image_ref="candidate-v11",
                expected_image_id="sha256:v11",
                quality_evaluation_path=Path("/quality.json"),
                quality_signature_path=Path("/quality.sig.json"),
                quality_public_key_path=Path("/quality-public.pem"),
                expected_quality_public_key_sha256="public-key-sha",
                data_volume="candidate-data",
                uploads_volume="candidate-uploads",
                bind_host="127.0.0.1",
                public_port=5173,
                health_url="http://127.0.0.1:5173/api/health",
                health_timeout_seconds=60,
            )

        inspect_json.assert_not_called()
        run_command.assert_not_called()

    @patch("backend.tools.production_backup._run_command")
    @patch("backend.tools.production_backup._inspect_json")
    @patch(
        "backend.tools.production_backup."
        "verify_candidate_quality_evaluation"
    )
    @patch("backend.tools.production_backup.verify_backup")
    def test_cutover_rejects_backup_candidate_mismatch_before_inspect(
        self,
        verify_backup_mock,
        verify_quality,
        inspect_json,
        run_command,
    ):
        verify_backup_mock.return_value = {
            "metadata": {
                "rollback_image_id": "sha256:v4",
                "candidate_image_id": "sha256:other",
                "quality_evaluation": {
                    "sha256": "quality-sha",
                    "image_id": "sha256:other",
                },
            }
        }

        with self.assertRaisesRegex(
            ProductionBackupError,
            "candidate image identity does not match cutover",
        ):
            cutover_to_candidate(
                backup_dir=Path("/backup"),
                compose_file=Path("/compose.prod.yml"),
                project_name="zlb-production",
                active_container="zlb-mindmap",
                rollback_container="zlb-rollback-v4",
                image_ref="candidate-v11",
                expected_image_id="sha256:v11",
                quality_evaluation_path=Path("/quality.json"),
                quality_signature_path=Path("/quality.sig.json"),
                quality_public_key_path=Path("/quality-public.pem"),
                expected_quality_public_key_sha256="public-key-sha",
                data_volume="candidate-data",
                uploads_volume="candidate-uploads",
                bind_host="127.0.0.1",
                public_port=5173,
                health_url="http://127.0.0.1:5173/api/health",
                health_timeout_seconds=60,
            )

        verify_quality.assert_not_called()
        inspect_json.assert_not_called()
        run_command.assert_not_called()

    def test_freeze_and_cutover_cli_require_signed_quality_evaluation(self):
        command_lines = {
            "freeze": [
                "freeze",
                "--rollback-image",
                "rollback-v4",
                "--candidate-image",
                "candidate-v11",
                "--quality-evaluation",
                "/quality.json",
                "--quality-signature",
                "/quality.sig.json",
                "--quality-public-key",
                "/quality-public.pem",
                "--quality-public-key-sha256",
                "public-key-sha",
                "--output",
                "/backup",
            ],
            "cutover": [
                "cutover",
                "--backup-dir",
                "/backup",
                "--rollback-container",
                "zlb-rollback-v4",
                "--image-ref",
                "candidate-v11",
                "--expected-image-id",
                "sha256:v11",
                "--quality-evaluation",
                "/quality.json",
                "--quality-signature",
                "/quality.sig.json",
                "--quality-public-key",
                "/quality-public.pem",
                "--quality-public-key-sha256",
                "public-key-sha",
                "--data-volume",
                "candidate-data",
                "--uploads-volume",
                "candidate-uploads",
            ],
        }
        required_options = (
            "--quality-evaluation",
            "--quality-signature",
            "--quality-public-key",
            "--quality-public-key-sha256",
        )
        for command, argv in command_lines.items():
            for option in required_options:
                with self.subTest(command=command, missing=option):
                    missing_index = argv.index(option)
                    incomplete = (
                        argv[:missing_index] + argv[missing_index + 2 :]
                    )
                    with redirect_stderr(io.StringIO()):
                        with self.assertRaises(SystemExit) as raised:
                            _parser().parse_args(incomplete)
                    self.assertEqual(raised.exception.code, 2)

    @patch("backend.tools.production_backup._inspect_json")
    @patch("backend.tools.production_backup._optional_inspect_json")
    @patch("backend.tools.production_backup._run_command")
    def test_rollback_removes_candidate_and_restarts_exact_v4(
        self,
        run_command,
        optional_inspect_json,
        inspect_json,
    ):
        optional_inspect_json.return_value = {
            "Image": "sha256:v11",
            "State": {"Running": True, "Status": "running"},
        }
        optional_inspect_json.side_effect = [
            optional_inspect_json.return_value,
            None,
        ]
        inspect_json.side_effect = [
            {
                "Image": "sha256:v4",
                "State": {"Running": False},
            },
            {
                "Image": "sha256:v4",
                "State": {"Running": True},
            },
        ]

        result = rollback_to_preserved_container(
            active_container="zlb-mindmap",
            rollback_container="zlb-rollback-v4",
            expected_rollback_image_id="sha256:v4",
        )

        self.assertEqual(result["image_id"], "sha256:v4")
        self.assertEqual(
            run_command.call_args_list[0].args[0],
            ["docker", "rm", "--force", "zlb-mindmap"],
        )
        self.assertEqual(
            run_command.call_args_list[-1].args[0],
            ["docker", "start", "zlb-mindmap"],
        )

    @patch("backend.tools.production_backup._inspect_json")
    @patch("backend.tools.production_backup._optional_inspect_json")
    @patch("backend.tools.production_backup._run_command")
    def test_rollback_uses_plain_rm_for_created_candidate(
        self,
        run_command,
        optional_inspect_json,
        inspect_json,
    ):
        optional_inspect_json.side_effect = [
            {
                "Image": "sha256:v11",
                "State": {"Running": False, "Status": "created"},
            },
            None,
        ]
        inspect_json.side_effect = [
            {
                "Image": "sha256:v4",
                "State": {"Running": False},
            },
            {
                "Image": "sha256:v4",
                "State": {"Running": True},
            },
        ]

        rollback_to_preserved_container(
            active_container="zlb-mindmap",
            rollback_container="zlb-rollback-v4",
            expected_rollback_image_id="sha256:v4",
        )

        self.assertEqual(
            run_command.call_args_list[0].args[0],
            ["docker", "rm", "zlb-mindmap"],
        )

    @patch("backend.tools.production_backup._inspect_json")
    @patch("backend.tools.production_backup._optional_inspect_json")
    @patch("backend.tools.production_backup._run_command")
    def test_rollback_continues_when_rm_errors_but_name_is_released(
        self,
        run_command,
        optional_inspect_json,
        inspect_json,
    ):
        optional_inspect_json.side_effect = [
            {
                "Image": "sha256:v11",
                "State": {"Running": False, "Status": "created"},
            },
            None,
        ]
        inspect_json.side_effect = [
            {
                "Image": "sha256:v4",
                "State": {"Running": False},
            },
            {
                "Image": "sha256:v4",
                "State": {"Running": True},
            },
        ]

        def run_with_removal_race(args, **_kwargs):
            if args == ["docker", "rm", "zlb-mindmap"]:
                raise ProductionBackupError(
                    "removal of container is already in progress"
                )
            return ""

        run_command.side_effect = run_with_removal_race

        result = rollback_to_preserved_container(
            active_container="zlb-mindmap",
            rollback_container="zlb-rollback-v4",
            expected_rollback_image_id="sha256:v4",
        )

        self.assertEqual(result["status"], "running")
        self.assertIn(
            [
                "docker",
                "rename",
                "zlb-rollback-v4",
                "zlb-mindmap",
            ],
            [call.args[0] for call in run_command.call_args_list],
        )

    @patch("backend.tools.production_backup._inspect_json")
    def test_optional_inspect_only_swallows_not_found(self, inspect_json):
        inspect_json.side_effect = ProductionBackupError(
            "Command failed: docker container inspect missing: "
            "Error response from daemon: No such container: missing"
        )
        self.assertIsNone(
            _optional_inspect_json("container", "missing")
        )

        inspect_json.side_effect = ProductionBackupError(
            "Command failed: docker container inspect missing: "
            "Cannot connect to the Docker daemon"
        )
        with self.assertRaisesRegex(
            ProductionBackupError,
            "Cannot connect to the Docker daemon",
        ):
            _optional_inspect_json("container", "missing")


if __name__ == "__main__":
    unittest.main()
