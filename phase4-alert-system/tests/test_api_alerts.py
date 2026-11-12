"""alert management api: ingestion integration, worklist, acknowledgment, roles, search, history, configuration"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.alerts.engine import AlertEngine
from app.models import Alert, AuditLog, DailyActivity, VitalSign
from app.models.enums import AlertStatus
from app.repositories.alerts import AlertRepository
from tests.conftest import ago, auth_header

API = "/api/v1"
sc = pytest.mark.scenario


def hr_batch(w, values, ctx="exercise", start_minutes=10, key="b"):
    return {"readings": [{"recorded_at": ago(minutes=start_minutes - i).isoformat(), "context": ctx,
                          "heart_rate": v, "device_id": str(w["band"].device_id), "idempotency_key": f"key-{key}-{i:05d}"}
                         for i, v in enumerate(values)]}


@pytest.fixture
def raised(client, db, alert_world):
    """robert's device app uploads an exercise batch that crosses his 128 bpm ceiling"""
    w = alert_world
    r = client.post(f"{API}/patients/{w['robert'].patient_id}/vitals/batch", headers=auth_header(db, w["robert_login"]),
                    json=hr_batch(w, [110, 118, 125, 131, 136, 139, 137]))
    assert r.status_code == 200
    alert = db.scalar(select(Alert).where(Alert.patient_id == w["robert"].patient_id))
    return {**w, "batch": r.json(), "alert": alert}


def h(db, w, who):
    return auth_header(db, w[who])


# ---------------------------------------------------------------- ingestion integration
@sc("AS-47", "A device batch that crosses the ceiling returns alerts_raised and the alert appears on the care "
             "team's worklist, with repeats folded into it", "FR-10, FR-18")
def test_batch_raises_alert(client, db, raised):
    w = raised
    assert raised["batch"]["accepted"] == 7 and raised["batch"]["alerts_raised"] == 1
    a = raised["alert"]
    assert a.rule.rule_code == "HR_ABOVE_CEILING" and a.occurrences == 3        # 136, 139, 137 after 131
    items = client.get(f"{API}/alerts", headers=h(db, w, "dana")).json()["items"]
    assert [i["alert_id"] for i in items] == [str(a.alert_id)] and items[0]["rule_name"]
    assert client.get(f"{API}/alerts", headers=h(db, w, "marcus")).json()["items"] == []


@sc("AS-48", "If alert evaluation fails, the reading is still stored and the request succeeds", "NFR-12")
def test_evaluation_failure_never_loses_readings(client, db, alert_world, monkeypatch):
    w = alert_world

    def boom(*a, **k):  # noqa: ANN002, ANN003, ANN202
        raise RuntimeError("rule bug")

    monkeypatch.setattr(AlertEngine, "evaluate_readings", boom)
    r = client.post(f"{API}/patients/{w['robert'].patient_id}/vitals", headers=h(db, w, "robert_login"),
                    json={"recorded_at": ago(minutes=1).isoformat(), "context": "exercise", "heart_rate": 150,
                          "device_id": str(w["band"].device_id)})
    assert r.status_code == 201 and db.get(VitalSign, r.json()["vital_id"]) is not None


@sc("AS-49", "The monitoring worklist ranks the patient with a critical alert first and carries latest values and "
             "prescription limits", "FR-17, NFR-15")
def test_worklist(client, db, raised):
    w = raised
    rows = client.get(f"{API}/monitoring/worklist", headers=h(db, w, "dana")).json()
    assert rows[0]["patient_id"] == str(w["robert"].patient_id) and rows[0]["priority"] == 4
    assert rows[0]["active_alerts"]["critical"] == 1 and rows[0]["latest"]["heart_rate"]["value"] == 137
    assert rows[0]["prescription"]["hr_ceiling"] == 128
    assert {r["patient_id"] for r in rows} == {str(w["robert"].patient_id), str(w["linda"].patient_id)}
    assert client.get(f"{API}/monitoring/worklist", headers=h(db, w, "robert_login")).status_code == 403


# ---------------------------------------------------------------- acknowledgment and roles (FR-14)
@sc("AS-29", "A clinician on the care team acknowledges an alert; who and when are recorded in the alert history "
             "and the audit log", "FR-14, NFR-05")
def test_acknowledge(client, db, raised):
    w, a = raised, raised["alert"]
    r = client.post(f"{API}/alerts/{a.alert_id}/acknowledge", headers=h(db, w, "dana"),
                    json={"note": "Calling patient now."})
    assert r.status_code == 200 and r.json()["status"] == "acknowledged"
    assert r.json()["acknowledged_by"] == str(w["dana"].user_id)
    audit = db.scalar(select(AuditLog).where(AuditLog.entity_type == "alerts", AuditLog.action == "update"))
    assert audit.entity_id == str(a.alert_id) and audit.details["changed_columns"] == ["status", "acknowledged_at"]
    again = client.post(f"{API}/alerts/{a.alert_id}/acknowledge", headers=h(db, w, "dana"), json={})
    assert again.status_code == 409


@sc("AS-30", "Patients and administrators cannot acknowledge (403); a clinician outside the care team gets 404 and "
             "the attempt is audited", "FR-14, NFR-04")
@pytest.mark.parametrize("who,code", [("robert_login", 403), ("admin", 403), ("it", 403), ("marcus", 404)])
def test_ack_permissions(client, db, raised, who, code):
    a = raised["alert"]
    r = client.post(f"{API}/alerts/{a.alert_id}/acknowledge", headers=h(db, raised, who), json={})
    assert r.status_code == code
    if who == "marcus":
        denied = db.scalar(select(AuditLog).where(AuditLog.outcome == "denied", AuditLog.entity_type == "alerts"))
        assert denied.actor_user_id == raised["marcus"].user_id


def test_resolve_via_api(client, db, raised):
    w, a = raised, raised["alert"]
    assert client.post(f"{API}/alerts/{a.alert_id}/resolve", headers=h(db, w, "raman"), json={}).status_code == 422
    r = client.post(f"{API}/alerts/{a.alert_id}/resolve", headers=h(db, w, "raman"),
                    json={"note": "Session stopped; HR 102 at rest, asymptomatic."})
    assert r.status_code == 200 and r.json()["status"] == "resolved" and r.json()["acknowledged_by"]
    c = client.post(f"{API}/alerts/{a.alert_id}/comments", headers=h(db, w, "dana"), json={"note": "Follow-up Fri."})
    assert c.status_code == 201 and c.json()["events"][-1]["event_type"] == "comment"


# ---------------------------------------------------------------- history (FR-16)
@pytest.fixture
def history(db, alert_world):
    """six alerts across two patients, three rules, several statuses and days"""
    w = alert_world
    eng, repo = AlertEngine(db), AlertRepository(db)
    base = datetime.now(timezone.utc) - timedelta(days=10)
    spec = [("robert", "HR_ABOVE_CEILING", 0), ("robert", "RESTING_SBP_HIGH", 1), ("linda", "RESTING_HR_HIGH", 2),
            ("linda", "STEPS_DECLINE", 5), ("robert", "DATA_GAP", 8), ("linda", "SPO2_LOW", 9)]
    alerts = {}
    for who, code, day in spec:
        o = eng.raise_alert(w[who].patient_id, repo.get_rule(code), title=code, triggering={}, threshold=1,
                            source="default", now=base + timedelta(days=day))
        alerts[code] = o.alert
    eng.acknowledge(alerts["HR_ABOVE_CEILING"], w["dana"], now=base + timedelta(minutes=6))
    eng.resolve(alerts["HR_ABOVE_CEILING"], w["dana"], "Resolved after rest.", now=base + timedelta(minutes=40))
    eng.acknowledge(alerts["RESTING_HR_HIGH"], w["raman"], now=base + timedelta(days=2, minutes=30))
    db.commit()
    return {**w, "alerts": alerts, "base": base}


@sc("AS-35", "History search filters by patient, severity, status, rule, date range, and acknowledging user, with "
             "correct paging", "FR-16")
def test_history_search(client, db, history):
    w, hd = history, h(db, history, "dana")

    def codes(**params):
        r = client.get(f"{API}/alerts", headers=hd, params=params)
        assert r.status_code == 200, r.text
        return [i["rule_code"] for i in r.json()["items"]]

    # active worklist: severity first, then newest
    assert codes() == ["SPO2_LOW", "STEPS_DECLINE", "RESTING_HR_HIGH", "RESTING_SBP_HIGH", "DATA_GAP"]
    assert codes(status="resolved") == ["HR_ABOVE_CEILING"]
    assert codes(patient_id=str(w["linda"].patient_id), sort="oldest") == ["RESTING_HR_HIGH", "STEPS_DECLINE",
                                                                           "SPO2_LOW"]
    assert codes(severity=["critical", "high"], status=["open", "resolved"]) == ["SPO2_LOW", "HR_ABOVE_CEILING"]
    assert codes(rule_code="RESTING_HR_HIGH", status="acknowledged") == ["RESTING_HR_HIGH"]
    assert codes(acknowledged_by=str(w["raman"].user_id)) == ["RESTING_HR_HIGH"]
    start = (w["base"] + timedelta(days=4)).isoformat()
    assert codes(start=start, sort="oldest") == ["STEPS_DECLINE", "DATA_GAP", "SPO2_LOW"]
    page = client.get(f"{API}/alerts", headers=hd, params={"status": ["open", "acknowledged", "resolved"],
                                                          "page_size": 4, "page": 2}).json()
    assert page["meta"] == {"page": 2, "page_size": 4, "total_items": 6, "total_pages": 2} and len(page["items"]) == 2


@sc("AS-36", "Alert detail returns the full timeline (created, notified, acknowledged, resolved) and minutes from "
             "trigger to acknowledgment and resolution", "FR-16")
def test_detail_timeline(client, db, history):
    a = history["alerts"]["HR_ABOVE_CEILING"]
    d = client.get(f"{API}/alerts/{a.alert_id}", headers=h(db, history, "dana")).json()
    assert [e["event_type"] for e in d["events"]] == ["created", "acknowledged", "resolved"]
    assert d["timeline"] == {"minutes_to_acknowledge": 6.0, "minutes_to_escalate": None, "minutes_to_resolve": 40.0}
    assert len(d["notifications"]) == 3 and d["events"][1]["actor_user_id"] == str(history["dana"].user_id)


@sc("AS-37", "Metrics report counts by severity and status and minutes to acknowledge, for clinicians (their team) "
             "and admins (whole program)", "FR-16, FR-26")
def test_metrics(client, db, history):
    params = {"start": (history["base"] - timedelta(days=1)).isoformat()}
    m = client.get(f"{API}/alerts/metrics", headers=h(db, history, "admin"), params=params).json()
    assert m["total"] == 6 and m["by_severity"] == {"critical": 2, "high": 0, "moderate": 3, "low": 1}
    assert m["by_status"]["resolved"] == 1 and m["minutes_to_acknowledge"]["n"] == 2
    assert m["critical_minutes_to_acknowledge"]["median"] == 6.0
    assert client.get(f"{API}/alerts/metrics", headers=h(db, history, "robert_login")).status_code == 403


# ---------------------------------------------------------------- configuration
@sc("AS-38", "Only a physician changes program rules, the reason is audited, and a critical rule cannot be given "
             "a suppression window", "FR-12, NFR-05")
def test_rule_changes(client, db, alert_world):
    w = alert_world
    url = f"{API}/alert-rules/RESTING_SBP_HIGH"
    body = {"default_threshold": 155, "reason": "Program review: earlier warning for post-CABG cohort."}
    assert client.patch(url, headers=h(db, w, "dana"), json=body).status_code == 403
    r = client.patch(url, headers=h(db, w, "raman"), json=body)
    assert r.status_code == 200 and r.json()["default_threshold"] == 155 and r.json()["updated_by"]
    entry = db.scalar(select(AuditLog).where(AuditLog.entity_type == "alert_rules"))
    assert entry.details == {"changed_columns": ["default_threshold"], "reason": body["reason"]}
    bad = client.patch(f"{API}/alert-rules/SPO2_LOW", headers=h(db, w, "raman"),
                       json={"suppression_minutes": 30, "reason": "fewer alerts please"})
    assert bad.status_code == 422
    rules = client.get(f"{API}/alert-rules", headers=h(db, w, "admin")).json()
    assert len(rules) == 12 and {r["rule_type"] for r in rules} == {"threshold", "pattern", "data_gap"}


@sc("AS-39", "A physician issues a new prescription version; the next reading is judged against the new ceiling",
    "FR-02, FR-10")
def test_prescription_endpoint(client, db, alert_world):
    w = alert_world
    url = f"{API}/patients/{w['robert'].patient_id}/prescription"
    rx = {"resting_hr_baseline": 66, "target_hr_min": 100, "target_hr_max": 120, "hr_ceiling": 140,
          "max_exercise_sbp": 190, "notes": "Progressed after week 6."}
    assert client.put(url, headers=h(db, w, "dana"), json=rx).status_code == 403
    r = client.put(url, headers=h(db, w, "raman"), json=rx)
    assert r.status_code == 201 and r.json()["version"] == 2
    assert client.get(url, headers=h(db, w, "robert_login")).json()["hr_ceiling"] == 140
    bad = client.put(url, headers=h(db, w, "raman"), json={**rx, "hr_ceiling": 110})
    assert bad.status_code == 422
    res = client.post(f"{API}/patients/{w['robert'].patient_id}/vitals/batch", headers=h(db, w, "robert_login"),
                      json=hr_batch(w, [134, 136, 138], key="rx"))
    assert res.json()["alerts_raised"] == 0


@sc("AS-40", "Patient-specific thresholds need a clinical reason, are refused for prescription-driven rules, and "
             "removing one falls back to the default", "FR-10")
def test_patient_thresholds(client, db, alert_world):
    w = alert_world
    url = f"{API}/patients/{w['robert'].patient_id}/alert-thresholds"
    eff = {t["rule_code"]: t for t in client.get(url, headers=h(db, w, "dana")).json()}
    assert eff["HR_ABOVE_CEILING"]["source"] == "prescription" and eff["RESTING_HR_HIGH"]["source"] == "default"
    r = client.post(url, headers=h(db, w, "dana"), json={"rule_code": "RESTING_HR_HIGH", "threshold_value": 90,
                                                          "reason": "Beta-blocker; resting HR normally in the 60s."})
    eff = {t["rule_code"]: t for t in r.json()}
    assert r.status_code == 201 and eff["RESTING_HR_HIGH"]["threshold"] == 90 and eff["RESTING_HR_HIGH"]["source"] == \
        "override"
    assert client.post(url, headers=h(db, w, "dana"), json={"rule_code": "HR_ABOVE_CEILING", "threshold_value": 160,
                                                            "reason": "athlete"}).status_code == 422
    assert client.post(url, headers=h(db, w, "dana"), json={"rule_code": "RESTING_HR_HIGH", "threshold_value": 90,
                                                            "reason": "x"}).status_code == 422
    assert client.delete(f"{url}/RESTING_HR_HIGH", headers=h(db, w, "dana")).status_code == 204
    eff = {t["rule_code"]: t for t in client.get(url, headers=h(db, w, "dana")).json()}
    assert eff["RESTING_HR_HIGH"]["source"] == "default"
    assert client.get(url, headers=h(db, w, "marcus")).status_code == 404


@sc("AS-41", "Escalation policies are validated: critical must escalate within 30 minutes, only low may use the "
             "digest, and the dashboard channel is required", "FR-15")
def test_policy_updates(client, db, alert_world):
    w = alert_world
    hd = h(db, w, "admin")
    ok = {"ack_timeout_minutes": 10, "escalate_to": "supervising_physician", "max_escalation_level": 2,
          "channels": ["dashboard", "sms"], "reason": "Drill review: tighten response."}
    assert client.put(f"{API}/escalation-policies/critical", headers=hd, json=ok).status_code == 200
    assert client.put(f"{API}/escalation-policies/critical", headers=hd,
                      json={**ok, "ack_timeout_minutes": 45}).status_code == 422
    assert client.put(f"{API}/escalation-policies/high", headers=hd,
                      json={**ok, "deliver_as_digest": True}).status_code == 422
    assert client.put(f"{API}/escalation-policies/high", headers=hd,
                      json={**ok, "channels": ["email"]}).status_code == 422
    assert client.put(f"{API}/escalation-policies/high", headers=h(db, w, "dana"), json=ok).status_code == 403
    pols = client.get(f"{API}/escalation-policies", headers=hd).json()
    assert [p["severity"] for p in pols] == ["critical", "high", "moderate", "low"] and pols[0]["ack_timeout_minutes"] == 10


@sc("AS-50", "Uploading a day of activity re-checks trend rules, so a step decline alerts without waiting for the "
             "scheduled job", "FR-11")
def test_activity_upload_triggers_patterns(client, db, alert_world):
    w = alert_world
    today = datetime.now(ZoneInfo("America/Denver")).date()
    for i in range(2, 15):
        d = today - timedelta(days=i)
        db.add(DailyActivity(patient_id=w["linda"].patient_id, activity_date=d, steps=3000 if i <= 7 else 8000,
                             active_minutes=20))
    db.commit()
    r = client.put(f"{API}/patients/{w['linda'].patient_id}/daily-activity/{today - timedelta(days=1)}",
                   headers=h(db, w, "linda_login"), json={"steps": 2900, "active_minutes": 18})
    assert r.status_code == 201
    codes = {a.rule.rule_code for a in db.scalars(select(Alert).where(Alert.patient_id == w["linda"].patient_id))}
    assert "STEPS_DECLINE" in codes


def test_jobs_endpoint_and_notifications(client, db, raised):
    w = raised
    assert client.post(f"{API}/alerts/jobs/dispatch", headers=h(db, w, "dana")).status_code == 403
    r = client.post(f"{API}/alerts/jobs/dispatch", headers=h(db, w, "it"))
    assert r.status_code == 200 and r.json()["affected"] == 3
    assert client.post(f"{API}/alerts/jobs/escalations", headers=h(db, w, "admin")).json()["affected"] == 0
    mine = client.get(f"{API}/notifications", headers=h(db, w, "dana"), params={"unread_only": True}).json()
    assert mine["meta"]["total_items"] == 3 and {n["channel"] for n in mine["items"]} == {"dashboard", "email", "sms"}
    assert {n["status"] for n in mine["items"]} == {"sent"}
    nid = mine["items"][0]["notification_id"]
    assert client.post(f"{API}/notifications/{nid}/read", headers=h(db, w, "dana")).json()["read_at"]
    assert client.post(f"{API}/notifications/{nid}/read", headers=h(db, w, "raman")).status_code == 404
    # no exercise since enrollment for robert and linda in this fixture, so missed-session alerts appear
    job = client.post(f"{API}/alerts/jobs/patterns", headers=h(db, w, "admin")).json()
    assert job["affected"] >= 1


def test_alert_status_enum_and_health(client, db, alert_world):
    body = client.get(f"{API}/health").json()
    assert body["alert_workers"] is False and body["stream_subscribers"] == 0
    assert {s.value for s in AlertStatus} == {"open", "acknowledged", "escalated", "resolved", "suppressed"}
    _ = date
