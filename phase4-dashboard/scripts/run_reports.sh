#!/usr/bin/env bash
# unit tests with coverage, then the end-to-end browser measurements (load time, real-time latency, data accuracy)
# usage: ./scripts/run_reports.sh   (from phase4-dashboard/, virtual environment active; the alert-system project
#        must be set up next to this folder with its own .venv, see README)
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p reports

echo "== unit tests (with coverage)"
python3 -m pytest --junitxml=reports/junit-unit.xml --cov=dashboard --cov-report=json:reports/coverage.json \
  --cov-report=term | tee reports/pytest-unit.txt || true

echo "== end-to-end browser tests"
python3 -m scripts.measure_dashboard "$@"

echo
echo "done. reports/dashboard_test_results.md is ready; screenshots are in reports/screens/."
