from __future__ import annotations

import hashlib
import html
import ipaddress
import os
import re
import secrets
import socket
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Protocol
from urllib.parse import urljoin, urlsplit, urlunsplit

from backend.vnext.artifacts.canonical import payload_digest
from backend.vnext.contracts.control import (
    EvidenceMode,
    RunManifest,
)
from backend.vnext.contracts.evidence import EvidenceNamespace, EvidenceRef
from backend.vnext.contracts.integrations import (
    DataClassification,
    EvidenceBundle,
    EvidencePurpose,
    ExternalEvidenceRecord,
    ExternalRelation,
    FetchSnapshot,
    SearchBudgetUsage,
    SearchIntent,
    SearchQueryRecord,
)
from backend.vnext.contracts.common import RuntimeRole


SANITIZER_VERSION = "search-sanitizer-v1"
_ALLOWED_MIME_TYPES = frozenset(
    {
        "text/html",
        "text/plain",
        "application/xhtml+xml",
    }
)
_INJECTION_PATTERNS = (
    re.compile(r"ignore (?:all |the )?previous instructions", re.I),
    re.compile(r"system prompt", re.I),
    re.compile(r"developer message", re.I),
    re.compile(r"tool permissions?", re.I),
    re.compile(r"override (?:the )?(?:policy|rules|instructions)", re.I),
)


class SearchPolicyDenied(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SearchHit:
    url: str
    title: str
    publisher: str
    license_note: str
    published_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class FetchResponse:
    status_code: int
    mime_type: str
    body: bytes
    redirect_url: str | None = None


@dataclass(frozen=True, slots=True)
class ValidatedTarget:
    canonical_url: str
    hostname: str
    resolved_ip: str


class SearchConnector(Protocol):
    def search(
        self,
        query: str,
        *,
        limit: int,
    ) -> tuple[SearchHit, ...]: ...


class PinnedFetcher(Protocol):
    def fetch(
        self,
        target: ValidatedTarget,
        *,
        max_bytes: int,
    ) -> FetchResponse: ...


Resolver = Callable[[str], tuple[str, ...]]


@dataclass(frozen=True, slots=True)
class GatewayConfig:
    enabled: bool = False
    policy_version: str = "search-gateway-v1-locked"
    allowed_roles: frozenset[RuntimeRole] = frozenset(
        {RuntimeRole.DOMAIN_RESOLVER}
    )
    allowed_domains: tuple[str, ...] = ()
    blocked_domains: tuple[str, ...] = ()
    max_download_bytes: int = 25 * 1024 * 1024
    max_redirects: int = 3


class _VisibleTextParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.casefold() in {"script", "style", "noscript", "template"}:
            self._ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if (
            tag.casefold() in {"script", "style", "noscript", "template"}
            and self._ignored_depth
        ):
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            self.parts.append(data)


def _default_resolver(hostname: str) -> tuple[str, ...]:
    addresses = {
        item[4][0]
        for item in socket.getaddrinfo(
            hostname,
            None,
            type=socket.SOCK_STREAM,
        )
    }
    return tuple(sorted(addresses))


def _domain_matches(hostname: str, rule: str) -> bool:
    normalized = rule.casefold().strip().lstrip(".").rstrip(".")
    return hostname == normalized or hostname.endswith("." + normalized)


def validate_public_http_target(
    url: str,
    *,
    resolver: Resolver = _default_resolver,
    allowed_domains: tuple[str, ...] = (),
    blocked_domains: tuple[str, ...] = (),
) -> ValidatedTarget:
    try:
        parsed = urlsplit(url.strip())
    except ValueError as exc:
        raise SearchPolicyDenied("invalid_url") from exc
    if parsed.scheme.casefold() not in {"http", "https"}:
        raise SearchPolicyDenied("unsupported_url_scheme")
    if not parsed.hostname:
        raise SearchPolicyDenied("missing_url_hostname")
    if parsed.username or parsed.password:
        raise SearchPolicyDenied("url_credentials_forbidden")
    if parsed.port not in {None, 80, 443}:
        raise SearchPolicyDenied("url_port_forbidden")
    try:
        hostname = parsed.hostname.encode("idna").decode("ascii").casefold()
    except UnicodeError as exc:
        raise SearchPolicyDenied("invalid_idna_hostname") from exc
    hostname = hostname.rstrip(".")
    if any(_domain_matches(hostname, item) for item in blocked_domains):
        raise SearchPolicyDenied("blocked_domain")
    if allowed_domains and not any(
        _domain_matches(hostname, item) for item in allowed_domains
    ):
        raise SearchPolicyDenied("domain_not_allowlisted")
    try:
        addresses = resolver(hostname)
    except OSError as exc:
        raise SearchPolicyDenied("dns_resolution_failed") from exc
    if not addresses:
        raise SearchPolicyDenied("dns_resolution_empty")
    parsed_addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for address in addresses:
        try:
            parsed_address = ipaddress.ip_address(address)
        except ValueError as exc:
            raise SearchPolicyDenied("dns_returned_invalid_ip") from exc
        if (
            not parsed_address.is_global
            or parsed_address.is_private
            or parsed_address.is_loopback
            or parsed_address.is_link_local
            or parsed_address.is_multicast
            or parsed_address.is_reserved
            or parsed_address.is_unspecified
        ):
            raise SearchPolicyDenied("dns_resolved_non_public_ip")
        parsed_addresses.append(parsed_address)
    canonical_url = urlunsplit(
        (
            parsed.scheme.casefold(),
            parsed.netloc,
            parsed.path or "/",
            parsed.query,
            "",
        )
    )
    return ValidatedTarget(
        canonical_url=canonical_url,
        hostname=hostname,
        resolved_ip=str(sorted(parsed_addresses, key=str)[0]),
    )


def _sanitize(
    body: bytes,
    *,
    mime_type: str,
) -> tuple[str, tuple[str, ...]]:
    text = body.decode("utf-8", errors="replace")
    if mime_type in {"text/html", "application/xhtml+xml"}:
        parser = _VisibleTextParser()
        parser.feed(text)
        text = " ".join(parser.parts)
    text = html.unescape(text)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    signals = tuple(
        pattern.pattern
        for pattern in _INJECTION_PATTERNS
        if pattern.search(text)
    )
    return text, signals


class SnapshotStore:
    def __init__(self, root: Path):
        self.root = root

    def put(
        self,
        *,
        owner_id: str,
        snapshot_id: str,
        content: str,
    ) -> EvidenceRef:
        owner_scope = hashlib.sha256(
            ("zlb-vnext-search-owner-v1\0" + owner_id).encode("utf-8")
        ).hexdigest()
        snapshots = self.root / "owners" / owner_scope / "snapshots"
        snapshots.mkdir(parents=True, exist_ok=True)
        target = snapshots / snapshot_id
        pending = snapshots / (
            f".pending-{snapshot_id}-{secrets.token_hex(8)}"
        )
        content_bytes = content.encode("utf-8")
        pending.mkdir(exist_ok=False)
        try:
            with (pending / "content.txt").open("xb") as handle:
                handle.write(content_bytes)
                handle.flush()
                os.fsync(handle.fileno())
            pending.rename(target)
            self._fsync_directory(snapshots)
        except Exception:
            if pending.exists():
                (pending / "content.txt").unlink(missing_ok=True)
                pending.rmdir()
            raise
        return EvidenceRef(
            namespace=EvidenceNamespace.SYSTEM,
            ref_id=f"sys:search:{snapshot_id}:sanitized",
            content_digest=payload_digest(content),
        )

    def get(
        self,
        *,
        owner_id: str,
        snapshot_id: str,
    ) -> str:
        owner_scope = hashlib.sha256(
            ("zlb-vnext-search-owner-v1\0" + owner_id).encode("utf-8")
        ).hexdigest()
        return (
            self.root
            / "owners"
            / owner_scope
            / "snapshots"
            / snapshot_id
            / "content.txt"
        ).read_text(encoding="utf-8")

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


class SearchGateway:
    def __init__(
        self,
        *,
        config: GatewayConfig,
        snapshot_store: SnapshotStore,
        resolver: Resolver = _default_resolver,
    ):
        self.config = config
        self.snapshot_store = snapshot_store
        self.resolver = resolver

    def _denial_reasons(
        self,
        intent: SearchIntent,
        manifest: RunManifest,
    ) -> tuple[str, ...]:
        reasons: list[str] = []
        if not self.config.enabled:
            reasons.append("live_search_locked")
        if intent.owner_id != manifest.owner_id:
            reasons.append("owner_mismatch")
        if intent.run_id != manifest.run_id:
            reasons.append("run_mismatch")
        if manifest.declared.no_egress:
            reasons.append("run_declared_no_egress")
        if manifest.declared.evidence_mode is EvidenceMode.SOURCE_ONLY:
            reasons.append("source_only_mode")
        if intent.tenant_consent_ref is None:
            reasons.append("tenant_consent_missing")
        if intent.agent_role not in self.config.allowed_roles:
            reasons.append("role_not_authorized_for_search")
        if intent.data_classification is DataClassification.RESTRICTED:
            reasons.append("restricted_data_search_forbidden")
        if intent.max_queries > manifest.declared.budget.max_search_queries:
            reasons.append("query_budget_exceeds_run_manifest")
        if intent.max_fetches > manifest.declared.budget.max_search_fetches:
            reasons.append("fetch_budget_exceeds_run_manifest")
        return tuple(dict.fromkeys(reasons))

    def execute(
        self,
        intent: SearchIntent,
        manifest: RunManifest,
        *,
        connector: SearchConnector,
        fetcher: PinnedFetcher,
    ) -> EvidenceBundle:
        denial_reasons = self._denial_reasons(intent, manifest)
        if denial_reasons:
            return EvidenceBundle(
                bundle_id=self._bundle_id(intent, "denied"),
                intent_id=intent.intent_id,
                run_id=intent.run_id,
                owner_id=intent.owner_id,
                decision="denied",
                denial_reasons=denial_reasons,
                budget_usage=SearchBudgetUsage(
                    queries=0,
                    fetches=0,
                    downloaded_bytes=0,
                ),
                gateway_policy_version=self.config.policy_version,
            )

        query_log: list[SearchQueryRecord] = []
        hits: list[SearchHit] = []
        seen_urls: set[str] = set()
        queries = intent.query_candidates[: intent.max_queries]
        for query in queries:
            query_hits = connector.search(
                query,
                limit=intent.max_fetches,
            )
            query_log.append(
                SearchQueryRecord(
                    query=query,
                    result_count=len(query_hits),
                    executed_at=datetime.now(UTC),
                )
            )
            for hit in query_hits:
                if hit.url in seen_urls:
                    continue
                seen_urls.add(hit.url)
                hits.append(hit)

        snapshots: list[FetchSnapshot] = []
        results: list[ExternalEvidenceRecord] = []
        conflicts: list[str] = []
        unresolved: list[str] = []
        downloaded_bytes = 0
        fetch_count = 0
        for hit in hits:
            if fetch_count >= intent.max_fetches:
                break
            try:
                response, target, redirect_chain = self._fetch_with_redirects(
                    hit.url,
                    intent=intent,
                    fetcher=fetcher,
                    remaining_bytes=(
                        self.config.max_download_bytes - downloaded_bytes
                    ),
                )
            except SearchPolicyDenied as exc:
                conflicts.append(f"{hit.url}: {exc}")
                continue
            fetch_count += 1
            downloaded_bytes += len(response.body)
            if response.status_code < 200 or response.status_code >= 300:
                unresolved.append(
                    f"{target.canonical_url}: http_{response.status_code}"
                )
                continue
            mime_type = response.mime_type.split(";", 1)[0].strip().casefold()
            if mime_type not in _ALLOWED_MIME_TYPES:
                unresolved.append(
                    f"{target.canonical_url}: unsupported_mime"
                )
                continue
            sanitized, injection_signals = _sanitize(
                response.body,
                mime_type=mime_type,
            )
            if not sanitized:
                unresolved.append(
                    f"{target.canonical_url}: empty_sanitized_content"
                )
                continue
            snapshot_id = "snapshot_" + secrets.token_hex(16)
            sanitized_ref = self.snapshot_store.put(
                owner_id=intent.owner_id,
                snapshot_id=snapshot_id,
                content=sanitized,
            )
            fetched_at = datetime.now(UTC)
            content_hash = (
                "sha256:" + hashlib.sha256(response.body).hexdigest()
            )
            snapshots.append(
                FetchSnapshot(
                    snapshot_id=snapshot_id,
                    canonical_url=target.canonical_url,
                    resolved_ip=target.resolved_ip,
                    status_code=response.status_code,
                    mime_type=mime_type,
                    content_hash=content_hash,
                    sanitized_content_ref=sanitized_ref,
                    byte_count=len(response.body),
                    redirect_chain=redirect_chain,
                    fetched_at=fetched_at,
                    sanitizer_version=SANITIZER_VERSION,
                    injection_signals=injection_signals,
                )
            )
            external_ref = EvidenceRef(
                namespace=EvidenceNamespace.EXTERNAL,
                ref_id=f"ext:snapshot:{snapshot_id}",
                content_digest=content_hash,
            )
            results.append(
                ExternalEvidenceRecord(
                    external_ref_id=external_ref,
                    snapshot_id=snapshot_id,
                    canonical_url=target.canonical_url,
                    publisher=hit.publisher or target.hostname,
                    title=hit.title or target.hostname,
                    published_at=hit.published_at,
                    fetched_at=fetched_at,
                    content_hash=content_hash,
                    quote_span=sanitized[:1024],
                    relation_to_claim=self._relation(intent.evidence_purpose),
                    trust_tier=(
                        "authoritative"
                        if intent.allowed_domains
                        and any(
                            _domain_matches(target.hostname, domain)
                            for domain in intent.allowed_domains
                        )
                        else "unknown"
                    ),
                    license_note=hit.license_note,
                )
            )
            if injection_signals:
                conflicts.append(
                    f"{target.canonical_url}: prompt_injection_signal"
                )

        decision = "allowed"
        if conflicts or unresolved:
            decision = "partial"
        return EvidenceBundle(
            bundle_id=self._bundle_id(intent, decision),
            intent_id=intent.intent_id,
            run_id=intent.run_id,
            owner_id=intent.owner_id,
            decision=decision,
            query_log=tuple(query_log),
            results=tuple(results),
            fetch_snapshots=tuple(snapshots),
            conflicts=tuple(conflicts),
            unresolved_questions=tuple(unresolved),
            budget_usage=SearchBudgetUsage(
                queries=len(query_log),
                fetches=fetch_count,
                downloaded_bytes=downloaded_bytes,
            ),
            gateway_policy_version=self.config.policy_version,
        )

    def _fetch_with_redirects(
        self,
        url: str,
        *,
        intent: SearchIntent,
        fetcher: PinnedFetcher,
        remaining_bytes: int,
    ) -> tuple[FetchResponse, ValidatedTarget, tuple[str, ...]]:
        if remaining_bytes <= 0:
            raise SearchPolicyDenied("download_budget_exhausted")
        current_url = url
        redirect_chain: list[str] = []
        for redirect_count in range(self.config.max_redirects + 1):
            target = validate_public_http_target(
                current_url,
                resolver=self.resolver,
                allowed_domains=(
                    intent.allowed_domains
                    if intent.allowed_domains
                    else self.config.allowed_domains
                ),
                blocked_domains=(
                    *self.config.blocked_domains,
                    *intent.blocked_domains,
                ),
            )
            if self.config.allowed_domains and not any(
                _domain_matches(target.hostname, domain)
                for domain in self.config.allowed_domains
            ):
                raise SearchPolicyDenied("gateway_domain_not_allowlisted")
            response = fetcher.fetch(
                target,
                max_bytes=remaining_bytes,
            )
            if len(response.body) > remaining_bytes:
                raise SearchPolicyDenied("download_budget_exceeded")
            if response.redirect_url is None:
                return response, target, tuple(redirect_chain)
            if redirect_count >= self.config.max_redirects:
                raise SearchPolicyDenied("redirect_limit_exceeded")
            current_url = urljoin(target.canonical_url, response.redirect_url)
            redirect_chain.append(current_url)
        raise SearchPolicyDenied("redirect_limit_exceeded")

    @staticmethod
    def _relation(purpose: EvidencePurpose) -> ExternalRelation:
        return {
            EvidencePurpose.DISAMBIGUATE: ExternalRelation.DISAMBIGUATES,
            EvidencePurpose.NORMALIZE: ExternalRelation.NORMALIZES,
            EvidencePurpose.CONFLICT_CHECK: ExternalRelation.UNRESOLVED,
            EvidencePurpose.EXTEND: ExternalRelation.EXTENDS,
        }[purpose]

    def _bundle_id(
        self,
        intent: SearchIntent,
        decision: str,
    ) -> str:
        digest = hashlib.sha256(
            (
                intent.intent_id
                + "\0"
                + decision
                + "\0"
                + self.config.policy_version
            ).encode("utf-8")
        ).hexdigest()
        return "evidence_bundle_" + digest[:32]
