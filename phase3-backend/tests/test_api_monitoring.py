"""vital sign, activity, and device endpoints"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models import AuditLog
from tests.conftest import ago, auth_header


def vurl(world, who="robert"):  # noqa: ANN001, ANN201
    return f"/api/v1/patients/{world[who].patient_id}/vitals"


def body(world, device="band", **kw):  # noqa: ANN001, ANN003, ANN201
    b = {"recorded_at": ago(minutes=3).isoformat(), "context": "rest", "heart_rate": 72,
         "device_id": str(world[device].device_id)}
    b.update(kw)
    return b


class TestVitalCollection:
    def test_patient_app_posts_reading(self, client, db, world):
        r = client.post(vurl(world), json=body(world, idempotency_key="hb-1-20261021"),
                        headers=auth_header(db, world["robert_login"]))
        assert r.status_code == 201 and r.json()["quality"] == "valid"
        assert r.headers["location"] == f"/api/v1/vitals/{r.json()['vital_id']}"

    def test_suspect_value_stored_and_flagged(self, client, db, world):
        r = client.post(vurl(world), json=body(world, heart_rate=241), headers=auth_header(db, world["robert_login"]))
        assert r.status_code == 201 and r.json()["quality"] == "suspect"

    @pytest.mark.parametrize("override,field", [({"heart_rate": 400}, "heart_rate"), ({"context": "sleep"}, "context"),
                                                ({"recorded_at": "2026-10-21T09:00:00"}, "recorded_at")])
    def test_invalid_readings_422_with_field(self, client, db, world, override, field):
        r = client.post(vurl(world), json=body(world, **override), headers=auth_header(db, world["robert_login"]))
        assert r.status_code == 422 and r.json()["errors"][0]["field"] == field

    def test_bp_order_rule(self, client, db, world):
        r = client.post(vurl(world), json=body(world, "cuff", heart_rate=None, systolic_bp=80, diastolic_bp=90),
                        headers=auth_header(db, world["robert_login"]))
        assert r.status_code == 422 and "systolic_bp must be greater" in r.text

    def test_future_reading_rejected(self, client, db, world):
        future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        r = client.post(vurl(world), json=body(world, recorded_at=future), headers=auth_header(db, world["robert_login"]))
        assert r.status_code == 422

    def test_foreign_device_rejected(self, client, db, world):
        r = client.post(vurl(world), json=body(world, "thomas_band"), headers=auth_header(db, world["robert_login"]))
        assert r.status_code == 422 and r.json()["errors"][0]["field"] == "device_id"

    def test_duplicate_idempotency_key_409(self, client, db, world):
        h = auth_header(db, world["robert_login"])
        client.post(vurl(world), json=body(world, idempotency_key="same-key-123"), headers=h)
        assert client.post(vurl(world), json=body(world, idempotency_key="same-key-123"), headers=h).status_code == 409

    def test_clinician_manual_entry_records_author(self, client, db, world):
        r = client.post(vurl(world), json={"recorded_at": ago(minutes=1).isoformat(), "context": "rest",
                                           "systolic_bp": 146, "diastolic_bp": 88, "source": "manual"},
                        headers=auth_header(db, world["dana"]))
        assert r.status_code == 201 and r.json()["entered_by"] == str(world["dana"].user_id)

    def test_patient_cannot_post_manual(self, client, db, world):
        r = client.post(vurl(world), json={"recorded_at": ago(minutes=1).isoformat(), "context": "rest",
                                           "heart_rate": 70, "source": "manual"},
                        headers=auth_header(db, world["robert_login"]))
        assert r.status_code == 403

    @pytest.mark.parametrize("who,target,expected", [("robert_login", "linda", 404), ("marcus", "robert", 404),
                                                     ("admin", "robert", 403), ("it", "robert", 403)])
    def test_write_scope(self, client, db, world, who, target, expected):
        r = client.post(vurl(world, target), json=body(world), headers=auth_header(db, world[who]))
        assert r.status_code == expected

    def test_batch_upload_and_safe_replay(self, client, db, world):
        readings = [body(world, recorded_at=ago(minutes=40 - i).isoformat(), idempotency_key=f"batch-{i:04d}")
                    for i in range(25)]
        h = auth_header(db, world["robert_login"])
        r = client.post(f"{vurl(world)}/batch", json={"readings": readings}, headers=h)
        assert r.status_code == 200 and r.json() == {"accepted": 25, "duplicates": 0, "flagged_suspect": 0,
                                                     "rejected": []}
        again = client.post(f"{vurl(world)}/batch", json={"readings": readings}, headers=h).json()
        assert (again["accepted"], again["duplicates"]) == (0, 25)
        entry = db.scalar(select(AuditLog).where(AuditLog.entity_type == "vital_signs")
                          .order_by(AuditLog.audit_id.desc()))
        assert entry.details["batch"] is True and entry.details["duplicates"] == 25

    def test_batch_with_mixed_measurements(self, client, db, world):
        readings = [body(world, recorded_at=ago(minutes=9).isoformat()),
                    body(world, "cuff", recorded_at=ago(minutes=8).isoformat(), heart_rate=None, systolic_bp=138,
                         diastolic_bp=80)]
        r = client.post(f"{vurl(world)}/batch", json={"readings": readings}, headers=auth_header(db, world["robert_login"]))
        assert r.status_code == 200 and r.json()["accepted"] == 2

    def test_batch_limits(self, client, db, world):
        h = auth_header(db, world["robert_login"])
        assert client.post(f"{vurl(world)}/batch", json={"readings": []}, headers=h).status_code == 422
        assert client.post(f"{vurl(world)}/batch", json={"readings": [body(world)] * 501}, headers=h).status_code == 422


class TestVitalQueries:
    @pytest.fixture
    def seeded(self, client, db, world):
        h = auth_header(db, world["robert_login"])
        for i, hr in enumerate((70, 110, 115, 240)):
            client.post(vurl(world), json=body(world, recorded_at=ago(minutes=50 - i * 10).isoformat(), heart_rate=hr,
                                               context="exercise" if hr in (110, 115) else "rest"), headers=h)
        client.post(vurl(world), json=body(world, "cuff", recorded_at=ago(minutes=5).isoformat(), heart_rate=None,
                                           systolic_bp=126, diastolic_bp=78), headers=h)
        client.post(vurl(world), json=body(world, recorded_at=ago(days=3).isoformat(), heart_rate=66), headers=h)
        return h

    def test_default_window_is_last_24_hours(self, client, world, seeded):
        r = client.get(vurl(world), headers=seeded)
        assert r.json()["meta"]["total_items"] == 5

    def test_filters(self, client, world, seeded):
        start = ago(days=4).isoformat()
        end = ago(seconds=-60).isoformat()
        get = lambda **p: client.get(vurl(world), params={"start": start, "end": end, **p}, headers=seeded).json()  # noqa: E731
        assert get()["meta"]["total_items"] == 6
        assert get(context="exercise")["meta"]["total_items"] == 2
        assert get(metric="blood_pressure")["items"][0]["systolic_bp"] == 126
        assert get(quality="suspect")["items"][0]["heart_rate"] == 240
        assert get(order="oldest")["items"][0]["heart_rate"] == 66

    def test_range_validation(self, client, world, seeded):
        r = client.get(vurl(world), params={"start": "2026-10-10T00:00:00Z", "end": "2026-10-01T00:00:00Z"},
                       headers=seeded)
        assert r.status_code == 422
        r = client.get(vurl(world), params={"start": "2026-01-01T00:00:00Z", "end": "2026-10-01T00:00:00Z"},
                       headers=seeded)
        assert r.status_code == 422 and "92 days" in r.json()["detail"]

    def test_latest_and_daily_summary(self, client, world, seeded):
        latest = client.get(f"{vurl(world)}/latest", headers=seeded).json()
        assert latest["heart_rate"]["heart_rate"] == 115 and latest["blood_pressure"]["systolic_bp"] == 126
        today = datetime.now(timezone.utc).date()
        rows = client.get(f"{vurl(world)}/daily-summary", params={"start_date": str(today - timedelta(days=5)),
                                                                   "end_date": str(today)}, headers=seeded).json()
        assert sum(r["readings"] for r in rows) == 6 and sum(r["flagged_readings"] for r in rows) == 1

    def test_reads_are_audited_with_row_counts(self, client, db, world, seeded):
        client.get(vurl(world), headers=seeded)
        entry = db.scalar(select(AuditLog).where(AuditLog.action == "read", AuditLog.entity_type == "vital_signs")
                          .order_by(AuditLog.audit_id.desc()))
        assert entry.details == {"rows": 5} and entry.patient_id == world["robert"].patient_id

    def test_get_patch_delete_single_reading(self, client, db, world, seeded):
        vid = client.get(vurl(world), headers=seeded).json()["items"][0]["vital_id"]
        assert client.get(f"/api/v1/vitals/{vid}", headers=seeded).status_code == 200
        assert client.get(f"/api/v1/vitals/{vid}", headers=auth_header(db, world["marcus"])).status_code == 404
        assert client.get(f"/api/v1/vitals/{vid}", headers=auth_header(db, world["admin"])).status_code == 403
        assert client.patch(f"/api/v1/vitals/{vid}", json={"quality": "artifact"}, headers=seeded).status_code == 404
        h = auth_header(db, world["dana"])
        r = client.patch(f"/api/v1/vitals/{vid}", json={"quality": "artifact"}, headers=h)
        assert r.status_code == 200 and r.json()["quality"] == "artifact"
        assert client.patch(f"/api/v1/vitals/{vid}", json={"heart_rate": 1}, headers=h).status_code == 422
        assert client.delete(f"/api/v1/vitals/{vid}", headers=h).status_code == 204
        assert client.get(f"/api/v1/vitals/{vid}", headers=h).status_code == 404


class TestActivityAndDevices:
    def aurl(self, world, day="2026-10-21", who="robert"):  # noqa: ANN001, ANN201
        return f"/api/v1/patients/{world[who].patient_id}/daily-activity/{day}"

    def test_put_creates_201_then_replaces_200(self, client, db, world):
        h = auth_header(db, world["robert_login"])
        payload = {"steps": 7046, "active_minutes": 48, "resting_hr": 64, "device_id": str(world["tracker"].device_id)}
        assert client.put(self.aurl(world), json=payload, headers=h).status_code == 201
        r = client.put(self.aurl(world), json={"steps": 8000, "active_minutes": 55}, headers=h)
        assert r.status_code == 200 and r.json()["steps"] == 8000 and r.json()["resting_hr"] is None
        assert client.get(self.aurl(world), headers=h).json()["steps"] == 8000

    def test_invalid_activity(self, client, db, world):
        h = auth_header(db, world["robert_login"])
        assert client.put(self.aurl(world), json={"steps": -1, "active_minutes": 1}, headers=h).status_code == 422
        assert client.put(self.aurl(world), json={"steps": 1, "active_minutes": 1000, "sedentary_minutes": 500},
                          headers=h).status_code == 422
        assert client.put(self.aurl(world, day="2026-13-01"), json={"steps": 1, "active_minutes": 1},
                          headers=h).status_code == 422

    def test_history_summary_and_scope(self, client, db, world):
        h = auth_header(db, world["robert_login"])
        for i in range(5):
            client.put(self.aurl(world, day=str(date(2026, 10, 1) + timedelta(days=i))),
                       json={"steps": 5000 + i * 100, "active_minutes": 30}, headers=h)
        base = f"/api/v1/patients/{world['robert'].patient_id}/daily-activity"
        rows = client.get(base, params={"start_date": "2026-10-02", "end_date": "2026-10-04"}, headers=h).json()
        assert [r["activity_date"] for r in rows] == ["2026-10-02", "2026-10-03", "2026-10-04"]
        s = client.get(f"{base}/summary", params={"start_date": "2026-10-01", "end_date": "2026-10-07"},
                       headers=auth_header(db, world["dana"])).json()
        assert s["days_reported"] == 5 and s["total_steps"] == 26000
        assert client.get(base, headers=auth_header(db, world["marcus"])).status_code == 404
        assert client.get(f"{base}/2026-10-09", headers=h).status_code == 404

    def test_delete_is_clinician_only(self, client, db, world):
        client.put(self.aurl(world), json={"steps": 1, "active_minutes": 1}, headers=auth_header(db, world["robert_login"]))
        assert client.delete(self.aurl(world), headers=auth_header(db, world["robert_login"])).status_code == 403
        assert client.delete(self.aurl(world), headers=auth_header(db, world["dana"])).status_code == 204

    def test_devices(self, client, db, world):
        url = f"/api/v1/patients/{world['linda'].patient_id}/devices"
        dev = {"device_type": "pulse_oximeter", "manufacturer": "Corvane", "model": "OX-1", "serial_number": "OX1-LC-1"}
        assert client.post(url, json=dev, headers=auth_header(db, world["linda_login"])).status_code == 403
        r = client.post(url, json=dev, headers=auth_header(db, world["dana"]))
        assert r.status_code == 201 and r.json()["status"] == "active"
        assert client.post(url, json=dev, headers=auth_header(db, world["dana"])).status_code == 409
        assert len(client.get(url, headers=auth_header(db, world["linda_login"])).json()) == 1


class TestCrossCutting:
    def test_health(self, client):
        r = client.get("/api/v1/health")
        assert r.status_code == 200 and r.json()["status"] == "ok"

    def test_request_id_echoed_and_security_headers(self, client):
        rid = "6f1c2a9e-3b7d-4c55-9a0e-2d8f41b7c903"
        r = client.get("/api/v1/health", headers={"X-Request-ID": rid})
        assert r.headers["x-request-id"] == rid
        assert r.headers["cache-control"] == "no-store" and r.headers["x-content-type-options"] == "nosniff"
        assert client.get("/api/v1/health", headers={"X-Request-ID": "bad\nvalue"}).headers["x-request-id"] != "bad\nvalue"

    def test_unknown_route_problem_json(self, client):
        r = client.get("/api/v1/nope")
        assert r.status_code == 404 and r.headers["content-type"].startswith("application/problem+json")

    def test_unhandled_error_is_500_without_internals(self, client, db, world, monkeypatch):
        from app.repositories import monitoring
        def boom(*a, **k):  # noqa: ANN002, ANN003, ANN202
            raise RuntimeError("secret internal detail")
        monkeypatch.setattr(monitoring.VitalSignRepository, "latest", boom)
        from fastapi.testclient import TestClient
        from app.main import app
        with TestClient(app, raise_server_exceptions=False) as c:
            r = c.get(f"{vurl(world)}/latest", headers=auth_header(db, world["robert_login"]))
        assert r.status_code == 500 and "secret" not in r.text and r.json()["request_id"]

    def test_openapi_documents_errors_and_security(self, client):
        spec = client.get("/api/v1/openapi.json").json()
        op = spec["paths"]["/api/v1/patients/{patient_id}/vitals"]["post"]
        assert {"201", "401", "403", "404", "409", "422"} <= set(op["responses"])
        assert "OAuth2PasswordBearer" in spec["components"]["securitySchemes"]
