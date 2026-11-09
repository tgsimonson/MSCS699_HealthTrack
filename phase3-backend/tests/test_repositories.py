"""data access layer: crud, filtering, pagination, error translation, and logging"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import OperationalError

from app.errors import ConflictError, DataAccessError, NotFoundError, ValidationFailed
from app.models.enums import (AuditAction, ClinicalRisk, DataQuality, DeviceType, ProgramStatus, ReadingContext,
                              ReadingSource, UserRole)
from app.repositories import (ActivityRepository, AuditRepository, DeviceRepository, PatientRepository,
                              UserRepository, VitalSignRepository)
from app.repositories.base import db_errors
from tests.conftest import ago, make_user, patient_data


def reading(device, minutes_ago=5, **kw):  # noqa: ANN001, ANN003, ANN201
    d = dict(recorded_at=ago(minutes=minutes_ago), context=ReadingContext.rest, heart_rate=72,
             source=ReadingSource.device, device_id=device.device_id)
    d.update(kw)
    return d


# ---------------------------------------------------------------- patients

class TestPatientRepository:
    def test_create_adds_two_care_team_members(self, db, world):
        repo = PatientRepository(db)
        p = repo.create(patient_data(), primary_clinician_id=world["dana"].user_id,
                        supervising_physician_id=world["raman"].user_id, created_by=world["admin"].user_id)
        roles = {a.team_role.value for a in repo.care_team(p.patient_id)}
        assert roles == {"primary_clinician", "supervising_physician"} and p.created_by == world["admin"].user_id

    def test_create_rejects_non_physician_supervisor(self, db, world):
        with pytest.raises(ValidationFailed, match="supervising_physician_id"):
            PatientRepository(db).create(patient_data(), primary_clinician_id=world["dana"].user_id,
                                         supervising_physician_id=world["marcus"].user_id, created_by=None)

    def test_create_rejects_staff_account_as_patient_login(self, db, world):
        with pytest.raises(ValidationFailed, match="user_id"):
            PatientRepository(db).create(patient_data(user_id=world["dana"].user_id),
                                         primary_clinician_id=world["dana"].user_id,
                                         supervising_physician_id=world["raman"].user_id, created_by=None)

    def test_create_rejects_inactive_clinician(self, db, world):
        world["marcus"].is_active = False
        with pytest.raises(ValidationFailed):
            PatientRepository(db).create(patient_data(), primary_clinician_id=world["marcus"].user_id,
                                         supervising_physician_id=world["raman"].user_id, created_by=None)

    def test_duplicate_mrn_becomes_conflict_error(self, db, world):
        with pytest.raises(ConflictError, match="MRN"):
            PatientRepository(db).create(patient_data(mrn=world["robert"].mrn),
                                         primary_clinician_id=world["dana"].user_id,
                                         supervising_physician_id=world["raman"].user_id, created_by=None)

    def test_check_violation_becomes_validation_error_and_session_survives(self, db, world):
        repo = PatientRepository(db)
        with pytest.raises(ValidationFailed, match="low or moderate"):
            repo.update(world["robert"].patient_id, {"clinical_risk_category": ClinicalRisk.high})
        # the savepoint rolled back only the failed change; earlier work in the session is intact and usable
        assert repo.get(world["linda"].patient_id).last_name == "Chen"
        assert repo.get(world["robert"].patient_id).clinical_risk_category == ClinicalRisk.low

    def test_model_validator_error_becomes_validation_error(self, db, world):
        with pytest.raises(ValidationFailed, match="phone"):
            PatientRepository(db).update(world["robert"].patient_id, {"phone": "555"})

    def test_get_missing_raises_not_found(self, db):
        with pytest.raises(NotFoundError):
            PatientRepository(db).get(uuid.uuid4())

    def test_list_scoped_to_clinician_care_team(self, db, world):
        repo = PatientRepository(db)
        names = {p.first_name for p in repo.list(visible_to=world["dana"]).items}
        assert names == {"Robert", "Linda"}
        assert {p.first_name for p in repo.list(visible_to=world["marcus"]).items} == {"Thomas"}
        assert repo.list(visible_to=world["raman"]).total_items == 3
        assert repo.list(visible_to=world["admin"]).total_items >= 3
        assert repo.list(visible_to=world["it"]).total_items == 0
        assert [p.first_name for p in repo.list(visible_to=world["robert_login"]).items] == ["Robert"]

    def test_future_dated_assignment_grants_no_access(self, db, world):
        from app.models import CareTeamAssignment
        from app.models.enums import CareTeamRole
        db.add(CareTeamAssignment(patient_id=world["thomas"].patient_id, user_id=world["dana"].user_id,
                                  team_role=CareTeamRole.covering_clinician, start_date=date.today() + timedelta(days=3)))
        db.flush()
        assert not PatientRepository(db).is_on_care_team(world["dana"].user_id, world["thomas"].patient_id)

    def test_list_filters_status_sort_and_paginates(self, db, world):
        repo = PatientRepository(db)
        page1 = repo.list(visible_to=world["raman"], sort="last_name", page=1, page_size=2)
        page2 = repo.list(visible_to=world["raman"], sort="last_name", page=2, page_size=2)
        assert [p.last_name for p in page1.items] == ["Alvarez", "Chen"] and [p.last_name for p in page2.items] == ["Reed"]
        assert page1.meta() == {"page": 1, "page_size": 2, "total_items": 3, "total_pages": 2}
        repo.update(world["thomas"].patient_id, {"program_status": ProgramStatus.paused})
        assert [p.first_name for p in repo.list(visible_to=world["raman"],
                                                program_status=[ProgramStatus.paused]).items] == ["Thomas"]
        assert repo.list(visible_to=world["raman"], clinician_id=world["marcus"].user_id).total_items == 1

    def test_search_matches_name_or_mrn_case_insensitively(self, db, world):
        repo = PatientRepository(db)
        assert [p.first_name for p in repo.search("ALVA", visible_to=world["dana"]).items] == ["Robert"]
        assert repo.search(world["linda"].mrn[-4:], visible_to=world["dana"]).total_items == 1
        assert repo.search("reed", visible_to=world["dana"]).total_items == 0      # out of scope

    def test_update_reports_changed_columns_only(self, db, world):
        _, changed = PatientRepository(db).update(world["robert"].patient_id,
                                                  {"first_name": "Robert", "phone": "+17195550999"})
        assert changed == ["phone"]

    def test_soft_delete_hides_and_withdraws(self, db, world):
        repo = PatientRepository(db)
        repo.soft_delete(world["robert"].patient_id)
        with pytest.raises(NotFoundError):
            repo.get(world["robert"].patient_id)
        hidden = repo.get(world["robert"].patient_id, include_deleted=True)
        assert hidden.program_status == ProgramStatus.withdrawn
        assert world["robert"].patient_id not in {p.patient_id for p in repo.list(visible_to=world["admin"]).items}

    def test_hard_delete_logs_warning(self, db, world, caplog):
        with caplog.at_level(logging.WARNING, logger="healthtrack"):
            PatientRepository(db).hard_delete(world["thomas"].patient_id)
        assert any("hard-deleted" in r.getMessage() for r in caplog.records)

    def test_create_is_logged(self, db, world, caplog):
        with caplog.at_level(logging.INFO, logger="healthtrack"):
            PatientRepository(db).create(patient_data(), primary_clinician_id=world["dana"].user_id,
                                         supervising_physician_id=world["raman"].user_id, created_by=None)
        assert any(r.getMessage() == "patient created" for r in caplog.records)


# ---------------------------------------------------------------- vital signs

class TestVitalSignRepository:
    def test_create_assesses_quality(self, db, world):
        repo = VitalSignRepository(db)
        ok = repo.create(world["robert"].patient_id, reading(world["band"]))
        odd = repo.create(world["robert"].patient_id, reading(world["band"], minutes_ago=4, heart_rate=240))
        assert ok.quality == DataQuality.valid and odd.quality == DataQuality.suspect

    def test_manual_reading_records_author(self, db, world):
        v = VitalSignRepository(db).create(world["robert"].patient_id,
                                           dict(recorded_at=ago(minutes=2), context=ReadingContext.rest,
                                                systolic_bp=130, diastolic_bp=80, source=ReadingSource.manual),
                                           entered_by=world["dana"].user_id)
        assert v.entered_by == world["dana"].user_id and v.device_id is None

    def test_manual_reading_without_author_rejected(self, db, world):
        with pytest.raises(ValidationFailed, match="manual"):
            VitalSignRepository(db).create(world["robert"].patient_id,
                                           dict(recorded_at=ago(minutes=2), context=ReadingContext.rest, heart_rate=70,
                                                source=ReadingSource.manual))

    def test_device_reading_requires_device(self, db, world):
        with pytest.raises(ValidationFailed, match="device_id"):
            VitalSignRepository(db).create(world["robert"].patient_id, reading(world["band"], device_id=None))

    def test_device_must_belong_to_patient(self, db, world):
        with pytest.raises(ValidationFailed, match="device"):
            VitalSignRepository(db).create(world["robert"].patient_id, reading(world["thomas_band"]))

    def test_inactive_device_rejected(self, db, world):
        from app.models.enums import DeviceStatus
        world["band"].status = DeviceStatus.lost
        db.flush()
        with pytest.raises(ValidationFailed):
            VitalSignRepository(db).create(world["robert"].patient_id, reading(world["band"]))

    def test_create_updates_device_last_sync(self, db, world):
        VitalSignRepository(db).create(world["robert"].patient_id, reading(world["band"]))
        assert world["band"].last_sync_at is not None

    def test_duplicate_idempotency_key_is_conflict(self, db, world):
        repo = VitalSignRepository(db)
        repo.create(world["robert"].patient_id, reading(world["band"], idempotency_key="hb-1-0001"))
        with pytest.raises(ConflictError, match="idempotency_key"):
            repo.create(world["robert"].patient_id, reading(world["band"], idempotency_key="hb-1-0001"))

    def test_bulk_create_counts_duplicates_suspect_and_rejected(self, db, world):
        repo = VitalSignRepository(db)
        batch = [reading(world["band"], minutes_ago=30 - i, idempotency_key=f"b-{i:04d}") for i in range(10)]
        batch[3]["heart_rate"] = 235
        batch.append(reading(world["thomas_band"], idempotency_key="b-foreign"))
        first = repo.bulk_create(world["robert"].patient_id, batch)
        assert (first["accepted"], first["duplicates"], first["flagged_suspect"]) == (10, 0, 1)
        assert first["rejected"] == [{"index": 10, "errors": ["device_id is not an active device for this patient"]}]
        replay = repo.bulk_create(world["robert"].patient_id, batch[:10])
        assert (replay["accepted"], replay["duplicates"]) == (0, 10)

    def test_bulk_create_accepts_mixed_measurement_types(self, db, world):
        # rows with different measurements (heart rate, blood pressure, spo2) in one multi-row insert
        res = VitalSignRepository(db).bulk_create(world["robert"].patient_id, [
            reading(world["band"], minutes_ago=9, idempotency_key="mix-hr"),
            reading(world["cuff"], minutes_ago=8, heart_rate=None, systolic_bp=131, diastolic_bp=82,
                    idempotency_key="mix-bp"),
            {"recorded_at": ago(minutes=7), "context": ReadingContext.rest, "spo2": 97,
             "device_id": world["band"].device_id}])
        assert res["accepted"] == 3 and res["rejected"] == []

    def test_bulk_create_rejects_manual_rows(self, db, world):
        res = VitalSignRepository(db).bulk_create(world["robert"].patient_id,
                                                  [reading(world["band"], source=ReadingSource.manual)])
        assert res["accepted"] == 0 and res["rejected"][0]["index"] == 0

    def test_list_filters_by_date_range_context_metric_quality(self, db, world):
        repo, pid = VitalSignRepository(db), world["robert"].patient_id
        repo.create(pid, reading(world["band"], minutes_ago=60 * 30, idempotency_key="old-reading-1"))
        repo.create(pid, reading(world["band"], minutes_ago=50, context=ReadingContext.exercise, heart_rate=110))
        repo.create(pid, reading(world["cuff"], minutes_ago=40, heart_rate=None, systolic_bp=128, diastolic_bp=80))
        repo.create(pid, reading(world["band"], minutes_ago=30, heart_rate=250))
        now = datetime.now(timezone.utc)
        last_day = repo.list(pid, start=now - timedelta(hours=24), end=now)
        assert last_day.total_items == 3
        assert repo.list(pid, start=now - timedelta(hours=24), end=now,
                         context=[ReadingContext.exercise]).items[0].heart_rate == 110
        assert repo.list(pid, start=now - timedelta(hours=24), end=now, metric="blood_pressure").total_items == 1
        assert repo.list(pid, start=now - timedelta(hours=24), end=now, quality=DataQuality.suspect).total_items == 1
        newest = repo.list(pid, start=now - timedelta(days=2), end=now).items
        assert newest == sorted(newest, key=lambda v: v.recorded_at, reverse=True)
        oldest = repo.list(pid, start=now - timedelta(days=2), end=now, newest_first=False).items
        assert oldest[0].idempotency_key == "old-reading-1"

    def test_end_is_exclusive(self, db, world):
        repo, pid = VitalSignRepository(db), world["robert"].patient_id
        at = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=1)
        repo.create(pid, reading(world["band"], recorded_at=at))
        assert repo.list(pid, start=at - timedelta(hours=1), end=at).total_items == 0
        assert repo.list(pid, start=at, end=at + timedelta(seconds=1)).total_items == 1

    @pytest.mark.parametrize("delta,msg", [(timedelta(days=-1), "after start"), (timedelta(days=93), "92 days")])
    def test_invalid_ranges_rejected(self, db, world, delta, msg):
        start = datetime(2026, 10, 1, tzinfo=timezone.utc)
        with pytest.raises(ValidationFailed, match=msg):
            VitalSignRepository(db).list(world["robert"].patient_id, start=start, end=start + delta)

    def test_latest_ignores_suspect_readings(self, db, world):
        repo, pid = VitalSignRepository(db), world["robert"].patient_id
        repo.create(pid, reading(world["band"], minutes_ago=20, heart_rate=70))
        repo.create(pid, reading(world["band"], minutes_ago=10, heart_rate=245))
        repo.create(pid, reading(world["cuff"], minutes_ago=15, heart_rate=None, systolic_bp=125, diastolic_bp=79))
        latest = repo.latest(pid)
        assert latest["heart_rate"].heart_rate == 70 and latest["blood_pressure"].systolic_bp == 125
        assert latest["spo2"] is None

    def test_daily_summary_aggregates_valid_readings_per_day(self, db, world):
        repo, pid = VitalSignRepository(db), world["robert"].patient_id
        d1 = datetime(2026, 10, 20, 14, 0, tzinfo=timezone.utc)
        for i, hr in enumerate((60, 70, 80)):
            repo.create(pid, reading(world["band"], recorded_at=d1 + timedelta(minutes=i), heart_rate=hr))
        repo.create(pid, reading(world["band"], recorded_at=d1 + timedelta(minutes=9), heart_rate=241))
        repo.create(pid, reading(world["cuff"], recorded_at=d1 + timedelta(days=1), heart_rate=None,
                                 systolic_bp=130, diastolic_bp=80))
        rows = repo.daily_summary(pid, date(2026, 10, 20), date(2026, 10, 22))
        assert [r["reading_date"] for r in rows] == [date(2026, 10, 20), date(2026, 10, 21)]
        day1 = rows[0]
        assert (day1["readings"], day1["avg_hr"], day1["min_hr"], day1["max_hr"], day1["flagged_readings"]) == \
               (4, 70.0, 60, 80, 1)
        assert rows[1]["avg_sbp"] == 130.0 and rows[1]["avg_hr"] is None

    def test_update_only_context_and_quality(self, db, world):
        repo = VitalSignRepository(db)
        v = repo.create(world["robert"].patient_id, reading(world["band"]))
        _, changed = repo.update(v.vital_id, {"quality": DataQuality.artifact})
        assert changed == ["quality"] and repo.get(v.vital_id).quality == DataQuality.artifact
        with pytest.raises(ValidationFailed, match="heart_rate"):
            repo.update(v.vital_id, {"heart_rate": 90})

    def test_delete_and_get_missing(self, db, world):
        repo = VitalSignRepository(db)
        v = repo.create(world["robert"].patient_id, reading(world["band"]))
        repo.delete(v.vital_id)
        with pytest.raises(NotFoundError):
            repo.get(v.vital_id)


# ---------------------------------------------------------------- activity and devices

class TestActivityRepository:
    def test_upsert_creates_then_replaces(self, db, world):
        repo, pid, d = ActivityRepository(db), world["robert"].patient_id, date(2026, 10, 20)
        row, created = repo.upsert(pid, d, {"steps": 5000, "active_minutes": 30, "resting_hr": 66})
        assert created and row.steps == 5000
        row, created = repo.upsert(pid, d, {"steps": 6100, "active_minutes": 41})
        assert not created and row.steps == 6100 and row.resting_hr is None    # put replaces the whole day

    def test_upsert_rejects_future_date_and_foreign_device(self, db, world):
        repo = ActivityRepository(db)
        with pytest.raises(ValidationFailed, match="future"):
            repo.upsert(world["robert"].patient_id, date.today() + timedelta(days=5), {"steps": 1, "active_minutes": 1})
        with pytest.raises(ValidationFailed, match="device"):
            repo.upsert(world["robert"].patient_id, date(2026, 10, 1),
                        {"steps": 1, "active_minutes": 1, "device_id": world["thomas_band"].device_id})

    def test_check_violation_translated(self, db, world):
        with pytest.raises(ValidationFailed, match="1440"):
            ActivityRepository(db).upsert(world["robert"].patient_id, date(2026, 10, 1),
                                          {"steps": 1, "active_minutes": 900, "sedentary_minutes": 900})

    def test_list_range_summary_and_delete(self, db, world):
        repo, pid = ActivityRepository(db), world["robert"].patient_id
        for i in range(10):
            repo.upsert(pid, date(2026, 10, 1) + timedelta(days=i), {"steps": 1000 * (i + 1), "active_minutes": 10 + i,
                                                                    "resting_hr": 60 + i})
        rows = repo.list(pid, date(2026, 10, 3), date(2026, 10, 5))
        assert [r.activity_date.day for r in rows] == [3, 4, 5]
        s = repo.summary(pid, date(2026, 10, 1), date(2026, 10, 7))
        assert (s["days_reported"], s["days_in_range"], s["total_steps"], s["avg_steps"]) == (7, 7, 28000, 4000.0)
        assert s["avg_resting_hr"] == 63.0
        repo.delete(pid, date(2026, 10, 1))
        with pytest.raises(NotFoundError):
            repo.get(pid, date(2026, 10, 1))
        assert repo.delete_range(pid, date(2026, 10, 2), date(2026, 10, 4)) == 3

    def test_empty_summary(self, db, world):
        s = ActivityRepository(db).summary(world["linda"].patient_id, date(2026, 10, 1), date(2026, 10, 7))
        assert s["days_reported"] == 0 and s["avg_steps"] is None and s["total_steps"] == 0


class TestDeviceRepository:
    def test_register_list_get(self, db, world):
        repo = DeviceRepository(db)
        d = repo.register(world["linda"].patient_id, {"device_type": DeviceType.pulse_oximeter,
                                                      "manufacturer": "Corvane", "model": "OX-1",
                                                      "serial_number": "OX1-LINDA-1"})
        assert [x.device_id for x in repo.list_for_patient(world["linda"].patient_id)] == [d.device_id]
        assert repo.get(d.device_id).status.value == "active"
        with pytest.raises(NotFoundError):
            repo.get(uuid.uuid4())

    def test_duplicate_serial_conflict(self, db, world):
        with pytest.raises(ConflictError, match="serial"):
            DeviceRepository(db).register(world["linda"].patient_id, {
                "device_type": DeviceType.heart_rate_band, "manufacturer": "Corvane", "model": "HB-2",
                "serial_number": world["band"].serial_number})


# ---------------------------------------------------------------- users, sessions, audit

class TestUserAndAuditRepositories:
    def test_email_lookup_is_case_insensitive(self, db):
        u = make_user(db, UserRole.clinician, email="nina.cho@test.example")
        assert UserRepository(db).get_by_email("  Nina.Cho@TEST.example ").user_id == u.user_id

    def test_failed_logins_lock_account(self, db):
        u = make_user(db, UserRole.clinician)
        repo = UserRepository(db)
        for _ in range(5):
            repo.record_failed_login(u, 5, timedelta(minutes=15))
        assert u.locked_until is not None and u.failed_login_attempts == 0
        repo.record_successful_login(u)
        assert u.locked_until is None and u.last_login_at is not None

    def test_sessions_revoke(self, db):
        u = make_user(db, UserRole.patient)
        repo = UserRepository(db)
        s1 = repo.create_session(u.user_id, "a" * 64, timedelta(hours=1))
        repo.create_session(u.user_id, "b" * 64, timedelta(hours=1))
        assert repo.session_is_live(s1)
        assert repo.revoke_all_sessions(u.user_id) == 2
        db.refresh(s1)
        assert not repo.session_is_live(s1)

    def test_duplicate_email_conflict(self, db):
        make_user(db, UserRole.clinician, email="dup@test.example")
        with pytest.raises(ConflictError, match="email"):
            UserRepository(db).create(dict(email="dup@test.example", password_hash="$2b$04$" + "x" * 53,
                                           role=UserRole.clinician, first_name="A", last_name="B"))

    def test_get_missing_user(self, db):
        with pytest.raises(NotFoundError):
            UserRepository(db).get(uuid.uuid4())

    def test_audit_record_and_filter(self, db, world):
        repo = AuditRepository(db)
        repo.record(AuditAction.read, "vital_signs", actor=world["dana"], patient_id=world["robert"].patient_id,
                    details={"rows": 3})
        repo.record(AuditAction.update, "patients", actor=world["admin"], patient_id=world["robert"].patient_id)
        res = repo.list(patient_id=world["robert"].patient_id)
        assert res.total_items == 2 and res.items[0].action == AuditAction.update
        assert repo.list(actor_user_id=world["dana"].user_id, action=AuditAction.read).total_items == 1
        assert repo.list(start=ago(hours=1), end=ago(seconds=-60)).total_items >= 2


class TestErrorTranslation:
    def test_operational_error_becomes_503_and_is_logged(self, db, caplog):
        with caplog.at_level(logging.ERROR, logger="healthtrack"):
            with pytest.raises(DataAccessError):
                with db_errors(db, "thing", "probe"):
                    raise OperationalError("SELECT 1", {}, Exception("connection refused"))
        assert any(r.getMessage() == "database unavailable" for r in caplog.records)

    def test_unknown_foreign_key_message(self, db, world):
        with pytest.raises(ValidationFailed, match="does not exist"):
            ActivityRepository(db).upsert(uuid.uuid4(), date(2026, 10, 1), {"steps": 1, "active_minutes": 1})
