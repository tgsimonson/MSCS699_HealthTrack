"""patient endpoints: crud, search, scoping, role matrix, and audit"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import AuditLog
from app.models.enums import AuditAction
from tests.conftest import auth_header

BASE = "/api/v1/patients"


def new_patient_body(world, **kw):  # noqa: ANN001, ANN003, ANN201
    body = {"mrn": f"HT-N{uuid.uuid4().int % 10**6:06d}", "first_name": "Grace", "last_name": "Morales",
            "date_of_birth": "1963-02-11", "sex": "female", "qualifying_event": "pci",
            "qualifying_event_date": "2026-10-19", "referral_date": "2026-10-27", "clinical_risk_category": "low",
            "primary_clinician_id": str(world["dana"].user_id),
            "supervising_physician_id": str(world["raman"].user_id)}
    body.update(kw)
    return body


class TestCreate:
    def test_clinician_creates_patient(self, client, db, world):
        r = client.post(BASE, json=new_patient_body(world), headers=auth_header(db, world["dana"]))
        assert r.status_code == 201
        pid = r.json()["patient_id"]
        assert r.headers["location"] == f"/api/v1/patients/{pid}"
        team = client.get(f"{BASE}/{pid}/care-team", headers=auth_header(db, world["dana"])).json()
        assert {m["team_role"] for m in team} == {"primary_clinician", "supervising_physician"}

    def test_duplicate_mrn_409(self, client, db, world):
        r = client.post(BASE, json=new_patient_body(world, mrn=world["robert"].mrn), headers=auth_header(db, world["admin"]))
        assert r.status_code == 409 and r.json()["title"] == "Conflict"

    def test_validation_errors_list_each_field(self, client, db, world):
        r = client.post(BASE, json=new_patient_body(world, mrn="bad", phone="5551212", target_sessions=0),
                        headers=auth_header(db, world["admin"]))
        assert r.status_code == 422
        fields = {e["field"] for e in r.json()["errors"]}
        assert {"mrn", "phone", "target_sessions"} <= fields

    def test_unknown_field_rejected(self, client, db, world):
        r = client.post(BASE, json=new_patient_body(world, is_admin=True), headers=auth_header(db, world["admin"]))
        assert r.status_code == 422

    def test_supervisor_must_be_physician(self, client, db, world):
        r = client.post(BASE, json=new_patient_body(world, supervising_physician_id=str(world["marcus"].user_id)),
                        headers=auth_header(db, world["admin"]))
        assert r.status_code == 422 and r.json()["errors"][0]["field"] == "supervising_physician_id"

    @pytest.mark.parametrize("who", ["robert_login", "it"])
    def test_patients_and_it_cannot_create(self, client, db, world, who):
        assert client.post(BASE, json=new_patient_body(world), headers=auth_header(db, world[who])).status_code == 403


class TestReadAndScope:
    @pytest.mark.parametrize("who,patient,expected", [
        ("robert_login", "robert", 200), ("robert_login", "linda", 404),
        ("dana", "robert", 200), ("dana", "thomas", 404),
        ("marcus", "thomas", 200), ("marcus", "robert", 404),
        ("raman", "thomas", 200), ("admin", "thomas", 200), ("it", "robert", 403)])
    def test_get_matrix(self, client, db, world, who, patient, expected):
        r = client.get(f"{BASE}/{world[patient].patient_id}", headers=auth_header(db, world[who]))
        assert r.status_code == expected

    def test_out_of_scope_is_404_and_audited_as_denied(self, client, db, world):
        r = client.get(f"{BASE}/{world['thomas'].patient_id}", headers=auth_header(db, world["dana"]))
        assert r.status_code == 404 and r.json()["detail"] == "patient not found"
        denied = db.scalar(select(AuditLog).where(AuditLog.outcome == "denied",
                                                  AuditLog.actor_user_id == world["dana"].user_id))
        assert denied is not None and denied.patient_id == world["thomas"].patient_id

    def test_missing_patient_404(self, client, db, world):
        assert client.get(f"{BASE}/{uuid.uuid4()}", headers=auth_header(db, world["admin"])).status_code == 404

    def test_malformed_id_422(self, client, db, world):
        assert client.get(f"{BASE}/not-a-uuid", headers=auth_header(db, world["admin"])).status_code == 422

    def test_list_is_scoped_and_paginated(self, client, db, world):
        r = client.get(BASE, params={"page_size": 1}, headers=auth_header(db, world["dana"]))
        assert r.status_code == 200
        body = r.json()
        assert body["meta"] == {"page": 1, "page_size": 1, "total_items": 2, "total_pages": 2}
        assert body["items"][0]["last_name"] == "Alvarez"

    def test_list_filters_and_sort(self, client, db, world):
        h = auth_header(db, world["raman"])
        r = client.get(BASE, params={"sort": "-last_name"}, headers=h)
        assert [p["last_name"] for p in r.json()["items"]] == ["Reed", "Chen", "Alvarez"]
        r = client.get(BASE, params={"clinician_id": str(world["marcus"].user_id)}, headers=h)
        assert [p["last_name"] for p in r.json()["items"]] == ["Reed"]
        assert client.get(BASE, params={"program_status": "graduated"}, headers=h).json()["meta"]["total_items"] == 0

    def test_page_size_capped(self, client, db, world):
        assert client.get(BASE, params={"page_size": 500}, headers=auth_header(db, world["admin"])).status_code == 422

    def test_patients_cannot_list(self, client, db, world):
        assert client.get(BASE, headers=auth_header(db, world["robert_login"])).status_code == 403

    def test_search_in_body_and_scoped(self, client, db, world):
        r = client.post(f"{BASE}/search", json={"q": "che"}, headers=auth_header(db, world["dana"]))
        assert [p["first_name"] for p in r.json()["items"]] == ["Linda"]
        r = client.post(f"{BASE}/search", json={"q": "reed"}, headers=auth_header(db, world["dana"]))
        assert r.json()["items"] == []
        assert client.post(f"{BASE}/search", json={"q": "r"}, headers=auth_header(db, world["dana"])).status_code == 422


class TestUpdateDelete:
    def test_clinician_updates_and_audit_stores_column_names_only(self, client, db, world):
        r = client.patch(f"{BASE}/{world['robert'].patient_id}", json={"phone": "+17195550999", "program_status": "paused"},
                         headers=auth_header(db, world["dana"]))
        assert r.status_code == 200 and r.json()["program_status"] == "paused"
        entry = db.scalar(select(AuditLog).where(AuditLog.action == AuditAction.update)
                          .order_by(AuditLog.audit_id.desc()))
        assert sorted(entry.details["changed_columns"]) == ["phone", "program_status"]
        assert "5550999" not in str(entry.details)

    def test_patient_may_edit_contact_fields_only(self, client, db, world):
        h = auth_header(db, world["robert_login"])
        assert client.patch(f"{BASE}/{world['robert'].patient_id}", json={"postal_code": "80921"}, headers=h).status_code == 200
        r = client.patch(f"{BASE}/{world['robert'].patient_id}", json={"program_status": "withdrawn"}, headers=h)
        assert r.status_code == 403

    def test_rule_violation_on_update_is_422(self, client, db, world):
        r = client.patch(f"{BASE}/{world['robert'].patient_id}", json={"clinical_risk_category": "high"},
                         headers=auth_header(db, world["dana"]))
        assert r.status_code == 422 and "low or moderate" in r.json()["detail"]

    def test_graduate_requires_date(self, client, db, world):
        h = auth_header(db, world["dana"])
        assert client.patch(f"{BASE}/{world['robert'].patient_id}", json={"program_status": "graduated"},
                            headers=h).status_code == 422
        r = client.patch(f"{BASE}/{world['robert'].patient_id}",
                         json={"program_status": "graduated", "graduation_date": "2026-12-01"}, headers=h)
        assert r.status_code == 200

    def test_only_admin_soft_deletes(self, client, db, world):
        pid = world["linda"].patient_id
        assert client.delete(f"{BASE}/{pid}", headers=auth_header(db, world["dana"])).status_code == 403
        assert client.delete(f"{BASE}/{pid}", headers=auth_header(db, world["admin"])).status_code == 204
        assert client.get(f"{BASE}/{pid}", headers=auth_header(db, world["admin"])).status_code == 404
