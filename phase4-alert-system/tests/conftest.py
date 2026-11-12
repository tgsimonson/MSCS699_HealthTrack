"""test fixtures

every test runs inside a transaction that is rolled back afterward, so tests are isolated and fast.
default database: in-memory sqlite. set HT_TEST_DATABASE_URL=postgresql+psycopg://user@host/db to run the
same suite against postgresql (the database is emptied and rebuilt at the start of the run).
"""
from __future__ import annotations

import os

os.environ.setdefault("HT_BCRYPT_ROUNDS", "4")             # fast hashing in tests only
os.environ.setdefault("HT_JWT_SECRET", "test-secret-not-for-production-use-0123456789")
os.environ.setdefault("HT_LOGIN_RATE_LIMIT", "1000")
os.environ.setdefault("HT_DATABASE_URL", "sqlite://")
os.environ.setdefault("HT_OUTBOX_DIR", __import__("tempfile").mkdtemp(prefix="ht_outbox_"))
os.environ.setdefault("HT_ALERT_WORKERS", "0")               # tests drive jobs directly on a controlled clock

import uuid  # noqa: E402
from collections.abc import Iterator  # noqa: E402
from contextlib import contextmanager  # noqa: E402
from datetime import date, datetime, timedelta, timezone  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from sqlalchemy import insert  # noqa: E402

from app.alerts.defaults import policy_rows, rule_rows  # noqa: E402
from app.db import get_db, get_session_factory, make_engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (AlertRule, Base, CareTeamAssignment, Device, EscalationPolicy, Patient,  # noqa: E402
                        User)
from app.models.enums import (CareTeamRole, ClinicalRisk, DeviceStatus, DeviceType, ProgramStatus,  # noqa: E402
                              QualifyingEvent, SexAtBirth, UserRole)
from app.repositories import UserRepository  # noqa: E402
from app.security import create_access_token, hash_password, login_limiter, new_refresh_token  # noqa: E402

TEST_URL = os.getenv("HT_TEST_DATABASE_URL") or "sqlite://"
PASSWORD = "Correct-Horse-Battery-9"


@pytest.fixture(scope="session")
def engine():
    eng = make_engine(TEST_URL)
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    with eng.begin() as conn:                     # the default rules and policies, as migration 0003 loads them
        conn.execute(insert(AlertRule), rule_rows())
        conn.execute(insert(EscalationPolicy), policy_rows())
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine) -> Iterator[Session]:
    """a session whose commits become savepoints inside one outer transaction that is always rolled back"""
    conn = engine.connect()
    outer = conn.begin()
    session = Session(bind=conn, join_transaction_mode="create_savepoint", autoflush=False, expire_on_commit=False)
    try:
        yield session
    finally:
        session.close()
        outer.rollback()
        conn.close()


@pytest.fixture
def client(db: Session) -> Iterator[TestClient]:
    def _get_db():
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise

    @contextmanager
    def _factory():
        yield db                                   # websocket code shares the test transaction

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_session_factory] = lambda: _factory
    login_limiter.reset()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------- factories

def make_user(db: Session, role: UserRole, email: str | None = None, **kw) -> User:  # noqa: ANN003
    user = User(email=email or f"{role.value}-{uuid.uuid4().hex[:8]}@test.example",
                password_hash=hash_password(PASSWORD), role=role, first_name=kw.pop("first_name", role.value.title()),
                last_name=kw.pop("last_name", "Tester"), **kw)
    db.add(user)
    db.commit()     # a savepoint release: survives request rollbacks, still undone by the outer rollback
    return user


def patient_data(**overrides) -> dict:  # noqa: ANN003
    n = uuid.uuid4().int % 1_000_000
    data = dict(mrn=f"HT-T{n:06d}", first_name="Pat", last_name="Ient", date_of_birth=date(1960, 1, 1),
                sex=SexAtBirth.female, qualifying_event=QualifyingEvent.pci,
                qualifying_event_date=date(2026, 9, 1), referral_date=date(2026, 9, 5),
                enrollment_date=date(2026, 9, 10), program_status=ProgramStatus.active,
                clinical_risk_category=ClinicalRisk.low)
    data.update(overrides)
    return data


def make_patient(db: Session, clinician: User | None = None, physician: User | None = None,
                 login: User | None = None, **overrides) -> Patient:  # noqa: ANN003
    p = Patient(**patient_data(**overrides), user_id=login.user_id if login else None)
    db.add(p)
    db.flush()
    if clinician:
        db.add(CareTeamAssignment(patient_id=p.patient_id, user_id=clinician.user_id,
                                  team_role=CareTeamRole.primary_clinician, start_date=date(2026, 9, 5)))
    if physician:
        db.add(CareTeamAssignment(patient_id=p.patient_id, user_id=physician.user_id,
                                  team_role=CareTeamRole.supervising_physician, start_date=date(2026, 9, 5)))
    db.commit()
    return p


def make_device(db: Session, patient: Patient, dtype: DeviceType = DeviceType.heart_rate_band) -> Device:
    d = Device(patient_id=patient.patient_id, device_type=dtype, manufacturer="Corvane", model="HB-2",
               serial_number=f"SN-{uuid.uuid4().hex[:10]}", status=DeviceStatus.active)
    db.add(d)
    db.commit()
    return d


def auth_header(db: Session, user: User) -> dict[str, str]:
    """create a real session and access token without going through the login endpoint"""
    _, token_hash = new_refresh_token()
    sess = UserRepository(db).create_session(user.user_id, token_hash, timedelta(hours=1))
    token, _ = create_access_token(user.user_id, user.role.value, sess.session_id)
    db.commit()
    return {"Authorization": f"Bearer {token}"}


def ago(**kw) -> datetime:  # noqa: ANN003
    return datetime.now(timezone.utc) - timedelta(**kw)


@pytest.fixture
def world(db: Session) -> dict:
    """a small care setting: two clinicians, a physician, an admin, an it admin, and three patients"""
    dana = make_user(db, UserRole.clinician, first_name="Dana")
    marcus = make_user(db, UserRole.clinician, first_name="Marcus")
    raman = make_user(db, UserRole.physician, first_name="Priya")
    admin = make_user(db, UserRole.admin)
    it = make_user(db, UserRole.it_admin)
    robert_login = make_user(db, UserRole.patient, first_name="Robert")
    linda_login = make_user(db, UserRole.patient, first_name="Linda")
    robert = make_patient(db, dana, raman, robert_login, first_name="Robert", last_name="Alvarez")
    linda = make_patient(db, dana, raman, linda_login, first_name="Linda", last_name="Chen",
                         clinical_risk_category=ClinicalRisk.moderate)
    thomas = make_patient(db, marcus, raman, first_name="Thomas", last_name="Reed")
    band = make_device(db, robert)
    cuff = make_device(db, robert, DeviceType.blood_pressure_cuff)
    tracker = make_device(db, robert, DeviceType.activity_tracker)
    thomas_band = make_device(db, thomas)
    return dict(dana=dana, marcus=marcus, raman=raman, admin=admin, it=it, robert_login=robert_login,
                linda_login=linda_login, robert=robert, linda=linda, thomas=thomas, band=band, cuff=cuff,
                tracker=tracker, thomas_band=thomas_band)


# ---------------------------------------------------------------- phase 4: alert helpers

NOW = datetime(2026, 11, 12, 17, 0, tzinfo=timezone.utc)      # 10:00 in Denver; engine tests run on this clock


def add_vitals(db: Session, patient: Patient, rows: list[tuple], *, now: datetime = NOW,
               device: Device | None = None) -> list:
    """rows of (minutes_before_now, context, {measurements}); stored with the quality the api would assign"""
    from app.models import VitalSign
    out = []
    for minutes, ctx, values in rows:
        v = VitalSign(patient_id=patient.patient_id, recorded_at=now - timedelta(minutes=minutes), context=ctx,
                      device_id=device.device_id if device else None,
                      quality=VitalSign.assess_quality(values.get("heart_rate"), values.get("systolic_bp"),
                                                       values.get("diastolic_bp"), values.get("spo2")), **values)
        db.add(v)
        out.append(v)
    db.flush()
    return out


def set_rx(db: Session, patient: Patient, by: User, at: datetime | None = None, **kw) -> object:  # noqa: ANN003
    from app.repositories.alerts import AlertRepository
    data = dict(resting_hr_baseline=66, target_hr_min=95, target_hr_max=115, hr_ceiling=128, max_exercise_sbp=180,
                min_spo2=90, sessions_per_week=3, session_minutes=30)
    data.update(kw)
    rx = AlertRepository(db).set_prescription(patient.patient_id, data, by, now=at or NOW - timedelta(days=60))
    db.commit()
    return rx


@pytest.fixture
def alert_world(world, db) -> dict:
    """the phase 3 world plus phone numbers (for sms) and prescriptions for robert (ceiling 128) and linda (150)"""
    for key, phone in (("dana", "+17195550101"), ("marcus", "+17195550102"), ("raman", "+17195550103")):
        world[key].phone = phone
    db.commit()
    world["robert_rx"] = set_rx(db, world["robert"], world["raman"])
    world["linda_rx"] = set_rx(db, world["linda"], world["raman"], target_hr_min=110, target_hr_max=135,
                               hr_ceiling=150, resting_hr_baseline=72)
    return world


# ---------------------------------------------------------------- scenario report (reports/scenarios.json)

_SCENARIOS: dict[str, dict] = {}


def pytest_configure(config) -> None:  # noqa: ANN001
    config.addinivalue_line("markers", "scenario(sid, title, requirement): an alert-system testing scenario")


def pytest_collection_modifyitems(items) -> None:  # noqa: ANN001
    for item in items:
        m = item.get_closest_marker("scenario")
        if m:
            sid, title, req = m.args
            _SCENARIOS[item.nodeid] = {"id": sid, "title": title, "requirement": req, "test": item.nodeid,
                                       "outcome": "not run", "seconds": 0.0}


def pytest_runtest_logreport(report) -> None:  # noqa: ANN001
    s = _SCENARIOS.get(report.nodeid)
    if s is None:
        return
    if report.when == "call" or report.outcome != "passed":
        s["outcome"] = report.outcome if s["outcome"] in ("not run", "passed") else s["outcome"]
        s["seconds"] += report.duration


def pytest_sessionfinish(session) -> None:  # noqa: ANN001
    target = os.getenv("HT_SCENARIO_REPORT")
    if target and _SCENARIOS:
        import json
        from pathlib import Path
        rows = sorted(_SCENARIOS.values(), key=lambda r: (r["id"], r["test"]))
        Path(target).write_text(json.dumps(rows, indent=2))
