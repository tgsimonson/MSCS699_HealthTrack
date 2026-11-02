# HealthTrack: Remote Monitoring for Home-Based Cardiac Rehabilitation

MSCS 699 Computer Science Capstone, University of the Cumberlands
Todd Simonson, Fall 2026, Dr. Michael Solomon

HealthTrack lets patients complete cardiac rehabilitation at home while their rehab team supervises remotely. A heart rate band, blood pressure cuff, and pulse oximeter send readings to the platform. HealthTrack checks each reading against the patient's own exercise prescription, raises and escalates alerts for unsafe exertion or declining progress, and scores each patient's risk of dropping out or getting worse.

All patient data in this repository is synthetic. No real protected health information is used.

## Phases

| Phase | Due | Folder | Contents |
|---|---|---|---|
| 1. Proposal | Oct 25 | [`phase1-proposal/`](phase1-proposal/) | Proposal, requirements matrix, stakeholder analysis diagram, Gantt chart |
| 2. Data layer and API design | Nov 1 | [`phase2-data-api/`](phase2-data-api/) | ERD, SQL schema scripts, OpenAPI (Swagger) specification, design rationale |
| 3. Backend implementation | Nov 8 | | FastAPI and SQLAlchemy backend |
| 4. Alert system and dashboard | Nov 15 | | Real-time alerts and Dash dashboard |
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

To view the API documentation, open `HealthTrack_API_Docs.html` in a browser, or paste `healthtrack-openapi.yaml` into https://editor.swagger.io. The same viewer is in `docs/index.html` so it can be published with GitHub Pages.

### Build the database

Requires PostgreSQL 15 or later.

```bash
cd phase2-data-api/sql
createdb healthtrack
psql -d healthtrack -v ON_ERROR_STOP=1 -f 00_run_all.sql
```

The last script runs 58 validation tests and prints a PASS/FAIL table. It stops with an error if any test fails.

## Planned stack

PostgreSQL, FastAPI, SQLAlchemy with Alembic migrations, Dash (Plotly) with WebSockets, and scikit-learn for risk models.
