#!/usr/bin/env bash
# runs the full test suite (sqlite, plus postgres if HT_TEST_DATABASE_URL is set), coverage, the performance
# benchmark, and the openapi export, then writes the reports into reports/ and docs/
# usage: ./scripts/run_reports.sh            (from phase4-alert-system/, with the virtual environment active)
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p reports

echo "== tests on sqlite (with coverage)"
env -u HT_TEST_DATABASE_URL HT_SCENARIO_REPORT=reports/scenarios.json python3 -m pytest \
  --junitxml=reports/junit-sqlite.xml \
  --cov=app --cov-report=json:reports/coverage.json --cov-report=html:reports/coverage_html --cov-report=term \
  | tee reports/pytest-sqlite.txt || true

JUNITS="reports/junit-sqlite.xml"
if [[ -n "${HT_TEST_DATABASE_URL:-}" ]]; then
  echo "== tests on postgresql"
  python3 -m pytest --junitxml=reports/junit-postgresql.xml | tee reports/pytest-postgresql.txt || true
  JUNITS="$JUNITS reports/junit-postgresql.xml"
fi

echo "== test summary"
python3 -m scripts.summarize_tests $JUNITS

echo "== alert system performance benchmark"
python3 -m scripts.benchmark_alerts

echo "== api performance benchmark (phase 3 endpoints, now with alert evaluation on ingest)"
python3 -m scripts.benchmark

echo "== openapi export"
python3 -m scripts.export_openapi

echo
echo "done. reports/test_results.md (scenarios and results) and reports/alert_performance.md are ready."
