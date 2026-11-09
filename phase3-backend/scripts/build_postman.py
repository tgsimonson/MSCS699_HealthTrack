"""generate the postman collection and environment in postman/ (run once after changing endpoints)"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "postman"
NS = uuid.UUID("6f1c2a9e-3b7d-4c55-9a0e-2d8f41b7c903")


def tests(*lines: str) -> list[dict]:
    return [{"listen": "test", "script": {"type": "text/javascript", "exec": list(lines)}}]


def status_is(code: int, extra: tuple[str, ...] = ()) -> list[dict]:
    return tests(f'pm.test("status is {code}", () => pm.response.to.have.status({code}));', *extra)


def problem(code: int) -> list[dict]:
    return status_is(code, (
        'pm.test("problem+json body", () => {',
        '  pm.expect(pm.response.headers.get("Content-Type")).to.include("application/problem+json");',
        '  const b = pm.response.json(); pm.expect(b).to.have.property("request_id"); pm.expect(b.status).to.eql(' + str(code) + ');',
        '});'))


def req(name: str, method: str, path: str, *, body=None, form=None, token: str | None = "accessToken",  # noqa: ANN001
        query: dict | None = None, ev=None, desc: str = "") -> dict:  # noqa: ANN001
    url = {"raw": "{{baseUrl}}" + path + ("?" + "&".join(f"{k}={v}" for k, v in query.items()) if query else ""),
           "host": ["{{baseUrl}}"], "path": [p for p in path.strip("/").split("/")]}
    if query:
        url["query"] = [{"key": k, "value": str(v)} for k, v in query.items()]
    r: dict = {"method": method, "header": [], "url": url, "description": desc}
    if token:
        r["auth"] = {"type": "bearer", "bearer": [{"key": "token", "value": "{{" + token + "}}", "type": "string"}]}
    else:
        r["auth"] = {"type": "noauth"}
    if body is not None:
        r["header"].append({"key": "Content-Type", "value": "application/json"})
        r["body"] = {"mode": "raw", "raw": json.dumps(body, indent=2), "options": {"raw": {"language": "json"}}}
    if form is not None:
        r["body"] = {"mode": "urlencoded", "urlencoded": [{"key": k, "value": v, "type": "text"} for k, v in form.items()]}
    return {"name": name, "request": r, "event": ev or [], "_postman_id": str(uuid.uuid5(NS, name + method + path))}


def login(name: str, email_var: str, token_var: str, refresh_var: str | None = None) -> dict:
    lines = ['pm.test("status is 200", () => pm.response.to.have.status(200));',
             "const b = pm.response.json();",
             f'pm.collectionVariables.set("{token_var}", b.access_token);',
             'pm.test("token issued", () => pm.expect(b.access_token).to.be.a("string"));']
    if refresh_var:
        lines.append(f'pm.collectionVariables.set("{refresh_var}", b.refresh_token);')
    return req(name, "POST", "/api/v1/auth/token", token=None,
               form={"grant_type": "password", "username": "{{" + email_var + "}}", "password": "{{password}}"},
               ev=tests(*lines), desc="OAuth2 password grant. Saves the access token for later requests.")


P = "/api/v1/patients/{{patientId}}"
now_js = ['const now = new Date();', 'pm.collectionVariables.set("nowIso", now.toISOString());',
          'pm.collectionVariables.set("today", now.toISOString().slice(0, 10));',
          'pm.collectionVariables.set("weekAgo", new Date(now - 7*864e5).toISOString().slice(0, 10));',
          'pm.collectionVariables.set("dayAgoIso", new Date(now - 864e5).toISOString());',
          '// one key prefix per collection run, so the duplicate-key test sends a true duplicate',
          'if (pm.info.iteration === 0 && pm.info.requestName === "Health check") {',
          '  pm.collectionVariables.set("runKey", "pm-" + now.getTime()); }']

collection = {
    "info": {"_postman_id": str(uuid.uuid5(NS, "healthtrack-phase3")), "name": "HealthTrack API (Phase 3)",
             "description": "Requests for every Phase 3 endpoint with assertions. Run the folders in order with the "
                            "Collection Runner against a freshly seeded database (python -m scripts.seed). Login "
                            "requests save tokens into collection variables automatically.",
             "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},
    "event": [{"listen": "prerequest", "script": {"type": "text/javascript", "exec": now_js}}],
    "variable": [
        {"key": "baseUrl", "value": "http://localhost:8000"},
        {"key": "password", "value": "HealthTrack-Demo-2026!"},
        {"key": "clinicianEmail", "value": "marcus.lee@healthtrack.example"},
        {"key": "otherClinicianEmail", "value": "dana.whitfield@healthtrack.example"},
        {"key": "adminEmail", "value": "karen.holt@healthtrack.example"},
        {"key": "itAdminEmail", "value": "jordan.pike@healthtrack.example"},
        {"key": "patientEmail", "value": "t.reed@mail.example"},
        {"key": "physicianId", "value": "00000000-0000-4000-a000-000000000004"},
        {"key": "clinicianId", "value": "00000000-0000-4000-a000-000000000002"},
        {"key": "patientId", "value": "00000000-0000-4000-b000-000000000005"},
        {"key": "otherPatientId", "value": "00000000-0000-4000-b000-000000000001"},
        {"key": "bandId", "value": "00000000-0000-4000-c000-000000000051"},
        {"key": "cuffId", "value": "00000000-0000-4000-c000-000000000052"},
        {"key": "trackerId", "value": "00000000-0000-4000-c000-000000000054"},
        *[{"key": k, "value": ""} for k in ("accessToken", "refreshToken", "patientToken", "otherClinicianToken",
                                            "adminToken", "itToken", "newPatientId", "vitalId", "nowIso", "today",
                                            "weekAgo", "dayAgoIso", "runKey")]],
    "item": [
        {"name": "0 System", "item": [req("Health check", "GET", "/api/v1/health", token=None, ev=status_is(200))]},
        {"name": "1 Auth", "item": [
            login("Log in as clinician (Marcus Lee)", "clinicianEmail", "accessToken", "refreshToken"),
            login("Log in as patient (Thomas Reed)", "patientEmail", "patientToken"),
            login("Log in as other clinician (Dana Whitfield)", "otherClinicianEmail", "otherClinicianToken"),
            login("Log in as admin (Karen Holt)", "adminEmail", "adminToken"),
            login("Log in as IT admin (Jordan Pike)", "itAdminEmail", "itToken"),
            req("Current user", "GET", "/api/v1/auth/me", ev=status_is(200, (
                'pm.test("is clinician", () => pm.expect(pm.response.json().role).to.eql("clinician"));',))),
            req("Rotate refresh token", "POST", "/api/v1/auth/refresh", token=None,
                body={"refresh_token": "{{refreshToken}}"},
                ev=tests('pm.test("status is 200", () => pm.response.to.have.status(200));',
                         'const b = pm.response.json();',
                         'pm.collectionVariables.set("oldRefresh", pm.collectionVariables.get("refreshToken"));',
                         'pm.collectionVariables.set("accessToken", b.access_token);',
                         'pm.collectionVariables.set("refreshToken", b.refresh_token);')),
            req("Wrong password is 401", "POST", "/api/v1/auth/token", token=None,
                form={"username": "{{clinicianEmail}}", "password": "wrong-password"}, ev=problem(401)),
            req("No token is 401", "GET", "/api/v1/auth/me", token=None, ev=problem(401)),
        ]},
        {"name": "2 Patients", "item": [
            req("List my patients", "GET", "/api/v1/patients", query={"page_size": 50}, ev=status_is(200, (
                'pm.test("scoped to care team", () => {',
                '  const names = pm.response.json().items.map(p => p.last_name);',
                '  pm.expect(names).to.include("Reed"); pm.expect(names).to.not.include("Alvarez"); });',))),
            req("Search by name", "POST", "/api/v1/patients/search", body={"q": "reed"}, ev=status_is(200)),
            req("Get patient", "GET", P, ev=status_is(200)),
            req("Care team", "GET", P + "/care-team", ev=status_is(200)),
            req("Register patient", "POST", "/api/v1/patients", body={
                "mrn": "HT-PM{{$randomInt}}", "first_name": "Grace", "last_name": "Morales",
                "date_of_birth": "1963-02-11", "sex": "female", "qualifying_event": "pci",
                "qualifying_event_date": "2026-10-19", "referral_date": "2026-10-27", "clinical_risk_category": "low",
                "primary_clinician_id": "{{clinicianId}}", "supervising_physician_id": "{{physicianId}}"},
                ev=status_is(201, ('pm.collectionVariables.set("newPatientId", pm.response.json().patient_id);',))),
            req("Update patient (pause)", "PATCH", "/api/v1/patients/{{newPatientId}}",
                body={"program_status": "paused", "enrollment_date": "2026-10-28"}, ev=status_is(200)),
            req("Invalid update is 422", "PATCH", "/api/v1/patients/{{newPatientId}}",
                body={"target_sessions": 0}, ev=problem(422)),
            req("Out-of-scope patient is 404", "GET", "/api/v1/patients/{{otherPatientId}}", ev=problem(404)),
            req("Patient reads own record", "GET", P, token="patientToken", ev=status_is(200)),
            req("Patient cannot list patients (403)", "GET", "/api/v1/patients", token="patientToken", ev=problem(403)),
            req("IT admin cannot read patients (403)", "GET", P, token="itToken", ev=problem(403)),
            req("Admin soft-deletes new patient", "DELETE", "/api/v1/patients/{{newPatientId}}", token="adminToken",
                ev=status_is(204)),
        ]},
        {"name": "3 Vital Signs", "item": [
            req("Patient app posts a reading", "POST", P + "/vitals", token="patientToken", body={
                "recorded_at": "{{nowIso}}", "context": "rest", "heart_rate": 68, "device_id": "{{bandId}}",
                "idempotency_key": "{{runKey}}-single"},
                ev=status_is(201, ('pm.collectionVariables.set("vitalId", pm.response.json().vital_id);',
                                   'pm.test("quality valid", () => pm.expect(pm.response.json().quality).to.eql("valid"));'))),
            req("Duplicate idempotency key is 409", "POST", P + "/vitals", token="patientToken", body={
                "recorded_at": "{{nowIso}}", "context": "rest", "heart_rate": 68, "device_id": "{{bandId}}",
                "idempotency_key": "{{runKey}}-single"}, ev=problem(409)),
            req("Out-of-range heart rate is 422", "POST", P + "/vitals", token="patientToken", body={
                "recorded_at": "{{nowIso}}", "context": "rest", "heart_rate": 400, "device_id": "{{bandId}}"},
                ev=problem(422)),
            req("Batch upload", "POST", P + "/vitals/batch", token="patientToken", body={"readings": [
                {"recorded_at": "{{dayAgoIso}}", "context": "exercise", "heart_rate": 112, "device_id": "{{bandId}}",
                 "idempotency_key": "{{runKey}}-b1"},
                {"recorded_at": "{{dayAgoIso}}", "context": "recovery", "systolic_bp": 138, "diastolic_bp": 80,
                 "device_id": "{{cuffId}}", "idempotency_key": "{{runKey}}-b2"}]},
                ev=status_is(200, ('pm.test("2 accepted", () => pm.expect(pm.response.json().accepted).to.eql(2));',))),
            req("Clinician manual entry", "POST", P + "/vitals", body={
                "recorded_at": "{{nowIso}}", "context": "rest", "systolic_bp": 132, "diastolic_bp": 82,
                "source": "manual"}, ev=status_is(201)),
            req("Query last 24 hours", "GET", P + "/vitals", ev=status_is(200)),
            req("Query 7 days, exercise only", "GET", P + "/vitals",
                query={"start": "{{weekAgo}}T00:00:00Z", "end": "{{today}}T23:59:59Z", "context": "exercise",
                       "page_size": 100}, ev=status_is(200)),
            req("Latest readings", "GET", P + "/vitals/latest", ev=status_is(200)),
            req("Daily summary", "GET", P + "/vitals/daily-summary",
                query={"start_date": "{{weekAgo}}", "end_date": "{{today}}"}, ev=status_is(200)),
            req("Get one reading", "GET", "/api/v1/vitals/{{vitalId}}", ev=status_is(200)),
            req("Mark reading as artifact", "PATCH", "/api/v1/vitals/{{vitalId}}", body={"quality": "artifact"},
                ev=status_is(200)),
            req("Other clinician cannot see it (404)", "GET", "/api/v1/vitals/{{vitalId}}", token="otherClinicianToken",
                ev=problem(404)),
            req("Delete reading entered in error", "DELETE", "/api/v1/vitals/{{vitalId}}", ev=status_is(204)),
        ]},
        {"name": "4 Activity and Devices", "item": [
            req("Record today's activity", "PUT", P + "/daily-activity/{{today}}", token="patientToken", body={
                "steps": 7046, "active_minutes": 48, "sedentary_minutes": 552, "resting_hr": 64, "distance_m": 5120,
                "device_id": "{{trackerId}}"},
                ev=tests('pm.test("201 or 200", () => pm.expect(pm.response.code).to.be.oneOf([200, 201]));')),
            req("Get today's activity", "GET", P + "/daily-activity/{{today}}", ev=status_is(200)),
            req("Activity history", "GET", P + "/daily-activity", query={"start_date": "{{weekAgo}}",
                                                                         "end_date": "{{today}}"}, ev=status_is(200)),
            req("Weekly summary", "GET", P + "/daily-activity/summary", query={"start_date": "{{weekAgo}}"},
                ev=status_is(200)),
            req("Invalid activity is 422", "PUT", P + "/daily-activity/{{today}}", token="patientToken",
                body={"steps": 10, "active_minutes": 1000, "sedentary_minutes": 600}, ev=problem(422)),
            req("List devices", "GET", P + "/devices", ev=status_is(200)),
        ]},
        {"name": "5 Session end", "item": [
            req("Reusing rotated refresh token is 401", "POST", "/api/v1/auth/refresh", token=None,
                body={"refresh_token": "{{oldRefresh}}"}, ev=problem(401),
                desc="Reuse detection revokes every session for the account."),
            req("Old access token now rejected", "GET", "/api/v1/auth/me", ev=problem(401)),
        ]},
    ],
}

environment = {"id": str(uuid.uuid5(NS, "env")), "name": "HealthTrack local",
               "values": [{"key": "baseUrl", "value": "http://localhost:8000", "enabled": True}],
               "_postman_variable_scope": "environment"}

if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    (OUT / "HealthTrack_Phase3.postman_collection.json").write_text(json.dumps(collection, indent=2))
    (OUT / "HealthTrack_local.postman_environment.json").write_text(json.dumps(environment, indent=2))
    n = sum(len(f["item"]) for f in collection["item"])
    print(f"wrote postman collection with {n} requests")
