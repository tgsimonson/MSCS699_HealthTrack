"""performance benchmark: ingestion throughput, endpoint latency, and index effectiveness

builds a fresh database with the migrations, loads the seed data plus a synthetic load, then times the api
in-process (fastapi testclient, so no network) and times the main query with and without its index.

usage:  python -m scripts.benchmark                 # sqlite file under reports/
        HT_BENCH_DATABASE_URL=postgresql+psycopg://user@localhost/ht_bench python -m scripts.benchmark
writes reports/performance.json and reports/performance.md
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import random
import statistics
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"


def pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * p / 100
    f, c = int(k), min(int(k) + 1, len(s) - 1)
    return s[f] + (s[c] - s[f]) * (k - f)


def stats(ms: list[float]) -> dict[str, float]:
    return {"n": len(ms), "p50_ms": round(pct(ms, 50), 2), "p95_ms": round(pct(ms, 95), 2),
            "p99_ms": round(pct(ms, 99), 2), "mean_ms": round(statistics.fmean(ms), 2), "max_ms": round(max(ms), 2)}


def timed(fn, n: int) -> list[float]:  # noqa: ANN001
    out = []
    for i in range(n):
        t = time.perf_counter()
        fn(i)
        out.append((time.perf_counter() - t) * 1000)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--patients", type=int, default=100, help="synthetic load patients (in addition to seed data)")
    ap.add_argument("--days", type=int, default=14, help="days of readings per synthetic patient")
    ap.add_argument("--per-day", type=int, default=96, help="readings per synthetic patient per day")
    ap.add_argument("--iterations", type=int, default=200)
    args = ap.parse_args()

    REPORTS.mkdir(exist_ok=True)
    url = os.getenv("HT_BENCH_DATABASE_URL")
    tmpdir = None
    if not url:
        tmpdir = tempfile.mkdtemp(prefix="ht_bench_")
        url = f"sqlite:///{Path(tmpdir) / 'bench.db'}"
    os.environ["HT_DATABASE_URL"] = url
    os.environ.setdefault("HT_BCRYPT_ROUNDS", "12")
    os.environ["HT_LOGIN_RATE_LIMIT"] = "100000"
    os.environ["HT_LOG_LEVEL"] = "ERROR"     # escalation warnings are expected during a benchmark

    print(f"database: {url.split('@')[-1]}")
    env = {**os.environ, "HT_DATABASE_URL": url}
    if url.startswith("postgresql"):
        subprocess.run([sys.executable, "-m", "alembic", "downgrade", "base"], cwd=ROOT, env=env, check=True,
                       capture_output=True)
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT, env=env, check=True,
                   capture_output=True)

    from fastapi.testclient import TestClient
    from sqlalchemy import insert, text

    from app.db import SessionLocal, engine
    from app.main import app
    from app.models import DailyActivity, Device, Patient, VitalSign
    from app.models.enums import (ClinicalRisk, DeviceStatus, DeviceType, ProgramStatus, QualifyingEvent,
                                  ReadingContext, ReadingSource, SexAtBirth)
    from scripts.seed import P, U, seed

    results: dict = {"environment": {
        "date": datetime.now(timezone.utc).isoformat(timespec="seconds"), "os": platform.platform(),
        "machine": platform.machine(), "processor": platform.processor() or platform.machine(),
        "cpu_count": os.cpu_count(), "python": platform.python_version(), "database": engine.dialect.name,
        "database_version": None, "load": vars(args)}}

    # ------------------------------------------------------------ data load
    t0 = time.perf_counter()
    with SessionLocal() as db:
        results["environment"]["database_version"] = str(db.execute(
            text("select sqlite_version()" if engine.dialect.name == "sqlite" else "show server_version")).scalar())
        seed(db, days=21)
        rng = random.Random(7)
        start = datetime.now(timezone.utc) - timedelta(days=args.days)
        for i in range(args.patients):
            pid = uuid.uuid4()
            db.add(Patient(patient_id=pid, mrn=f"HT-B{i:05d}", first_name=f"Load{i}", last_name="Patient",
                           date_of_birth=datetime(1960, 1, 1).date(), sex=SexAtBirth.unknown,
                           qualifying_event=QualifyingEvent.pci, qualifying_event_date=datetime(2026, 9, 1).date(),
                           referral_date=datetime(2026, 9, 2).date(), enrollment_date=datetime(2026, 9, 3).date(),
                           program_status=ProgramStatus.active, clinical_risk_category=ClinicalRisk.low))
            dev = uuid.uuid4()
            db.flush()
            db.add(Device(device_id=dev, patient_id=pid, device_type=DeviceType.heart_rate_band, manufacturer="Corvane",
                          model="HB-2", serial_number=f"LOAD-{i}", status=DeviceStatus.active))
            db.flush()
            rows = []
            step = timedelta(minutes=1440 / args.per_day)
            for d in range(args.days):
                for k in range(args.per_day):
                    at = start + timedelta(days=d) + step * k
                    rows.append({"patient_id": pid, "device_id": dev, "recorded_at": at, "received_at": at,
                                 "context": ReadingContext.rest, "heart_rate": rng.randint(58, 118),
                                 "source": ReadingSource.device, "quality": "valid"})
            db.execute(insert(VitalSign), rows)
            db.execute(insert(DailyActivity), [{"patient_id": pid, "activity_date": (start + timedelta(days=d)).date(),
                                                "steps": rng.randint(2000, 9000), "active_minutes": rng.randint(10, 80),
                                                "source": ReadingSource.device} for d in range(args.days)])
        db.commit()
        total_vitals = db.execute(text("select count(*) from vital_signs")).scalar()
    results["dataset"] = {"vital_signs_rows": total_vitals, "patients": args.patients + 8,
                          "load_seconds": round(time.perf_counter() - t0, 2)}
    print(f"loaded {total_vitals:,} readings in {results['dataset']['load_seconds']} s")

    client = TestClient(app)
    password = "HealthTrack-Demo-2026!"

    # ------------------------------------------------------------ login cost (bcrypt work factor 12)
    login_ms = timed(lambda _: client.post("/api/v1/auth/token", data={"username": "marcus.lee@healthtrack.example",
                                                                       "password": password}), 10)
    results["login"] = stats(login_ms)
    marcus = {"Authorization": "Bearer " + client.post(
        "/api/v1/auth/token", data={"username": "marcus.lee@healthtrack.example", "password": password}).json()["access_token"]}
    thomas = {"Authorization": "Bearer " + client.post(
        "/api/v1/auth/token", data={"username": "t.reed@mail.example", "password": password}).json()["access_token"]}
    p5 = P(5)
    band = str(uuid.UUID("00000000-0000-4000-c000-000000000051"))
    n = args.iterations

    # ------------------------------------------------------------ ingestion
    now = datetime.now(timezone.utc)

    def single(i: int) -> None:
        r = client.post(f"/api/v1/patients/{p5}/vitals", headers=thomas, json={
            "recorded_at": (now - timedelta(seconds=i + 1)).isoformat(), "context": "rest", "heart_rate": 70 + i % 20,
            "device_id": band, "idempotency_key": f"bench-single-{i:06d}"})
        assert r.status_code == 201, r.text

    results["ingest_single"] = stats(timed(single, n))

    batch_ms = []
    for b in range(20):
        readings = [{"recorded_at": (now - timedelta(hours=2, seconds=b * 500 + k)).isoformat(), "context": "exercise",
                     "heart_rate": 100 + k % 15, "device_id": band, "idempotency_key": f"bench-b{b:03d}-{k:04d}"}
                    for k in range(500)]
        t = time.perf_counter()
        r = client.post(f"/api/v1/patients/{p5}/vitals/batch", headers=thomas, json={"readings": readings})
        batch_ms.append((time.perf_counter() - t) * 1000)
        assert r.json()["accepted"] == 500, r.text
    t = time.perf_counter()
    replay = client.post(f"/api/v1/patients/{p5}/vitals/batch", headers=thomas, json={"readings": readings})
    replay_ms = (time.perf_counter() - t) * 1000
    results["ingest_batch_500"] = {**stats(batch_ms), "readings_per_second": round(500 / (statistics.fmean(batch_ms) / 1000)),
                                   "replay_duplicates": replay.json()["duplicates"], "replay_ms": round(replay_ms, 2)}

    # ------------------------------------------------------------ read endpoints
    week_ago = (now - timedelta(days=7)).date()
    reads = {
        "GET /patients (worklist page)": lambda _: client.get("/api/v1/patients", headers=marcus),
        "GET /patients/{id}/vitals (24 h page)": lambda _: client.get(f"/api/v1/patients/{p5}/vitals", headers=marcus),
        "GET /patients/{id}/vitals (7 days, page 1 of n)": lambda _: client.get(
            f"/api/v1/patients/{p5}/vitals", params={"start": (now - timedelta(days=7)).isoformat(),
                                                     "end": now.isoformat(), "page_size": 200}, headers=marcus),
        "GET /patients/{id}/vitals/latest": lambda _: client.get(f"/api/v1/patients/{p5}/vitals/latest", headers=marcus),
        "GET /patients/{id}/vitals/daily-summary (21 days)": lambda _: client.get(
            f"/api/v1/patients/{p5}/vitals/daily-summary",
            params={"start_date": str((now - timedelta(days=21)).date()), "end_date": str(now.date())}, headers=marcus),
        "GET /patients/{id}/daily-activity/summary": lambda _: client.get(
            f"/api/v1/patients/{p5}/daily-activity/summary", params={"start_date": str(week_ago)}, headers=marcus),
        "POST /patients/search": lambda _: client.post("/api/v1/patients/search", json={"q": "reed"}, headers=marcus),
    }
    results["endpoints"] = {}
    for name, fn in reads.items():
        assert fn(0).status_code == 200, name
        results["endpoints"][name] = stats(timed(fn, n))
        print(f"{name:55s} p50 {results['endpoints'][name]['p50_ms']:7.2f} ms  p95 {results['endpoints'][name]['p95_ms']:7.2f} ms")

    # ------------------------------------------------------------ index effectiveness on the main access pattern
    big = None
    with engine.connect() as conn:
        big = conn.execute(text("select patient_id from vital_signs group by patient_id order by count(*) desc limit 1")).scalar()
        q = text("select vital_id, recorded_at, heart_rate from vital_signs where patient_id = :p and "
                 "recorded_at >= :s and recorded_at < :e order by recorded_at desc limit 200")
        params = {"p": big, "s": now - timedelta(days=2), "e": now - timedelta(days=1)}
        if engine.dialect.name == "sqlite":
            params = {"p": big.hex if isinstance(big, uuid.UUID) else big,
                      "s": (now - timedelta(days=2)).replace(tzinfo=None).isoformat(sep=" "),
                      "e": (now - timedelta(days=1)).replace(tzinfo=None).isoformat(sep=" ")}
            plan_sql = "EXPLAIN QUERY PLAN "
        else:
            plan_sql = "EXPLAIN "

        def run_query(_: int) -> None:
            conn.execute(q, params).fetchall()

        def plan(tag: str) -> str:
            # a distinct sql comment forces a fresh prepare; sqlite would otherwise reuse the cached explain
            # statement and report the plan from before the index was dropped
            return " | ".join(str(r[-1]) for r in conn.execute(text(f"{plan_sql}{q.text} -- {tag}"), params))

        rows_in_window = len(conn.execute(q, params).fetchall())
        patient_rows = conn.execute(text("select count(*) from vital_signs where patient_id = :p"),
                                    {"p": params["p"]}).scalar()
        with_idx = stats(timed(run_query, n))
        plan_with = plan("with-index")
        conn.execute(text("DROP INDEX ix_vital_signs_patient_time"))
        conn.execute(text("DROP INDEX IF EXISTS ix_vital_signs_device"))
        if engine.dialect.name == "postgresql":
            conn.execute(text("ANALYZE vital_signs"))
        without_idx = stats(timed(run_query, max(20, n // 5)))
        plan_without = plan("without-index")
        conn.execute(text("CREATE INDEX ix_vital_signs_patient_time ON vital_signs (patient_id, recorded_at)"))
        conn.execute(text("CREATE INDEX ix_vital_signs_device ON vital_signs (device_id)"))
        conn.commit()
    results["index_effectiveness"] = {
        "query": "readings for one patient in a 24-hour window, newest 200",
        "patient_total_rows": patient_rows, "rows_returned": rows_in_window,
        "with_index": with_idx, "without_index": without_idx,
        "speedup_p50": round(without_idx["p50_ms"] / max(with_idx["p50_ms"], 0.001), 1),
        "plan_with_index": plan_with, "plan_without_index": plan_without}
    print(f"index speedup (p50): {results['index_effectiveness']['speedup_p50']}x")

    (REPORTS / "performance.json").write_text(json.dumps(results, indent=2, default=str))
    (REPORTS / "performance.md").write_text(render(results))
    print(f"wrote {REPORTS / 'performance.md'}")


def render(r: dict) -> str:
    e, d = r["environment"], r["dataset"]
    lines = ["# HealthTrack Phase 3 performance results", "",
             f"Run {e['date']} on {e['os']} ({e['machine']}, {e['cpu_count']} CPUs), Python {e['python']}, "
             f"{e['database']} {e['database_version']}.", "",
             f"Dataset: {d['vital_signs_rows']:,} vital sign rows across {d['patients']} patients "
             f"(loaded in {d['load_seconds']} s). Requests run in-process through the full FastAPI stack "
             "(routing, authentication, authorization, validation, audit write), so network time is excluded.", "",
             "## Latency", "", "| Operation | n | p50 (ms) | p95 (ms) | p99 (ms) |", "|---|---|---|---|---|"]
    rows = {"POST /auth/token (bcrypt cost 12)": r["login"], "POST /patients/{id}/vitals (single reading)":
            r["ingest_single"], "POST /patients/{id}/vitals/batch (500 readings)": r["ingest_batch_500"],
            **r["endpoints"]}
    for name, s in rows.items():
        lines.append(f"| {name} | {s['n']} | {s['p50_ms']} | {s['p95_ms']} | {s['p99_ms']} |")
    b, ix = r["ingest_batch_500"], r["index_effectiveness"]
    lines += ["", "## Ingestion", "",
              f"Batch upload sustained about **{b['readings_per_second']:,} readings per second**. Replaying the last "
              f"batch returned {b['replay_duplicates']} duplicates and stored nothing ({b['replay_ms']} ms).", "",
              "## Index effectiveness", "",
              f"Query: {ix['query']}. The patient tested has {ix['patient_total_rows']:,} readings; the window returned "
              f"{ix['rows_returned']} of them.", "",
              "| | p50 (ms) | p95 (ms) |", "|---|---|---|",
              f"| With `ix_vital_signs_patient_time` | {ix['with_index']['p50_ms']} | {ix['with_index']['p95_ms']} |",
              f"| Without the index | {ix['without_index']['p50_ms']} | {ix['without_index']['p95_ms']} |", "",
              f"Speedup at p50: **{ix['speedup_p50']}x**.", "",
              f"Plan with index: `{ix['plan_with_index']}`", "", f"Plan without index: `{ix['plan_without_index']}`", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    main()
