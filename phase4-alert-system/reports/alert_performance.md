# HealthTrack alert system performance

Run 2026-11-12T22:55:31+00:00 on macOS-26.5.1-arm64-arm-64bit (arm64, 8 cores), Python 3.12.13, sqlite 3.53.3. Dataset: 119,750 readings, 105 active patients. All requests run in-process, so network time is excluded.

## 1. Rule evaluation per reading

| Measurement | n | p50 (ms) | p95 (ms) | max (ms) |
|---|---|---|---|---|
| Normal reading (no breach) | 200 | 0.52 | 0.68 | 1.38 |
| Breach folded into an open alert | 200 | 1.24 | 1.36 | 1.56 |
| Breach creating a new alert and notifications | 200 | 1.48 | 1.70 | 3.15 |

## 2. Ingestion with alert evaluation on and off

| Measurement | n | p50 (ms) | p95 (ms) | max (ms) |
|---|---|---|---|---|
| Single reading, rules on | 200 | 3.43 | 4.53 | 9.15 |
| Single reading, rules off | 200 | 3.07 | 3.78 | 27.70 |
| Batch of 500, rules on | 10 | 69.19 | 84.66 | 93.95 |
| Batch of 500, rules off | 10 | 72.54 | 114.92 | 132.72 |

Alert evaluation adds 0.36 ms to a single reading at the median. Batch throughput: 7,227 readings/s with rules on, 6,893 with rules off. The batch medians differ by 3.35 ms, less than the spread within either set of 10 batches (up to 42.38 ms between median and 95th percentile), so this run cannot separate the cost of alert evaluation for a batch from run-to-run variation; the single-reading comparison, over 200 requests each, is the better estimate.

## 3. End to end: breaching reading posted to event on a connected dashboard

| Measurement | n | p50 (ms) | p95 (ms) | max (ms) |
|---|---|---|---|---|
| Reading to live reading event | 50 | 9.10 | 13.86 | 15.06 |
| Reading to critical alert event | 50 | 9.36 | 14.34 | 15.56 |
| Reading to dashboard notification | 50 | 9.61 | 14.66 | 15.98 |

Requirement NFR-07: critical alerts on the dashboard within 5 s (5000 ms) at the 95th percentile. Measured p95: 14.3 ms for the alert event and 14.7 ms for the notification. Met.

## 4. Notification dispatch delay (queued to sent, background workers)

| Measurement | n | p50 (ms) | p95 (ms) | max (ms) |
|---|---|---|---|---|
| Dashboard | 50 | 3.58 | 6.23 | 9.20 |
| Email | 50 | 3.58 | 6.23 | 9.20 |
| SMS | 50 | 3.58 | 6.23 | 9.20 |

Every channel for an alert is queued in the same transaction and sent in the same dispatch pass, so the channels share one delay. Email and SMS were written to the local outbox (no gateway configured), so these times exclude any external provider.

## 5. Scheduled jobs

- Pattern detection across 105 active patients: 0.34 s (3.2 ms per patient), 3 outcomes.
- Escalation check over 108 open alerts: 39 ms (108 escalated).

## 6. Alert fatigue: one noisy patient over 48 hours

A resting reading every 15 minutes with heart rate around the 100 bpm limit and systolic pressure around 160 mmHg; each alert is resolved 45 minutes after it opens.

| Readings | Threshold crossings | Alerts created | Repeats folded | Suppressed | Notifications |
|---|---|---|---|---|---|
| 192 | 150 | 8 | 5 | 93 | 8 |

Without deduplication and suppression each crossing would notify; here 150 crossings produced 8 notifications (95% fewer).

## 7. WebSocket fan-out (in-process broker)

| Subscribers | Events | Deliveries | Publish cost (us/event) | Deliveries per second |
|---|---|---|---|---|
| 1 | 1000 | 1,000 | 8.8 | 113,825 |
| 10 | 1000 | 10,000 | 39.5 | 253,007 |
| 50 | 1000 | 50,000 | 200.0 | 249,982 |

