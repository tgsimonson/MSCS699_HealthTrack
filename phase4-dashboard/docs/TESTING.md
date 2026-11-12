# HealthTrack Dashboard: Testing Documentation

This document describes how the dashboard is tested: what each test measures, where a timing starts and stops, the
target it is judged against, and how to reproduce the run. The numbers themselves are in
`reports/dashboard_test_results.md`, written by `scripts/run_reports.sh` on the machine that ran it.

## 1. What is tested, and against which requirement

| Area | Requirement (Phase 1 matrix) | Target | How |
|---|---|---|---|
| Load time | NFR-09 | Initial view within 3 s | Browser, 10 page loads |
| Real-time updates | FR-18 | A posted reading reaches an open dashboard without a reload | Browser, 30 readings |
| Alert latency | NFR-07 | Critical alert on the dashboard within 5 s of ingestion | Browser, 8 alerts |
| Color-coded abnormal readings | FR-17, NFR-14 | Abnormal readings in the alert color with a text label and symbol | Unit tests and browser checks |
| Worklist ranking | FR-17, NFR-15 | Patient with the newest critical alert re-sorts to the top; highest priority reachable in two clicks | Unit tests and browser checks |
| Data accuracy | FR-17, FR-19 | Every displayed value matches the API | Browser checks against direct API calls |
| Resilience | NFR-11 | A dropped connection recovers without a reload | Browser, forced disconnect |
| Security of the browser session | NFR-03, NFR-04 | No token in browser storage or cookies; only the care team's patients | Unit tests; API tests AS-42 to AS-46 |

## 2. Unit tests (`tests/`, 47 tests)

Run with `python3 -m pytest`. They need no API or browser.

| File | Covers |
|---|---|
| `test_figures.py` | Reading classification matches the alert engine's rules (context filters, suspect readings), downsampling keeps spikes and every abnormal point, threshold lines and target-zone bands come from the patient's effective thresholds, abnormal markers use the severity color and symbol, session gaps break the line, empty ranges say so, gauges use the patient's limits |
| `test_ui_logic.py` | Severity badges always carry text and a glyph, worklist cards and patient header content, alert actions offered for each status, folding stream events into the worklist, alert, and gauge state, suspect readings never change the display, one notification pop-up per alert, alert ordering, selection order (deep link, then previous, then top of worklist), the server routes (no ticket when signed out, security headers, logout), tokens kept off the browser, and a concurrent token refresh that rotates exactly once |

`dashboard/app.py` callbacks are exercised by the browser tests rather than unit tests, which is why line coverage
of `dashboard/` is lower than the alert system's.

## 3. Browser tests (`scripts/measure_dashboard.py`)

### 3.1 Test environment

The script builds its own environment so results are repeatable and never touch a working database:

1. A fresh SQLite database in a temporary folder, migrated to head and loaded with the seed data.
2. The alert-system API (`uvicorn`, background workers on) and the dashboard, each on a free local port.
3. Headless Chromium driven by Playwright, at 1500 by 1000 pixels, signed in as Marcus Lee (clinician).
4. Readings are posted to the API as Thomas Reed's heart rate band, exactly as the device app would.

All times come from the same machine's clocks, so the API and the browser share a time base.

### 3.2 Measurements

| Measurement | Starts | Stops |
|---|---|---|
| Worklist rendered | Navigation start | First worklist card in the page |
| Charts drawn | Navigation start | Patient data loaded and all five charts and the heart rate gauge have rendered |
| Live stream connected | Navigation start | Connection pill reads Live |
| Reading received | Just before the reading is posted to the API | The browser's WebSocket client receives its event |
| Reading on the chart | Just before the reading is posted | The live chart update for that reading has been applied |
| Alert in the alert panel | Just before a breaching pair of readings is posted | A critical alert item appears (observed with a DOM mutation observer) |
| Worklist re-sorted | Same | The first worklist card carries the critical style |
| Notification shown | Same | A new critical pop-up appears |
| Range switch to 7 days | Click | All charts redrawn with the 7-day data |
| Acknowledge | Click on Acknowledge | The alert's status reads Acknowledged |
| Reconnect | The test closes the browser's WebSocket | The pill reads Live again (it must pass through Reconnecting) |

Each series is reported as n, median (p50), 95th percentile (p95), and maximum. Between alert runs the test resolves
Thomas's open alerts through the API and waits for the screen to clear, so each run measures a new alert rather
than a repeat folded into an old one.

### 3.3 Data accuracy and behavior checks

Each check compares what the browser shows with what the API returns at the same moment:

1. Live readings appear on the chart with the posted values.
2. Live readings clear the empty-chart label on a chart that started empty.
3. Worklist order, names, and latest values match `GET /monitoring/worklist` card by card.
4. The heart rate gauge matches `GET /vitals/latest`.
5. The alert panel lists every active alert in scope (`GET /alerts`).
6. Critical alerts carry a text label, not only color.
7. Readings above the ceiling are drawn red, as triangles, labeled Critical.
8. Chart threshold lines equal the patient's effective thresholds (`GET /alert-thresholds`).
9. The 24-hour heart rate chart plots every reading the API returns for that range.
10. Acknowledging in the dashboard records the signed-in clinician in the API.
11. After a dropped connection the stream reconnects and the next reading arrives.

A failed check is reported as FAIL with the observed values; the script does not stop, so one failure does not hide
the others.

## 4. Reproducing the results

From `phase4-dashboard/`, with the alert-system project set up in `../phase4-alert-system/` (its own `.venv`)
and Chromium installed for Playwright:

```bash
source .venv/bin/activate
./scripts/run_reports.sh                       # unit tests with coverage, then the browser tests
python3 -m scripts.measure_dashboard --runs 20 --readings 50 --alerts 10    # larger samples
python3 -m scripts.measure_dashboard --headed  # watch the browser while it runs
```

Outputs: `reports/dashboard_test_results.md` (tables), `reports/dashboard_e2e.json` (every raw timing),
`reports/pytest-unit.txt`, `reports/junit-unit.xml`, and screenshots in `reports/screens/`.

## 5. Limits of these results

- Everything runs on one machine, so network latency between a clinic and a server is not included. The 3 s and
  5 s targets leave room for it, but a deployed test over a real network is still needed (Phase 6).
- One browser client is measured. Many simultaneous dashboards are measured at the broker level in the alert
  system's performance report (WebSocket fan-out), not in a browser.
- The database is SQLite. PostgreSQL behavior is covered by the alert system's own test suite.
- Contrast was computed from the palette values rather than with an automated audit tool: every severity text
  color is at least 4.6:1 on white and on its own tint (WCAG 2.1 AA needs 4.5:1), and chart symbols are at least
  4.9:1 (3:1 needed).
