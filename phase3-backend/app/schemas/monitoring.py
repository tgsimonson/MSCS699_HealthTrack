"""vital sign, activity, and device schemas"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from pydantic import AwareDatetime, Field, field_validator, model_validator

from app.models.enums import DataQuality, DeviceStatus, DeviceType, ReadingContext, ReadingSource
from app.schemas.common import ApiModel

CLOCK_SKEW = timedelta(minutes=5)


class VitalSignCreate(ApiModel):
    recorded_at: AwareDatetime = Field(description="Device clock time with UTC offset. Max 5 minutes in the future.")
    context: ReadingContext
    heart_rate: int | None = Field(default=None, ge=20, le=300, description="bpm")
    systolic_bp: int | None = Field(default=None, ge=50, le=300, description="mmHg")
    diastolic_bp: int | None = Field(default=None, ge=20, le=200, description="mmHg")
    spo2: int | None = Field(default=None, ge=50, le=100, description="percent")
    device_id: uuid.UUID | None = None
    source: ReadingSource = ReadingSource.device
    idempotency_key: str | None = Field(default=None, pattern=r"^[A-Za-z0-9._:-]{8,64}$")

    model_config = {"json_schema_extra": {"examples": [{
        "recorded_at": "2026-10-21T09:48:00-06:00", "context": "exercise", "heart_rate": 138,
        "device_id": "00000000-0000-4000-c000-000000000051", "source": "device",
        "idempotency_key": "hb-5-202610211548"}]}}

    @field_validator("recorded_at")
    @classmethod
    def _not_future(cls, v: datetime) -> datetime:
        if v > datetime.now(timezone.utc) + CLOCK_SKEW:
            raise ValueError("recorded_at is in the future")
        return v

    @model_validator(mode="after")
    def _rules(self) -> VitalSignCreate:
        if self.heart_rate is None and self.systolic_bp is None and self.spo2 is None:
            raise ValueError("at least one of heart_rate, systolic_bp/diastolic_bp, or spo2 is required")
        if (self.systolic_bp is None) != (self.diastolic_bp is None):
            raise ValueError("systolic_bp and diastolic_bp must be sent together")
        if self.systolic_bp is not None and self.systolic_bp <= self.diastolic_bp:  # type: ignore[operator]
            raise ValueError("systolic_bp must be greater than diastolic_bp")
        return self


class VitalSignUpdate(ApiModel):
    """clinicians may correct the context or mark a reading as an artifact; measured values are immutable"""

    context: ReadingContext | None = None
    quality: DataQuality | None = None

    model_config = {"json_schema_extra": {"examples": [{"quality": "artifact"}]}}


class VitalSignOut(ApiModel):
    vital_id: int
    patient_id: uuid.UUID
    device_id: uuid.UUID | None
    recorded_at: datetime
    received_at: datetime
    context: ReadingContext
    heart_rate: int | None
    systolic_bp: int | None
    diastolic_bp: int | None
    spo2: int | None
    source: ReadingSource
    entered_by: uuid.UUID | None
    quality: DataQuality
    idempotency_key: str | None


class VitalBatchCreate(ApiModel):
    readings: list[VitalSignCreate] = Field(min_length=1, max_length=500)


class RejectedReading(ApiModel):
    index: int
    errors: list[str]


class VitalBatchResult(ApiModel):
    accepted: int
    duplicates: int
    flagged_suspect: int
    rejected: list[RejectedReading]

    model_config = {"json_schema_extra": {"examples": [{"accepted": 58, "duplicates": 2, "flagged_suspect": 1,
                                                         "rejected": []}]}}


class LatestVitals(ApiModel):
    heart_rate: VitalSignOut | None
    blood_pressure: VitalSignOut | None
    spo2: VitalSignOut | None


class DailyVitalSummary(ApiModel):
    reading_date: date
    readings: int
    avg_hr: float | None
    min_hr: int | None
    max_hr: int | None
    avg_sbp: float | None
    avg_dbp: float | None
    min_spo2: int | None
    flagged_readings: int


class DailyActivityUpsert(ApiModel):
    steps: int = Field(ge=0, le=100000)
    active_minutes: int = Field(ge=0, le=1440)
    sedentary_minutes: int | None = Field(default=None, ge=0, le=1440)
    resting_hr: int | None = Field(default=None, ge=25, le=150)
    distance_m: int | None = Field(default=None, ge=0, le=100000)
    source: ReadingSource = ReadingSource.device
    device_id: uuid.UUID | None = None

    model_config = {"json_schema_extra": {"examples": [{
        "steps": 7046, "active_minutes": 48, "sedentary_minutes": 552, "resting_hr": 64, "distance_m": 5120,
        "source": "device", "device_id": "00000000-0000-4000-c000-000000000054"}]}}

    @model_validator(mode="after")
    def _fits_in_day(self) -> DailyActivityUpsert:
        if self.active_minutes + (self.sedentary_minutes or 0) > 1440:
            raise ValueError("active_minutes plus sedentary_minutes cannot exceed 1440")
        return self


class DailyActivityOut(ApiModel):
    patient_id: uuid.UUID
    activity_date: date
    steps: int
    active_minutes: int
    sedentary_minutes: int | None
    resting_hr: int | None
    distance_m: int | None
    source: ReadingSource
    device_id: uuid.UUID | None
    updated_at: datetime


class ActivitySummary(ApiModel):
    start_date: date
    end_date: date
    days_reported: int
    days_in_range: int
    total_steps: int
    avg_steps: float | None
    total_active_minutes: int
    avg_active_minutes: float | None
    avg_resting_hr: float | None


class DeviceCreate(ApiModel):
    device_type: DeviceType
    manufacturer: str = Field(min_length=1, max_length=60)
    model: str = Field(min_length=1, max_length=60)
    serial_number: str = Field(min_length=1, max_length=60)

    model_config = {"json_schema_extra": {"examples": [{"device_type": "heart_rate_band", "manufacturer": "Corvane",
                                                         "model": "HB-2 Chest Strap", "serial_number": "HB2-900417"}]}}


class DeviceOut(ApiModel):
    device_id: uuid.UUID
    patient_id: uuid.UUID | None
    device_type: DeviceType
    manufacturer: str
    model: str
    serial_number: str
    status: DeviceStatus
    last_sync_at: datetime | None
