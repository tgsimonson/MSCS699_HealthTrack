"""request validation schemas and security primitives"""
from __future__ import annotations

import time
import uuid
from datetime import date, datetime, timedelta, timezone

import jwt
import pytest
from pydantic import ValidationError

from app.config import get_settings
from app.errors import AuthenticationError, RateLimited
from app.schemas.monitoring import DailyActivityUpsert, VitalBatchCreate, VitalSignCreate
from app.schemas.patient import PatientCreate, PatientUpdate
from app.security import (SlidingWindowLimiter, create_access_token, decode_access_token, hash_password,
                          hash_refresh_token, new_refresh_token, new_totp_secret, totp_code, verify_password,
                          verify_totp)

NOW = datetime.now(timezone.utc)
VALID_PATIENT = dict(mrn="HT-200001", first_name="A", last_name="B", date_of_birth="1960-01-01", sex="male",
                     qualifying_event="pci", qualifying_event_date="2026-09-01", referral_date="2026-09-05",
                     clinical_risk_category="low", primary_clinician_id=str(uuid.uuid4()),
                     supervising_physician_id=str(uuid.uuid4()))


class TestPatientSchemas:
    def test_valid(self):
        p = PatientCreate(**VALID_PATIENT)
        assert p.program_status.value == "referred" and p.target_sessions == 36

    @pytest.mark.parametrize("override", [{"mrn": "bad mrn"}, {"phone": "555-1212"}, {"email": "x@"},
                                          {"postal_code": "ABCDE"}, {"target_sessions": 0}, {"sex": "other"},
                                          {"first_name": ""}, {"unexpected": 1},
                                          {"qualifying_event_date": "2026-09-10"},
                                          {"program_status": "active"},
                                          {"program_status": "active", "enrollment_date": "2026-09-06",
                                           "clinical_risk_category": "high"},
                                          {"program_status": "graduated"}])
    def test_invalid(self, override):
        with pytest.raises(ValidationError):
            PatientCreate(**{**VALID_PATIENT, **override})

    def test_update_is_partial_and_checks_date_order(self):
        assert PatientUpdate(program_status="paused").model_dump(exclude_unset=True) == {"program_status": "paused"} or \
            PatientUpdate(program_status="paused").model_dump(exclude_unset=True)["program_status"].value == "paused"
        with pytest.raises(ValidationError):
            PatientUpdate(enrollment_date=date(2026, 10, 10), graduation_date=date(2026, 10, 1))


class TestMonitoringSchemas:
    def base(self, **kw):  # noqa: ANN003, ANN201
        d = dict(recorded_at=NOW - timedelta(minutes=1), context="rest", heart_rate=70,
                 device_id=str(uuid.uuid4()))
        d.update(kw)
        return d

    def test_valid(self):
        assert VitalSignCreate(**self.base()).source.value == "device"

    @pytest.mark.parametrize("override", [{"heart_rate": 301}, {"heart_rate": None},
                                          {"systolic_bp": 120}, {"heart_rate": None, "systolic_bp": 80,
                                                                 "diastolic_bp": 90},
                                          {"recorded_at": (NOW + timedelta(hours=1)).isoformat()},
                                          {"recorded_at": "2026-10-01T09:00:00"}, {"context": "sleep"},
                                          {"idempotency_key": "short"}, {"spo2": 101}])
    def test_invalid(self, override):
        with pytest.raises(ValidationError):
            VitalSignCreate(**self.base(**override))

    def test_small_clock_skew_allowed(self):
        VitalSignCreate(**self.base(recorded_at=(NOW + timedelta(minutes=2)).isoformat()))

    def test_batch_size_limits(self):
        with pytest.raises(ValidationError):
            VitalBatchCreate(readings=[])
        with pytest.raises(ValidationError):
            VitalBatchCreate(readings=[self.base()] * 501)

    def test_activity_minutes_fit_in_day(self):
        with pytest.raises(ValidationError):
            DailyActivityUpsert(steps=1, active_minutes=1000, sedentary_minutes=500)
        assert DailyActivityUpsert(steps=1, active_minutes=100, sedentary_minutes=500).steps == 1


class TestPasswords:
    def test_hash_and_verify(self):
        h = hash_password("Correct-Horse-Battery-9", rounds=4)
        assert h.startswith("$2") and verify_password("Correct-Horse-Battery-9", h)
        assert not verify_password("wrong", h) and not verify_password("x", "not-a-hash")

    def test_hashes_are_salted(self):
        assert hash_password("same", rounds=4) != hash_password("same", rounds=4)

    def test_overlong_password_refused(self):
        with pytest.raises(ValueError):
            hash_password("x" * 73, rounds=4)


class TestTokens:
    def test_round_trip(self):
        uid, sid = uuid.uuid4(), uuid.uuid4()
        token, ttl = create_access_token(uid, "clinician", sid)
        claims = decode_access_token(token)
        assert claims["sub"] == str(uid) and claims["sid"] == str(sid) and ttl == 15 * 60

    def test_tampered_token_rejected(self):
        token, _ = create_access_token(uuid.uuid4(), "patient", uuid.uuid4())
        head, body, sig = token.split(".")
        forged = jwt.encode({**jwt.decode(token, options={"verify_signature": False}), "role": "admin"}, "guess",
                            algorithm="HS256")
        with pytest.raises(AuthenticationError):
            decode_access_token(forged)
        with pytest.raises(AuthenticationError):
            decode_access_token(f"{head}.{body}.{sig[::-1]}")

    def test_none_algorithm_rejected(self):
        unsigned = jwt.encode({"sub": str(uuid.uuid4()), "role": "admin", "sid": str(uuid.uuid4()),
                               "exp": NOW + timedelta(minutes=5)}, None, algorithm="none")
        with pytest.raises(AuthenticationError):
            decode_access_token(unsigned)

    def test_expired_token_rejected(self):
        s = get_settings()
        expired = jwt.encode({"sub": str(uuid.uuid4()), "role": "patient", "sid": str(uuid.uuid4()),
                              "iss": s.jwt_issuer, "aud": s.jwt_audience, "exp": NOW - timedelta(seconds=1)},
                             s.jwt_secret, algorithm="HS256")
        with pytest.raises(AuthenticationError, match="expired"):
            decode_access_token(expired)

    def test_wrong_audience_rejected(self):
        s = get_settings()
        other = jwt.encode({"sub": str(uuid.uuid4()), "role": "patient", "sid": str(uuid.uuid4()),
                            "iss": s.jwt_issuer, "aud": "someone-else", "exp": NOW + timedelta(minutes=5)},
                           s.jwt_secret, algorithm="HS256")
        with pytest.raises(AuthenticationError):
            decode_access_token(other)

    def test_refresh_tokens_are_random_and_hashed(self):
        t1, h1 = new_refresh_token()
        t2, _ = new_refresh_token()
        assert t1 != t2 and h1 == hash_refresh_token(t1) and len(h1) == 64 and t1 not in h1


class TestTotpAndLimiter:
    def test_rfc6238_reference_vector(self):
        # rfc 6238 appendix b: ascii key "12345678901234567890", t=59 -> 94287082 (8 digits) -> last 6 = 287082
        import base64
        secret = base64.b32encode(b"12345678901234567890").decode()
        assert totp_code(secret, at=59) == "287082"

    def test_verify_window(self):
        secret = new_totp_secret()
        now = time.time()
        assert verify_totp(secret, totp_code(secret, now), at=now)
        assert verify_totp(secret, totp_code(secret, now - 30), at=now)
        assert not verify_totp(secret, totp_code(secret, now - 120), at=now)
        assert not verify_totp(secret, None) and not verify_totp(secret, "abc123")

    def test_limiter_blocks_after_limit(self):
        lim = SlidingWindowLimiter(3, 60)
        for _ in range(3):
            lim.check("k")
        with pytest.raises(RateLimited) as exc:
            lim.check("k")
        assert int(exc.value.headers["Retry-After"]) > 0
        lim.check("other-key")


def test_unknown_email_dummy_hash_uses_configured_cost():
    # the timing equalizer only works if the dummy hash costs as much as a real one
    from app.security import _dummy_hash
    rounds = get_settings().bcrypt_rounds
    assert _dummy_hash(rounds).split("$")[2] == f"{rounds:02d}"
