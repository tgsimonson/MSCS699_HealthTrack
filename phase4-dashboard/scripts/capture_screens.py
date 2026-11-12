"""screenshots for the user guide and design document (docs/images/)

starts a throwaway api and dashboard like measure_dashboard, plays a 40-minute exercise session for thomas reed
that ends above his heart rate ceiling, and captures the main views.
usage:  python -m scripts.capture_screens  [--api-dir ../phase4-alert-system]
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.measure_dashboard import (CHARTS_READY, PASSWORD, ROOT, THOMAS, THOMAS_BAND, Api, free_port,
                                       wait_http)

OUT = ROOT / "docs" / "images"


def session_readings(end: datetime) -> list[dict]:
    """warmup, 30 minutes of exercise in the target zone, then two readings above the 128 bpm ceiling"""
    out = []
    for m in range(36):
        at = end - timedelta(minutes=36 - m)
        ctx = "warmup" if m < 5 else "exercise"
        hr = 78 + m * 6 if m < 5 else 104 + (m * 7) % 9
        out.append({"recorded_at": at.isoformat(), "context": ctx, "heart_rate": hr, "device_id": THOMAS_BAND,
                    "idempotency_key": f"guide-session-{m:04d}"})
    for i, hr in enumerate((133, 138)):
        out.append({"recorded_at": (end - timedelta(seconds=45 - 30 * i)).isoformat(), "context": "exercise",
                    "heart_rate": hr, "device_id": THOMAS_BAND, "idempotency_key": f"guide-breach-{i:04d}"})
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api-dir", default=str(ROOT.parent / "phase4-alert-system"))
    args = ap.parse_args()
    from playwright.sync_api import sync_playwright

    api_dir = Path(args.api_dir).resolve()
    api_py = next((p for p in (api_dir / ".venv/bin/python", api_dir / ".venv/Scripts/python.exe") if p.exists()),
                  Path(sys.executable))
    tmp = Path(tempfile.mkdtemp(prefix="ht_dash_shots_"))
    api_port, dash_port = free_port(), free_port()
    api_url, dash_url = f"http://127.0.0.1:{api_port}", f"http://127.0.0.1:{dash_port}"
    env = {**os.environ, "HT_DATABASE_URL": f"sqlite:///{tmp / 'shots.db'}", "HT_LOG_LEVEL": "WARNING",
           "HT_JWT_SECRET": "shots-" + "x" * 40, "HT_OUTBOX_DIR": str(tmp / "outbox"),
           "HT_CORS_ORIGINS": dash_url, "HT_DASHBOARD_URL": dash_url, "HT_LOGIN_RATE_LIMIT": "1000"}
    OUT.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(api_py), "-m", "alembic", "upgrade", "head"], cwd=api_dir, env=env, check=True,
                   capture_output=True)
    subprocess.run([str(api_py), "-m", "scripts.seed"], cwd=api_dir, env=env, check=True, capture_output=True)
    procs = [subprocess.Popen([str(api_py), "-m", "uvicorn", "app.main:app", "--port", str(api_port),
                               "--log-level", "warning"], cwd=api_dir, env=env, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL),
             subprocess.Popen([sys.executable, "-m", "dashboard", "--port", str(dash_port), "--api", api_url],
                              cwd=ROOT, env={**os.environ, "HT_DASH_SECRET": "shots"}, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL)]
    try:
        wait_http(f"{api_url}/api/v1/health")
        wait_http(dash_url)
        api = Api(api_url)
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1500, "height": 960}, device_scale_factor=2)
            page.goto(dash_url)
            page.wait_for_selector("#login-email")
            page.screenshot(path=str(OUT / "sign_in.png"))
            page.fill("#login-email", "marcus.lee@healthtrack.example")
            page.fill("#login-password", PASSWORD)
            page.click("#login-submit")
            page.wait_for_function(CHARTS_READY, timeout=20000)
            page.wait_for_function("document.querySelector('#conn-pill').innerText.includes('Live')", timeout=15000)
            page.click(f'button[data-patient="{THOMAS}"]')
            page.click("text=1 h")
            page.wait_for_function(CHARTS_READY, timeout=20000)
            page.wait_for_timeout(800)
            r = api.c.post(f"/patients/{THOMAS}/vitals/batch", headers=api.h("t.reed@mail.example"),
                           json={"readings": session_readings(datetime.now(timezone.utc))})
            r.raise_for_status()
            page.wait_for_selector(".toast.sev-critical", timeout=15000)
            page.wait_for_timeout(1200)
            page.screenshot(path=str(OUT / "overview_critical.png"), full_page=True)
            page.locator(".alerts-col").screenshot(path=str(OUT / "alert_panel.png"))
            page.locator(".worklist-col").screenshot(path=str(OUT / "worklist.png"))
            page.locator(".alert-item.sev-critical button", has_text="Acknowledge").first.click()
            page.wait_for_function("[...document.querySelectorAll('.alert-item.sev-critical')]"
                                   ".some(e => e.innerText.toUpperCase().includes('ACKNOWLEDGED'))", timeout=10000)
            page.wait_for_timeout(600)
            page.locator(".alerts-col").screenshot(path=str(OUT / "alert_acknowledged.png"))
            page.click("text=7 days")
            page.wait_for_function(CHARTS_READY, timeout=20000)
            page.wait_for_timeout(1000)
            page.locator(".main-col").screenshot(path=str(OUT / "seven_day_view.png"))
            browser.close()
    finally:
        for p in procs:
            p.terminate()
    for f in sorted(OUT.glob("*.png")):
        print("wrote", f.relative_to(ROOT))


if __name__ == "__main__":
    main()
