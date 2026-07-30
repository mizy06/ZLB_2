from __future__ import annotations

import base64
import hashlib
import hmac
import time
from dataclasses import dataclass

from fastapi import Header, HTTPException, Request

from .config import Settings, settings


class AuthConfigurationError(RuntimeError):
    pass


class AuthenticationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Principal:
    id: str


def _principal_id(token: str) -> str:
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return f"token-{digest[:20]}"


def authenticate_token(config: Settings, provided_token: str) -> Principal:
    expected = config.api_access_token
    if not expected:
        if config.production:
            raise AuthConfigurationError(
                "生产环境未配置 MINDMAP_API_TOKEN，接口已关闭。"
            )
        return Principal(id="local-development")
    if not provided_token or not hmac.compare_digest(
        provided_token,
        expected,
    ):
        raise AuthenticationError("接口鉴权失败。")
    return Principal(id=_principal_id(expected))


def _bearer_token(authorization: str | None) -> str:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return ""


def create_session_value(
    config: Settings,
    *,
    ttl_seconds: int = 12 * 60 * 60,
    now: int | None = None,
) -> str:
    if not config.api_access_token:
        raise AuthConfigurationError("未配置 API Token，不能签发会话。")
    issued_at = int(time.time() if now is None else now)
    principal_id = _principal_id(config.api_access_token)
    payload = f"{principal_id}:{issued_at + max(ttl_seconds, 60)}"
    signature = hmac.new(
        config.api_access_token.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    encoded = base64.urlsafe_b64encode(
        f"{payload}:{signature}".encode("utf-8")
    ).decode("ascii")
    return encoded.rstrip("=")


def authenticate_session(
    config: Settings,
    value: str,
    *,
    now: int | None = None,
) -> Principal:
    if not value or not config.api_access_token:
        raise AuthenticationError("会话鉴权失败。")
    try:
        padded = value + "=" * (-len(value) % 4)
        decoded = base64.urlsafe_b64decode(padded).decode("utf-8")
        principal_id, expiry_text, signature = decoded.rsplit(":", 2)
        expiry = int(expiry_text)
    except (ValueError, UnicodeDecodeError):
        raise AuthenticationError("会话格式无效。") from None
    payload = f"{principal_id}:{expiry}"
    expected_signature = hmac.new(
        config.api_access_token.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature, expected_signature):
        raise AuthenticationError("会话签名无效。")
    current = int(time.time() if now is None else now)
    if expiry < current:
        raise AuthenticationError("会话已过期。")
    expected_principal = _principal_id(config.api_access_token)
    if not hmac.compare_digest(principal_id, expected_principal):
        raise AuthenticationError("会话主体无效。")
    return Principal(id=principal_id)


async def require_api_principal(
    request: Request,
    authorization: str | None = Header(default=None),
    x_api_token: str | None = Header(default=None),
) -> Principal:
    session_value = request.cookies.get(settings.session_cookie_name, "")
    try:
        if session_value:
            return authenticate_session(settings, session_value)
        return authenticate_token(
            settings,
            x_api_token or _bearer_token(authorization),
        )
    except AuthConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=401,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
