# HealthTrack SQL schema scripts

PostgreSQL 15 or later (uses `security_invoker` views, `btree_gist` exclusion constraints, and row-level security).

## Build

```bash
createdb healthtrack
psql -d healthtrack -v ON_ERROR_STOP=1 -f 00_run_all.sql
```

Run as a superuser (or a role allowed to create extensions and roles). The run stops at the first error.

## Files

| File | Contents |
|---|---|
| `00_run_all.sql` | Runs 01 through 05 in order. |
| `01_schema.sql` | Extensions, 26 enumerated types, 23 tables, CHECK/UNIQUE/EXCLUDE constraints, indexes, and validation triggers (role checks, prescription versioning, vital plausibility flags, risk band derivation, automatic alert history, session metric computation). |
| `02_security.sql` | Database roles, least-privilege grants, append-only audit log, automatic PHI change auditing, and row-level security policies. |
| `03_views.sql` | Worklist, weekly adherence, daily vital summary, alert response, and aggregate program metrics views; transfers ownership to `healthtrack_owner`. |
| `04_sample_data.sql` | Deterministic synthetic test data: 12 users, 8 patients covering stable, improving, declining, non-adherent, exertion-spike, graduated, referred, and paused profiles, about 1,450 vital readings, sessions, activity, appointments, alerts with history, notifications, and risk assessments. |
| `05_validation_tests.sql` | 58 executable checks of constraints, domain rules, triggers, auditing, and row-level security. Each test rolls back; the script fails if any check fails. |

## Request context used by row-level security

The API connects as a login role that is a member of `healthtrack_api` and, inside each request's transaction, runs:

```sql
SET LOCAL app.user_id = '<user uuid from the verified JWT>';
SET LOCAL app.user_role = '<role from the verified JWT>';
SET LOCAL app.request_id = '<request uuid>';
```

Without these settings, patient-scoped queries return no rows.

## Sample accounts

All sample accounts use the mock password `HealthTrack-Demo-2026!`. Every person and record in the sample data is fictitious.
