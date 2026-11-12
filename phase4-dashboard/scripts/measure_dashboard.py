"""end-to-end dashboard tests in a real browser: load time, real-time update latency, alert-to-screen time, data
accuracy against the api, reconnection, and acknowledging through the ui

starts a throwaway copy of the alert-system api (fresh sqlite database, migrations, seed data) and the dashboard,
then drives headless chromium with playwright. all times come from this machine's clock.

usage:  python -m scripts.measure_dashboard                      # api project at ../phase4-alert-system
        python -m scripts.measure_dashboard --api-dir /path/to/phase4-alert-system --runs 10
writes reports/dashboard_e2e.json, reports/dashboard_test_results.md, and screenshots in reports/screens/
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import socket
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
PASSWORD = "HealthTrack-Demo-2026!"
THOMAS = "00000000-0000-4000-b000-000000000005"
THOMAS_BAND = "00000000-0000-4000-c000-000000000051"
MARCUS = "00000000-0000-4000-a000-000000000002"
CRITICAL = "#B42318"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def stats(values: list[float]) -> dict:
    v = sorted(values)
    if not v:
        return {"n": 0}
    p95 = v[min(len(v) - 1, max(0, round(0.95 * len(v)) - 1))]
    return {"n": len(v), "p50_ms": round(statistics.median(v), 1), "p95_ms": round(p95, 1),
            "max_ms": round(v[-1], 1), "min_ms": round(v[0], 1)}


def wait_http(url: str, seconds: float = 30) -> None:
    end = time.time() + seconds
    while time.time() < end:
        try:
            if httpx.get(url, timeout=1).status_code < 500:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    raise SystemExit(f"{url} did not start")


class Api:
    def __init__(self, base: str) -> None:
        self.c = httpx.Client(base_url=f"{base}/api/v1", timeout=10)
        self.tokens: dict[str, str] = {}
        self.last_at = datetime.now(timezone.utc)

    def h(self, email: str) -> dict:
        if email not in self.tokens:
            r = self.c.post("/auth/token", data={"username": email, "password": PASSWORD})
            r.raise_for_status()
            self.tokens[email] = r.json()["access_token"]
        return {"Authorization": f"Bearer {self.tokens[email]}"}

    def post_hr(self, values: list[int], ctx: str = "exercise") -> list[int]:
        ids = []
        for v in values:
            # device clocks only move forward: each reading is stamped after the previous one
            at = max(datetime.now(timezone.utc), self.last_at + timedelta(milliseconds=500))
            self.last_at = at
            r = self.c.post(f"/patients/{THOMAS}/vitals", headers=self.h("t.reed@mail.example"), json={
                "recorded_at": at.isoformat(), "context": ctx, "heart_rate": v, "device_id": THOMAS_BAND})
            r.raise_for_status()
            ids.append(r.json()["vital_id"])
        return ids

    def resolve_open_thomas(self) -> None:
        m = self.h("marcus.lee@healthtrack.example")
        for a in self.c.get("/alerts", headers=m, params={"patient_id": THOMAS}).json()["items"]:
            self.c.post(f"/alerts/{a['alert_id']}/resolve", headers=m, json={"note": "measurement run"})


# the patient view is ready when the bundle has loaded and every chart has rendered its svg
CHARTS_READY = ("document.querySelector('#loaded-at') && document.querySelector('#loaded-at').innerText"
                ".includes('readings loaded') && ['#hr-graph', '#bp-graph', '#spo2-graph', '#activity-graph', '#g-hr']"
                ".every(id => document.querySelector(id + ' .main-svg'))")

OBSERVER = """
() => {
  window.__seen = {};
  const before = new Set([...document.querySelectorAll('.toast')].map(t => t.dataset.alert));
  const mark = (k) => { if (!window.__seen[k]) window.__seen[k] = Date.now(); };
  const check = () => {
    if (document.querySelector('.alert-item.sev-critical')) mark('alert');
    if ([...document.querySelectorAll('.toast.sev-critical')].some(t => !before.has(t.dataset.alert))) mark('toast');
    const first = document.querySelector('.patient-card');
    if (first && first.classList.contains('sev-critical')) mark('worklist');
  };
  new MutationObserver(check).observe(document.body, {subtree: true, childList: true, attributes: true});
  check();
}
"""


def main() -> None:  # noqa: PLR0915
    ap = argparse.ArgumentParser()
    ap.add_argument("--api-dir", default=str(ROOT.parent / "phase4-alert-system"))
    ap.add_argument("--runs", type=int, default=10, help="page loads to time")
    ap.add_argument("--readings", type=int, default=30, help="live readings to time")
    ap.add_argument("--alerts", type=int, default=8, help="critical alerts to time")
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args()
    from playwright.sync_api import sync_playwright

    api_dir = Path(args.api_dir).resolve()
    api_py = next((p for p in (api_dir / ".venv/bin/python", api_dir / ".venv/Scripts/python.exe") if p.exists()),
                  Path(sys.executable))
    tmp = Path(tempfile.mkdtemp(prefix="ht_dash_e2e_"))
    api_port, dash_port = free_port(), free_port()
    api_url, dash_url = f"http://127.0.0.1:{api_port}", f"http://127.0.0.1:{dash_port}"
    env = {**os.environ, "HT_DATABASE_URL": f"sqlite:///{tmp / 'e2e.db'}", "HT_LOG_LEVEL": "WARNING",
           "HT_JWT_SECRET": "e2e-" + "x" * 40, "HT_OUTBOX_DIR": str(tmp / "outbox"),
           "HT_CORS_ORIGINS": dash_url, "HT_DASHBOARD_URL": dash_url, "HT_LOGIN_RATE_LIMIT": "1000"}
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "screens").mkdir(exist_ok=True)
    print(f"api project: {api_dir}\nworking copy: {tmp}")
    subprocess.run([str(api_py), "-m", "alembic", "upgrade", "head"], cwd=api_dir, env=env, check=True,
                   capture_output=True)
    subprocess.run([str(api_py), "-m", "scripts.seed"], cwd=api_dir, env=env, check=True, capture_output=True)
    procs = [subprocess.Popen([str(api_py), "-m", "uvicorn", "app.main:app", "--port", str(api_port),
                               "--log-level", "warning"], cwd=api_dir, env=env, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL),
             subprocess.Popen([sys.executable, "-m", "dashboard", "--port", str(dash_port), "--api", api_url],
                              cwd=ROOT, env={**os.environ, "HT_DASH_SECRET": "e2e"}, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL)]
    res: dict = {"environment": {"date": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                 "os": platform.platform(), "machine": platform.machine(),
                                 "cpu_count": os.cpu_count(), "python": platform.python_version()},
                 "checks": []}
    api = Api(api_url)

    def check(name: str, ok: bool, detail: str) -> None:
        res["checks"].append({"check": name, "result": "PASS" if ok else "FAIL", "detail": detail})
        print(f"  {'PASS' if ok else 'FAIL'}  {name}: {detail}")

    try:
        wait_http(f"{api_url}/api/v1/health")
        wait_http(dash_url)
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=not args.headed)
            res["environment"]["browser"] = f"chromium {browser.version}"
            ctx = browser.new_context(viewport={"width": 1500, "height": 1000})
            page = ctx.new_page()
            page.goto(dash_url)
            page.fill("#login-password", PASSWORD)
            page.click("#login-submit")
            page.wait_for_selector(".patient-card", timeout=20000)
            page.close()

            # ---------------------------------------------------------------- 1 load time
            print("load time")
            loads = []
            for i in range(args.runs):
                p = ctx.new_page()
                p.goto(dash_url)
                p.wait_for_selector(".patient-card", timeout=20000)
                t_list = p.evaluate("performance.now()")
                p.wait_for_function(CHARTS_READY, timeout=20000)
                t_chart = p.evaluate("performance.now()")
                p.wait_for_function("document.querySelector('#conn-pill').innerText.includes('Live')", timeout=20000)
                t_live = p.evaluate("performance.now()")
                nav = p.evaluate("(() => { const n = performance.getEntriesByType('navigation')[0];"
                                 " const r = performance.getEntriesByType('resource');"
                                 " return {dcl: n.domContentLoadedEventEnd,"
                                 " bytes: n.transferSize + r.reduce((a, x) => a + (x.transferSize || 0), 0)}; })()")
                loads.append({"run": i + 1, "dom_content_loaded_ms": round(nav["dcl"], 1),
                              "worklist_ms": round(t_list, 1), "charts_ms": round(t_chart, 1),
                              "live_ms": round(t_live, 1), "transferred_kb": round(nav["bytes"] / 1024, 1)})
                if i < args.runs - 1:
                    p.close()
                else:
                    page = p
            res["load"] = {"runs": loads, "worklist": stats([x["worklist_ms"] for x in loads]),
                           "charts": stats([x["charts_ms"] for x in loads]),
                           "live": stats([x["live_ms"] for x in loads]), "target_ms": 3000}
            print(f"  charts drawn p95 {res['load']['charts']['p95_ms']} ms")

            # select thomas and keep the page open for the live tests
            page.click(f'button[data-patient="{THOMAS}"]')
            page.wait_for_function("document.querySelector('.pname-lg') && "
                                   "document.querySelector('.pname-lg').innerText.includes('Thomas')")
            page.click("text=1 h")
            page.wait_for_timeout(1200)

            # ---------------------------------------------------------------- 2 live reading latency
            print("live readings")
            recv, applied = [], []
            values = []
            for i in range(args.readings):
                hr = 104 + i % 8
                t_ms = time.time() * 1000
                [vid] = api.post_hr([hr])
                page.wait_for_function(f"window.__htRT.some(e => e.type === 'applied' && e.id === {vid})",
                                       timeout=10000)
                e = page.evaluate(f"window.__htRT.find(e => e.type === 'applied' && e.id === {vid})")
                recv.append(e["received_at"] - t_ms)
                applied.append(e["applied_at"] - t_ms)
                values.append(hr)
                page.wait_for_timeout(350)
            res["live_reading"] = {"to_browser": stats(recv), "on_chart": stats(applied), "target_ms": 5000}
            last_y = page.evaluate("(() => { const d = document.querySelector('#hr-graph .js-plotly-plot').data[0].y;"
                                   " return d.filter(v => v !== null).slice(-3); })()")
            check("Live readings appear on the chart with the posted values", last_y == values[-3:],
                  f"last three plotted {last_y}, posted {values[-3:]}")
            notes = page.evaluate("(document.querySelector('#hr-graph .js-plotly-plot').layout.annotations || [])"
                                  ".map(a => a.text)")
            check("Live readings clear the empty-chart label on a chart that started empty",
                  "No readings in this time range" not in notes, f"chart labels now {notes}")
            print(f"  reading on chart p95 {res['live_reading']['on_chart']['p95_ms']} ms")

            # ---------------------------------------------------------------- 3 alert to screen
            print("critical alerts")
            a_list, a_card, a_toast = [], [], []
            for i in range(args.alerts):
                api.resolve_open_thomas()
                page.wait_for_function("!document.querySelector('.alert-item.sev-critical') && "
                                       "!document.querySelector('.patient-card').classList.contains('sev-critical')",
                                       timeout=15000)
                page.evaluate(OBSERVER)
                t_ms = time.time() * 1000
                api.post_hr([134 + i % 3, 137 + i % 3])
                page.wait_for_function("window.__seen.alert && window.__seen.toast && window.__seen.worklist",
                                       timeout=15000)
                seen = page.evaluate("window.__seen")
                a_list.append(seen["alert"] - t_ms)
                a_card.append(seen["worklist"] - t_ms)
                a_toast.append(seen["toast"] - t_ms)
            res["alert_to_screen"] = {"alert_panel": stats(a_list), "worklist_resorted": stats(a_card),
                                      "toast": stats(a_toast), "target_ms": 5000}
            page.wait_for_timeout(600)
            page.screenshot(path=str(REPORTS / "screens" / "critical_alert.png"), full_page=True)
            print(f"  alert on screen p95 {res['alert_to_screen']['alert_panel']['p95_ms']} ms")

            # ---------------------------------------------------------------- 4 data accuracy
            print("data accuracy")
            m = api.h("marcus.lee@healthtrack.example")
            wl = api.c.get("/monitoring/worklist", headers=m).json()
            cards = page.evaluate("[...document.querySelectorAll('.patient-card')].map(c => ({id: c.dataset.patient,"
                                  " name: c.querySelector('.pname').innerText,"
                                  " vitals: [...c.querySelectorAll('.vital b')].map(b => b.innerText)}))")
            want = [{"id": r["patient_id"], "name": f"{r['last_name']}, {r['first_name']}",
                     "vitals": [str(r["latest"][k]["value"]) if r["latest"][k] else "--"
                                for k in ("heart_rate", "blood_pressure", "spo2")]} for r in wl]
            check("Worklist order, names, and latest values match the API", cards == want,
                  f"{len(cards)} cards compared field by field")
            latest = api.c.get(f"/patients/{THOMAS}/vitals/latest", headers=m).json()
            g_hr = page.evaluate("document.querySelector('#g-hr .js-plotly-plot').data[0].value")
            check("Heart rate gauge matches the latest valid reading", g_hr == latest["heart_rate"]["heart_rate"],
                  f"gauge {g_hr}, api {latest['heart_rate']['heart_rate']}")
            api_alerts = api.c.get("/alerts", headers=m, params={"page_size": 200}).json()["meta"]["total_items"]
            panel = page.evaluate("document.querySelectorAll('.alert-item').length")
            check("Alert panel shows every active alert in scope", panel == api_alerts,
                  f"panel {panel}, api {api_alerts}")
            label = page.evaluate("document.querySelector('.alert-item.sev-critical .badge').innerText")
            label = " ".join(label.split())
            check("Critical alerts carry a text label, not only color", "CRITICAL" in label.upper(), f"badge '{label}'")
            pt = page.evaluate("(() => { const t = document.querySelector('#hr-graph .js-plotly-plot').data[0];"
                               " const i = t.y.findLastIndex(v => v !== null && v > 128);"
                               " return {color: t.marker.color[i], symbol: t.marker.symbol[i], text: t.text[i]}; })()")
            check("Readings above the ceiling are drawn red, as triangles, labeled Critical",
                  pt["color"] == CRITICAL and pt["symbol"] == "triangle-up" and "Critical" in pt["text"], str(pt))
            th = {t["rule_code"]: t["threshold"] for t in
                  api.c.get(f"/patients/{THOMAS}/alert-thresholds", headers=m).json()}
            lines = page.evaluate("document.querySelector('#hr-graph .js-plotly-plot').layout.shapes.map(s => s.y0)")
            check("Chart threshold lines come from the patient's effective thresholds",
                  th["HR_ABOVE_CEILING"] in lines and th["RESTING_HR_HIGH"] in lines,
                  f"ceiling {th['HR_ABOVE_CEILING']}, resting {th['RESTING_HR_HIGH']}, drawn {sorted(set(lines))}")
            page.click("text=24 h")
            page.wait_for_function("document.querySelector('#loaded-at').innerText.includes('readings loaded')")
            page.wait_for_timeout(1500)
            start = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
            n_api = api.c.get(f"/patients/{THOMAS}/vitals", headers=m,
                              params={"start": start, "metric": "heart_rate", "page_size": 1}).json()["meta"]
            n_chart = page.evaluate("document.querySelector('#hr-graph .js-plotly-plot').data[0].y"
                                    ".filter(v => v !== null).length")
            check("24-hour heart rate chart plots every reading the API returns", n_chart == n_api["total_items"],
                  f"chart {n_chart}, api {n_api['total_items']}")

            # ---------------------------------------------------------------- 5 range switch, acknowledge, reconnect
            t = time.perf_counter()
            page.click("text=7 days")
            page.wait_for_function("document.querySelector('#loaded-at').innerText.includes('readings loaded') && "
                                   "document.querySelector('.range-label:has(input:checked)').innerText.includes('7')")
            page.wait_for_function(CHARTS_READY)
            res["range_switch_7d_ms"] = round((time.perf_counter() - t) * 1000, 1)
            page.click("text=1 h")
            page.wait_for_timeout(800)

            t = time.perf_counter()
            page.click(".alert-item.sev-critical button:has-text('Acknowledge')")
            page.wait_for_function("[...document.querySelectorAll('.alert-item.sev-critical .status')]"
                                   ".some(s => s.innerText.toUpperCase().includes('ACKNOWLEDGED'))", timeout=10000)
            res["acknowledge_click_to_update_ms"] = round((time.perf_counter() - t) * 1000, 1)
            acked = api.c.get("/alerts", headers=m, params={"patient_id": THOMAS, "status": "acknowledged"}).json()
            check("Acknowledging in the dashboard records the clinician in the API",
                  bool(acked["items"]) and acked["items"][0]["acknowledged_by"] == MARCUS,
                  f"acknowledged_by {acked['items'][0]['acknowledged_by'] if acked['items'] else None}")

            page.evaluate("window.__htWS.close()")
            t = time.perf_counter()
            page.wait_for_function("document.querySelector('#conn-pill').innerText.includes('Reconnecting')",
                                   timeout=5000)
            page.wait_for_function("document.querySelector('#conn-pill').innerText.includes('Live')", timeout=15000)
            res["reconnect_ms"] = round((time.perf_counter() - t) * 1000, 1)
            [vid] = api.post_hr([109])
            page.wait_for_function(f"window.__htRT.some(e => e.type === 'applied' && e.id === {vid})", timeout=10000)
            check("After a dropped connection the stream reconnects and live updates resume", True,
                  f"live again after {res['reconnect_ms']:.0f} ms; next reading arrived")
            page.screenshot(path=str(REPORTS / "screens" / "after_acknowledge.png"), full_page=True)
            browser.close()
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()

    (REPORTS / "dashboard_e2e.json").write_text(json.dumps(res, indent=2))
    (REPORTS / "dashboard_test_results.md").write_text(render(res))
    print(f"wrote {REPORTS / 'dashboard_test_results.md'}")


def unit_summary() -> list[str]:
    junit = REPORTS / "junit-unit.xml"
    if not junit.exists():
        return ["Unit tests were not run in this pass (run scripts/run_reports.sh)."]
    import xml.etree.ElementTree as ET
    root = ET.parse(junit).getroot()
    s = root if root.tag == "testsuite" else root.find("testsuite")
    total, fail = int(s.get("tests")), int(s.get("failures")) + int(s.get("errors"))
    out = [f"{total} unit tests, {total - fail - int(s.get('skipped'))} passed, {fail} failed "
           f"({float(s.get('time')):.2f} s): figure builders, reading classification, gauges, components, stream "
           "state updates, and the dashboard server routes."]
    cov = REPORTS / "coverage.json"
    if cov.exists():
        out.append(f"Line coverage of `dashboard/`: {json.loads(cov.read_text())['totals']['percent_covered']:.1f}%.")
    return out


def render(r: dict) -> str:
    e = r["environment"]
    head = "| Measurement | n | p50 (ms) | p95 (ms) | max (ms) |\n|---|---|---|---|---|"

    def row(name: str, s: dict) -> str:
        return f"| {name} | {s['n']} | {s['p50_ms']} | {s['p95_ms']} | {s['max_ms']} |"

    ld, lr, al = r["load"], r["live_reading"], r["alert_to_screen"]
    passed = sum(1 for c in r["checks"] if c["result"] == "PASS")
    verdict = lambda v, t: "met" if v <= t else "not met"  # noqa: E731
    out = [
        "# HealthTrack dashboard: test results", "",
        f"Run {e['date']} on {e['os']} ({e['machine']}, {e['cpu_count']} cores), Python {e['python']}, "
        f"{e.get('browser', 'chromium')} headless. The API and dashboard ran locally on this machine with the seed "
        "data; times are from this machine's clock.", "",
        "## Unit tests", "", *unit_summary(), "",
        "## 1. Load time (requirement NFR-09: initial view within 3 s)", "",
        "Measured from navigation start in the browser, signed in, across "
        f"{len(ld['runs'])} page loads.", "", head,
        row("Worklist rendered", ld["worklist"]), row("Charts drawn", ld["charts"]),
        row("Live stream connected", ld["live"]), "",
        f"Charts drawn p95 {ld['charts']['p95_ms']} ms: target {verdict(ld['charts']['p95_ms'], 3000)}. "
        f"Each load transferred about {statistics.median(x['transferred_kb'] for x in ld['runs']):.0f} KB, because "
        "the Dash and Plotly bundles come from the browser cache after the sign-in page.", "",
        "## 2. Real-time updates", "",
        "A reading posted to the API (as the patient's device) until it reaches the browser and is drawn on the "
        "open chart.", "", head, row("Reading received over the WebSocket", lr["to_browser"]),
        row("Reading appended to the chart", lr["on_chart"]), "",
        "A breaching reading pair posted until each part of the screen shows the new critical alert "
        "(requirement NFR-07: within 5 s).", "", head,
        row("Alert in the alert panel", al["alert_panel"]), row("Worklist re-sorted, patient first",
                                                                 al["worklist_resorted"]),
        row("Notification toast shown", al["toast"]), "",
        f"Alert panel p95 {al['alert_panel']['p95_ms']} ms: target {verdict(al['alert_panel']['p95_ms'], 5000)}.",
        "", "## 3. Interaction timing", "",
        f"- Switch the charts to 7 days (reload and redraw): {r['range_switch_7d_ms']} ms",
        f"- Acknowledge an alert, click to updated status: {r['acknowledge_click_to_update_ms']} ms",
        f"- Dropped WebSocket to live again (automatic reconnect): {r['reconnect_ms']} ms", "",
        f"## 4. Data accuracy and behavior checks ({passed} of {len(r['checks'])} passed)", "",
        "| Check | Result | Detail |", "|---|---|---|",
        *[f"| {c['check']} | {c['result']} | {c['detail']} |" for c in r["checks"]], "",
        "## 5. Page loads", "", "| Run | DOM ready (ms) | Worklist (ms) | Charts (ms) | Live (ms) | Transferred (KB) |",
        "|---|---|---|---|---|---|",
        *[f"| {x['run']} | {x['dom_content_loaded_ms']} | {x['worklist_ms']} | {x['charts_ms']} | {x['live_ms']} | "
          f"{x['transferred_kb']} |" for x in ld["runs"]], ""]
    return "\n".join(out)


if __name__ == "__main__":
    main()
