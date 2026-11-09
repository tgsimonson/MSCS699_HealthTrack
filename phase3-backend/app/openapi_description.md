Backend for **HealthTrack**, remote monitoring for home-based cardiac rehabilitation. This Phase 3 build implements
patients, vital signs, daily activity, and devices from the Phase 2 design, with JWT authentication and care-team
authorization. All data is synthetic.

## Quick start

1. **Authorize:** click **Authorize**, enter `marcus.lee@healthtrack.example` / `HealthTrack-Demo-2026!`
   (seed data), and submit. Swagger UI sends the token on every request after that.
2. Call `GET /api/v1/patients` to see the patients on that clinician's care team.
3. Pick a `patient_id` and try `GET /api/v1/patients/{patient_id}/vitals/daily-summary`.

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
