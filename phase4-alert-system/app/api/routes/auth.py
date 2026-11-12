"""authentication: login, refresh-token rotation, logout, current user"""
from __future__ import annotations

from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Form, Request, status

from app.api.deps import DB, CurrentUser
from app.api.responses import R401, R422, R423, R429
from app.config import get_settings
from app.errors import AccountLocked, AuthenticationError
from app.logging_config import get_logger
from app.models import User
from app.models.base import utcnow
from app.models.enums import AuditAction, UserRole
from app.repositories import AuditRepository, UserRepository
from app.schemas.auth import MeOut, RefreshRequest, TokenResponse, UserSummary
from app.security import (burn_password_check, create_access_token, hash_refresh_token, login_limiter,
                          new_refresh_token, verify_password, verify_totp)

router = APIRouter(prefix="/auth", tags=["Auth"])
log = get_logger("api.auth")


def _issue_tokens(users: UserRepository, user: User, user_agent: str | None) -> TokenResponse:
    s = get_settings()
    hours = s.refresh_token_hours_patient if user.role == UserRole.patient else s.refresh_token_hours_staff
    token, token_hash = new_refresh_token()
    sess = users.create_session(user.user_id, token_hash, timedelta(hours=hours), user_agent)
    access, ttl = create_access_token(user.user_id, user.role.value, sess.session_id)
    return TokenResponse(access_token=access, expires_in=ttl, refresh_token=token, refresh_expires_in=hours * 3600,
                         user=UserSummary.model_validate(user))


@router.post("/token", response_model=TokenResponse, summary="Log in and receive tokens",
             responses={**R401, **R422, **R423, **R429},
             description="OAuth2 password grant (form-encoded). Accounts with MFA enabled must send a 6-digit "
                         "`mfa_code`. Five failed attempts lock the account for 15 minutes. Errors never reveal "
                         "whether an email exists. Rate limited per client IP and per account.")
def login(request: Request, db: DB,
          username: Annotated[str, Form(description="Account email", examples=["marcus.lee@healthtrack.example"])],
          password: Annotated[str, Form(examples=["HealthTrack-Demo-2026!"])],
          grant_type: Annotated[str, Form(pattern="^password$")] = "password",
          mfa_code: Annotated[str | None, Form(pattern=r"^\d{6}$")] = None) -> TokenResponse:
    s = get_settings()
    ip = request.client.host if request.client else "unknown"
    login_limiter.check(f"ip:{ip}")
    login_limiter.check(f"acct:{username.strip().lower()}")
    users, audit = UserRepository(db), AuditRepository(db)
    user = users.get_by_email(username)

    def fail(reason: str) -> None:
        audit.record(AuditAction.login_failed, "auth", actor=user if user else None, outcome="denied",
                     details={"reason": reason})
        db.commit()
        raise AuthenticationError("invalid credentials")

    if user is None:
        burn_password_check(password)
        fail("unknown account")
    assert user is not None
    if user.locked_until and user.locked_until > utcnow():
        audit.record(AuditAction.login_failed, "auth", actor=user, outcome="denied", details={"reason": "locked"})
        db.commit()
        raise AccountLocked("account temporarily locked after repeated failed logins")
    if not user.is_active:
        burn_password_check(password)
        fail("inactive account")
    if not verify_password(password, user.password_hash):
        users.record_failed_login(user, s.max_failed_logins, timedelta(minutes=s.lockout_minutes))
        fail("bad password")
    if user.mfa_enabled and not (user.mfa_secret and verify_totp(user.mfa_secret, mfa_code)):
        users.record_failed_login(user, s.max_failed_logins, timedelta(minutes=s.lockout_minutes))
        fail("bad or missing mfa code")

    users.record_successful_login(user)
    tokens = _issue_tokens(users, user, request.headers.get("user-agent"))
    audit.record(AuditAction.login, "auth", actor=user, details={"mfa": user.mfa_enabled})
    return tokens


@router.post("/refresh", response_model=TokenResponse, summary="Rotate the refresh token",
             responses={**R401, **R422},
             description="Exchanges a valid refresh token for a new pair and revokes the old one. Presenting a "
                         "token that was already rotated revokes every session for the account (theft detection).")
def refresh(body: RefreshRequest, request: Request, db: DB) -> TokenResponse:
    users = UserRepository(db)
    sess = users.get_session_by_hash(hash_refresh_token(body.refresh_token))
    if sess is None:
        raise AuthenticationError("refresh token invalid")
    if sess.revoked_at is not None:
        users.revoke_all_sessions(sess.user_id)
        AuditRepository(db).record(AuditAction.login_failed, "auth", actor=sess.user, outcome="denied",
                                   details={"reason": "refresh token reuse; all sessions revoked"})
        db.commit()
        log.warning("refresh token reuse detected", extra={"ctx": {"user_id": str(sess.user_id)}})
        raise AuthenticationError("refresh token reuse detected; log in again")
    if not users.session_is_live(sess) or not sess.user.is_active:
        raise AuthenticationError("refresh token expired")
    tokens = _issue_tokens(users, sess.user, request.headers.get("user-agent"))
    new_sess = users.get_session_by_hash(hash_refresh_token(tokens.refresh_token))
    users.revoke_session(sess, replaced_by=new_sess.session_id if new_sess else None)
    return tokens


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Revoke the current session",
             responses=R401)
def logout(db: DB, user: CurrentUser, request: Request) -> None:
    users = UserRepository(db)
    sess = users.get_session(request.state.session_id)
    if sess and sess.revoked_at is None:
        users.revoke_session(sess)
    AuditRepository(db).record(AuditAction.logout, "auth", actor=user)


@router.get("/me", response_model=MeOut, summary="Current user profile", responses=R401)
def me(user: CurrentUser) -> User:
    return user
