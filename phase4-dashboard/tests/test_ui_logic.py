"""layout components, state updates from stream events, and the flask routes"""
from __future__ import annotations

import json
import threading
import time
from datetime import timedelta

import flask
import httpx
import pytest

from dashboard import components as ui
from dashboard import logic
from dashboard.app import create_app
from tests.conftest import MARIA, NOW, THOMAS, alert, iso, reading


def text_of(component) -> str:  # noqa: ANN001
    """flatten a dash component tree to its visible text"""
    if component is None:
        return ""
    if isinstance(component, (str, int, float)):
        return str(component)
    if isinstance(component, (list, tuple)):
        return " ".join(text_of(c) for c in component)
    return text_of(getattr(component, "children", None))


class TestComponents:
    @pytest.mark.parametrize("sev,label", [("critical", "Critical"), ("high", "High"), ("moderate", "Moderate"),
                                           ("low", "Low"), ("stable", "Stable")])
    def test_badges_carry_text_and_glyph(self, sev, label):
        b = ui.badge(sev)
        assert label in text_of(b) and b.children[0].children and b.title == label    # NFR-14: never color alone

    def test_worklist_card(self, worklist):
        card = ui.worklist_card(worklist[0], True, NOW)
        t = text_of(card)
        assert "Reed, Thomas" in t and "136" in t and "121/73" in t and "Critical" in t and "1 active" in t
        assert card.id == {"type": "patient-card", "id": THOMAS} and "selected" in card.className
        assert "sev-critical" in card.className

    def test_alert_actions_follow_status(self):
        open_ = ui.alert_item(alert("a", THOMAS, "critical"), "Thomas Reed", True)
        acked = ui.alert_item(alert("b", THOMAS, "critical", status="acknowledged"), "Thomas Reed", True)
        ids = lambda c: {x.id["type"] for x in c.children[-1].children}  # noqa: E731
        assert ids(open_) == {"ack", "note", "resolve"} and ids(acked) == {"note", "resolve"}
        assert "Thomas Reed" in text_of(open_)

    @pytest.mark.parametrize("minutes,expected", [(0.2, "just now"), (5, "5 min ago"), (130, "2 h ago"),
                                                  (60 * 50, "2 d ago")])
    def test_ago(self, minutes, expected):
        assert ui.ago(iso(minutes), NOW) == expected

    def test_patient_header(self, rx):
        bundle = {"patient": {"first_name": "Thomas", "last_name": "Reed", "mrn": "HT-100005",
                              "date_of_birth": "1959-01-30", "sex": "male", "qualifying_event": "valve_surgery",
                              "clinical_risk_category": "moderate", "program_status": "active"},
                  "prescription": rx}
        t = text_of(ui.patient_header(bundle))
        assert "Valve surgery" in t and "ceiling 128 bpm" in t and "target zone 95-115" in t
        assert "Select a patient" in text_of(ui.patient_header(None))


class TestStreamState:
    def test_vitals_update_latest_values_and_gauges(self, worklist):
        ev = {"type": "vital", "patient_id": THOMAS,
              "data": reading(0, heart_rate=141, systolic_bp=None, vital_id=9)}
        st = logic.apply_events([ev], worklist, {}, THOMAS, [])
        assert st["rows"][0]["latest"]["heart_rate"]["value"] == 141 and st["rows_changed"]
        assert st["gauges"]["heart_rate"]["heart_rate"] == 141 and st["gauges"]["spo2"] is None
        assert worklist[0]["latest"]["heart_rate"]["value"] == 136                  # input not mutated

    def test_suspect_readings_never_update_the_display(self, worklist):
        ev = {"type": "vital", "patient_id": THOMAS, "data": reading(0, quality="suspect", heart_rate=250)}
        st = logic.apply_events([ev], worklist, {}, THOMAS, [])
        assert not st["rows_changed"] and st["gauges"]["heart_rate"] is None

    def test_alert_events_add_and_remove(self):
        a = alert("a9", MARIA, "high")
        st = logic.apply_events([{"type": "alert", "action": "created", "patient_id": MARIA, "data": a}], [], {},
                                THOMAS, [])
        assert st["alerts"] == {"a9": a} and st["alerts_changed"]
        done = {**a, "status": "resolved"}
        st2 = logic.apply_events([{"type": "alert", "action": "resolved", "patient_id": MARIA, "data": done}], [],
                                 st["alerts"], THOMAS, [])
        assert st2["alerts"] == {}

    def test_notifications_become_toasts(self):
        note = lambda aid, lvl=0: {"type": "notification", "user_id": "u",  # noqa: E731
                                   "data": {"severity": "critical", "alert_id": aid, "escalation_level": lvl}}
        toasts = []
        for i in range(5):
            toasts = logic.apply_events([note(f"a{i}")], [], {}, None, toasts, now=NOW)["toasts"]
        assert [t["data"]["alert_id"] for t in toasts] == ["a4", "a3", "a2"]       # newest first, at most 3
        assert toasts[0]["shown_at"] == NOW.isoformat()
        assert logic.fresh_toasts(toasts, NOW + timedelta(seconds=91)) == []

    def test_one_toast_per_alert_and_closed_alerts_drop_theirs(self):
        note = lambda aid, lvl=0: {"type": "notification", "user_id": "u",  # noqa: E731
                                   "data": {"severity": "critical", "alert_id": aid, "escalation_level": lvl}}
        toasts = logic.apply_events([note("a1"), note("a2"), note("a1", 1)], [], {}, None, [], now=NOW)["toasts"]
        assert [(t["data"]["alert_id"], t["data"]["escalation_level"]) for t in toasts] == [("a1", 1), ("a2", 0)]
        ack = alert("a1", THOMAS, "critical", status="acknowledged")
        st = logic.apply_events([{"type": "alert", "action": "acknowledged", "patient_id": THOMAS, "data": ack}], [],
                                {"a1": ack}, THOMAS, toasts, now=NOW)
        assert [t["data"]["alert_id"] for t in st["toasts"]] == ["a2"] and st["toasts_changed"]

    def test_selection_order(self, worklist):
        assert logic.initial_selection(worklist, None) == THOMAS
        assert logic.initial_selection(worklist, MARIA) == MARIA
        assert logic.initial_selection(worklist, THOMAS, linked_patient=MARIA) == MARIA
        assert logic.initial_selection(worklist, "gone") == THOMAS and logic.initial_selection([], None) is None

    def test_alert_ordering(self):
        alerts = [alert("m", THOMAS, "moderate", minutes_ago=1), alert("c", THOMAS, "critical", status="acknowledged"),
                  alert("c2", THOMAS, "critical", minutes_ago=2), alert("h", MARIA, "high")]
        mine, others = logic.order_alerts(alerts, THOMAS)
        assert [a["alert_id"] for a in mine] == ["c2", "c", "m"] and [a["alert_id"] for a in others] == ["h"]


class TestServer:
    @pytest.fixture
    def client(self):
        app = create_app("http://127.0.0.1:9", secret="test-secret")
        return app.server.test_client()

    def test_signed_out_gets_login_and_no_ticket(self, client):
        assert client.get("/rt/ticket").status_code == 401
        layout = client.get("/_dash-layout").get_json()
        assert "login-email" in str(layout) and "worklist" not in str(layout)

    def test_security_headers(self, client):
        r = client.get("/")
        assert r.headers["X-Frame-Options"] == "DENY" and r.headers["X-Content-Type-Options"] == "nosniff"

    def test_logout_clears_session(self, client):
        api = client.application.api
        api._tokens["sid-1"] = {"access": "a", "refresh": "r"}
        with client.session_transaction() as s:
            s["sid"] = "sid-1"
            s["user"] = {"first_name": "M", "last_name": "L", "role": "clinician"}
        assert "worklist" in str(client.get("/_dash-layout").get_json())
        assert client.get("/logout").status_code == 302
        with client.session_transaction() as s:
            assert "sid" not in s and "user" not in s
        assert "sid-1" not in api._tokens                    # tokens are dropped on the server too


class TestTokenHandling:
    """tokens never reach the browser, and concurrent callbacks refresh an expired token exactly once"""

    @staticmethod
    def fake_api(calls: list[str]) -> httpx.MockTransport:
        state = {"access": "a1", "refresh": "r1", "n": 1}

        def handler(req: httpx.Request) -> httpx.Response:
            calls.append(req.url.path)
            if req.url.path == "/api/v1/auth/token":
                return httpx.Response(200, json={"access_token": "a1", "refresh_token": "r1",
                                                 "user": {"role": "clinician", "first_name": "M", "last_name": "L"}})
            if req.url.path == "/api/v1/auth/refresh":
                body = json.loads(req.content)
                if body["refresh_token"] != state["refresh"]:
                    return httpx.Response(401, json={"detail": "refresh token reused"})
                state["n"] += 1
                state["access"], state["refresh"] = f"a{state['n']}", f"r{state['n']}"
                time.sleep(0.05)                               # widen the race window
                return httpx.Response(200, json={"access_token": state["access"], "refresh_token": state["refresh"]})
            if req.headers.get("authorization") != f"Bearer {state['access']}":
                return httpx.Response(401, json={"detail": "expired"})
            return httpx.Response(200, json=[])
        state["access"] = "a0"                                 # the token issued at login has already expired
        return httpx.MockTransport(handler)

    def test_cookie_holds_only_a_session_id(self):
        app = create_app("http://api.test", secret="test-secret")
        api = app.server.api
        api.http = httpx.Client(base_url="http://api.test", transport=self.fake_api([]))
        with app.server.test_request_context():
            api.login("m@example", "pw")
            assert set(flask.session) == {"sid", "user"}
            assert "a1" not in str(dict(flask.session)) and "r1" not in str(dict(flask.session))

    def test_concurrent_expiry_refreshes_once(self):
        app = create_app("http://api.test", secret="test-secret")
        api, calls = app.server.api, []
        api.http = httpx.Client(base_url="http://api.test", transport=self.fake_api(calls))
        with app.server.test_request_context():
            api.login("m@example", "pw")
            sid = flask.session["sid"]
        results, errors = [], []

        def worker() -> None:
            with app.server.test_request_context():
                flask.session["sid"] = sid
                try:
                    results.append(api.call("GET", "/monitoring/worklist"))
                except Exception as exc:  # noqa: BLE001
                    errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == [] and len(results) == 4
        assert calls.count("/api/v1/auth/refresh") == 1     # one rotation, so the api never sees a reused token
