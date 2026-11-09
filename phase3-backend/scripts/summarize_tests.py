"""turn pytest junit xml and coverage json into reports/test_results.md

usage: python -m scripts.summarize_tests reports/junit-sqlite.xml [reports/junit-postgres.xml]
"""
from __future__ import annotations

import json
import platform
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"

AREAS = {
    "test_models": "SQLAlchemy models: field constraints, foreign keys, invalid data",
    "test_repositories": "Data access layer: CRUD, filtering, pagination, errors, logging",
    "test_schemas_security": "Request validation schemas and security primitives",
    "test_migrations": "Alembic migrations: create, schema update, downgrade, drift",
    "test_api_auth": "Auth endpoints: login, lockout, MFA, refresh rotation, logout",
    "test_api_patients": "Patient endpoints: CRUD, search, role and scope matrix, audit",
    "test_api_monitoring": "Vital sign, activity, and device endpoints; error handling",
}


def parse(path: Path) -> dict:
    root = ET.parse(path).getroot()
    suite = root if root.tag == "testsuite" else root.find("testsuite")
    cases = []
    for tc in suite.iter("testcase"):
        status = "passed"
        msg = ""
        for tag in ("failure", "error", "skipped"):
            el = tc.find(tag)
            if el is not None:
                status = {"failure": "failed", "error": "error", "skipped": "skipped"}[tag]
                msg = (el.get("message") or "").splitlines()[0][:160]
        mod = tc.get("classname", "").split(".")
        cases.append({"module": next((m for m in mod if m.startswith("test_")), mod[-1]),
                      "cls": mod[-1] if mod[-1][:1].isupper() else "", "name": tc.get("name"),
                      "time": float(tc.get("time", 0)), "status": status, "message": msg})
    return {"name": path.stem.replace("junit-", ""), "timestamp": suite.get("timestamp"),
            "time": float(suite.get("time", 0)), "cases": cases}


def main(paths: list[str]) -> None:
    runs = [parse(Path(p)) for p in paths if Path(p).exists()]
    if not runs:
        raise SystemExit("no junit files found")
    cov = None
    cov_path = REPORTS / "coverage.json"
    if cov_path.exists():
        cov = json.loads(cov_path.read_text())
    out = ["# HealthTrack Phase 3 test results", "",
           f"Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')} on {platform.platform()}, "
           f"Python {platform.python_version()}.", ""]
    out += ["## Summary", "", "| Database | Tests | Passed | Failed | Errors | Skipped | Duration (s) |",
            "|---|---|---|---|---|---|---|"]
    for r in runs:
        c = defaultdict(int)
        for t in r["cases"]:
            c[t["status"]] += 1
        out.append(f"| {r['name']} | {len(r['cases'])} | {c['passed']} | {c['failed']} | {c['error']} | "
                   f"{c['skipped']} | {r['time']:.2f} |")
    if cov:
        out += ["", f"Line coverage of `app/`: **{cov['totals']['percent_covered']:.1f}%** "
                    f"({cov['totals']['covered_lines']} of {cov['totals']['num_statements']} statements). "
                    "Target from requirement NFR-16: 80%."]
    main_run = runs[0]
    out += ["", f"## Results by area ({main_run['name']})", "", "| Test module | What it covers | Passed | Failed | Skipped |",
            "|---|---|---|---|---|"]
    by_mod = defaultdict(lambda: defaultdict(int))
    for t in main_run["cases"]:
        by_mod[t["module"]][t["status"]] += 1
    for mod in AREAS:
        if mod in by_mod:
            m = by_mod[mod]
            out.append(f"| `{mod}.py` | {AREAS[mod]} | {m['passed']} | {m['failed'] + m['error']} | {m['skipped']} |")
    problems = [(r["name"], t) for r in runs for t in r["cases"] if t["status"] in ("failed", "error")]
    out += ["", "## Failures", ""]
    if problems:
        out += ["| Database | Test | Message |", "|---|---|---|"]
        out += [f"| {db} | `{t['module']}::{(t['cls'] + '::') if t['cls'] else ''}{t['name']}` | {t['message']} |"
                for db, t in problems]
    else:
        out.append("None. Every test passed.")
    skipped = [(r["name"], t) for r in runs for t in r["cases"] if t["status"] == "skipped"]
    if skipped:
        out += ["", "## Skipped", "", "| Database | Test | Reason |", "|---|---|---|"]
        out += [f"| {db} | `{t['module']}::{t['name']}` | {t['message']} |" for db, t in skipped]
    if cov:
        out += ["", "## Coverage by module", "", "| Module | Statements | Missed | Coverage |", "|---|---|---|---|"]
        for f, data in sorted(cov["files"].items()):
            s = data["summary"]
            out.append(f"| `{f}` | {s['num_statements']} | {s['missing_lines']} | {s['percent_covered']:.0f}% |")
    slow = sorted(main_run["cases"], key=lambda t: -t["time"])[:10]
    out += ["", "## Slowest tests", "", "| Test | Seconds |", "|---|---|"]
    out += [f"| `{t['module']}::{t['name']}` | {t['time']:.3f} |" for t in slow]
    out += ["", "## Complete list", ""]
    for mod in AREAS:
        rows = [t for t in main_run["cases"] if t["module"] == mod]
        if rows:
            out += [f"### {mod}.py", ""]
            out += [f"- {'PASS' if t['status'] == 'passed' else t['status'].upper()} "
                    f"{(t['cls'] + '::') if t['cls'] else ''}{t['name']}" for t in rows]
            out.append("")
    (REPORTS / "test_results.md").write_text("\n".join(out))
    print(f"wrote {REPORTS / 'test_results.md'}")


if __name__ == "__main__":
    main(sys.argv[1:] or [str(REPORTS / "junit-sqlite.xml")])
