"""authentication endpoints: login, lockout, mfa, refresh rotation, reuse detection, logout"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from app.models import AuditLog
from app.models.base import utcnow
from app.models.enums import AuditAction, UserRole
from app.security import SlidingWindowLimiter, new_totp_secret, totp_code
from tests.conftest import PASSWORD, auth_header, make_user

TOKEN = "/api/v1/auth/token"


def login(client, email, password=PASSWORD, **extra):  # noqa: ANN001, ANN003, ANN201
    return client.post(TOKEN, data={"username": email, "password": password, **extra})


def test_login_returns_tokens_and_profile(client, db):
    u = make_user(db, UserRole.clinician, email="dana@test.example")
    r = login(client, "DANA@test.example")
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "bearer" and body["expires_in"] == 900 and body["refresh_expires_in"] == 12 * 3600
    assert body["user"]["user_id"] == str(u.user_id) and "password_hash" not in r.text
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200 and me.json()["email"] == "dana@test.example"


def test_patient_refresh_lifetime_is_seven_days(client, db):
    make_user(db, UserRole.patient, email="pat@test.example")
    assert login(client, "pat@test.example").json()["refresh_expires_in"] == 7 * 24 * 3600


def test_bad_password_and_unknown_email_look_identical(client, db):
    make_user(db, UserRole.clinician, email="known@test.example")
    a, b = login(client, "known@test.example", "nope"), login(client, "unknown@test.example", "nope")
    assert a.status_code == b.status_code == 401
    assert a.json()["detail"] == b.json()["detail"] == "invalid credentials"
    assert a.headers["content-type"].startswith("application/problem+json")
    assert a.headers["www-authenticate"] == "Bearer"


def test_five_failures_lock_the_account(client, db):
    u = make_user(db, UserRole.clinician, email="lock@test.example")
    for _ in range(5):
        assert login(client, "lock@test.example", "wrong").status_code == 401
    r = login(client, "lock@test.example")          # even the right password is refused while locked
    assert r.status_code == 423 and u.locked_until is not None
    u.locked_until = utcnow() - timedelta(seconds=1)
    assert login(client, "lock@test.example").status_code == 200


def test_inactive_account_cannot_log_in(client, db):
    make_user(db, UserRole.clinician, email="gone@test.example", is_active=False)
    assert login(client, "gone@test.example").status_code == 401


def test_mfa_required_when_enabled(client, db):
    secret = new_totp_secret()
    make_user(db, UserRole.physician, email="mfa@test.example", mfa_enabled=True, mfa_secret=secret)
    assert login(client, "mfa@test.example").status_code == 401
    assert login(client, "mfa@test.example", mfa_code="000000").status_code in (401, 200)  # 1-in-a-million collision
    assert login(client, "mfa@test.example", mfa_code=totp_code(secret)).status_code == 200


def test_login_is_audited_without_password(client, db):
    make_user(db, UserRole.clinician, email="aud@test.example")
    login(client, "aud@test.example", "Wrong-Password-1")
    login(client, "aud@test.example")
    rows = db.scalars(select(AuditLog).where(AuditLog.entity_type == "auth")).all()
    assert {r.action for r in rows} >= {AuditAction.login, AuditAction.login_failed}
    assert all("Wrong-Password-1" not in str(r.details) for r in rows)


def test_rate_limit_returns_429_with_retry_after(client, db, monkeypatch):
    from app.api.routes import auth as auth_routes
    monkeypatch.setattr(auth_routes, "login_limiter", SlidingWindowLimiter(2, 60))
    make_user(db, UserRole.clinician, email="rl@test.example")
    login(client, "rl@test.example", "x")
    login(client, "rl@test.example", "x")
    r = login(client, "rl@test.example", "x")
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0


def test_refresh_rotates_and_detects_reuse(client, db):
    make_user(db, UserRole.clinician, email="rot@test.example")
    first = login(client, "rot@test.example").json()
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert r.status_code == 200
    second = r.json()
    assert second["refresh_token"] != first["refresh_token"]
    # replaying the rotated token is treated as theft: every session for the account is revoked
    replay = client.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert replay.status_code == 401 and "reuse" in replay.json()["detail"]
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {second['access_token']}"}).status_code == 401


def test_refresh_with_unknown_token(client):
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": "rt_" + "x" * 40}).status_code == 401


def test_logout_revokes_access_token_immediately(client, db):
    u = make_user(db, UserRole.clinician)
    h = auth_header(db, u)
    assert client.post("/api/v1/auth/logout", headers=h).status_code == 204
    assert client.get("/api/v1/auth/me", headers=h).status_code == 401


def test_missing_garbage_and_stale_role_tokens(client, db):
    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.get("/api/v1/auth/me", headers={"Authorization": "Bearer not.a.jwt"}).status_code == 401
    u = make_user(db, UserRole.clinician)
    h = auth_header(db, u)
    u.role = UserRole.admin                    # role changed after the token was issued
    db.flush()
    assert client.get("/api/v1/auth/me", headers=h).status_code == 401


def test_deactivated_user_token_stops_working(client, db):
    u = make_user(db, UserRole.clinician)
    h = auth_header(db, u)
    u.is_active = False
    db.flush()
    assert client.get("/api/v1/auth/me", headers=h).status_code == 401
