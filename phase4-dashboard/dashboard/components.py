"""layout pieces: login, header, worklist cards, patient header, alert items, toasts"""
from __future__ import annotations

from datetime import date, datetime, timezone

from dash import dcc, html

from dashboard.theme import PRIORITY_NAME, SEVERITY

EVENT_LABEL = {"myocardial_infarction": "Heart attack (MI)", "pci": "Stent (PCI)", "cabg": "Bypass surgery (CABG)",
               "valve_surgery": "Valve surgery", "stable_angina": "Stable angina",
               "heart_failure_reduced_ef": "Heart failure (HFrEF)", "heart_transplant": "Heart transplant"}
STATUS_LABEL = {"open": "Open", "acknowledged": "Acknowledged", "escalated": "Escalated", "resolved": "Resolved",
                "suppressed": "Suppressed"}


def badge(severity: str, compact: bool = False) -> html.Span:
    color, tint, glyph, label = SEVERITY[severity]
    return html.Span([html.Span(glyph, className="glyph", **{"aria-hidden": "true"}), "" if compact else label],
                     className=f"badge badge-{severity}", style={"color": color, "backgroundColor": tint},
                     title=label, **{"aria-label": f"{label} priority"})


def ago(ts: str | None, now: datetime | None = None) -> str:
    if not ts:
        return "no data"
    now = now or datetime.now(timezone.utc)
    secs = max(0, (now - datetime.fromisoformat(ts.replace("Z", "+00:00"))).total_seconds())
    if secs < 60:
        return "just now"
    if secs < 3600:
        return f"{int(secs // 60)} min ago"
    if secs < 86400:
        return f"{int(secs // 3600)} h ago"
    return f"{int(secs // 86400)} d ago"


# ---------------------------------------------------------------- login
def login_layout(error: str | None = None) -> html.Div:
    return html.Main(className="login-wrap", children=html.Div(className="login-card", children=[
        html.Div("HealthTrack", className="brand brand-lg"),
        html.P("Cardiac rehab remote monitoring", className="muted"),
        html.Label("Email", htmlFor="login-email"),
        dcc.Input(id="login-email", type="email", value="marcus.lee@healthtrack.example", autoComplete="username",
                  className="input", debounce=False),
        html.Label("Password", htmlFor="login-password"),
        dcc.Input(id="login-password", type="password", value="", autoComplete="current-password", className="input",
                  n_submit=0),
        html.Button("Sign in", id="login-submit", className="btn btn-primary", n_clicks=0),
        html.Div(error or "", id="login-error", className="error", role="alert"),
        html.P(["Synthetic demo data only. Clinician demo accounts: marcus.lee@ or dana.whitfield@",
                "healthtrack.example (password HealthTrack-Demo-2026!)."], className="muted small"),
    ]))


# ---------------------------------------------------------------- shell
def header(user: dict) -> html.Header:
    return html.Header(className="topbar", children=[
        html.Div([html.Span("HealthTrack", className="brand"), html.Span("Rehab monitoring", className="brand-sub")]),
        html.Div(className="topbar-right", children=[
            html.Span(id="conn-pill", className="pill pill-wait", children="Connecting", role="status",
                      **{"aria-live": "polite"}),
            html.Span(f"{user['first_name']} {user['last_name']}, {user.get('credentials') or user['role']}",
                      className="who"),
            html.A("Sign out", href="/logout", className="link"),
        ]),
    ])


def worklist_card(row: dict, selected: bool, now: datetime | None = None) -> html.Button:
    sev = PRIORITY_NAME[row["priority"]]
    latest = row["latest"]

    def val(key: str, unit: str) -> html.Span:
        v = latest.get(key)
        return html.Span([html.B(str(v["value"]) if v else "--"), f" {unit}"], className="vital")

    top = row.get("top_alert")
    counts = row["active_alerts"]
    n_active = sum(counts.values())
    return html.Button(
        id={"type": "patient-card", "id": row["patient_id"]}, n_clicks=0,
        className=f"card patient-card sev-{sev}{' selected' if selected else ''}",
        **{"data-patient": row["patient_id"], "aria-pressed": "true" if selected else "false"},
        children=[
            html.Div(className="card-row", children=[
                html.Span(f"{row['last_name']}, {row['first_name']}", className="pname"), badge(sev)]),
            html.Div(f"{row['mrn']}  |  {row['clinical_risk_category'].title()} risk"
                     f"{'  |  paused' if row['program_status'] == 'paused' else ''}", className="muted small"),
            html.Div(className="card-row vitals", children=[val("heart_rate", "bpm"), val("blood_pressure", "mmHg"),
                                                            val("spo2", "%")]),
            html.Div(top["title"] if top else "No active alerts", className="top-alert" if top else "muted small"),
            html.Div(className="card-row muted small", children=[
                html.Span(f"Last reading {ago(row['last_reading_at'], now)}"),
                html.Span(f"{n_active} active" if n_active else "")]),
        ])


def patient_header(bundle: dict | None) -> html.Div:
    if not bundle:
        return html.Div("Select a patient from the worklist.", className="muted empty")
    p, rx = bundle["patient"], bundle["prescription"]
    dob = date.fromisoformat(p["date_of_birth"])
    today = date.today()
    age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    facts = [f"{age} y, {p['sex']}", EVENT_LABEL.get(p["qualifying_event"], p["qualifying_event"]),
             f"{p['clinical_risk_category'].title()} risk", p["program_status"].title()]
    rx_line = (f"Prescription v{rx['version']}: target zone {rx['target_hr_min']}-{rx['target_hr_max']} bpm, ceiling "
               f"{rx['hr_ceiling']} bpm, SpO2 floor {rx['min_spo2']}%, exercise SBP max {rx['max_exercise_sbp']}, "
               f"{rx['sessions_per_week']} sessions/week" if rx else "No exercise prescription on file; program "
                                                                     "defaults apply.")
    return html.Div(className="phead", children=[
        html.Div([html.H1(f"{p['first_name']} {p['last_name']}", className="pname-lg"),
                  html.Span(p["mrn"], className="mrn")]),
        html.Div("  |  ".join(facts), className="muted"),
        html.Div(rx_line, className="rx"),
    ])


def alert_item(a: dict, patient_name: str, show_patient: bool) -> html.Div:
    st = a["status"]
    actions = []
    if st in ("open", "escalated"):
        actions.append(html.Button("Acknowledge", id={"type": "ack", "id": a["alert_id"]}, n_clicks=0,
                                   className="btn btn-small btn-primary"))
    if st in ("open", "escalated", "acknowledged"):
        actions += [dcc.Input(id={"type": "note", "id": a["alert_id"]}, placeholder="Resolution note",
                              className="input input-small", debounce=False),
                    html.Button("Resolve", id={"type": "resolve", "id": a["alert_id"]}, n_clicks=0,
                                className="btn btn-small")]
    esc = f"  |  escalated to level {a['escalation_level']}" if a["escalation_level"] else ""
    reps = f"  |  {a['occurrences']} occurrences" if a["occurrences"] > 1 else ""
    return html.Div(className=f"alert-item sev-{a['severity']} st-{st}", **{"data-alert": a["alert_id"]}, children=[
        html.Div(className="card-row", children=[badge(a["severity"]),
                                                 html.Span(STATUS_LABEL[st], className=f"status status-{st}")]),
        html.Div(([html.B(patient_name), ": "] if show_patient else []) + [a["title"]], className="atitle"),
        html.Div(f"{ago(a['triggered_at'])}  |  {a['rule_name']}{esc}{reps}", className="muted small"),
        html.Div(actions, className="actions") if actions else None,
    ])


def toast(n: dict) -> html.Div:
    d = n["data"]
    return html.Div(className=f"toast sev-{d['severity']}", role="alert", **{"data-alert": d["alert_id"]}, children=[
        badge(d["severity"]),
        html.Div(d["subject"].replace("HealthTrack ", ""), className="toast-title"),
        html.Div(d["title"], className="small"),
        html.Button("Open patient", id={"type": "toast-open", "id": d["patient_id"]}, n_clicks=0,
                    className="btn btn-small btn-primary"),
    ])
