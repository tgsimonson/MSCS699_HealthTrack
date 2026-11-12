"""daily activity tracking and device registration"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Response, status

from app.alerts.service import process_activity
from app.api.deps import CARE_ROLES, DB, CurrentUser, PatientAccess
from app.api.responses import PATIENT_SCOPED, R409, R422
from app.errors import PermissionDenied
from app.models import DailyActivity, Device, Patient
from app.models.enums import AuditAction, UserRole
from app.repositories import ActivityRepository, AuditRepository, DeviceRepository
from app.schemas.monitoring import ActivitySummary, DailyActivityOut, DailyActivityUpsert, DeviceCreate, DeviceOut

router = APIRouter(tags=["Activity"])
devices_router = APIRouter(tags=["Devices"])
Readable = Annotated[Patient, Depends(PatientAccess(entity="daily_activity"))]
Writable = Annotated[Patient, Depends(PatientAccess(entity="daily_activity", action=AuditAction.update))]
Day = Annotated[date, Path(description="Calendar date in the patient's time zone", examples=["2026-10-21"])]


@router.get("/patients/{patient_id}/daily-activity", response_model=list[DailyActivityOut],
            summary="Daily activity history", responses={**PATIENT_SCOPED, **R422},
            description="**Roles:** patient (self), clinician and physician (care team). Inclusive date range, "
                        "oldest first. Defaults to the last 30 days.")
def list_activity(db: DB, user: CurrentUser, patient: Readable,
                  start_date: Annotated[date | None, Query(examples=["2026-10-01"])] = None,
                  end_date: Annotated[date | None, Query(examples=["2026-10-31"])] = None) -> list:
    end_date = end_date or datetime.now(timezone.utc).date()
    start_date = start_date or end_date - timedelta(days=29)
    rows = ActivityRepository(db).list(patient.patient_id, start_date, end_date)
    AuditRepository(db).record(AuditAction.read, "daily_activity", actor=user, patient_id=patient.patient_id,
                               details={"rows": len(rows)})
    return rows


@router.get("/patients/{patient_id}/daily-activity/summary", response_model=ActivitySummary,
            summary="Activity totals and averages", responses={**PATIENT_SCOPED, **R422},
            description="**Roles:** patient (self), clinician and physician (care team). Defaults to the last 7 days.")
def activity_summary(db: DB, user: CurrentUser, patient: Readable,
                     start_date: date | None = None, end_date: date | None = None) -> dict:
    end_date = end_date or datetime.now(timezone.utc).date()
    start_date = start_date or end_date - timedelta(days=6)
    out = ActivityRepository(db).summary(patient.patient_id, start_date, end_date)
    AuditRepository(db).record(AuditAction.read, "daily_activity", actor=user, patient_id=patient.patient_id,
                               details={"summary": True})
    return out


@router.get("/patients/{patient_id}/daily-activity/{activity_date}", response_model=DailyActivityOut,
            summary="One day's activity", responses=PATIENT_SCOPED,
            description="**Roles:** patient (self), clinician and physician (care team).")
def get_activity(activity_date: Day, db: DB, user: CurrentUser, patient: Readable) -> DailyActivity:
    row = ActivityRepository(db).get(patient.patient_id, activity_date)
    AuditRepository(db).record(AuditAction.read, "daily_activity", actor=user, patient_id=patient.patient_id,
                               entity_id=activity_date)
    return row


@router.put("/patients/{patient_id}/daily-activity/{activity_date}", response_model=DailyActivityOut,
            summary="Create or replace a day's activity", responses={**PATIENT_SCOPED, **R422},
            description="**Roles:** patient (self, device app), clinician and physician (care team). Idempotent "
                        "upsert keyed by patient and date: returns 201 when created and 200 when replaced. "
                        "Fields omitted from the body are cleared.")
def put_activity(activity_date: Day, body: DailyActivityUpsert, db: DB, user: CurrentUser, patient: Writable,
                 response: Response) -> DailyActivity:
    row, created = ActivityRepository(db).upsert(patient.patient_id, activity_date, body.model_dump(exclude_none=True))
    if created:
        response.status_code = status.HTTP_201_CREATED
    AuditRepository(db).record(AuditAction.create if created else AuditAction.update, "daily_activity", actor=user,
                               patient_id=patient.patient_id, entity_id=activity_date)
    db.commit()                                   # the day is stored before trend rules run
    process_activity(db, row)
    return row


@router.delete("/patients/{patient_id}/daily-activity/{activity_date}", status_code=status.HTTP_204_NO_CONTENT,
               summary="Delete a day's activity", responses=PATIENT_SCOPED,
               description="**Roles:** clinician and physician (care team).")
def delete_activity(activity_date: Day, db: DB, user: CurrentUser,
                    patient: Annotated[Patient, Depends(PatientAccess(entity="daily_activity", allow_patient=False,
                                                                      action=AuditAction.delete))]) -> None:
    ActivityRepository(db).delete(patient.patient_id, activity_date)
    AuditRepository(db).record(AuditAction.delete, "daily_activity", actor=user, patient_id=patient.patient_id,
                               entity_id=activity_date)


@devices_router.get("/patients/{patient_id}/devices", response_model=list[DeviceOut],
                    summary="List a patient's devices", responses=PATIENT_SCOPED,
                    description="**Roles:** patient (self), clinician and physician (care team).")
def list_devices(db: DB, patient: Readable) -> list[Device]:
    return DeviceRepository(db).list_for_patient(patient.patient_id)


@devices_router.post("/patients/{patient_id}/devices", response_model=DeviceOut, status_code=status.HTTP_201_CREATED,
                     summary="Register and assign a device", responses={**PATIENT_SCOPED, **R409, **R422},
                     description="**Roles:** clinician and physician (care team).")
def register_device(body: DeviceCreate, db: DB, user: CurrentUser,
                    patient: Annotated[Patient, Depends(PatientAccess(entity="devices", allow_patient=False,
                                                                      action=AuditAction.create))]) -> Device:
    if user.role not in CARE_ROLES:
        raise PermissionDenied("only clinicians and physicians register devices")
    device = DeviceRepository(db).register(patient.patient_id, body.model_dump())
    AuditRepository(db).record(AuditAction.create, "devices", actor=user, entity_id=device.device_id,
                               patient_id=patient.patient_id)
    return device


_ = UserRole  # re-exported for type checkers
