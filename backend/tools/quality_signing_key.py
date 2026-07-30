from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Sequence

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)

from backend.app.config import _find_age_executable


TRUST_RECORD_SCHEMA_VERSION = "zlb-quality-signing-trust-record-v1"
AGE_ENCRYPT_TIMEOUT_SECONDS = 20
MAX_ENCRYPTED_PRIVATE_KEY_BYTES = 64 * 1024


class QualitySigningKeyError(RuntimeError):
    pass


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _validate_outputs(paths: Sequence[Path]) -> list[Path]:
    resolved = [path.expanduser().resolve() for path in paths]
    if len(set(resolved)) != len(resolved):
        raise QualitySigningKeyError(
            "quality signing key outputs must be distinct"
        )
    for path in resolved:
        if os.path.lexists(path):
            raise QualitySigningKeyError(
                f"quality signing key output already exists: {path}"
            )
    return resolved


def _write_new_file(path: Path, payload: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor: int | None = None
    created_by_us = False
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            mode,
        )
        created_by_us = True
        with os.fdopen(descriptor, "wb") as destination:
            descriptor = None
            destination.write(payload)
            destination.flush()
            os.fsync(destination.fileno())
        path.chmod(mode)
    except OSError as exc:
        if descriptor is not None:
            os.close(descriptor)
        if created_by_us:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        raise QualitySigningKeyError(
            "quality signing key output could not be written"
        ) from exc


def _encrypt_private_key(
    *,
    private_key_pem: bytearray,
    age_recipient: str,
) -> bytes:
    age_executable = _find_age_executable()
    if age_executable is None:
        raise QualitySigningKeyError(
            "quality signing age executable is unavailable"
        )
    try:
        completed = subprocess.run(
            [
                str(age_executable.resolve()),
                "--encrypt",
                "-r",
                age_recipient,
            ],
            input=private_key_pem,
            capture_output=True,
            check=False,
            timeout=AGE_ENCRYPT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise QualitySigningKeyError(
            "quality signing age encryption timed out"
        ) from exc
    except (OSError, subprocess.SubprocessError) as exc:
        raise QualitySigningKeyError(
            "quality signing age encryption could not start"
        ) from exc
    if completed.returncode != 0:
        raise QualitySigningKeyError(
            "quality signing age encryption failed"
        )
    if len(completed.stdout) > MAX_ENCRYPTED_PRIVATE_KEY_BYTES:
        raise QualitySigningKeyError(
            "quality signing encrypted private key is too large"
        )
    if not completed.stdout:
        raise QualitySigningKeyError(
            "quality signing encrypted private key is empty"
        )
    return completed.stdout


def generate_quality_signing_key(
    *,
    age_recipient: str,
    encrypted_private_key_path: Path,
    public_key_path: Path,
    trust_record_path: Path,
) -> dict[str, str]:
    normalized_recipient = age_recipient.strip()
    if not normalized_recipient:
        raise QualitySigningKeyError(
            "quality signing age recipient is required"
        )
    if (
        len(normalized_recipient) > 512
        or normalized_recipient.startswith("-")
        or any(
            ord(character) < 33 or ord(character) > 126
            for character in normalized_recipient
        )
    ):
        raise QualitySigningKeyError(
            "quality signing age recipient is invalid"
        )
    encrypted_path, public_path, trust_path = _validate_outputs(
        (
            encrypted_private_key_path,
            public_key_path,
            trust_record_path,
        )
    )

    private_key = Ed25519PrivateKey.generate()
    private_key_pem = bytearray(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    public_key_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    public_key_der = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    try:
        encrypted_private_key = _encrypt_private_key(
            private_key_pem=private_key_pem,
            age_recipient=normalized_recipient,
        )
    finally:
        private_key_pem[:] = b"\x00" * len(private_key_pem)

    trust_record = {
        "schema_version": TRUST_RECORD_SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "algorithm": "ed25519",
        "age_recipient": normalized_recipient,
        "public_key_sha256": _sha256_bytes(public_key_der),
        "public_key_pem_sha256": _sha256_bytes(public_key_pem),
        "encrypted_private_key_sha256": _sha256_bytes(
            encrypted_private_key
        ),
    }
    trust_record_bytes = (
        json.dumps(trust_record, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")

    created_paths: list[Path] = []
    try:
        _write_new_file(encrypted_path, encrypted_private_key, 0o600)
        created_paths.append(encrypted_path)
        _write_new_file(public_path, public_key_pem, 0o644)
        created_paths.append(public_path)
        _write_new_file(trust_path, trust_record_bytes, 0o644)
        created_paths.append(trust_path)
    except QualitySigningKeyError:
        for path in created_paths:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        raise
    return trust_record


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        allow_abbrev=False,
        description=(
            "Generate an Ed25519 quality-evaluator key whose private PEM is "
            "encrypted to an age recipient before any filesystem write."
        ),
    )
    parser.add_argument("--age-recipient", required=True)
    parser.add_argument(
        "--encrypted-private-key-output",
        type=Path,
        required=True,
    )
    parser.add_argument("--public-key-output", type=Path, required=True)
    parser.add_argument("--trust-record-output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        trust_record = generate_quality_signing_key(
            age_recipient=args.age_recipient,
            encrypted_private_key_path=(
                args.encrypted_private_key_output
            ),
            public_key_path=args.public_key_output,
            trust_record_path=args.trust_record_output,
        )
    except QualitySigningKeyError as exc:
        print(f"quality signing key generation failed: {exc}")
        return 2
    print(
        json.dumps(
            {
                "public_key_sha256": trust_record["public_key_sha256"],
                "encrypted_private_key_output": str(
                    args.encrypted_private_key_output.resolve()
                ),
                "public_key_output": str(
                    args.public_key_output.resolve()
                ),
                "trust_record_output": str(
                    args.trust_record_output.resolve()
                ),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
