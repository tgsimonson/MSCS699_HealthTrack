# HealthTrack: Remote Monitoring for Home-Based Cardiac Rehabilitation

MSCS 699 Computer Science Capstone, University of the Cumberlands<br>
Todd Simonson, Fall 2026, Dr. Michael Solomon

HealthTrack lets patients complete cardiac rehabilitation at home while their rehab team supervises remotely. A heart rate band, blood pressure cuff, and pulse oximeter send readings to the platform. HealthTrack checks each reading against the patient's own exercise prescription, raises and escalates alerts for unsafe exertion or declining progress, and scores each patient's risk of dropping out or getting worse.

All patient data in this repository is synthetic. No real protected health information is used.

## Phases

| Phase | Due | Folder | Contents |
|---|---|---|---|
| 1. Proposal | Oct 25 | [`phase1-proposal/`](phase1-proposal/) | Proposal, requirements matrix, stakeholder analysis diagram, Gantt chart |
| 2. Data layer and API design | Nov 1 | [`phase2-data-api/`](phase2-data-api/) | ERD, SQL schema scripts, OpenAPI (Swagger) specification, design rationale |
| 3. Backend implementation | Nov 8 | [`phase3-backend/`](phase3-backend/) | SQLAlchemy models, Alembic migrations, data access layer, FastAPI endpoints with JWT auth, tests, Postman collection |
| 4. Alert system | Nov 15 | [`phase4-alert-system/`](phase4-alert-system/) | Threshold and pattern alerts, prioritization and fatigue controls, notifications, escalation, alert history, WebSocket stream |
| 4. Monitoring dashboard | Nov 15 | [`phase4-dashboard/`](phase4-dashboard/) | Real-time Dash (Plotly) dashboard with gauges, trend charts, color-coded alerts, and live updates |
| 5. Risk assessment | Nov 22 | | Risk scoring, prediction, and reporting |
| 6. Performance optimization | Nov 29 | | Profiling, optimizations, benchmarks |
| 7. Final submission and presentation | Dec 6 | | Integrated system, deployment package, final report, recording |

## Phase 2 at a glance

| Deliverable | File |
|---|---|
| ERD (PDF) | [`phase2-data-api/erd/HealthTrack_ERD.pdf`](phase2-data-api/erd/HealthTrack_ERD.pdf): conceptual model, full ERD with crow's foot notation, data dictionary, and validation rules |
| SQL schema creation scripts | [`phase2-data-api/sql/`](phase2-data-api/sql/): schema, security (roles, row-level security, audit), views, sample data, validation tests |
| API documentation (Swagger) | [`phase2-data-api/api/healthtrack-openapi.yaml`](phase2-data-api/api/healthtrack-openapi.yaml) (OpenAPI 3.1), plus an offline Swagger UI viewer: [`HealthTrack_API_Docs.html`](phase2-data-api/api/HealthTrack_API_Docs.html) |
| Design rationale | [`phase2-data-api/docs/HealthTrack_Design_Rationale.pdf`](phase2-data-api/docs/HealthTrack_Design_Rationale.pdf) |

**Live API documentation (Swagger UI): https://tgsimonson.github.io/MSCS699_HealthTrack/**

The same viewer works offline: open `HealthTrack_API_Docs.html` in a browser, or paste `healthtrack-openapi.yaml` into https://editor.swagger.io.

### Build the database

Requires PostgreSQL 15 or later.

```bash
cd phase2-data-api/sql
createdb healthtrack
psql -d healthtrack -v ON_ERROR_STOP=1 -f 00_run_all.sql
```

The last script runs 58 validation tests and prints a PASS/FAIL table. It stops with an error if any test fails.

## Phase 3 at a glance

See [`phase3-backend/README.md`](phase3-backend/README.md) for setup. Quick start:

```bash
cd phase3-backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
python3 -m alembic upgrade head && python3 -m scripts.seed
python3 -m uvicorn app.main:app --reload     # then open http://localhost:8000/docs
python3 -m pytest                            # run the test suite
```

## Phase 4 at a glance

The alert system extends the Phase 3 backend (copied forward; `phase3-backend/` stays as submitted). The dashboard
is a separate client of that API. See each folder's README for setup and the deliverable map.

```bash
# terminal 1: api with the alert engine
cd phase4-alert-system && uv venv && source .venv/bin/activate && uv pip install -r requirements-dev.txt
python3 -m alembic upgrade head && python3 -m scripts.seed
python3 -m uvicorn app.main:app

# terminal 2: dashboard, then open http://localhost:8050
cd phase4-dashboard && uv venv && source .venv/bin/activate && uv pip install -r requirements-dev.txt
python3 -m dashboard

# terminal 3 (optional): live device data
cd phase4-alert-system && source .venv/bin/activate && python3 -m scripts.simulate_devices
```

## Stack

PostgreSQL or SQLite, FastAPI, SQLAlchemy 2 with Alembic migrations, Pydantic 2, Dash (Plotly) with WebSockets (Phase 4), and scikit-learn for risk models (Phase 5).
