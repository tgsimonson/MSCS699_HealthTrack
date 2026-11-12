"""password hashing, jwt access tokens, refresh tokens, totp, and a login rate limiter"""
from __future__ import annotations

import base64
import functools
import hashlib
import hmac
import secrets
import struct
import threading
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

from app.config import get_settings
from app.errors import AuthenticationError, RateLimited

# ---------------------------------------------------------------- passwords


def hash_password(password: str, rounds: int | None = None) -> str:
    if len(password.encode()) > 72:
        raise ValueError("password longer than 72 bytes")   # bcrypt silently truncates beyond 72
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds or get_settings().bcrypt_rounds)).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode()[:72], hashed.encode())
    except ValueError:
        return False


# a real hash to check against when the email is unknown, so response time does not reveal which emails exist.
# it must use the same cost as stored hashes, or unknown emails would answer measurably faster.
@functools.cache
def _dummy_hash(rounds: int) -> str:
    return bcrypt.hashpw(b"timing-equalizer", bcrypt.gensalt(rounds)).decode()


def burn_password_check(password: str) -> None:
    verify_password(password, _dummy_hash(get_settings().bcrypt_rounds))


# ---------------------------------------------------------------- access tokens


def create_access_token(user_id: uuid.UUID, role: str, session_id: uuid.UUID) -> tuple[str, int]:
    s = get_settings()
    now = datetime.now(timezone.utc)
    ttl = timedelta(minutes=s.access_token_minutes)
    claims = {"sub": str(user_id), "role": role, "sid": str(session_id), "iss": s.jwt_issuer, "aud": s.jwt_audience,
              "iat": now, "nbf": now, "exp": now + ttl, "jti": secrets.token_hex(8)}
    return jwt.encode(claims, s.jwt_secret, algorithm=s.jwt_algorithm), int(ttl.total_seconds())


def decode_access_token(token: str) -> dict[str, Any]:
    s = get_settings()
    try:
        # algorithms is pinned so a token signed with "none" or a different algorithm is rejected
        return jwt.decode(token, s.jwt_secret, algorithms=[s.jwt_algorithm], audience=s.jwt_audience,
                          issuer=s.jwt_issuer, options={"require": ["exp", "sub", "role", "sid"]})
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("access token expired") from exc
    except jwt.PyJWTError as exc:
        raise AuthenticationError("access token invalid") from exc


# ---------------------------------------------------------------- refresh tokens


def new_refresh_token() -> tuple[str, str]:
    """returns (token for the client, sha-256 hex for the database)"""
    token = "rt_" + secrets.token_urlsafe(32)
    return token, hash_refresh_token(token)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ---------------------------------------------------------------- totp (rfc 6238)


def new_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def totp_code(secret: str, at: float | None = None, step: int = 30, digits: int = 6) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    counter = int((at if at is not None else time.time()) // step)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % 10 ** digits
    return str(code).zfill(digits)


def verify_totp(secret: str, code: str | None, window: int = 1, at: float | None = None) -> bool:
    if not code or not code.isdigit() or len(code) != 6:
        return False
    now = at if at is not None else time.time()
    return any(hmac.compare_digest(totp_code(secret, now + i * 30), code) for i in range(-window, window + 1))


# ---------------------------------------------------------------- rate limiting


class SlidingWindowLimiter:
    """in-process limiter keyed by ip or account; a shared store (redis) replaces it when scaled out"""

    def __init__(self, limit: int, window_seconds: int = 60) -> None:
        self.limit, self.window = limit, window_seconds
        self.hits: dict[str, deque[float]] = defaultdict(deque)
        self.lock = threading.Lock()

    def check(self, key: str) -> None:
        now = time.monotonic()
        with self.lock:
            q = self.hits[key]
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.limit:
                retry = int(self.window - (now - q[0])) + 1
                raise RateLimited("too many login attempts; try again later", headers={"Retry-After": str(retry)})
            q.append(now)

    def reset(self) -> None:
        with self.lock:
            self.hits.clear()


login_limiter = SlidingWindowLimiter(get_settings().login_rate_limit_per_minute)
