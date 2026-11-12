"""activity pattern detection: each pattern rule fires on a declining patient and stays silent on a stable control
(acceptance criterion of FR-11). the clock is Thursday 2026-11-12 10:00 in Denver; weeks end yesterday."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.alerts.engine import AlertEngine
from app.alerts.patterns import PatternMetrics
from app.models import DailyActivity
from app.models.enums import AlertSeverity, ReadingContext
from app.repositories.alerts import AlertRepository
from tests.conftest import NOW, add_vitals

DENVER = ZoneInfo("America/Denver")
sc = pytest.mark.scenario
PRIOR_WEEK = [date(2026, 10, 30), date(2026, 11, 2), date(2026, 11, 4)]          # fri, mon, wed
THIS_WEEK = [date(2026, 11, 6), date(2026, 11, 9), date(2026, 11, 11)]


def session(db, patient, d: date, hr: int, minutes: int = 25) -> None:
    start = datetime.combine(d, time(9), DENVER).astimezone(timezone.utc)
    add_vitals(db, patient, [(-i, ReadingContext.exercise, {"heart_rate": hr}) for i in range(minutes)], now=start)


def activity(db, patient, d: date, steps: int, rhr: int) -> None:
    db.add(DailyActivity(patient_id=patient.patient_id, activity_date=d, steps=steps, active_minutes=steps // 150,
                         resting_hr=rhr))


@pytest.fixture
def trends(db, alert_world):
    """robert: stops exercising after Nov 4, steps fall, resting HR rises. linda: steady control"""
    w = alert_world
    r, linda = w["robert"], w["linda"]
    for d in PRIOR_WEEK:
        session(db, r, d, 105)                 # in robert's 95-115 zone
    for d in PRIOR_WEEK + THIS_WEEK:
        session(db, linda, d, 120)             # in linda's 110-135 zone
    for i in range(14):
        d = date(2026, 11, 11) - timedelta(days=i)
        this_week = i < 7
        activity(db, r, d, 4000 if this_week else 7000, 77 if this_week else 66)
        activity(db, linda, d, 6100 if this_week else 6000, 74)
    add_vitals(db, linda, [(60, ReadingContext.rest, {"heart_rate": 72})])
    db.flush()
    outcomes = AlertEngine(db).evaluate_patterns({r.patient_id, linda.patient_id}, now=NOW)
    db.flush()
    codes = {pid: {o.alert.rule.rule_code for o in outcomes if o.alert.patient_id == pid}
             for pid in (r.patient_id, linda.patient_id)}
    return {**w, "robert_codes": codes[r.patient_id], "linda_codes": codes[linda.patient_id], "outcomes": outcomes}


@sc("AS-11", "Missed sessions: no exercise session for a week (3 prescribed per week) raises a high alert; the "
             "adherent control stays silent", "FR-11")
def test_missed_sessions(trends):
    assert "MISSED_SESSIONS" in trends["robert_codes"] and "MISSED_SESSIONS" not in trends["linda_codes"]
    a = next(o.alert for o in trends["outcomes"] if o.alert.rule.rule_code == "MISSED_SESSIONS")
    assert a.severity == AlertSeverity.high and a.triggering_values["value"] == 3
    assert a.triggering_values["last_session_date"] == "2026-11-04"


@sc("AS-12", "Minutes in the prescribed heart rate zone falling at least 25% week over week raises a moderate "
             "alert; the control stays silent", "FR-11")
def test_zone_minutes_decline(trends):
    assert "ZONE_MINUTES_DECLINE" in trends["robert_codes"] and "ZONE_MINUTES_DECLINE" not in trends["linda_codes"]


@sc("AS-13", "7-day resting heart rate more than 8 bpm above the prescription baseline raises a moderate alert; the "
             "control stays silent", "FR-11")
def test_resting_hr_rise(trends):
    assert "RESTING_HR_RISE" in trends["robert_codes"] and "RESTING_HR_RISE" not in trends["linda_codes"]
    a = next(o.alert for o in trends["outcomes"] if o.alert.rule.rule_code == "RESTING_HR_RISE")
    assert a.triggering_values["baseline"] == 66 and a.triggering_values["avg_7d"] == 77


@sc("AS-14", "Average daily steps falling at least 30% from the week before raises a moderate alert; the control "
             "stays silent", "FR-11")
def test_steps_decline(trends):
    assert "STEPS_DECLINE" in trends["robert_codes"] and "STEPS_DECLINE" not in trends["linda_codes"]


@sc("AS-15", "No readings for 48 hours raises a low-severity data-gap alert; recent data stays silent", "FR-11")
def test_data_gap(trends):
    assert "DATA_GAP" in trends["robert_codes"] and "DATA_GAP" not in trends["linda_codes"]


def test_control_patient_completely_silent(trends):
    assert trends["linda_codes"] == set()


@sc("AS-16", "Too little history never looks like a decline: trends need 4+ days in each week and a minimum "
             "baseline", "FR-11")
def test_insufficient_data(db, alert_world):
    t = alert_world["thomas"]
    activity(db, t, date(2026, 11, 10), 900, 70)
    activity(db, t, date(2026, 11, 11), 800, 90)
    db.flush()
    m = PatternMetrics(db, t, None, NOW).compute({"steps_7d_vs_prior_pct", "resting_hr_7d_minus_baseline",
                                                 "minutes_in_zone_wow_pct", "hours_since_last_reading"})
    assert m == {}


def test_repeated_pattern_runs_do_not_duplicate(trends, db):
    w = trends
    again = AlertEngine(db).evaluate_patterns({w["robert"].patient_id}, now=NOW + timedelta(minutes=15))
    assert {o.action for o in again} == {"repeated"}
    assert AlertRepository(db).search(scope=None, patient_id=w["robert"].patient_id).total_items == len(w["robert_codes"])


def test_pattern_titles_are_readable(trends):
    titles = {o.alert.rule.rule_code: o.alert.title for o in trends["outcomes"]}
    assert titles["STEPS_DECLINE"] == "Daily steps down 43% (4,000 vs 7,000 per day)"
    assert titles["MISSED_SESSIONS"] == "Missed 3 consecutive prescribed sessions (last session Nov 04)"
    assert titles["RESTING_HR_RISE"] == "Resting heart rate 11 bpm above baseline (77 vs 66 bpm)"
