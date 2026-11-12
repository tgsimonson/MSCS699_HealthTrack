"""glue between ingestion, the alert engine, and the live event stream

called after the readings are committed, so a failure in alert evaluation is logged but can never lose a
reading. events are published only after the alert transaction commits, so a dashboard never shows an alert that
was rolled back.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.alerts.engine import AlertEngine, Outcome
from app.logging_config import get_logger
from app.models import Alert, DailyActivity, VitalSign
from app.realtime.broker import broker
from app.repositories.monitoring import VitalSignRepository
from app.schemas.alerts import AlertOut

log = get_logger("alerts.service")
VITAL_FIELDS = ("vital_id", "recorded_at", "context", "heart_rate", "systolic_bp", "diastolic_bp", "spo2", "quality",
                "source", "device_id")


def vital_event(v: VitalSign) -> dict[str, Any]:
    data = {}
    for f in VITAL_FIELDS:
        val = getattr(v, f)
        data[f] = val.isoformat() if hasattr(val, "isoformat") else getattr(val, "value", val)
    data["device_id"] = str(v.device_id) if v.device_id else None
    return {"type": "vital", "patient_id": str(v.patient_id), "data": data}


def alert_event(alert: Alert, action: str) -> dict[str, Any]:
    return {"type": "alert", "action": action, "patient_id": str(alert.patient_id),
            "data": AlertOut.model_validate(alert).model_dump(mode="json")}


def publish_outcomes(outcomes: list[Outcome]) -> None:
    for o in outcomes:
        broker.publish(alert_event(o.alert, o.action))
    if any(o.notifications for o in outcomes):
        from app.alerts.workers import workers
        workers.wake()


def process_new_readings(db: Session, patient_id: uuid.UUID, vital_ids: list[int]) -> list[Outcome]:
    vitals = VitalSignRepository(db).load(vital_ids)
    for v in vitals:
        broker.publish(vital_event(v))
    try:
        outcomes = AlertEngine(db).evaluate_readings(patient_id, vitals)
        db.commit()
    except Exception:
        db.rollback()
        log.exception("alert evaluation failed; readings are stored", extra={"ctx": {"patient_id": str(patient_id),
                                                                                     "readings": len(vital_ids)}})
        return []
    publish_outcomes(outcomes)
    return outcomes


def process_activity(db: Session, row: DailyActivity) -> list[Outcome]:
    """daily totals feed the step and resting heart rate trends, so re-check this patient's pattern rules"""
    broker.publish({"type": "activity", "patient_id": str(row.patient_id),
                    "data": {"activity_date": row.activity_date.isoformat(), "steps": row.steps,
                             "active_minutes": row.active_minutes, "resting_hr": row.resting_hr}})
    try:
        outcomes = AlertEngine(db).evaluate_patterns({row.patient_id})
        db.commit()
    except Exception:
        db.rollback()
        log.exception("pattern evaluation failed", extra={"ctx": {"patient_id": str(row.patient_id)}})
        return []
    publish_outcomes(outcomes)
    return outcomes
