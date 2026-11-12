"""home-device simulator: streams live readings for the seeded patients to a running api

each patient's app logs in with the patient's own account and posts readings the way a paired heart rate band,
blood pressure cuff, and pulse oximeter would, so alerts and live dashboard updates can be demonstrated and
measured end to end. the default script is accelerated: one reading per patient every 2 seconds.

  robert   exercise session with heart rate inside his zone (stable control)
  linda    resting readings; oxygen saturation dips below 90% twice in a row at 60 s (critical)
  thomas   exercise session; heart rate climbs past his 128 bpm ceiling at 30 s (critical, then repeats)
  james    resting; systolic 156 at 90 s, above his 150 override (moderate)
  maria    sends nothing (she is not adhering; the missed-session alert is already open)

usage:  python -m scripts.simulate_devices                       # api at http://localhost:8000, runs until ctrl-c
        python -m scripts.simulate_devices --interval 1 --duration 180 --api http://localhost:8000
"""
from __future__ import annotations

import argparse
import math
import random
import time
import uuid
from datetime import datetime, timezone

import httpx

PASSWORD = "HealthTrack-Demo-2026!"
P = lambda n: f"00000000-0000-4000-b000-{n:012d}"  # noqa: E731
D = lambda p, k: f"00000000-0000-4000-c000-0000000000{p}{k}"  # noqa: E731
LOGINS = {1: "r.alvarez@mail.example", 2: "l.chen@mail.example", 3: "j.whitaker@mail.example",
          5: "t.reed@mail.example"}


class PatientApp:
    def __init__(self, client: httpx.Client, n: int) -> None:
        self.c, self.n, self.pid = client, n, P(n)
        self.access = self.refresh = ""
        self.login()

    def login(self) -> None:
        r = self.c.post("/api/v1/auth/token", data={"username": LOGINS[self.n], "password": PASSWORD})
        r.raise_for_status()
        body = r.json()
        self.access, self.refresh = body["access_token"], body["refresh_token"]

    def send(self, context: str, device: int, **values: int) -> dict:
        body = {"recorded_at": datetime.now(timezone.utc).isoformat(), "context": context,
                "device_id": D(self.n, device), "idempotency_key": f"sim-{self.n}-{uuid.uuid4().hex[:16]}", **values}
        for attempt in range(2):
            r = self.c.post(f"/api/v1/patients/{self.pid}/vitals", json=body,
                            headers={"Authorization": f"Bearer {self.access}"})
            if r.status_code == 401 and attempt == 0:          # access tokens last 15 minutes: rotate and retry
                rr = self.c.post("/api/v1/auth/refresh", json={"refresh_token": self.refresh})
                if rr.status_code == 200:
                    self.access, self.refresh = rr.json()["access_token"], rr.json()["refresh_token"]
                else:
                    self.login()
                continue
            r.raise_for_status()
            return r.json()
        return {}


def readings(n: int, t: float, rng: random.Random) -> list[tuple[str, int, dict]]:
    """what each patient's devices report at t seconds into the demo"""
    wobble = 3 * math.sin(t / 7)
    if n == 1:
        return [("exercise", 1, {"heart_rate": round(108 + wobble + rng.uniform(-3, 3))})]
    if n == 2:
        out = [("rest", 1, {"heart_rate": round(72 + rng.uniform(-2, 2))}),
               ("rest", 3, {"spo2": 88 if 60 <= t < 66 else round(96 + rng.uniform(-1, 1))})]
        if int(t) % 30 == 0:
            out.append(("rest", 2, {"systolic_bp": round(130 + rng.uniform(-4, 4)), "diastolic_bp": 82}))
        return out
    if n == 5:
        climb = max(0.0, min(1.0, (t - 30) / 10))               # 110 -> 136 between 30 and 40 seconds
        return [("exercise", 1, {"heart_rate": round(110 + 26 * climb + wobble + rng.uniform(-2, 2))})]
    if n == 3:
        sbp = 156 if 90 <= t < 92 else round(138 + rng.uniform(-4, 4))
        out = [("rest", 1, {"heart_rate": round(78 + rng.uniform(-2, 2))})]
        if int(t) % 20 == 0 or 90 <= t < 92:
            out.append(("rest", 2, {"systolic_bp": sbp, "diastolic_bp": 84}))
        return out
    return []


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--interval", type=float, default=2.0, help="seconds between readings per patient")
    ap.add_argument("--duration", type=float, default=0, help="seconds to run (0 = until ctrl-c)")
    ap.add_argument("--seed", type=int, default=11)
    args = ap.parse_args()
    rng = random.Random(args.seed)
    with httpx.Client(base_url=args.api, timeout=10) as client:
        apps = {n: PatientApp(client, n) for n in LOGINS}
        print(f"streaming for {len(apps)} patients every {args.interval:g} s (ctrl-c to stop)")
        t0 = time.monotonic()
        sent = alerts = 0
        try:
            while not args.duration or time.monotonic() - t0 < args.duration:
                t = time.monotonic() - t0
                for n, app in apps.items():
                    for ctx, device, values in readings(n, t, rng):
                        app.send(ctx, device, **values)
                        sent += 1
                if int(t) % 10 == 0:
                    alerts = client.get("/api/v1/health").json().get("stream_subscribers", 0)
                    print(f"{t:6.0f} s  readings sent: {sent:5d}  dashboards connected: {alerts}")
                time.sleep(max(0.0, args.interval - (time.monotonic() - t0 - t)))
        except KeyboardInterrupt:
            pass
        print(f"stopped after {time.monotonic() - t0:.0f} s; {sent} readings sent")


if __name__ == "__main__":
    main()
