from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import tarfile
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Sequence
from urllib.parse import quote

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PublicKey,
)

from backend.tools import (
    pdf_page_knowledge_evaluator as evaluator_module,
)
from backend.tools import pdf_quality_oracle as quality_oracle_module
from backend.tools.pdf_page_knowledge_evaluator import (
    EVALUATION_SCHEMA_VERSION,
    EVALUATION_SIGNATURE_SCHEMA_VERSION,
)


BACKUP_SCHEMA_VERSION = "zlb-production-backup-v1"
DATA_MOUNT_DESTINATION = "/app/.data/mindmap_engine"
UPLOADS_MOUNT_DESTINATION = "/app/backend/uploads"
BLACKBOARD_FILENAME = "blackboard.sqlite3"
CONTAINER_REMOVE_TIMEOUT_SECONDS = 15.0
CONTAINER_REMOVE_POLL_SECONDS = 0.25


class ProductionBackupError(RuntimeError):
    pass


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _require_mapping(
    value: Any,
    *,
    field: str,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProductionBackupError(
            f"Candidate quality evaluation field is invalid: {field}"
        )
    return value


def verify_quality_evaluation_signature(
    *,
    evaluation_path: Path,
    signature_path: Path,
    public_key_path: Path,
    expected_public_key_sha256: str,
) -> dict[str, str]:
    if not _is_sha256(expected_public_key_sha256):
        raise ProductionBackupError(
            "Candidate quality public key trust anchor is not a valid "
            "SHA-256 digest"
        )
    resolved_evaluation = evaluation_path.resolve()
    resolved_signature = signature_path.resolve()
    resolved_public_key = public_key_path.resolve()
    try:
        evaluation_bytes = resolved_evaluation.read_bytes()
    except OSError as exc:
        raise ProductionBackupError(
            f"Cannot read candidate quality evaluation: {exc}"
        ) from exc
    try:
        signature_payload = json.loads(
            resolved_signature.read_text(encoding="utf-8")
        )
    except FileNotFoundError as exc:
        raise ProductionBackupError(
            f"Candidate quality signature does not exist: "
            f"{resolved_signature}"
        ) from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ProductionBackupError(
            f"Cannot read candidate quality signature: {exc}"
        ) from exc
    if not isinstance(signature_payload, dict):
        raise ProductionBackupError(
            "Candidate quality signature must be a JSON object"
        )
    if (
        signature_payload.get("schema_version")
        != EVALUATION_SIGNATURE_SCHEMA_VERSION
        or signature_payload.get("algorithm") != "ed25519"
    ):
        raise ProductionBackupError(
            "Candidate quality signature schema or algorithm is unsupported"
        )
    artifact_sha256 = hashlib.sha256(evaluation_bytes).hexdigest()
    if signature_payload.get("artifact_sha256") != artifact_sha256:
        raise ProductionBackupError(
            "Candidate quality signature artifact SHA-256 mismatch"
        )
    try:
        signature = base64.b64decode(
            signature_payload.get("signature_base64", ""),
            validate=True,
        )
    except (binascii.Error, ValueError, TypeError) as exc:
        raise ProductionBackupError(
            "Candidate quality signature encoding is invalid"
        ) from exc
    if len(signature) != 64:
        raise ProductionBackupError(
            "Candidate quality signature length is invalid"
        )
    try:
        public_key_bytes = resolved_public_key.read_bytes()
        public_key = serialization.load_pem_public_key(public_key_bytes)
    except FileNotFoundError as exc:
        raise ProductionBackupError(
            f"Candidate quality public key does not exist: "
            f"{resolved_public_key}"
        ) from exc
    except (OSError, TypeError, ValueError) as exc:
        raise ProductionBackupError(
            "Candidate quality public key is invalid"
        ) from exc
    if not isinstance(public_key, Ed25519PublicKey):
        raise ProductionBackupError(
            "Candidate quality public key must be Ed25519"
        )
    public_key_der = public_key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    public_key_sha256 = hashlib.sha256(public_key_der).hexdigest()
    if public_key_sha256 != expected_public_key_sha256:
        raise ProductionBackupError(
            "Candidate quality public key is not trusted"
        )
    if signature_payload.get("public_key_sha256") != public_key_sha256:
        raise ProductionBackupError(
            "Candidate quality signature public key identity mismatch"
        )
    try:
        public_key.verify(signature, evaluation_bytes)
    except InvalidSignature as exc:
        raise ProductionBackupError(
            "Candidate quality signature verification failed"
        ) from exc
    return {
        "schema_version": EVALUATION_SIGNATURE_SCHEMA_VERSION,
        "algorithm": "ed25519",
        "sha256": _sha256_file(resolved_signature),
        "artifact_sha256": artifact_sha256,
        "public_key_sha256": public_key_sha256,
        "trust_anchor_sha256": expected_public_key_sha256,
    }


def verify_candidate_quality_evaluation(
    path: Path,
    *,
    expected_image_id: str,
    signature_path: Path,
    public_key_path: Path,
    expected_public_key_sha256: str,
) -> dict[str, Any]:
    evaluation_path = path.resolve()
    signature_identity = verify_quality_evaluation_signature(
        evaluation_path=evaluation_path,
        signature_path=signature_path,
        public_key_path=public_key_path,
        expected_public_key_sha256=expected_public_key_sha256,
    )
    try:
        payload = json.loads(evaluation_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ProductionBackupError(
            f"Candidate quality evaluation does not exist: {evaluation_path}"
        ) from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ProductionBackupError(
            f"Cannot read candidate quality evaluation: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise ProductionBackupError(
            "Candidate quality evaluation must be a JSON object"
        )
    if payload.get("schema_version") != EVALUATION_SCHEMA_VERSION:
        raise ProductionBackupError(
            "Candidate quality evaluation schema is unsupported"
        )

    canary = _require_mapping(
        payload.get("canary_report"),
        field="canary_report",
    )
    manifest = _require_mapping(
        canary.get("manifest"),
        field="canary_report.manifest",
    )
    selected_pages = canary.get("selected_original_pages")
    if (
        not isinstance(selected_pages, list)
        or not selected_pages
        or any(
            not isinstance(page, int) or isinstance(page, bool) or page < 1
            for page in selected_pages
        )
        or len(selected_pages) != len(set(selected_pages))
    ):
        raise ProductionBackupError(
            "Candidate quality evaluation selected pages are invalid"
        )
    source_sha256 = canary.get("source_sha256")
    if not _is_sha256(source_sha256):
        raise ProductionBackupError(
            "Candidate quality evaluation source SHA-256 is invalid"
        )
    if (
        manifest.get("source_sha256") != source_sha256
        or manifest.get("original_pages") != selected_pages
    ):
        raise ProductionBackupError(
            "Candidate quality evaluation manifest does not match its report"
        )
    if manifest.get("image_digest") != expected_image_id:
        raise ProductionBackupError(
            "Candidate quality evaluation does not match the candidate "
            "image identity"
        )
    expected_manifest = {
        "kind": "pdf_page_knowledge_canary",
        "provider": "qwen",
        "credential_source": "age",
        "extraction_profile": "direct_layout_fallback",
    }
    if any(
        manifest.get(field) != expected
        for field, expected in expected_manifest.items()
    ):
        raise ProductionBackupError(
            "Candidate quality evaluation manifest is not production-eligible"
        )
    if quality_oracle_module.qwen_manifest_profile_issues(manifest):
        raise ProductionBackupError(
            "Candidate quality evaluation Qwen production profile "
            "is not eligible"
        )
    for field in ("sha256",):
        if not _is_sha256(canary.get(field)):
            raise ProductionBackupError(
                f"Candidate quality evaluation {field} is invalid"
            )
    for field in ("run_id", "task_id"):
        value = canary.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ProductionBackupError(
                f"Candidate quality evaluation {field} is missing"
            )

    quality_oracle = _require_mapping(
        payload.get("quality_oracle"),
        field="quality_oracle",
    )
    evaluator = _require_mapping(
        payload.get("evaluator"),
        field="evaluator",
    )
    if not _is_sha256(quality_oracle.get("sha256")):
        raise ProductionBackupError(
            "Candidate quality oracle SHA-256 is invalid"
        )
    expected_evaluator_identity = {
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "module_sha256": _sha256_file(
            Path(evaluator_module.__file__).resolve()
        ),
        "quality_module_sha256": _sha256_file(
            Path(quality_oracle_module.__file__).resolve()
        ),
    }
    if any(
        evaluator.get(field) != expected
        for field, expected in expected_evaluator_identity.items()
    ):
        raise ProductionBackupError(
            "Candidate quality evaluator identity is invalid"
        )

    result = _require_mapping(
        payload.get("evaluation"),
        field="evaluation",
    )
    if result.get("passed") is not True:
        raise ProductionBackupError(
            "Candidate quality evaluation did not pass"
        )
    gate_names = (
        "page_state",
        "model_call_policy",
        "artifact_identity",
        "canonical_formulas",
        "required_coverage",
        "has_knowledge",
    )
    gates = {
        name: _require_mapping(
            result.get(name),
            field=f"evaluation.{name}",
        )
        for name in gate_names
    }
    if any(gate.get("passed") is not True for gate in gates.values()):
        raise ProductionBackupError(
            "Candidate quality evaluation contains a failed sub-gate"
        )

    page_state = gates["page_state"]
    selected_page_count = page_state.get("selected_page_count")
    if (
        page_state.get("all_clean") is not True
        or selected_page_count != len(selected_pages)
        or page_state.get("clean_page_count") != len(selected_pages)
        or page_state.get("degraded_pages") != []
        or page_state.get("failed_pages") != []
    ):
        raise ProductionBackupError(
            "Candidate quality evaluation page-state proof is incomplete"
        )
    model_policy = gates["model_call_policy"]
    if (
        model_policy.get("request_policy_all_match") is not True
        or not isinstance(model_policy.get("request_policy_count"), int)
        or isinstance(model_policy.get("request_policy_count"), bool)
        or model_policy["request_policy_count"] < 1
    ):
        raise ProductionBackupError(
            "Candidate quality evaluation model-call proof is incomplete"
        )
    artifact_identity = gates["artifact_identity"]
    if artifact_identity.get("issues") != []:
        raise ProductionBackupError(
            "Candidate quality evaluation artifact identity is incomplete"
        )
    formulas = gates["canonical_formulas"]
    expected_formula_count = formulas.get("expected_count")
    if (
        not isinstance(expected_formula_count, int)
        or isinstance(expected_formula_count, bool)
        or expected_formula_count < 1
        or formulas.get("exact_count") != expected_formula_count
    ):
        raise ProductionBackupError(
            "Candidate quality evaluation formula proof is incomplete"
        )
    coverage = gates["required_coverage"]
    required_count = coverage.get("required_count")
    if (
        not isinstance(required_count, int)
        or isinstance(required_count, bool)
        or required_count < 1
        or coverage.get("covered_count") != required_count
    ):
        raise ProductionBackupError(
            "Candidate quality evaluation coverage proof is incomplete"
        )
    knowledge = gates["has_knowledge"]
    assertion_count = knowledge.get("assertion_count")
    if (
        not isinstance(assertion_count, int)
        or isinstance(assertion_count, bool)
        or assertion_count < 1
    ):
        raise ProductionBackupError(
            "Candidate quality evaluation knowledge proof is incomplete"
        )

    evaluation_sha256 = _sha256_file(evaluation_path)
    if evaluation_sha256 != signature_identity["artifact_sha256"]:
        raise ProductionBackupError(
            "Candidate quality evaluation changed during verification"
        )
    return {
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "sha256": evaluation_sha256,
        "image_id": expected_image_id,
        "run_id": canary["run_id"],
        "task_id": canary["task_id"],
        "source_sha256": source_sha256,
        "selected_page_count": len(selected_pages),
        "canary_report_sha256": canary["sha256"],
        "quality_oracle_sha256": quality_oracle["sha256"],
        "evaluator_module_sha256": evaluator["module_sha256"],
        "quality_module_sha256": evaluator["quality_module_sha256"],
        "signature": signature_identity,
    }


def _sqlite_uri(path: Path) -> str:
    return f"file:{quote(str(path.resolve()), safe='/')}?mode=ro"


def _sqlite_quick_check(path: Path) -> None:
    try:
        with sqlite3.connect(_sqlite_uri(path), uri=True) as connection:
            rows = connection.execute("PRAGMA quick_check").fetchall()
    except sqlite3.Error as exc:
        raise ProductionBackupError(
            f"SQLite quick_check failed for {path}: {exc}"
        ) from exc
    if rows != [("ok",)]:
        raise ProductionBackupError(
            f"SQLite quick_check failed for {path}: {rows!r}"
        )


def _backup_sqlite(source: Path, target: Path) -> None:
    if not source.is_file():
        raise ProductionBackupError(
            f"SQLite source does not exist: {source}"
        )
    if target.exists():
        raise ProductionBackupError(
            f"SQLite backup target already exists: {target}"
        )
    _sqlite_quick_check(source)
    try:
        with sqlite3.connect(_sqlite_uri(source), uri=True) as source_db:
            with sqlite3.connect(target) as target_db:
                source_db.backup(target_db, pages=256, sleep=0.05)
    except sqlite3.Error as exc:
        raise ProductionBackupError(
            f"SQLite online backup failed: {exc}"
        ) from exc
    _sqlite_quick_check(target)


def _relative_paths(root: Path) -> list[Path]:
    if not root.exists():
        return []
    if not root.is_dir():
        raise ProductionBackupError(f"Snapshot source is not a directory: {root}")
    paths: list[Path] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ProductionBackupError(
                f"Snapshot source contains a symlink: {path}"
            )
        if not path.is_dir() and not path.is_file():
            raise ProductionBackupError(
                f"Snapshot source contains a special file: {path}"
            )
        paths.append(path.relative_to(root))
    return paths


def _snapshot_tree(
    root: Path,
    archive_path: Path,
    *,
    include: Callable[[Path], bool] | None = None,
) -> list[dict[str, Any]]:
    source_paths = [
        relative
        for relative in _relative_paths(root)
        if include is None or include(relative)
    ]
    files: list[dict[str, Any]] = []
    with tarfile.open(
        archive_path,
        mode="w:gz",
        format=tarfile.PAX_FORMAT,
    ) as archive:
        for relative in source_paths:
            source = root / relative
            archive.add(
                source,
                arcname=relative.as_posix(),
                recursive=False,
            )
            if source.is_file():
                files.append(
                    {
                        "path": relative.as_posix(),
                        "size": source.stat().st_size,
                        "sha256": _sha256_file(source),
                    }
                )
    return files


def _artifact(path: Path, source_files: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "path": path.name,
        "size": path.stat().st_size,
        "sha256": _sha256_file(path),
        "source_file_count": len(source_files),
        "source_bytes": sum(item["size"] for item in source_files),
        "source_files": source_files,
    }


def _write_manifest(destination: Path, manifest: dict[str, Any]) -> None:
    manifest_path = destination / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            manifest,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    os.chmod(manifest_path, 0o600)
    digest = _sha256_file(manifest_path)
    digest_path = destination / "manifest.sha256"
    digest_path.write_text(
        f"{digest}  manifest.json\n",
        encoding="ascii",
    )
    os.chmod(digest_path, 0o600)


def create_backup(
    *,
    data_dir: Path,
    uploads_dir: Path,
    destination: Path,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data_root = data_dir.resolve()
    uploads_root = uploads_dir.resolve()
    backup_root = destination.resolve()
    if backup_root.exists():
        raise ProductionBackupError(
            f"Backup destination already exists: {backup_root}"
        )
    if not data_root.is_dir():
        raise ProductionBackupError(
            f"Data directory does not exist: {data_root}"
        )
    if not uploads_root.is_dir():
        raise ProductionBackupError(
            f"Uploads directory does not exist: {uploads_root}"
        )
    backup_root.mkdir(parents=True, mode=0o700)

    database_target = backup_root / BLACKBOARD_FILENAME
    _backup_sqlite(data_root / BLACKBOARD_FILENAME, database_target)

    assets_archive = backup_root / "assets.tar.gz"
    assets_files = _snapshot_tree(data_root / "assets", assets_archive)

    uploads_archive = backup_root / "uploads.tar.gz"
    uploads_files = _snapshot_tree(uploads_root, uploads_archive)

    data_archive = backup_root / "data-files.tar.gz"

    def include_data_file(relative: Path) -> bool:
        top_level = relative.parts[0] if relative.parts else ""
        return top_level not in {
            "assets",
            BLACKBOARD_FILENAME,
            f"{BLACKBOARD_FILENAME}-shm",
            f"{BLACKBOARD_FILENAME}-wal",
        }

    data_files = _snapshot_tree(
        data_root,
        data_archive,
        include=include_data_file,
    )
    manifest = {
        "schema_version": BACKUP_SCHEMA_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "source": {
            "data_dir": str(data_root),
            "uploads_dir": str(uploads_root),
        },
        "metadata": dict(metadata or {}),
        "artifacts": {
            "database": {
                "path": database_target.name,
                "size": database_target.stat().st_size,
                "sha256": _sha256_file(database_target),
                "quick_check": "ok",
            },
            "assets": _artifact(assets_archive, assets_files),
            "uploads": _artifact(uploads_archive, uploads_files),
            "data_files": _artifact(data_archive, data_files),
        },
    }
    _write_manifest(backup_root, manifest)
    verify_backup(backup_root)
    return manifest


def _safe_archive_members(archive_path: Path) -> list[tarfile.TarInfo]:
    try:
        with tarfile.open(archive_path, mode="r:gz") as archive:
            members = archive.getmembers()
    except (tarfile.TarError, OSError) as exc:
        raise ProductionBackupError(
            f"Cannot read backup archive {archive_path}: {exc}"
        ) from exc
    for member in members:
        relative = PurePosixPath(member.name)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or member.issym()
            or member.islnk()
            or not (member.isdir() or member.isfile())
        ):
            raise ProductionBackupError(
                f"Unsafe archive member in {archive_path}: {member.name}"
            )
    return members


def _load_manifest(backup_dir: Path) -> dict[str, Any]:
    manifest_path = backup_dir / "manifest.json"
    digest_path = backup_dir / "manifest.sha256"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected_digest = digest_path.read_text(encoding="ascii").split()[0]
    except (OSError, ValueError, IndexError, json.JSONDecodeError) as exc:
        raise ProductionBackupError(
            f"Cannot read backup manifest from {backup_dir}: {exc}"
        ) from exc
    if manifest.get("schema_version") != BACKUP_SCHEMA_VERSION:
        raise ProductionBackupError("Unsupported backup manifest schema")
    actual_digest = _sha256_file(manifest_path)
    if actual_digest != expected_digest:
        raise ProductionBackupError("Backup manifest SHA-256 mismatch")
    return manifest


def verify_backup(backup_dir: Path) -> dict[str, Any]:
    root = backup_dir.resolve()
    manifest = _load_manifest(root)
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        raise ProductionBackupError("Backup manifest has no artifacts")
    for name in ("database", "assets", "uploads", "data_files"):
        artifact = artifacts.get(name)
        if not isinstance(artifact, dict):
            raise ProductionBackupError(
                f"Backup manifest is missing artifact: {name}"
            )
        path = root / str(artifact.get("path") or "")
        if not path.is_file():
            raise ProductionBackupError(
                f"Backup artifact does not exist: {path}"
            )
        if path.stat().st_size != artifact.get("size"):
            raise ProductionBackupError(
                f"Backup artifact size mismatch: {path}"
            )
        if _sha256_file(path) != artifact.get("sha256"):
            raise ProductionBackupError(
                f"Backup artifact SHA-256 mismatch: {path}"
            )
        if name != "database":
            members = _safe_archive_members(path)
            regular_files = sum(member.isfile() for member in members)
            if regular_files != artifact.get("source_file_count"):
                raise ProductionBackupError(
                    f"Backup archive file-count mismatch: {path}"
                )
    _sqlite_quick_check(root / artifacts["database"]["path"])
    return manifest


def _require_empty_destination(path: Path) -> None:
    if path.exists() and (not path.is_dir() or any(path.iterdir())):
        raise ProductionBackupError(
            f"Restore destination must be an empty directory: {path}"
        )
    path.mkdir(parents=True, exist_ok=True)


def _extract_archive(archive_path: Path, destination: Path) -> None:
    _safe_archive_members(archive_path)
    try:
        with tarfile.open(archive_path, mode="r:gz") as archive:
            archive.extractall(destination)
    except (tarfile.TarError, OSError) as exc:
        raise ProductionBackupError(
            f"Cannot restore archive {archive_path}: {exc}"
        ) from exc


def _chown_tree(root: Path, uid: int, gid: int) -> None:
    os.chown(root, uid, gid)
    for path in root.rglob("*"):
        os.chown(path, uid, gid, follow_symlinks=False)


def restore_backup(
    *,
    backup_dir: Path,
    data_dir: Path,
    uploads_dir: Path,
    owner_uid: int | None = None,
    owner_gid: int | None = None,
) -> dict[str, Any]:
    if (owner_uid is None) != (owner_gid is None):
        raise ProductionBackupError(
            "Restore owner UID and GID must be provided together"
        )
    root = backup_dir.resolve()
    manifest = verify_backup(root)
    data_root = data_dir.resolve()
    uploads_root = uploads_dir.resolve()
    _require_empty_destination(data_root)
    _require_empty_destination(uploads_root)
    artifacts = manifest["artifacts"]

    _extract_archive(
        root / artifacts["data_files"]["path"],
        data_root,
    )
    assets_root = data_root / "assets"
    assets_root.mkdir()
    _extract_archive(
        root / artifacts["assets"]["path"],
        assets_root,
    )
    shutil.copy2(
        root / artifacts["database"]["path"],
        data_root / BLACKBOARD_FILENAME,
    )
    _extract_archive(
        root / artifacts["uploads"]["path"],
        uploads_root,
    )
    _sqlite_quick_check(data_root / BLACKBOARD_FILENAME)
    if owner_uid is not None and owner_gid is not None:
        _chown_tree(data_root, owner_uid, owner_gid)
        _chown_tree(uploads_root, owner_uid, owner_gid)
    return manifest


def _run_command(
    args: list[str],
    *,
    env: dict[str, str] | None = None,
) -> str:
    try:
        completed = subprocess.run(
            args,
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        stderr = (
            exc.stderr.strip()
            if isinstance(exc, subprocess.CalledProcessError) and exc.stderr
            else str(exc)
        )
        raise ProductionBackupError(
            f"Command failed: {' '.join(args)}: {stderr}"
        ) from exc
    return completed.stdout


def _inspect_json(object_type: str, name: str) -> dict[str, Any]:
    output = _run_command(["docker", object_type, "inspect", name])
    try:
        payload = json.loads(output)
        result = payload[0]
    except (json.JSONDecodeError, IndexError, TypeError) as exc:
        raise ProductionBackupError(
            f"Cannot parse docker {object_type} inspect for {name}"
        ) from exc
    if not isinstance(result, dict):
        raise ProductionBackupError(
            f"Unexpected docker {object_type} inspect payload for {name}"
        )
    return result


def _optional_inspect_json(
    object_type: str,
    name: str,
) -> dict[str, Any] | None:
    try:
        return _inspect_json(object_type, name)
    except ProductionBackupError as exc:
        message = str(exc).lower()
        not_found_markers = (
            f"no such {object_type.lower()}",
            "no such object",
        )
        if any(marker in message for marker in not_found_markers):
            return None
        raise


def _assert_tcp_port_available(bind_host: str, port: int) -> None:
    if not bind_host:
        raise ProductionBackupError("TCP bind host must be non-empty")
    if not 1 <= port <= 65535:
        raise ProductionBackupError(
            f"TCP port must be between 1 and 65535: {port}"
        )
    try:
        addresses = socket.getaddrinfo(
            bind_host,
            port,
            type=socket.SOCK_STREAM,
            flags=socket.AI_PASSIVE,
        )
    except socket.gaierror as exc:
        raise ProductionBackupError(
            f"Cannot resolve TCP bind host {bind_host}: {exc}"
        ) from exc
    probes: list[socket.socket] = []
    seen: set[tuple[int, tuple[Any, ...]]] = set()
    try:
        for family, socket_type, protocol, _, address in addresses:
            key = (family, address)
            if key in seen:
                continue
            seen.add(key)
            probe = socket.socket(family, socket_type, protocol)
            probes.append(probe)
            if family == socket.AF_INET6:
                probe.setsockopt(
                    socket.IPPROTO_IPV6,
                    socket.IPV6_V6ONLY,
                    1,
                )
            probe.bind(address)
    except OSError as exc:
        raise ProductionBackupError(
            "TCP port is already in use or unavailable: "
            f"{bind_host}:{port}: {exc}"
        ) from exc
    finally:
        for probe in probes:
            probe.close()


def _container_remove_command(
    container_name: str,
    container: dict[str, Any],
) -> list[str]:
    state = container.get("State") or {}
    status = str(state.get("Status") or "").lower()
    command = ["docker", "rm"]
    if state.get("Running") or status in {
        "paused",
        "restarting",
        "running",
    }:
        command.append("--force")
    command.append(container_name)
    return command


def _remove_container_for_rollback(
    container_name: str,
    *,
    timeout_seconds: float = CONTAINER_REMOVE_TIMEOUT_SECONDS,
) -> None:
    container = _optional_inspect_json("container", container_name)
    if container is None:
        return
    deadline = time.monotonic() + max(timeout_seconds, 1)
    last_error = ""
    next_remove_attempt = 0.0
    while container is not None:
        state = container.get("State") or {}
        status = str(state.get("Status") or "").lower()
        now = time.monotonic()
        if status != "removing" and now >= next_remove_attempt:
            try:
                _run_command(
                    _container_remove_command(
                        container_name,
                        container,
                    )
                )
                last_error = ""
            except ProductionBackupError as exc:
                last_error = str(exc)
            next_remove_attempt = now + 1

        container = _optional_inspect_json(
            "container",
            container_name,
        )
        if container is None:
            return
        if time.monotonic() >= deadline:
            state = container.get("State") or {}
            status = str(state.get("Status") or "unknown")
            detail = f"; last removal error: {last_error}" if last_error else ""
            raise ProductionBackupError(
                f"Timed out removing candidate container "
                f"{container_name} in state {status}{detail}"
            )
        time.sleep(CONTAINER_REMOVE_POLL_SECONDS)


def _mount_for_destination(
    container: dict[str, Any],
    destination: str,
) -> dict[str, Any]:
    matches = [
        mount
        for mount in container.get("Mounts", [])
        if mount.get("Destination") == destination
    ]
    if len(matches) != 1 or not matches[0].get("Source"):
        raise ProductionBackupError(
            f"Container has no unique mount for {destination}"
        )
    return matches[0]


def freeze_production(
    *,
    container_name: str,
    rollback_image: str,
    candidate_image: str,
    quality_evaluation_path: Path,
    quality_signature_path: Path,
    quality_public_key_path: Path,
    expected_quality_public_key_sha256: str,
    destination: Path,
    stop_container: bool,
    stop_timeout_seconds: int,
) -> dict[str, Any]:
    container = _inspect_json("container", container_name)
    rollback = _inspect_json("image", rollback_image)
    candidate = _inspect_json("image", candidate_image)
    current_image_id = str(container.get("Image") or "")
    rollback_image_id = str(rollback.get("Id") or "")
    candidate_image_id = str(candidate.get("Id") or "")
    if not current_image_id or current_image_id != rollback_image_id:
        raise ProductionBackupError(
            "Rollback image does not match the current production container"
        )
    quality_evaluation = verify_candidate_quality_evaluation(
        quality_evaluation_path,
        expected_image_id=candidate_image_id,
        signature_path=quality_signature_path,
        public_key_path=quality_public_key_path,
        expected_public_key_sha256=expected_quality_public_key_sha256,
    )
    state = container.get("State") or {}
    if state.get("Running"):
        if not stop_container:
            raise ProductionBackupError(
                "Production container is running; pass --stop-container "
                "to enter the write-freeze window"
            )
        _run_command(
            ["docker", "update", "--restart=no", container_name]
        )
        _run_command(
            [
                "docker",
                "stop",
                "--time",
                str(max(stop_timeout_seconds, 1)),
                container_name,
            ]
        )
        container = _inspect_json("container", container_name)
        if (container.get("State") or {}).get("Running"):
            raise ProductionBackupError(
                "Production container is still running after docker stop"
            )

    data_mount = _mount_for_destination(
        container,
        DATA_MOUNT_DESTINATION,
    )
    uploads_mount = _mount_for_destination(
        container,
        UPLOADS_MOUNT_DESTINATION,
    )
    metadata = {
        "container_name": container_name,
        "production_image_id": current_image_id,
        "rollback_image": rollback_image,
        "rollback_image_id": rollback_image_id,
        "candidate_image": candidate_image,
        "candidate_image_id": candidate_image_id,
        "quality_evaluation": quality_evaluation,
        "data_volume": data_mount.get("Name") or "",
        "uploads_volume": uploads_mount.get("Name") or "",
        "write_freeze": "container_stopped",
        "restart_policy_after_freeze": "no",
    }
    return create_backup(
        data_dir=Path(data_mount["Source"]),
        uploads_dir=Path(uploads_mount["Source"]),
        destination=destination,
        metadata=metadata,
    )


def _backup_manifest_sha256(backup_dir: Path) -> str:
    root = backup_dir.resolve()
    verify_backup(root)
    return _sha256_file(root / "manifest.json")


def prepare_restored_volumes(
    *,
    backup_dir: Path,
    data_volume: str,
    uploads_volume: str,
    owner_uid: int = 10001,
    owner_gid: int = 10001,
) -> dict[str, str]:
    if not data_volume or not uploads_volume or data_volume == uploads_volume:
        raise ProductionBackupError(
            "Data and uploads volume names must be distinct and non-empty"
        )
    for volume in (data_volume, uploads_volume):
        if _optional_inspect_json("volume", volume) is not None:
            raise ProductionBackupError(
                f"Restore volume already exists: {volume}"
            )
    manifest_sha256 = _backup_manifest_sha256(backup_dir)
    created: list[str] = []
    try:
        for volume, role in (
            (data_volume, "data"),
            (uploads_volume, "uploads"),
        ):
            _run_command(
                [
                    "docker",
                    "volume",
                    "create",
                    "--label",
                    f"zlb.backup_sha256={manifest_sha256}",
                    "--label",
                    f"zlb.role={role}",
                    volume,
                ]
            )
            created.append(volume)
        data = _inspect_json("volume", data_volume)
        uploads = _inspect_json("volume", uploads_volume)
        data_mountpoint = Path(str(data.get("Mountpoint") or ""))
        uploads_mountpoint = Path(str(uploads.get("Mountpoint") or ""))
        if not data_mountpoint.is_dir() or not uploads_mountpoint.is_dir():
            raise ProductionBackupError(
                "Docker volume inspect returned an invalid mountpoint"
            )
        restore_backup(
            backup_dir=backup_dir,
            data_dir=data_mountpoint,
            uploads_dir=uploads_mountpoint,
            owner_uid=owner_uid,
            owner_gid=owner_gid,
        )
    except Exception:
        for volume in reversed(created):
            try:
                _run_command(["docker", "volume", "rm", volume])
            except ProductionBackupError:
                pass
        raise
    return {
        "data_volume": data_volume,
        "uploads_volume": uploads_volume,
        "backup_manifest_sha256": manifest_sha256,
    }


def _verify_restored_volume(
    *,
    volume_name: str,
    expected_role: str,
    backup_manifest_sha256: str,
) -> None:
    volume = _inspect_json("volume", volume_name)
    labels = volume.get("Labels") or {}
    if labels.get("zlb.role") != expected_role:
        raise ProductionBackupError(
            f"Docker volume role mismatch: {volume_name}"
        )
    if labels.get("zlb.backup_sha256") != backup_manifest_sha256:
        raise ProductionBackupError(
            f"Docker volume backup SHA-256 mismatch: {volume_name}"
        )


def _wait_for_health(
    url: str,
    *,
    timeout_seconds: float,
) -> None:
    deadline = time.monotonic() + max(timeout_seconds, 1)
    last_error = ""
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                if response.status == 200:
                    payload = json.loads(response.read().decode("utf-8"))
                    if payload.get("status") == "ok":
                        return
                    last_error = "health payload status is not ok"
                else:
                    last_error = f"health returned HTTP {response.status}"
        except (
            OSError,
            urllib.error.URLError,
            ValueError,
            json.JSONDecodeError,
        ) as exc:
            last_error = str(exc)
        time.sleep(1)
    raise ProductionBackupError(
        f"Candidate health check failed for {url}: {last_error}"
    )


def deploy_compose_candidate(
    *,
    backup_dir: Path,
    compose_file: Path,
    project_name: str,
    container_name: str,
    image_ref: str,
    expected_image_id: str,
    data_volume: str,
    uploads_volume: str,
    bind_host: str,
    public_port: int,
    health_url: str,
    health_timeout_seconds: float,
) -> dict[str, str]:
    image = _inspect_json("image", image_ref)
    actual_image_id = str(image.get("Id") or "")
    if actual_image_id != expected_image_id:
        raise ProductionBackupError(
            "Candidate image ID does not match the validated image"
        )
    manifest_sha256 = _backup_manifest_sha256(backup_dir)
    _verify_restored_volume(
        volume_name=data_volume,
        expected_role="data",
        backup_manifest_sha256=manifest_sha256,
    )
    _verify_restored_volume(
        volume_name=uploads_volume,
        expected_role="uploads",
        backup_manifest_sha256=manifest_sha256,
    )
    environment = dict(os.environ)
    environment.update(
        {
            "MINDMAP_CONTAINER_NAME": container_name,
            "MINDMAP_IMAGE_REF": image_ref,
            "IMAGE_DIGEST": expected_image_id,
            "MINDMAP_DATA_VOLUME_NAME": data_volume,
            "MINDMAP_DATA_VOLUME_EXTERNAL": "true",
            "MINDMAP_UPLOADS_VOLUME_NAME": uploads_volume,
            "MINDMAP_UPLOADS_VOLUME_EXTERNAL": "true",
            "MINDMAP_BIND_HOST": bind_host,
            "MINDMAP_PUBLIC_PORT": str(public_port),
        }
    )
    _run_command(
        [
            "docker",
            "compose",
            "-p",
            project_name,
            "-f",
            str(compose_file.resolve()),
            "up",
            "-d",
            "--no-build",
            "--force-recreate",
            "app",
        ],
        env=environment,
    )
    container = _inspect_json("container", container_name)
    if str(container.get("Image") or "") != expected_image_id:
        raise ProductionBackupError(
            "Started container does not use the validated candidate image"
        )
    if not (container.get("State") or {}).get("Running"):
        raise ProductionBackupError("Started candidate container is not running")
    _wait_for_health(
        health_url,
        timeout_seconds=health_timeout_seconds,
    )
    return {
        "container_name": container_name,
        "image_id": expected_image_id,
        "data_volume": data_volume,
        "uploads_volume": uploads_volume,
        "health_url": health_url,
    }


def rollback_to_preserved_container(
    *,
    active_container: str,
    rollback_container: str,
    expected_rollback_image_id: str,
) -> dict[str, str]:
    preserved = _inspect_json("container", rollback_container)
    if str(preserved.get("Image") or "") != expected_rollback_image_id:
        raise ProductionBackupError(
            "Preserved rollback container image ID mismatch"
        )
    _remove_container_for_rollback(active_container)
    _run_command(
        ["docker", "rename", rollback_container, active_container]
    )
    _run_command(
        [
            "docker",
            "update",
            "--restart=unless-stopped",
            active_container,
        ]
    )
    _run_command(["docker", "start", active_container])
    active = _inspect_json("container", active_container)
    if not (active.get("State") or {}).get("Running"):
        raise ProductionBackupError(
            "Rollback container did not return to a running state"
        )
    return {
        "container_name": active_container,
        "image_id": expected_rollback_image_id,
        "status": "running",
    }


def cutover_to_candidate(
    *,
    backup_dir: Path,
    compose_file: Path,
    project_name: str,
    active_container: str,
    rollback_container: str,
    image_ref: str,
    expected_image_id: str,
    quality_evaluation_path: Path,
    quality_signature_path: Path,
    quality_public_key_path: Path,
    expected_quality_public_key_sha256: str,
    data_volume: str,
    uploads_volume: str,
    bind_host: str,
    public_port: int,
    health_url: str,
    health_timeout_seconds: float,
) -> dict[str, str]:
    manifest = verify_backup(backup_dir)
    metadata = manifest.get("metadata") or {}
    expected_rollback_image_id = str(
        metadata.get("rollback_image_id") or ""
    )
    if not expected_rollback_image_id:
        raise ProductionBackupError(
            "Backup manifest has no rollback image identity"
        )
    if metadata.get("candidate_image_id") != expected_image_id:
        raise ProductionBackupError(
            "Backup manifest candidate image identity does not match cutover"
        )
    quality_evaluation = verify_candidate_quality_evaluation(
        quality_evaluation_path,
        expected_image_id=expected_image_id,
        signature_path=quality_signature_path,
        public_key_path=quality_public_key_path,
        expected_public_key_sha256=expected_quality_public_key_sha256,
    )
    frozen_quality = metadata.get("quality_evaluation")
    if not isinstance(frozen_quality, dict):
        raise ProductionBackupError(
            "Backup manifest has no candidate quality evaluation identity"
        )
    if frozen_quality != quality_evaluation:
        raise ProductionBackupError(
            "Candidate quality evaluation identity does not match the "
            "write-freeze manifest"
        )
    active = _inspect_json("container", active_container)
    if (active.get("State") or {}).get("Running"):
        raise ProductionBackupError(
            "Production container must be stopped before cutover"
        )
    if str(active.get("Image") or "") != expected_rollback_image_id:
        raise ProductionBackupError(
            "Stopped production container no longer matches the rollback image"
        )
    if _optional_inspect_json("container", rollback_container) is not None:
        raise ProductionBackupError(
            f"Rollback container name already exists: {rollback_container}"
        )
    _assert_tcp_port_available(bind_host, public_port)
    _run_command(
        ["docker", "rename", active_container, rollback_container]
    )
    try:
        return deploy_compose_candidate(
            backup_dir=backup_dir,
            compose_file=compose_file,
            project_name=project_name,
            container_name=active_container,
            image_ref=image_ref,
            expected_image_id=expected_image_id,
            data_volume=data_volume,
            uploads_volume=uploads_volume,
            bind_host=bind_host,
            public_port=public_port,
            health_url=health_url,
            health_timeout_seconds=health_timeout_seconds,
        )
    except Exception as exc:
        try:
            rollback_to_preserved_container(
                active_container=active_container,
                rollback_container=rollback_container,
                expected_rollback_image_id=expected_rollback_image_id,
            )
        except Exception as rollback_exc:
            raise ProductionBackupError(
                f"Cutover failed and automatic rollback also failed: "
                f"{rollback_exc}"
            ) from exc
        raise ProductionBackupError(
            f"Cutover failed; preserved production container was restored: "
            f"{exc}"
        ) from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Create, verify, restore, or freeze a ZLB production backup."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create")
    create.add_argument("--data-dir", type=Path, required=True)
    create.add_argument("--uploads-dir", type=Path, required=True)
    create.add_argument("--output", type=Path, required=True)

    verify = subparsers.add_parser("verify")
    verify.add_argument("--backup-dir", type=Path, required=True)

    restore = subparsers.add_parser("restore")
    restore.add_argument("--backup-dir", type=Path, required=True)
    restore.add_argument("--data-dir", type=Path, required=True)
    restore.add_argument("--uploads-dir", type=Path, required=True)
    restore.add_argument("--owner-uid", type=int)
    restore.add_argument("--owner-gid", type=int)

    freeze = subparsers.add_parser("freeze")
    freeze.add_argument("--container", default="zlb-mindmap")
    freeze.add_argument("--rollback-image", required=True)
    freeze.add_argument("--candidate-image", required=True)
    freeze.add_argument(
        "--quality-evaluation",
        type=Path,
        required=True,
    )
    freeze.add_argument(
        "--quality-signature",
        type=Path,
        required=True,
    )
    freeze.add_argument(
        "--quality-public-key",
        type=Path,
        required=True,
    )
    freeze.add_argument(
        "--quality-public-key-sha256",
        required=True,
    )
    freeze.add_argument("--output", type=Path, required=True)
    freeze.add_argument("--stop-container", action="store_true")
    freeze.add_argument("--stop-timeout-seconds", type=int, default=60)

    prepare = subparsers.add_parser("prepare-volumes")
    prepare.add_argument("--backup-dir", type=Path, required=True)
    prepare.add_argument("--data-volume", required=True)
    prepare.add_argument("--uploads-volume", required=True)
    prepare.add_argument("--owner-uid", type=int, default=10001)
    prepare.add_argument("--owner-gid", type=int, default=10001)

    cutover = subparsers.add_parser("cutover")
    cutover.add_argument("--backup-dir", type=Path, required=True)
    cutover.add_argument(
        "--compose-file",
        type=Path,
        default=Path("compose.prod.yml"),
    )
    cutover.add_argument("--project-name", default="zlb-production")
    cutover.add_argument("--active-container", default="zlb-mindmap")
    cutover.add_argument("--rollback-container", required=True)
    cutover.add_argument("--image-ref", required=True)
    cutover.add_argument("--expected-image-id", required=True)
    cutover.add_argument(
        "--quality-evaluation",
        type=Path,
        required=True,
    )
    cutover.add_argument(
        "--quality-signature",
        type=Path,
        required=True,
    )
    cutover.add_argument(
        "--quality-public-key",
        type=Path,
        required=True,
    )
    cutover.add_argument(
        "--quality-public-key-sha256",
        required=True,
    )
    cutover.add_argument("--data-volume", required=True)
    cutover.add_argument("--uploads-volume", required=True)
    cutover.add_argument("--bind-host", default="127.0.0.1")
    cutover.add_argument("--public-port", type=int, default=5173)
    cutover.add_argument(
        "--health-url",
        default="http://127.0.0.1:5173/api/health",
    )
    cutover.add_argument("--health-timeout-seconds", type=float, default=60)

    rollback = subparsers.add_parser("rollback")
    rollback.add_argument("--active-container", default="zlb-mindmap")
    rollback.add_argument("--rollback-container", required=True)
    rollback.add_argument("--expected-image-id", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "create":
            manifest = create_backup(
                data_dir=args.data_dir,
                uploads_dir=args.uploads_dir,
                destination=args.output,
            )
        elif args.command == "verify":
            manifest = verify_backup(args.backup_dir)
        elif args.command == "restore":
            manifest = restore_backup(
                backup_dir=args.backup_dir,
                data_dir=args.data_dir,
                uploads_dir=args.uploads_dir,
                owner_uid=args.owner_uid,
                owner_gid=args.owner_gid,
            )
        elif args.command == "freeze":
            manifest = freeze_production(
                container_name=args.container,
                rollback_image=args.rollback_image,
                candidate_image=args.candidate_image,
                quality_evaluation_path=args.quality_evaluation,
                quality_signature_path=args.quality_signature,
                quality_public_key_path=args.quality_public_key,
                expected_quality_public_key_sha256=(
                    args.quality_public_key_sha256
                ),
                destination=args.output,
                stop_container=args.stop_container,
                stop_timeout_seconds=args.stop_timeout_seconds,
            )
        elif args.command == "prepare-volumes":
            result = prepare_restored_volumes(
                backup_dir=args.backup_dir,
                data_volume=args.data_volume,
                uploads_volume=args.uploads_volume,
                owner_uid=args.owner_uid,
                owner_gid=args.owner_gid,
            )
            print(
                json.dumps(
                    result,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0
        elif args.command == "cutover":
            result = cutover_to_candidate(
                backup_dir=args.backup_dir,
                compose_file=args.compose_file,
                project_name=args.project_name,
                active_container=args.active_container,
                rollback_container=args.rollback_container,
                image_ref=args.image_ref,
                expected_image_id=args.expected_image_id,
                quality_evaluation_path=args.quality_evaluation,
                quality_signature_path=args.quality_signature,
                quality_public_key_path=args.quality_public_key,
                expected_quality_public_key_sha256=(
                    args.quality_public_key_sha256
                ),
                data_volume=args.data_volume,
                uploads_volume=args.uploads_volume,
                bind_host=args.bind_host,
                public_port=args.public_port,
                health_url=args.health_url,
                health_timeout_seconds=args.health_timeout_seconds,
            )
            print(
                json.dumps(
                    result,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0
        else:
            result = rollback_to_preserved_container(
                active_container=args.active_container,
                rollback_container=args.rollback_container,
                expected_rollback_image_id=args.expected_image_id,
            )
            print(
                json.dumps(
                    result,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0
    except ProductionBackupError as exc:
        print(f"production backup failed: {exc}", file=os.sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "schema_version": manifest["schema_version"],
                "created_at": manifest["created_at"],
                "metadata": manifest.get("metadata", {}),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
