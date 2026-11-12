"""alert, rule, threshold, prescription, escalation, notification, and worklist schemas"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, Field, model_validator

from app.models import Alert, AlertEvent, Notification
from app.models.enums import (AlertEventType, AlertRuleType, AlertSeverity, AlertStatus, CareTeamRole,
                              NotificationChannel, NotificationStatus, ReadingContext)
from app.schemas.common import ApiModel

ALERT_EXAMPLE = {
    "alert_id": "6f1c2a9e-3b7d-4c51-9e2a-8d4b6c0f1a23", "patient_id": "00000000-0000-4000-b000-000000000005",
    "rule_code": "HR_ABOVE_CEILING", "rule_name": "Heart rate above prescribed ceiling", "rule_type": "threshold",
    "severity": "critical", "status": "escalated",
    "title": "Heart rate 138 bpm above prescribed limit of 128 bpm",
    "triggering_values": {"metric": "heart_rate", "values": [133, 138], "context": "exercise",
                          "recorded_at": "2026-11-12T16:18:00+00:00", "vital_id": 4412},
    "threshold_applied": 128.0, "threshold_source": "prescription", "occurrences": 3,
    "triggered_at": "2026-11-12T16:18:02+00:00", "last_occurred_at": "2026-11-12T16:20:01+00:00",
    "acknowledged_at": None, "acknowledged_by": None, "escalation_level": 1,
    "escalated_at": "2026-11-12T16:33:02+00:00", "resolved_at": None, "resolved_by": None, "resolution_note": None,
    "suppressed_reason": None}


class AlertOut(BaseModel):
    alert_id: uuid.UUID
    patient_id: uuid.UUID
    rule_code: str
    rule_name: str
    rule_type: AlertRuleType
    severity: AlertSeverity
    status: AlertStatus
    title: str
    triggering_values: dict[str, Any]
    threshold_applied: float | None
    threshold_source: Literal["default", "prescription", "override"] | None
    occurrences: int
    triggered_at: datetime
    last_occurred_at: datetime
    acknowledged_at: datetime | None
    acknowledged_by: uuid.UUID | None
    escalation_level: int
    escalated_at: datetime | None
    resolved_at: datetime | None
    resolved_by: uuid.UUID | None
    resolution_note: str | None
    suppressed_reason: str | None

    model_config = {"from_attributes": True, "json_schema_extra": {"examples": [ALERT_EXAMPLE]}}

    @model_validator(mode="before")
    @classmethod
    def _from_orm(cls, data: Any) -> Any:
        if isinstance(data, Alert):
            out = {c: getattr(data, c) for c in cls.model_fields if hasattr(Alert, c)}
            out.update(rule_code=data.rule.rule_code, rule_name=data.rule.name, rule_type=data.rule.rule_type)
            return out
        return data


class AlertEventOut(BaseModel):
    event_id: int
    event_type: AlertEventType
    from_status: AlertStatus | None
    to_status: AlertStatus | None
    actor_user_id: uuid.UUID | None = Field(description="null means the system")
    occurred_at: datetime
    note: str | None
    payload: dict[str, Any]

    model_config = {"from_attributes": True}


class NotificationOut(BaseModel):
    notification_id: uuid.UUID
    alert_id: uuid.UUID
    recipient_user_id: uuid.UUID
    channel: NotificationChannel
    status: NotificationStatus
    escalation_level: int
    is_digest: bool
    attempts: int
    queued_at: datetime
    deliver_after: datetime
    sent_at: datetime | None
    read_at: datetime | None
    failure_reason: str | None
    payload: dict[str, Any]

    model_config = {"from_attributes": True}


class AlertDetail(AlertOut):
    events: list[AlertEventOut]
    notifications: list[NotificationOut]
    timeline: dict[str, float | None] = Field(description="minutes from trigger to acknowledgment and resolution")


def alert_detail(alert: Alert, events: list[AlertEvent], notifications: list[Notification]) -> AlertDetail:
    base = AlertOut.model_validate(alert).model_dump()

    def mins(t: datetime | None) -> float | None:
        return round((t - alert.triggered_at).total_seconds() / 60, 1) if t else None

    return AlertDetail(**base, events=[AlertEventOut.model_validate(e) for e in events],
                       notifications=[NotificationOut.model_validate(n) for n in notifications],
                       timeline={"minutes_to_acknowledge": mins(alert.acknowledged_at),
                                 "minutes_to_escalate": mins(alert.escalated_at),
                                 "minutes_to_resolve": mins(alert.resolved_at)})


class AcknowledgeRequest(ApiModel):
    note: str | None = Field(default=None, max_length=1000, examples=["Called patient; stopping session and resting."])


class ResolveRequest(ApiModel):
    note: str = Field(min_length=3, max_length=2000,
                      examples=["HR back to 104 after 5 min rest; no symptoms. Reviewed with Dr. Ortiz."])


class CommentRequest(ApiModel):
    note: str = Field(min_length=1, max_length=2000, examples=["Left voicemail; will retry at 11:00."])


class AlertMetrics(BaseModel):
    start: datetime
    end: datetime
    total: int
    by_severity: dict[str, int]
    by_status: dict[str, int]
    escalated: int
    repeat_occurrences_absorbed: int
    minutes_to_acknowledge: dict[str, float | int | None]
    minutes_to_resolve: dict[str, float | int | None]
    critical_minutes_to_acknowledge: dict[str, float | int | None]
    notifications: dict[str, int]


class JobResult(BaseModel):
    job: str
    affected: int
    details: dict[str, Any] = {}


# ---------------------------------------------------------------- configuration
class AlertRuleOut(BaseModel):
    rule_id: uuid.UUID
    rule_code: str
    name: str
    description: str
    rule_type: AlertRuleType
    metric: str
    comparator: str
    default_threshold: float
    prescription_field: str | None
    applies_to_context: list[ReadingContext] | None
    evaluation_window_minutes: int
    consecutive_required: int
    severity: AlertSeverity
    suppression_minutes: int
    is_customizable: bool
    is_active: bool
    updated_by: uuid.UUID | None
    updated_at: datetime

    model_config = {"from_attributes": True}


class AlertRuleUpdate(ApiModel):
    """program-wide change; applies to every patient without an override or prescription value"""

    default_threshold: float | None = Field(default=None, ge=-100, le=1000, examples=[155])
    consecutive_required: int | None = Field(default=None, ge=1, le=20)
    evaluation_window_minutes: int | None = Field(default=None, ge=0, le=43200)
    severity: AlertSeverity | None = None
    suppression_minutes: int | None = Field(default=None, ge=0, le=10080)
    is_active: bool | None = None
    reason: str = Field(min_length=5, max_length=500, description="Why the rule is changing (kept in the audit log)",
                        examples=["Medical director review: too many alerts at 150 for post-PCI patients."])


class PrescriptionIn(ApiModel):
    resting_hr_baseline: int = Field(ge=30, le=120, examples=[66])
    target_hr_min: int = Field(ge=40, le=200, examples=[95])
    target_hr_max: int = Field(ge=40, le=200, examples=[115])
    hr_ceiling: int = Field(ge=40, le=200, examples=[128])
    max_exercise_sbp: int = Field(default=200, ge=140, le=250, examples=[180])
    min_spo2: int = Field(default=90, ge=85, le=95, examples=[90])
    sessions_per_week: int = Field(default=3, ge=1, le=7)
    session_minutes: int = Field(default=30, ge=10, le=90)
    notes: str | None = Field(default=None, max_length=2000, examples=["On beta-blocker; conservative ceiling."])

    @model_validator(mode="after")
    def _order(self) -> PrescriptionIn:
        if not self.resting_hr_baseline < self.target_hr_min < self.target_hr_max < self.hr_ceiling:
            raise ValueError("heart rates must satisfy resting_hr_baseline < target_hr_min < target_hr_max < hr_ceiling")
        return self


class PrescriptionOut(PrescriptionIn):
    model_config = {"from_attributes": True, "extra": "ignore"}
    prescription_id: uuid.UUID
    patient_id: uuid.UUID
    version: int
    effective_from: datetime
    effective_to: datetime | None
    prescribed_by: uuid.UUID


class EffectiveThreshold(BaseModel):
    rule_code: str
    name: str
    rule_type: AlertRuleType
    metric: str
    comparator: str
    threshold: float
    source: Literal["default", "prescription", "override"]
    severity: AlertSeverity
    applies_to_context: list[ReadingContext] | None
    consecutive_required: int
    is_customizable: bool
    override_reason: str | None = None
    override_set_by: uuid.UUID | None = None
    override_since: datetime | None = None


class ThresholdOverrideIn(ApiModel):
    rule_code: str = Field(examples=["RESTING_HR_HIGH"])
    threshold_value: float = Field(ge=-100, le=1000, examples=[90])
    reason: str = Field(min_length=5, max_length=1000,
                        examples=["On beta-blocker; baseline resting HR in the 60s, so 90 is abnormal for him."])


class EscalationPolicyOut(BaseModel):
    severity: AlertSeverity
    ack_timeout_minutes: int
    escalate_to: CareTeamRole
    max_escalation_level: int
    channels: list[NotificationChannel]
    deliver_as_digest: bool
    updated_by: uuid.UUID | None
    updated_at: datetime

    model_config = {"from_attributes": True}


class EscalationPolicyUpdate(ApiModel):
    ack_timeout_minutes: int = Field(ge=1, le=1440, examples=[15])
    escalate_to: CareTeamRole = CareTeamRole.supervising_physician
    max_escalation_level: int = Field(ge=0, le=3, examples=[2])
    channels: list[NotificationChannel] = Field(min_length=1, examples=[["dashboard", "sms", "email"]])
    deliver_as_digest: bool = False
    reason: str = Field(min_length=5, max_length=500, examples=["Shorten critical timeout after drill review."])

    @model_validator(mode="after")
    def _dashboard_always(self) -> EscalationPolicyUpdate:
        if NotificationChannel.dashboard not in self.channels:
            raise ValueError("channels must include dashboard")
        return self


# ---------------------------------------------------------------- dashboard support
class LatestValue(BaseModel):
    value: int | str
    recorded_at: datetime
    context: ReadingContext


class WorklistRow(BaseModel):
    patient_id: uuid.UUID
    mrn: str
    first_name: str
    last_name: str
    clinical_risk_category: str
    program_status: str
    latest: dict[str, LatestValue | None]
    last_reading_at: datetime | None
    active_alerts: dict[str, int] = Field(description="active alert counts by severity")
    top_alert: AlertOut | None
    priority: int = Field(description="4 critical, 3 high, 2 moderate, 1 low, 0 no active alert")
    prescription: dict[str, int] | None


class StreamTicket(BaseModel):
    ticket: str
    expires_in: int
    url: str = Field(examples=["ws://localhost:8000/api/v1/stream"])


class AwareRange(ApiModel):
    start: AwareDatetime | None = None
    end: AwareDatetime | None = None
