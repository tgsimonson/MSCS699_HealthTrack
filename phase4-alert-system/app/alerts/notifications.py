"""notification payloads, channel adapters, and the outbox dispatcher

payload design: the stored payload (notifications.payload) holds the full alert context for the dashboard, which
is an authenticated, care-team-scoped channel. email and sms are not secure channels, so their rendered text
follows the hipaa minimum-necessary idea: severity, rule name, and a link that requires login. no patient name,
mrn, or measured value leaves the system by email or sms.

delivery: each adapter raises DeliveryError on failure. the dispatcher retries with backoff (15 s, 30 s) and marks
the notification failed after notification_max_attempts. low-severity email is grouped into one digest per
recipient per day, and an alert storm (too many non-critical alerts for one patient in an hour) moves email and
sms into the same digest.
"""
from __future__ import annotations

import json
import smtplib
import threading
import urllib.request
from collections import defaultdict
from datetime import datetime, time, timedelta
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.logging_config import get_logger
from app.models import Alert, Notification, User
from app.models.enums import AlertEventType, NotificationChannel, NotificationStatus
from app.realtime.broker import Broker, broker as default_broker
from app.repositories.alerts import AlertRepository

log = get_logger("alerts.notify")
SEVERITY_TAG = {"critical": "CRITICAL", "high": "HIGH", "moderate": "MODERATE", "low": "LOW"}


class DeliveryError(Exception):
    pass


# ---------------------------------------------------------------- payload
def build_payload(alert: Alert, level: int, settings: Settings | None = None) -> dict[str, Any]:
    s = settings or get_settings()
    return {
        "schema": "healthtrack.alert-notification/1",
        "alert_id": str(alert.alert_id),
        "patient_id": str(alert.patient_id),
        "severity": alert.severity.value,
        "rule_code": alert.rule.rule_code,
        "rule_name": alert.rule.name,
        "title": alert.title,
        "status": alert.status.value,
        "triggering_values": alert.triggering_values,
        "threshold_applied": alert.threshold_applied,
        "threshold_source": alert.threshold_source,
        "triggered_at": alert.triggered_at.isoformat(),
        "escalation_level": level,
        "links": {"dashboard": f"{s.dashboard_url}/?alert={alert.alert_id}",
                  "api": f"/api/v1/alerts/{alert.alert_id}"},
    }


def next_digest_time(now: datetime, settings: Settings | None = None) -> datetime:
    s = settings or get_settings()
    tz = ZoneInfo(s.program_timezone)
    local = now.astimezone(tz)
    at = datetime.combine(local.date(), time(s.digest_hour), tz)
    if at <= local:
        at += timedelta(days=1)
    return at.astimezone(now.tzinfo)


def render_text(payload: dict[str, Any]) -> tuple[str, str]:
    """subject and body for email/sms: minimum necessary, no identifiers or measured values"""
    tag = SEVERITY_TAG[payload["severity"]]
    level = payload.get("escalation_level", 0)
    esc = f" (escalation level {level})" if level else ""
    subject = f"HealthTrack {tag} alert{esc}: {payload['rule_name']}"
    body = (f"{subject}.\nA patient on your care team needs review. Sign in to view and acknowledge:\n"
            f"{payload['links']['dashboard']}\nThis message contains no patient details. Do not reply.")
    return subject, body


def render_digest(payloads: list[dict[str, Any]]) -> tuple[str, str]:
    subject = f"HealthTrack digest: {len(payloads)} lower-priority alert{'s' if len(payloads) != 1 else ''}"
    lines = [f"- {SEVERITY_TAG[p['severity']]}: {p['rule_name']}  {p['links']['dashboard']}" for p in payloads]
    return subject, subject + "\nSign in to review:\n" + "\n".join(lines)


# ---------------------------------------------------------------- adapters
class Channel(Protocol):
    channel: NotificationChannel

    def send(self, recipient: User, subject: str, body: str, payload: dict[str, Any]) -> bool:
        """deliver one message; return True if delivery is confirmed, raise DeliveryError on failure"""


class _Outbox:
    _lock = threading.Lock()

    def __init__(self, settings: Settings, name: str) -> None:
        self.path = Path(settings.outbox_dir) / f"{name}.jsonl"

    def write(self, record: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")


class DashboardChannel:
    """pushes the full payload to the recipient's open dashboard sessions over the websocket"""

    channel = NotificationChannel.dashboard

    def __init__(self, bus: Broker | None = None) -> None:
        self.bus = bus or default_broker

    def send(self, recipient: User, subject: str, body: str, payload: dict[str, Any]) -> bool:
        delivered = self.bus.publish({"type": "notification", "user_id": str(recipient.user_id),
                                      "data": {**payload, "subject": subject}})
        return delivered > 0          # stored either way; the dashboard also lists unread notifications


class EmailChannel:
    channel = NotificationChannel.email

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.outbox = _Outbox(self.settings, "email")

    def send(self, recipient: User, subject: str, body: str, payload: dict[str, Any]) -> bool:
        s = self.settings
        if not s.smtp_host:
            self.outbox.write({"to": recipient.email, "subject": subject, "body": body,
                               "alert_id": payload.get("alert_id")})
            return False
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = s.smtp_from, recipient.email, subject
        msg.set_content(body)
        try:
            with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=10) as smtp:
                smtp.starttls()
                smtp.send_message(msg)
        except (OSError, smtplib.SMTPException) as exc:
            raise DeliveryError(f"smtp: {exc.__class__.__name__}") from exc
        return False


class SmsChannel:
    channel = NotificationChannel.sms

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.outbox = _Outbox(self.settings, "sms")

    def send(self, recipient: User, subject: str, body: str, payload: dict[str, Any]) -> bool:
        if not recipient.phone:
            raise DeliveryError("recipient has no phone number")
        text = f"{subject}. Review: {payload['links']['dashboard']}"[:320]
        if not self.settings.sms_webhook_url:
            self.outbox.write({"to": recipient.phone, "text": text, "alert_id": payload.get("alert_id")})
            return False
        req = urllib.request.Request(self.settings.sms_webhook_url, method="POST",
                                     data=json.dumps({"to": recipient.phone, "text": text}).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 - url comes from configuration
                if resp.status >= 300:
                    raise DeliveryError(f"sms gateway returned {resp.status}")
        except OSError as exc:
            raise DeliveryError(f"sms gateway: {exc.__class__.__name__}") from exc
        return False


def default_channels(settings: Settings | None = None, bus: Broker | None = None) -> dict[NotificationChannel, Channel]:
    return {NotificationChannel.dashboard: DashboardChannel(bus), NotificationChannel.email: EmailChannel(settings),
            NotificationChannel.sms: SmsChannel(settings)}


# ---------------------------------------------------------------- dispatcher
class Dispatcher:
    def __init__(self, session: Session, channels: dict[NotificationChannel, Channel] | None = None,
                 settings: Settings | None = None) -> None:
        self.s = session
        self.settings = settings or get_settings()
        self.channels = channels or default_channels(self.settings)
        self.repo = AlertRepository(session)

    def dispatch_due(self, now: datetime) -> dict[str, int]:
        """send every queued notification that is due: individual messages first, then grouped digests"""
        stats = {"sent": 0, "failed": 0, "retry": 0, "digests": 0}
        self.s.flush()                       # sessions here do not autoflush; make earlier status changes visible
        due = [n for n in self.repo.due_notifications(now) if n.status == NotificationStatus.queued]
        digests: dict[tuple, list[Notification]] = defaultdict(list)
        for n in due:
            if n.is_digest:
                digests[(n.recipient_user_id, n.channel)].append(n)
                continue
            subject, body = render_text(n.payload)
            self._attempt([n], subject, body, n.payload, now, stats)
        for (_, _channel), group in digests.items():
            subject, body = render_digest([g.payload for g in group])
            self._attempt(group, subject, body, group[0].payload, now, stats)
            stats["digests"] += 1
        if due:
            log.info("notifications dispatched", extra={"ctx": stats})
        return stats

    def _attempt(self, group: list[Notification], subject: str, body: str, payload: dict[str, Any],
                 now: datetime, stats: dict[str, int]) -> None:
        first = group[0]
        recipient = self.s.get(User, first.recipient_user_id)
        adapter = self.channels[first.channel]
        try:
            if recipient is None or not recipient.is_active:
                raise DeliveryError("recipient account inactive")
            confirmed = adapter.send(recipient, subject, body, payload)
        except DeliveryError as exc:
            for n in group:
                n.attempts += 1
                if n.attempts >= self.settings.notification_max_attempts:
                    n.status, n.failure_reason = NotificationStatus.failed, str(exc)[:255]
                    stats["failed"] += 1
                else:
                    n.deliver_after = now + timedelta(seconds=15 * 2 ** (n.attempts - 1))
                    stats["retry"] += 1
            log.warning("notification delivery failed", extra={"ctx": {"channel": first.channel.value,
                                                                       "error": str(exc), "count": len(group)}})
            return
        for n in group:
            n.attempts += 1
            n.status, n.sent_at = NotificationStatus.sent, now
            if confirmed:
                n.status, n.delivered_at = NotificationStatus.delivered, now
            self.repo.add_event(n.alert, AlertEventType.notified, at=now,
                                payload={"channel": n.channel.value, "recipient_user_id": str(n.recipient_user_id),
                                         "level": n.escalation_level, "digest": n.is_digest,
                                         "notification_id": str(n.notification_id)})
            stats["sent"] += 1
