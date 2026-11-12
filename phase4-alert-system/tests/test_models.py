"""model tests: field constraints, foreign keys, and rejection of invalid data at the database layer"""
from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, StatementError

from app.models import AuditLog, CareTeamAssignment, DailyActivity, Device, Patient, VitalSign
from app.models.enums import (AuditAction, CareTeamRole, ClinicalRisk, DataQuality, DeviceStatus, DeviceType,
                              ProgramStatus, ReadingContext, ReadingSource, UserRole)
from tests.conftest import ago, make_device, make_patient, make_user, patient_data


def flush_fails(db, obj, exc=IntegrityError):  # noqa: ANN001, ANN201
    with pytest.raises(exc):
        with db.begin_nested():
            db.add(obj)
            db.flush()


# ---------------------------------------------------------------- patient field constraints

class TestPatientConstraints:
    def test_valid_patient_persists_with_defaults(self, db):
        p = make_patient(db)
        db.refresh(p)
        assert p.timezone == "America/Denver" and p.target_sessions == 36 and p.created_at is not None

    def test_duplicate_mrn_rejected(self, db):
        make_patient(db, mrn="HT-DUP001")
        flush_fails(db, Patient(**patient_data(mrn="HT-DUP001")))

    @pytest.mark.parametrize("mrn", ["ht-1", "HT 100001", "X" * 21, ""])
    def test_malformed_mrn_rejected_by_model_validator(self, mrn):
        with pytest.raises(ValueError, match="mrn"):
            Patient(**patient_data(mrn=mrn))

    @pytest.mark.parametrize("field,value", [("phone", "7195550111"), ("postal_code", "8092"), ("email", "nope")])
    def test_format_validators(self, field, value):
        with pytest.raises(ValueError):
            Patient(**patient_data(**{field: value}))

    def test_email_is_normalized_to_lowercase(self):
        assert Patient(**patient_data(email="T.Reed@Mail.Example")).email == "t.reed@mail.example"

    def test_minor_at_qualifying_event_rejected(self, db):
        flush_fails(db, Patient(**patient_data(date_of_birth=date(2010, 1, 1))), ValueError)

    def test_future_qualifying_event_rejected(self, db):
        future = date.today() + timedelta(days=10)
        flush_fails(db, Patient(**patient_data(qualifying_event_date=future, referral_date=future)), ValueError)

    def test_event_after_referral_rejected(self, db):
        flush_fails(db, Patient(**patient_data(qualifying_event_date=date(2026, 9, 10), referral_date=date(2026, 9, 1))))

    def test_enrollment_before_referral_rejected(self, db):
        flush_fails(db, Patient(**patient_data(enrollment_date=date(2026, 9, 1))))

    def test_active_without_enrollment_date_rejected(self, db):
        flush_fails(db, Patient(**patient_data(enrollment_date=None)))

    def test_referred_without_enrollment_date_allowed(self, db):
        make_patient(db, enrollment_date=None, program_status=ProgramStatus.referred)

    def test_graduated_requires_graduation_date(self, db):
        flush_fails(db, Patient(**patient_data(program_status=ProgramStatus.graduated)))

    def test_graduation_date_without_graduated_status_rejected(self, db):
        flush_fails(db, Patient(**patient_data(graduation_date=date(2026, 12, 1))))

    def test_active_high_risk_rejected(self, db):
        flush_fails(db, Patient(**patient_data(clinical_risk_category=ClinicalRisk.high)))

    def test_paused_high_risk_allowed(self, db):
        make_patient(db, program_status=ProgramStatus.paused, clinical_risk_category=ClinicalRisk.high)

    @pytest.mark.parametrize("n", [0, 73])
    def test_target_sessions_range(self, db, n):
        flush_fails(db, Patient(**patient_data(target_sessions=n)))

    def test_blank_name_rejected(self, db):
        flush_fails(db, Patient(**patient_data(first_name="  ")))

    def test_invalid_enum_value_rejected(self, db):
        with pytest.raises((StatementError, LookupError, ValueError)):
            with db.begin_nested():
                db.add(Patient(**patient_data(program_status="enrolled")))
                db.flush()


# ---------------------------------------------------------------- care team

class TestCareTeam:
    def test_second_current_primary_clinician_rejected(self, db, world):
        flush_fails(db, CareTeamAssignment(patient_id=world["robert"].patient_id, user_id=world["marcus"].user_id,
                                           team_role=CareTeamRole.primary_clinician))

    def test_ended_assignment_does_not_block_new_primary(self, db, world):
        a = db.scalar(select(CareTeamAssignment).where(CareTeamAssignment.patient_id == world["robert"].patient_id,
                                                      CareTeamAssignment.team_role == CareTeamRole.primary_clinician))
        a.end_date = date.today()
        db.flush()
        db.add(CareTeamAssignment(patient_id=world["robert"].patient_id, user_id=world["marcus"].user_id,
                                  team_role=CareTeamRole.primary_clinician))
        db.flush()

    def test_covering_clinicians_may_overlap(self, db, world):
        for u in (world["marcus"], world["dana"]):
            db.add(CareTeamAssignment(patient_id=world["thomas"].patient_id, user_id=u.user_id,
                                      team_role=CareTeamRole.covering_clinician))
        db.flush()

    def test_end_before_start_rejected(self, db, world):
        flush_fails(db, CareTeamAssignment(patient_id=world["thomas"].patient_id, user_id=world["dana"].user_id,
                                           team_role=CareTeamRole.covering_clinician, start_date=date(2026, 10, 10),
                                           end_date=date(2026, 10, 1)))


# ---------------------------------------------------------------- vital signs

def vital(patient, **kw):  # noqa: ANN001, ANN003, ANN201
    base = dict(patient_id=patient.patient_id, recorded_at=ago(minutes=5), context=ReadingContext.rest,
                source=ReadingSource.manual, entered_by=None)
    base.update(kw)
    return VitalSign(**base)


class TestVitalSignConstraints:
    def test_valid_reading_persists(self, db, world):
        v = vital(world["robert"], heart_rate=72, source=ReadingSource.device, device_id=world["band"].device_id)
        db.add(v)
        db.flush()
        assert v.vital_id is not None and v.quality == DataQuality.valid

    @pytest.mark.parametrize("kw", [dict(heart_rate=19), dict(heart_rate=301), dict(spo2=101), dict(spo2=49),
                                    dict(systolic_bp=301, diastolic_bp=80), dict(systolic_bp=120, diastolic_bp=19)])
    def test_hard_limits(self, db, world, kw):
        flush_fails(db, vital(world["robert"], entered_by=world["dana"].user_id, **kw))

    def test_reading_without_measurement_rejected(self, db, world):
        flush_fails(db, vital(world["robert"], entered_by=world["dana"].user_id))

    def test_bp_must_be_paired(self, db, world):
        flush_fails(db, vital(world["robert"], systolic_bp=120, entered_by=world["dana"].user_id))

    def test_systolic_must_exceed_diastolic(self, db, world):
        flush_fails(db, vital(world["robert"], systolic_bp=80, diastolic_bp=90, entered_by=world["dana"].user_id))

    def test_manual_reading_requires_author(self, db, world):
        flush_fails(db, vital(world["robert"], heart_rate=70))

    def test_duplicate_idempotency_key_rejected(self, db, world):
        db.add(vital(world["robert"], heart_rate=70, entered_by=world["dana"].user_id, idempotency_key="dup-key-001"))
        db.flush()
        flush_fails(db, vital(world["robert"], heart_rate=71, entered_by=world["dana"].user_id,
                              idempotency_key="dup-key-001"))

    def test_same_key_allowed_for_different_patients(self, db, world):
        for p in (world["robert"], world["linda"]):
            db.add(vital(p, heart_rate=70, entered_by=world["dana"].user_id, idempotency_key="shared-key-01"))
        db.flush()

    def test_naive_datetime_rejected(self, db, world):
        from datetime import datetime
        with pytest.raises(StatementError, match="naive"):
            db.add(vital(world["robert"], heart_rate=70, entered_by=world["dana"].user_id,
                         recorded_at=datetime(2026, 10, 1, 9, 0)))
            db.flush()
        db.rollback()

    def test_datetimes_round_trip_as_utc(self, db, world):
        v = vital(world["robert"], heart_rate=70, entered_by=world["dana"].user_id)
        db.add(v)
        db.flush()
        db.expire(v)
        assert v.recorded_at.tzinfo is not None and v.recorded_at.utcoffset() == timedelta(0)

    @pytest.mark.parametrize("args,expected", [((72, None, None, None), DataQuality.valid),
                                               ((245, None, None, None), DataQuality.suspect),
                                               ((25, None, None, None), DataQuality.suspect),
                                               ((None, 260, 90, None), DataQuality.suspect),
                                               ((None, 120, 110, None), DataQuality.suspect),
                                               ((None, None, None, 65), DataQuality.suspect),
                                               ((None, 128, 78, 97), DataQuality.valid)])
    def test_quality_assessment(self, args, expected):
        assert VitalSign.assess_quality(*args) == expected


# ---------------------------------------------------------------- daily activity and devices

class TestActivityAndDevices:
    def test_valid_day_persists(self, db, world):
        db.add(DailyActivity(patient_id=world["robert"].patient_id, activity_date=date(2026, 10, 1), steps=7000,
                             active_minutes=45, sedentary_minutes=600))
        db.flush()

    def test_one_row_per_patient_per_day(self, db, world):
        db.add(DailyActivity(patient_id=world["robert"].patient_id, activity_date=date(2026, 10, 2), steps=1,
                             active_minutes=1))
        db.flush()
        db.expunge_all()
        flush_fails(db, DailyActivity(patient_id=world["robert"].patient_id, activity_date=date(2026, 10, 2), steps=2,
                                      active_minutes=2))

    @pytest.mark.parametrize("kw", [dict(steps=-1, active_minutes=0), dict(steps=100001, active_minutes=0),
                                    dict(steps=10, active_minutes=1441),
                                    dict(steps=10, active_minutes=900, sedentary_minutes=900),
                                    dict(steps=10, active_minutes=10, resting_hr=200),
                                    dict(steps=10, active_minutes=10, distance_m=-5)])
    def test_activity_limits(self, db, world, kw):
        flush_fails(db, DailyActivity(patient_id=world["robert"].patient_id, activity_date=date(2026, 10, 3), **kw))

    def test_active_device_requires_patient(self, db):
        flush_fails(db, Device(device_type=DeviceType.pulse_oximeter, manufacturer="Corvane", model="OX-1",
                               serial_number="OX-NOPATIENT", status=DeviceStatus.active))

    def test_duplicate_serial_rejected(self, db, world):
        flush_fails(db, Device(patient_id=world["robert"].patient_id, device_type=DeviceType.heart_rate_band,
                               manufacturer="Corvane", model="HB-2", serial_number=world["band"].serial_number))


# ---------------------------------------------------------------- foreign keys and relationships

class TestForeignKeys:
    def test_vital_for_missing_patient_rejected(self, db, world):
        flush_fails(db, VitalSign(patient_id=uuid.uuid4(), recorded_at=ago(minutes=1), context=ReadingContext.rest,
                                  heart_rate=70, source=ReadingSource.manual, entered_by=world["dana"].user_id))

    def test_activity_for_missing_patient_rejected(self, db):
        flush_fails(db, DailyActivity(patient_id=uuid.uuid4(), activity_date=date(2026, 10, 1), steps=1,
                                      active_minutes=1))

    def test_care_team_for_missing_user_rejected(self, db, world):
        flush_fails(db, CareTeamAssignment(patient_id=world["thomas"].patient_id, user_id=uuid.uuid4(),
                                           team_role=CareTeamRole.covering_clinician))

    def test_vital_with_unknown_device_rejected(self, db, world):
        flush_fails(db, vital(world["robert"], heart_rate=70, source=ReadingSource.device, device_id=uuid.uuid4()))

    def test_relationships_navigate_both_ways(self, db, world):
        r = world["robert"]
        db.add(vital(r, heart_rate=70, source=ReadingSource.device, device_id=world["band"].device_id))
        db.flush()
        db.refresh(r)
        assert len(r.vitals) == 1 and r.vitals[0].patient is r
        assert {d.device_type for d in r.devices} == {DeviceType.heart_rate_band, DeviceType.blood_pressure_cuff,
                                                      DeviceType.activity_tracker}
        assert {a.team_role for a in r.care_team} == {CareTeamRole.primary_clinician,
                                                      CareTeamRole.supervising_physician}

    def test_deleting_patient_cascades_to_monitoring_data(self, db, world):
        p = make_patient(db, world["dana"])
        d = make_device(db, p)
        db.add(vital(p, heart_rate=70, source=ReadingSource.device, device_id=d.device_id))
        db.add(DailyActivity(patient_id=p.patient_id, activity_date=date(2026, 10, 1), steps=1, active_minutes=1))
        db.flush()
        pid, did = p.patient_id, d.device_id
        db.delete(p)
        db.flush()
        db.expunge_all()
        assert db.scalar(select(VitalSign).where(VitalSign.patient_id == pid)) is None
        assert db.scalar(select(DailyActivity).where(DailyActivity.patient_id == pid)) is None
        device = db.get(Device, did)
        assert device is None or device.patient_id is None   # devices survive, unassigned

    def test_user_who_entered_readings_cannot_be_deleted(self, db, world):
        author = make_user(db, UserRole.clinician)
        db.add(vital(world["robert"], heart_rate=70, entered_by=author.user_id))
        db.flush()
        with pytest.raises(IntegrityError):
            with db.begin_nested():
                db.delete(author)
                db.flush()


# ---------------------------------------------------------------- audit log

class TestAuditLog:
    def test_audit_rows_cannot_be_updated_or_deleted(self, db):
        entry = AuditLog(action=AuditAction.read, entity_type="patients")
        db.add(entry)
        db.flush()
        entry.outcome = "denied"
        with pytest.raises(PermissionError):
            db.flush()
        db.rollback()
