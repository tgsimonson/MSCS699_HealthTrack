"""live updates: websocket stream, ticket issuing, and the monitoring worklist the dashboard starts from

protocol (json text frames):
  client -> {"type": "auth", "ticket": "wst_..."}         first frame, within 10 s (or "token": access token)
  server -> {"type": "ready", "user_id", "role", "patients": [...], "server_time"}
  client -> {"type": "subscribe", "patient_ids": [...]}   optional: readings only for these patients (alerts still
                                                          arrive for every patient in scope); [] or null resets
  server -> {"type": "vital" | "alert" | "activity" | "notification", "patient_id"?, "data", "published_at"}
  server -> {"type": "ping"} every 20 s; client may reply {"type": "pong"}
close codes: 4401 authentication failed, 4403 origin not allowed, 1000 normal.
"""
from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Request, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool

from app.api.deps import DB, CurrentUser, require_roles
from app.api.responses import AUTHED
from app.config import get_settings
from app.db import get_session_factory
from app.errors import HealthTrackError
from app.logging_config import get_logger
from app.models import Patient, User
from app.models.enums import AuditAction, ProgramStatus, UserRole
from app.realtime.broker import broker
from app.realtime.tickets import tickets
from app.repositories import AuditRepository, UserRepository, VitalSignRepository
from app.repositories.alerts import AlertRepository
from app.schemas.alerts import AlertOut, StreamTicket, WorklistRow
from app.security import decode_access_token

router = APIRouter(tags=["Live Stream"])
log = get_logger("api.stream")
HEARTBEAT_SECONDS = 20
SCOPE_REFRESH_SECONDS = 60
CareStaff = Annotated[User, Depends(require_roles(UserRole.clinician, UserRole.physician))]


@router.post("/stream/ticket", response_model=StreamTicket, summary="Get a one-time websocket ticket",
             responses=AUTHED,
             description="**Roles:** clinician and physician. Returns a single-use ticket valid for 60 seconds. "
                         "Send it as the first websocket frame `{\"type\": \"auth\", \"ticket\": \"...\"}`. Tickets "
                         "keep access tokens out of browser code and out of urls.")
def stream_ticket(request: Request, user: CareStaff) -> StreamTicket:
    value, ttl = tickets.issue(user.user_id, request.state.session_id, get_settings().stream_ticket_seconds)
    base = str(request.base_url).replace("http", "ws", 1).rstrip("/")
    return StreamTicket(ticket=value, expires_in=ttl, url=f"{base}/api/v1/stream")


@router.get("/monitoring/worklist", response_model=list[WorklistRow], summary="Monitoring worklist",
            responses=AUTHED,
            description="**Roles:** clinician and physician. One row per active or paused patient on the caller's "
                        "care team: latest valid heart rate, blood pressure, and SpO2, active alert counts by "
                        "severity, the highest-priority alert, and the prescription zone. Sorted by priority "
                        "(critical first), then by the most recent alert. The dashboard loads this once and then "
                        "applies websocket events.")
def worklist(db: DB, user: CareStaff) -> list[WorklistRow]:
    return build_worklist(db, user)


def build_worklist(db, user: User) -> list[WorklistRow]:  # noqa: ANN001
    repo, vitals = AlertRepository(db), VitalSignRepository(db)
    scope = repo.scoped_patient_ids(user)
    patients = [p for p in db.query(Patient).filter(Patient.patient_id.in_(scope), Patient.deleted_at.is_(None))
                if p.program_status in (ProgramStatus.active, ProgramStatus.paused)] if scope else []
    alerts = repo.active_for_patients({p.patient_id for p in patients})
    rows = []
    for p in patients:
        mine = [a for a in alerts if a.patient_id == p.patient_id]
        latest = vitals.latest(p.patient_id)
        rx = repo.current_prescription(p.patient_id)
        lv = {}
        for key, v in latest.items():
            if v is None:
                lv[key] = None
            else:
                value = f"{v.systolic_bp}/{v.diastolic_bp}" if key == "blood_pressure" else getattr(v, key)
                lv[key] = {"value": value, "recorded_at": v.recorded_at, "context": v.context}
        rows.append(WorklistRow(
            patient_id=p.patient_id, mrn=p.mrn, first_name=p.first_name, last_name=p.last_name,
            clinical_risk_category=p.clinical_risk_category.value, program_status=p.program_status.value,
            latest=lv, last_reading_at=vitals.last_reading_at(p.patient_id),
            active_alerts={s: sum(1 for a in mine if a.severity.value == s) for s in ("critical", "high", "moderate",
                                                                                      "low")},
            top_alert=AlertOut.model_validate(mine[0]) if mine else None,
            priority=mine[0].severity.rank if mine else 0,
            prescription={k: getattr(rx, k) for k in ("target_hr_min", "target_hr_max", "hr_ceiling", "min_spo2",
                                                      "max_exercise_sbp", "resting_hr_baseline")} if rx else None))
    rows.sort(key=lambda r: (-r.priority, -(r.top_alert.triggered_at.timestamp() if r.top_alert else 0),
                             r.last_name))
    AuditRepository(db).record(AuditAction.read, "worklist", actor=user, details={"patients": len(rows)})
    return rows


# ---------------------------------------------------------------- websocket
def _authenticate(factory: Callable, message: dict) -> tuple[uuid.UUID, str, set[uuid.UUID]] | None:
    """runs in a worker thread: validates a ticket or access token and loads the caller's patient scope"""
    with factory() as db:
        users = UserRepository(db)
        if message.get("ticket"):
            t = tickets.redeem(str(message["ticket"]))
            if t is None:
                return None
            user_id, session_id = t.user_id, t.session_id
        elif message.get("token"):
            try:
                claims = decode_access_token(str(message["token"]))
                user_id, session_id = uuid.UUID(claims["sub"]), uuid.UUID(claims["sid"])
            except (HealthTrackError, KeyError, ValueError):
                return None
        else:
            return None
        user = db.get(User, user_id)
        sess = users.get_session(session_id)
        if (user is None or not user.is_active or sess is None or sess.revoked_at is not None
                or user.role not in (UserRole.clinician, UserRole.physician)):
            return None
        scope = AlertRepository(db).scoped_patient_ids(user)
        AuditRepository(db).record(AuditAction.read, "stream", actor=user, details={"patients": len(scope)})
        db.commit()
        return user.user_id, user.role.value, scope


def _scope_for(factory: Callable, user_id: uuid.UUID) -> set[uuid.UUID]:
    with factory() as db:
        user = db.get(User, user_id)
        return AlertRepository(db).scoped_patient_ids(user) if user and user.is_active else set()


def _origin_allowed(ws: WebSocket) -> bool:
    origin = ws.headers.get("origin")
    if origin is None:                   # non-browser clients (device gateways, tests) send no origin
        return True
    host = ws.headers.get("host", "")
    return origin in get_settings().cors_origins or origin.split("://", 1)[-1] == host


@router.websocket("/stream")
async def stream(ws: WebSocket, factory: Annotated[Callable, Depends(get_session_factory)]) -> None:
    if not _origin_allowed(ws):
        await ws.close(code=4403)
        return
    await ws.accept()
    try:
        first = await asyncio.wait_for(ws.receive_json(), timeout=10)
        auth = await run_in_threadpool(_authenticate, factory, first if isinstance(first, dict) else {})
    except (asyncio.TimeoutError, ValueError, WebSocketDisconnect):
        auth = None
    if auth is None:
        with contextlib.suppress(Exception):
            await ws.send_json({"type": "error", "detail": "authentication failed"})
            await ws.close(code=4401)
        return
    user_id, role, scope = auth
    sub = broker.subscribe(user_id, scope)
    await ws.send_json({"type": "ready", "user_id": str(user_id), "role": role,
                        "patients": sorted(str(p) for p in scope),
                        "server_time": datetime.now(timezone.utc).isoformat()})

    async def sender() -> None:
        last_scope = asyncio.get_running_loop().time()
        while True:
            try:
                event = await asyncio.wait_for(sub.queue.get(), timeout=HEARTBEAT_SECONDS)
                await ws.send_json(event)
            except asyncio.TimeoutError:
                await ws.send_json({"type": "ping"})
            now = asyncio.get_running_loop().time()
            if now - last_scope > SCOPE_REFRESH_SECONDS:     # care-team changes take effect within a minute
                sub.scope = await run_in_threadpool(_scope_for, factory, user_id)
                last_scope = now

    async def receiver() -> None:
        while True:
            msg = await ws.receive_json()
            if isinstance(msg, dict) and msg.get("type") == "subscribe":
                ids = msg.get("patient_ids")
                sub.vitals_for = ({uuid.UUID(i) for i in ids} & sub.scope) if ids else None

    tasks = [asyncio.create_task(sender()), asyncio.create_task(receiver())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for t in tasks:
            t.cancel()
        broker.unsubscribe(sub)
        with contextlib.suppress(Exception):
            await ws.close()
