"""enumerated types shared by models, schemas, and migrations (values match the phase 2 schema)"""
from __future__ import annotations

import enum

from sqlalchemy import Enum as SAEnum


class UserRole(str, enum.Enum):
    patient = "patient"
    clinician = "clinician"
    physician = "physician"
    admin = "admin"
    it_admin = "it_admin"


class SexAtBirth(str, enum.Enum):
    female = "female"
    male = "male"
    intersex = "intersex"
    unknown = "unknown"


class QualifyingEvent(str, enum.Enum):
    myocardial_infarction = "myocardial_infarction"
    pci = "pci"
    cabg = "cabg"
    valve_surgery = "valve_surgery"
    stable_angina = "stable_angina"
    heart_failure_reduced_ef = "heart_failure_reduced_ef"
    heart_transplant = "heart_transplant"


class ProgramStatus(str, enum.Enum):
    referred = "referred"
    active = "active"
    paused = "paused"
    graduated = "graduated"
    withdrawn = "withdrawn"


class ClinicalRisk(str, enum.Enum):
    low = "low"
    moderate = "moderate"
    high = "high"


class CareTeamRole(str, enum.Enum):
    primary_clinician = "primary_clinician"
    supervising_physician = "supervising_physician"
    covering_clinician = "covering_clinician"


class ReadingContext(str, enum.Enum):
    rest = "rest"
    warmup = "warmup"
    exercise = "exercise"
    cooldown = "cooldown"
    recovery = "recovery"


class ReadingSource(str, enum.Enum):
    device = "device"
    manual = "manual"


class DataQuality(str, enum.Enum):
    valid = "valid"
    suspect = "suspect"
    artifact = "artifact"


class DeviceType(str, enum.Enum):
    heart_rate_band = "heart_rate_band"
    blood_pressure_cuff = "blood_pressure_cuff"
    pulse_oximeter = "pulse_oximeter"
    activity_tracker = "activity_tracker"


class DeviceStatus(str, enum.Enum):
    active = "active"
    inactive = "inactive"
    lost = "lost"
    retired = "retired"


class AuditAction(str, enum.Enum):
    create = "create"
    read = "read"
    update = "update"
    delete = "delete"
    login = "login"
    login_failed = "login_failed"
    logout = "logout"
    export = "export"


def sa_enum(py_enum: type[enum.Enum], name: str) -> SAEnum:
    """native enum on postgres, varchar + check constraint on sqlite"""
    return SAEnum(py_enum, name=name, values_callable=lambda e: [m.value for m in e],
                  create_constraint=True, validate_strings=True)
