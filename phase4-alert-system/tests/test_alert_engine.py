"""alert engine scenarios: threshold monitoring, patient-specific limits, fatigue controls, escalation"""
from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.alerts.engine import AlertEngine, ThresholdResolver, breaches
from app.errors import ConflictError, ValidationFailed
from app.models import Alert, AlertEvent, Notification
from app.models.enums import (AlertEventType, AlertSeverity, AlertStatus, NotificationChannel, ReadingContext)
from app.repositories.alerts import AlertRepository
from tests.conftest import NOW, add_vitals, set_rx

EX, REST, REC = ReadingContext.exercise, ReadingContext.rest, ReadingContext.recovery
sc = pytest.mark.scenario


def run(db, patient, rows, now=NOW):
    vitals = add_vitals(db, patient, rows, now=now)
    out = AlertEngine(db).evaluate_readings(patient.patient_id, vitals, now=now)
    db.flush()
    return out


def created(outcomes):
    return [o for o in outcomes if o.action == "created"]


def notes_for(db, alert):
    db.flush()
    return list(db.scalars(select(Notification).where(Notification.alert_id == alert.alert_id)))


# ---------------------------------------------------------------- threshold monitoring (FR-10)
@sc("AS-01", "Exercise heart rate above the prescribed ceiling on 2 consecutive readings raises a critical alert "
             "and queues dashboard, SMS, and email for the primary clinician", "FR-10, FR-12, FR-13")
def test_critical_hr_above_prescribed_ceiling(db, alert_world):
    w = alert_world
    out = run(db, w["robert"], [(2, EX, {"heart_rate": 133}), (1, EX, {"heart_rate": 138})])
    [o] = created(out)
    a = o.alert
    assert (a.severity, a.status, a.rule.rule_code) == (AlertSeverity.critical, AlertStatus.open, "HR_ABOVE_CEILING")
    assert a.threshold_applied == 128 and a.threshold_source == "prescription"
    assert a.triggering_values["values"] == [133, 138] and a.title == \
        "Heart rate 138 bpm above prescribed limit of 128 bpm"
    notes = notes_for(db, a)
    assert {(n.recipient_user_id, n.channel) for n in notes} == {
        (w["dana"].user_id, NotificationChannel.dashboard), (w["dana"].user_id, NotificationChannel.sms),
        (w["dana"].user_id, NotificationChannel.email)}
    assert all(n.deliver_after == NOW and not n.is_digest for n in notes)


@sc("AS-02", "The same heart rate does not alert for a patient whose prescribed ceiling is higher", "FR-10")
def test_same_value_patient_specific(db, alert_world):
    w = alert_world
    assert created(run(db, w["robert"], [(2, EX, {"heart_rate": 138}), (1, EX, {"heart_rate": 138})]))
    assert run(db, w["linda"], [(2, EX, {"heart_rate": 138}), (1, EX, {"heart_rate": 138})]) == []


@sc("AS-03", "A single breaching reading does not alert when the rule needs consecutive readings", "FR-10")
def test_single_spike_filtered(db, alert_world):
    assert run(db, alert_world["robert"], [(2, EX, {"heart_rate": 112}), (1, EX, {"heart_rate": 140})]) == []


@sc("AS-04", "Breaching readings farther apart than the rule window are not consecutive", "FR-10")
def test_consecutive_window(db, alert_world):
    assert run(db, alert_world["robert"], [(45, EX, {"heart_rate": 140}), (1, EX, {"heart_rate": 140})]) == []


@sc("AS-05", "Context filters: a resting reading never triggers the exercise ceiling rule, but two high resting "
             "readings trigger the resting rule", "FR-10")
def test_context_filters(db, alert_world):
    out = run(db, alert_world["linda"], [(3, REST, {"heart_rate": 131}), (1, REST, {"heart_rate": 133})])
    assert [o.alert.rule.rule_code for o in created(out)] == ["RESTING_HR_HIGH"]


@sc("AS-06", "Suspect readings (implausible values) are stored but never alert", "FR-07, FR-10")
def test_suspect_never_alerts(db, alert_world):
    vitals = run(db, alert_world["robert"], [(2, EX, {"heart_rate": 235}), (1, EX, {"heart_rate": 236})])
    assert vitals == []


@sc("AS-07", "A patient override (beta-blocker, resting limit 90) takes precedence over the program default", "FR-10")
def test_override_precedence(db, alert_world):
    w = alert_world
    repo = AlertRepository(db)
    repo.set_override(w["robert"].patient_id, repo.get_rule("RESTING_HR_HIGH"), 90, "On beta-blocker; baseline 60s.",
                      w["raman"], now=NOW - timedelta(days=1))
    rows = [(3, REST, {"heart_rate": 95}), (1, REST, {"heart_rate": 96})]
    [o] = created(run(db, w["robert"], rows))
    assert (o.alert.threshold_applied, o.alert.threshold_source) == (90, "override")
    assert run(db, w["linda"], rows) == []          # same values, default limit 100


@sc("AS-08", "Without a prescription the program default applies and is labeled as the source", "FR-10")
def test_default_without_prescription(db, alert_world):
    thomas = alert_world["thomas"]
    assert run(db, thomas, [(2, EX, {"heart_rate": 140}), (1, EX, {"heart_rate": 145})]) == []
    [o] = created(run(db, thomas, [(2, EX, {"heart_rate": 152}), (1, EX, {"heart_rate": 155})],
                      now=NOW + timedelta(minutes=10)))
    assert (o.alert.threshold_applied, o.alert.threshold_source) == (150, "default")


@sc("AS-09", "SpO2 below the prescription floor raises a critical alert in any context", "FR-10")
def test_spo2_low(db, alert_world):
    [o] = created(run(db, alert_world["robert"], [(2, REST, {"spo2": 88}), (1, REST, {"spo2": 87})]))
    assert o.alert.severity == AlertSeverity.critical and o.alert.title == "SpO2 87% below prescribed limit of 90%"


@sc("AS-10", "Blood pressure rules: exercise systolic above the prescribed maximum is high; resting systolic at or "
             "above 160 is moderate", "FR-10")
def test_bp_rules(db, alert_world):
    w = alert_world
    [o] = created(run(db, w["robert"], [(1, REC, {"systolic_bp": 186, "diastolic_bp": 84})]))
    assert (o.alert.rule.rule_code, o.alert.severity, o.alert.threshold_applied) == \
        ("EXERCISE_SBP_HIGH", AlertSeverity.high, 180)
    [o2] = created(run(db, w["linda"], [(1, REST, {"systolic_bp": 162, "diastolic_bp": 90})]))
    assert (o2.alert.rule.rule_code, o2.alert.severity) == ("RESTING_SBP_HIGH", AlertSeverity.moderate)


def test_comparators_and_resolver_order(db, alert_world):
    assert breaches(101, ">", 100) and not breaches(100, ">", 100) and breaches(100, ">=", 100)
    assert breaches(89, "<", 90) and breaches(90, "<=", 90) and not breaches(90, "<", 90)
    repo = AlertRepository(db)
    res = ThresholdResolver(repo, alert_world["robert"].patient_id)
    assert res.resolve(repo.get_rule("HR_ABOVE_CEILING")) == (128.0, "prescription")
    assert res.resolve(repo.get_rule("RESTING_SBP_HIGH")) == (160.0, "default")


# ---------------------------------------------------------------- prioritization and fatigue (FR-12)
@sc("AS-17", "Repeated breaches attach to the open alert instead of creating new alerts or notifications", "FR-12")
def test_repeats_absorbed(db, alert_world):
    w = alert_world
    [o] = created(run(db, w["robert"], [(3, EX, {"heart_rate": 133}), (2, EX, {"heart_rate": 138})]))
    before = len(notes_for(db, o.alert))
    out = run(db, w["robert"], [(1, EX, {"heart_rate": 141}), (0, EX, {"heart_rate": 143})])
    assert [x.action for x in out] == ["repeated", "repeated"]
    assert o.alert.occurrences == 3 and o.alert.triggering_values["latest"]["values"][-1] == 143
    assert len(notes_for(db, o.alert)) == before
    assert db.scalar(select(Alert).where(Alert.patient_id == w["robert"].patient_id).limit(2).offset(1)) is None


@sc("AS-18", "After resolution, the same moderate rule inside its suppression window is logged as suppressed with no "
             "notifications; after the window it alerts again", "FR-12")
def test_suppression_window(db, alert_world):
    w = alert_world
    rows = [(3, REST, {"systolic_bp": 165, "diastolic_bp": 88})]
    [o] = created(run(db, w["linda"], rows))
    eng = AlertEngine(db)
    eng.resolve(o.alert, w["dana"], "Rechecked: 142/86 after rest.", now=NOW + timedelta(minutes=30))
    later = NOW + timedelta(hours=2)
    [s] = run(db, w["linda"], rows, now=later)
    assert s.action == "suppressed" and s.alert.status == AlertStatus.suppressed and notes_for(db, s.alert) == []
    assert "suppression window" in s.alert.suppressed_reason
    [s2] = run(db, w["linda"], rows, now=later + timedelta(minutes=5))       # folded into the suppressed record
    assert s2.alert.alert_id == s.alert.alert_id and s.alert.occurrences == 2
    [fresh] = run(db, w["linda"], rows, now=NOW + timedelta(hours=13))      # window is 720 minutes
    assert fresh.action == "created" and notes_for(db, fresh.alert)


@sc("AS-19", "Critical alerts are never suppressed: a repeat right after resolution notifies again", "FR-12")
def test_critical_never_suppressed(db, alert_world):
    w = alert_world
    [o] = created(run(db, w["robert"], [(3, EX, {"heart_rate": 135}), (2, EX, {"heart_rate": 136})]))
    AlertEngine(db).resolve(o.alert, w["dana"], "Stopped exercise; HR 104 after rest.", now=NOW + timedelta(minutes=5))
    [again] = created(run(db, w["robert"], [(1, EX, {"heart_rate": 137}), (0, EX, {"heart_rate": 139})],
                          now=NOW + timedelta(minutes=10)))
    assert again.alert.alert_id != o.alert.alert_id and len(notes_for(db, again.alert)) == 3


@sc("AS-20", "An active high-severity alert masks a lower-severity alert on the same measurement", "FR-12")
def test_masking(db, alert_world):
    w = alert_world
    created(run(db, w["robert"], [(30, REC, {"systolic_bp": 190, "diastolic_bp": 86})]))
    [m] = run(db, w["robert"], [(1, REST, {"systolic_bp": 166, "diastolic_bp": 84})])
    assert m.action == "suppressed" and "masked by active high alert EXERCISE_SBP_HIGH" in m.alert.suppressed_reason


@sc("AS-22", "Alert-storm cap: past the hourly limit, a patient's non-critical email and SMS go to the digest while "
             "the dashboard is still notified immediately", "FR-12")
def test_storm_cap(db, alert_world):
    w = alert_world
    repo, eng = AlertRepository(db), AlertEngine(db)
    codes = ["RESTING_HR_HIGH", "RESTING_SBP_HIGH", "RESTING_SBP_LOW", "RESTING_HR_LOW", "EXERCISE_SBP_HIGH"]
    outs = [eng.raise_alert(w["robert"].patient_id, repo.get_rule(c), title=c, triggering={}, threshold=1,
                            source="default", now=NOW + timedelta(minutes=i)) for i, c in enumerate(codes)]
    last = notes_for(db, outs[-1].alert)
    assert {n.channel for n in last if n.is_digest} == {NotificationChannel.email}
    assert [n for n in last if n.channel == NotificationChannel.dashboard and not n.is_digest]
    assert not any(n.is_digest for n in notes_for(db, outs[0].alert))


@sc("AS-21", "Low-severity alerts reach the dashboard now and email in the next morning digest", "FR-12")
def test_low_goes_to_digest(db, alert_world):
    w = alert_world
    repo = AlertRepository(db)
    o = AlertEngine(db).raise_alert(w["robert"].patient_id, repo.get_rule("DATA_GAP"), title="No readings for 50 hours",
                                    triggering={"value": 50}, threshold=48, source="default", now=NOW)
    notes = {n.channel: n for n in notes_for(db, o.alert)}
    assert notes[NotificationChannel.dashboard].deliver_after == NOW
    assert notes[NotificationChannel.email].is_digest
    assert notes[NotificationChannel.email].deliver_after.isoformat() == "2026-11-13T14:00:00+00:00"   # 07:00 Denver


# ---------------------------------------------------------------- escalation (FR-15)
@sc("AS-32", "An unacknowledged critical alert escalates to the supervising physician at 15 minutes (not before), "
             "to the whole care team on every channel at 30 minutes, and stops at the maximum level", "FR-15")
def test_escalation_ladder(db, alert_world):
    w = alert_world
    [o] = created(run(db, w["robert"], [(2, EX, {"heart_rate": 133}), (1, EX, {"heart_rate": 138})]))
    eng = AlertEngine(db)
    assert eng.run_escalations(NOW + timedelta(minutes=14, seconds=59)) == []
    assert eng.run_escalations(NOW + timedelta(minutes=15)) == [o.alert]
    assert (o.alert.status, o.alert.escalation_level) == (AlertStatus.escalated, 1)
    lvl1 = [n for n in notes_for(db, o.alert) if n.escalation_level == 1]
    assert {n.recipient_user_id for n in lvl1} == {w["raman"].user_id} and len(lvl1) == 3
    assert eng.run_escalations(NOW + timedelta(minutes=29)) == []
    assert eng.run_escalations(NOW + timedelta(minutes=30)) == [o.alert]
    lvl2 = [n for n in notes_for(db, o.alert) if n.escalation_level == 2]
    assert {n.recipient_user_id for n in lvl2} == {w["dana"].user_id, w["raman"].user_id} and len(lvl2) == 6
    assert eng.run_escalations(NOW + timedelta(hours=3)) == []
    events = [e.event_type for e in AlertRepository(db).events(o.alert.alert_id)]
    assert events.count(AlertEventType.escalated) == 2


@sc("AS-33", "Acknowledging an alert stops escalation", "FR-14, FR-15")
def test_ack_stops_escalation(db, alert_world):
    w = alert_world
    [o] = created(run(db, w["robert"], [(2, EX, {"heart_rate": 133}), (1, EX, {"heart_rate": 138})]))
    eng = AlertEngine(db)
    eng.acknowledge(o.alert, w["dana"], "On the phone with him.", now=NOW + timedelta(minutes=4))
    assert eng.run_escalations(NOW + timedelta(hours=1)) == []
    assert o.alert.acknowledged_by == w["dana"].user_id and o.alert.escalation_level == 0


@sc("AS-34", "Moderate alerts escalate once (after 4 hours); low alerts never escalate", "FR-15")
def test_policy_levels(db, alert_world):
    w = alert_world
    repo, eng = AlertRepository(db), AlertEngine(db)
    mod = eng.raise_alert(w["linda"].patient_id, repo.get_rule("RESTING_HR_HIGH"), title="m", triggering={},
                          threshold=100, source="default", now=NOW).alert
    low = eng.raise_alert(w["linda"].patient_id, repo.get_rule("DATA_GAP"), title="l", triggering={}, threshold=48,
                          source="default", now=NOW).alert
    assert eng.run_escalations(NOW + timedelta(minutes=239)) == []
    assert eng.run_escalations(NOW + timedelta(minutes=240)) == [mod]
    assert eng.run_escalations(NOW + timedelta(days=3)) == [] and low.escalation_level == 0


# ---------------------------------------------------------------- acknowledgment and resolution (FR-14)
@sc("AS-31", "Resolution needs a note, records acknowledgment if missing, and closed alerts reject further "
             "actions", "FR-14")
def test_resolution_rules(db, alert_world):
    w = alert_world
    [o] = created(run(db, w["robert"], [(2, EX, {"heart_rate": 133}), (1, EX, {"heart_rate": 138})]))
    eng = AlertEngine(db)
    with pytest.raises(ValidationFailed):
        eng.resolve(o.alert, w["dana"], " ", now=NOW + timedelta(minutes=2))
    eng.resolve(o.alert, w["dana"], "Rested 5 min, HR 101, no symptoms.", now=NOW + timedelta(minutes=6))
    assert o.alert.acknowledged_by == w["dana"].user_id and o.alert.status == AlertStatus.resolved
    with pytest.raises(ConflictError):
        eng.acknowledge(o.alert, w["dana"], now=NOW + timedelta(minutes=7))
    with pytest.raises(ConflictError):
        eng.resolve(o.alert, w["dana"], "again", now=NOW + timedelta(minutes=7))
    db.flush()
    types = [e.event_type for e in db.scalars(select(AlertEvent).where(AlertEvent.alert_id == o.alert.alert_id))]
    assert types == [AlertEventType.created, AlertEventType.resolved]


def test_alert_events_are_append_only(db, alert_world):
    [o] = created(run(db, alert_world["robert"], [(2, EX, {"heart_rate": 133}), (1, EX, {"heart_rate": 138})]))
    ev = AlertRepository(db).events(o.alert.alert_id)[0]
    ev.note = "edited"
    with pytest.raises(PermissionError):
        db.flush()
    db.rollback()


def test_prescription_versions(db, alert_world):
    w = alert_world
    repo = AlertRepository(db)
    first = repo.current_prescription(w["robert"].patient_id)
    new = set_rx(db, w["robert"], w["raman"], at=NOW - timedelta(days=1), hr_ceiling=135)
    assert new.version == first.version + 1 and first.effective_to is not None
    assert [r.version for r in repo.prescription_history(w["robert"].patient_id)] == [2, 1]
    # 132 no longer breaches the raised ceiling
    assert run(db, w["robert"], [(2, EX, {"heart_rate": 132}), (1, EX, {"heart_rate": 132})]) == []


def test_override_rejected_for_prescription_rules(db, alert_world):
    repo = AlertRepository(db)
    with pytest.raises(ValidationFailed, match="exercise prescription"):
        repo.set_override(alert_world["robert"].patient_id, repo.get_rule("HR_ABOVE_CEILING"), 140, "reason x",
                          alert_world["raman"])
