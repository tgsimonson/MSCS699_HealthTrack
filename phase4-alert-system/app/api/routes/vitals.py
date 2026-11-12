"""vital sign collection and queries"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response, status

from app.alerts.service import process_new_readings
from app.api.deps import CARE_ROLES, DB, CurrentUser, PatientAccess
from app.api.responses import PATIENT_SCOPED, R409, R422
from app.config import get_settings
from app.errors import NotFoundError, PermissionDenied
from app.models import Patient, VitalSign
from app.models.enums import AuditAction, DataQuality, ReadingContext, ReadingSource, UserRole
from app.repositories import AuditRepository, PatientRepository, VitalSignRepository
from app.schemas.common import Page
from app.schemas.monitoring import (DailyVitalSummary, LatestVitals, VitalBatchCreate, VitalBatchResult,
                                    VitalSignCreate, VitalSignOut, VitalSignUpdate)

router = APIRouter(tags=["Vital Signs"])
MAX = get_settings().max_page_size
Readable = Annotated[Patient, Depends(PatientAccess(entity="vital_signs"))]
Writable = Annotated[Patient, Depends(PatientAccess(entity="vital_signs", action=AuditAction.create))]


@router.get("/patients/{patient_id}/vitals", response_model=Page[VitalSignOut], summary="Query readings",
            responses={**PATIENT_SCOPED, **R422},
            description="**Roles:** patient (self), clinician and physician (care team). Defaults to the last 24 "
                        "hours, newest first. `start` is inclusive, `end` exclusive, and the range may not exceed "
                        "92 days. Suspect and artifact readings are included and labeled.")
def list_vitals(db: DB, user: CurrentUser, patient: Readable,
                start: Annotated[datetime | None, Query(examples=["2026-10-19T00:00:00-06:00"])] = None,
                end: Annotated[datetime | None, Query(examples=["2026-10-26T00:00:00-06:00"])] = None,
                context: Annotated[list[ReadingContext] | None, Query()] = None,
                metric: Annotated[Literal["heart_rate", "blood_pressure", "spo2"] | None, Query()] = None,
                quality: DataQuality | None = None,
                order: Annotated[Literal["newest", "oldest"], Query()] = "newest",
                page: Annotated[int, Query(ge=1)] = 1,
                page_size: Annotated[int, Query(ge=1, le=MAX)] = 50) -> dict:
    if start is None and end is None:
        end = datetime.now(timezone.utc)
        start = end - timedelta(hours=24)
    res = VitalSignRepository(db).list(patient.patient_id, start=_aware(start), end=_aware(end), context=context,
                                       metric=metric, quality=quality, newest_first=order == "newest", page=page,
                                       page_size=page_size)
    AuditRepository(db).record(AuditAction.read, "vital_signs", actor=user, patient_id=patient.patient_id,
                               details={"rows": len(res.items)})
    return {"items": res.items, "meta": res.meta()}


@router.post("/patients/{patient_id}/vitals", response_model=VitalSignOut, status_code=status.HTTP_201_CREATED,
             summary="Record one reading", responses={**PATIENT_SCOPED, **R409, **R422},
             description="**Roles:** patient (self, device app), clinician and physician (care team, manual entry). "
                         "Values outside hard limits return 422. Possible-but-unlikely values (for example heart "
                         "rate above 220) are stored with `quality: suspect`. Device readings must reference an "
                         "active device assigned to the patient. A repeated `idempotency_key` returns 409.")
def create_vital(body: VitalSignCreate, db: DB, user: CurrentUser, patient: Writable, response: Response) -> VitalSign:
    data = body.model_dump(exclude_none=True)
    if user.role == UserRole.patient and data.get("source") == ReadingSource.manual:
        raise PermissionDenied("manual entry is for clinicians; the patient app sends device readings")
    vital = VitalSignRepository(db).create(patient.patient_id, data, entered_by=user.user_id)
    AuditRepository(db).record(AuditAction.create, "vital_signs", actor=user, entity_id=vital.vital_id,
                               patient_id=patient.patient_id)
    db.commit()                                   # the reading is durable before alert rules run
    process_new_readings(db, patient.patient_id, [vital.vital_id])
    response.headers["Location"] = f"/api/v1/vitals/{vital.vital_id}"
    return vital


@router.post("/patients/{patient_id}/vitals/batch", response_model=VitalBatchResult, summary="Upload a device batch",
             responses={**PATIENT_SCOPED, **R422},
             description="**Roles:** patient (self, device app), clinician and physician (care team). Up to 500 "
                         "device readings in one request, stored with a single INSERT. Readings whose "
                         "`idempotency_key` already exists are counted as duplicates rather than failing the batch, "
                         "so a retry after a dropped connection is always safe. Stored readings are checked against "
                         "the alert rules; `alerts_raised` counts new alerts.")
def create_vital_batch(body: VitalBatchCreate, db: DB, user: CurrentUser, patient: Writable) -> dict:
    readings = [r.model_dump(exclude_none=True) for r in body.readings]
    result = VitalSignRepository(db).bulk_create(patient.patient_id, readings)
    AuditRepository(db).record(AuditAction.create, "vital_signs", actor=user, patient_id=patient.patient_id,
                               details={"batch": True, "accepted": result["accepted"],
                                        "duplicates": result["duplicates"], "rejected": len(result["rejected"])})
    db.commit()
    outcomes = process_new_readings(db, patient.patient_id, result.pop("vital_ids"))
    result["alerts_raised"] = sum(1 for o in outcomes if o.action == "created")
    return result


@router.get("/patients/{patient_id}/vitals/latest", response_model=LatestVitals,
            summary="Latest valid reading of each measurement", responses=PATIENT_SCOPED,
            description="**Roles:** patient (self), clinician and physician (care team).")
def latest_vitals(db: DB, user: CurrentUser, patient: Readable) -> dict:
    out = VitalSignRepository(db).latest(patient.patient_id)
    AuditRepository(db).record(AuditAction.read, "vital_signs", actor=user, patient_id=patient.patient_id,
                               details={"latest": True})
    return {"heart_rate": out["heart_rate"], "blood_pressure": out["blood_pressure"], "spo2": out["spo2"]}


@router.get("/patients/{patient_id}/vitals/daily-summary", response_model=list[DailyVitalSummary],
            summary="Daily vital summary", responses={**PATIENT_SCOPED, **R422},
            description="**Roles:** patient (self), clinician and physician (care team). One row per UTC day with "
                        "min, max, and average of valid readings; `flagged_readings` counts suspect and artifact "
                        "readings. Defaults to the last 7 days.")
def daily_summary(db: DB, user: CurrentUser, patient: Readable,
                  start_date: Annotated[date | None, Query(examples=["2026-10-05"])] = None,
                  end_date: Annotated[date | None, Query(examples=["2026-10-25"])] = None,
                  context: ReadingContext | None = None) -> list:
    end_date = end_date or datetime.now(timezone.utc).date()
    start_date = start_date or end_date - timedelta(days=6)
    rows = VitalSignRepository(db).daily_summary(patient.patient_id, start_date, end_date, context)
    AuditRepository(db).record(AuditAction.read, "vital_signs", actor=user, patient_id=patient.patient_id,
                               details={"summary_days": len(rows)})
    return rows


def _vital_in_scope(db, user, vital_id: int, *, care_only: bool) -> VitalSign:  # noqa: ANN001
    vital = VitalSignRepository(db).get(vital_id)
    repo = PatientRepository(db)
    ok = ((user.role in CARE_ROLES and repo.is_on_care_team(user.user_id, vital.patient_id))
          or (not care_only and user.role == UserRole.patient and repo.get(vital.patient_id).user_id == user.user_id))
    if not ok:
        if user.role not in CARE_ROLES and user.role != UserRole.patient:
            raise PermissionDenied(f"role {user.role.value} cannot access vital signs")
        raise NotFoundError("vital sign not found")
    return vital


@router.get("/vitals/{vital_id}", response_model=VitalSignOut, summary="Get one reading", responses=PATIENT_SCOPED,
            description="**Roles:** patient (own readings), clinician and physician (care team).")
def get_vital(vital_id: int, db: DB, user: CurrentUser) -> VitalSign:
    vital = _vital_in_scope(db, user, vital_id, care_only=False)
    AuditRepository(db).record(AuditAction.read, "vital_signs", actor=user, entity_id=vital_id,
                               patient_id=vital.patient_id)
    return vital


@router.patch("/vitals/{vital_id}", response_model=VitalSignOut, summary="Correct context or mark an artifact",
              responses={**PATIENT_SCOPED, **R422},
              description="**Roles:** clinician and physician (care team). Only `context` and `quality` can change; "
                          "measured values are immutable.")
def update_vital(vital_id: int, body: VitalSignUpdate, db: DB, user: CurrentUser) -> VitalSign:
    _vital_in_scope(db, user, vital_id, care_only=True)
    vital, changed = VitalSignRepository(db).update(vital_id, body.model_dump(exclude_unset=True))
    AuditRepository(db).record(AuditAction.update, "vital_signs", actor=user, entity_id=vital_id,
                               patient_id=vital.patient_id, details={"changed_columns": changed})
    return vital


@router.delete("/vitals/{vital_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a reading entered in error",
               responses=PATIENT_SCOPED,
               description="**Roles:** clinician and physician (care team). Intended for manual entries made in "
                           "error; device artifacts should be marked `quality: artifact` instead so history is kept.")
def delete_vital(vital_id: int, db: DB, user: CurrentUser) -> None:
    vital = _vital_in_scope(db, user, vital_id, care_only=True)
    pid = vital.patient_id
    VitalSignRepository(db).delete(vital_id)
    AuditRepository(db).record(AuditAction.delete, "vital_signs", actor=user, entity_id=vital_id, patient_id=pid)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
