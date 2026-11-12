"""fastapi application factory"""
from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app import __version__
from app.api.deps import DB
from app.api.handlers import register_handlers
from app.alerts.workers import workers
from app.api.routes import activity, alert_config, alerts, auth, patients, stream, vitals
from app.config import get_settings
from app.realtime.broker import broker
from app.logging_config import configure_logging, get_logger, request_id_var

API_PREFIX = "/api/v1"
DESCRIPTION = (Path(__file__).parent / "openapi_description.md").read_text()

TAGS = [
    {"name": "Auth", "description": "Login, refresh-token rotation, logout, current user."},
    {"name": "Patients", "description": "Patient registration, profile, search, and care team."},
    {"name": "Vital Signs", "description": "Heart rate, blood pressure, and SpO2 collection and queries."},
    {"name": "Activity", "description": "Daily steps, active minutes, and resting heart rate."},
    {"name": "Devices", "description": "Home monitoring devices assigned to a patient."},
    {"name": "Alerts", "description": "Alert worklist, history search, acknowledgment, resolution, and metrics."},
    {"name": "Alert Configuration", "description": "Program rules, escalation policies, exercise prescriptions, "
                                                   "and patient-specific thresholds."},
    {"name": "Notifications", "description": "Notifications addressed to the signed-in clinician."},
    {"name": "Live Stream", "description": "WebSocket stream of new readings and alert changes, and the "
                                          "monitoring worklist."},
    {"name": "System", "description": "Health check."},
]

log = get_logger("api")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    s = get_settings()
    if s.alert_workers:
        await workers.start()
    try:
        yield
    finally:
        if workers.running:
            await workers.stop()


def create_app() -> FastAPI:
    s = get_settings()
    configure_logging(s.log_level)
    app = FastAPI(title="HealthTrack API", version=__version__, description=DESCRIPTION, openapi_tags=TAGS,
                  lifespan=lifespan,
                  docs_url="/docs", redoc_url="/redoc", openapi_url=f"{API_PREFIX}/openapi.json",
                  servers=[{"url": "http://localhost:8000", "description": "Local development"}],
                  swagger_ui_parameters={"persistAuthorization": False, "displayRequestDuration": True})

    app.add_middleware(CORSMiddleware, allow_origins=list(s.cors_origins), allow_credentials=False,
                       allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
                       allow_headers=["Authorization", "Content-Type", "X-Request-ID"])

    @app.middleware("http")
    async def request_context(request: Request, call_next):  # noqa: ANN001, ANN202
        rid = request.headers.get("x-request-id") or str(uuid.uuid4())
        try:
            rid = str(uuid.UUID(rid))           # only accept a uuid so log lines cannot be injected
        except ValueError:
            rid = str(uuid.uuid4())
        token = request_id_var.set(rid)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        ms = round((time.perf_counter() - started) * 1000, 2)
        response.headers["X-Request-ID"] = rid
        response.headers["X-Response-Time-ms"] = str(ms)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"        # phi must not be cached by browsers or proxies
        if s.is_production:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        # path only: query strings could carry search terms, and uuids in paths are not phi
        log.info("request", extra={"ctx": {"request_id": rid, "method": request.method, "path": request.url.path,
                                           "status": response.status_code, "ms": ms}})
        return response

    register_handlers(app)

    api = APIRouter(prefix=API_PREFIX)
    api.include_router(auth.router)
    api.include_router(patients.router)
    api.include_router(vitals.router)
    api.include_router(activity.router)
    api.include_router(activity.devices_router)
    api.include_router(alerts.router)
    api.include_router(alerts.notifications_router)
    api.include_router(alert_config.router)
    api.include_router(stream.router)

    @api.get("/health", tags=["System"], summary="Liveness and database check")
    def health(db: DB) -> dict:
        db.execute(text("SELECT 1"))
        return {"status": "ok", "database": db.bind.dialect.name, "version": __version__,
                "alert_workers": workers.running, "stream_subscribers": broker.subscriber_count}

    app.include_router(api)
    return app


app = create_app()
