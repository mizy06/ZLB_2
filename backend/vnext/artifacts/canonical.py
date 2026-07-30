from __future__ import annotations

import hashlib
import re
import secrets
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from enum import Enum
from typing import Any

import rfc8785
from pydantic import BaseModel


_SHA256_RE = re.compile(r"^(?:sha256:)?([0-9a-f]{64})$")
_SOURCE_KIND_RE = re.compile(r"^[a-z][a-z0-9_-]{1,31}$")
def _json_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", exclude_none=False)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Mapping):
        invalid_keys = [key for key in value if not isinstance(key, str)]
        if invalid_keys:
            raise TypeError(
                "RFC 8785 JSON objects require string keys; got "
                + ", ".join(type(key).__name__ for key in invalid_keys)
            )
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    ):
        return [_json_value(item) for item in value]
    return value


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize a JSON-compatible value using RFC 8785 JCS."""

    return rfc8785.dumps(_json_value(value))


def payload_digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def stable_source_id(
    kind: str,
    *,
    source_hash: str,
    parser_major: int,
    locator: Mapping[str, Any] | Sequence[Any] | str | int,
) -> str:
    """Derive a source ID stable for one source hash and parser major."""

    if not _SOURCE_KIND_RE.fullmatch(kind):
        raise ValueError("invalid source ID kind")
    hash_match = _SHA256_RE.fullmatch(source_hash)
    if not hash_match:
        raise ValueError("source_hash must be a SHA-256 hex digest")
    if parser_major < 1:
        raise ValueError("parser_major must be at least 1")
    identity = {
        "kind": kind,
        "locator": locator,
        "parser_major": parser_major,
        "source_hash": hash_match.group(1),
    }
    digest = hashlib.sha256(
        b"zlb-vnext-source-id-v1\0" + canonical_json_bytes(identity)
    ).hexdigest()
    return f"src:{kind}:{digest}"


def new_artifact_id() -> str:
    """Return a random opaque artifact ID, independent of payload content."""

    return "art_" + secrets.token_hex(16)
