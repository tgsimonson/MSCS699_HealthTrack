"""notification payloads, channel adapters, delivery logging, retries, digests, and priority ordering"""
from __future__ import annotations

import json
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.alerts.engine import AlertEngine
from app.alerts.notifications import (DashboardChannel, DeliveryError, Dispatcher, EmailChannel, SmsChannel,
                                      build_payload, render_digest, render_text)
from app.config import Settings
from app.models import Notification
from app.models.alerting import REQUIRED_PAYLOAD_KEYS
from app.models.enums import AlertEventType, NotificationChannel, NotificationStatus, ReadingContext
from app.realtime.broker import Broker
from app.repositories.alerts import AlertRepository
from tests.conftest import NOW, add_vitals

EX = ReadingContext.exercise
sc = pytest.mark.scenario


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv("HT_OUTBOX_DIR", str(tmp_path / "outbox"))
    return Settings()


def critical(db, w, now=NOW):
    vitals = add_vitals(db, w["robert"], [(2, EX, {"heart_rate": 133}), (1, EX, {"heart_rate": 138})], now=now)
    [o] = [x for x in AlertEngine(db).evaluate_readings(w["robert"].patient_id, vitals, now=now)
           if x.action == "created"]
    db.flush()
    return o.alert


def notes(db, alert):
    db.flush()
    return list(db.scalars(select(Notification).where(Notification.alert_id == alert.alert_id)))


class FlakySms:
    channel = NotificationChannel.sms

    def __init__(self) -> None:
        self.calls = 0

    def send(self, recipient, subject, body, payload) -> bool:  # noqa: ANN001
        self.calls += 1
        raise DeliveryError("gateway timeout")


@sc("AS-24", "Notification payload carries alert id, patient id, severity, rule, triggering values, and time; email "
             "and SMS text carry no patient name, MRN, or measured values", "FR-13, NFR-06")
def test_payload_and_minimum_necessary(db, alert_world):
    w = alert_world
    alert = critical(db, w)
    p = build_payload(alert, 0)
    assert set(REQUIRED_PAYLOAD_KEYS) <= set(p) and p["triggering_values"]["values"] == [133, 138]
    assert p["links"]["dashboard"].endswith(f"?alert={alert.alert_id}")
    subject, body = render_text(p)
    for secret in (w["robert"].first_name, w["robert"].last_name, w["robert"].mrn, "138", "133", "128"):
        assert secret not in subject + body
    assert subject == "HealthTrack CRITICAL alert: Heart rate above prescribed ceiling"


@sc("AS-25", "Dispatch sends every due message, logs a 'notified' history event per delivery, and writes email and "
             "SMS to the outbox when no gateway is configured", "FR-13")
def test_dispatch_logs_delivery(db, alert_world, settings):
    alert = critical(db, alert_world)
    stats = Dispatcher(db, settings=settings).dispatch_due(NOW)
    assert stats == {"sent": 3, "failed": 0, "retry": 0, "digests": 0}
    assert {n.status for n in notes(db, alert)} == {NotificationStatus.sent}
    events = [e for e in AlertRepository(db).events(alert.alert_id) if e.event_type == AlertEventType.notified]
    assert sorted(e.payload["channel"] for e in events) == ["dashboard", "email", "sms"]
    outbox = settings.outbox_dir
    sms = [json.loads(x) for x in open(f"{outbox}/sms.jsonl")]
    mail = [json.loads(x) for x in open(f"{outbox}/email.jsonl")]
    assert sms[0]["to"] == alert_world["dana"].phone and mail[0]["to"] == alert_world["dana"].email
    assert Dispatcher(db, settings=settings).dispatch_due(NOW)["sent"] == 0          # nothing sent twice


@sc("AS-26", "A failing channel retries with backoff (15 s, then 30 s) and is marked failed with a reason after 3 "
             "attempts, without blocking other channels", "FR-13")
def test_retry_then_fail(db, alert_world, settings):
    alert = critical(db, alert_world)
    flaky = FlakySms()
    chans = {NotificationChannel.dashboard: DashboardChannel(Broker()), NotificationChannel.email:
             EmailChannel(settings), NotificationChannel.sms: flaky}
    d = Dispatcher(db, channels=chans, settings=settings)
    assert d.dispatch_due(NOW) == {"sent": 2, "failed": 0, "retry": 1, "digests": 0}
    sms = next(n for n in notes(db, alert) if n.channel == NotificationChannel.sms)
    assert sms.deliver_after == NOW + timedelta(seconds=15) and sms.attempts == 1
    assert d.dispatch_due(NOW + timedelta(seconds=10))["retry"] == 0                  # not due yet
    assert d.dispatch_due(NOW + timedelta(seconds=15))["retry"] == 1
    assert sms.deliver_after == NOW + timedelta(seconds=45)
    assert d.dispatch_due(NOW + timedelta(seconds=45))["failed"] == 1
    assert (sms.status, sms.failure_reason, flaky.calls) == (NotificationStatus.failed, "gateway timeout", 3)


@sc("AS-27", "Low-severity email is held for the morning digest and several alerts go out as one message per "
             "recipient", "FR-12")
def test_digest_groups_messages(db, alert_world, settings):
    w = alert_world
    repo, eng = AlertRepository(db), AlertEngine(db)
    for p in ("robert", "linda"):
        eng.raise_alert(w[p].patient_id, repo.get_rule("DATA_GAP"), title="No readings for 60 hours",
                        triggering={"value": 60}, threshold=48, source="default", now=NOW)
    db.flush()
    stats = Dispatcher(db, settings=settings).dispatch_due(NOW)
    assert stats["sent"] == 2 and stats["digests"] == 0                 # dashboard now, email waits
    morning = NOW + timedelta(hours=21)                                 # 2026-11-13 07:00 Denver
    stats = Dispatcher(db, settings=settings).dispatch_due(morning)
    assert stats == {"sent": 2, "failed": 0, "retry": 0, "digests": 1}  # both alerts, one email to dana
    [line] = open(f"{settings.outbox_dir}/email.jsonl").read().splitlines()
    assert json.loads(line)["subject"] == "HealthTrack digest: 2 lower-priority alerts"


@sc("AS-23", "Critical notifications are dispatched before lower-priority ones that were queued earlier", "FR-12")
def test_critical_first(db, alert_world):
    w = alert_world
    repo = AlertRepository(db)
    AlertEngine(db).raise_alert(w["linda"].patient_id, repo.get_rule("RESTING_HR_HIGH"), title="m", triggering={},
                                threshold=100, source="default", now=NOW - timedelta(minutes=5))
    critical(db, w)
    due = repo.due_notifications(NOW)
    first_moderate = next(i for i, n in enumerate(due) if n.alert.severity.value == "moderate")
    assert all(n.alert.severity.value == "critical" for n in due[:first_moderate])


def test_dashboard_channel_targets_one_user(db, alert_world):
    bus = Broker()
    alert = critical(db, alert_world)
    ch = DashboardChannel(bus)
    assert ch.send(alert_world["dana"], "s", "b", build_payload(alert, 0)) is False        # nobody connected


@sc("AS-28", "SMS needs a phone number on the recipient account, and the digest message lists each alert with its "
             "sign-in link", "FR-13")
def test_sms_requires_phone_and_digest_text(db, alert_world, settings):
    alert = critical(db, alert_world)
    with pytest.raises(DeliveryError):
        SmsChannel(settings).send(alert_world["linda_login"], "s", "b", build_payload(alert, 0))
    subject, body = render_digest([build_payload(alert, 0)])
    assert subject == "HealthTrack digest: 1 lower-priority alert" and str(alert.alert_id) in body
