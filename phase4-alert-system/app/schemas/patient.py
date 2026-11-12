"""patient request and response schemas"""
from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import EmailStr, Field, model_validator

from app.models.enums import CareTeamRole, ClinicalRisk, ProgramStatus, QualifyingEvent, SexAtBirth
from app.schemas.common import ApiModel

MRN = Field(pattern=r"^[A-Z0-9-]{6,20}$", examples=["HT-100005"])
PHONE = Field(default=None, pattern=r"^\+[1-9][0-9]{7,14}$", examples=["+17195550115"])
POSTAL = Field(default=None, pattern=r"^[0-9]{5}(-[0-9]{4})?$", examples=["80921"])
NAME = Field(min_length=1, max_length=80)


def _check_dates(m) -> None:  # noqa: ANN001
    evt, ref = getattr(m, "qualifying_event_date", None), getattr(m, "referral_date", None)
    enr, grad = getattr(m, "enrollment_date", None), getattr(m, "graduation_date", None)
    if evt and ref and evt > ref:
        raise ValueError("qualifying_event_date must be on or before referral_date")
    if ref and enr and enr < ref:
        raise ValueError("enrollment_date must be on or after referral_date")
    if enr and grad and grad < enr:
        raise ValueError("graduation_date must be on or after enrollment_date")


class PatientCreate(ApiModel):
    mrn: str = MRN
    first_name: str = NAME
    last_name: str = NAME
    date_of_birth: date
    sex: SexAtBirth
    phone: str | None = PHONE
    email: EmailStr | None = None
    postal_code: str | None = POSTAL
    timezone: str = Field(default="America/Denver", max_length=40)
    qualifying_event: QualifyingEvent
    qualifying_event_date: date
    referral_date: date
    enrollment_date: date | None = None
    program_status: ProgramStatus = ProgramStatus.referred
    clinical_risk_category: ClinicalRisk
    target_sessions: int = Field(default=36, ge=1, le=72)
    user_id: uuid.UUID | None = Field(default=None, description="Existing patient login to link, if any.")
    primary_clinician_id: uuid.UUID = Field(description="Becomes the primary_clinician care team member.")
    supervising_physician_id: uuid.UUID = Field(description="Must be an active physician.")

    model_config = {"json_schema_extra": {"examples": [{
        "mrn": "HT-100009", "first_name": "Grace", "last_name": "Morales", "date_of_birth": "1963-02-11",
        "sex": "female", "phone": "+17195550119", "postal_code": "80915", "timezone": "America/Denver",
        "qualifying_event": "pci", "qualifying_event_date": "2026-10-19", "referral_date": "2026-10-27",
        "program_status": "referred", "clinical_risk_category": "low", "target_sessions": 36,
        "primary_clinician_id": "00000000-0000-4000-a000-000000000001",
        "supervising_physician_id": "00000000-0000-4000-a000-000000000003"}]}}

    @model_validator(mode="after")
    def _rules(self) -> PatientCreate:
        _check_dates(self)
        if self.program_status in (ProgramStatus.active, ProgramStatus.paused) and not self.enrollment_date:
            raise ValueError("active or paused patients need an enrollment_date")
        if self.program_status == ProgramStatus.graduated:
            raise ValueError("create the patient first, then graduate them with PATCH")
        if self.program_status == ProgramStatus.active and self.clinical_risk_category == ClinicalRisk.high:
            raise ValueError("home-based rehab is limited to low and moderate risk patients")
        return self


class PatientUpdate(ApiModel):
    """partial update; omitted fields stay unchanged"""

    first_name: str | None = Field(default=None, min_length=1, max_length=80)
    last_name: str | None = Field(default=None, min_length=1, max_length=80)
    phone: str | None = PHONE
    email: EmailStr | None = None
    postal_code: str | None = POSTAL
    timezone: str | None = Field(default=None, max_length=40)
    enrollment_date: date | None = None
    graduation_date: date | None = None
    program_status: ProgramStatus | None = None
    clinical_risk_category: ClinicalRisk | None = None
    target_sessions: int | None = Field(default=None, ge=1, le=72)

    model_config = {"json_schema_extra": {"examples": [{"program_status": "paused"}]}}

    @model_validator(mode="after")
    def _rules(self) -> PatientUpdate:
        _check_dates(self)
        return self


PATIENT_SELF_EDITABLE = {"phone", "email", "postal_code"}


class PatientOut(ApiModel):
    patient_id: uuid.UUID
    mrn: str
    user_id: uuid.UUID | None
    first_name: str
    last_name: str
    date_of_birth: date
    sex: SexAtBirth
    phone: str | None
    email: str | None
    postal_code: str | None
    timezone: str
    qualifying_event: QualifyingEvent
    qualifying_event_date: date
    referral_date: date
    enrollment_date: date | None
    graduation_date: date | None
    program_status: ProgramStatus
    clinical_risk_category: ClinicalRisk
    target_sessions: int
    created_at: datetime
    updated_at: datetime

    model_config = {"json_schema_extra": {"examples": [{
        "patient_id": "00000000-0000-4000-b000-000000000005", "mrn": "HT-100005",
        "user_id": "00000000-0000-4000-a000-000000000015", "first_name": "Thomas", "last_name": "Reed",
        "date_of_birth": "1959-01-30", "sex": "male", "phone": "+17195550115", "email": "t.reed@mail.example",
        "postal_code": "80921", "timezone": "America/Denver", "qualifying_event": "valve_surgery",
        "qualifying_event_date": "2026-08-31", "referral_date": "2026-09-21", "enrollment_date": "2026-10-01",
        "graduation_date": None, "program_status": "active", "clinical_risk_category": "moderate",
        "target_sessions": 36, "created_at": "2026-09-21T20:10:00Z", "updated_at": "2026-10-01T18:00:00Z"}]}}


class PatientSummary(ApiModel):
    patient_id: uuid.UUID
    mrn: str
    first_name: str
    last_name: str
    program_status: ProgramStatus
    clinical_risk_category: ClinicalRisk
    enrollment_date: date | None


class PatientSearch(ApiModel):
    q: str = Field(min_length=2, max_length=80, description="Name or MRN fragment.", examples=["reed"])
    program_status: list[ProgramStatus] | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=200)


class CareTeamMemberOut(ApiModel):
    assignment_id: uuid.UUID
    user_id: uuid.UUID
    team_role: CareTeamRole
    start_date: date
    end_date: date | None
