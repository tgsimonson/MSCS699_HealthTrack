# HealthTrack Phase 3 performance results

Run 2026-11-09T04:57:25+00:00 on macOS-26.5.1-arm64-arm-64bit (arm64, 8 CPUs), Python 3.12.13, sqlite 3.53.3.

Dataset: 135,850 vital sign rows across 108 patients (loaded in 2.93 s). Requests run in-process through the full FastAPI stack (routing, authentication, authorization, validation, audit write), so network time is excluded.

## Latency

| Operation | n | p50 (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|---|
| POST /auth/token (bcrypt cost 12) | 10 | 252.32 | 283.92 | 298.32 |
| POST /patients/{id}/vitals (single reading) | 200 | 4.35 | 9.33 | 24.59 |
| POST /patients/{id}/vitals/batch (500 readings) | 20 | 61.8 | 83.44 | 91.22 |
| GET /patients (worklist page) | 200 | 2.75 | 3.38 | 3.87 |
| GET /patients/{id}/vitals (24 h page) | 200 | 4.36 | 5.37 | 5.7 |
| GET /patients/{id}/vitals (7 days, page 1 of n) | 200 | 6.88 | 22.55 | 41.42 |
| GET /patients/{id}/vitals/latest | 200 | 6.41 | 8.7 | 13.32 |
| GET /patients/{id}/vitals/daily-summary (21 days) | 200 | 12.0 | 15.1 | 20.57 |
| GET /patients/{id}/daily-activity/summary | 200 | 2.71 | 3.82 | 4.81 |
| POST /patients/search | 200 | 2.95 | 3.89 | 4.75 |

## Ingestion

Batch upload sustained about **7,775 readings per second**. Replaying the last batch returned 500 duplicates and stored nothing (55.47 ms).

## Index effectiveness

Query: readings for one patient in a 24-hour window, newest 200. The patient tested has 10,521 readings; the window returned 2 of them.

| | p50 (ms) | p95 (ms) |
|---|---|---|
| With `ix_vital_signs_patient_time` | 0.02 | 0.02 |
| Without the index | 2.98 | 3.16 |

Speedup at p50: **149.0x**.

Plan with index: `SEARCH vital_signs USING INDEX ix_vital_signs_patient_time (patient_id=? AND recorded_at>? AND recorded_at<?)`

Plan without index: `SEARCH vital_signs USING INDEX sqlite_autoindex_vital_signs_1 (patient_id=?) | USE TEMP B-TREE FOR ORDER BY`
