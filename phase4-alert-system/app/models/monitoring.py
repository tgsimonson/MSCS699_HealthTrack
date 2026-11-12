"""monitoring data: vital signs, daily activity, devices"""
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (CheckConstraint, Date, ForeignKey, Index, Integer, SmallInteger, String, UniqueConstraint, event,
                        Uuid)
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from app.models.base import BigIntPK, Base, TimestampMixin, UTCDateTime, new_uuid, utcnow
from app.models.enums import (DataQuality, DeviceStatus, DeviceType, ReadingContext, ReadingSource, sa_enum)

# hard limits reject physically impossible values; soft limits only flag a reading as suspect
HARD_LIMITS = {"heart_rate": (20, 300), "systolic_bp": (50, 300), "diastolic_bp": (20, 200), "spo2": (50, 100)}
SOFT_LIMITS = {"heart_rate": (30, 220), "systolic_bp": (70, 250), "diastolic_bp": (35, 140), "spo2": (70, 100)}
MIN_PULSE_PRESSURE = 15


class Device(TimestampMixin, Base):
    """added by migration 0002 (device registry)"""

    __tablename__ = "devices"
    __table_args__ = (
        UniqueConstraint("manufacturer", "serial_number"),
        CheckConstraint("status <> 'active' OR patient_id IS NOT NULL", name="active_has_patient"),
        Index("ix_devices_patient", "patient_id"),
    )

    device_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    patient_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("patients.patient_id", ondelete="SET NULL"))
    device_type: Mapped[DeviceType] = mapped_column(sa_enum(DeviceType, "device_type"), nullable=False)
    manufacturer: Mapped[str] = mapped_column(String(60), nullable=False)
    model: Mapped[str] = mapped_column(String(60), nullable=False)
    serial_number: Mapped[str] = mapped_column(String(60), nullable=False)
    status: Mapped[DeviceStatus] = mapped_column(sa_enum(DeviceStatus, "device_status"),
                                                 default=DeviceStatus.inactive, nullable=False)
    last_sync_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    patient: Mapped["Patient | None"] = relationship(back_populates="devices")  # noqa: F821


@event.listens_for(Session, "before_flush")
def _release_devices_of_deleted_patients(session: Session, _ctx, _instances) -> None:  # noqa: ANN001
    """when a patient is removed, return their devices to inventory instead of leaving an orphaned active device"""
    from app.models.patient import Patient
    for obj in list(session.deleted):
        if isinstance(obj, Patient):
            for device in list(obj.devices):
                device.status = DeviceStatus.inactive
                device.patient_id = None


class VitalSign(Base):
    __tablename__ = "vital_signs"
    __table_args__ = (
        CheckConstraint("heart_rate IS NULL OR heart_rate BETWEEN 20 AND 300", name="heart_rate_range"),
        CheckConstraint("systolic_bp IS NULL OR systolic_bp BETWEEN 50 AND 300", name="systolic_range"),
        CheckConstraint("diastolic_bp IS NULL OR diastolic_bp BETWEEN 20 AND 200", name="diastolic_range"),
        CheckConstraint("spo2 IS NULL OR spo2 BETWEEN 50 AND 100", name="spo2_range"),
        CheckConstraint("heart_rate IS NOT NULL OR systolic_bp IS NOT NULL OR spo2 IS NOT NULL", name="has_measurement"),
        CheckConstraint("(systolic_bp IS NULL) = (diastolic_bp IS NULL)", name="bp_pair"),
        CheckConstraint("systolic_bp IS NULL OR systolic_bp > diastolic_bp", name="bp_order"),
        CheckConstraint("source <> 'manual' OR entered_by IS NOT NULL", name="manual_has_author"),
        UniqueConstraint("patient_id", "idempotency_key"),
        # covers every per-patient time-range query (the dominant access pattern)
        Index("ix_vital_signs_patient_time", "patient_id", "recorded_at"),
        Index("ix_vital_signs_device", "device_id"),
    )

    vital_id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.patient_id", ondelete="CASCADE"), nullable=False)
    device_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("devices.device_id", ondelete="SET NULL"))
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    received_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    context: Mapped[ReadingContext] = mapped_column(sa_enum(ReadingContext, "reading_context"), nullable=False)
    heart_rate: Mapped[int | None] = mapped_column(SmallInteger)
    systolic_bp: Mapped[int | None] = mapped_column(SmallInteger)
    diastolic_bp: Mapped[int | None] = mapped_column(SmallInteger)
    spo2: Mapped[int | None] = mapped_column(SmallInteger)
    source: Mapped[ReadingSource] = mapped_column(sa_enum(ReadingSource, "reading_source"),
                                                  default=ReadingSource.device, nullable=False)
    # restrict: accounts are deactivated, never deleted, so a manual reading always keeps its author
    entered_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.user_id", ondelete="RESTRICT"))
    quality: Mapped[DataQuality] = mapped_column(sa_enum(DataQuality, "data_quality"),
                                                 default=DataQuality.valid, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(64))

    patient: Mapped["Patient"] = relationship(back_populates="vitals")  # noqa: F821
    device: Mapped[Device | None] = relationship()

    @staticmethod
    def assess_quality(heart_rate: int | None, systolic_bp: int | None, diastolic_bp: int | None,
                       spo2: int | None) -> DataQuality:
        """flag possible-but-unlikely values so they are stored but never alert"""
        values = {"heart_rate": heart_rate, "systolic_bp": systolic_bp, "diastolic_bp": diastolic_bp, "spo2": spo2}
        for name, v in values.items():
            lo, hi = SOFT_LIMITS[name]
            if v is not None and not lo <= v <= hi:
                return DataQuality.suspect
        if systolic_bp is not None and diastolic_bp is not None and systolic_bp - diastolic_bp < MIN_PULSE_PRESSURE:
            return DataQuality.suspect
        return DataQuality.valid


class DailyActivity(TimestampMixin, Base):
    __tablename__ = "daily_activity"
    __table_args__ = (
        CheckConstraint("steps BETWEEN 0 AND 100000", name="steps_range"),
        CheckConstraint("active_minutes BETWEEN 0 AND 1440", name="active_minutes_range"),
        CheckConstraint("sedentary_minutes IS NULL OR sedentary_minutes BETWEEN 0 AND 1440", name="sedentary_range"),
        CheckConstraint("active_minutes + coalesce(sedentary_minutes, 0) <= 1440", name="minutes_fit_in_day"),
        CheckConstraint("resting_hr IS NULL OR resting_hr BETWEEN 25 AND 150", name="resting_hr_range"),
        CheckConstraint("distance_m IS NULL OR distance_m BETWEEN 0 AND 100000", name="distance_range"),
    )

    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.patient_id", ondelete="CASCADE"),
                                                  primary_key=True)
    activity_date: Mapped[date] = mapped_column(Date, primary_key=True)
    steps: Mapped[int] = mapped_column(Integer, nullable=False)
    active_minutes: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    sedentary_minutes: Mapped[int | None] = mapped_column(SmallInteger)
    resting_hr: Mapped[int | None] = mapped_column(SmallInteger)
    distance_m: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[ReadingSource] = mapped_column(sa_enum(ReadingSource, "reading_source"),
                                                  default=ReadingSource.device, nullable=False)
    device_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("devices.device_id", ondelete="SET NULL"))

    patient: Mapped["Patient"] = relationship(back_populates="activity")  # noqa: F821
