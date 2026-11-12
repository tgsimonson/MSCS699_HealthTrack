"""alert worklist, search, history, acknowledgment, resolution, metrics, and notifications"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query

from app.alerts.engine import AlertEngine
from app.alerts.service import alert_event
from app.api.deps import CARE_ROLES, DB, CurrentUser, require_roles
from app.api.responses import AUTHED, R404, R409, R422
from app.config import get_settings
from app.errors import NotFoundError
from app.models import Alert, Notification, User
from app.models.enums import AlertSeverity, AlertStatus, AuditAction, UserRole
from app.realtime.broker import broker
from app.repositories import AuditRepository
from app.repositories.alerts import AlertRepository
from app.schemas.alerts import (AcknowledgeRequest, AlertDetail, AlertMetrics, AlertOut, CommentRequest, JobResult,
                                NotificationOut, ResolveRequest, alert_detail)
from app.schemas.common import Page

router = APIRouter(tags=["Alerts"])
notifications_router = APIRouter(tags=["Notifications"])
MAX = get_settings().max_page_size
CareStaff = Annotated[User, Depends(require_roles(UserRole.clinician, UserRole.physician))]
SCOPED = {**AUTHED, **R404}


def load_scoped_alert(db: DB, user: CareStaff, alert_id: Annotated[uuid.UUID, Path()]) -> Alert:
    """the alert's patient must be on the caller's care team; otherwise 404 (and the denial is audited)"""
    repo = AlertRepository(db)
    alert = repo.get(alert_id)
    if alert.patient_id not in repo.scoped_patient_ids(user):
        AuditRepository(db).record(AuditAction.read, "alerts", actor=user, entity_id=alert_id,
                                   patient_id=alert.patient_id, outcome="denied", details={"reason": "out of scope"})
        db.commit()
        raise NotFoundError("alert not found")
    return alert


ScopedAlert = Annotated[Alert, Depends(load_scoped_alert)]


@router.get("/alerts", response_model=Page[AlertOut], summary="Search alerts (worklist and history)",
            responses={**AUTHED, **R422},
            description="**Roles:** clinician and physician; results are limited to patients on the caller's care "
                        "team. With no filters this is the active worklist (open, acknowledged, escalated) sorted by "
                        "priority: severity first, then newest. Pass `status` to search history, for example "
                        "`status=resolved&start=2026-11-01T00:00:00Z`. Filters combine with AND; repeat a parameter "
                        "to match any of several values (`severity=critical&severity=high`).")
def search_alerts(db: DB, user: CareStaff,
                  patient_id: uuid.UUID | None = None,
                  severity: Annotated[list[AlertSeverity] | None, Query()] = None,
                  status: Annotated[list[AlertStatus] | None, Query()] = None,
                  rule_code: Annotated[list[str] | None, Query(examples=["HR_ABOVE_CEILING"])] = None,
                  start: Annotated[datetime | None, Query(description="triggered at or after")] = None,
                  end: Annotated[datetime | None, Query(description="triggered before")] = None,
                  acknowledged_by: uuid.UUID | None = None,
                  escalated: bool | None = None,
                  sort: Literal["priority", "newest", "oldest"] = "priority",
                  page: Annotated[int, Query(ge=1)] = 1,
                  page_size: Annotated[int, Query(ge=1, le=MAX)] = 50) -> dict:
    repo = AlertRepository(db)
    if status is None and not any([start, end, acknowledged_by, escalated is not None]):
        status = [AlertStatus.open, AlertStatus.acknowledged, AlertStatus.escalated]
    res = repo.search(scope=repo.scoped_patient_ids(user), patient_id=patient_id, severity=severity, status=status,
                      rule_code=rule_code, start=_aware(start), end=_aware(end), acknowledged_by=acknowledged_by,
                      escalated=escalated, sort=sort, page=page, page_size=page_size)
    AuditRepository(db).record(AuditAction.read, "alerts", actor=user, patient_id=patient_id,
                               details={"rows": len(res.items), "search": True})
    return {"items": res.items, "meta": res.meta()}


@router.get("/alerts/metrics", response_model=AlertMetrics, summary="Alert volume and response times",
            responses={**AUTHED, **R422},
            description="**Roles:** clinician and physician (their care-team patients), admin (whole program). "
                        "Counts by severity and status, escalations, repeats absorbed by deduplication, minutes to "
                        "acknowledge and resolve (median, 90th percentile, max), and notification delivery counts. "
                        "Defaults to the last 7 days. Contains no patient-identifying data.")
def alert_metrics(db: DB, user: Annotated[User, Depends(require_roles(UserRole.clinician, UserRole.physician,
                                                                      UserRole.admin))],
                  start: datetime | None = None, end: datetime | None = None) -> dict:
    end = _aware(end) or datetime.now(timezone.utc)
    start = _aware(start) or end - timedelta(days=7)
    repo = AlertRepository(db)
    scope = None if user.role == UserRole.admin else repo.scoped_patient_ids(user)
    return repo.metrics(scope=scope, start=start, end=end)


@router.get("/alerts/{alert_id}", response_model=AlertDetail, summary="Alert detail with full history",
            responses=SCOPED,
            description="**Roles:** clinician and physician (care team). Includes every history event (created, "
                        "repeated, notified, acknowledged, escalated, resolved, comments), each notification with "
                        "its delivery status, and minutes from trigger to acknowledgment, escalation, and resolution.")
def get_alert(db: DB, user: CareStaff, alert: ScopedAlert) -> AlertDetail:
    repo = AlertRepository(db)
    notes = list(db.query(Notification).filter(Notification.alert_id == alert.alert_id)
                 .order_by(Notification.queued_at))
    AuditRepository(db).record(AuditAction.read, "alerts", actor=user, entity_id=alert.alert_id,
                               patient_id=alert.patient_id)
    return alert_detail(alert, repo.events(alert.alert_id), notes)


@router.post("/alerts/{alert_id}/acknowledge", response_model=AlertOut, summary="Acknowledge an alert",
             responses={**SCOPED, **R409},
             description="**Roles:** clinician and physician (care team). Records who took ownership and when, and "
                         "stops further escalation. Allowed from `open` or `escalated`; otherwise 409. Patients and "
                         "administrators cannot acknowledge.")
def acknowledge(body: AcknowledgeRequest, db: DB, user: CareStaff, alert: ScopedAlert) -> Alert:
    AlertEngine(db).acknowledge(alert, user, body.note)
    AuditRepository(db).record(AuditAction.update, "alerts", actor=user, entity_id=alert.alert_id,
                               patient_id=alert.patient_id, details={"changed_columns": ["status", "acknowledged_at"]})
    db.commit()
    broker.publish(alert_event(alert, "acknowledged"))
    return alert


@router.post("/alerts/{alert_id}/resolve", response_model=AlertOut, summary="Resolve an alert with a note",
             responses={**SCOPED, **R409, **R422},
             description="**Roles:** clinician and physician (care team). A resolution note is required. Resolving an "
                         "unacknowledged alert also records the acknowledgment.")
def resolve(body: ResolveRequest, db: DB, user: CareStaff, alert: ScopedAlert) -> Alert:
    AlertEngine(db).resolve(alert, user, body.note)
    AuditRepository(db).record(AuditAction.update, "alerts", actor=user, entity_id=alert.alert_id,
                               patient_id=alert.patient_id, details={"changed_columns": ["status", "resolved_at"]})
    db.commit()
    broker.publish(alert_event(alert, "resolved"))
    return alert


@router.post("/alerts/{alert_id}/comments", response_model=AlertDetail, status_code=201, summary="Add a note",
             responses=SCOPED, description="**Roles:** clinician and physician (care team). Adds a comment event to "
                                           "the alert history without changing its status.")
def comment(body: CommentRequest, db: DB, user: CareStaff, alert: ScopedAlert) -> AlertDetail:
    repo = AlertRepository(db)
    AlertEngine(db).comment(alert, user, body.note)
    AuditRepository(db).record(AuditAction.update, "alerts", actor=user, entity_id=alert.alert_id,
                               patient_id=alert.patient_id, details={"comment": True})
    db.flush()
    notes = list(db.query(Notification).filter(Notification.alert_id == alert.alert_id))
    return alert_detail(alert, repo.events(alert.alert_id), notes)


@router.post("/alerts/jobs/{job}", response_model=JobResult, summary="Run an alert job now",
             responses={**AUTHED, **R422},
             description="**Roles:** admin and IT admin. Runs a background job immediately instead of waiting for "
                         "its schedule: `patterns` (trend and data-gap rules for every active patient), "
                         "`escalations` (raise unacknowledged alerts past their timeout), or `dispatch` (send due "
                         "notifications). Used for demonstrations and operations.")
def run_job(job: Literal["patterns", "escalations", "dispatch"], db: DB,
            user: Annotated[User, Depends(require_roles(UserRole.admin, UserRole.it_admin))]) -> JobResult:
    from app.alerts.notifications import Dispatcher
    from app.alerts.service import publish_outcomes
    now = datetime.now(timezone.utc)
    if job == "patterns":
        outcomes = AlertEngine(db).evaluate_patterns(now=now)
        db.commit()
        publish_outcomes(outcomes)
        created = [o for o in outcomes if o.action == "created"]
        result = JobResult(job=job, affected=len(created),
                           details={"evaluated_outcomes": len(outcomes),
                                    "suppressed": sum(1 for o in outcomes if o.action == "suppressed")})
    elif job == "escalations":
        escalated = AlertEngine(db).run_escalations(now)
        db.commit()
        for a in escalated:
            broker.publish(alert_event(a, "escalated"))
        result = JobResult(job=job, affected=len(escalated))
    else:
        stats = Dispatcher(db).dispatch_due(now)
        db.commit()
        result = JobResult(job=job, affected=stats["sent"], details=stats)
    AuditRepository(db).record(AuditAction.update, "alert_jobs", actor=user, details={"job": job,
                                                                                      "affected": result.affected})
    return result


# ---------------------------------------------------------------- notifications for the current user
@notifications_router.get("/notifications", response_model=Page[NotificationOut], summary="My notifications",
                          responses=AUTHED,
                          description="**Roles:** clinician and physician. Notifications addressed to the caller on "
                                      "any channel, newest first. The dashboard uses this to show unread alerts "
                                      "after a reconnect.")
def my_notifications(db: DB, user: CareStaff, unread_only: bool = False, page: Annotated[int, Query(ge=1)] = 1,
                     page_size: Annotated[int, Query(ge=1, le=MAX)] = 50) -> dict:
    res = AlertRepository(db).notifications_for(user.user_id, unread_only=unread_only, page=page, page_size=page_size)
    return {"items": res.items, "meta": res.meta()}


@notifications_router.post("/notifications/{notification_id}/read", response_model=NotificationOut,
                           summary="Mark a notification read", responses=SCOPED,
                           description="**Roles:** the recipient only.")
def mark_read(notification_id: uuid.UUID, db: DB, user: CurrentUser) -> Notification:
    if user.role not in CARE_ROLES:
        raise NotFoundError("notification not found")
    return AlertRepository(db).mark_read(notification_id, user.user_id)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
