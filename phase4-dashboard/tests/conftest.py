"""shared fixtures: realistic api payloads (shapes copied from the alert-system api responses)"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

NOW = datetime(2026, 11, 12, 16, 30, tzinfo=timezone.utc)
THOMAS, MARIA = "00000000-0000-4000-b000-000000000005", "00000000-0000-4000-b000-000000000004"


def iso(minutes_ago: float) -> str:
    return (NOW - timedelta(minutes=minutes_ago)).isoformat()


def reading(minutes_ago: float, ctx: str = "exercise", quality: str = "valid", vital_id: int = 1, **v) -> dict:  # noqa: ANN003
    return {"vital_id": vital_id, "recorded_at": iso(minutes_ago), "context": ctx, "quality": quality,
            "heart_rate": None, "systolic_bp": None, "diastolic_bp": None, "spo2": None, **v}


@pytest.fixture
def thresholds() -> list[dict]:
    """GET /patients/{thomas}/alert-thresholds (prescription ceiling 128, override resting hr 90)"""
    def t(code, metric, comp, value, sev, ctx, source="default", rtype="threshold"):  # noqa: ANN001, ANN202
        return {"rule_code": code, "name": code, "rule_type": rtype, "metric": metric, "comparator": comp,
                "threshold": value, "source": source, "severity": sev, "applies_to_context": ctx,
                "consecutive_required": 1, "is_customizable": True}
    return [t("HR_ABOVE_CEILING", "heart_rate", ">", 128, "critical", ["warmup", "exercise", "cooldown"], "prescription"),
            t("SPO2_LOW", "spo2", "<", 90, "critical", None, "prescription"),
            t("EXERCISE_SBP_HIGH", "systolic_bp", ">", 180, "high", ["exercise", "cooldown", "recovery"], "prescription"),
            t("RESTING_SBP_LOW", "systolic_bp", "<", 90, "high", ["rest"]),
            t("RESTING_HR_LOW", "heart_rate", "<", 40, "high", ["rest"]),
            t("RESTING_SBP_HIGH", "systolic_bp", ">=", 160, "moderate", ["rest"]),
            t("RESTING_HR_HIGH", "heart_rate", ">", 90, "moderate", ["rest"], "override"),
            t("STEPS_DECLINE", "steps_7d_vs_prior_pct", "<=", -30, "moderate", None, rtype="pattern")]


@pytest.fixture
def rx() -> dict:
    return {"version": 1, "resting_hr_baseline": 66, "target_hr_min": 95, "target_hr_max": 115, "hr_ceiling": 128,
            "min_spo2": 90, "max_exercise_sbp": 180, "sessions_per_week": 3, "session_minutes": 30}


@pytest.fixture
def limits(thresholds, rx) -> dict:
    from dashboard.figures import build_limits
    return {**build_limits(thresholds, rx), "patient_id": THOMAS}


def alert(alert_id: str, patient: str, severity: str, status: str = "open", minutes_ago: float = 5, **kw) -> dict:  # noqa: ANN003
    return {"alert_id": alert_id, "patient_id": patient, "rule_code": "HR_ABOVE_CEILING",
            "rule_name": "Heart rate above prescribed ceiling", "rule_type": "threshold", "severity": severity,
            "status": status, "title": f"{severity} alert", "triggering_values": {}, "threshold_applied": 128,
            "threshold_source": "prescription", "occurrences": 1, "triggered_at": iso(minutes_ago),
            "last_occurred_at": iso(minutes_ago), "acknowledged_at": None, "acknowledged_by": None,
            "escalation_level": 0, "escalated_at": None, "resolved_at": None, "resolved_by": None,
            "resolution_note": None, "suppressed_reason": None, **kw}


@pytest.fixture
def worklist() -> list[dict]:
    """GET /monitoring/worklist for marcus"""
    def row(pid, first, last, prio, top):  # noqa: ANN001, ANN202
        return {"patient_id": pid, "mrn": "HT-10000" + pid[-1], "first_name": first, "last_name": last,
                "clinical_risk_category": "moderate", "program_status": "active",
                "latest": {"heart_rate": {"value": 136, "recorded_at": iso(1), "context": "exercise"},
                           "blood_pressure": {"value": "121/73", "recorded_at": iso(600), "context": "rest"},
                           "spo2": None},
                "last_reading_at": iso(1), "active_alerts": {"critical": int(prio == 4), "high": int(prio == 3),
                                                             "moderate": 0, "low": 0},
                "top_alert": top, "priority": prio, "prescription": None}
    return [row(THOMAS, "Thomas", "Reed", 4, alert("a1", THOMAS, "critical")),
            row(MARIA, "Maria", "Gonzales", 3, alert("a2", MARIA, "high"))]
