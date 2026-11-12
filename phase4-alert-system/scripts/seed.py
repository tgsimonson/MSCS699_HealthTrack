"""load deterministic synthetic sample data (same people and ids as the phase 2 sample data)

usage:  python -m scripts.seed            # uses HT_DATABASE_URL, default sqlite:///./healthtrack.db
        python -m scripts.seed --days 21  # days of readings per active patient
all sample accounts use the mock password HealthTrack-Demo-2026!
"""
from __future__ import annotations

import argparse
import heapq
import math
import random
import uuid
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import CareTeamAssignment, DailyActivity, Device, Patient, User, VitalSign
from app.models.enums import (CareTeamRole, ClinicalRisk, DataQuality, DeviceStatus, DeviceType, ProgramStatus,
                              QualifyingEvent, ReadingContext, ReadingSource, SexAtBirth, UserRole)
from app.security import hash_password

PASSWORD = "HealthTrack-Demo-2026!"
DENVER = ZoneInfo("America/Denver")
U = lambda n: uuid.UUID(f"00000000-0000-4000-a000-{n:012d}")  # noqa: E731
P = lambda n: uuid.UUID(f"00000000-0000-4000-b000-{n:012d}")  # noqa: E731
D = lambda p, n: uuid.UUID(f"00000000-0000-4000-c000-0000000000{p}{n}")  # noqa: E731

STAFF = [
    (1, "dana.whitfield@healthtrack.example", UserRole.clinician, "Dana", "Whitfield", "RN"),
    (2, "marcus.lee@healthtrack.example", UserRole.clinician, "Marcus", "Lee", "CEP"),
    (3, "priya.raman@healthtrack.example", UserRole.physician, "Priya", "Raman", "MD"),
    (4, "samuel.ortiz@healthtrack.example", UserRole.physician, "Samuel", "Ortiz", "MD"),
    (5, "karen.holt@healthtrack.example", UserRole.admin, "Karen", "Holt", None),
    (6, "jordan.pike@healthtrack.example", UserRole.it_admin, "Jordan", "Pike", None),
]
# n, login n, mrn, first, last, dob, sex, event, event date, referral, enrollment, graduation, status, risk,
# primary clinician, physician
PATIENTS = [
    (1, 11, "HT-100001", "Robert", "Alvarez", date(1962, 3, 14), SexAtBirth.male, QualifyingEvent.myocardial_infarction,
     date(2026, 9, 8), date(2026, 9, 15), date(2026, 9, 28), None, ProgramStatus.active, ClinicalRisk.low, 1, 3),
    (2, 12, "HT-100002", "Linda", "Chen", date(1968, 7, 2), SexAtBirth.female, QualifyingEvent.pci,
     date(2026, 9, 10), date(2026, 9, 17), date(2026, 9, 28), None, ProgramStatus.active, ClinicalRisk.moderate, 1, 3),
    (3, 13, "HT-100003", "James", "Whitaker", date(1955, 11, 23), SexAtBirth.male, QualifyingEvent.cabg,
     date(2026, 8, 24), date(2026, 9, 8), date(2026, 9, 21), None, ProgramStatus.active, ClinicalRisk.moderate, 1, 3),
    (4, 14, "HT-100004", "Maria", "Gonzales", date(1974, 5, 9), SexAtBirth.female, QualifyingEvent.pci,
     date(2026, 9, 14), date(2026, 9, 22), date(2026, 10, 1), None, ProgramStatus.active, ClinicalRisk.low, 2, 3),
    (5, 15, "HT-100005", "Thomas", "Reed", date(1959, 1, 30), SexAtBirth.male, QualifyingEvent.valve_surgery,
     date(2026, 8, 31), date(2026, 9, 21), date(2026, 10, 1), None, ProgramStatus.active, ClinicalRisk.moderate, 2, 4),
    (6, 16, "HT-100006", "Angela", "Brooks", date(1966, 9, 18), SexAtBirth.female, QualifyingEvent.stable_angina,
     date(2026, 6, 2), date(2026, 6, 10), date(2026, 6, 22), date(2026, 10, 2), ProgramStatus.graduated,
     ClinicalRisk.low, 2, 4),
    (7, None, "HT-100007", "Kevin", "O'Neil", date(1971, 4, 27), SexAtBirth.male, QualifyingEvent.myocardial_infarction,
     date(2026, 10, 14), date(2026, 10, 22), None, None, ProgramStatus.referred, ClinicalRisk.low, 2, 4),
    (8, None, "HT-100008", "Susan", "Patel", date(1957, 12, 5), SexAtBirth.female,
     QualifyingEvent.heart_failure_reduced_ef, date(2026, 8, 3), date(2026, 8, 12), date(2026, 8, 24), None,
     ProgramStatus.paused, ClinicalRisk.moderate, 1, 3),
]
# rest hr start/end, exercise hr start/end, steps start/end, sbp, dbp, spo2, misses sessions after day index
# (phase 4: james's decline is steeper so the step and resting heart rate trend rules have something to find)
PROFILES = {1: (68, 66, 108, 109, 7200, 7600, 128, 78, 97, None), 2: (74, 71, 108, 116, 5800, 7000, 132, 82, 97, None),
            3: (70, 84, 104, 109, 7000, 2400, 138, 84, 95, None), 4: (74, 76, 110, 110, 3000, 2200, 126, 80, 98, 9),
            5: (66, 67, 104, 106, 6800, 7200, 124, 76, 97, None)}
DEVICE_KINDS = [(1, DeviceType.heart_rate_band, "HB-2 Chest Strap", "HB2"),
                (2, DeviceType.blood_pressure_cuff, "BP-Connect 5", "BPC"),
                (3, DeviceType.pulse_oximeter, "OX-1 Fingertip", "OX1"),
                (4, DeviceType.activity_tracker, "Stride Band", "STR")]


def seed(db: Session, days: int = 21, end: date | None = None, rounds: int | None = None) -> dict[str, int]:
    if db.scalar(select(User).limit(1)) is not None:
        raise SystemExit("database already has data; seed into an empty database")
    rng = random.Random(2026)
    pw = hash_password(PASSWORD, rounds)          # one hash reused: every sample account shares the mock password
    for n, email, role, first, last, cred in STAFF:
        db.add(User(user_id=U(n), email=email, password_hash=pw, role=role, first_name=first, last_name=last,
                    credentials=cred, phone=f"+171955501{n:02d}"))
    for row in PATIENTS:
        if row[1]:
            db.add(User(user_id=U(row[1]), email=f"{row[3][0].lower()}.{row[4].lower().replace(chr(39), '')}@mail.example",
                        password_hash=pw, role=UserRole.patient, first_name=row[3], last_name=row[4]))
    db.flush()
    for (n, login, mrn, first, last, dob, sex, evt, evt_d, ref_d, enr_d, grad_d, status, risk, pc, md) in PATIENTS:
        db.add(Patient(patient_id=P(n), user_id=U(login) if login else None, mrn=mrn, first_name=first, last_name=last,
                       date_of_birth=dob, sex=sex, qualifying_event=evt, qualifying_event_date=evt_d,
                       referral_date=ref_d, enrollment_date=enr_d, graduation_date=grad_d, program_status=status,
                       clinical_risk_category=risk, phone=f"+171955501{10 + n}", postal_code="80920",
                       created_by=U(5)))
        db.flush()
        ended = grad_d if status == ProgramStatus.graduated else None
        db.add(CareTeamAssignment(patient_id=P(n), user_id=U(pc), team_role=CareTeamRole.primary_clinician,
                                  start_date=ref_d, end_date=ended))
        db.add(CareTeamAssignment(patient_id=P(n), user_id=U(md), team_role=CareTeamRole.supervising_physician,
                                  start_date=ref_d, end_date=ended))
    for p in PROFILES:
        for k, dtype, model, prefix in DEVICE_KINDS:
            db.add(Device(device_id=D(p, k), patient_id=P(p), device_type=dtype, manufacturer="Corvane", model=model,
                          serial_number=f"{prefix}-{p}{k}0417", status=DeviceStatus.active))
    db.flush()

    end = end or datetime.now(DENVER).date() - timedelta(days=1)
    start = end - timedelta(days=days - 1)
    vitals, activity = [], []
    # thomas's exertion spike goes on his latest session day at least 3 days back (sessions are mon/wed/fri)
    spike_day = max(start + timedelta(days=i) for i in range(days - 3)
                    if (start + timedelta(days=i)).isoweekday() in (1, 3, 5))
    for p, (rh0, rh1, eh0, eh1, st0, st1, sbp, dbp, spo2, miss_after) in PROFILES.items():
        for i in range(days):
            d = start + timedelta(days=i)
            f = i / max(days - 1, 1)
            rh, eh, steps = rh0 + (rh1 - rh0) * f, eh0 + (eh1 - eh0) * f, st0 + (st1 - st0) * f
            morning = datetime.combine(d, time(7, 0), DENVER).astimezone(timezone.utc)
            rest_sbp = round(sbp + rng.uniform(-5, 5))
            if p == 1 and i == days - 8:
                rest_sbp = 164                                # one high resting reading (moderate alert)
            vitals.append(_v(p, morning, ReadingContext.rest, D(p, 2), hr=round(rh + rng.uniform(-2, 2)),
                             sbp=rest_sbp, dbp=round(dbp + rng.uniform(-3, 3))))
            vitals.append(_v(p, morning + timedelta(minutes=1), ReadingContext.rest, D(p, 3),
                             spo2=min(100, round(spo2 + rng.uniform(-1, 1)))))
            if d.isoweekday() in (1, 3, 5) and not (miss_after is not None and i > miss_after):
                t0 = datetime.combine(d, time(9, 0), DENVER).astimezone(timezone.utc) + timedelta(minutes=30 * (p % 3))
                for m in range(30):
                    ctx = ReadingContext.warmup if m < 5 else ReadingContext.exercise if m < 25 else ReadingContext.cooldown
                    base = rh + (eh - rh) * (m + 1) / 6 if m < 5 else eh + 3 * math.sin(m / 3) if m < 25 else \
                        eh - (eh - rh - 10) * (m - 24) / 5
                    hr = round(base + rng.uniform(-4, 4))
                    if p == 5 and d == spike_day and m in (17, 18, 19):
                        hr = (133, 138, 141)[m - 17]          # exertion spike above his 128 bpm ceiling
                    vitals.append(_v(p, t0 + timedelta(minutes=m), ctx, D(p, 1), hr=hr))
                vitals.append(_v(p, t0 + timedelta(minutes=33), ReadingContext.recovery, D(p, 2),
                                 hr=round(rh + 14), sbp=sbp + 12, dbp=dbp + 2))
            activity.append({"patient_id": P(p), "activity_date": d, "steps": round(steps + rng.uniform(-600, 600)),
                             "active_minutes": max(0, round(steps / 150 + rng.uniform(-5, 5))),
                             "sedentary_minutes": round(560 + rng.uniform(-40, 40)),
                             "resting_hr": round(rh - 2 + rng.uniform(-1.5, 1.5)), "distance_m": round(steps * 0.72),
                             "source": ReadingSource.device, "device_id": D(p, 4)})
    db.execute(insert(VitalSign), vitals)
    db.execute(insert(DailyActivity), activity)
    db.commit()
    alert_counts = seed_alerts(db, start, end)
    return {"users": len(STAFF) + sum(1 for r in PATIENTS if r[1]), "patients": len(PATIENTS),
            "devices": len(PROFILES) * len(DEVICE_KINDS), "vital_signs": len(vitals), "daily_activity": len(activity),
            **alert_counts}


# ---------------------------------------------------------------- phase 4: prescriptions, overrides, alert history
# patient n: resting baseline, zone min, zone max, ceiling, max exercise sbp, prescribing physician, note
PRESCRIPTIONS = {
    1: (68, 98, 118, 130, 200, 3, "Treadmill walking; zone from symptom-limited exercise test."),
    2: (74, 100, 120, 132, 200, 3, "Stationary bike."),
    3: (70, 95, 112, 125, 190, 3, "Post-CABG; sternal precautions, no upper-body resistance."),
    4: (74, 100, 122, 135, 200, 3, "Walking program."),
    5: (66, 95, 115, 128, 180, 4, "Post-valve replacement; on beta-blocker, conservative ceiling."),
}
OVERRIDES = [(3, "RESTING_SBP_HIGH", 150, "Post-CABG: cardiology requests tighter resting BP control.", 3),
             (5, "RESTING_HR_HIGH", 90, "On beta-blocker; baseline resting HR in the 60s, so 90 is abnormal for him.", 4)]
RESOLUTION_NOTES = {
    "HR_ABOVE_CEILING": "Called patient during session; stopped and rested 5 min, HR back in zone, no symptoms. "
                        "Reviewed pacing; reduce treadmill grade next session.",
    "SPO2_LOW": "Probe repositioned; repeat SpO2 96%. Likely poor finger perfusion.",
    "EXERCISE_SBP_HIGH": "Repeat cuff reading after 5 min recovery within limits; no symptoms.",
    "RESTING_SBP_HIGH": "Rechecked after 10 min seated rest; within range. Will review at weekly check-in.",
    "RESTING_HR_HIGH": "Patient had coffee before reading; repeat resting HR normal.",
}


def seed_alerts(db: Session, start: date, end: date) -> dict[str, int]:
    """replay the seeded readings through the alert engine in time order, then add clinician responses, so the
    worklist and alert history start realistic (resolved older alerts, open trend alerts this morning)"""
    from app.alerts.engine import AlertEngine
    from app.alerts.notifications import Dispatcher
    from app.models import Alert
    from app.models.enums import AlertStatus
    from app.repositories.alerts import AlertRepository

    repo = AlertRepository(db)
    staff = {u.user_id: u for u in db.scalars(select(User).where(User.role != UserRole.patient))}
    rx_from = datetime.combine(start - timedelta(days=1), time(12), DENVER).astimezone(timezone.utc)
    for n, (base, lo, hi, ceil, sbp, md, note) in PRESCRIPTIONS.items():
        repo.set_prescription(P(n), dict(resting_hr_baseline=base, target_hr_min=lo, target_hr_max=hi,
                                         hr_ceiling=ceil, max_exercise_sbp=sbp, notes=note), staff[U(md)], now=rx_from)
    for n, code, value, reason, md in OVERRIDES:
        repo.set_override(P(n), repo.get_rule(code), value, reason, staff[U(md)], now=rx_from)
    db.commit()

    engine, dispatcher = AlertEngine(db), Dispatcher(db)
    rng = random.Random(4)
    pending: list[tuple[datetime, int, str, Alert]] = []        # simulated clinician responses, in time order

    def respond_until(t: datetime) -> None:
        while pending and pending[0][0] <= t:
            at, _, kind, a = heapq.heappop(pending)
            if kind == "escalate":
                engine.run_escalations(at)                  # nobody answered within the critical timeout
            elif kind == "ack" and a.status in (AlertStatus.open, AlertStatus.escalated):
                engine.acknowledge(a, primary_for(a), "Reviewing now.", now=at)
            elif kind == "resolve" and a.status != AlertStatus.resolved:
                engine.resolve(a, primary_for(a), RESOLUTION_NOTES.get(a.rule.rule_code, "Reviewed; no action."),
                               now=at)
            dispatcher.dispatch_due(at)

    def primary_for(a: Alert) -> User:
        return next(u for u in repo.care_team_members(a.patient_id) if u.role == UserRole.clinician)

    readings = sorted(db.scalars(select(VitalSign)), key=lambda v: (v.recorded_at, v.vital_id))
    for v in readings:
        at = v.received_at
        respond_until(at)
        for o in engine.evaluate_readings(v.patient_id, [v], now=at):
            if o.action != "created":
                continue
            seq = len(pending) + rng.random()
            if o.alert.severity.value == "critical":
                schedule = [("escalate", 15), ("ack", 17), ("resolve", 42)]
            else:
                ack = rng.randint(4, 40)
                schedule = [("ack", ack), ("resolve", ack + rng.randint(15, 90))]
            for kind, minutes in schedule:
                heapq.heappush(pending, (at + timedelta(minutes=minutes), seq, kind, o.alert))
        dispatcher.dispatch_due(at)
        db.commit()
    respond_until(datetime.max.replace(tzinfo=timezone.utc))
    db.commit()
    morning = datetime.combine(end + timedelta(days=1), time(6), DENVER).astimezone(timezone.utc)
    engine.evaluate_patterns(now=morning)               # trend alerts stay open for the morning worklist
    dispatcher.dispatch_due(morning)
    db.commit()
    alerts = list(db.scalars(select(Alert)))
    return {"alerts": len(alerts),
            "alerts_open": sum(1 for a in alerts if a.status in (AlertStatus.open, AlertStatus.escalated))}


def _v(p: int, at: datetime, ctx: ReadingContext, device: uuid.UUID, hr: int | None = None, sbp: int | None = None,
       dbp: int | None = None, spo2: int | None = None) -> dict:
    return {"patient_id": P(p), "device_id": device, "recorded_at": at, "received_at": at + timedelta(minutes=2),
            "context": ctx, "heart_rate": hr, "systolic_bp": sbp, "diastolic_bp": dbp, "spo2": spo2,
            "source": ReadingSource.device, "quality": VitalSign.assess_quality(hr, sbp, dbp, spo2),
            "idempotency_key": f"seed-{p}-{device.hex[-2:]}-{at:%Y%m%d%H%M}"}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=21)
    args = ap.parse_args()
    from app.logging_config import configure_logging
    configure_logging("ERROR")        # the seed escalates old sample alerts on purpose; those warnings are noise here
    with SessionLocal() as session:
        counts = seed(session, args.days)
    print("seeded:", ", ".join(f"{k}={v}" for k, v in counts.items()))
    print(f"log in as marcus.lee@healthtrack.example / {PASSWORD}")
    _ = DataQuality
