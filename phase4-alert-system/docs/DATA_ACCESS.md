# HealthTrack Data Access Layer

Technical reference for `app/repositories/`, the layer between the FastAPI routes and the database. Repositories
own every query and write. They know nothing about HTTP, tokens, or roles, except that the patient list and
search accept a `visible_to` user and scope their query to that user's care team.

## Design

| Concern | How it is handled |
|---|---|
| Unit of work | One SQLAlchemy `Session` per request (`app.db.get_db`). Repositories flush; the request commits once at the end, or rolls back on any error. |
| Partial failure | Every write runs inside `db_errors()`, which opens a **savepoint**. A failed write rolls back only that savepoint, so earlier work in the request stays intact and the session stays usable. |
| Error translation | Database exceptions never leave the layer raw. `db_errors()` maps them to domain errors (below) using the constraint name, so the API can return a precise 409 or 422 message. |
| Logging | Each create, update, delete, and failure writes one structured JSON log line with the request id, entity, and ids or column names. Log lines never contain measured values or names. |
| Portability | All queries use SQLAlchemy Core expressions and run unchanged on SQLite and PostgreSQL. The two dialect-specific spots (batch upsert and daily bucketing) branch on `session.bind.dialect.name`. |
| Pagination | `paginate()` runs a `COUNT(*)` over the same filtered statement, then fetches one page with `LIMIT`/`OFFSET`. Page size is capped at 200 by the API. |
| Time | All timestamps are timezone-aware UTC (`UTCDateTime` column type). Naive datetimes are refused at bind time. Ranges are half-open: `start` inclusive, `end` exclusive. |

## Error mapping

| Raised | When | HTTP |
|---|---|---|
| `NotFoundError` | Record missing, or soft-deleted (patients) | 404 |
| `ConflictError` | Unique constraint: duplicate MRN, email, idempotency key, device serial, second current primary clinician | 409 |
| `ValidationFailed` | CHECK constraint, foreign key to a missing row, model validator (`@validates`, `validate_domain`), or a rule the repository checks itself (device ownership, date range length, immutable fields) | 422 |
| `DataAccessError` | `OperationalError` or other driver error (database down, connection lost). Logged at ERROR with a stack trace. | 503 |

Constraint names follow a fixed convention (`ck_<table>_<rule>`, `uq_<table>_<columns>`, `fk_<table>_<column>_<ref>`),
set in `app/models/base.py`. `CONSTRAINT_MESSAGES` in `app/repositories/base.py` turns each into a readable message.
On PostgreSQL the name comes from the driver (`diag.constraint_name`); on SQLite it is parsed from the error text.

## PatientRepository (`patients.py`)

| Method | Purpose | Returns | Errors |
|---|---|---|---|
| `create(data, *, primary_clinician_id, supervising_physician_id, created_by)` | Insert the patient and both required care team assignments in one savepoint. Checks that the clinician is an active clinician or physician, the supervisor an active physician, and any linked login a patient account. | `Patient` | `ValidationFailed`, `ConflictError` (MRN, login) |
| `get(patient_id, *, include_deleted=False)` | Primary-key lookup; soft-deleted patients are hidden unless asked for. | `Patient` | `NotFoundError` |
| `get_by_user(user_id)` | The patient record linked to a patient login. | `Patient \| None` | |
| `list(*, visible_to, program_status, clinician_id, sort, page, page_size)` | Patients scoped to the caller: care team for clinicians and physicians (via an `EXISTS` on current assignments), own record for patients, all for admins, none for IT. Filters by status and primary clinician; sorts by name, enrollment date, or created date. | `PageResult[Patient]` | |
| `search(q, *, visible_to, program_status, page, page_size)` | Case-insensitive match on first name, last name, or MRN, with the same scoping. | `PageResult[Patient]` | |
| `care_team(patient_id, *, include_ended=False)` | Current (or all) care team assignments. | `list[CareTeamAssignment]` | |
| `is_on_care_team(user_id, patient_id)` | True when the user has a current assignment that has started and not ended. Used by every authorization check. | `bool` | |
| `update(patient_id, changes)` | Partial update; skips unchanged fields. | `(Patient, changed_columns)` | `NotFoundError`, `ValidationFailed`, `ConflictError` |
| `soft_delete(patient_id)` | Sets `deleted_at` and moves active patients to `withdrawn`. History is kept. | `Patient` | `NotFoundError` |
| `hard_delete(patient_id)` | Permanent delete with cascade, for test cleanup only. Not exposed by the API. Logged at WARNING. | `None` | `NotFoundError` |

## VitalSignRepository (`monitoring.py`)

| Method | Purpose | Returns | Errors |
|---|---|---|---|
| `create(patient_id, data, *, entered_by)` | Store one reading. Device readings must reference an active device assigned to the same patient; manual readings record `entered_by`. Assigns `quality` with `VitalSign.assess_quality` (values outside soft limits become `suspect`). Updates the device's `last_sync_at`. | `VitalSign` | `ValidationFailed`, `ConflictError` (idempotency key) |
| `bulk_create(patient_id, readings)` | Store up to 500 device readings with **one** multi-row `INSERT ... ON CONFLICT (patient_id, idempotency_key) DO NOTHING ... RETURNING`. Device ownership is checked once per distinct device. Rows with a foreign device or manual source are rejected individually without failing the batch. Replays are counted, not errored. | `{accepted, duplicates, flagged_suspect, rejected[]}` | |
| `get(vital_id)` | Primary-key lookup. | `VitalSign` | `NotFoundError` |
| `list(patient_id, *, start, end, context, metric, quality, newest_first, page, page_size)` | Readings in `[start, end)` with optional filters. Range at most 92 days. Served by index `ix_vital_signs_patient_time (patient_id, recorded_at)`. | `PageResult[VitalSign]` | `ValidationFailed` (range) |
| `latest(patient_id)` | Most recent **valid** heart rate, blood pressure, and SpO2 reading: three `ORDER BY recorded_at DESC LIMIT 1` lookups on the same index. | `dict` | |
| `daily_summary(patient_id, start, end, context)` | Per-UTC-day count, average, min, and max of valid readings, plus a count of flagged readings, computed with `GROUP BY` in the database so one row per day crosses the wire. | `list[dict]` | `ValidationFailed` (range) |
| `update(vital_id, changes)` | Only `context` and `quality` may change; measured values are immutable. | `(VitalSign, changed_columns)` | `ValidationFailed`, `NotFoundError` |
| `delete(vital_id)` | Remove a reading entered in error. Logged at WARNING. | `VitalSign` | `NotFoundError` |

## ActivityRepository (`monitoring.py`)

| Method | Purpose | Returns | Errors |
|---|---|---|---|
| `upsert(patient_id, activity_date, data)` | Create or fully replace one day's totals (primary key `patient_id, activity_date`). Fields omitted from a replace are cleared. Rejects dates more than a day in the future and devices not assigned to the patient. | `(DailyActivity, created)` | `ValidationFailed` |
| `get(patient_id, activity_date)` | One day. | `DailyActivity` | `NotFoundError` |
| `list(patient_id, start, end)` | Days in `[start, end]` inclusive, oldest first (primary-key range scan). | `list[DailyActivity]` | `ValidationFailed` (range) |
| `summary(patient_id, start, end)` | Days reported, total and average steps, active minutes, and average resting heart rate in one aggregate query. | `dict` | `ValidationFailed` (range) |
| `delete(patient_id, activity_date)` / `delete_range(patient_id, start, end)` | Remove one day or a range. | `None` / row count | `NotFoundError` |

## DeviceRepository (`monitoring.py`)

| Method | Purpose | Returns | Errors |
|---|---|---|---|
| `register(patient_id, data)` | Create a device assigned to the patient with status `active`. | `Device` | `ConflictError` (manufacturer and serial) |
| `list_for_patient(patient_id)` / `get(device_id)` | Lookups. | `list[Device]` / `Device` | `NotFoundError` |
| `ensure_owned(device_id, patient_id)` | Guard used before any reading or activity write. | `None` | `ValidationFailed` |

## UserRepository (`users.py`) and AuditRepository (`audit.py`)

| Method | Purpose |
|---|---|
| `UserRepository.get_by_email(email)` | Case-insensitive, whitespace-trimmed lookup used by login. |
| `record_failed_login(user, max_attempts, lockout)` / `record_successful_login(user)` | Track failures; the fifth sets `locked_until`. Success clears the counter and stamps `last_login_at`. |
| `create_session`, `get_session_by_hash`, `revoke_session`, `revoke_all_sessions`, `session_is_live` | Refresh-token sessions. Only the SHA-256 hash of a refresh token is stored. Rotation links old to new (`replaced_by`); reuse of a revoked token triggers `revoke_all_sessions`. |
| `AuditRepository.record(action, entity_type, *, actor, entity_id, patient_id, outcome, details)` | Append one audit row with the request id. `details` holds counts and column names only. The model refuses updates and deletes. |
| `AuditRepository.list(...)` | Filter by patient, actor, action, and time range, newest first. |

## Query plan and indexes

| Access pattern | Index | Notes |
|---|---|---|
| Readings for a patient in a time window (list, latest, daily summary) | `ix_vital_signs_patient_time (patient_id, recorded_at)` | The dominant query. `scripts/benchmark.py` times it with and without this index. |
| Readings by device | `ix_vital_signs_device (device_id)` | Added by migration 0002 with the device registry. |
| Duplicate detection on upload | `uq_vital_signs_patient_id_idempotency_key` | Also the conflict target for the batch `ON CONFLICT DO NOTHING`. |
| Care team scope check | `ix_care_team_user_current (user_id, patient_id) WHERE end_date IS NULL` | Partial index: only current assignments are indexed. |
| One current primary clinician and supervisor | `uq_care_team_one_current_role (patient_id, team_role) WHERE ...` | Partial unique index enforces the rule in the database. |
| Patient worklist by status | `ix_patients_status_active (program_status) WHERE deleted_at IS NULL` | Soft-deleted rows stay out of the index. |
| Activity by date range | Primary key `(patient_id, activity_date)` | No extra index needed. |
| Audit by patient or actor over time | `ix_audit_log_patient_time`, `ix_audit_log_actor_time` | |

Other choices: batch ingestion uses one statement per batch instead of 500; daily summaries aggregate in SQL;
patient lists use `EXISTS` subqueries rather than joins so a patient with several care team rows is never duplicated;
PostgreSQL connections are pooled (`pool_size=10`, `max_overflow=20`, `pool_pre_ping`); SQLite runs in WAL mode with
foreign keys enforced.

## Usage example

```python
from datetime import datetime, timedelta, timezone
from app.db import SessionLocal
from app.repositories import VitalSignRepository

with SessionLocal() as db:
    vitals = VitalSignRepository(db)
    end = datetime.now(timezone.utc)
    page = vitals.list(patient_id, start=end - timedelta(days=7), end=end, metric="heart_rate", page_size=200)
    print(page.meta(), [v.heart_rate for v in page.items[:5]])
    result = vitals.bulk_create(patient_id, readings)   # {"accepted": ..., "duplicates": ..., ...}
    db.commit()
```
