# HealthTrack Phase 3 performance results

Run 2026-11-12T22:55:45+00:00 on macOS-26.5.1-arm64-arm-64bit (arm64, 8 CPUs), Python 3.12.13, sqlite 3.53.3.

Dataset: 135,850 vital sign rows across 108 patients (loaded in 3.91 s). Requests run in-process through the full FastAPI stack (routing, authentication, authorization, validation, audit write), so network time is excluded.

## Latency

| Operation | n | p50 (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|---|
| POST /auth/token (bcrypt cost 12) | 10 | 237.07 | 263.3 | 279.26 |
| POST /patients/{id}/vitals (single reading) | 200 | 3.85 | 4.7 | 6.03 |
| POST /patients/{id}/vitals/batch (500 readings) | 20 | 67.66 | 97.52 | 98.75 |
| GET /patients (worklist page) | 200 | 2.66 | 3.0 | 3.84 |
| GET /patients/{id}/vitals (24 h page) | 200 | 3.99 | 4.8 | 6.03 |
| GET /patients/{id}/vitals (7 days, page 1 of n) | 200 | 6.45 | 8.26 | 30.91 |
| GET /patients/{id}/vitals/latest | 200 | 5.53 | 6.37 | 6.66 |
| GET /patients/{id}/vitals/daily-summary (21 days) | 200 | 11.22 | 12.74 | 13.95 |
| GET /patients/{id}/daily-activity/summary | 200 | 2.65 | 2.93 | 3.37 |
| POST /patients/search | 200 | 2.92 | 3.96 | 5.98 |

## Ingestion

Batch upload sustained about **6,715 readings per second**. Replaying the last batch returned 500 duplicates and stored nothing (54.43 ms).

## Index effectiveness

Query: readings for one patient in a 24-hour window, newest 200. The patient tested has 10,521 readings; the window returned 33 of them.

| | p50 (ms) | p95 (ms) |
|---|---|---|
| With `ix_vital_signs_patient_time` | 0.04 | 0.04 |
| Without the index | 3.5 | 4.63 |

Speedup at p50: **87.5x**.

Plan with index: `SEARCH vital_signs USING INDEX ix_vital_signs_patient_time (patient_id=? AND recorded_at>? AND recorded_at<?)`

Plan without index: `SEARCH vital_signs USING INDEX sqlite_autoindex_vital_signs_1 (patient_id=?) | USE TEMP B-TREE FOR ORDER BY`
