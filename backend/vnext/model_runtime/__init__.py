"""Provider-neutral structured model execution for vNext."""

from .adapter import (
    AllProvidersFailed,
    CircuitBreaker,
    CircuitOpenError,
    HttpxChatTransport,
    ModelCall,
    ModelRefusalError,
    ProviderEndpoint,
    ProviderTimeout,
    ProviderTransportError,
    ReplaySequenceError,
    RetryPolicy,
    StructuredCallResult,
    StructuredModelAdapter,
    TransportResponse,
)
from .router import (
    PortfolioRouteError,
    require_independent_pair,
    select_independent_verifier,
    select_precision_verifier_pair,
)

__all__ = [
    "AllProvidersFailed",
    "CircuitBreaker",
    "CircuitOpenError",
    "HttpxChatTransport",
    "ModelCall",
    "ModelRefusalError",
    "PortfolioRouteError",
    "ProviderEndpoint",
    "ProviderTimeout",
    "ProviderTransportError",
    "ReplaySequenceError",
    "RetryPolicy",
    "StructuredCallResult",
    "StructuredModelAdapter",
    "TransportResponse",
    "require_independent_pair",
    "select_independent_verifier",
    "select_precision_verifier_pair",
]
