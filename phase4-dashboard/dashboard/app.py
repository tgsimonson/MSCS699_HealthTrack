"""healthtrack real-time monitoring dashboard (dash)

data flow
  initial view   rest calls through the api client: worklist, active alerts, then the selected patient's bundle
  live updates   assets/realtime.js holds a websocket to the api stream and hands events to the page in batches
                 every 250 ms (dash_clientside.set_props on the rt-events store); then
                   - a clientside callback appends new readings to the open charts with extendData (no server trip,
                     no full redraw, capped at 3000 points per chart)
                   - one server callback applies the same batch to the worklist and alert stores, patches only the
                     changed fields of the gauges (dash Patch), and raises toasts for notifications
  fallback       if the websocket drops, a 15-second poll refreshes the stores until the stream reconnects
"""
from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime, timezone

from dash import ALL, Dash, Input, Output, Patch, State, ctx, dcc, html, no_update, set_props
from dash.exceptions import PreventUpdate
from flask import jsonify, redirect, session

from dashboard import components as ui
from dashboard import figures as fx
from dashboard import logic
from dashboard.api import ApiClient, ApiError, NotSignedIn

log = logging.getLogger("dashboard")
RANGES = [{"label": "1 h", "value": 1}, {"label": "6 h", "value": 6}, {"label": "24 h", "value": 24},
          {"label": "7 days", "value": 168}]
GRAPH_CONFIG = {"displayModeBar": False, "responsive": True}
ACTIVE = ("open", "acknowledged", "escalated")


def shell(user: dict) -> html.Div:
    graph = lambda gid, cls="": dcc.Graph(id=gid, config=GRAPH_CONFIG, className=cls,  # noqa: E731
                                          figure={"layout": {"height": 170 if gid.startswith("g-") else 230}})
    return html.Div(className="shell", children=[
        ui.header(user),
        html.Div(className="grid", children=[
            html.Aside(className="col worklist-col", **{"aria-label": "Patient worklist"}, children=[
                html.Div(className="section-head", children=[html.H2("Worklist"), html.Span(id="worklist-count",
                                                                                           className="muted")]),
                html.Div(id="worklist", className="worklist"),
            ]),
            html.Main(className="col main-col", children=[
                html.Div(id="patient-header"),
                html.Div(className="range-row", children=[
                    dcc.RadioItems(id="range", options=RANGES, value=6, inline=True, className="range",
                                   inputClassName="range-input", labelClassName="range-label"),
                    html.Span(id="loaded-at", className="muted small")]),
                html.Div(className="gauges", children=[graph("g-hr"), graph("g-spo2"), graph("g-bp")]),
                html.Div(className="panel", children=graph("hr-graph")),
                html.Div(className="two", children=[html.Div(className="panel", children=graph("bp-graph")),
                                                    html.Div(className="panel", children=graph("spo2-graph"))]),
                html.Div(className="panel", children=graph("activity-graph")),
            ]),
            html.Aside(className="col alerts-col", **{"aria-label": "Alerts"}, children=[
                html.Div(className="section-head", children=[html.H2("Alerts"), html.Span(id="alert-count",
                                                                                         className="muted")]),
                html.Div(id="action-msg", className="small", role="status"),
                html.Div(id="alert-list"),
            ]),
        ]),
        html.Div(id="toasts", className="toasts", **{"aria-live": "assertive"}),
        dcc.Store(id="boot", data=1), dcc.Store(id="worklist-store"), dcc.Store(id="alerts-store"),
        dcc.Store(id="selected", storage_type="session"), dcc.Store(id="bundle-store"), dcc.Store(id="limits-store"),
        dcc.Store(id="rt-events"), dcc.Store(id="conn-status"), dcc.Store(id="toast-store", data=[]),
        dcc.Interval(id="poll", interval=15_000, disabled=True), dcc.Interval(id="clock", interval=30_000),
    ])


def create_app(api_url: str | None = None, secret: str | None = None) -> Dash:
    api = ApiClient(api_url or os.getenv("HT_API_URL", "http://localhost:8000"))
    app = Dash(__name__, title="HealthTrack Monitor", update_title=None, suppress_callback_exceptions=True)
    server = app.server
    server.secret_key = secret or os.getenv("HT_DASH_SECRET") or secrets.token_urlsafe(32)
    server.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                         SESSION_COOKIE_SECURE=os.getenv("HT_ENV") == "production")
    app.server.api = api  # type: ignore[attr-defined]

    def serve_layout() -> html.Div:
        page = shell(session["user"]) if api.signed_in() else ui.login_layout()
        return html.Div([dcc.Location(id="url", refresh=True), page])

    app.layout = serve_layout
    app.validation_layout = html.Div([dcc.Location(id="url"), ui.login_layout(), shell(
        {"first_name": "A", "last_name": "B", "role": "clinician"})])

    # ---------------------------------------------------------------- flask routes
    @server.get("/rt/ticket")
    def rt_ticket():  # noqa: ANN202
        try:
            return jsonify(api.stream_ticket())
        except NotSignedIn:
            return jsonify({"detail": "not signed in"}), 401
        except ApiError as e:
            return jsonify({"detail": e.detail}), e.status

    @server.get("/logout")
    def logout():  # noqa: ANN202
        api.logout()
        return redirect("/")

    @server.after_request
    def headers(resp):  # noqa: ANN001, ANN202
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        if resp.mimetype == "application/json":
            resp.headers["Cache-Control"] = "no-store"          # patient data is never cached
        return resp

    def signed_out() -> None:
        set_props("url", {"href": "/logout"})
        raise PreventUpdate

    # ---------------------------------------------------------------- sign in
    @app.callback(Output("url", "href"), Output("login-error", "children"),
                  Input("login-submit", "n_clicks"), Input("login-password", "n_submit"),
                  State("login-email", "value"), State("login-password", "value"), prevent_initial_call=True)
    def sign_in(_c, _s, email, password):  # noqa: ANN001, ANN202
        if not email or not password:
            return no_update, "Enter your email and password."
        try:
            api.login(email.strip(), password)
        except ApiError as e:
            msg = {401: "Email or password is incorrect.", 423: "Account locked after repeated failures; try later.",
                   429: "Too many attempts; wait a minute."}.get(e.status, e.detail)
            return no_update, msg
        return "/", ""

    # ---------------------------------------------------------------- initial load and selection
    @app.callback(Output("worklist-store", "data"), Output("alerts-store", "data"), Output("selected", "data"),
                  Input("boot", "data"), State("url", "search"), State("selected", "data"))
    def boot(_b, search, selected):  # noqa: ANN001, ANN202
        try:
            rows, alerts = api.worklist(), api.active_alerts()
        except NotSignedIn:
            signed_out()
        linked = None
        if search and "alert=" in search:              # deep link from an email or sms notification
            alert_id = search.split("alert=", 1)[1].split("&")[0]
            try:
                linked = api.alert_detail(alert_id)["patient_id"]
            except ApiError:
                pass
        return rows, {a["alert_id"]: a for a in alerts}, logic.initial_selection(rows, selected, linked)

    @app.callback(Output("selected", "data", allow_duplicate=True),
                  Input({"type": "patient-card", "id": ALL}, "n_clicks"),
                  Input({"type": "toast-open", "id": ALL}, "n_clicks"), prevent_initial_call=True)
    def select(_cards, _toasts):  # noqa: ANN001, ANN202
        if not ctx.triggered or not ctx.triggered[0]["value"]:
            raise PreventUpdate
        return ctx.triggered_id["id"]

    @app.callback(Output("bundle-store", "data"), Output("limits-store", "data"),
                  Input("selected", "data"), Input("range", "value"))
    def load_patient(pid, hours):  # noqa: ANN001, ANN202
        if not pid:
            return None, None
        try:
            b = api.patient_bundle(pid, hours or 6)
        except NotSignedIn:
            signed_out()
        except ApiError as e:
            if e.status == 404:
                return None, None
            raise
        return b, {**fx.build_limits(b["thresholds"], b["prescription"]), "patient_id": pid}

    # ---------------------------------------------------------------- patient view
    @app.callback(Output("patient-header", "children"), Output("hr-graph", "figure"), Output("bp-graph", "figure"),
                  Output("spo2-graph", "figure"), Output("activity-graph", "figure"), Output("g-hr", "figure"),
                  Output("g-spo2", "figure"), Output("g-bp", "figure"), Output("loaded-at", "children"),
                  Input("bundle-store", "data"), State("limits-store", "data"))
    def render_patient(b, limits):  # noqa: ANN001, ANN202
        if not b:
            empty = fx.hr_figure([], {})
            return (ui.patient_header(None), empty, fx.bp_figure([], {}), fx.spo2_figure([], {}),
                    fx.activity_figure([], None), fx.gauge("hr", None, {}), fx.gauge("spo2", None, {}),
                    fx.gauge("bp", None, {}), "")
        pid, r = b["patient"]["patient_id"], b["readings"]
        lv = b.get("latest") or {}
        latest = {"heart_rate": lv.get("heart_rate"), "spo2": lv.get("spo2"), "systolic_bp": lv.get("blood_pressure")}
        return (ui.patient_header(b), fx.hr_figure(r, limits, f"hr-{pid}"), fx.bp_figure(r, limits, f"bp-{pid}"),
                fx.spo2_figure(r, limits, f"spo2-{pid}"), fx.activity_figure(b["activity"], b["prescription"]),
                fx.gauge("hr", latest["heart_rate"], limits), fx.gauge("spo2", latest["spo2"], limits),
                fx.gauge("bp", latest["systolic_bp"], limits),
                f"{len(r):,} readings loaded at {datetime.now().strftime('%H:%M:%S')}; live updates append")

    # ---------------------------------------------------------------- live events (server side)
    @app.callback(Output("worklist-store", "data", allow_duplicate=True),
                  Output("alerts-store", "data", allow_duplicate=True),
                  Output("g-hr", "figure", allow_duplicate=True), Output("g-spo2", "figure", allow_duplicate=True),
                  Output("g-bp", "figure", allow_duplicate=True), Output("toast-store", "data", allow_duplicate=True),
                  Input("rt-events", "data"), State("worklist-store", "data"), State("alerts-store", "data"),
                  State("selected", "data"), State("limits-store", "data"), State("toast-store", "data"),
                  prevent_initial_call=True)
    def apply_events(batch, rows, alerts, selected, limits, toasts):  # noqa: ANN001, ANN202, PLR0912
        events = (batch or {}).get("events") or []
        if not events:
            raise PreventUpdate
        st = logic.apply_events(events, rows or [], alerts or {}, selected, toasts or [])
        rows = st["rows"]
        if st["alerts_changed"]:                 # priorities and top alerts are recalculated by the api
            try:
                rows = api.worklist()
            except NotSignedIn:
                signed_out()
            st["rows_changed"] = True
        gauges = st["gauges"]
        patches = []
        for kind, key in (("hr", "heart_rate"), ("spo2", "spo2"), ("bp", "systolic_bp")):
            v = gauges[key]
            if v is None or not limits:
                patches.append(no_update)
                continue
            fig, p = fx.gauge(kind, v, limits), Patch()       # send only the changed parts of the gauge
            p["data"][0]["value"] = fig.data[0].value
            p["data"][0]["number"] = fig.data[0].number.to_plotly_json()
            p["data"][0]["title"] = fig.data[0].title.to_plotly_json()
            patches.append(p)
        return (rows if st["rows_changed"] else no_update, st["alerts"] if st["alerts_changed"] else no_update,
                *patches, st["toasts"] if st["toasts_changed"] else no_update)

    # live readings onto the open charts happen in the browser (assets/clientside.js)
    app.clientside_callback(
        "function(batch, selected, limits) { return window.dash_clientside.ht.extend(batch, selected, limits); }",
        Output("hr-graph", "extendData"), Output("bp-graph", "extendData"), Output("spo2-graph", "extendData"),
        Input("rt-events", "data"), State("selected", "data"), State("limits-store", "data"),
        prevent_initial_call=True)

    # ---------------------------------------------------------------- worklist and alerts
    @app.callback(Output("worklist", "children"), Output("worklist-count", "children"),
                  Input("worklist-store", "data"), Input("selected", "data"), Input("clock", "n_intervals"))
    def render_worklist(rows, selected, _t):  # noqa: ANN001, ANN202
        rows = rows or []
        now = datetime.now(timezone.utc)
        if not rows:
            return html.Div("No patients on your care team.", className="muted empty"), ""
        return [ui.worklist_card(r, r["patient_id"] == selected, now) for r in rows], f"{len(rows)} patients"

    @app.callback(Output("alert-list", "children"), Output("alert-count", "children"),
                  Input("alerts-store", "data"), Input("selected", "data"), Input("clock", "n_intervals"),
                  State("worklist-store", "data"))
    def render_alerts(alerts, selected, _t, rows):  # noqa: ANN001, ANN202
        alerts = list((alerts or {}).values())
        names = {r["patient_id"]: f"{r['first_name']} {r['last_name']}" for r in rows or []}
        mine, others = logic.order_alerts(alerts, selected)
        out = [html.H3(f"This patient ({len(mine)})", className="subhead")]
        out += [ui.alert_item(a, names.get(a["patient_id"], ""), False) for a in mine] or \
            [html.Div("No active alerts for this patient.", className="muted small pad")]
        out += [html.H3(f"Other patients ({len(others)})", className="subhead")]
        out += [ui.alert_item(a, names.get(a["patient_id"], "Patient"), True) for a in others] or \
            [html.Div("None.", className="muted small pad")]
        crit = sum(1 for a in alerts if a["severity"] == "critical")
        return out, f"{len(alerts)} active" + (f", {crit} critical" if crit else "")

    @app.callback(Output("alerts-store", "data", allow_duplicate=True), Output("action-msg", "children"),
                  Input({"type": "ack", "id": ALL}, "n_clicks"), Input({"type": "resolve", "id": ALL}, "n_clicks"),
                  State({"type": "note", "id": ALL}, "value"), State({"type": "note", "id": ALL}, "id"),
                  State("alerts-store", "data"), prevent_initial_call=True)
    def act(_a, _r, notes, note_ids, alerts):  # noqa: ANN001, ANN202
        if not ctx.triggered or not ctx.triggered[0]["value"]:
            raise PreventUpdate
        kind, alert_id = ctx.triggered_id["type"], ctx.triggered_id["id"]
        alerts = dict(alerts or {})
        try:
            if kind == "ack":
                a = api.acknowledge(alert_id)
                msg = "Acknowledged. Escalation stopped."
            else:
                note = next((v for v, i in zip(notes, note_ids) if i["id"] == alert_id), None)
                if not note or len(note.strip()) < 3:
                    return no_update, html.Span("Type a resolution note first.", className="error")
                a = api.resolve(alert_id, note.strip())
                msg = "Resolved."
        except NotSignedIn:
            signed_out()
        except ApiError as e:
            return no_update, html.Span(e.detail, className="error")
        if a["status"] in ACTIVE:
            alerts[alert_id] = a
        else:
            alerts.pop(alert_id, None)
        return alerts, msg

    # ---------------------------------------------------------------- connection state, polling fallback, toasts
    @app.callback(Output("conn-pill", "children"), Output("conn-pill", "className"), Output("poll", "disabled"),
                  Input("conn-status", "data"))
    def connection(status):  # noqa: ANN001, ANN202
        state = (status or {}).get("state", "connecting")
        if state == "live":
            return "● Live", "pill pill-live", True
        if state == "signed-out":
            signed_out()
        return "○ Reconnecting (polling every 15 s)", "pill pill-wait", False

    @app.callback(Output("worklist-store", "data", allow_duplicate=True),
                  Output("alerts-store", "data", allow_duplicate=True),
                  Output("bundle-store", "data", allow_duplicate=True),
                  Input("poll", "n_intervals"), State("selected", "data"), State("range", "value"),
                  prevent_initial_call=True)
    def poll(_n, pid, hours):  # noqa: ANN001, ANN202
        try:
            return (api.worklist(), {a["alert_id"]: a for a in api.active_alerts()},
                    api.patient_bundle(pid, hours or 6) if pid else no_update)
        except NotSignedIn:
            signed_out()

    @app.callback(Output("toasts", "children"), Input("toast-store", "data"), Input("clock", "n_intervals"))
    def render_toasts(toasts, _t):  # noqa: ANN001, ANN202
        return [ui.toast(t) for t in logic.fresh_toasts(toasts or [])]

    return app
