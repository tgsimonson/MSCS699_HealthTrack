"""exercise prescriptions, alert rules, patient threshold overrides, escalation policies, alerts, alert history,
and notifications (tables follow the phase 2 alerting design)"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (JSON, CheckConstraint, ForeignKey, Index, Integer, Numeric, SmallInteger, String, Text,
                        Uuid, event, text)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BigIntPK, Base, TimestampMixin, UTCDateTime, new_uuid, utcnow
from app.models.enums import (AlertEventType, AlertRuleType, AlertSeverity, AlertStatus, CareTeamRole,
                              NotificationChannel, NotificationStatus, sa_enum)

Threshold = Numeric(8, 2, asdecimal=False)
ACTIVE_WHERE = text("status IN ('open', 'acknowledged', 'escalated')")
CURRENT_WHERE = text("effective_to IS NULL")


class ExercisePrescription(Base):
    """the patient's individual exercise limits; its values are the patient-specific alert thresholds"""

    __tablename__ = "exercise_prescriptions"
    __table_args__ = (
        CheckConstraint("resting_hr_baseline BETWEEN 30 AND 120", name="baseline_range"),
        CheckConstraint("resting_hr_baseline < target_hr_min AND target_hr_min < target_hr_max "
                        "AND target_hr_max < hr_ceiling AND target_hr_min >= 40 AND hr_ceiling <= 200",
                        name="hr_order"),
        CheckConstraint("max_exercise_sbp BETWEEN 140 AND 250", name="max_sbp_range"),
        CheckConstraint("min_spo2 BETWEEN 85 AND 95", name="min_spo2_range"),
        CheckConstraint("sessions_per_week BETWEEN 1 AND 7", name="sessions_range"),
        CheckConstraint("session_minutes BETWEEN 10 AND 90", name="minutes_range"),
        CheckConstraint("effective_to IS NULL OR effective_to > effective_from", name="period"),
        # one current prescription per patient; older versions keep effective_to
        Index("ux_exercise_prescriptions_current", "patient_id", unique=True, postgresql_where=CURRENT_WHERE,
              sqlite_where=CURRENT_WHERE),
    )

    prescription_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.patient_id", ondelete="CASCADE"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    resting_hr_baseline: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    target_hr_min: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    target_hr_max: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    hr_ceiling: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    max_exercise_sbp: Mapped[int] = mapped_column(SmallInteger, default=200, nullable=False)
    min_spo2: Mapped[int] = mapped_column(SmallInteger, default=90, nullable=False)
    sessions_per_week: Mapped[int] = mapped_column(SmallInteger, default=3, nullable=False)
    session_minutes: Mapped[int] = mapped_column(SmallInteger, default=30, nullable=False)
    effective_from: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    effective_to: Mapped[datetime | None] = mapped_column(UTCDateTime)
    prescribed_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.user_id"), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)


class AlertRule(TimestampMixin, Base):
    """a program-wide rule; the threshold can come from the prescription or a per-patient override"""

    __tablename__ = "alert_rules"
    __table_args__ = (
        CheckConstraint("comparator IN ('>', '>=', '<', '<=')", name="comparator"),
        CheckConstraint("evaluation_window_minutes BETWEEN 0 AND 43200", name="window_range"),
        CheckConstraint("consecutive_required BETWEEN 1 AND 20", name="consecutive_range"),
        CheckConstraint("suppression_minutes BETWEEN 0 AND 10080", name="suppression_range"),
        # critical alerts are never suppressed
        CheckConstraint("severity <> 'critical' OR suppression_minutes = 0", name="critical_not_suppressed"),
    )

    rule_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    rule_code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    rule_type: Mapped[AlertRuleType] = mapped_column(sa_enum(AlertRuleType, "alert_rule_type"), nullable=False)
    metric: Mapped[str] = mapped_column(String(40), nullable=False)
    comparator: Mapped[str] = mapped_column(String(2), nullable=False)
    default_threshold: Mapped[float] = mapped_column(Threshold, nullable=False)
    # prescription column that supplies this patient's threshold, for example hr_ceiling
    prescription_field: Mapped[str | None] = mapped_column(String(40))
    applies_to_context: Mapped[list[str] | None] = mapped_column(JSON)       # null means every context
    evaluation_window_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    consecutive_required: Mapped[int] = mapped_column(SmallInteger, default=1, nullable=False)
    severity: Mapped[AlertSeverity] = mapped_column(sa_enum(AlertSeverity, "alert_severity"), nullable=False)
    suppression_minutes: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    is_customizable: Mapped[bool] = mapped_column(default=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.user_id"))


class PatientAlertThreshold(Base):
    """a per-patient override of one rule's threshold, with the clinical reason"""

    __tablename__ = "patient_alert_thresholds"
    __table_args__ = (
        CheckConstraint("length(trim(reason)) >= 5", name="reason_present"),
        CheckConstraint("effective_to IS NULL OR effective_to > effective_from", name="period"),
        Index("ux_patient_alert_thresholds_current", "patient_id", "rule_id", unique=True,
              postgresql_where=CURRENT_WHERE, sqlite_where=CURRENT_WHERE),
    )

    override_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.patient_id", ondelete="CASCADE"), nullable=False)
    rule_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("alert_rules.rule_id", ondelete="CASCADE"), nullable=False)
    threshold_value: Mapped[float] = mapped_column(Threshold, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    set_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.user_id"), nullable=False)
    effective_from: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    effective_to: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)

    rule: Mapped[AlertRule] = relationship()


class EscalationPolicy(Base):
    """per severity: who is told, on which channels, and how long before an unacknowledged alert escalates"""

    __tablename__ = "escalation_policies"
    __table_args__ = (
        CheckConstraint("ack_timeout_minutes BETWEEN 1 AND 1440", name="timeout_range"),
        CheckConstraint("max_escalation_level BETWEEN 0 AND 3", name="level_range"),
        CheckConstraint("severity <> 'critical' OR (ack_timeout_minutes <= 30 AND NOT deliver_as_digest)",
                        name="critical_fast"),
        CheckConstraint("NOT deliver_as_digest OR severity = 'low'", name="digest_low_only"),
    )

    severity: Mapped[AlertSeverity] = mapped_column(sa_enum(AlertSeverity, "alert_severity"), primary_key=True)
    ack_timeout_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    escalate_to: Mapped[CareTeamRole] = mapped_column(sa_enum(CareTeamRole, "care_team_role"), nullable=False)
    max_escalation_level: Mapped[int] = mapped_column(SmallInteger, default=2, nullable=False)
    channels: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    deliver_as_digest: Mapped[bool] = mapped_column(default=False, nullable=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.user_id"))
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow, nullable=False)


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        CheckConstraint("(acknowledged_at IS NULL) = (acknowledged_by IS NULL)", name="ack_pair"),
        CheckConstraint("acknowledged_at IS NULL OR acknowledged_at >= triggered_at", name="ack_after_trigger"),
        CheckConstraint("status <> 'acknowledged' OR acknowledged_at IS NOT NULL", name="ack_state"),
        CheckConstraint("status <> 'escalated' OR (escalation_level >= 1 AND escalated_at IS NOT NULL)",
                        name="escalated_state"),
        CheckConstraint("(status = 'resolved') = (resolved_at IS NOT NULL)", name="resolved_state"),
        CheckConstraint("status <> 'resolved' OR (resolved_by IS NOT NULL AND length(trim(coalesce(resolution_note, "
                        "''))) > 0 AND resolved_at >= triggered_at)", name="resolution_complete"),
        CheckConstraint("escalation_level BETWEEN 0 AND 3", name="level_range"),
        CheckConstraint("occurrences >= 1", name="occurrences_positive"),
        # one active alert per patient, rule, and condition: repeats attach to it instead of creating new alerts
        Index("ux_alerts_active_dedup", "patient_id", "rule_id", "dedup_key", unique=True,
              postgresql_where=ACTIVE_WHERE, sqlite_where=ACTIVE_WHERE),
        Index("ix_alerts_worklist", "status", "severity", "triggered_at"),
        Index("ix_alerts_patient_time", "patient_id", "triggered_at"),
    )

    alert_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.patient_id", ondelete="CASCADE"), nullable=False)
    rule_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("alert_rules.rule_id"), nullable=False)
    vital_id: Mapped[int | None] = mapped_column(ForeignKey("vital_signs.vital_id", ondelete="SET NULL"))
    severity: Mapped[AlertSeverity] = mapped_column(sa_enum(AlertSeverity, "alert_severity"), nullable=False)
    status: Mapped[AlertStatus] = mapped_column(sa_enum(AlertStatus, "alert_status"), default=AlertStatus.open,
                                                nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    triggering_values: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    threshold_applied: Mapped[float | None] = mapped_column(Threshold)
    threshold_source: Mapped[str | None] = mapped_column(String(20))      # default, prescription, or override
    dedup_key: Mapped[str] = mapped_column(String(120), nullable=False)
    occurrences: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    triggered_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    last_occurred_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    acknowledged_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.user_id"))
    escalation_level: Mapped[int] = mapped_column(SmallInteger, default=0, nullable=False)
    escalated_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.user_id"))
    resolution_note: Mapped[str | None] = mapped_column(Text)
    suppressed_reason: Mapped[str | None] = mapped_column(String(160))

    rule: Mapped[AlertRule] = relationship(lazy="joined")
    events: Mapped[list[AlertEvent]] = relationship(back_populates="alert", order_by="AlertEvent.event_id",
                                                    cascade="all, delete-orphan")


class AlertEvent(Base):
    """append-only alert history: creation, repeats, notifications, acknowledgment, escalation, resolution"""

    __tablename__ = "alert_events"
    __table_args__ = (Index("ix_alert_events_alert_time", "alert_id", "occurred_at"),)

    event_id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    alert_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("alerts.alert_id", ondelete="CASCADE"), nullable=False)
    event_type: Mapped[AlertEventType] = mapped_column(sa_enum(AlertEventType, "alert_event_type"), nullable=False)
    from_status: Mapped[AlertStatus | None] = mapped_column(sa_enum(AlertStatus, "alert_status"))
    to_status: Mapped[AlertStatus | None] = mapped_column(sa_enum(AlertStatus, "alert_status"))
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.user_id"))   # null means the system
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    alert: Mapped[Alert] = relationship(back_populates="events")


@event.listens_for(AlertEvent, "before_update")
def _event_immutable(_mapper, _conn, _target) -> None:  # noqa: ANN001
    raise PermissionError("alert_events is append-only")


class Notification(Base):
    """one message to one recipient on one channel (an outbox row: written with the alert, sent by the dispatcher)"""

    __tablename__ = "notifications"
    __table_args__ = (
        CheckConstraint("status NOT IN ('sent', 'delivered') OR sent_at IS NOT NULL", name="sent_has_time"),
        CheckConstraint("status <> 'failed' OR failure_reason IS NOT NULL", name="failed_has_reason"),
        CheckConstraint("delivered_at IS NULL OR delivered_at >= sent_at", name="delivery_order"),
        CheckConstraint("attempts BETWEEN 0 AND 10", name="attempts_range"),
        Index("ix_notifications_recipient_time", "recipient_user_id", "queued_at"),
        Index("ix_notifications_due", "deliver_after", postgresql_where=text("status = 'queued'"),
              sqlite_where=text("status = 'queued'")),
    )

    notification_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    alert_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("alerts.alert_id", ondelete="CASCADE"), nullable=False)
    recipient_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.user_id"), nullable=False)
    channel: Mapped[NotificationChannel] = mapped_column(sa_enum(NotificationChannel, "notification_channel"),
                                                         nullable=False)
    status: Mapped[NotificationStatus] = mapped_column(sa_enum(NotificationStatus, "notification_status"),
                                                       default=NotificationStatus.queued, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    escalation_level: Mapped[int] = mapped_column(SmallInteger, default=0, nullable=False)
    is_digest: Mapped[bool] = mapped_column(default=False, nullable=False)
    attempts: Mapped[int] = mapped_column(SmallInteger, default=0, nullable=False)
    queued_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    deliver_after: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    delivered_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    read_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    failure_reason: Mapped[str | None] = mapped_column(String(255))

    alert: Mapped[Alert] = relationship()


REQUIRED_PAYLOAD_KEYS = ("alert_id", "patient_id", "severity", "rule_code", "triggered_at")
