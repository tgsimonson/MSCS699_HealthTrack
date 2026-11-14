# HealthTrack Phase 4: Real-Time Monitoring Dashboard

A Dash (Plotly) dashboard that lets cardiac rehab clinicians watch their home-based patients at a glance. It shows
a worklist ranked by alert priority, gauges and trend charts for heart rate, blood pressure, and SpO2 drawn against
each patient's own thresholds, color-coded abnormal readings, daily activity, and the active alerts with
acknowledge and resolve actions. New readings and alerts arrive over a WebSocket and are drawn without reloading the
page. All data is synthetic.

The dashboard is a client of the Phase 4 alert-system API in `../phase4-alert-system/`; it never opens the
database. Start that API first.

## Deliverables

Each written deliverable is a PDF in `docs/`; the Markdown and generated report files they were built from stay
next to them so they can be read on GitHub and regenerated.

| Deliverable | PDF | Source in this folder |
|---|---|---|
| Dashboard implementation | (code) | `dashboard/` (layout, callbacks, figures, components, API client, browser assets), tests in `tests/` |
| User interface design document (layout, components, interaction flow, design decisions) | [`docs/HealthTrack_Dashboard_UI_Design.pdf`](docs/HealthTrack_Dashboard_UI_Design.pdf) | `docs/build/ui_design.json` |
| User guide | [`docs/HealthTrack_Dashboard_User_Guide.pdf`](docs/HealthTrack_Dashboard_User_Guide.pdf) | `docs/USER_GUIDE.md` |
| Testing documentation (load time, real-time updates, data accuracy) | [`docs/HealthTrack_Dashboard_Testing_Documentation.pdf`](docs/HealthTrack_Dashboard_Testing_Documentation.pdf) | `docs/TESTING.md` (method) and `reports/dashboard_test_results.md` (results from `scripts/run_reports.sh`) |

## Setup (macOS, Linux, or Windows)

Requires Python 3.10 to 3.14 and the alert-system project set up next to this folder (see its README). With
[uv](https://docs.astral.sh/uv/):

```bash
cd phase4-dashboard
uv venv && source .venv/bin/activate          # Windows: .venv\Scripts\activate
uv pip install -r requirements-dev.txt
python3 -m playwright install chromium        # once, for the browser tests
```

## Run

Three terminals, each with its own folder's virtual environment active:

```bash
# 1. api (in phase4-alert-system/)
python3 -m alembic upgrade head && python3 -m scripts.seed     # first time only
python3 -m uvicorn app.main:app

# 2. dashboard (in phase4-dashboard/)
python3 -m dashboard                         # http://localhost:8050, api at http://localhost:8000

# 3. live device data (in phase4-alert-system/, optional)
python3 -m scripts.simulate_devices          # thomas reed crosses his heart rate ceiling about 30 s in
```

Open **http://localhost:8050** and sign in as `marcus.lee@healthtrack.example` / `HealthTrack-Demo-2026!` (or
`dana.whitfield@healthtrack.example`, who has a different care team). `HT_API_URL`, `HT_DASH_PORT`, and
`HT_DASH_SECRET` change the API address, port, and session signing key.

## Tests and reports

```bash
python3 -m pytest                  # 47 unit tests, about a second
./scripts/run_reports.sh           # unit tests with coverage, then the browser tests (about a minute)
```

`run_reports.sh` starts its own throwaway copy of the API (fresh SQLite database, migrations, seed data) and the
dashboard, drives headless Chromium with Playwright, and writes `reports/dashboard_test_results.md`,
`reports/dashboard_e2e.json`, and screenshots in `reports/screens/`. `python3 -m scripts.capture_screens` refreshes
the images used in the user guide.

## Layout

```
dashboard/
  app.py          layout and callbacks (initial load, selection, live events, actions, polling fallback)
  api.py          api client; tokens stay in the server-side session, the browser only gets a websocket ticket
  figures.py      gauges and trend charts, reading classification, downsampling
  components.py   worklist cards, patient header, alert items, notifications, sign-in page
  logic.py        pure state updates applied to each batch of stream events (unit tested)
  theme.py        clinical slate palette and severity styles (color, glyph, and text label)
  assets/         realtime.js (websocket client), clientside.js (live chart updates), style.css
tests/            figure, component, state, and route tests
scripts/          measure_dashboard (browser tests), capture_screens, run_reports.sh
docs/             design document, user guide, testing method, images
```
