"""patient and care team data access"""
from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session

from app.errors import NotFoundError, ValidationFailed
from app.logging_config import get_logger
from app.models import CareTeamAssignment, Patient, User
from app.models.base import utcnow
from app.models.enums import CareTeamRole, ProgramStatus, UserRole
from app.repositories.base import PageResult, db_errors, paginate

log = get_logger("dal.patients")

SORTS = {"last_name": (Patient.last_name, Patient.first_name), "-last_name": (Patient.last_name.desc(),),
         "enrollment_date": (Patient.enrollment_date,), "-enrollment_date": (Patient.enrollment_date.desc(),),
         "created_at": (Patient.created_at,), "-created_at": (Patient.created_at.desc(),)}


def current_assignment_clause(user_id: uuid.UUID):  # noqa: ANN201
    today = date.today()
    return exists().where(CareTeamAssignment.patient_id == Patient.patient_id,
                          CareTeamAssignment.user_id == user_id,
                          CareTeamAssignment.start_date <= today,
                          CareTeamAssignment.end_date.is_(None))


class PatientRepository:
    def __init__(self, session: Session) -> None:
        self.s = session

    # ---------------------------------------------------------------- create
    def create(self, data: dict[str, Any], *, primary_clinician_id: uuid.UUID, supervising_physician_id: uuid.UUID,
               created_by: uuid.UUID | None) -> Patient:
        """create a patient and the two required care team assignments in one unit of work"""
        self._require_role(primary_clinician_id, {UserRole.clinician, UserRole.physician}, "primary_clinician_id")
        self._require_role(supervising_physician_id, {UserRole.physician}, "supervising_physician_id")
        if data.get("user_id"):
            self._require_role(data["user_id"], {UserRole.patient}, "user_id")
        patient = Patient(**data, created_by=created_by)
        with db_errors(self.s, "patient", "create"):
            self.s.add(patient)
            self.s.flush()
            self.s.add_all([
                CareTeamAssignment(patient_id=patient.patient_id, user_id=primary_clinician_id,
                                   team_role=CareTeamRole.primary_clinician),
                CareTeamAssignment(patient_id=patient.patient_id, user_id=supervising_physician_id,
                                   team_role=CareTeamRole.supervising_physician),
            ])
        log.info("patient created", extra={"ctx": {"patient_id": str(patient.patient_id)}})
        return patient

    # ---------------------------------------------------------------- read
    def get(self, patient_id: uuid.UUID, *, include_deleted: bool = False) -> Patient:
        patient = self.s.get(Patient, patient_id)
        if patient is None or (patient.is_deleted and not include_deleted):
            raise NotFoundError("patient not found")
        return patient

    def get_by_user(self, user_id: uuid.UUID) -> Patient | None:
        return self.s.scalar(select(Patient).where(Patient.user_id == user_id, Patient.deleted_at.is_(None)))

    def list(self, *, visible_to: User | None = None, program_status: list[ProgramStatus] | None = None,
             clinician_id: uuid.UUID | None = None, sort: str = "last_name", page: int = 1,
             page_size: int = 50) -> PageResult[Patient]:
        """list patients, scoped to the caller's care team when visible_to is a clinician or physician"""
        stmt = select(Patient).where(Patient.deleted_at.is_(None))
        stmt = self._scope(stmt, visible_to)
        if program_status:
            stmt = stmt.where(Patient.program_status.in_(program_status))
        if clinician_id:
            stmt = stmt.where(exists().where(CareTeamAssignment.patient_id == Patient.patient_id,
                                             CareTeamAssignment.user_id == clinician_id,
                                             CareTeamAssignment.team_role == CareTeamRole.primary_clinician,
                                             CareTeamAssignment.end_date.is_(None)))
        stmt = stmt.order_by(*SORTS.get(sort, SORTS["last_name"]), Patient.patient_id)
        return paginate(self.s, stmt, page, page_size)

    def search(self, q: str, *, visible_to: User | None = None, program_status: list[ProgramStatus] | None = None,
               page: int = 1, page_size: int = 50) -> PageResult[Patient]:
        """case-insensitive match on first name, last name, or MRN"""
        like = f"%{q.strip().lower()}%"
        stmt = select(Patient).where(Patient.deleted_at.is_(None),
                                     or_(Patient.first_name.ilike(like), Patient.last_name.ilike(like),
                                         Patient.mrn.ilike(like)))
        stmt = self._scope(stmt, visible_to)
        if program_status:
            stmt = stmt.where(Patient.program_status.in_(program_status))
        return paginate(self.s, stmt.order_by(Patient.last_name, Patient.first_name, Patient.patient_id), page,
                        page_size)

    def care_team(self, patient_id: uuid.UUID, *, include_ended: bool = False) -> list[CareTeamAssignment]:
        stmt = select(CareTeamAssignment).where(CareTeamAssignment.patient_id == patient_id)
        if not include_ended:
            stmt = stmt.where(CareTeamAssignment.end_date.is_(None))
        return list(self.s.scalars(stmt.order_by(CareTeamAssignment.team_role)))

    def is_on_care_team(self, user_id: uuid.UUID, patient_id: uuid.UUID) -> bool:
        today = date.today()
        return bool(self.s.scalar(select(exists().where(
            CareTeamAssignment.patient_id == patient_id, CareTeamAssignment.user_id == user_id,
            CareTeamAssignment.start_date <= today, CareTeamAssignment.end_date.is_(None)))))

    # ---------------------------------------------------------------- update / delete
    def update(self, patient_id: uuid.UUID, changes: dict[str, Any]) -> tuple[Patient, list[str]]:
        """apply a partial update; returns the patient and the names of columns that changed"""
        patient = self.get(patient_id)
        changed = [k for k, v in changes.items() if getattr(patient, k) != v]
        with db_errors(self.s, "patient", "update"):
            for k in changed:
                setattr(patient, k, changes[k])
        if changed:
            log.info("patient updated", extra={"ctx": {"patient_id": str(patient_id), "columns": changed}})
        return patient, changed

    def soft_delete(self, patient_id: uuid.UUID) -> Patient:
        """withdraw and hide the patient; clinical history is retained"""
        patient = self.get(patient_id)
        with db_errors(self.s, "patient", "soft_delete"):
            if patient.program_status not in (ProgramStatus.graduated, ProgramStatus.withdrawn):
                patient.program_status = ProgramStatus.withdrawn
            patient.deleted_at = utcnow()
        log.info("patient soft-deleted", extra={"ctx": {"patient_id": str(patient_id)}})
        return patient

    def hard_delete(self, patient_id: uuid.UUID) -> None:
        """permanent removal with cascade; used for test data cleanup, never exposed by the api"""
        patient = self.get(patient_id, include_deleted=True)
        with db_errors(self.s, "patient", "hard_delete"):
            self.s.delete(patient)
        log.warning("patient hard-deleted", extra={"ctx": {"patient_id": str(patient_id)}})

    # ---------------------------------------------------------------- helpers
    def _scope(self, stmt, visible_to: User | None):  # noqa: ANN001, ANN202
        if visible_to is None or visible_to.role == UserRole.admin:
            return stmt
        if visible_to.role in (UserRole.clinician, UserRole.physician):
            return stmt.where(current_assignment_clause(visible_to.user_id))
        if visible_to.role == UserRole.patient:
            return stmt.where(Patient.user_id == visible_to.user_id)
        return stmt.where(False)  # it_admin and any future role see no patients

    def _require_role(self, user_id: uuid.UUID, roles: set[UserRole], field: str) -> None:
        user = self.s.get(User, user_id)
        if user is None or not user.is_active or user.role not in roles:
            allowed = " or ".join(sorted(r.value for r in roles))
            raise ValidationFailed(f"{field} must reference an active {allowed} account",
                                   errors=[{"field": field, "message": f"must be an active {allowed}",
                                            "code": "invalid_reference"}])
