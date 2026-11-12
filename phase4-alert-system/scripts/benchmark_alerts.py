"""alert system performance benchmark

builds a fresh database with the migrations, loads the seed data plus a synthetic load of patients with
prescriptions, then measures:
  1 rule evaluation cost per reading (normal, repeat, new alert)
  2 ingestion latency with alert evaluation on and off (single reading and 500-reading batch)
  3 end-to-end latency from posting a breaching reading to the alert, and then the notification, arriving on a
    connected websocket (requirement NFR-07: critical alerts on the dashboard within 5 s)
  4 notification dispatch delay (queued to sent) with the background workers running
  5 scheduled job run time: pattern detection across all active patients, escalation checks
  6 alert fatigue: a noisy 48-hour patient, comparing raw threshold crossings with alerts and notifications
  7 websocket fan-out: one event delivered to many connected dashboards

everything runs in-process (fastapi testclient), so network time is excluded.
usage:  python -m scripts.benchmark_alerts            writes reports/alert_performance.json and .md
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import random
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
PASSWORD = "HealthTrack-Demo-2026!"


def main() -> None:  # noqa: PLR0915
    ap = argparse.ArgumentParser()
    ap.add_argument("--patients", type=int, default=100, help="synthetic patients in addition to the seed data")
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--iterations", type=int, default=200)
    ap.add_argument("--e2e", type=int, default=50, help="end-to-end websocket alert measurements")
    ap.add_argument("--render-only", action="store_true",
                    help="rewrite alert_performance.md from the saved alert_performance.json without measuring")
    args = ap.parse_args()
    if args.render_only:
        saved = json.loads((REPORTS / "alert_performance.json").read_text())
        (REPORTS / "alert_performance.md").write_text(render(saved) + "\n")
        print(f"wrote {REPORTS / 'alert_performance.md'} from the saved measurements")
        return

    REPORTS.mkdir(exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="ht_alert_bench_"))
    url = f"sqlite:///{tmp / 'bench.db'}"
    os.environ.update({"HT_DATABASE_URL": url, "HT_LOG_LEVEL": "ERROR", "HT_LOGIN_RATE_LIMIT": "100000",
                       "HT_OUTBOX_DIR": str(tmp / "outbox"), "HT_ALERT_WORKERS": "1",
                       "HT_ESCALATION_CHECK_SECONDS": "86400", "HT_PATTERN_CHECK_MINUTES": "1440",
                       "HT_DISPATCH_POLL_SECONDS": "2"})
    os.environ.setdefault("HT_BCRYPT_ROUNDS", "12")
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT, env=dict(os.environ), check=True,
                   capture_output=True)
    print(f"database: {url}")

    from fastapi.testclient import TestClient
    from sqlalchemy import insert, select, text, update

    from app.alerts.engine import AlertEngine
    from app.db import SessionLocal, engine
    from app.main import app
    from app.models import (Alert, AlertRule, DailyActivity, Device, ExercisePrescription, Notification, Patient,
                            User, VitalSign)
    from app.models.enums import (AlertStatus, ClinicalRisk, DeviceStatus, DeviceType, ProgramStatus,
                                  QualifyingEvent, ReadingContext, ReadingSource, SexAtBirth)
    from app.realtime.broker import Broker
    from scripts.benchmark import pct, stats, timed
    from scripts.seed import P, U, seed

    res: dict = {"environment": {
        "date": datetime.now(timezone.utc).isoformat(timespec="seconds"), "os": platform.platform(),
        "machine": platform.machine(), "cpu_count": os.cpu_count(), "python": platform.python_version(),
        "database": engine.dialect.name, "load": vars(args)}}

    # ------------------------------------------------------------ data
    t0 = time.perf_counter()
    with SessionLocal() as db:
        res["environment"]["database_version"] = db.execute(text("select sqlite_version()")).scalar()
        seed(db, days=21)
        rng = random.Random(7)
        start = datetime.now(timezone.utc) - timedelta(days=args.days)
        for i in range(args.patients):
            pid, dev = uuid.uuid4(), uuid.uuid4()
            db.add(Patient(patient_id=pid, mrn=f"HT-A{i:05d}", first_name=f"Load{i}", last_name="Patient",
                           date_of_birth=date(1960, 1, 1), sex=SexAtBirth.unknown, qualifying_event=QualifyingEvent.pci,
                           qualifying_event_date=date(2026, 9, 1), referral_date=date(2026, 9, 2),
                           enrollment_date=date(2026, 9, 3), program_status=ProgramStatus.active,
                           clinical_risk_category=ClinicalRisk.low))
            db.flush()
            db.add(Device(device_id=dev, patient_id=pid, device_type=DeviceType.heart_rate_band, manufacturer="Corvane",
                          model="HB-2", serial_number=f"ALOAD-{i}", status=DeviceStatus.active))
            db.add(ExercisePrescription(patient_id=pid, resting_hr_baseline=66, target_hr_min=95, target_hr_max=118,
                                        hr_ceiling=130, prescribed_by=U(3), effective_from=start - timedelta(days=1)))
            db.flush()
            rows = []
            for d in range(args.days):
                day = start + timedelta(days=d)
                rows += [{"patient_id": pid, "device_id": dev, "recorded_at": day + timedelta(minutes=15 * k),
                          "received_at": day + timedelta(minutes=15 * k), "context": ReadingContext.rest,
                          "heart_rate": rng.randint(58, 92), "source": ReadingSource.device, "quality": "valid"}
                         for k in range(72)]
                if d % 2 == 0:
                    rows += [{"patient_id": pid, "device_id": dev, "recorded_at": day + timedelta(hours=18, minutes=m),
                              "received_at": day + timedelta(hours=18, minutes=m), "context": ReadingContext.exercise,
                              "heart_rate": rng.randint(98, 116), "source": ReadingSource.device, "quality": "valid"}
                             for m in range(25)]
            db.execute(insert(VitalSign), rows)
            db.execute(insert(DailyActivity), [{"patient_id": pid, "activity_date": (start + timedelta(days=d)).date(),
                                                "steps": rng.randint(4000, 8000), "active_minutes": 40,
                                                "resting_hr": rng.randint(62, 70), "source": ReadingSource.device}
                                               for d in range(args.days)])
        db.commit()
        n_vitals = db.execute(text("select count(*) from vital_signs")).scalar()
        n_active = db.execute(text("select count(*) from patients where program_status = 'active'")).scalar()
    res["dataset"] = {"vital_signs_rows": n_vitals, "active_patients": n_active,
                      "load_seconds": round(time.perf_counter() - t0, 2)}
    print(f"loaded {n_vitals:,} readings for {n_active} active patients")

    # ------------------------------------------------------------ 1 rule evaluation cost
    robert = P(1)
    with SessionLocal() as db:
        eng = AlertEngine(db)
        base = datetime.now(timezone.utc) - timedelta(hours=2)

        def reading(i: int, hr: int, ctx=ReadingContext.exercise) -> VitalSign:  # noqa: ANN001
            v = VitalSign(patient_id=robert, recorded_at=base + timedelta(seconds=5 * i), context=ctx, heart_rate=hr,
                          quality="valid", source=ReadingSource.device)
            db.add(v)
            db.flush()
            return v

        n = args.iterations
        normal = timed(lambda i: eng.evaluate_readings(robert, [reading(i, 108)]), n)
        db.rollback()
        reading(-2, 140)
        reading(-1, 141)
        eng.evaluate_readings(robert, db.scalars(select(VitalSign).where(VitalSign.heart_rate >= 140,
                                                                          VitalSign.patient_id == robert)).all())
        repeat = timed(lambda i: eng.evaluate_readings(robert, [reading(i, 142)]), n)
        db.rollback()
        new_ms = []
        for i in range(n):
            reading(2 * i, 140)
            v = reading(2 * i + 1, 141)
            t = time.perf_counter()
            out = eng.evaluate_readings(robert, [v])
            new_ms.append((time.perf_counter() - t) * 1000)
            for o in out:
                o.alert.status, o.alert.resolved_at, o.alert.resolved_by, o.alert.resolution_note = (
                    AlertStatus.resolved, o.alert.triggered_at, U(1), "bench")
                o.alert.acknowledged_at, o.alert.acknowledged_by = o.alert.triggered_at, U(1)
            db.flush()
        db.rollback()
    res["rule_evaluation"] = {"normal_reading": stats(normal), "breach_repeat": stats(repeat),
                              "breach_new_alert": stats(new_ms)}
    print(f"rule evaluation p50: normal {pct(normal, 50):.2f} ms, repeat {pct(repeat, 50):.2f} ms, "
          f"new alert {pct(new_ms, 50):.2f} ms")

    # ------------------------------------------------------------ 2 ingestion with alerts on and off
    with TestClient(app) as client:
        def token(email: str) -> dict:
            r = client.post("/api/v1/auth/token", data={"username": email, "password": PASSWORD})
            return {"Authorization": "Bearer " + r.json()["access_token"]}

        robert_h, thomas_h, marcus_h = (token("r.alvarez@mail.example"), token("t.reed@mail.example"),
                                        token("marcus.lee@healthtrack.example"))
        band1, band5 = "00000000-0000-4000-c000-000000000011", "00000000-0000-4000-c000-000000000051"

        def post_single(tag: str):  # noqa: ANN202
            def f(i: int) -> None:
                r = client.post(f"/api/v1/patients/{robert}/vitals", headers=robert_h, json={
                    "recorded_at": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
                    "context": "exercise", "heart_rate": 106 + i % 6, "device_id": band1,
                    "idempotency_key": f"bench-{tag}-{i:06d}"})
                assert r.status_code == 201, r.text
            return f

        def batch(tag: str, b: int) -> float:
            now = datetime.now(timezone.utc)
            body = {"readings": [{"recorded_at": (now - timedelta(seconds=500 - k)).isoformat(),
                                  "context": "exercise", "heart_rate": 104 + k % 10, "device_id": band1,
                                  "idempotency_key": f"bench-{tag}-{b}-{k:04d}"} for k in range(500)]}
            t = time.perf_counter()
            r = client.post(f"/api/v1/patients/{robert}/vitals/batch", headers=robert_h, json=body)
            assert r.status_code == 200 and r.json()["accepted"] == 500
            return (time.perf_counter() - t) * 1000

        def set_rules(active: bool) -> None:
            with SessionLocal() as db:
                db.execute(update(AlertRule).values(is_active=active))
                db.commit()

        # on and off runs alternate in small blocks so table growth affects both equally
        on_single, off_single, on_batch, off_batch = [], [], [], []
        block = 20
        for k in range(max(1, args.iterations // block)):
            for active, sink in ((True, on_single), (False, off_single)):
                set_rules(active)
                sink += timed(lambda i, a=active, k=k: post_single("on" if a else "off")(k * block + i), block)
            for active, sink in ((True, on_batch), (False, off_batch)):
                set_rules(active)
                sink.append(batch("on" if active else "off", k))
        set_rules(True)
        res["ingestion"] = {
            "single_rules_on": stats(on_single), "single_rules_off": stats(off_single),
            "batch500_rules_on": {**stats(on_batch), "readings_per_second": round(500 / (pct(on_batch, 50) / 1000))},
            "batch500_rules_off": {**stats(off_batch), "readings_per_second": round(500 / (pct(off_batch, 50) / 1000))},
            "single_overhead_p50_ms": round(pct(on_single, 50) - pct(off_single, 50), 2)}
        print(f"single ingest p50: rules on {pct(on_single, 50):.2f} ms, off {pct(off_single, 50):.2f} ms")

        # -------------------------------------------------------- 3 end to end over the websocket
        e2e_alert, e2e_note, e2e_vital = [], [], []
        e2e_started = datetime.now(timezone.utc)
        with client.websocket_connect("/api/v1/stream") as ws:
            ws.send_json({"type": "auth", "token": marcus_h["Authorization"].split()[1]})
            assert ws.receive_json()["type"] == "ready"
            for i in range(args.e2e):
                now = datetime.now(timezone.utc)
                body = {"readings": [{"recorded_at": (now - timedelta(seconds=10 - k)).isoformat(), "context": "exercise",
                                      "heart_rate": 139 + k, "device_id": band5, "idempotency_key": f"e2e-{i:04d}-{k}"}
                                     for k in range(2)]}
                t = time.perf_counter()
                r = client.post(f"/api/v1/patients/{P(5)}/vitals/batch", headers=thomas_h, json=body)
                assert r.json()["alerts_raised"] == 1, r.text
                alert_id = got_alert = got_note = None
                while got_alert is None or got_note is None:
                    msg = ws.receive_json()
                    elapsed = (time.perf_counter() - t) * 1000
                    if msg["type"] == "vital" and len(e2e_vital) <= i:
                        e2e_vital.append(elapsed)
                    elif msg["type"] == "alert" and msg["action"] == "created":
                        got_alert, alert_id = elapsed, msg["data"]["alert_id"]
                    elif msg["type"] == "notification" and msg["data"]["alert_id"] == alert_id:
                        got_note = elapsed
                e2e_alert.append(got_alert)
                e2e_note.append(got_note)
                client.post(f"/api/v1/alerts/{alert_id}/resolve", headers=marcus_h, json={"note": "benchmark run"})
        res["end_to_end"] = {"reading_to_vital_event": stats(e2e_vital), "reading_to_alert_event": stats(e2e_alert),
                             "reading_to_dashboard_notification": stats(e2e_note), "target_p95_ms": 5000}
        print(f"end to end p95: alert {pct(e2e_alert, 95):.1f} ms, notification {pct(e2e_note, 95):.1f} ms")

        # -------------------------------------------------------- 4 dispatch delay
        time.sleep(2.5)                       # let the poll fallback finish anything still queued
        with SessionLocal() as db:
            rows = db.execute(select(Notification.channel, Notification.queued_at, Notification.sent_at)
                              .join(Alert, Alert.alert_id == Notification.alert_id)
                              .where(Alert.patient_id == P(5), Notification.sent_at.is_not(None),
                                     Notification.queued_at >= e2e_started)).all()
        by_channel: dict[str, list[float]] = {}
        for ch, q, s in rows:
            by_channel.setdefault(ch.value, []).append((s - q).total_seconds() * 1000)
        res["dispatch_delay"] = {ch: stats(v) for ch, v in sorted(by_channel.items())}

    # ------------------------------------------------------------ 5 scheduled jobs
    with SessionLocal() as db:
        t = time.perf_counter()
        outcomes = AlertEngine(db).evaluate_patterns()
        pattern_s = time.perf_counter() - t
        db.rollback()
        eng = AlertEngine(db)
        rule = eng.repo.get_rule("RESTING_HR_HIGH")
        pids = list(db.scalars(select(Patient.patient_id).where(Patient.program_status == ProgramStatus.active)))
        old = datetime.now(timezone.utc) - timedelta(hours=6)
        for pid in pids:
            eng.raise_alert(pid, rule, title="bench", triggering={}, threshold=100, source="default", now=old)
        db.flush()
        open_now = db.scalar(select(text("count(*)")).select_from(Alert).where(
            Alert.status.in_((AlertStatus.open, AlertStatus.escalated))))
        t = time.perf_counter()
        escalated = eng.run_escalations()
        esc_s = time.perf_counter() - t
        db.rollback()
    res["jobs"] = {"pattern_run_seconds": round(pattern_s, 3), "patients": n_active,
                   "pattern_ms_per_patient": round(pattern_s * 1000 / n_active, 2),
                   "pattern_outcomes": len(outcomes), "escalation_run_seconds": round(esc_s, 3),
                   "open_alerts_checked": open_now, "escalated": len(escalated)}
    print(f"pattern job: {pattern_s:.2f} s for {n_active} patients; escalation check: {esc_s * 1000:.0f} ms")

    # ------------------------------------------------------------ 6 alert fatigue (noisy 48 hours)
    with SessionLocal() as db:
        eng = AlertEngine(db)
        linda = P(2)
        rng = random.Random(3)
        t_start = datetime.now(timezone.utc) - timedelta(hours=48)
        raw = {"heart_rate": 0, "systolic_bp": 0}
        created = repeated = suppressed = 0
        resolve_at: list[tuple[datetime, Alert]] = []
        for k in range(48 * 4):                                  # a resting reading every 15 minutes
            at = t_start + timedelta(minutes=15 * k)
            for when, a in [x for x in resolve_at if x[0] <= at]:
                if a.status in (AlertStatus.open, AlertStatus.acknowledged):
                    eng.resolve(a, db.get(User, U(1)), "Rechecked; within range.", now=when)
                resolve_at.remove((when, a))
            hr = round(100 + rng.gauss(0, 5))
            sbp = round(158 + rng.gauss(0, 5))
            raw["heart_rate"] += hr > 100
            raw["systolic_bp"] += sbp >= 160
            v = VitalSign(patient_id=linda, recorded_at=at, context=ReadingContext.rest, heart_rate=hr,
                          systolic_bp=sbp, diastolic_bp=84, quality="valid", source=ReadingSource.device)
            db.add(v)
            db.flush()
            for o in eng.evaluate_readings(linda, [v], now=at + timedelta(seconds=5)):
                if o.action == "created":
                    created += 1
                    resolve_at.append((at + timedelta(minutes=45), o.alert))
                elif o.action == "repeated":
                    repeated += 1
                else:
                    suppressed += 1
        db.flush()
        sent = db.scalar(select(text("count(*)")).select_from(Notification).join(Alert).where(
            Alert.patient_id == linda, Alert.triggered_at >= t_start))
        db.rollback()
    crossings = raw["heart_rate"] + raw["systolic_bp"]
    res["alert_fatigue"] = {"readings": 48 * 4, "threshold_crossings": crossings, "alerts_created": created,
                            "repeats_folded": repeated, "suppressed": suppressed, "notifications": sent,
                            "alerts_per_crossing": round(created / crossings, 3) if crossings else None}
    print(f"fatigue: {crossings} crossings -> {created} alerts, {repeated} repeats folded, {suppressed} suppressed")

    # ------------------------------------------------------------ 7 websocket fan-out
    async def fanout(subscribers: int, events: int) -> dict:
        bus = Broker(queue_size=events + 10)
        pid = uuid.uuid4()
        subs = [bus.subscribe(uuid.uuid4(), {pid}) for _ in range(subscribers)]
        done = asyncio.Event()
        loop = asyncio.get_running_loop()

        async def drain(sub) -> None:  # noqa: ANN001
            for _ in range(events):
                await sub.queue.get()

        tasks = [asyncio.create_task(drain(s)) for s in subs]
        t = time.perf_counter()

        def publisher() -> None:
            for i in range(events):
                bus.publish({"type": "vital", "patient_id": str(pid), "data": {"i": i}})
            loop.call_soon_threadsafe(done.set)

        threading.Thread(target=publisher).start()
        await done.wait()
        publish_s = time.perf_counter() - t
        await asyncio.gather(*tasks)
        total_s = time.perf_counter() - t
        return {"subscribers": subscribers, "events": events, "deliveries": subscribers * events,
                "publish_us_per_event": round(publish_s * 1e6 / events, 1),
                "deliveries_per_second": round(subscribers * events / total_s)}

    res["fanout"] = [asyncio.run(fanout(s, 1000)) for s in (1, 10, 50)]

    (REPORTS / "alert_performance.json").write_text(json.dumps(res, indent=2, default=str))
    (REPORTS / "alert_performance.md").write_text(render(res))
    print(f"wrote {REPORTS / 'alert_performance.md'}")


def batch_note(ing: dict) -> str:
    """say so when the batch on/off gap is inside the run-to-run spread, instead of implying rules make it faster"""
    on, off = ing["batch500_rules_on"], ing["batch500_rules_off"]
    gap = on["p50_ms"] - off["p50_ms"]
    spread = max(on["p95_ms"] - on["p50_ms"], off["p95_ms"] - off["p50_ms"])
    if abs(gap) >= spread:
        return ""
    return (f" The batch medians differ by {abs(gap):.2f} ms, less than the spread within either set of {on['n']} "
            f"batches (up to {spread:.2f} ms between median and 95th percentile), so this run cannot separate the "
            f"cost of alert evaluation for a batch from run-to-run variation; the single-reading comparison, over "
            f"{ing['single_rules_on']['n']} requests each, is the better estimate.")


def render(r: dict) -> str:
    e, d = r["environment"], r["dataset"]

    def row(name: str, s: dict) -> str:
        return f"| {name} | {s['n']} | {s['p50_ms']:.2f} | {s['p95_ms']:.2f} | {s['max_ms']:.2f} |"

    re, ing, ee, j, f = r["rule_evaluation"], r["ingestion"], r["end_to_end"], r["jobs"], r["alert_fatigue"]
    head = "| Measurement | n | p50 (ms) | p95 (ms) | max (ms) |\n|---|---|---|---|---|"
    out = [
        "# HealthTrack alert system performance", "",
        f"Run {e['date']} on {e['os']} ({e['machine']}, {e['cpu_count']} cores), Python {e['python']}, "
        f"{e['database']} {e['database_version']}. Dataset: {d['vital_signs_rows']:,} readings, "
        f"{d['active_patients']} active patients. All requests run in-process, so network time is excluded.", "",
        "## 1. Rule evaluation per reading", "", head,
        row("Normal reading (no breach)", re["normal_reading"]),
        row("Breach folded into an open alert", re["breach_repeat"]),
        row("Breach creating a new alert and notifications", re["breach_new_alert"]), "",
        "## 2. Ingestion with alert evaluation on and off", "", head,
        row("Single reading, rules on", ing["single_rules_on"]), row("Single reading, rules off", ing["single_rules_off"]),
        row("Batch of 500, rules on", ing["batch500_rules_on"]), row("Batch of 500, rules off", ing["batch500_rules_off"]),
        "", f"Alert evaluation adds {ing['single_overhead_p50_ms']:.2f} ms to a single reading at the median. Batch "
            f"throughput: {ing['batch500_rules_on']['readings_per_second']:,} readings/s with rules on, "
            f"{ing['batch500_rules_off']['readings_per_second']:,} with rules off.{batch_note(ing)}", "",
        "## 3. End to end: breaching reading posted to event on a connected dashboard", "", head,
        row("Reading to live reading event", ee["reading_to_vital_event"]),
        row("Reading to critical alert event", ee["reading_to_alert_event"]),
        row("Reading to dashboard notification", ee["reading_to_dashboard_notification"]), "",
        f"Requirement NFR-07: critical alerts on the dashboard within 5 s (5000 ms) at the 95th percentile. "
        f"Measured p95: {ee['reading_to_alert_event']['p95_ms']:.1f} ms for the alert event and "
        f"{ee['reading_to_dashboard_notification']['p95_ms']:.1f} ms for the notification. "
        f"{'Met.' if ee['reading_to_dashboard_notification']['p95_ms'] < 5000 else 'Not met.'}", "",
        "## 4. Notification dispatch delay (queued to sent, background workers)", "", head,
        *[row("SMS" if ch == "sms" else ch.capitalize(), s) for ch, s in r["dispatch_delay"].items()], "",
        "Every channel for an alert is queued in the same transaction and sent in the same dispatch pass, so the "
        "channels share one delay. Email and SMS were written to the local outbox (no gateway configured), so these "
        "times exclude any external provider.", "",
        "## 5. Scheduled jobs", "",
        f"- Pattern detection across {j['patients']} active patients: {j['pattern_run_seconds']:.2f} s "
        f"({j['pattern_ms_per_patient']:.1f} ms per patient), {j['pattern_outcomes']} outcomes.",
        f"- Escalation check over {j['open_alerts_checked']} open alerts: {j['escalation_run_seconds'] * 1000:.0f} ms "
        f"({j['escalated']} escalated).", "",
        "## 6. Alert fatigue: one noisy patient over 48 hours", "",
        "A resting reading every 15 minutes with heart rate around the 100 bpm limit and systolic pressure around 160 "
        "mmHg; each alert is resolved 45 minutes after it opens.", "",
        "| Readings | Threshold crossings | Alerts created | Repeats folded | Suppressed | Notifications |",
        "|---|---|---|---|---|---|",
        f"| {f['readings']} | {f['threshold_crossings']} | {f['alerts_created']} | {f['repeats_folded']} | "
        f"{f['suppressed']} | {f['notifications']} |", "",
        f"Without deduplication and suppression each crossing would notify; here {f['threshold_crossings']} crossings "
        f"produced {f['notifications']} notifications "
        f"({(1 - f['notifications'] / max(f['threshold_crossings'], 1)) * 100:.0f}% fewer).", "",
        "## 7. WebSocket fan-out (in-process broker)", "",
        "| Subscribers | Events | Deliveries | Publish cost (us/event) | Deliveries per second |", "|---|---|---|---|---|",
        *[f"| {x['subscribers']} | {x['events']} | {x['deliveries']:,} | {x['publish_us_per_event']} | "
          f"{x['deliveries_per_second']:,} |" for x in r["fanout"]], ""]
    return "\n".join(out)


if __name__ == "__main__":
    main()
