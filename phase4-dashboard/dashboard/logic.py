"""pure state updates used by the callbacks (no dash or http here, so they are unit tested directly)"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

ACTIVE = ("open", "acknowledged", "escalated")
RANK = {"critical": 4, "high": 3, "moderate": 2, "low": 1}


def initial_selection(rows: list[dict], previous: str | None, linked_patient: str | None = None) -> str | None:
    """deep link first, then the patient selected earlier this session, then the top of the worklist"""
    ids = [r["patient_id"] for r in rows]
    for candidate in (linked_patient, previous):
        if candidate in ids:
            return candidate
    return ids[0] if ids else None


def apply_events(events: list[dict], rows: list[dict], alerts: dict[str, dict], selected: str | None,
                 toasts: list[dict], now: datetime | None = None) -> dict[str, Any]:
    """fold one batch of stream events into the dashboard state

    returns new copies plus flags saying what changed, so the callback only sends what is different:
      rows / alerts / toasts   updated state
      rows_changed, alerts_changed, toasts_changed
      gauges                   newest valid reading per measurement for the selected patient (or None)
    """
    rows = [{**r, "latest": dict(r["latest"])} for r in rows]
    alerts, toasts = dict(alerts), list(toasts)
    flags = {"rows_changed": False, "alerts_changed": False, "toasts_changed": False}
    gauges: dict[str, dict | None] = {"heart_rate": None, "spo2": None, "systolic_bp": None}
    by_id = {r["patient_id"]: r for r in rows}
    for e in events:
        kind = e.get("type")
        if kind == "alert":
            a = e["data"]
            if a["status"] in ACTIVE:
                alerts[a["alert_id"]] = a
            else:
                alerts.pop(a["alert_id"], None)
            flags["alerts_changed"] = True
            if a["status"] not in ("open", "escalated"):
                # someone acknowledged or closed it, so its pop-up has done its job
                kept = [t for t in toasts if t["data"].get("alert_id") != a["alert_id"]]
                if len(kept) != len(toasts):
                    toasts, flags["toasts_changed"] = kept, True
        elif kind == "vital":
            v = e["data"]
            if v.get("quality") != "valid":
                continue
            row = by_id.get(e["patient_id"])
            if row is not None:
                for key, field in (("heart_rate", "heart_rate"), ("spo2", "spo2"), ("blood_pressure", "systolic_bp")):
                    if v.get(field) is not None:
                        value = f"{v['systolic_bp']}/{v['diastolic_bp']}" if key == "blood_pressure" else v[field]
                        row["latest"][key] = {"value": value, "recorded_at": v["recorded_at"], "context": v["context"]}
                row["last_reading_at"] = v["recorded_at"]
                flags["rows_changed"] = True
            if e["patient_id"] == selected:
                for k in gauges:
                    if v.get(k) is not None:
                        gauges[k] = v
        elif kind == "notification":
            shown = (now or datetime.now(timezone.utc)).isoformat()
            # one pop-up per alert: an escalation replaces the earlier pop-up for the same alert
            others = [t for t in toasts if t["data"].get("alert_id") != e["data"].get("alert_id")]
            toasts = [{**e, "shown_at": shown}, *others][:3]
            flags["toasts_changed"] = True
    return {"rows": rows, "alerts": alerts, "toasts": toasts, "gauges": gauges, **flags}


def order_alerts(alerts: list[dict], selected: str | None) -> tuple[list[dict], list[dict]]:
    """selected patient's alerts first; within each list: severity, then unacknowledged, then oldest first"""
    key = lambda a: (-RANK[a["severity"]], a["status"] == "acknowledged", a["triggered_at"])  # noqa: E731
    ordered = sorted(alerts, key=key)
    return [a for a in ordered if a["patient_id"] == selected], [a for a in ordered if a["patient_id"] != selected]


def fresh_toasts(toasts: list[dict], now: datetime | None = None, seconds: int = 90) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    return [t for t in toasts if (now - datetime.fromisoformat(t["shown_at"])).total_seconds() < seconds]
