"""alert engine: evaluates readings and trends against rules, raises alerts with duplicate and fatigue controls,
queues notifications by severity, escalates unacknowledged alerts, and records every state change

every public method takes `now` so tests and the benchmark can run on a controlled clock.
"""
from __future__ import annotations

import operator
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.alerts.notifications import build_payload, next_digest_time
from app.alerts.patterns import PatternMetrics
from app.config import Settings, get_settings
from app.errors import ValidationFailed
from app.logging_config import get_logger
from app.models import Alert, AlertRule, Notification, User, VitalSign
from app.models.base import utcnow
from app.models.enums import (ACTIVE_ALERT_STATUSES, AlertEventType, AlertRuleType, AlertSeverity, AlertStatus,
                              CareTeamRole, DataQuality, NotificationChannel)
from app.repositories.alerts import AlertRepository, ensure_transition
from app.repositories.monitoring import VitalSignRepository

log = get_logger("alerts.engine")

COMPARATORS = {">": operator.gt, ">=": operator.ge, "<": operator.lt, "<=": operator.le}
WORDS = {">": "above", ">=": "at or above", "<": "below", "<=": "at or below"}
METRIC_LABELS = {"heart_rate": ("Heart rate", "bpm"), "systolic_bp": ("Systolic pressure", "mmHg"),
                 "diastolic_bp": ("Diastolic pressure", "mmHg"), "spo2": ("SpO2", "%")}
SOURCE_WORDS = {"prescription": "prescribed limit", "override": "patient limit", "default": "program limit"}
LEVEL0_ROLES = {CareTeamRole.primary_clinician, CareTeamRole.covering_clinician}
ALL_CHANNELS = [c.value for c in NotificationChannel]


def breaches(value: float, comparator: str, threshold: float) -> bool:
    return COMPARATORS[comparator](value, threshold)


def threshold_title(rule: AlertRule, value: float, threshold: float, source: str) -> str:
    label, unit = METRIC_LABELS.get(rule.metric, (rule.metric, ""))
    sep = "" if unit == "%" else " "
    return (f"{label} {value:g}{sep}{unit} {WORDS[rule.comparator]} {SOURCE_WORDS[source]} of "
            f"{threshold:g}{sep}{unit}")[:160]


class ThresholdResolver:
    """patient override, then exercise prescription, then the rule default"""

    def __init__(self, repo: AlertRepository, patient_id: uuid.UUID) -> None:
        self.rx = repo.current_prescription(patient_id)
        self.overrides = {o.rule_id: o for o in repo.current_overrides(patient_id)}

    def resolve(self, rule: AlertRule) -> tuple[float, str]:
        if rule.rule_id in self.overrides:
            return float(self.overrides[rule.rule_id].threshold_value), "override"
        if rule.prescription_field and self.rx is not None:
            return float(getattr(self.rx, rule.prescription_field)), "prescription"
        return float(rule.default_threshold), "default"


@dataclass
class Outcome:
    alert: Alert
    action: str          # created, repeated, or suppressed
    notifications: int = 0


class AlertEngine:
    def __init__(self, session: Session, settings: Settings | None = None) -> None:
        self.s = session
        self.settings = settings or get_settings()
        self.repo = AlertRepository(session)
        self.vitals = VitalSignRepository(session)

    # ---------------------------------------------------------------- threshold rules (every reading)
    def evaluate_readings(self, patient_id: uuid.UUID, vitals: list[VitalSign],
                          now: datetime | None = None) -> list[Outcome]:
        """check each valid reading against the active threshold rules; suspect and artifact readings never alert"""
        now = now or utcnow()
        self.s.flush()
        rules = self.repo.list_rules(active_only=True, rule_types=(AlertRuleType.threshold,))
        resolver: ThresholdResolver | None = None
        outcomes: list[Outcome] = []
        for v in sorted(vitals, key=lambda x: (x.recorded_at, x.vital_id or 0)):
            if v.quality != DataQuality.valid:
                continue
            for rule in rules:
                value = getattr(v, rule.metric, None)
                if value is None or (rule.applies_to_context and v.context.value not in rule.applies_to_context):
                    continue
                resolver = resolver or ThresholdResolver(self.repo, patient_id)
                threshold, source = resolver.resolve(rule)
                if not breaches(value, rule.comparator, threshold):
                    continue
                values = [value]
                if rule.consecutive_required > 1:
                    prior = self.vitals.prior_values(patient_id, rule.metric, rule.applies_to_context, v.recorded_at,
                                                     rule.evaluation_window_minutes or 30,
                                                     rule.consecutive_required - 1)
                    if (len(prior) < rule.consecutive_required - 1
                            or not all(breaches(p, rule.comparator, threshold) for p in prior)):
                        continue
                    values = [*reversed(prior), value]
                trig = {"metric": rule.metric, "values": values, "context": v.context.value,
                        "recorded_at": v.recorded_at.isoformat(), "vital_id": v.vital_id}
                outcomes.append(self.raise_alert(patient_id, rule, title=threshold_title(rule, value, threshold, source),
                                                 triggering=trig, threshold=threshold, source=source,
                                                 vital_id=v.vital_id, now=now))
        return outcomes

    # ---------------------------------------------------------------- pattern and data-gap rules (scheduled)
    def evaluate_patterns(self, patient_ids: set[uuid.UUID] | None = None,
                          now: datetime | None = None) -> list[Outcome]:
        now = now or utcnow()
        self.s.flush()
        rules = self.repo.list_rules(active_only=True, rule_types=(AlertRuleType.pattern, AlertRuleType.data_gap))
        if not rules:
            return []
        wanted = {r.metric for r in rules}
        outcomes: list[Outcome] = []
        for patient in self.repo.monitored_patients():
            if patient_ids is not None and patient.patient_id not in patient_ids:
                continue
            rx = self.repo.current_prescription(patient.patient_id)
            metrics = PatternMetrics(self.s, patient, rx, now).compute(wanted)
            resolver = ThresholdResolver(self.repo, patient.patient_id)
            for rule in rules:
                result = metrics.get(rule.metric)
                if result is None:
                    continue
                threshold, source = resolver.resolve(rule)
                if breaches(result.value, rule.comparator, threshold):
                    trig = {"metric": rule.metric, "value": round(result.value, 1), **result.details}
                    outcomes.append(self.raise_alert(patient.patient_id, rule, title=result.title, triggering=trig,
                                                     threshold=threshold, source=source, now=now))
        return outcomes

    # ---------------------------------------------------------------- raising
    def raise_alert(self, patient_id: uuid.UUID, rule: AlertRule, *, title: str, triggering: dict[str, Any],
                    threshold: float | None, source: str | None, vital_id: int | None = None,
                    dedup_key: str | None = None, now: datetime | None = None) -> Outcome:
        """create an alert, or fold the occurrence into an existing one, applying the fatigue controls in order:
        1 duplicate (an active alert for the same condition absorbs the repeat), 2 suppression window after a
        recent alert of the same rule, 3 masking by a more severe active alert on the same measurement.
        critical alerts skip 2 and 3, so they always notify."""
        now = now or utcnow()
        dedup_key = dedup_key or rule.rule_code
        active = self.repo.active_alert(patient_id, rule.rule_id, dedup_key)
        if active is not None:
            return self._repeat(active, rule, triggering, now)
        base = dict(patient_id=patient_id, rule_id=rule.rule_id, vital_id=vital_id, severity=rule.severity,
                    title=title, triggering_values=triggering, threshold_applied=threshold, threshold_source=source,
                    dedup_key=dedup_key, triggered_at=now, last_occurred_at=now)
        if rule.severity != AlertSeverity.critical:
            if rule.suppression_minutes:
                recent = self.repo.latest_real_since(patient_id, rule.rule_id,
                                                     now - timedelta(minutes=rule.suppression_minutes))
                if recent is not None:
                    holder = self.repo.suppressed_after(patient_id, rule.rule_id, recent.triggered_at)
                    if holder is not None:
                        return self._repeat(holder, rule, triggering, now)
                    return self._suppress(base, f"within the {rule.suppression_minutes}-minute suppression window "
                                                f"after alert {str(recent.alert_id)[:8]}", now)
            mask = self.repo.masking_alert(patient_id, rule.metric, rule.severity)
            if mask is not None:
                return self._suppress(base, f"masked by active {mask.severity.value} alert {mask.rule.rule_code}", now)
        try:
            with self.s.begin_nested():
                alert = self.repo.add(Alert(**base, status=AlertStatus.open))
        except IntegrityError:                      # a concurrent request created the same alert first
            active = self.repo.active_alert(patient_id, rule.rule_id, dedup_key)
            if active is None:
                raise
            return self._repeat(active, rule, triggering, now)
        self.repo.add_event(alert, AlertEventType.created, to_status=AlertStatus.open, at=now,
                            payload={"threshold": threshold, "threshold_source": source})
        storm = False
        if rule.severity != AlertSeverity.critical:
            storm = self.repo.count_recent(patient_id, now - timedelta(hours=1)) > \
                self.settings.max_noncritical_alerts_per_hour
        n = self.queue_notifications(alert, 0, now, storm=storm)
        log.info("alert created", extra={"ctx": {"alert_id": str(alert.alert_id), "rule": rule.rule_code,
                                                 "severity": rule.severity.value, "patient_id": str(patient_id),
                                                 "notifications": n, "storm_capped": storm}})
        return Outcome(alert, "created", n)

    def _repeat(self, alert: Alert, rule: AlertRule, triggering: dict[str, Any], now: datetime) -> Outcome:
        alert.occurrences += 1
        alert.last_occurred_at = max(now, alert.last_occurred_at)
        alert.triggering_values = {**alert.triggering_values, "latest": triggering}
        if rule.rule_type == AlertRuleType.threshold and alert.status in ACTIVE_ALERT_STATUSES:
            self.repo.add_event(alert, AlertEventType.repeated, at=now,
                                payload={"occurrence": alert.occurrences, "values": triggering.get("values")})
        return Outcome(alert, "repeated" if alert.status != AlertStatus.suppressed else "suppressed")

    def _suppress(self, base: dict[str, Any], reason: str, now: datetime) -> Outcome:
        alert = self.repo.add(Alert(**base, status=AlertStatus.suppressed, suppressed_reason=reason[:160]))
        self.repo.add_event(alert, AlertEventType.suppressed, to_status=AlertStatus.suppressed, note=reason, at=now)
        log.info("alert suppressed", extra={"ctx": {"alert_id": str(alert.alert_id), "reason": reason}})
        return Outcome(alert, "suppressed")

    # ---------------------------------------------------------------- notifications
    def recipients(self, alert: Alert, level: int) -> list[User]:
        """level 0: the patient's clinicians; level 1: the policy's escalation role; level 2+: the whole care team"""
        pol = self.repo.policy(alert.severity)
        if level == 0:
            users = self.repo.care_team_members(alert.patient_id, LEVEL0_ROLES)
        elif level == 1:
            users = self.repo.care_team_members(alert.patient_id, {pol.escalate_to})
        else:
            users = self.repo.care_team_members(alert.patient_id)
        return users or self.repo.care_team_members(alert.patient_id)

    def queue_notifications(self, alert: Alert, level: int, now: datetime, *, storm: bool = False) -> int:
        """write one outbox row per recipient and channel; the dispatcher sends them (critical first)"""
        pol = self.repo.policy(alert.severity)
        channels = pol.channels if level < 2 else ALL_CHANNELS
        payload = build_payload(alert, level, self.settings)
        digest_at = next_digest_time(now, self.settings)
        count = 0
        for user in self.recipients(alert, level):
            for ch in channels:
                channel = NotificationChannel(ch)
                if channel == NotificationChannel.sms and not user.phone:
                    continue
                digest = channel != NotificationChannel.dashboard and (pol.deliver_as_digest or storm)
                self.repo.add_notification(Notification(
                    alert_id=alert.alert_id, recipient_user_id=user.user_id, channel=channel, payload=payload,
                    escalation_level=level, is_digest=digest, queued_at=now,
                    deliver_after=digest_at if digest else now))
                count += 1
        return count

    # ---------------------------------------------------------------- escalation (scheduled)
    def run_escalations(self, now: datetime | None = None) -> list[Alert]:
        """raise the level of open alerts that nobody acknowledged within the policy timeout"""
        now = now or utcnow()
        self.s.flush()                                  # include acknowledgments made earlier in this session
        escalated = []
        for alert in self.repo.escalation_candidates():
            pol = self.repo.policy(alert.severity)
            if alert.status not in (AlertStatus.open, AlertStatus.escalated) or \
                    alert.escalation_level >= pol.max_escalation_level:
                continue
            since = alert.escalated_at or alert.triggered_at
            if now - since < timedelta(minutes=pol.ack_timeout_minutes):
                continue
            previous = alert.status
            alert.escalation_level += 1
            alert.status = AlertStatus.escalated
            alert.escalated_at = now
            n = self.queue_notifications(alert, alert.escalation_level, now)
            self.repo.add_event(alert, AlertEventType.escalated, from_status=previous, to_status=AlertStatus.escalated,
                                at=now, payload={"level": alert.escalation_level, "notifications": n,
                                                 "unacknowledged_minutes": round((now - alert.triggered_at)
                                                                                 .total_seconds() / 60, 1)})
            escalated.append(alert)
            log.warning("alert escalated", extra={"ctx": {"alert_id": str(alert.alert_id),
                                                          "escalation_level": alert.escalation_level}})
        return escalated

    # ---------------------------------------------------------------- clinician actions
    def acknowledge(self, alert: Alert, user: User, note: str | None = None, now: datetime | None = None) -> Alert:
        now = now or utcnow()
        ensure_transition(alert, (AlertStatus.open, AlertStatus.escalated), "acknowledge")
        previous = alert.status
        alert.status, alert.acknowledged_at, alert.acknowledged_by = AlertStatus.acknowledged, now, user.user_id
        self.repo.add_event(alert, AlertEventType.acknowledged, actor=user, from_status=previous,
                            to_status=AlertStatus.acknowledged, note=note, at=now,
                            payload={"minutes_to_acknowledge": _minutes(alert.triggered_at, now),
                                     "escalation_level": alert.escalation_level})
        return alert

    def resolve(self, alert: Alert, user: User, note: str, now: datetime | None = None) -> Alert:
        now = now or utcnow()
        ensure_transition(alert, ACTIVE_ALERT_STATUSES, "resolve")
        if not note or len(note.strip()) < 3:
            raise ValidationFailed("a resolution note is required",
                                   errors=[{"field": "note", "message": "required", "code": "missing"}])
        previous = alert.status
        if alert.acknowledged_at is None:             # resolving implies acknowledging
            alert.acknowledged_at, alert.acknowledged_by = now, user.user_id
        alert.status, alert.resolved_at, alert.resolved_by, alert.resolution_note = (
            AlertStatus.resolved, now, user.user_id, note.strip())
        self.repo.add_event(alert, AlertEventType.resolved, actor=user, from_status=previous,
                            to_status=AlertStatus.resolved, note=note.strip(), at=now,
                            payload={"minutes_to_resolve": _minutes(alert.triggered_at, now)})
        return alert

    def comment(self, alert: Alert, user: User, note: str, now: datetime | None = None) -> None:
        self.repo.add_event(alert, AlertEventType.comment, actor=user, note=note.strip(), at=now or utcnow())


def _minutes(start: datetime, end: datetime) -> float:
    return round((end - start).total_seconds() / 60, 1)
