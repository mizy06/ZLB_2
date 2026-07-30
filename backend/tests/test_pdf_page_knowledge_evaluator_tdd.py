from __future__ import annotations

import base64
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
)

from backend.tools.pdf_page_knowledge_evaluator import (
    QualityOracleError,
    build_evaluation_artifact,
    main,
    evaluate_canary_report,
    load_quality_oracle,
    sign_evaluation_artifact,
    sign_evaluation_artifact_with_age_key,
)
from backend.tools.pdf_quality_oracle import audit_formulas


SOURCE_SHA = "a" * 64
FIXTURE_ORACLE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "quantum_92page_26page_quality_oracle.json"
)


def _oracle_payload() -> dict:
    return {
        "schema_version": "pdf-page-quality-oracle-v1",
        "source_sha256": SOURCE_SHA,
        "selected_pages": [2, 6],
        "pages": {
            "2": {
                "expected_has_knowledge": True,
                "canonical_formulas": ["ε=hν"],
                "required_text": ["普朗克、爱因斯坦量子化"],
            },
            "6": {
                "expected_has_knowledge": True,
                "canonical_formulas": [
                    "hν=hc/λ=hcR(1/n²-1/n′²)",
                ],
                "required_text": ["右端应为能量差"],
            },
        },
    }


def _report_payload() -> dict:
    return {
        "complete": True,
        "run_id": "run-test",
        "task_id": "task-test",
        "source_sha256": SOURCE_SHA,
        "selected_original_pages": [2, 6],
        "provider": "qwen",
        "provider_endpoint": (
            "https://dashscope.aliyuncs.com/compatible-mode/v1"
        ),
        "text_model": "qwen3.7-max",
        "vision_model": "qwen3.7-plus",
        "qwen_production_profile": "standard",
        "extraction_profile": "direct_layout_fallback",
        "manifest": {
            "kind": "pdf_page_knowledge_canary",
            "source_sha256": SOURCE_SHA,
            "image_digest": "sha256:" + "d" * 64,
            "git_sha": "e" * 40 + "-dirty",
            "original_pages": [2, 6],
            "provider": "qwen",
            "provider_endpoint": (
                "https://dashscope.aliyuncs.com/compatible-mode/v1"
            ),
            "text_model": "qwen3.7-max",
            "vision_model": "qwen3.7-plus",
            "qwen_production_profile": "standard",
            "credential_source": "age",
            "extraction_profile": "direct_layout_fallback",
            "prompt": {
                "version": "prompt-v1",
                "sha256": "c" * 64,
            },
            "schema_versions": {
                "page_knowledge": "page-knowledge-v1",
                "page_layout": "page-layout-v1",
                "page_layout_nodes": "page-layout-nodes-v1",
            },
            "runner": {
                "module": "backend.tools.pdf_page_knowledge_canary",
                "sha256": "f" * 64,
            },
            "runtime_versions": {
                "python": "3.12.13",
                "pypdf": "6.14.2",
                "pdfplumber": "0.11.10",
                "pdfminer.six": "20260107",
                "pylatexenc": "2.11",
                "poppler": "25.03.0",
            },
        },
        "clean_accepted_original_pages": [2, 6],
        "degraded_original_pages": [],
        "failed_original_pages": [],
        "model_calls": {
            "request_policy_all_match": True,
            "request_policy_count": 4,
        },
        "pages": [
            {
                "original_page": 2,
                "status": "accepted",
                "has_knowledge": True,
                "nodes": [
                    {
                        "evidence_text": (
                            "普朗克、爱因斯坦量子化；光子能量 ε = hν"
                        ),
                        "formula_text": "ε = hν",
                    }
                ],
            },
            {
                "original_page": 6,
                "status": "accepted",
                "has_knowledge": True,
                "nodes": [
                    {
                        "evidence_text": (
                            "hν = hc/λ = hcR(1/n² − 1/n′²)，"
                            "右端应为能量差"
                        ),
                        "formula_text": (
                            "hν = hc/λ = hcR(1/n^2 - 1/n'^2)"
                        ),
                    }
                ],
            },
        ],
    }


class PdfPageKnowledgeEvaluatorTDDTests(unittest.TestCase):
    def test_formula_audit_accepts_general_notation_aliases(self):
        audit = audit_formulas(
            [
                "W_12 = B_12 ρ(ν、T)",
                (
                    "R_20 = (1/(sqrt(2) r_1^(3/2))) "
                    "(1-r/(2r_1))e^(-r/(2r_1))"
                ),
            ],
            [
                "W₁₂=B₁₂ρ(ν,T)",
                (
                    "R₂₀=(1/(√2r₁^(3/2)))"
                    "(1-r/(2r₁))e^(-r/(2r₁))"
                ),
            ],
        )

        self.assertEqual(audit["exact_count"], 2)

    def test_26_page_source_gold_is_complete_and_non_vacuous(self):
        payload = json.loads(FIXTURE_ORACLE.read_text(encoding="utf-8"))
        oracle = load_quality_oracle(
            FIXTURE_ORACLE,
            source_sha256=payload["source_sha256"],
            selected_pages=payload["selected_pages"],
        )

        self.assertEqual(len(oracle["selected_pages"]), 26)
        self.assertEqual(
            sum(
                len(page["canonical_formulas"])
                for page in oracle["pages"].values()
            ),
            53,
        )
        self.assertEqual(
            sum(
                len(page["required_text"])
                for page in oracle["pages"].values()
            ),
            66,
        )

    def test_load_oracle_binds_source_and_exact_selected_pages(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            oracle_path = Path(temp_dir) / "oracle.json"
            oracle_path.write_text(
                json.dumps(_oracle_payload(), ensure_ascii=False),
                encoding="utf-8",
            )

            oracle = load_quality_oracle(
                oracle_path,
                source_sha256=SOURCE_SHA,
                selected_pages=[2, 6],
            )

        self.assertEqual(oracle["selected_pages"], [2, 6])
        self.assertEqual(set(oracle["pages"]), {"2", "6"})

    def test_load_oracle_rejects_vacuous_selected_page(self):
        payload = _oracle_payload()
        payload["pages"]["6"] = {
            "canonical_formulas": [],
            "required_text": [],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            oracle_path = Path(temp_dir) / "oracle.json"
            oracle_path.write_text(
                json.dumps(payload, ensure_ascii=False),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                QualityOracleError,
                "at least one assertion",
            ):
                load_quality_oracle(
                    oracle_path,
                    source_sha256=SOURCE_SHA,
                    selected_pages=[2, 6],
                )

    def test_load_oracle_rejects_wrong_source_or_page_set(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            oracle_path = Path(temp_dir) / "oracle.json"
            oracle_path.write_text(
                json.dumps(_oracle_payload(), ensure_ascii=False),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                QualityOracleError,
                "source_sha256",
            ):
                load_quality_oracle(
                    oracle_path,
                    source_sha256="b" * 64,
                    selected_pages=[2, 6],
                )
            with self.assertRaisesRegex(
                QualityOracleError,
                "selected_pages",
            ):
                load_quality_oracle(
                    oracle_path,
                    source_sha256=SOURCE_SHA,
                    selected_pages=[6, 2],
                )

    def test_clean_complete_report_passes_all_quality_gates(self):
        result = evaluate_canary_report(
            _report_payload(),
            _oracle_payload(),
        )

        self.assertTrue(result["passed"])
        self.assertEqual(result["canonical_formulas"]["exact_count"], 2)
        self.assertEqual(result["canonical_formulas"]["exact_rate"], 1.0)
        self.assertEqual(result["required_coverage"]["covered_count"], 2)
        self.assertEqual(result["required_coverage"]["rate"], 1.0)
        self.assertTrue(result["page_state"]["all_clean"])
        self.assertTrue(result["model_call_policy"]["passed"])
        self.assertTrue(result["artifact_identity"]["passed"])

    def test_partial_formula_and_degraded_page_fail_gate(self):
        report = _report_payload()
        report["pages"][1]["nodes"][0]["formula_text"] = (
            "hν = hc/λ = hcR"
        )
        report["pages"][1]["status"] = "degraded"
        report["clean_accepted_original_pages"] = [2]
        report["degraded_original_pages"] = [6]

        result = evaluate_canary_report(report, _oracle_payload())

        self.assertFalse(result["passed"])
        self.assertEqual(result["canonical_formulas"]["exact_count"], 1)
        self.assertFalse(result["page_state"]["all_clean"])
        page_six = next(
            page for page in result["pages"] if page["page"] == 6
        )
        self.assertFalse(page_six["formula_audit"]["details"][0]["exact"])

    def test_missing_request_policy_evidence_fails_gate(self):
        report = _report_payload()
        report["model_calls"]["request_policy_count"] = 0

        result = evaluate_canary_report(report, _oracle_payload())

        self.assertFalse(result["passed"])
        self.assertFalse(result["model_call_policy"]["passed"])

    def test_missing_v49_manifest_identity_fails_gate(self):
        report = _report_payload()
        report.pop("manifest")

        result = evaluate_canary_report(report, _oracle_payload())

        self.assertFalse(result["passed"])
        self.assertFalse(result["artifact_identity"]["passed"])

    def test_approved_preview_profile_requires_exact_manifest_contract(self):
        report = _report_payload()
        report["qwen_production_profile"] = (
            "approved_cn_token_plan_preview"
        )
        report["manifest"]["qwen_production_profile"] = (
            "approved_cn_token_plan_preview"
        )
        report["provider_endpoint"] = (
            "https://token-plan.cn-beijing.maas.aliyuncs.com/"
            "compatible-mode/v1"
        )
        report["manifest"]["provider_endpoint"] = report[
            "provider_endpoint"
        ]
        report["text_model"] = "qwen3.8-max-preview"
        report["vision_model"] = "qwen3.8-max-preview"
        report["manifest"]["text_model"] = report["text_model"]
        report["manifest"]["vision_model"] = report["vision_model"]

        accepted = evaluate_canary_report(report, _oracle_payload())
        self.assertTrue(accepted["artifact_identity"]["passed"])

        report["manifest"]["vision_model"] = "qwen3.7-plus"
        rejected = evaluate_canary_report(report, _oracle_payload())
        self.assertFalse(rejected["artifact_identity"]["passed"])
        self.assertIn(
            "manifest_approved_profile_vision_model_mismatch",
            rejected["artifact_identity"]["issues"],
        )

    def test_evaluation_artifact_binds_report_and_oracle_hashes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report_path = root / "report.json"
            oracle_path = root / "oracle.json"
            report_path.write_text(
                json.dumps(_report_payload(), ensure_ascii=False),
                encoding="utf-8",
            )
            oracle_path.write_text(
                json.dumps(_oracle_payload(), ensure_ascii=False),
                encoding="utf-8",
            )

            artifact = build_evaluation_artifact(
                report_path=report_path,
                oracle_path=oracle_path,
            )

        self.assertTrue(artifact["evaluation"]["passed"])
        self.assertEqual(
            len(artifact["canary_report"]["sha256"]),
            64,
        )
        self.assertEqual(
            len(artifact["quality_oracle"]["sha256"]),
            64,
        )
        self.assertEqual(
            len(artifact["evaluator"]["module_sha256"]),
            64,
        )
        self.assertEqual(
            len(artifact["evaluator"]["quality_module_sha256"]),
            64,
        )

    def test_evaluation_artifact_can_be_signed_with_in_memory_ed25519(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            evaluation_path = root / "evaluation.json"
            signature_path = root / "evaluation.sig.json"
            private_key = Ed25519PrivateKey.generate()
            private_key_pem = private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
            evaluation_path.write_text(
                json.dumps(
                    {"schema_version": "test", "passed": True},
                    sort_keys=True,
                ),
                encoding="utf-8",
            )

            signature = sign_evaluation_artifact(
                evaluation_path=evaluation_path,
                private_key_pem=private_key_pem,
                signature_path=signature_path,
            )

            private_key.public_key().verify(
                base64.b64decode(signature["signature_base64"]),
                evaluation_path.read_bytes(),
            )
            self.assertEqual(
                signature["schema_version"],
                "zlb-quality-evaluation-signature-v1",
            )
            self.assertEqual(signature["algorithm"], "ed25519")
            self.assertEqual(len(signature["artifact_sha256"]), 64)
            self.assertEqual(len(signature["public_key_sha256"]), 64)
            self.assertEqual(
                json.loads(signature_path.read_text(encoding="utf-8")),
                signature,
            )

    def test_age_encrypted_ed25519_key_signs_without_plaintext_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            evaluation_path = root / "evaluation.json"
            signature_path = root / "evaluation.sig.json"
            encrypted_key_path = root / "attestation-private.pem.age"
            identity_path = root / "quality-signing-identity.txt"
            age_path = root / "age"
            private_key = Ed25519PrivateKey.generate()
            private_key_pem = private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
            evaluation_path.write_text(
                '{"schema_version":"test","passed":true}',
                encoding="utf-8",
            )
            encrypted_key_path.write_bytes(b"age-encrypted-private-key")
            identity_path.write_text(
                "AGE-SECRET-KEY-TEST-ONLY",
                encoding="utf-8",
            )
            age_path.write_text("test executable", encoding="utf-8")
            completed = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=private_key_pem,
                stderr=b"",
            )

            with (
                patch(
                    "backend.tools.pdf_page_knowledge_evaluator."
                    "_find_age_executable",
                    return_value=age_path,
                ),
                patch(
                    "backend.tools.pdf_page_knowledge_evaluator."
                    "subprocess.run",
                    return_value=completed,
                ) as run,
            ):
                signature = sign_evaluation_artifact_with_age_key(
                    evaluation_path=evaluation_path,
                    encrypted_private_key_path=encrypted_key_path,
                    age_identity_path=identity_path,
                    signature_path=signature_path,
                )

            private_key.public_key().verify(
                base64.b64decode(signature["signature_base64"]),
                evaluation_path.read_bytes(),
            )
            self.assertFalse(
                any(
                    path.suffix == ".pem"
                    for path in root.iterdir()
                )
            )
            run.assert_called_once_with(
                [
                    str(age_path.resolve()),
                    "--decrypt",
                    "-i",
                    str(identity_path.resolve()),
                ],
                input=b"age-encrypted-private-key",
                capture_output=True,
                check=False,
                timeout=20,
            )

    def test_age_signing_key_failures_are_bounded_and_sanitized(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            evaluation_path = root / "evaluation.json"
            signature_path = root / "evaluation.sig.json"
            encrypted_key_path = root / "attestation-private.pem.age"
            identity_path = root / "quality-signing-identity.txt"
            age_path = root / "age"
            evaluation_path.write_text("{}", encoding="utf-8")
            encrypted_key_path.write_bytes(b"age-encrypted-private-key")
            identity_path.write_text(
                "AGE-SECRET-KEY-TEST-ONLY",
                encoding="utf-8",
            )
            age_path.write_text("test executable", encoding="utf-8")

            missing_identity = root / "missing-identity.txt"
            with self.assertRaisesRegex(
                QualityOracleError,
                "age identity does not exist",
            ):
                sign_evaluation_artifact_with_age_key(
                    evaluation_path=evaluation_path,
                    encrypted_private_key_path=encrypted_key_path,
                    age_identity_path=missing_identity,
                    signature_path=signature_path,
                )

            with patch(
                "backend.tools.pdf_page_knowledge_evaluator."
                "_find_age_executable",
                return_value=None,
            ):
                with self.assertRaisesRegex(
                    QualityOracleError,
                    "age executable is unavailable",
                ):
                    sign_evaluation_artifact_with_age_key(
                        evaluation_path=evaluation_path,
                        encrypted_private_key_path=encrypted_key_path,
                        age_identity_path=identity_path,
                        signature_path=signature_path,
                    )

            with (
                patch(
                    "backend.tools.pdf_page_knowledge_evaluator."
                    "_find_age_executable",
                    return_value=age_path,
                ),
                patch(
                    "backend.tools.pdf_page_knowledge_evaluator."
                    "subprocess.run",
                    side_effect=subprocess.TimeoutExpired(
                        cmd=["age"],
                        timeout=20,
                    ),
                ),
            ):
                with self.assertRaisesRegex(
                    QualityOracleError,
                    "age decryption timed out",
                ):
                    sign_evaluation_artifact_with_age_key(
                        evaluation_path=evaluation_path,
                        encrypted_private_key_path=encrypted_key_path,
                        age_identity_path=identity_path,
                        signature_path=signature_path,
                    )

            leaked_key = "PRIVATE-KEY-MATERIAL-MUST-NOT-APPEAR"
            failed = subprocess.CompletedProcess(
                args=[],
                returncode=1,
                stdout=b"",
                stderr=leaked_key.encode("utf-8"),
            )
            with (
                patch(
                    "backend.tools.pdf_page_knowledge_evaluator."
                    "_find_age_executable",
                    return_value=age_path,
                ),
                patch(
                    "backend.tools.pdf_page_knowledge_evaluator."
                    "subprocess.run",
                    return_value=failed,
                ),
            ):
                with self.assertRaises(QualityOracleError) as raised:
                    sign_evaluation_artifact_with_age_key(
                        evaluation_path=evaluation_path,
                        encrypted_private_key_path=encrypted_key_path,
                        age_identity_path=identity_path,
                        signature_path=signature_path,
                    )
            self.assertIn("age decryption failed", str(raised.exception))
            self.assertNotIn(leaked_key, str(raised.exception))

            x25519_private_key_pem = X25519PrivateKey.generate().private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
            wrong_type = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=x25519_private_key_pem,
                stderr=b"",
            )
            with (
                patch(
                    "backend.tools.pdf_page_knowledge_evaluator."
                    "_find_age_executable",
                    return_value=age_path,
                ),
                patch(
                    "backend.tools.pdf_page_knowledge_evaluator."
                    "subprocess.run",
                    return_value=wrong_type,
                ),
            ):
                with self.assertRaisesRegex(
                    QualityOracleError,
                    "must be Ed25519",
                ):
                    sign_evaluation_artifact_with_age_key(
                        evaluation_path=evaluation_path,
                        encrypted_private_key_path=encrypted_key_path,
                        age_identity_path=identity_path,
                        signature_path=signature_path,
                    )

            oversized = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=b"x" * 16_385,
                stderr=b"",
            )
            with (
                patch(
                    "backend.tools.pdf_page_knowledge_evaluator."
                    "_find_age_executable",
                    return_value=age_path,
                ),
                patch(
                    "backend.tools.pdf_page_knowledge_evaluator."
                    "subprocess.run",
                    return_value=oversized,
                ),
            ):
                with self.assertRaisesRegex(
                    QualityOracleError,
                    "decrypted evaluation signing key is too large",
                ):
                    sign_evaluation_artifact_with_age_key(
                        evaluation_path=evaluation_path,
                        encrypted_private_key_path=encrypted_key_path,
                        age_identity_path=identity_path,
                        signature_path=signature_path,
                    )

            encrypted_key_path.write_bytes(b"x" * 65_537)
            with self.assertRaisesRegex(
                QualityOracleError,
                "encrypted evaluation signing key is too large",
            ):
                sign_evaluation_artifact_with_age_key(
                    evaluation_path=evaluation_path,
                    encrypted_private_key_path=encrypted_key_path,
                    age_identity_path=identity_path,
                    signature_path=signature_path,
                )

    def test_age_signing_cli_requires_complete_parameter_group(self):
        common = [
            "--report",
            "report.json",
            "--oracle",
            "oracle.json",
            "--output",
            "evaluation.json",
        ]
        incomplete_groups = (
            ["--signing-key-age", "key.pem.age"],
            ["--signing-key-age-identity", "identity.txt"],
            ["--signature-output", "evaluation.sig.json"],
            [
                "--signing-key-age",
                "key.pem.age",
                "--signature-output",
                "evaluation.sig.json",
            ],
        )
        for arguments in incomplete_groups:
            with self.subTest(arguments=arguments):
                with self.assertRaises(SystemExit):
                    main([*common, *arguments])

        with self.assertRaises(SystemExit):
            main(
                [
                    *common,
                    "--signing-key",
                    "plaintext-private.pem",
                    "--signature-output",
                    "evaluation.sig.json",
                ]
            )


if __name__ == "__main__":
    unittest.main()
