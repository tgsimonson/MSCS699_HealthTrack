"""user accounts, login state, and refresh-token sessions"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.errors import NotFoundError
from app.logging_config import get_logger
from app.models import AuthSession, User
from app.models.base import utcnow
from app.repositories.base import db_errors

log = get_logger("dal.users")


class UserRepository:
    def __init__(self, session: Session) -> None:
        self.s = session

    def create(self, data: dict[str, Any]) -> User:
        user = User(**data)
        with db_errors(self.s, "user", "create"):
            self.s.add(user)
        log.info("user created", extra={"ctx": {"user_id": str(user.user_id), "role": user.role.value}})
        return user

    def get(self, user_id: uuid.UUID) -> User:
        user = self.s.get(User, user_id)
        if user is None:
            raise NotFoundError("user not found")
        return user

    def get_by_email(self, email: str) -> User | None:
        return self.s.scalar(select(User).where(User.email == email.strip().lower()))

    def record_failed_login(self, user: User, max_attempts: int, lockout: timedelta) -> None:
        user.failed_login_attempts = min(user.failed_login_attempts + 1, 100)
        if user.failed_login_attempts >= max_attempts:
            user.locked_until = utcnow() + lockout
            user.failed_login_attempts = 0
            log.warning("account locked", extra={"ctx": {"user_id": str(user.user_id)}})
        self.s.flush()

    def record_successful_login(self, user: User) -> None:
        user.failed_login_attempts = 0
        user.locked_until = None
        user.last_login_at = utcnow()
        self.s.flush()

    # ---------------------------------------------------------------- sessions
    def create_session(self, user_id: uuid.UUID, token_hash: str, ttl: timedelta,
                       user_agent: str | None = None) -> AuthSession:
        now = utcnow()
        sess = AuthSession(user_id=user_id, refresh_token_hash=token_hash, issued_at=now, expires_at=now + ttl,
                           user_agent=(user_agent or "")[:255] or None)
        with db_errors(self.s, "session", "create"):
            self.s.add(sess)
        return sess

    def get_session_by_hash(self, token_hash: str) -> AuthSession | None:
        return self.s.scalar(select(AuthSession).where(AuthSession.refresh_token_hash == token_hash))

    def get_session(self, session_id: uuid.UUID) -> AuthSession | None:
        return self.s.get(AuthSession, session_id)

    def revoke_session(self, sess: AuthSession, replaced_by: uuid.UUID | None = None) -> None:
        sess.revoked_at = utcnow()
        sess.replaced_by = replaced_by
        self.s.flush()

    def revoke_all_sessions(self, user_id: uuid.UUID) -> int:
        n = self.s.execute(update(AuthSession).where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
                           .values(revoked_at=utcnow())).rowcount
        log.warning("all sessions revoked", extra={"ctx": {"user_id": str(user_id), "count": n}})
        return n or 0

    @staticmethod
    def session_is_live(sess: AuthSession, now: datetime | None = None) -> bool:
        now = now or utcnow()
        return sess.revoked_at is None and sess.expires_at > now
