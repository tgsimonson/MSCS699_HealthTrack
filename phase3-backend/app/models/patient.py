"""patients and care team assignments"""
from __future__ import annotations

import re
import uuid
from datetime import date, datetime

from sqlalchemy import (CheckConstraint, Date, ForeignKey, Index, SmallInteger, String, Uuid, event, text)
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.models.base import Base, TimestampMixin, UTCDateTime, new_uuid
from app.models.enums import (CareTeamRole, ClinicalRisk, ProgramStatus, QualifyingEvent, SexAtBirth, sa_enum)

MRN_RE = re.compile(r"^[A-Z0-9-]{6,20}$")
PHONE_RE = re.compile(r"^\+[1-9][0-9]{7,14}$")
POSTAL_RE = re.compile(r"^[0-9]{5}(-[0-9]{4})?$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")


class Patient(TimestampMixin, Base):
    __tablename__ = "patients"
    __table_args__ = (
        # portable cross-column rules (sqlite and postgres); age and format rules live in validate_domain()
        CheckConstraint("qualifying_event_date <= referral_date", name="event_before_referral"),
        CheckConstraint("enrollment_date IS NULL OR enrollment_date >= referral_date", name="enroll_after_referral"),
        CheckConstraint("program_status IN ('referred', 'withdrawn') OR enrollment_date IS NOT NULL",
                        name="enrolled_status_has_date"),
        CheckConstraint("(program_status = 'graduated') = (graduation_date IS NOT NULL)", name="graduation_date_matches"),
        CheckConstraint("graduation_date IS NULL OR graduation_date >= enrollment_date", name="graduate_after_enroll"),
        CheckConstraint("program_status <> 'active' OR clinical_risk_category IN ('low', 'moderate')",
                        name="home_program_risk"),
        CheckConstraint("target_sessions BETWEEN 1 AND 72", name="target_sessions_range"),
        CheckConstraint("length(trim(first_name)) > 0 AND length(trim(last_name)) > 0", name="names_present"),
        CheckConstraint("date_of_birth > '1900-01-01'", name="dob_after_1900"),
        Index("ix_patients_status_active", "program_status", postgresql_where=text("deleted_at IS NULL"),
              sqlite_where=text("deleted_at IS NULL")),
        Index("ix_patients_name", "last_name", "first_name"),
    )

    patient_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.user_id", ondelete="SET NULL"), unique=True)
    mrn: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    first_name: Mapped[str] = mapped_column(String(80), nullable=False)
    last_name: Mapped[str] = mapped_column(String(80), nullable=False)
    date_of_birth: Mapped[date] = mapped_column(Date, nullable=False)
    sex: Mapped[SexAtBirth] = mapped_column(sa_enum(SexAtBirth, "sex_at_birth"), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(16))
    email: Mapped[str | None] = mapped_column(String(254))
    postal_code: Mapped[str | None] = mapped_column(String(10))
    timezone: Mapped[str] = mapped_column(String(40), default="America/Denver", nullable=False)
    qualifying_event: Mapped[QualifyingEvent] = mapped_column(sa_enum(QualifyingEvent, "qualifying_event"), nullable=False)
    qualifying_event_date: Mapped[date] = mapped_column(Date, nullable=False)
    referral_date: Mapped[date] = mapped_column(Date, nullable=False)
    enrollment_date: Mapped[date | None] = mapped_column(Date)
    graduation_date: Mapped[date | None] = mapped_column(Date)
    program_status: Mapped[ProgramStatus] = mapped_column(sa_enum(ProgramStatus, "program_status"),
                                                          default=ProgramStatus.referred, nullable=False)
    clinical_risk_category: Mapped[ClinicalRisk] = mapped_column(sa_enum(ClinicalRisk, "clinical_risk"), nullable=False)
    target_sessions: Mapped[int] = mapped_column(SmallInteger, default=36, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.user_id", ondelete="SET NULL"))
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    care_team: Mapped[list[CareTeamAssignment]] = relationship(back_populates="patient", cascade="all, delete-orphan")
    vitals: Mapped[list["VitalSign"]] = relationship(back_populates="patient", cascade="all, delete-orphan",  # noqa: F821
                                                     passive_deletes=True)
    activity: Mapped[list["DailyActivity"]] = relationship(back_populates="patient",  # noqa: F821
                                                           cascade="all, delete-orphan", passive_deletes=True)
    devices: Mapped[list["Device"]] = relationship(back_populates="patient")  # noqa: F821

    @validates("mrn")
    def _v_mrn(self, _key: str, value: str) -> str:
        if not MRN_RE.match(value or ""):
            raise ValueError("mrn must be 6 to 20 characters of A-Z, 0-9, or hyphen")
        return value

    @validates("phone")
    def _v_phone(self, _key: str, value: str | None) -> str | None:
        if value is not None and not PHONE_RE.match(value):
            raise ValueError("phone must be E.164, for example +17195550111")
        return value

    @validates("postal_code")
    def _v_postal(self, _key: str, value: str | None) -> str | None:
        if value is not None and not POSTAL_RE.match(value):
            raise ValueError("postal_code must be a 5-digit or ZIP+4 code")
        return value

    @validates("email")
    def _v_email(self, _key: str, value: str | None) -> str | None:
        if value is not None and not EMAIL_RE.match(value):
            raise ValueError("email is not a valid address")
        return value.lower() if value else value

    def validate_domain(self) -> None:
        """cross-field rules that cannot be written as portable CHECK constraints"""
        if self.date_of_birth and self.qualifying_event_date:
            dob, evt = self.date_of_birth, self.qualifying_event_date
            age = evt.year - dob.year - ((evt.month, evt.day) < (dob.month, dob.day))
            if age < 18:
                raise ValueError("patient must be at least 18 at the qualifying event")
        if self.qualifying_event_date and self.qualifying_event_date > date.today():
            raise ValueError("qualifying_event_date cannot be in the future")

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


@event.listens_for(Patient, "before_insert")
@event.listens_for(Patient, "before_update")
def _patient_domain_check(_mapper, _conn, target: Patient) -> None:  # noqa: ANN001
    target.validate_domain()


class CareTeamAssignment(Base):
    __tablename__ = "care_team_assignments"
    __table_args__ = (
        CheckConstraint("end_date IS NULL OR end_date >= start_date", name="dates_ordered"),
        # one current primary clinician and one current supervising physician per patient
        Index("uq_care_team_one_current_role", "patient_id", "team_role", unique=True,
              postgresql_where=text("end_date IS NULL AND team_role IN ('primary_clinician', 'supervising_physician')"),
              sqlite_where=text("end_date IS NULL AND team_role IN ('primary_clinician', 'supervising_physician')")),
        Index("ix_care_team_user_current", "user_id", "patient_id",
              postgresql_where=text("end_date IS NULL"), sqlite_where=text("end_date IS NULL")),
    )

    assignment_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.patient_id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.user_id"), nullable=False)
    team_role: Mapped[CareTeamRole] = mapped_column(sa_enum(CareTeamRole, "care_team_role"), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, default=date.today, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date)

    patient: Mapped[Patient] = relationship(back_populates="care_team")
    user: Mapped["User"] = relationship()  # noqa: F821
