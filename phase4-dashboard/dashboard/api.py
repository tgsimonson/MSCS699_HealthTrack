"""client for the healthtrack api

the dashboard is a client of the alert-system api like any other: it never opens the database. access and refresh
tokens stay in memory on the dashboard server, keyed by a random session id; the browser holds only that id in an
http-only signed cookie and, for the live stream, a one-time websocket ticket. refreshes are serialized per session,
so two callbacks that hit an expired token together never present the same refresh token twice (the api treats a
reused refresh token as theft and revokes every session).
"""
from __future__ import annotations

import logging
import secrets
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx
from flask import session

log = logging.getLogger("dashboard.api")


class ApiError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(f"{status}: {detail}")
        self.status, self.detail = status, detail


class NotSignedIn(ApiError):
    def __init__(self) -> None:
        super().__init__(401, "not signed in")


@dataclass
class ApiClient:
    base_url: str
    timeout: float = 10.0

    _tokens: dict[str, dict[str, str]] = field(default_factory=dict, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        self.http = httpx.Client(base_url=self.base_url.rstrip("/"), timeout=self.timeout)

    def _current(self) -> dict[str, str] | None:
        sid = session.get("sid")
        with self._lock:
            return dict(self._tokens[sid]) if sid in self._tokens else None

    # ---------------------------------------------------------------- session tokens
    def login(self, email: str, password: str, mfa_code: str | None = None) -> dict[str, Any]:
        data = {"username": email, "password": password}
        if mfa_code:
            data["mfa_code"] = mfa_code
        r = self.http.post("/api/v1/auth/token", data=data)
        if r.status_code != 200:
            raise ApiError(r.status_code, _detail(r))
        body = r.json()
        if body["user"]["role"] not in ("clinician", "physician"):
            self._revoke(body["access_token"])           # do not leave an unused api session open
            raise ApiError(403, "the monitoring dashboard is for clinicians and physicians")
        self.logout()                                    # a new sign-in replaces any earlier one in this browser
        sid = secrets.token_urlsafe(32)
        with self._lock:
            self._tokens[sid] = {"access": body["access_token"], "refresh": body["refresh_token"]}
        session["sid"], session["user"] = sid, body["user"]
        return body["user"]

    def _revoke(self, access: str) -> None:
        try:
            self.http.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {access}"})
        except httpx.HTTPError:
            pass

    def logout(self) -> None:
        sid = session.get("sid")
        with self._lock:
            tokens = self._tokens.pop(sid, None) if sid else None
        if tokens:
            self._revoke(tokens["access"])
        session.clear()

    def signed_in(self) -> bool:
        return self._current() is not None

    def _refresh(self, stale_access: str) -> bool:
        """rotate the refresh token once per expiry: a caller that finds the token already replaced just retries"""
        sid = session.get("sid")
        with self._lock:
            tokens = self._tokens.get(sid) if sid else None
            if tokens is None:
                return False
            if tokens["access"] != stale_access:
                return True                              # another callback refreshed while this one waited
            r = self.http.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh"]})
            if r.status_code != 200:
                self._tokens.pop(sid, None)
                return False
            body = r.json()
            self._tokens[sid] = {"access": body["access_token"], "refresh": body["refresh_token"]}
            return True

    def call(self, method: str, path: str, **kw: Any) -> Any:
        """authenticated request; a 401 triggers one refresh-token rotation and a retry"""
        for attempt in range(2):
            tokens = self._current()
            if not tokens:
                session.clear()
                raise NotSignedIn()
            r = self.http.request(method, f"/api/v1{path}", headers={"Authorization": f"Bearer {tokens['access']}"},
                                  **kw)
            if r.status_code == 401 and attempt == 0 and self._refresh(tokens["access"]):
                continue
            if r.status_code == 401:
                session.clear()
                raise NotSignedIn()
            if r.status_code >= 400:
                raise ApiError(r.status_code, _detail(r))
            return r.json() if r.content else None
        raise NotSignedIn()

    # ---------------------------------------------------------------- data the dashboard uses
    def worklist(self) -> list[dict]:
        return self.call("GET", "/monitoring/worklist")

    def active_alerts(self) -> list[dict]:
        return self.call("GET", "/alerts", params={"page_size": 200})["items"]

    def patient_bundle(self, patient_id: str, hours: int) -> dict[str, Any]:
        """everything the patient view needs, in six requests (more pages only for long ranges)"""
        end = datetime.now(timezone.utc)
        start = end - timedelta(hours=hours)
        patient = self.call("GET", f"/patients/{patient_id}")
        try:
            rx = self.call("GET", f"/patients/{patient_id}/prescription")
        except ApiError as e:
            if e.status != 404:
                raise
            rx = None
        thresholds = self.call("GET", f"/patients/{patient_id}/alert-thresholds")
        readings: list[dict] = []
        page, max_pages = 1, 15                       # at most 3000 readings; long ranges are downsampled
        while page <= max_pages:
            body = self.call("GET", f"/patients/{patient_id}/vitals",
                             params={"start": start.isoformat(), "end": (end + timedelta(minutes=1)).isoformat(),
                                     "order": "newest", "page": page, "page_size": 200})
            readings += body["items"]
            if page >= body["meta"]["total_pages"]:
                break
            page += 1
        today = date.today()
        activity = self.call("GET", f"/patients/{patient_id}/daily-activity",
                             params={"start_date": (today - timedelta(days=13)).isoformat(),
                                     "end_date": today.isoformat()})
        readings.reverse()                            # oldest first for plotting
        latest = self.call("GET", f"/patients/{patient_id}/vitals/latest")   # gauges show it even if older
        return {"patient": patient, "prescription": rx, "thresholds": thresholds, "readings": readings,
                "latest": latest, "activity": activity, "hours": hours, "loaded_at": end.isoformat()}

    def alert_detail(self, alert_id: str) -> dict:
        return self.call("GET", f"/alerts/{alert_id}")

    def acknowledge(self, alert_id: str, note: str | None = None) -> dict:
        return self.call("POST", f"/alerts/{alert_id}/acknowledge", json={"note": note} if note else {})

    def resolve(self, alert_id: str, note: str) -> dict:
        return self.call("POST", f"/alerts/{alert_id}/resolve", json={"note": note})

    def stream_ticket(self) -> dict:
        return self.call("POST", "/stream/ticket")


def _detail(r: httpx.Response) -> str:
    try:
        return r.json().get("detail") or r.text[:200]
    except ValueError:
        return r.text[:200]
