"""patient crud, search, and care team listing"""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import DB, CurrentUser, PatientAccess, require_roles
from app.api.responses import AUTHED, PATIENT_SCOPED, R409, R422
from app.config import get_settings
from app.errors import PermissionDenied
from app.models import Patient, User
from app.models.enums import AuditAction, ProgramStatus, UserRole
from app.repositories import AuditRepository, PatientRepository
from app.schemas.common import Page
from app.schemas.patient import (PATIENT_SELF_EDITABLE, CareTeamMemberOut, PatientCreate, PatientOut, PatientSearch,
                                 PatientSummary, PatientUpdate)

router = APIRouter(prefix="/patients", tags=["Patients"])
MAX = get_settings().max_page_size

StaffLister = Annotated[User, Depends(require_roles(UserRole.clinician, UserRole.physician, UserRole.admin))]


@router.get("", response_model=Page[PatientSummary], summary="List patients in scope", responses=AUTHED,
            description="**Roles:** clinician and physician (their current care team), admin (all, demographics "
                        "only). Patients use `GET /patients/{patient_id}` for their own record.")
def list_patients(db: DB, user: StaffLister,
                  program_status: Annotated[list[ProgramStatus] | None, Query()] = None,
                  clinician_id: Annotated[uuid.UUID | None, Query(description="Primary clinician user id")] = None,
                  sort: Annotated[str, Query(pattern="^-?(last_name|enrollment_date|created_at)$")] = "last_name",
                  page: Annotated[int, Query(ge=1)] = 1,
                  page_size: Annotated[int, Query(ge=1, le=MAX)] = 50) -> dict:
    res = PatientRepository(db).list(visible_to=user, program_status=program_status, clinician_id=clinician_id, sort=sort,
                                     page=page, page_size=page_size)
    AuditRepository(db).record(AuditAction.read, "patients", actor=user, details={"list": True, "rows": len(res.items)})
    return {"items": res.items, "meta": res.meta()}


@router.post("", response_model=PatientOut, status_code=status.HTTP_201_CREATED, summary="Register a patient",
             responses={**AUTHED, **R409, **R422},
             description="**Roles:** admin, clinician, physician. Creates the patient plus the primary clinician "
                         "and supervising physician care team assignments in one transaction.")
def create_patient(body: PatientCreate, db: DB, response: Response,
                   user: Annotated[User, Depends(require_roles(UserRole.admin, UserRole.clinician,
                                                               UserRole.physician))]) -> Patient:
    data = body.model_dump(exclude={"primary_clinician_id", "supervising_physician_id"}, exclude_none=True)
    patient = PatientRepository(db).create(data, primary_clinician_id=body.primary_clinician_id,
                                           supervising_physician_id=body.supervising_physician_id,
                                           created_by=user.user_id)
    AuditRepository(db).record(AuditAction.create, "patients", actor=user, entity_id=patient.patient_id,
                               patient_id=patient.patient_id)
    response.headers["Location"] = f"/api/v1/patients/{patient.patient_id}"
    return patient


@router.post("/search", response_model=Page[PatientSummary], summary="Search patients by name or MRN",
             responses={**AUTHED, **R422},
             description="**Roles:** clinician, physician, admin. Terms travel in the body so names never appear "
                         "in URLs or access logs. Results are scoped like `GET /patients`.")
def search_patients(body: PatientSearch, db: DB, user: StaffLister) -> dict:
    res = PatientRepository(db).search(body.q, visible_to=user, program_status=body.program_status, page=body.page,
                                       page_size=body.page_size)
    AuditRepository(db).record(AuditAction.read, "patients", actor=user, details={"search": True,
                                                                                  "rows": len(res.items)})
    return {"items": res.items, "meta": res.meta()}


@router.get("/{patient_id}", response_model=PatientOut, summary="Get a patient", responses=PATIENT_SCOPED,
            description="**Roles:** patient (self), clinician and physician (care team), admin.")
def get_patient(db: DB, patient: Annotated[Patient, Depends(PatientAccess(allow_admin=True))],
                user: CurrentUser) -> Patient:
    AuditRepository(db).record(AuditAction.read, "patients", actor=user, entity_id=patient.patient_id,
                               patient_id=patient.patient_id)
    return patient


@router.patch("/{patient_id}", response_model=PatientOut, summary="Update a patient",
              responses={**PATIENT_SCOPED, **R409, **R422},
              description="**Roles:** clinician and physician (care team), admin; patients may change only "
                          "`phone`, `email`, and `postal_code` on their own record. The audit log stores the names "
                          "of changed columns, never their values.")
def update_patient(body: PatientUpdate, db: DB,
                   patient: Annotated[Patient, Depends(PatientAccess(allow_admin=True, action=AuditAction.update))],
                   user: CurrentUser) -> Patient:
    changes = body.model_dump(exclude_unset=True)
    if user.role == UserRole.patient and set(changes) - PATIENT_SELF_EDITABLE:
        raise PermissionDenied("patients may update only phone, email, and postal_code")
    patient, changed = PatientRepository(db).update(patient.patient_id, changes)
    AuditRepository(db).record(AuditAction.update, "patients", actor=user, entity_id=patient.patient_id,
                               patient_id=patient.patient_id, details={"changed_columns": changed})
    return patient


@router.delete("/{patient_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Withdraw and soft-delete a patient",
               responses=PATIENT_SCOPED,
               description="**Roles:** admin. Sets `program_status` to withdrawn and hides the record. Clinical "
                           "history is retained for the medical record.")
def delete_patient(db: DB,
                   patient: Annotated[Patient, Depends(PatientAccess(allow_admin=True, allow_patient=False,
                                                                     care_roles=set(), action=AuditAction.delete))],
                   user: Annotated[User, Depends(require_roles(UserRole.admin))]) -> None:
    PatientRepository(db).soft_delete(patient.patient_id)
    AuditRepository(db).record(AuditAction.delete, "patients", actor=user, entity_id=patient.patient_id,
                               patient_id=patient.patient_id)


@router.get("/{patient_id}/care-team", response_model=list[CareTeamMemberOut], summary="Current care team",
            responses=PATIENT_SCOPED, description="**Roles:** patient (self), clinician and physician (care team), admin.")
def care_team(db: DB, patient: Annotated[Patient, Depends(PatientAccess(allow_admin=True))],
              include_ended: bool = False) -> list:
    return PatientRepository(db).care_team(patient.patient_id, include_ended=include_ended)
