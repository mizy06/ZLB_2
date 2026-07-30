from __future__ import annotations

import argparse
import base64
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)

from backend.app.config import _find_age_executable
from backend.tools import pdf_quality_oracle as quality_oracle_module
from backend.tools.pdf_quality_oracle import (
    QUALITY_ORACLE_SCHEMA_VERSION,
    QualityOracleError,
    evaluate_canary_report,
    load_quality_oracle,
)


EVALUATION_SCHEMA_VERSION = "pdf-page-knowledge-evaluation-v1"
EVALUATION_SIGNATURE_SCHEMA_VERSION = (
    "zlb-quality-evaluation-signature-v1"
)
AGE_DECRYPT_TIMEOUT_SECONDS = 20
MAX_ENCRYPTED_SIGNING_KEY_BYTES = 64 * 1024
MAX_DECRYPTED_SIGNING_KEY_BYTES = 16 * 1024


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sign_evaluation_artifact(
    *,
    evaluation_path: Path,
    private_key_pem: bytes | bytearray,
    signature_path: Path,
) -> dict[str, str]:
    try:
        evaluation_bytes = evaluation_path.read_bytes()
    except OSError as exc:
        raise QualityOracleError(
            f"evaluation artifact cannot be read for signing: {exc}"
        ) from exc
    try:
        private_key = serialization.load_pem_private_key(
            private_key_pem,
            password=None,
        )
    except (TypeError, ValueError) as exc:
        raise QualityOracleError(
            "evaluation signing key is not a valid PEM key"
        ) from exc
    if not isinstance(private_key, Ed25519PrivateKey):
        raise QualityOracleError(
            "evaluation signing key must be Ed25519"
        )
    public_key_der = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    payload = {
        "schema_version": EVALUATION_SIGNATURE_SCHEMA_VERSION,
        "algorithm": "ed25519",
        "artifact_sha256": _sha256_bytes(evaluation_bytes),
        "public_key_sha256": _sha256_bytes(public_key_der),
        "signature_base64": base64.b64encode(
            private_key.sign(evaluation_bytes)
        ).decode("ascii"),
    }
    signature_path.parent.mkdir(parents=True, exist_ok=True)
    signature_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return payload


def _read_bounded_encrypted_signing_key(path: Path) -> bytes:
    resolved_path = path.resolve()
    try:
        with resolved_path.open("rb") as source:
            payload = source.read(MAX_ENCRYPTED_SIGNING_KEY_BYTES + 1)
    except OSError as exc:
        raise QualityOracleError(
            "encrypted evaluation signing key cannot be read"
        ) from exc
    if len(payload) > MAX_ENCRYPTED_SIGNING_KEY_BYTES:
        raise QualityOracleError(
            "encrypted evaluation signing key is too large"
        )
    if not payload:
        raise QualityOracleError(
            "encrypted evaluation signing key is empty"
        )
    return payload


def _decrypt_age_signing_key(
    *,
    encrypted_private_key_path: Path,
    age_identity_path: Path,
) -> bytearray:
    encrypted_key = _read_bounded_encrypted_signing_key(
        encrypted_private_key_path
    )
    resolved_identity = age_identity_path.resolve()
    if not resolved_identity.is_file():
        raise QualityOracleError(
            "evaluation signing age identity does not exist"
        )
    age_executable = _find_age_executable()
    if age_executable is None:
        raise QualityOracleError(
            "evaluation signing age executable is unavailable"
        )
    try:
        completed = subprocess.run(
            [
                str(age_executable.resolve()),
                "--decrypt",
                "-i",
                str(resolved_identity),
            ],
            input=encrypted_key,
            capture_output=True,
            check=False,
            timeout=AGE_DECRYPT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise QualityOracleError(
            "evaluation signing age decryption timed out"
        ) from exc
    except (OSError, subprocess.SubprocessError) as exc:
        raise QualityOracleError(
            "evaluation signing age decryption could not start"
        ) from exc
    if completed.returncode != 0:
        raise QualityOracleError(
            "evaluation signing age decryption failed"
        )
    if len(completed.stdout) > MAX_DECRYPTED_SIGNING_KEY_BYTES:
        raise QualityOracleError(
            "decrypted evaluation signing key is too large"
        )
    if not completed.stdout:
        raise QualityOracleError(
            "decrypted evaluation signing key is empty"
        )
    private_key_pem = bytearray(completed.stdout)
    completed.stdout = b""
    return private_key_pem


def sign_evaluation_artifact_with_age_key(
    *,
    evaluation_path: Path,
    encrypted_private_key_path: Path,
    age_identity_path: Path,
    signature_path: Path,
) -> dict[str, str]:
    private_key_pem = _decrypt_age_signing_key(
        encrypted_private_key_path=encrypted_private_key_path,
        age_identity_path=age_identity_path,
    )
    try:
        return sign_evaluation_artifact(
            evaluation_path=evaluation_path,
            private_key_pem=private_key_pem,
            signature_path=signature_path,
        )
    finally:
        private_key_pem[:] = b"\x00" * len(private_key_pem)


def _load_report(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise QualityOracleError(
            f"canary report is missing: {path}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise QualityOracleError(
            f"canary report is not valid JSON: {exc.msg}"
        ) from exc
    if not isinstance(payload, dict):
        raise QualityOracleError("canary report must be a JSON object")
    return payload


def build_evaluation_artifact(
    *,
    report_path: Path,
    oracle_path: Path,
) -> dict[str, Any]:
    report = _load_report(report_path)
    source_sha256 = str(report.get("source_sha256") or "")
    selected_pages = report.get("selected_original_pages")
    if not isinstance(selected_pages, list):
        raise QualityOracleError(
            "canary report selected_original_pages is invalid"
        )
    oracle = load_quality_oracle(
        oracle_path,
        source_sha256=source_sha256,
        selected_pages=selected_pages,
    )
    evaluation = evaluate_canary_report(report, oracle)
    return {
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "canary_report": {
            "sha256": _sha256(report_path),
            "run_id": report.get("run_id"),
            "task_id": report.get("task_id"),
            "source_sha256": source_sha256,
            "selected_original_pages": selected_pages,
            "manifest": report.get("manifest"),
        },
        "quality_oracle": {
            "schema_version": QUALITY_ORACLE_SCHEMA_VERSION,
            "sha256": _sha256(oracle_path),
        },
        "evaluator": {
            "schema_version": EVALUATION_SCHEMA_VERSION,
            "module_sha256": _sha256(Path(__file__).resolve()),
            "quality_module_sha256": _sha256(
                Path(quality_oracle_module.__file__).resolve()
            ),
        },
        "evaluation": evaluation,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        allow_abbrev=False,
        description=(
            "Evaluate one PDF page-knowledge canary artifact against an "
            "external source-bound quality oracle."
        )
    )
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--oracle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--signing-key-age", type=Path)
    parser.add_argument("--signing-key-age-identity", type=Path)
    parser.add_argument("--signature-output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    signing_arguments = (
        args.signing_key_age,
        args.signing_key_age_identity,
        args.signature_output,
    )
    if any(signing_arguments) and not all(signing_arguments):
        parser.error(
            "--signing-key-age, --signing-key-age-identity, and "
            "--signature-output must be provided together"
        )
    try:
        artifact = build_evaluation_artifact(
            report_path=args.report.resolve(),
            oracle_path=args.oracle.resolve(),
        )
    except QualityOracleError as exc:
        print(f"quality evaluation failed: {exc}")
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    signature = None
    if args.signing_key_age is not None:
        try:
            signature = sign_evaluation_artifact_with_age_key(
                evaluation_path=args.output.resolve(),
                encrypted_private_key_path=args.signing_key_age.resolve(),
                age_identity_path=args.signing_key_age_identity.resolve(),
                signature_path=args.signature_output.resolve(),
            )
        except QualityOracleError as exc:
            print(f"quality evaluation signing failed: {exc}")
            return 2
    evaluation = artifact["evaluation"]
    print(
        json.dumps(
            {
                "passed": evaluation["passed"],
                "clean_pages": evaluation["page_state"][
                    "clean_page_count"
                ],
                "canonical_formulas": (
                    f"{evaluation['canonical_formulas']['exact_count']}/"
                    f"{evaluation['canonical_formulas']['expected_count']}"
                ),
                "required_coverage": (
                    f"{evaluation['required_coverage']['covered_count']}/"
                    f"{evaluation['required_coverage']['required_count']}"
                ),
                "output": str(args.output.resolve()),
                "signature_output": (
                    str(args.signature_output.resolve())
                    if signature is not None
                    else None
                ),
            },
            ensure_ascii=False,
        )
    )
    return 0 if evaluation["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
