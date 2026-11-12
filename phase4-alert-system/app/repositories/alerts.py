"""alert data access: rules, thresholds, prescriptions, escalation policies, alerts, history, and notifications"""
from __future__ import annotations

import statistics
import uuid
from collections import Counter
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.errors import ConflictError, NotFoundError, ValidationFailed
from app.logging_config import get_logger
from app.models import (Alert, AlertEvent, AlertRule, CareTeamAssignment, EscalationPolicy, ExercisePrescription,
                        Notification, Patient, PatientAlertThreshold, User)
from app.models.base import utcnow
from app.models.enums import (ACTIVE_ALERT_STATUSES, AlertEventType, AlertRuleType, AlertSeverity, AlertStatus,
                              CareTeamRole, NotificationStatus, ProgramStatus, UserRole)
from app.repositories.base import PageResult, db_errors, paginate
from app.repositories.monitoring import check_range

log = get_logger("dal.alerts")

SEVERITY_ORDER = case({"critical": 4, "high": 3, "moderate": 2, "low": 1}, value=Alert.severity)
PRESCRIPTION_FIELDS = ("resting_hr_baseline", "target_hr_min", "target_hr_max", "hr_ceiling", "max_exercise_sbp",
                       "min_spo2", "sessions_per_week", "session_minutes", "notes")


class AlertRepository:
    def __init__(self, session: Session) -> None:
        self.s = session
        self._policies: dict[AlertSeverity, EscalationPolicy] | None = None

    # ---------------------------------------------------------------- rules
    def list_rules(self, *, active_only: bool = False, rule_types: tuple[AlertRuleType, ...] | None = None
                   ) -> list[AlertRule]:
        stmt = select(AlertRule)
        if active_only:
            stmt = stmt.where(AlertRule.is_active.is_(True))
        if rule_types:
            stmt = stmt.where(AlertRule.rule_type.in_(rule_types))
        return list(self.s.scalars(stmt.order_by(AlertRule.rule_type, AlertRule.rule_code)))

    def get_rule(self, rule_code: str) -> AlertRule:
        rule = self.s.scalar(select(AlertRule).where(AlertRule.rule_code == rule_code))
        if rule is None:
            raise NotFoundError("alert rule not found")
        return rule

    def update_rule(self, rule_code: str, changes: dict[str, Any], user: User) -> tuple[AlertRule, list[str]]:
        rule = self.get_rule(rule_code)
        severity = changes.get("severity", rule.severity)
        suppression = changes.get("suppression_minutes", rule.suppression_minutes)
        if severity == AlertSeverity.critical and suppression:
            raise ValidationFailed("critical rules cannot be suppressed; suppression_minutes must be 0",
                                   errors=[{"field": "suppression_minutes", "message": "must be 0 for critical rules",
                                            "code": "critical_not_suppressed"}])
        changed = [k for k, v in changes.items() if getattr(rule, k) != v]
        with db_errors(self.s, "alert rule", "update"):
            for k in changed:
                setattr(rule, k, changes[k])
            rule.updated_by = user.user_id
        log.info("alert rule updated", extra={"ctx": {"rule": rule_code, "changed": changed,
                                                      "user_id": str(user.user_id)}})
        return rule, changed

    # ---------------------------------------------------------------- prescriptions
    def current_prescription(self, patient_id: uuid.UUID) -> ExercisePrescription | None:
        return self.s.scalar(select(ExercisePrescription).where(ExercisePrescription.patient_id == patient_id,
                                                                ExercisePrescription.effective_to.is_(None)))

    def prescription_history(self, patient_id: uuid.UUID) -> list[ExercisePrescription]:
        return list(self.s.scalars(select(ExercisePrescription).where(ExercisePrescription.patient_id == patient_id)
                                   .order_by(ExercisePrescription.version.desc())))

    def set_prescription(self, patient_id: uuid.UUID, data: dict[str, Any], user: User,
                         now: datetime | None = None) -> ExercisePrescription:
        """new version; the previous one is closed at the same instant so history is never overwritten"""
        now = now or utcnow()
        current = self.current_prescription(patient_id)
        with db_errors(self.s, "exercise prescription", "set"):
            if current is not None:
                current.effective_to = now
                self.s.flush()
            rx = ExercisePrescription(patient_id=patient_id, version=(current.version + 1) if current else 1,
                                      effective_from=now, prescribed_by=user.user_id,
                                      **{k: v for k, v in data.items() if k in PRESCRIPTION_FIELDS})
            self.s.add(rx)
        log.info("prescription set", extra={"ctx": {"patient_id": str(patient_id), "version": rx.version}})
        return rx

    # ---------------------------------------------------------------- patient overrides
    def current_overrides(self, patient_id: uuid.UUID) -> list[PatientAlertThreshold]:
        return list(self.s.scalars(select(PatientAlertThreshold).where(
            PatientAlertThreshold.patient_id == patient_id, PatientAlertThreshold.effective_to.is_(None))))

    def set_override(self, patient_id: uuid.UUID, rule: AlertRule, value: float, reason: str, user: User,
                     now: datetime | None = None) -> PatientAlertThreshold:
        if not rule.is_customizable:
            raise ValidationFailed(f"{rule.rule_code} is not customizable per patient; its patient value comes from "
                                   "the exercise prescription" if rule.prescription_field else
                                   f"{rule.rule_code} is not customizable per patient")
        now = now or utcnow()
        with db_errors(self.s, "alert threshold override", "set"):
            for old in self.current_overrides(patient_id):
                if old.rule_id == rule.rule_id:
                    old.effective_to = now
            self.s.flush()
            ov = PatientAlertThreshold(patient_id=patient_id, rule_id=rule.rule_id, threshold_value=value,
                                       reason=reason, set_by=user.user_id, effective_from=now)
            self.s.add(ov)
        log.info("threshold override set", extra={"ctx": {"patient_id": str(patient_id), "rule": rule.rule_code}})
        return ov

    def end_override(self, patient_id: uuid.UUID, rule: AlertRule, now: datetime | None = None) -> None:
        current = [o for o in self.current_overrides(patient_id) if o.rule_id == rule.rule_id]
        if not current:
            raise NotFoundError("no current override for this rule")
        with db_errors(self.s, "alert threshold override", "end"):
            current[0].effective_to = now or utcnow()

    # ---------------------------------------------------------------- escalation policies
    def policy(self, severity: AlertSeverity) -> EscalationPolicy:
        if self._policies is None:
            self._policies = {p.severity: p for p in self.s.scalars(select(EscalationPolicy))}
        if severity not in self._policies:
            raise NotFoundError(f"no escalation policy for {severity.value}")
        return self._policies[severity]

    def list_policies(self) -> list[EscalationPolicy]:
        order = case({"critical": 1, "high": 2, "moderate": 3, "low": 4}, value=EscalationPolicy.severity)
        return list(self.s.scalars(select(EscalationPolicy).order_by(order)))

    def update_policy(self, severity: AlertSeverity, data: dict[str, Any], user: User) -> EscalationPolicy:
        pol = self.s.get(EscalationPolicy, severity)
        if pol is None:
            raise NotFoundError("escalation policy not found")
        with db_errors(self.s, "escalation policy", "update"):
            for k, v in data.items():
                setattr(pol, k, v)
            pol.updated_by = user.user_id
        self._policies = None
        return pol

    # ---------------------------------------------------------------- recipients
    def care_team_members(self, patient_id: uuid.UUID, roles: set[CareTeamRole] | None = None) -> list[User]:
        today = date.today()
        stmt = (select(User).join(CareTeamAssignment, CareTeamAssignment.user_id == User.user_id)
                .where(CareTeamAssignment.patient_id == patient_id, CareTeamAssignment.end_date.is_(None),
                       CareTeamAssignment.start_date <= today, User.is_active.is_(True)))
        if roles:
            stmt = stmt.where(CareTeamAssignment.team_role.in_(roles))
        return list(self.s.scalars(stmt.order_by(CareTeamAssignment.team_role)).unique())

    def scoped_patient_ids(self, user: User) -> set[uuid.UUID]:
        """patients whose alerts and readings this user may see"""
        if user.role in (UserRole.clinician, UserRole.physician):
            today = date.today()
            return set(self.s.scalars(select(CareTeamAssignment.patient_id).where(
                CareTeamAssignment.user_id == user.user_id, CareTeamAssignment.end_date.is_(None),
                CareTeamAssignment.start_date <= today)))
        if user.role == UserRole.patient:
            return set(self.s.scalars(select(Patient.patient_id).where(Patient.user_id == user.user_id)))
        return set()

    def monitored_patients(self) -> list[Patient]:
        return list(self.s.scalars(select(Patient).where(Patient.program_status == ProgramStatus.active,
                                                         Patient.deleted_at.is_(None))))

    # ---------------------------------------------------------------- alerts
    def get(self, alert_id: uuid.UUID) -> Alert:
        alert = self.s.get(Alert, alert_id)
        if alert is None:
            raise NotFoundError("alert not found")
        return alert

    def active_alert(self, patient_id: uuid.UUID, rule_id: uuid.UUID, dedup_key: str) -> Alert | None:
        return self.s.scalar(select(Alert).where(Alert.patient_id == patient_id, Alert.rule_id == rule_id,
                                                 Alert.dedup_key == dedup_key,
                                                 Alert.status.in_(ACTIVE_ALERT_STATUSES)))

    def latest_real_since(self, patient_id: uuid.UUID, rule_id: uuid.UUID, since: datetime) -> Alert | None:
        """the most recent notified (not suppressed) alert of this rule triggered or resolved inside the window;
        the suppression window is anchored here, so continuous breaches cannot keep extending it"""
        return self.s.scalar(select(Alert).where(
            Alert.patient_id == patient_id, Alert.rule_id == rule_id, Alert.status != AlertStatus.suppressed,
            (Alert.triggered_at >= since) | (Alert.resolved_at >= since))
            .order_by(Alert.triggered_at.desc()).limit(1))

    def suppressed_after(self, patient_id: uuid.UUID, rule_id: uuid.UUID, after: datetime) -> Alert | None:
        """the suppressed record that collects repeats inside the current window"""
        return self.s.scalar(select(Alert).where(
            Alert.patient_id == patient_id, Alert.rule_id == rule_id, Alert.status == AlertStatus.suppressed,
            Alert.triggered_at >= after).order_by(Alert.triggered_at.desc()).limit(1))

    def masking_alert(self, patient_id: uuid.UUID, metric: str, above: AlertSeverity) -> Alert | None:
        """an active alert on the same measurement with higher severity (it masks lesser ones)"""
        higher = [s for s in AlertSeverity if s.rank > above.rank]
        if not higher:
            return None
        return self.s.scalar(select(Alert).join(AlertRule, AlertRule.rule_id == Alert.rule_id).where(
            Alert.patient_id == patient_id, AlertRule.metric == metric, Alert.severity.in_(higher),
            Alert.status.in_(ACTIVE_ALERT_STATUSES)).limit(1))

    def count_recent(self, patient_id: uuid.UUID, since: datetime, *, noncritical: bool = True) -> int:
        stmt = select(func.count()).select_from(Alert).where(Alert.patient_id == patient_id,
                                                             Alert.triggered_at >= since,
                                                             Alert.status != AlertStatus.suppressed)
        if noncritical:
            stmt = stmt.where(Alert.severity != AlertSeverity.critical)
        return self.s.scalar(stmt) or 0

    def add(self, alert: Alert) -> Alert:
        self.s.add(alert)
        self.s.flush()
        return alert

    def add_event(self, alert: Alert, event_type: AlertEventType, *, actor: User | None = None,
                  from_status: AlertStatus | None = None, to_status: AlertStatus | None = None,
                  note: str | None = None, payload: dict | None = None, at: datetime | None = None) -> AlertEvent:
        ev = AlertEvent(alert_id=alert.alert_id, event_type=event_type, from_status=from_status, to_status=to_status,
                        actor_user_id=actor.user_id if actor else None, note=note, payload=payload or {},
                        occurred_at=at or utcnow())
        self.s.add(ev)
        return ev

    def events(self, alert_id: uuid.UUID) -> list[AlertEvent]:
        return list(self.s.scalars(select(AlertEvent).where(AlertEvent.alert_id == alert_id)
                                   .order_by(AlertEvent.occurred_at, AlertEvent.event_id)))

    def escalation_candidates(self) -> list[Alert]:
        return list(self.s.scalars(select(Alert).where(Alert.status.in_((AlertStatus.open, AlertStatus.escalated)))))

    def active_for_patients(self, patient_ids: set[uuid.UUID]) -> list[Alert]:
        if not patient_ids:
            return []
        return list(self.s.scalars(select(Alert).where(Alert.patient_id.in_(patient_ids),
                                                       Alert.status.in_(ACTIVE_ALERT_STATUSES))
                                   .order_by(SEVERITY_ORDER.desc(), Alert.triggered_at.desc())))

    def search(self, *, scope: set[uuid.UUID] | None, patient_id: uuid.UUID | None = None,
               severity: list[AlertSeverity] | None = None, status: list[AlertStatus] | None = None,
               rule_code: list[str] | None = None, start: datetime | None = None, end: datetime | None = None,
               acknowledged_by: uuid.UUID | None = None, escalated: bool | None = None, sort: str = "priority",
               page: int = 1, page_size: int = 50) -> PageResult[Alert]:
        """alert history with filters; scope=None means unrestricted (system use only)"""
        check_range(start, end, 366)
        stmt = select(Alert)
        if scope is not None:
            stmt = stmt.where(Alert.patient_id.in_(scope) if scope else False)
        if patient_id:
            stmt = stmt.where(Alert.patient_id == patient_id)
        if severity:
            stmt = stmt.where(Alert.severity.in_(severity))
        if status:
            stmt = stmt.where(Alert.status.in_(status))
        if rule_code:
            stmt = stmt.join(AlertRule, AlertRule.rule_id == Alert.rule_id).where(AlertRule.rule_code.in_(rule_code))
        if start:
            stmt = stmt.where(Alert.triggered_at >= start)
        if end:
            stmt = stmt.where(Alert.triggered_at < end)
        if acknowledged_by:
            stmt = stmt.where(Alert.acknowledged_by == acknowledged_by)
        if escalated is not None:
            stmt = stmt.where(Alert.escalation_level >= 1 if escalated else Alert.escalation_level == 0)
        order = ((SEVERITY_ORDER.desc(), Alert.triggered_at.desc()) if sort == "priority"
                 else (Alert.triggered_at.asc(),) if sort == "oldest" else (Alert.triggered_at.desc(),))
        return paginate(self.s, stmt.order_by(*order, Alert.alert_id), page, page_size)

    def metrics(self, *, scope: set[uuid.UUID] | None, start: datetime, end: datetime) -> dict[str, Any]:
        """alert volume and response times for a period (counts only; no patient data)"""
        check_range(start, end, 366)
        stmt = select(Alert).where(Alert.triggered_at >= start, Alert.triggered_at < end)
        if scope is not None:
            stmt = stmt.where(Alert.patient_id.in_(scope) if scope else False)
        alerts = list(self.s.scalars(stmt))
        ack = [(a.acknowledged_at - a.triggered_at).total_seconds() / 60 for a in alerts if a.acknowledged_at]
        res = [(a.resolved_at - a.triggered_at).total_seconds() / 60 for a in alerts if a.resolved_at]
        crit_ack = [(a.acknowledged_at - a.triggered_at).total_seconds() / 60 for a in alerts
                    if a.acknowledged_at and a.severity == AlertSeverity.critical]
        notif = Counter()
        if alerts:
            ids = [a.alert_id for a in alerts]
            for ch, st, n in self.s.execute(select(Notification.channel, Notification.status, func.count())
                                            .where(Notification.alert_id.in_(ids))
                                            .group_by(Notification.channel, Notification.status)):
                notif[f"{ch.value}:{st.value}"] = n
        return {
            "start": start, "end": end, "total": len(alerts),
            "by_severity": {s.value: sum(1 for a in alerts if a.severity == s) for s in AlertSeverity},
            "by_status": {s.value: sum(1 for a in alerts if a.status == s) for s in AlertStatus},
            "escalated": sum(1 for a in alerts if a.escalation_level > 0),
            "repeat_occurrences_absorbed": sum(a.occurrences - 1 for a in alerts),
            "minutes_to_acknowledge": _dist(ack), "minutes_to_resolve": _dist(res),
            "critical_minutes_to_acknowledge": _dist(crit_ack),
            "notifications": dict(sorted(notif.items())),
        }

    # ---------------------------------------------------------------- notifications
    def add_notification(self, n: Notification) -> Notification:
        self.s.add(n)
        return n

    def due_notifications(self, now: datetime, limit: int = 200) -> list[Notification]:
        """queued messages whose time has come, critical first"""
        sev = case({"critical": 4, "high": 3, "moderate": 2, "low": 1}, value=Alert.severity)
        return list(self.s.scalars(select(Notification).join(Alert, Alert.alert_id == Notification.alert_id)
                                   .where(Notification.status == NotificationStatus.queued,
                                          Notification.deliver_after <= now)
                                   .order_by(sev.desc(), Notification.queued_at).limit(limit)))

    def notifications_for(self, user_id: uuid.UUID, *, unread_only: bool = False, page: int = 1,
                          page_size: int = 50) -> PageResult[Notification]:
        stmt = select(Notification).where(Notification.recipient_user_id == user_id)
        if unread_only:
            stmt = stmt.where(Notification.read_at.is_(None))
        return paginate(self.s, stmt.order_by(Notification.queued_at.desc()), page, page_size)

    def mark_read(self, notification_id: uuid.UUID, user_id: uuid.UUID, now: datetime | None = None) -> Notification:
        n = self.s.get(Notification, notification_id)
        if n is None or n.recipient_user_id != user_id:
            raise NotFoundError("notification not found")
        if n.read_at is None:
            n.read_at = now or utcnow()
        return n


def ensure_transition(alert: Alert, allowed: tuple[AlertStatus, ...], action: str) -> None:
    if alert.status not in allowed:
        raise ConflictError(f"cannot {action} an alert that is {alert.status.value}")


def _dist(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"n": 0, "median": None, "p90": None, "max": None}
    v = sorted(values)
    p90 = v[min(len(v) - 1, max(0, round(0.9 * len(v)) - 1))]
    return {"n": len(v), "median": round(statistics.median(v), 1), "p90": round(p90, 1), "max": round(v[-1], 1)}


def window(now: datetime, minutes: int) -> datetime:
    return now - timedelta(minutes=minutes)
