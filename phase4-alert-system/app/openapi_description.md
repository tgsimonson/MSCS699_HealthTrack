Backend for **HealthTrack**, remote monitoring for home-based cardiac rehabilitation. Phase 3 delivered patients,
vital signs, daily activity, and devices with JWT authentication and care-team authorization. **Phase 4 adds the
real-time alert system:** every reading is checked against patient-specific thresholds, trend rules watch activity
patterns, alerts are prioritized and deduplicated, notifications go out on the dashboard, email, and SMS, unanswered
alerts escalate, and new readings and alerts are pushed to dashboards over a WebSocket. All data is synthetic.

## Quick start

1. **Authorize:** click **Authorize**, enter `marcus.lee@healthtrack.example` / `HealthTrack-Demo-2026!`
   (seed data), and submit. Swagger UI sends the token on every request after that.
2. Call `GET /api/v1/patients` to see the patients on that clinician's care team.
3. Pick a `patient_id` and try `GET /api/v1/patients/{patient_id}/vitals/daily-summary`.
4. Call `GET /api/v1/alerts` for the active alert worklist, then `GET /api/v1/alerts/{alert_id}` for its history.

## Alert workflow

1. A device posts a reading (`POST /patients/{id}/vitals` or `/vitals/batch`). It is stored first, then checked
   against the threshold rules. The threshold for each rule comes from a patient override, else the exercise
   prescription, else the program default (`GET /patients/{id}/alert-thresholds` shows which).
2. A breach creates an alert, or folds into the open alert for the same condition. Non-critical alerts inside a
   rule's suppression window, or masked by a more severe alert on the same measurement, are stored as `suppressed`.
   Critical alerts are never suppressed.
3. Notifications are queued per the severity's escalation policy (critical: dashboard, SMS, email) and sent at once;
   low severity email waits for the morning digest.
4. A clinician acknowledges (`POST /alerts/{id}/acknowledge`) and resolves with a note (`POST /alerts/{id}/resolve`).
   An alert nobody acknowledges escalates (critical: supervising physician at 15 minutes, whole care team at 30).
5. Trend rules (missed sessions, zone minutes, resting heart rate, steps, data gaps) run every 15 minutes and when a
   day of activity is uploaded.

## Live stream

`POST /stream/ticket` returns a one-time ticket. Open `ws://<host>/api/v1/stream`, send
`{"type": "auth", "ticket": "..."}`, and receive `vital`, `alert`, `activity`, and `notification` events for the
patients on your care team. See the **Live Stream** tag for the full protocol.

## Authentication

* `POST /api/v1/auth/token` (form-encoded `username`, `password`, optional `mfa_code`) returns a 15-minute JWT
  access token and an opaque refresh token. Send the access token as `Authorization: Bearer <token>`.
* `POST /api/v1/auth/refresh` rotates the refresh token. Reusing an already-rotated token revokes every session.
* `POST /api/v1/auth/logout` revokes the session; its access tokens stop working immediately.
* Five failed logins lock an account for 15 minutes (`423`). Login is rate limited per IP and per account (`429`).

## Authorization

| Resource | patient | clinician / physician | admin | it_admin |
|---|---|---|---|---|
| Patient record | read own, edit contact fields | read and edit care team patients | read, edit, soft-delete all | none |
| Vital signs, activity, devices | read and upload own | read, record, correct for care team | none | none |
| Patient list and search | none | care team only | all (demographics) | none |
| Alerts: worklist, history, acknowledge, resolve | none | care team only | metrics only | none |
| Alert rules | none | read (physician: change) | read | none |
| Escalation policies | none | read (physician: change) | read and change | none |
| Prescription and patient thresholds | read own prescription | care team (prescription: physician) | none | none |
| Live stream and worklist | none | care team only | none | none |

A request for a patient outside the caller's scope returns **404**, not 403, so the API never confirms that a record
exists. Every read and write of patient data is recorded in the audit log.

## Errors

Every error uses [RFC 9457](https://www.rfc-editor.org/rfc/rfc9457) problem details (`application/problem+json`)
with a `request_id` that also appears in the server log and the `X-Request-ID` response header.

| Status | Meaning |
|---|---|
| 400 | Malformed request |
| 401 | Missing, expired, or revoked token; bad credentials |
| 403 | Your role cannot perform this action |
| 404 | Not found, or outside your scope |
| 409 | Conflict with existing data (duplicate MRN, duplicate `idempotency_key`, care team role taken) |
| 422 | Validation failed; `errors` lists each field |
| 423 | Account locked after repeated failed logins |
| 429 | Rate limited; see `Retry-After` |
| 503 | Database unavailable; safe to retry |
