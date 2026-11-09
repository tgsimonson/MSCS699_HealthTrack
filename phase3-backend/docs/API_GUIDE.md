# HealthTrack API Usage Guide

Base URL in development: `http://localhost:8000/api/v1`. Interactive documentation: **http://localhost:8000/docs**
(Swagger UI) and `/redoc`. The machine-readable specification is `docs/openapi.json` (also served live at
`/api/v1/openapi.json`). A ready-made Postman collection is in `postman/`.

All sample accounts use the mock password `HealthTrack-Demo-2026!` (synthetic data only).

| Account | Role | Can see |
|---|---|---|
| marcus.lee@healthtrack.example | clinician | Reed, Gonzales, O'Neil |
| dana.whitfield@healthtrack.example | clinician | Alvarez, Chen, Whitaker, Patel |
| priya.raman@healthtrack.example | physician | Alvarez, Chen, Whitaker, Gonzales, Patel |
| karen.holt@healthtrack.example | admin | all patients (demographics only) |
| jordan.pike@healthtrack.example | it_admin | no patient data |
| t.reed@mail.example | patient | own record (Thomas Reed) |

## Workflow 1: log in and keep a session

```bash
curl -s -X POST http://localhost:8000/api/v1/auth/token \
  -d username=marcus.lee@healthtrack.example -d 'password=HealthTrack-Demo-2026!'
```

```json
{"access_token": "eyJhbGciOi...", "token_type": "bearer", "expires_in": 900,
 "refresh_token": "rt_Qm9...", "refresh_expires_in": 43200,
 "user": {"user_id": "00000000-0000-4000-a000-000000000002", "role": "clinician", "first_name": "Marcus",
          "last_name": "Lee", "credentials": "CEP"}}
```

Send `Authorization: Bearer <access_token>` on every other request. Before the 15 minutes run out, exchange the
refresh token:

```bash
curl -s -X POST http://localhost:8000/api/v1/auth/refresh -H 'Content-Type: application/json' \
  -d '{"refresh_token": "rt_Qm9..."}'
```

Each refresh returns a **new** refresh token and revokes the old one. Store the new one. If an old refresh token is
ever presented again, the server assumes it was stolen and revokes every session for the account. `POST /auth/logout`
ends the session immediately, including its unexpired access tokens. Accounts with MFA enabled add `-d mfa_code=123456`
to the login request.

## Workflow 2: register a patient

```bash
curl -s -X POST http://localhost:8000/api/v1/patients -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{
    "mrn": "HT-100009", "first_name": "Grace", "last_name": "Morales", "date_of_birth": "1963-02-11",
    "sex": "female", "qualifying_event": "pci", "qualifying_event_date": "2026-10-19",
    "referral_date": "2026-10-27", "clinical_risk_category": "low",
    "primary_clinician_id": "00000000-0000-4000-a000-000000000002",
    "supervising_physician_id": "00000000-0000-4000-a000-000000000004"}'
```

Returns `201` with the patient and a `Location` header. The patient starts as `referred`; enroll them with
`PATCH /patients/{id}` and `{"program_status": "active", "enrollment_date": "2026-11-02"}`. Graduation needs both
`program_status: graduated` and a `graduation_date`.

## Workflow 3: the patient app uploads readings

Single reading (patient token):

```bash
curl -s -X POST http://localhost:8000/api/v1/patients/00000000-0000-4000-b000-000000000005/vitals \
  -H "Authorization: Bearer $PATIENT_TOKEN" -H 'Content-Type: application/json' -d '{
    "recorded_at": "2026-11-02T09:48:00-07:00", "context": "exercise", "heart_rate": 118,
    "device_id": "00000000-0000-4000-c000-000000000051", "idempotency_key": "hb-5-202611020948"}'
```

After a workout, the app syncs its buffer with `POST .../vitals/batch` (up to 500 readings):

```json
{"accepted": 58, "duplicates": 2, "flagged_suspect": 1, "rejected": []}
```

Always send an `idempotency_key` per reading. If the connection drops mid-upload, resend the whole batch: readings
already stored come back as `duplicates`, and nothing is stored twice. A reading outside physical limits (heart rate
above 300) is rejected with `422`. One that is possible but unlikely (heart rate 240) is stored with
`quality: suspect` so it shows on charts but will never trigger an alert in Phase 4.

## Workflow 4: a clinician reviews a patient

```bash
P=http://localhost:8000/api/v1/patients/00000000-0000-4000-b000-000000000005
curl -s "$P/vitals/latest" -H "Authorization: Bearer $TOKEN"
curl -s "$P/vitals/daily-summary?start_date=2026-10-12&end_date=2026-11-01" -H "Authorization: Bearer $TOKEN"
curl -s "$P/vitals?start=2026-10-21T00:00:00-06:00&end=2026-10-22T00:00:00-06:00&context=exercise&page_size=200" \
  -H "Authorization: Bearer $TOKEN"
curl -s "$P/daily-activity/summary?start_date=2026-10-26" -H "Authorization: Bearer $TOKEN"
```

To mark a bad reading (for example a loose chest strap) without deleting it:
`PATCH /vitals/{vital_id}` with `{"quality": "artifact"}`. Manual entries made in error can be removed with
`DELETE /vitals/{vital_id}`. Clinicians enter readings taken during a telehealth visit with
`POST .../vitals` and `"source": "manual"` (no device needed); the server records who entered them.

## Workflow 5: daily activity

The tracker app writes one row per day with an idempotent `PUT`:

```bash
curl -s -X PUT "$P/daily-activity/2026-11-01" -H "Authorization: Bearer $PATIENT_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"steps": 7046, "active_minutes": 48, "sedentary_minutes": 552, "resting_hr": 64, "distance_m": 5120,
       "device_id": "00000000-0000-4000-c000-000000000054"}'
```

`201` on first write, `200` when replaced. Fields left out of a replace are cleared, so always send the whole day.

## Filtering and paging

| Parameter | Applies to | Notes |
|---|---|---|
| `start`, `end` | vitals | ISO 8601 with offset. `start` inclusive, `end` exclusive, at most 92 days apart. Default: last 24 hours. |
| `start_date`, `end_date` | daily summary, activity | Inclusive calendar dates. |
| `context` | vitals | Repeatable: `?context=exercise&context=cooldown`. |
| `metric` | vitals | `heart_rate`, `blood_pressure`, or `spo2`. |
| `quality` | vitals | `valid`, `suspect`, or `artifact`. |
| `order` | vitals | `newest` (default) or `oldest`. |
| `program_status`, `clinician_id`, `sort` | patient list | `sort` is `last_name`, `enrollment_date`, `created_at`, or prefixed with `-` for descending. |
| `page`, `page_size` | all lists | `page_size` 1 to 200, default 50. Responses carry `meta.total_items` and `meta.total_pages`. |

## Errors

Every error body follows RFC 9457:

```json
{"type": "https://api.healthtrack.example/problems/validation_error", "title": "Validation Error", "status": 422,
 "detail": "One or more fields are invalid.", "instance": "/api/v1/patients/.../vitals",
 "request_id": "6f1c2a9e-3b7d-4c55-9a0e-2d8f41b7c903",
 "errors": [{"field": "heart_rate", "message": "Input should be less than or equal to 300", "code": "less_than_equal"}]}
```

| Status | Meaning | What to do |
|---|---|---|
| 400 | Malformed body | Fix the JSON. |
| 401 | No token, expired token, revoked session, or bad credentials | Refresh, or log in again. |
| 403 | Role cannot perform the action (for example a patient listing patients) | Use an account with the right role. |
| 404 | Not found, **or outside your scope**. The API never confirms that another clinician's patient exists. | Check the id and your care team. |
| 409 | Duplicate MRN, duplicate `idempotency_key`, care team role already filled, duplicate device serial | Treat duplicates as already stored. |
| 422 | Validation failed; `errors` names each field | Fix the listed fields. |
| 423 | Account locked after 5 failed logins | Wait 15 minutes. |
| 429 | Too many login attempts; see `Retry-After` | Back off. |
| 500 | Unexpected server error; details are only in the server log | Report the `request_id`. |
| 503 | Database unavailable | Retry with backoff. |

Every response carries `X-Request-ID` (send your own UUID to correlate) and `X-Response-Time-ms`.
