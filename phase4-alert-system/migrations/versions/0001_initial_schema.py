"""initial schema: users, auth sessions, patients, care team, vital signs, daily activity, audit log

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-02
"""
import sqlalchemy as sa
from alembic import op

from app.models.enums import (AuditAction, CareTeamRole, ClinicalRisk, DataQuality, ProgramStatus, QualifyingEvent,
                              ReadingContext, ReadingSource, SexAtBirth, UserRole)
from migrations.helpers import create_enum_types, drop_enum_types, enum_col, ts

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

ENUMS = [(UserRole, "user_role"), (SexAtBirth, "sex_at_birth"), (QualifyingEvent, "qualifying_event"),
         (ProgramStatus, "program_status"), (ClinicalRisk, "clinical_risk"), (CareTeamRole, "care_team_role"),
         (ReadingContext, "reading_context"), (ReadingSource, "reading_source"), (DataQuality, "data_quality"),
         (AuditAction, "audit_action")]


def _timestamps() -> list[sa.Column]:
    return [sa.Column("created_at", ts(), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", ts(), server_default=sa.func.now(), nullable=False)]


def upgrade() -> None:
    create_enum_types(*ENUMS)

    op.create_table(
        "users",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", enum_col(UserRole, "user_role"), nullable=False),
        sa.Column("first_name", sa.String(80), nullable=False),
        sa.Column("last_name", sa.String(80), nullable=False),
        sa.Column("credentials", sa.String(40)),
        sa.Column("phone", sa.String(16)),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("mfa_enabled", sa.Boolean(), nullable=False),
        sa.Column("mfa_secret", sa.String(64)),
        sa.Column("failed_login_attempts", sa.SmallInteger(), nullable=False),
        sa.Column("locked_until", ts()),
        sa.Column("last_login_at", ts()),
        sa.Column("password_changed_at", ts(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
        sa.CheckConstraint("email LIKE '%_@_%._%'", name=op.f("ck_users_email_format")),
        sa.CheckConstraint("length(trim(first_name)) > 0", name=op.f("ck_users_first_name_present")),
        sa.CheckConstraint("length(trim(last_name)) > 0", name=op.f("ck_users_last_name_present")),
        sa.CheckConstraint("failed_login_attempts BETWEEN 0 AND 100", name=op.f("ck_users_failed_logins_range")),
        sa.CheckConstraint("password_hash LIKE '$2%' OR password_hash LIKE '$argon2id$%'",
                           name=op.f("ck_users_password_hash_format")),
    )

    op.create_table(
        "auth_sessions",
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("refresh_token_hash", sa.String(64), nullable=False),
        sa.Column("issued_at", ts(), nullable=False),
        sa.Column("expires_at", ts(), nullable=False),
        sa.Column("revoked_at", ts()),
        sa.Column("replaced_by", sa.Uuid()),
        sa.Column("user_agent", sa.String(255)),
        sa.PrimaryKeyConstraint("session_id", name=op.f("pk_auth_sessions")),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], name=op.f("fk_auth_sessions_user_id_users"),
                                ondelete="CASCADE"),
        sa.UniqueConstraint("refresh_token_hash", name=op.f("uq_auth_sessions_refresh_token_hash")),
        sa.CheckConstraint("expires_at > issued_at", name=op.f("ck_auth_sessions_expiry_after_issue")),
    )
    op.create_index("ix_auth_sessions_user_active", "auth_sessions", ["user_id", "revoked_at"])

    op.create_table(
        "patients",
        sa.Column("patient_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid()),
        sa.Column("mrn", sa.String(20), nullable=False),
        sa.Column("first_name", sa.String(80), nullable=False),
        sa.Column("last_name", sa.String(80), nullable=False),
        sa.Column("date_of_birth", sa.Date(), nullable=False),
        sa.Column("sex", enum_col(SexAtBirth, "sex_at_birth"), nullable=False),
        sa.Column("phone", sa.String(16)),
        sa.Column("email", sa.String(254)),
        sa.Column("postal_code", sa.String(10)),
        sa.Column("timezone", sa.String(40), nullable=False),
        sa.Column("qualifying_event", enum_col(QualifyingEvent, "qualifying_event"), nullable=False),
        sa.Column("qualifying_event_date", sa.Date(), nullable=False),
        sa.Column("referral_date", sa.Date(), nullable=False),
        sa.Column("enrollment_date", sa.Date()),
        sa.Column("graduation_date", sa.Date()),
        sa.Column("program_status", enum_col(ProgramStatus, "program_status"), nullable=False),
        sa.Column("clinical_risk_category", enum_col(ClinicalRisk, "clinical_risk"), nullable=False),
        sa.Column("target_sessions", sa.SmallInteger(), nullable=False),
        sa.Column("created_by", sa.Uuid()),
        sa.Column("deleted_at", ts()),
        *_timestamps(),
        sa.PrimaryKeyConstraint("patient_id", name=op.f("pk_patients")),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], name=op.f("fk_patients_user_id_users"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.user_id"], name=op.f("fk_patients_created_by_users"),
                                ondelete="SET NULL"),
        sa.UniqueConstraint("user_id", name=op.f("uq_patients_user_id")),
        sa.UniqueConstraint("mrn", name=op.f("uq_patients_mrn")),
        sa.CheckConstraint("qualifying_event_date <= referral_date", name=op.f("ck_patients_event_before_referral")),
        sa.CheckConstraint("enrollment_date IS NULL OR enrollment_date >= referral_date",
                           name=op.f("ck_patients_enroll_after_referral")),
        sa.CheckConstraint("program_status IN ('referred', 'withdrawn') OR enrollment_date IS NOT NULL",
                           name=op.f("ck_patients_enrolled_status_has_date")),
        sa.CheckConstraint("(program_status = 'graduated') = (graduation_date IS NOT NULL)",
                           name=op.f("ck_patients_graduation_date_matches")),
        sa.CheckConstraint("graduation_date IS NULL OR graduation_date >= enrollment_date",
                           name=op.f("ck_patients_graduate_after_enroll")),
        sa.CheckConstraint("program_status <> 'active' OR clinical_risk_category IN ('low', 'moderate')",
                           name=op.f("ck_patients_home_program_risk")),
        sa.CheckConstraint("target_sessions BETWEEN 1 AND 72", name=op.f("ck_patients_target_sessions_range")),
        sa.CheckConstraint("length(trim(first_name)) > 0 AND length(trim(last_name)) > 0",
                           name=op.f("ck_patients_names_present")),
        sa.CheckConstraint("date_of_birth > '1900-01-01'", name=op.f("ck_patients_dob_after_1900")),
    )
    op.create_index("ix_patients_status_active", "patients", ["program_status"],
                    postgresql_where=sa.text("deleted_at IS NULL"), sqlite_where=sa.text("deleted_at IS NULL"))
    op.create_index("ix_patients_name", "patients", ["last_name", "first_name"])

    op.create_table(
        "care_team_assignments",
        sa.Column("assignment_id", sa.Uuid(), nullable=False),
        sa.Column("patient_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("team_role", enum_col(CareTeamRole, "care_team_role"), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date()),
        sa.PrimaryKeyConstraint("assignment_id", name=op.f("pk_care_team_assignments")),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.patient_id"],
                                name=op.f("fk_care_team_assignments_patient_id_patients"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], name=op.f("fk_care_team_assignments_user_id_users")),
        sa.CheckConstraint("end_date IS NULL OR end_date >= start_date", name=op.f("ck_care_team_assignments_dates_ordered")),
    )
    current_roles = "end_date IS NULL AND team_role IN ('primary_clinician', 'supervising_physician')"
    op.create_index("uq_care_team_one_current_role", "care_team_assignments", ["patient_id", "team_role"], unique=True,
                    postgresql_where=sa.text(current_roles), sqlite_where=sa.text(current_roles))
    op.create_index("ix_care_team_user_current", "care_team_assignments", ["user_id", "patient_id"],
                    postgresql_where=sa.text("end_date IS NULL"), sqlite_where=sa.text("end_date IS NULL"))

    op.create_table(
        "vital_signs",
        sa.Column("vital_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), autoincrement=True, nullable=False),
        sa.Column("patient_id", sa.Uuid(), nullable=False),
        sa.Column("recorded_at", ts(), nullable=False),
        sa.Column("received_at", ts(), nullable=False),
        sa.Column("context", enum_col(ReadingContext, "reading_context"), nullable=False),
        sa.Column("heart_rate", sa.SmallInteger()),
        sa.Column("systolic_bp", sa.SmallInteger()),
        sa.Column("diastolic_bp", sa.SmallInteger()),
        sa.Column("spo2", sa.SmallInteger()),
        sa.Column("source", enum_col(ReadingSource, "reading_source"), nullable=False),
        sa.Column("entered_by", sa.Uuid()),
        sa.Column("quality", enum_col(DataQuality, "data_quality"), nullable=False),
        sa.Column("idempotency_key", sa.String(64)),
        sa.PrimaryKeyConstraint("vital_id", name=op.f("pk_vital_signs")),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.patient_id"], name=op.f("fk_vital_signs_patient_id_patients"),
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["entered_by"], ["users.user_id"], name=op.f("fk_vital_signs_entered_by_users"),
                                ondelete="RESTRICT"),
        sa.UniqueConstraint("patient_id", "idempotency_key", name=op.f("uq_vital_signs_patient_id_idempotency_key")),
        sa.CheckConstraint("heart_rate IS NULL OR heart_rate BETWEEN 20 AND 300", name=op.f("ck_vital_signs_heart_rate_range")),
        sa.CheckConstraint("systolic_bp IS NULL OR systolic_bp BETWEEN 50 AND 300", name=op.f("ck_vital_signs_systolic_range")),
        sa.CheckConstraint("diastolic_bp IS NULL OR diastolic_bp BETWEEN 20 AND 200",
                           name=op.f("ck_vital_signs_diastolic_range")),
        sa.CheckConstraint("spo2 IS NULL OR spo2 BETWEEN 50 AND 100", name=op.f("ck_vital_signs_spo2_range")),
        sa.CheckConstraint("heart_rate IS NOT NULL OR systolic_bp IS NOT NULL OR spo2 IS NOT NULL",
                           name=op.f("ck_vital_signs_has_measurement")),
        sa.CheckConstraint("(systolic_bp IS NULL) = (diastolic_bp IS NULL)", name=op.f("ck_vital_signs_bp_pair")),
        sa.CheckConstraint("systolic_bp IS NULL OR systolic_bp > diastolic_bp", name=op.f("ck_vital_signs_bp_order")),
        sa.CheckConstraint("source <> 'manual' OR entered_by IS NOT NULL", name=op.f("ck_vital_signs_manual_has_author")),
    )
    op.create_index("ix_vital_signs_patient_time", "vital_signs", ["patient_id", "recorded_at"])

    op.create_table(
        "daily_activity",
        sa.Column("patient_id", sa.Uuid(), nullable=False),
        sa.Column("activity_date", sa.Date(), nullable=False),
        sa.Column("steps", sa.Integer(), nullable=False),
        sa.Column("active_minutes", sa.SmallInteger(), nullable=False),
        sa.Column("sedentary_minutes", sa.SmallInteger()),
        sa.Column("resting_hr", sa.SmallInteger()),
        sa.Column("source", enum_col(ReadingSource, "reading_source"), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("patient_id", "activity_date", name=op.f("pk_daily_activity")),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.patient_id"], name=op.f("fk_daily_activity_patient_id_patients"),
                                ondelete="CASCADE"),
        sa.CheckConstraint("steps BETWEEN 0 AND 100000", name=op.f("ck_daily_activity_steps_range")),
        sa.CheckConstraint("active_minutes BETWEEN 0 AND 1440", name=op.f("ck_daily_activity_active_minutes_range")),
        sa.CheckConstraint("sedentary_minutes IS NULL OR sedentary_minutes BETWEEN 0 AND 1440",
                           name=op.f("ck_daily_activity_sedentary_range")),
        sa.CheckConstraint("active_minutes + coalesce(sedentary_minutes, 0) <= 1440",
                           name=op.f("ck_daily_activity_minutes_fit_in_day")),
        sa.CheckConstraint("resting_hr IS NULL OR resting_hr BETWEEN 25 AND 150", name=op.f("ck_daily_activity_resting_hr_range")),
    )

    op.create_table(
        "audit_log",
        sa.Column("audit_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), autoincrement=True, nullable=False),
        sa.Column("occurred_at", ts(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid()),
        sa.Column("actor_role", enum_col(UserRole, "user_role")),
        sa.Column("action", enum_col(AuditAction, "audit_action"), nullable=False),
        sa.Column("entity_type", sa.String(40), nullable=False),
        sa.Column("entity_id", sa.String(64)),
        sa.Column("patient_id", sa.Uuid()),
        sa.Column("outcome", sa.String(10), nullable=False),
        sa.Column("request_id", sa.String(64)),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("audit_id", name=op.f("pk_audit_log")),
    )
    op.create_index("ix_audit_log_patient_time", "audit_log", ["patient_id", "occurred_at"])
    op.create_index("ix_audit_log_actor_time", "audit_log", ["actor_user_id", "occurred_at"])


def downgrade() -> None:
    for table in ("audit_log", "daily_activity", "vital_signs", "care_team_assignments", "patients", "auth_sessions",
                  "users"):
        op.drop_table(table)
    drop_enum_types(*[name for _, name in ENUMS])
