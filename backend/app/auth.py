from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import unicodedata
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import RLock

from fastapi import HTTPException, Request, Response

from .config import Settings, settings


SESSION_COOKIE_NAME = "topomind_session"
SESSION_TTL = timedelta(days=30)
PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128
USERNAME_MIN_LENGTH = 2
USERNAME_MAX_LENGTH = 32
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1


@dataclass(frozen=True)
class Principal:
    id: str
    username: str = ""


@dataclass(frozen=True)
class Account:
    id: str
    username: str
    created_at: str

    def as_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "username": self.username,
            "created_at": self.created_at,
        }


class AccountInputError(ValueError):
    """The submitted username or password does not meet local policy."""


class AccountAlreadyExistsError(ValueError):
    """The normalized username is already registered."""


class InvalidCredentialsError(ValueError):
    """The account credentials are not valid."""


def workbench_principal(config: Settings) -> Principal:
    """Compatibility helper for older callers and migration tests."""

    return Principal(id=config.workbench_owner_id)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _iso_now() -> str:
    return _utc_now().isoformat()


def normalize_username(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip()
    if not (
        USERNAME_MIN_LENGTH <= len(normalized) <= USERNAME_MAX_LENGTH
    ):
        raise AccountInputError(
            f"用户名长度必须在 {USERNAME_MIN_LENGTH}-{USERNAME_MAX_LENGTH} 个字符之间。"
        )
    if any(
        character.isspace() or not (character.isalnum() or character in "._-")
        for character in normalized
    ):
        raise AccountInputError("用户名只能包含字母、数字、中文、下划线、短横线和点。")
    return normalized.casefold()


def validate_password(value: str) -> str:
    if not isinstance(value, str):
        raise AccountInputError("密码格式无效。")
    if not PASSWORD_MIN_LENGTH <= len(value) <= PASSWORD_MAX_LENGTH:
        raise AccountInputError(
            f"密码长度必须在 {PASSWORD_MIN_LENGTH}-{PASSWORD_MAX_LENGTH} 个字符之间。"
        )
    return value


def _password_digest(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=64,
    )


def _session_digest(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def _parse_expiry(value: str) -> datetime:
    return datetime.fromisoformat(value)


class AccountStore:
    """Small SQLite account/session store kept separate from the graph schema."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._initialize()

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        schema = """
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            username_key TEXT NOT NULL UNIQUE,
            password_salt BLOB NOT NULL,
            password_digest BLOB NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token_digest TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_sessions_user_id
            ON sessions(user_id);
        CREATE INDEX IF NOT EXISTS idx_sessions_expires_at
            ON sessions(expires_at);
        """
        with self._lock, self._connect() as connection:
            connection.executescript(schema)

    @staticmethod
    def _account_from_row(row: sqlite3.Row) -> Account:
        return Account(
            id=str(row["user_id"]),
            username=str(row["username"]),
            created_at=str(row["created_at"]),
        )

    @staticmethod
    def _new_session(
        connection: sqlite3.Connection,
        user_id: str,
    ) -> str:
        token = secrets.token_urlsafe(48)
        now = _utc_now()
        connection.execute(
            """
            INSERT INTO sessions (
                token_digest, user_id, created_at, expires_at
            ) VALUES (?, ?, ?, ?)
            """,
            (
                _session_digest(token),
                user_id,
                now.isoformat(),
                (now + SESSION_TTL).isoformat(),
            ),
        )
        return token

    def register(self, username: str, password: str) -> tuple[Account, str, bool]:
        username_key = normalize_username(username)
        password = validate_password(password)
        display_name = unicodedata.normalize("NFKC", username).strip()
        user_id = f"usr_{secrets.token_hex(16)}"
        created_at = _iso_now()
        salt = secrets.token_bytes(16)
        digest = _password_digest(password, salt)
        with self._lock, self._connect() as connection:
            # Serialize the existence check and insert so only one concurrent
            # registration can claim the legacy public owner.
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT 1 FROM users WHERE username_key = ?",
                (username_key,),
            ).fetchone()
            if existing:
                raise AccountAlreadyExistsError("用户名已存在。")
            first_account = (
                connection.execute("SELECT 1 FROM users LIMIT 1").fetchone()
                is None
            )
            connection.execute(
                """
                INSERT INTO users (
                    user_id, username, username_key, password_salt,
                    password_digest, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    display_name,
                    username_key,
                    salt,
                    digest,
                    created_at,
                ),
            )
            token = self._new_session(connection, user_id)
        return Account(user_id, display_name, created_at), token, first_account

    def login(self, username: str, password: str) -> tuple[Account, str]:
        username_key = normalize_username(username)
        password = validate_password(password)
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE username_key = ?",
                (username_key,),
            ).fetchone()
            if row is None:
                raise InvalidCredentialsError("用户名或密码错误。")
            expected = _password_digest(password, bytes(row["password_salt"]))
            if not hmac.compare_digest(expected, bytes(row["password_digest"])):
                raise InvalidCredentialsError("用户名或密码错误。")
            token = self._new_session(connection, str(row["user_id"]))
        return self._account_from_row(row), token

    def authenticate(self, token: str | None) -> Principal | None:
        if not token:
            return None
        now = _utc_now()
        with self._lock, self._connect() as connection:
            connection.execute(
                "DELETE FROM sessions WHERE expires_at <= ?",
                (now.isoformat(),),
            )
            row = connection.execute(
                """
                SELECT users.user_id, users.username, sessions.expires_at
                FROM sessions
                JOIN users ON users.user_id = sessions.user_id
                WHERE sessions.token_digest = ?
                """,
                (_session_digest(token),),
            ).fetchone()
        if row is None:
            return None
        try:
            if _parse_expiry(str(row["expires_at"])) <= now:
                return None
        except ValueError:
            return None
        return Principal(
            id=str(row["user_id"]),
            username=str(row["username"]),
        )

    def logout(self, token: str | None) -> None:
        if not token:
            return
        with self._lock, self._connect() as connection:
            connection.execute(
                "DELETE FROM sessions WHERE token_digest = ?",
                (_session_digest(token),),
            )

    def account_for_principal(self, principal: Principal) -> Account | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE user_id = ?",
                (principal.id,),
            ).fetchone()
        return self._account_from_row(row) if row else None


_stores: dict[Path, AccountStore] = {}
_stores_lock = RLock()


def account_store(config: Settings | None = None) -> AccountStore:
    config = config or settings
    path = (config.mindmap_data_dir / "auth.sqlite3").resolve()
    with _stores_lock:
        store = _stores.get(path)
        if store is None:
            store = AccountStore(path)
            _stores[path] = store
        return store


def session_token_from_request(request: Request) -> str | None:
    return request.cookies.get(SESSION_COOKIE_NAME)


def set_session_cookie(
    response: Response,
    request: Request,
    token: str,
) -> None:
    forwarded_proto = request.headers.get("x-forwarded-proto", "")
    scheme = (
        forwarded_proto.split(",", 1)[0].strip().casefold()
        or request.url.scheme.casefold()
    )
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=int(SESSION_TTL.total_seconds()),
        httponly=True,
        secure=scheme == "https",
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        httponly=True,
        samesite="lax",
        path="/",
    )


async def require_api_principal(request: Request) -> Principal:
    principal = account_store().authenticate(session_token_from_request(request))
    if principal is None:
        raise HTTPException(status_code=401, detail="请先登录。")
    return principal
