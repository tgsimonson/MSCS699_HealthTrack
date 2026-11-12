"""vital sign, daily activity, and device data access"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import Date, case, cast, delete, func, select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import NotFoundError, ValidationFailed
from app.logging_config import get_logger
from app.models import DailyActivity, Device, VitalSign
from app.models.base import utcnow
from app.models.enums import DataQuality, DeviceStatus, ReadingContext, ReadingSource
from app.repositories.base import PageResult, db_errors, paginate

log = get_logger("dal.monitoring")

BATCH_COLUMNS = ("recorded_at", "context", "heart_rate", "systolic_bp", "diastolic_bp", "spo2", "device_id",
                 "idempotency_key")
METRIC_COLUMN = {"heart_rate": VitalSign.heart_rate, "blood_pressure": VitalSign.systolic_bp,
                 "spo2": VitalSign.spo2}


def check_range(start: datetime | date | None, end: datetime | date | None, max_days: int) -> None:
    if start and end:
        if end <= start:
            raise ValidationFailed("end must be after start",
                                   errors=[{"field": "end", "message": "must be after start", "code": "range_order"}])
        if (end - start) > timedelta(days=max_days):
            raise ValidationFailed(f"date range cannot exceed {max_days} days",
                                   errors=[{"field": "end", "message": f"range exceeds {max_days} days",
                                            "code": "range_too_long"}])


class DeviceRepository:
    def __init__(self, session: Session) -> None:
        self.s = session

    def register(self, patient_id: uuid.UUID, data: dict[str, Any]) -> Device:
        """register a device and assign it to the patient as active"""
        device = Device(**data, patient_id=patient_id, status=DeviceStatus.active)
        with db_errors(self.s, "device", "register"):
            self.s.add(device)
        log.info("device registered", extra={"ctx": {"device_id": str(device.device_id), "patient_id": str(patient_id)}})
        return device

    def list_for_patient(self, patient_id: uuid.UUID) -> list[Device]:
        return list(self.s.scalars(select(Device).where(Device.patient_id == patient_id)
                                   .order_by(Device.device_type, Device.created_at)))

    def get(self, device_id: uuid.UUID) -> Device:
        device = self.s.get(Device, device_id)
        if device is None:
            raise NotFoundError("device not found")
        return device

    def ensure_owned(self, device_id: uuid.UUID | None, patient_id: uuid.UUID) -> None:
        """a reading may only reference an active device assigned to the same patient"""
        if device_id is None:
            return
        device = self.s.get(Device, device_id)
        if device is None or device.patient_id != patient_id or device.status != DeviceStatus.active:
            raise ValidationFailed("device_id must reference an active device assigned to this patient",
                                   errors=[{"field": "device_id", "message": "not an active device for this patient",
                                            "code": "invalid_reference"}])

    def touch_sync(self, device_ids: set[uuid.UUID]) -> None:
        if device_ids:
            for d in self.s.scalars(select(Device).where(Device.device_id.in_(device_ids))):
                d.last_sync_at = utcnow()


class VitalSignRepository:
    def __init__(self, session: Session) -> None:
        self.s = session
        self.devices = DeviceRepository(session)
        self.settings = get_settings()

    # ---------------------------------------------------------------- create
    def create(self, patient_id: uuid.UUID, data: dict[str, Any], *, entered_by: uuid.UUID | None = None) -> VitalSign:
        """store one reading; implausible-but-possible values are stored with quality=suspect"""
        self._validate_source(data, entered_by)
        self.devices.ensure_owned(data.get("device_id"), patient_id)
        quality = VitalSign.assess_quality(data.get("heart_rate"), data.get("systolic_bp"), data.get("diastolic_bp"),
                                           data.get("spo2"))
        vital = VitalSign(patient_id=patient_id, quality=quality,
                          entered_by=entered_by if data.get("source") == ReadingSource.manual else None, **data)
        with db_errors(self.s, "vital sign", "create"):
            self.s.add(vital)
        self.devices.touch_sync({vital.device_id} if vital.device_id else set())
        log.info("vital recorded", extra={"ctx": {"patient_id": str(patient_id), "vital_id": vital.vital_id,
                                                  "quality": quality.value}})
        return vital

    def bulk_create(self, patient_id: uuid.UUID, readings: list[dict[str, Any]]) -> dict[str, Any]:
        """insert a device batch in one statement; replays with a known idempotency_key are skipped, not failed"""
        rows, rejected, suspect = [], [], 0
        owned: dict[uuid.UUID | None, bool] = {}
        for i, r in enumerate(readings):
            dev = r.get("device_id")
            if dev not in owned:
                try:
                    self.devices.ensure_owned(dev, patient_id)
                    owned[dev] = True
                except ValidationFailed:
                    owned[dev] = False
            if not owned[dev]:
                rejected.append({"index": i, "errors": ["device_id is not an active device for this patient"]})
                continue
            if r.get("source") == ReadingSource.manual:
                rejected.append({"index": i, "errors": ["batch uploads accept device readings only"]})
                continue
            q = VitalSign.assess_quality(r.get("heart_rate"), r.get("systolic_bp"), r.get("diastolic_bp"),
                                         r.get("spo2"))
            suspect += q == DataQuality.suspect
            # a multi-row INSERT needs the same columns in every row, so fill omitted measurements with NULL
            rows.append({**dict.fromkeys(BATCH_COLUMNS), **r, "patient_id": patient_id, "quality": q,
                         "received_at": utcnow(), "source": r.get("source", ReadingSource.device)})
        ids: list[int] = []
        if rows:
            ins = (postgresql.insert(VitalSign) if self.s.bind.dialect.name == "postgresql" else sqlite.insert(VitalSign))
            stmt = ins.values(rows).on_conflict_do_nothing(index_elements=["patient_id", "idempotency_key"])
            with db_errors(self.s, "vital sign batch", "bulk_create"):
                ids = [r[0] for r in self.s.execute(stmt.returning(VitalSign.vital_id)).all()]
            self.devices.touch_sync({r["device_id"] for r in rows if r.get("device_id")})
        inserted = len(ids)
        result = {"accepted": inserted, "duplicates": len(rows) - inserted, "flagged_suspect": suspect,
                  "rejected": rejected, "vital_ids": ids}
        log.info("vital batch stored", extra={"ctx": {"patient_id": str(patient_id), "received": len(readings),
                                                      **{k: v for k, v in result.items()
                                                         if k not in ("rejected", "vital_ids")},
                                                      "rejected": len(rejected)}})
        return result

    # ---------------------------------------------------------------- alert engine queries
    def load(self, vital_ids: list[int]) -> list[VitalSign]:
        if not vital_ids:
            return []
        return list(self.s.scalars(select(VitalSign).where(VitalSign.vital_id.in_(vital_ids))
                                   .order_by(VitalSign.recorded_at, VitalSign.vital_id)))

    def prior_values(self, patient_id: uuid.UUID, metric: str, contexts: list[str] | None, before: datetime,
                     within_minutes: int, limit: int) -> list[int]:
        """the previous valid values of one measurement, newest first (consecutive-reading rules)"""
        col = getattr(VitalSign, metric)
        stmt = select(col).where(VitalSign.patient_id == patient_id, col.is_not(None),
                                 VitalSign.quality == DataQuality.valid, VitalSign.recorded_at < before,
                                 VitalSign.recorded_at >= before - timedelta(minutes=within_minutes))
        if contexts:
            stmt = stmt.where(VitalSign.context.in_(contexts))
        return list(self.s.scalars(stmt.order_by(VitalSign.recorded_at.desc()).limit(limit)))

    def exercise_heart_rates(self, patient_id: uuid.UUID, start: datetime, end: datetime) -> list[tuple[datetime, int]]:
        """valid exercise-phase heart rates in [start, end), oldest first (session and zone-minute patterns)"""
        rows = self.s.execute(select(VitalSign.recorded_at, VitalSign.heart_rate).where(
            VitalSign.patient_id == patient_id, VitalSign.recorded_at >= start, VitalSign.recorded_at < end,
            VitalSign.context == ReadingContext.exercise, VitalSign.heart_rate.is_not(None),
            VitalSign.quality == DataQuality.valid).order_by(VitalSign.recorded_at))
        return [(r[0], r[1]) for r in rows]

    def last_reading_at(self, patient_id: uuid.UUID) -> datetime | None:
        return self.s.scalar(select(func.max(VitalSign.recorded_at)).where(VitalSign.patient_id == patient_id))

    # ---------------------------------------------------------------- read
    def get(self, vital_id: int) -> VitalSign:
        vital = self.s.get(VitalSign, vital_id)
        if vital is None:
            raise NotFoundError("vital sign not found")
        return vital

    def list(self, patient_id: uuid.UUID, *, start: datetime | None = None, end: datetime | None = None,
             context: list[ReadingContext] | None = None, metric: str | None = None,
             quality: DataQuality | None = None, newest_first: bool = True, page: int = 1,
             page_size: int = 50) -> PageResult[VitalSign]:
        """readings for one patient in [start, end), filtered; served by ix_vital_signs_patient_time"""
        check_range(start, end, self.settings.max_query_days)
        stmt = select(VitalSign).where(VitalSign.patient_id == patient_id)
        if start:
            stmt = stmt.where(VitalSign.recorded_at >= start)
        if end:
            stmt = stmt.where(VitalSign.recorded_at < end)
        if context:
            stmt = stmt.where(VitalSign.context.in_(context))
        if metric:
            stmt = stmt.where(METRIC_COLUMN[metric].is_not(None))
        if quality:
            stmt = stmt.where(VitalSign.quality == quality)
        order = VitalSign.recorded_at.desc() if newest_first else VitalSign.recorded_at
        return paginate(self.s, stmt.order_by(order, VitalSign.vital_id), page, page_size)

    def latest(self, patient_id: uuid.UUID) -> dict[str, VitalSign | None]:
        """most recent valid reading of each measurement (three small index-backed lookups)"""
        out: dict[str, VitalSign | None] = {}
        for key, col in METRIC_COLUMN.items():
            out[key] = self.s.scalar(select(VitalSign).where(VitalSign.patient_id == patient_id, col.is_not(None),
                                                             VitalSign.quality == DataQuality.valid)
                                     .order_by(VitalSign.recorded_at.desc()).limit(1))
        return out

    def daily_summary(self, patient_id: uuid.UUID, start: date, end: date,
                      context: ReadingContext | None = None) -> list[dict[str, Any]]:
        """per-day aggregates computed in the database (utc days), so only one row per day crosses the wire"""
        check_range(start, end, self.settings.max_query_days)
        if self.s.bind.dialect.name == "postgresql":
            day = cast(func.timezone("UTC", VitalSign.recorded_at), Date)
        else:
            day = func.date(VitalSign.recorded_at)
        valid = VitalSign.quality == DataQuality.valid
        stmt = (select(day.label("reading_date"), func.count().label("readings"),
                       func.avg(case((valid, VitalSign.heart_rate))).label("avg_hr"),
                       func.min(case((valid, VitalSign.heart_rate))).label("min_hr"),
                       func.max(case((valid, VitalSign.heart_rate))).label("max_hr"),
                       func.avg(case((valid, VitalSign.systolic_bp))).label("avg_sbp"),
                       func.avg(case((valid, VitalSign.diastolic_bp))).label("avg_dbp"),
                       func.min(case((valid, VitalSign.spo2))).label("min_spo2"),
                       func.sum(case((valid, 0), else_=1)).label("flagged_readings"))
                .where(VitalSign.patient_id == patient_id,
                       VitalSign.recorded_at >= datetime.combine(start, datetime.min.time(), tzinfo=_utc()),
                       VitalSign.recorded_at < datetime.combine(end, datetime.min.time(), tzinfo=_utc())
                       + timedelta(days=1))
                .group_by(day).order_by(day))
        if context:
            stmt = stmt.where(VitalSign.context == context)
        out = []
        for r in self.s.execute(stmt):
            d = r.reading_date if isinstance(r.reading_date, date) else date.fromisoformat(r.reading_date)
            out.append({"reading_date": d, "readings": r.readings,
                        "avg_hr": _round(r.avg_hr), "min_hr": r.min_hr, "max_hr": r.max_hr,
                        "avg_sbp": _round(r.avg_sbp), "avg_dbp": _round(r.avg_dbp), "min_spo2": r.min_spo2,
                        "flagged_readings": int(r.flagged_readings or 0)})
        return out

    # ---------------------------------------------------------------- update / delete
    def update(self, vital_id: int, changes: dict[str, Any]) -> tuple[VitalSign, list[str]]:
        """only context and quality may change; measured values are immutable for data integrity"""
        illegal = set(changes) - {"context", "quality"}
        if illegal:
            raise ValidationFailed(f"cannot change {', '.join(sorted(illegal))} on a stored reading")
        vital = self.get(vital_id)
        changed = [k for k, v in changes.items() if getattr(vital, k) != v]
        with db_errors(self.s, "vital sign", "update"):
            for k in changed:
                setattr(vital, k, changes[k])
        log.info("vital updated", extra={"ctx": {"vital_id": vital_id, "columns": changed}})
        return vital, changed

    def delete(self, vital_id: int) -> VitalSign:
        vital = self.get(vital_id)
        with db_errors(self.s, "vital sign", "delete"):
            self.s.delete(vital)
        log.warning("vital deleted", extra={"ctx": {"vital_id": vital_id, "patient_id": str(vital.patient_id)}})
        return vital

    @staticmethod
    def _validate_source(data: dict[str, Any], entered_by: uuid.UUID | None) -> None:
        source = data.get("source", ReadingSource.device)
        if source == ReadingSource.manual and entered_by is None:
            raise ValidationFailed("manual readings must record who entered them")
        if source == ReadingSource.device and not data.get("device_id"):
            raise ValidationFailed("device readings must include device_id",
                                   errors=[{"field": "device_id", "message": "required when source is device",
                                            "code": "missing"}])


class ActivityRepository:
    def __init__(self, session: Session) -> None:
        self.s = session
        self.devices = DeviceRepository(session)
        self.settings = get_settings()

    def upsert(self, patient_id: uuid.UUID, activity_date: date, data: dict[str, Any]) -> tuple[DailyActivity, bool]:
        """create or replace one day's totals; returns (row, created)"""
        if activity_date > date.today() + timedelta(days=1):
            raise ValidationFailed("activity_date cannot be in the future")
        self.devices.ensure_owned(data.get("device_id"), patient_id)
        row = self.s.get(DailyActivity, (patient_id, activity_date))
        created = row is None
        with db_errors(self.s, "daily activity", "upsert"):
            if created:
                row = DailyActivity(patient_id=patient_id, activity_date=activity_date, **data)
                self.s.add(row)
            else:
                for k, v in data.items():
                    setattr(row, k, v)
                for k in ("sedentary_minutes", "resting_hr", "distance_m", "device_id"):
                    if k not in data:                   # put replaces the whole day
                        setattr(row, k, None)
        log.info("activity stored", extra={"ctx": {"patient_id": str(patient_id), "date": str(activity_date),
                                                   "created": created}})
        return row, created  # type: ignore[return-value]

    def get(self, patient_id: uuid.UUID, activity_date: date) -> DailyActivity:
        row = self.s.get(DailyActivity, (patient_id, activity_date))
        if row is None:
            raise NotFoundError("no activity recorded for this date")
        return row

    def list(self, patient_id: uuid.UUID, start: date | None = None, end: date | None = None) -> list[DailyActivity]:
        """days in [start, end] inclusive, oldest first (primary key range scan)"""
        check_range(start, end, self.settings.max_query_days * 4)
        stmt = select(DailyActivity).where(DailyActivity.patient_id == patient_id)
        if start:
            stmt = stmt.where(DailyActivity.activity_date >= start)
        if end:
            stmt = stmt.where(DailyActivity.activity_date <= end)
        return list(self.s.scalars(stmt.order_by(DailyActivity.activity_date)))

    def summary(self, patient_id: uuid.UUID, start: date, end: date) -> dict[str, Any]:
        check_range(start, end, self.settings.max_query_days * 4)
        r = self.s.execute(select(func.count(), func.coalesce(func.sum(DailyActivity.steps), 0),
                                  func.avg(DailyActivity.steps),
                                  func.coalesce(func.sum(DailyActivity.active_minutes), 0),
                                  func.avg(DailyActivity.active_minutes), func.avg(DailyActivity.resting_hr))
                           .where(DailyActivity.patient_id == patient_id, DailyActivity.activity_date >= start,
                                  DailyActivity.activity_date <= end)).one()
        return {"start_date": start, "end_date": end, "days_reported": r[0], "days_in_range": (end - start).days + 1,
                "total_steps": int(r[1]), "avg_steps": _round(r[2]), "total_active_minutes": int(r[3]),
                "avg_active_minutes": _round(r[4]), "avg_resting_hr": _round(r[5])}

    def delete(self, patient_id: uuid.UUID, activity_date: date) -> None:
        row = self.get(patient_id, activity_date)
        with db_errors(self.s, "daily activity", "delete"):
            self.s.delete(row)
        log.warning("activity deleted", extra={"ctx": {"patient_id": str(patient_id), "date": str(activity_date)}})

    def delete_range(self, patient_id: uuid.UUID, start: date, end: date) -> int:
        with db_errors(self.s, "daily activity", "delete_range"):
            n = self.s.execute(delete(DailyActivity).where(DailyActivity.patient_id == patient_id,
                                                           DailyActivity.activity_date.between(start, end))).rowcount
        return n or 0


def _round(v: Any) -> float | None:
    return None if v is None else round(float(v), 1)


def _utc():  # noqa: ANN202
    from datetime import timezone
    return timezone.utc
