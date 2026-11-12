# HealthTrack dashboard: test results

Run 2026-11-12T22:58:53+00:00 on macOS-26.5.1-arm64-arm-64bit (arm64, 8 cores), Python 3.12.13, chromium 153.0.8010.12 headless. The API and dashboard ran locally on this machine with the seed data; times are from this machine's clock.

## Unit tests

47 unit tests, 47 passed, 0 failed (0.90 s): figure builders, reading classification, gauges, components, stream state updates, and the dashboard server routes.
Line coverage of `dashboard/`: 71.1%.

## 1. Load time (requirement NFR-09: initial view within 3 s)

Measured from navigation start in the browser, signed in, across 10 page loads.

| Measurement | n | p50 (ms) | p95 (ms) | max (ms) |
|---|---|---|---|---|
| Worklist rendered | 10 | 152.6 | 596.6 | 596.6 |
| Charts drawn | 10 | 674.8 | 762.3 | 762.3 |
| Live stream connected | 10 | 691.0 | 774.1 | 774.1 |

Charts drawn p95 762.3 ms: target met. Each load transferred about 98 KB, because the Dash and Plotly bundles come from the browser cache after the sign-in page.

## 2. Real-time updates

A reading posted to the API (as the patient's device) until it reaches the browser and is drawn on the open chart.

| Measurement | n | p50 (ms) | p95 (ms) | max (ms) |
|---|---|---|---|---|
| Reading received over the WebSocket | 30 | 12.4 | 15.5 | 288.1 |
| Reading appended to the chart | 30 | 122.3 | 131.3 | 393.1 |

A breaching reading pair posted until each part of the screen shows the new critical alert (requirement NFR-07: within 5 s).

| Measurement | n | p50 (ms) | p95 (ms) | max (ms) |
|---|---|---|---|---|
| Alert in the alert panel | 8 | 254.6 | 269.1 | 269.1 |
| Worklist re-sorted, patient first | 8 | 250.6 | 265.1 | 265.1 |
| Notification toast shown | 8 | 258.1 | 274.1 | 274.1 |

Alert panel p95 269.1 ms: target met.

## 3. Interaction timing

- Switch the charts to 7 days (reload and redraw): 18.3 ms
- Acknowledge an alert, click to updated status: 62.0 ms
- Dropped WebSocket to live again (automatic reconnect): 1042.1 ms

## 4. Data accuracy and behavior checks (11 of 11 passed)

| Check | Result | Detail |
|---|---|---|
| Live readings appear on the chart with the posted values | PASS | last three plotted [107, 108, 109], posted [107, 108, 109] |
| Live readings clear the empty-chart label on a chart that started empty | PASS | chart labels now ['Target zone 95-115', 'Exercise ceiling 128', 'Resting limit 90'] |
| Worklist order, names, and latest values match the API | PASS | 2 cards compared field by field |
| Heart rate gauge matches the latest valid reading | PASS | gauge 138, api 138 |
| Alert panel shows every active alert in scope | PASS | panel 2, api 2 |
| Critical alerts carry a text label, not only color | PASS | badge '▲ CRITICAL' |
| Readings above the ceiling are drawn red, as triangles, labeled Critical | PASS | {'color': '#B42318', 'symbol': 'triangle-up', 'text': 'Critical reading, exercise'} |
| Chart threshold lines come from the patient's effective thresholds | PASS | ceiling 128.0, resting 90.0, drawn [90, 95, 128] |
| 24-hour heart rate chart plots every reading the API returns | PASS | chart 46, api 46 |
| Acknowledging in the dashboard records the clinician in the API | PASS | acknowledged_by 00000000-0000-4000-a000-000000000002 |
| After a dropped connection the stream reconnects and live updates resume | PASS | live again after 1042 ms; next reading arrived |

## 5. Page loads

| Run | DOM ready (ms) | Worklist (ms) | Charts (ms) | Live (ms) | Transferred (KB) |
|---|---|---|---|---|---|
| 1 | 77.5 | 160.9 | 690.3 | 712.8 | 98.4 |
| 2 | 68.8 | 153.5 | 677.3 | 690.7 | 98.4 |
| 3 | 71 | 152.7 | 675.8 | 690.1 | 98.4 |
| 4 | 69.7 | 153.6 | 673.8 | 691.9 | 98.4 |
| 5 | 70.4 | 152.4 | 680 | 707 | 98.4 |
| 6 | 68.3 | 596.6 | 762.3 | 774.1 | 98.4 |
| 7 | 70.3 | 152.4 | 667.9 | 691.2 | 98.4 |
| 8 | 68.5 | 152.6 | 670.1 | 690.3 | 98.4 |
| 9 | 65.4 | 143.7 | 653.2 | 674.1 | 98.4 |
| 10 | 65.8 | 146.3 | 670.9 | 690.1 | 98.4 |
