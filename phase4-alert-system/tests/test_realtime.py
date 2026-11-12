"""live stream: websocket authentication, push latency, care-team scope, subscriptions, notifications, workers"""
from __future__ import annotations

import asyncio
import time

import pytest
from sqlalchemy import select
from starlette.websockets import WebSocketDisconnect

from app.alerts.engine import AlertEngine
from app.alerts.notifications import Dispatcher
from app.alerts.workers import AlertWorkers
from app.models import Notification
from app.models.enums import NotificationStatus, ReadingContext
from app.realtime.broker import Broker, broker
from app.realtime.tickets import TicketStore
from app.repositories.alerts import AlertRepository
from tests.conftest import NOW, add_vitals, ago, auth_header

API = "/api/v1"
sc = pytest.mark.scenario


def ticket(client, db, user) -> str:
    r = client.post(f"{API}/stream/ticket", headers=auth_header(db, user))
    assert r.status_code == 200 and r.json()["url"].endswith("/api/v1/stream")
    return r.json()["ticket"]


def connect(client, db, user):
    ws = client.websocket_connect(f"{API}/stream").__enter__()
    ws.send_json({"type": "auth", "ticket": ticket(client, db, user)})
    ready = ws.receive_json()
    assert ready["type"] == "ready"
    return ws, ready


def post_hr(client, db, w, who, values, ctx="exercise", key="rt"):
    body = {"readings": [{"recorded_at": ago(seconds=60 - 10 * i).isoformat(), "context": ctx, "heart_rate": v,
                          "device_id": str(w["band" if who == "robert" else "thomas_band"].device_id),
                          "idempotency_key": f"{key}-{who}-{i:04d}"} for i, v in enumerate(values)]}
    login = w["robert_login"] if who == "robert" else w["marcus"]
    return client.post(f"{API}/patients/{w[who].patient_id}/vitals/batch", headers=auth_header(db, login), json=body)


def next_of(ws, kind, limit=50):
    for _ in range(limit):
        msg = ws.receive_json()
        if msg["type"] == kind:
            return msg
    raise AssertionError(f"no {kind} event")


@sc("AS-42", "A dashboard connected with a ticket receives the new readings and the critical alert pushed over the "
             "websocket within the 5-second target", "FR-18, NFR-07")
def test_push_reading_and_alert(client, db, alert_world):
    w = alert_world
    ws, ready = connect(client, db, w["dana"])
    assert set(ready["patients"]) == {str(w["robert"].patient_id), str(w["linda"].patient_id)}
    started = time.perf_counter()
    assert post_hr(client, db, w, "robert", [131, 136]).json()["alerts_raised"] == 1
    vital = next_of(ws, "vital")
    alert = next_of(ws, "alert")
    elapsed = time.perf_counter() - started
    assert vital["patient_id"] == str(w["robert"].patient_id) and vital["data"]["heart_rate"] == 131
    assert alert["action"] == "created" and alert["data"]["severity"] == "critical"
    assert alert["data"]["rule_code"] == "HR_ABOVE_CEILING" and elapsed < 5
    ws.__exit__(None, None, None)


@sc("AS-43", "Tickets are single-use; a reused or invalid ticket and a wrong origin are refused", "NFR-03")
def test_ticket_rules(client, db, alert_world):
    w = alert_world
    t = ticket(client, db, w["dana"])
    with client.websocket_connect(f"{API}/stream") as ws:
        ws.send_json({"type": "auth", "ticket": t})
        assert ws.receive_json()["type"] == "ready"
    with client.websocket_connect(f"{API}/stream") as ws:
        ws.send_json({"type": "auth", "ticket": t})
        assert ws.receive_json() == {"type": "error", "detail": "authentication failed"}
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 4401
    with pytest.raises(WebSocketDisconnect) as exc, \
            client.websocket_connect(f"{API}/stream", headers={"origin": "https://evil.example"}) as ws:
        ws.receive_json()
    assert exc.value.code == 4403
    assert client.post(f"{API}/stream/ticket", headers=auth_header(db, w["robert_login"])).status_code == 403
    store = TicketStore()
    value, _ = store.issue(w["dana"].user_id, w["dana"].user_id, ttl_seconds=0)
    assert store.redeem(value) is None                                            # expired


def test_access_token_auth_for_non_browser_clients(client, db, alert_world):
    token = auth_header(db, alert_world["raman"])["Authorization"].split()[1]
    with client.websocket_connect(f"{API}/stream") as ws:
        ws.send_json({"type": "auth", "token": token})
        assert ws.receive_json()["role"] == "physician"
    with client.websocket_connect(f"{API}/stream") as ws:
        ws.send_json({"type": "auth", "token": "not-a-jwt"})
        assert ws.receive_json()["type"] == "error"


@sc("AS-44", "Events are filtered by care team: a clinician never receives another team's patient", "NFR-04")
def test_scope_filtering(client, db, alert_world):
    w = alert_world
    ws, ready = connect(client, db, w["marcus"])
    assert ready["patients"] == [str(w["thomas"].patient_id)]
    post_hr(client, db, w, "robert", [131, 136])              # dana's patient
    post_hr(client, db, w, "thomas", [101])                   # marcus's patient
    first = ws.receive_json()
    assert first["type"] == "vital" and first["patient_id"] == str(w["thomas"].patient_id)
    ws.__exit__(None, None, None)


@sc("AS-45", "Subscribing to one patient narrows reading events, while alerts still arrive for every patient in "
             "scope", "FR-18")
def test_subscription_narrows_vitals(client, db, alert_world):
    w = alert_world
    ws, _ = connect(client, db, w["dana"])
    ws.send_json({"type": "subscribe", "patient_ids": [str(w["linda"].patient_id)]})
    time.sleep(0.05)
    post_hr(client, db, w, "robert", [131, 136])
    first = ws.receive_json()
    assert first["type"] == "alert" and first["patient_id"] == str(w["robert"].patient_id)
    ws.__exit__(None, None, None)


@sc("AS-46", "Dashboard notifications go only to their recipient's open sessions", "FR-13")
def test_notification_goes_to_recipient(client, db, alert_world):
    w = alert_world
    dana, _ = connect(client, db, w["dana"])
    raman, _ = connect(client, db, w["raman"])
    vitals = add_vitals(db, w["robert"], [(2, ReadingContext.exercise, {"heart_rate": 133}),
                                          (1, ReadingContext.exercise, {"heart_rate": 138})], now=NOW)
    AlertEngine(db).evaluate_readings(w["robert"].patient_id, vitals, now=NOW)
    Dispatcher(db).dispatch_due(NOW)
    db.flush()
    note = dana.receive_json()
    assert note["type"] == "notification" and note["data"]["rule_code"] == "HR_ABOVE_CEILING"
    dash = db.scalar(select(Notification).where(Notification.channel == "dashboard"))
    assert dash.status == NotificationStatus.delivered                       # a live session received it
    broker.publish({"type": "vital", "patient_id": str(w["linda"].patient_id), "data": {"marker": True}})
    assert raman.receive_json()["data"] == {"marker": True}                  # raman got no notification first
    dana.__exit__(None, None, None)
    raman.__exit__(None, None, None)


def test_broker_drops_oldest_for_slow_clients(alert_world):
    async def main() -> tuple[int, list[int]]:
        bus = Broker(queue_size=3)
        sub = bus.subscribe(alert_world["dana"].user_id, {alert_world["robert"].patient_id})
        for i in range(5):
            bus.publish({"type": "vital", "patient_id": str(alert_world["robert"].patient_id), "data": {"i": i}})
        await asyncio.sleep(0.01)
        got = [sub.queue.get_nowait()["data"]["i"] for _ in range(sub.queue.qsize())]
        bus.unsubscribe(sub)
        return sub.dropped, got

    dropped, got = asyncio.run(main())
    assert dropped == 2 and got == [2, 3, 4]


@sc("AS-52", "Background workers send queued notifications as soon as they are woken, without waiting for the poll "
             "interval", "NFR-07")
def test_workers_dispatch_on_wake(db, alert_world):
    from contextlib import contextmanager
    w = alert_world
    vitals = add_vitals(db, w["robert"], [(2, ReadingContext.exercise, {"heart_rate": 133}),
                                          (1, ReadingContext.exercise, {"heart_rate": 138})], now=ago(seconds=0))
    AlertEngine(db).evaluate_readings(w["robert"].patient_id, vitals)
    db.commit()

    @contextmanager
    def factory():
        yield db

    async def main() -> float:
        wk = AlertWorkers()
        await wk.start(factory)
        started = time.perf_counter()
        wk.wake()
        while wk.runs["dispatch"] == 0 and time.perf_counter() - started < 3:
            await asyncio.sleep(0.005)
        elapsed = time.perf_counter() - started
        await wk.stop()
        return elapsed

    elapsed = asyncio.run(main())
    statuses = {n.status for n in db.scalars(select(Notification))}
    assert statuses == {NotificationStatus.sent} and elapsed < 1.0
    assert AlertRepository(db).search(scope=None).total_items == 1
