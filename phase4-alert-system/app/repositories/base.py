"""shared data access helpers: pagination, integrity error translation, logging"""
from __future__ import annotations

import math
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Generic, TypeVar

from sqlalchemy import Select, func, select
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.errors import ConflictError, DataAccessError, ValidationFailed
from app.logging_config import get_logger

T = TypeVar("T")
log = get_logger("dal")

# readable messages for constraint violations, keyed by constraint name
CONSTRAINT_MESSAGES: dict[str, tuple[type, str]] = {
    "uq_patients_mrn": (ConflictError, "a patient with this MRN already exists"),
    "uq_patients_user_id": (ConflictError, "this login is already linked to another patient"),
    "uq_users_email": (ConflictError, "an account with this email already exists"),
    "uq_vital_signs_patient_id_idempotency_key": (ConflictError, "a reading with this idempotency_key already exists"),
    "uq_care_team_one_current_role": (ConflictError, "the patient already has a current member in this care team role"),
    "uq_devices_manufacturer_serial_number": (ConflictError, "a device with this manufacturer and serial number exists"),
    "ck_patients_event_before_referral": (ValidationFailed, "qualifying_event_date must be on or before referral_date"),
    "ck_patients_enroll_after_referral": (ValidationFailed, "enrollment_date must be on or after referral_date"),
    "ck_patients_enrolled_status_has_date": (ValidationFailed, "this program_status requires an enrollment_date"),
    "ck_patients_graduation_date_matches": (ValidationFailed,
                                            "graduated status and graduation_date must be set together"),
    "ck_patients_graduate_after_enroll": (ValidationFailed, "graduation_date must be on or after enrollment_date"),
    "ck_patients_home_program_risk": (ValidationFailed, "active home-program patients must be low or moderate risk"),
    "ck_vital_signs_bp_order": (ValidationFailed, "systolic_bp must be greater than diastolic_bp"),
    "ck_vital_signs_bp_pair": (ValidationFailed, "systolic_bp and diastolic_bp must be sent together"),
    "ck_vital_signs_manual_has_author": (ValidationFailed, "manual readings must record who entered them"),
    "ck_daily_activity_minutes_fit_in_day": (ValidationFailed, "active plus sedentary minutes cannot exceed 1440"),
    "ck_devices_active_has_patient": (ValidationFailed, "an active device must be assigned to a patient"),
}

_SQLITE_CHECK = re.compile(r"CHECK constraint failed: (\w+)")
_SQLITE_UNIQUE = re.compile(r"UNIQUE constraint failed: ([\w., ]+)")
_UNIQUE_COLUMNS = {
    "patients.mrn": "uq_patients_mrn", "patients.user_id": "uq_patients_user_id", "users.email": "uq_users_email",
    "vital_signs.patient_id, vital_signs.idempotency_key": "uq_vital_signs_patient_id_idempotency_key",
    "care_team_assignments.patient_id, care_team_assignments.team_role": "uq_care_team_one_current_role",
    "devices.manufacturer, devices.serial_number": "uq_devices_manufacturer_serial_number",
}


def constraint_name(exc: IntegrityError) -> str | None:
    orig = exc.orig
    diag = getattr(orig, "diag", None)                  # psycopg exposes the name directly
    if diag is not None and getattr(diag, "constraint_name", None):
        return diag.constraint_name
    msg = str(orig)
    if m := _SQLITE_CHECK.search(msg):
        return m.group(1)
    if m := _SQLITE_UNIQUE.search(msg):
        return _UNIQUE_COLUMNS.get(m.group(1).strip())
    if "FOREIGN KEY" in msg.upper():
        return "foreign_key"
    return None


def translate_integrity_error(exc: IntegrityError, entity: str) -> Exception:
    name = constraint_name(exc)
    if name in CONSTRAINT_MESSAGES:
        cls, message = CONSTRAINT_MESSAGES[name]
        return cls(message, constraint=name)
    if name == "foreign_key" or (name or "").startswith("fk_"):
        return ValidationFailed(f"{entity} references a record that does not exist", constraint=name)
    if (name or "").startswith("uq_"):
        return ConflictError(f"{entity} conflicts with an existing record", constraint=name)
    return ValidationFailed(f"{entity} violates a data rule" + (f" ({name})" if name else ""), constraint=name)


@contextmanager
def db_errors(session: Session, entity: str, operation: str) -> Iterator[None]:
    """flush inside a savepoint and convert database errors into domain errors, logging each failure"""
    try:
        with session.begin_nested():
            yield
            session.flush()
    except IntegrityError as exc:
        err = translate_integrity_error(exc, entity)
        log.warning("integrity violation", extra={"ctx": {"entity": entity, "op": operation,
                                                         "constraint": getattr(err, "extra", {}).get("constraint")}})
        raise err from exc
    except ValueError as exc:                      # model-level validators (@validates, validate_domain)
        log.warning("model validation failed", extra={"ctx": {"entity": entity, "op": operation, "error": str(exc)}})
        raise ValidationFailed(str(exc)) from exc
    except OperationalError as exc:
        log.error("database unavailable", extra={"ctx": {"entity": entity, "op": operation}}, exc_info=True)
        raise DataAccessError("the database is temporarily unavailable") from exc
    except DBAPIError as exc:
        log.error("database error", extra={"ctx": {"entity": entity, "op": operation}}, exc_info=True)
        raise DataAccessError("unexpected database error") from exc


@dataclass
class PageResult(Generic[T]):
    items: list[T]
    page: int
    page_size: int
    total_items: int

    @property
    def total_pages(self) -> int:
        return math.ceil(self.total_items / self.page_size) if self.page_size else 0

    def meta(self) -> dict[str, int]:
        return {"page": self.page, "page_size": self.page_size, "total_items": self.total_items,
                "total_pages": self.total_pages}


def paginate(session: Session, stmt: Select, page: int, page_size: int) -> PageResult:
    """count with the same filters, then fetch one page with LIMIT/OFFSET"""
    total = session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = list(session.scalars(stmt.limit(page_size).offset((page - 1) * page_size)))
    return PageResult(rows, page, page_size, total)
