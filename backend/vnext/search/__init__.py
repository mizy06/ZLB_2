"""Policy-gated external evidence search with replayable snapshots."""

from .gateway import (
    FetchResponse,
    GatewayConfig,
    PinnedFetcher,
    SearchConnector,
    SearchGateway,
    SearchHit,
    SearchPolicyDenied,
    SnapshotStore,
    ValidatedTarget,
    validate_public_http_target,
)

__all__ = [
    "FetchResponse",
    "GatewayConfig",
    "PinnedFetcher",
    "SearchConnector",
    "SearchGateway",
    "SearchHit",
    "SearchPolicyDenied",
    "SnapshotStore",
    "ValidatedTarget",
    "validate_public_http_target",
]
