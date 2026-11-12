"""schema update: alerting (exercise prescriptions, rules, patient overrides, escalation policies, alerts,
alert history, notifications) plus the default rules and policies

Revision ID: 0003_alerting
Revises: 0002_device_registry
Create Date: 2026-11-10

New tables only, so the upgrade is safe on a populated phase 3 database. The default rules and escalation
policies are configuration data and are inserted here so every environment starts from the same settings.
"""
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

from app.alerts.defaults import policy_rows, rule_rows
from app.models.enums import (AlertEventType, AlertRuleType, AlertSeverity, AlertStatus, CareTeamRole,
                              NotificationChannel, NotificationStatus)
from migrations.helpers import create_enum_types, drop_enum_types, enum_col, is_postgres, ts

revision = "0003_alerting"
down_revision = "0002_device_registry"
branch_labels = None
depends_on = None

ENUMS = [(AlertRuleType, "alert_rule_type"), (AlertSeverity, "alert_severity"), (AlertStatus, "alert_status"),
         (AlertEventType, "alert_event_type"), (NotificationChannel, "notification_channel"),
         (NotificationStatus, "notification_status")]
BIGINT = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
NUM = sa.Numeric(8, 2, asdecimal=False)
CURRENT = sa.text("effective_to IS NULL")
ACTIVE = sa.text("status IN ('open', 'acknowledged', 'escalated')")


def _fk(table: str, col: str, ref: str, ref_col: str, ondelete: str | None = None) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint([col], [f"{ref}.{ref_col}"], name=op.f(f"fk_{table}_{col}_{ref}"), ondelete=ondelete)


def _ck(table: str, name: str, sql: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(sql, name=op.f(f"ck_{table}_{name}"))


def upgrade() -> None:
    create_enum_types(*ENUMS)
    t = "exercise_prescriptions"
    op.create_table(
        t,
        sa.Column("prescription_id", sa.Uuid(), nullable=False),
        sa.Column("patient_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("resting_hr_baseline", sa.SmallInteger(), nullable=False),
        sa.Column("target_hr_min", sa.SmallInteger(), nullable=False),
        sa.Column("target_hr_max", sa.SmallInteger(), nullable=False),
        sa.Column("hr_ceiling", sa.SmallInteger(), nullable=False),
        sa.Column("max_exercise_sbp", sa.SmallInteger(), nullable=False),
        sa.Column("min_spo2", sa.SmallInteger(), nullable=False),
        sa.Column("sessions_per_week", sa.SmallInteger(), nullable=False),
        sa.Column("session_minutes", sa.SmallInteger(), nullable=False),
        sa.Column("effective_from", ts(), nullable=False),
        sa.Column("effective_to", ts()),
        sa.Column("prescribed_by", sa.Uuid(), nullable=False),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", ts(), nullable=False),
        sa.PrimaryKeyConstraint("prescription_id", name=op.f(f"pk_{t}")),
        _fk(t, "patient_id", "patients", "patient_id", "CASCADE"),
        _fk(t, "prescribed_by", "users", "user_id"),
        _ck(t, "baseline_range", "resting_hr_baseline BETWEEN 30 AND 120"),
        _ck(t, "hr_order", "resting_hr_baseline < target_hr_min AND target_hr_min < target_hr_max "
                           "AND target_hr_max < hr_ceiling AND target_hr_min >= 40 AND hr_ceiling <= 200"),
        _ck(t, "max_sbp_range", "max_exercise_sbp BETWEEN 140 AND 250"),
        _ck(t, "min_spo2_range", "min_spo2 BETWEEN 85 AND 95"),
        _ck(t, "sessions_range", "sessions_per_week BETWEEN 1 AND 7"),
        _ck(t, "minutes_range", "session_minutes BETWEEN 10 AND 90"),
        _ck(t, "period", "effective_to IS NULL OR effective_to > effective_from"),
    )
    op.create_index("ux_exercise_prescriptions_current", t, ["patient_id"], unique=True,
                    postgresql_where=CURRENT, sqlite_where=CURRENT)

    t = "alert_rules"
    rules = op.create_table(
        t,
        sa.Column("rule_id", sa.Uuid(), nullable=False),
        sa.Column("rule_code", sa.String(40), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("rule_type", enum_col(AlertRuleType, "alert_rule_type"), nullable=False),
        sa.Column("metric", sa.String(40), nullable=False),
        sa.Column("comparator", sa.String(2), nullable=False),
        sa.Column("default_threshold", NUM, nullable=False),
        sa.Column("prescription_field", sa.String(40)),
        sa.Column("applies_to_context", sa.JSON()),
        sa.Column("evaluation_window_minutes", sa.Integer(), nullable=False),
        sa.Column("consecutive_required", sa.SmallInteger(), nullable=False),
        sa.Column("severity", enum_col(AlertSeverity, "alert_severity"), nullable=False),
        sa.Column("suppression_minutes", sa.Integer(), nullable=False),
        sa.Column("is_customizable", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("updated_by", sa.Uuid()),
        sa.Column("created_at", ts(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", ts(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("rule_id", name=op.f(f"pk_{t}")),
        sa.UniqueConstraint("rule_code", name=op.f("uq_alert_rules_rule_code")),
        _fk(t, "updated_by", "users", "user_id"),
        _ck(t, "comparator", "comparator IN ('>', '>=', '<', '<=')"),
        _ck(t, "window_range", "evaluation_window_minutes BETWEEN 0 AND 43200"),
        _ck(t, "consecutive_range", "consecutive_required BETWEEN 1 AND 20"),
        _ck(t, "suppression_range", "suppression_minutes BETWEEN 0 AND 10080"),
        _ck(t, "critical_not_suppressed", "severity <> 'critical' OR suppression_minutes = 0"),
    )

    t = "patient_alert_thresholds"
    op.create_table(
        t,
        sa.Column("override_id", sa.Uuid(), nullable=False),
        sa.Column("patient_id", sa.Uuid(), nullable=False),
        sa.Column("rule_id", sa.Uuid(), nullable=False),
        sa.Column("threshold_value", NUM, nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("set_by", sa.Uuid(), nullable=False),
        sa.Column("effective_from", ts(), nullable=False),
        sa.Column("effective_to", ts()),
        sa.Column("created_at", ts(), nullable=False),
        sa.PrimaryKeyConstraint("override_id", name=op.f(f"pk_{t}")),
        _fk(t, "patient_id", "patients", "patient_id", "CASCADE"),
        _fk(t, "rule_id", "alert_rules", "rule_id", "CASCADE"),
        _fk(t, "set_by", "users", "user_id"),
        _ck(t, "reason_present", "length(trim(reason)) >= 5"),
        _ck(t, "period", "effective_to IS NULL OR effective_to > effective_from"),
    )
    op.create_index("ux_patient_alert_thresholds_current", t, ["patient_id", "rule_id"], unique=True,
                    postgresql_where=CURRENT, sqlite_where=CURRENT)

    t = "escalation_policies"
    policies = op.create_table(
        t,
        sa.Column("severity", enum_col(AlertSeverity, "alert_severity"), nullable=False),
        sa.Column("ack_timeout_minutes", sa.Integer(), nullable=False),
        sa.Column("escalate_to", enum_col(CareTeamRole, "care_team_role"), nullable=False),
        sa.Column("max_escalation_level", sa.SmallInteger(), nullable=False),
        sa.Column("channels", sa.JSON(), nullable=False),
        sa.Column("deliver_as_digest", sa.Boolean(), nullable=False),
        sa.Column("updated_by", sa.Uuid()),
        sa.Column("updated_at", ts(), nullable=False),
        sa.PrimaryKeyConstraint("severity", name=op.f(f"pk_{t}")),
        _fk(t, "updated_by", "users", "user_id"),
        _ck(t, "timeout_range", "ack_timeout_minutes BETWEEN 1 AND 1440"),
        _ck(t, "level_range", "max_escalation_level BETWEEN 0 AND 3"),
        _ck(t, "critical_fast", "severity <> 'critical' OR (ack_timeout_minutes <= 30 AND NOT deliver_as_digest)"),
        _ck(t, "digest_low_only", "NOT deliver_as_digest OR severity = 'low'"),
    )

    t = "alerts"
    op.create_table(
        t,
        sa.Column("alert_id", sa.Uuid(), nullable=False),
        sa.Column("patient_id", sa.Uuid(), nullable=False),
        sa.Column("rule_id", sa.Uuid(), nullable=False),
        sa.Column("vital_id", BIGINT),
        sa.Column("severity", enum_col(AlertSeverity, "alert_severity"), nullable=False),
        sa.Column("status", enum_col(AlertStatus, "alert_status"), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("triggering_values", sa.JSON(), nullable=False),
        sa.Column("threshold_applied", NUM),
        sa.Column("threshold_source", sa.String(20)),
        sa.Column("dedup_key", sa.String(120), nullable=False),
        sa.Column("occurrences", sa.Integer(), nullable=False),
        sa.Column("triggered_at", ts(), nullable=False),
        sa.Column("last_occurred_at", ts(), nullable=False),
        sa.Column("acknowledged_at", ts()),
        sa.Column("acknowledged_by", sa.Uuid()),
        sa.Column("escalation_level", sa.SmallInteger(), nullable=False),
        sa.Column("escalated_at", ts()),
        sa.Column("resolved_at", ts()),
        sa.Column("resolved_by", sa.Uuid()),
        sa.Column("resolution_note", sa.Text()),
        sa.Column("suppressed_reason", sa.String(160)),
        sa.PrimaryKeyConstraint("alert_id", name=op.f(f"pk_{t}")),
        _fk(t, "patient_id", "patients", "patient_id", "CASCADE"),
        _fk(t, "rule_id", "alert_rules", "rule_id"),
        _fk(t, "vital_id", "vital_signs", "vital_id", "SET NULL"),
        _fk(t, "acknowledged_by", "users", "user_id"),
        _fk(t, "resolved_by", "users", "user_id"),
        _ck(t, "ack_pair", "(acknowledged_at IS NULL) = (acknowledged_by IS NULL)"),
        _ck(t, "ack_after_trigger", "acknowledged_at IS NULL OR acknowledged_at >= triggered_at"),
        _ck(t, "ack_state", "status <> 'acknowledged' OR acknowledged_at IS NOT NULL"),
        _ck(t, "escalated_state", "status <> 'escalated' OR (escalation_level >= 1 AND escalated_at IS NOT NULL)"),
        _ck(t, "resolved_state", "(status = 'resolved') = (resolved_at IS NOT NULL)"),
        _ck(t, "resolution_complete", "status <> 'resolved' OR (resolved_by IS NOT NULL AND length(trim(coalesce("
                                      "resolution_note, ''))) > 0 AND resolved_at >= triggered_at)"),
        _ck(t, "level_range", "escalation_level BETWEEN 0 AND 3"),
        _ck(t, "occurrences_positive", "occurrences >= 1"),
    )
    op.create_index("ux_alerts_active_dedup", t, ["patient_id", "rule_id", "dedup_key"], unique=True,
                    postgresql_where=ACTIVE, sqlite_where=ACTIVE)
    op.create_index("ix_alerts_worklist", t, ["status", "severity", "triggered_at"])
    op.create_index("ix_alerts_patient_time", t, ["patient_id", "triggered_at"])

    t = "alert_events"
    op.create_table(
        t,
        sa.Column("event_id", BIGINT, autoincrement=True, nullable=False),
        sa.Column("alert_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", enum_col(AlertEventType, "alert_event_type"), nullable=False),
        sa.Column("from_status", enum_col(AlertStatus, "alert_status")),
        sa.Column("to_status", enum_col(AlertStatus, "alert_status")),
        sa.Column("actor_user_id", sa.Uuid()),
        sa.Column("occurred_at", ts(), nullable=False),
        sa.Column("note", sa.Text()),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("event_id", name=op.f(f"pk_{t}")),
        _fk(t, "alert_id", "alerts", "alert_id", "CASCADE"),
        _fk(t, "actor_user_id", "users", "user_id"),
    )
    op.create_index("ix_alert_events_alert_time", t, ["alert_id", "occurred_at"])

    t = "notifications"
    op.create_table(
        t,
        sa.Column("notification_id", sa.Uuid(), nullable=False),
        sa.Column("alert_id", sa.Uuid(), nullable=False),
        sa.Column("recipient_user_id", sa.Uuid(), nullable=False),
        sa.Column("channel", enum_col(NotificationChannel, "notification_channel"), nullable=False),
        sa.Column("status", enum_col(NotificationStatus, "notification_status"), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("escalation_level", sa.SmallInteger(), nullable=False),
        sa.Column("is_digest", sa.Boolean(), nullable=False),
        sa.Column("attempts", sa.SmallInteger(), nullable=False),
        sa.Column("queued_at", ts(), nullable=False),
        sa.Column("deliver_after", ts(), nullable=False),
        sa.Column("sent_at", ts()),
        sa.Column("delivered_at", ts()),
        sa.Column("read_at", ts()),
        sa.Column("failure_reason", sa.String(255)),
        sa.PrimaryKeyConstraint("notification_id", name=op.f(f"pk_{t}")),
        _fk(t, "alert_id", "alerts", "alert_id", "CASCADE"),
        _fk(t, "recipient_user_id", "users", "user_id"),
        _ck(t, "sent_has_time", "status NOT IN ('sent', 'delivered') OR sent_at IS NOT NULL"),
        _ck(t, "failed_has_reason", "status <> 'failed' OR failure_reason IS NOT NULL"),
        _ck(t, "delivery_order", "delivered_at IS NULL OR delivered_at >= sent_at"),
        _ck(t, "attempts_range", "attempts BETWEEN 0 AND 10"),
    )
    op.create_index("ix_notifications_recipient_time", t, ["recipient_user_id", "queued_at"])
    op.create_index("ix_notifications_due", t, ["deliver_after"], postgresql_where=sa.text("status = 'queued'"),
                    sqlite_where=sa.text("status = 'queued'"))

    # configuration data: default rules and escalation policies
    op.bulk_insert(rules, [{**r, "rule_type": r["rule_type"].value, "severity": r["severity"].value}
                           for r in rule_rows()])
    now = datetime.now(timezone.utc)
    now = now if is_postgres() else now.replace(tzinfo=None)      # sqlite stores naive utc (see UTCDateTime)
    op.bulk_insert(policies, [{**p, "severity": p["severity"].value, "escalate_to": p["escalate_to"].value,
                               "updated_at": now} for p in policy_rows()])


def downgrade() -> None:
    for name, table in [("ix_notifications_due", "notifications"), ("ix_notifications_recipient_time", "notifications"),
                        ("ix_alert_events_alert_time", "alert_events"), ("ix_alerts_patient_time", "alerts"),
                        ("ix_alerts_worklist", "alerts"), ("ux_alerts_active_dedup", "alerts"),
                        ("ux_patient_alert_thresholds_current", "patient_alert_thresholds"),
                        ("ux_exercise_prescriptions_current", "exercise_prescriptions")]:
        op.drop_index(name, table_name=table)
    for table in ("notifications", "alert_events", "alerts", "escalation_policies", "patient_alert_thresholds",
                  "alert_rules", "exercise_prescriptions"):
        op.drop_table(table)
    drop_enum_types(*(name for _, name in ENUMS))
