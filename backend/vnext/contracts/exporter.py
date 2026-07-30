from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.vnext.artifacts.canonical import payload_digest

from .registry import CONTRACTS, ContractRegistration


JSON_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
DEFAULT_SCHEMA_DIR = Path(__file__).with_name("jsonschema")


def contract_schema(
    registration: ContractRegistration,
) -> dict[str, Any]:
    schema = registration.model.model_json_schema(
        mode="validation",
        ref_template="#/$defs/{model}",
    )
    return {
        "$schema": JSON_SCHEMA_DIALECT,
        "$id": registration.schema_id,
        **schema,
    }


def _pretty_json(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("ascii")


def schema_bundle() -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    manifest_contracts: list[dict[str, str]] = []
    for registration in CONTRACTS:
        schema = contract_schema(registration)
        files[registration.filename] = _pretty_json(schema)
        manifest_contracts.append(
            {
                "artifact_type": (
                    registration.artifact_type.value
                    if registration.artifact_type is not None
                    else "metadata"
                ),
                "filename": registration.filename,
                "name": registration.name,
                "schema_digest": payload_digest(schema),
                "schema_id": registration.schema_id,
                "version": registration.version,
            }
        )
    manifest = {
        "dialect": JSON_SCHEMA_DIALECT,
        "contracts": manifest_contracts,
        "manifest_version": "1.0.0",
    }
    files["manifest.json"] = _pretty_json(manifest)
    return files


def write_schema_bundle(
    output_dir: Path = DEFAULT_SCHEMA_DIR,
    *,
    check: bool = False,
) -> tuple[str, ...]:
    expected = schema_bundle()
    changed: list[str] = []
    for filename, content in expected.items():
        path = output_dir / filename
        current = path.read_bytes() if path.is_file() else None
        if current == content:
            continue
        changed.append(filename)
        if not check:
            output_dir.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
    stale = (
        {
            path.name
            for path in output_dir.glob("*.json")
            if path.is_file()
        }
        - expected.keys()
        if output_dir.is_dir()
        else set()
    )
    changed.extend(sorted(stale))
    if not check:
        for filename in stale:
            (output_dir / filename).unlink()
    return tuple(sorted(set(changed)))
