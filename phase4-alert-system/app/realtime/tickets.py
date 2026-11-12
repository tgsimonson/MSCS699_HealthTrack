"""short-lived, single-use tickets for opening a websocket from a browser

browsers cannot set an Authorization header on a websocket, and a bearer token in the url would end up in
proxy and server logs. the dashboard server (which holds the access token) asks the api for a ticket and gives
only the ticket to the browser. a ticket works once and expires after a minute.
"""
from __future__ import annotations

import secrets
import threading
import time
import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class Ticket:
    user_id: uuid.UUID
    session_id: uuid.UUID
    expires: float


class TicketStore:
    def __init__(self) -> None:
        self._tickets: dict[str, Ticket] = {}
        self._lock = threading.Lock()

    def issue(self, user_id: uuid.UUID, session_id: uuid.UUID, ttl_seconds: int) -> tuple[str, int]:
        value = "wst_" + secrets.token_urlsafe(24)
        now = time.monotonic()
        with self._lock:
            self._tickets = {k: t for k, t in self._tickets.items() if t.expires > now}   # drop expired
            self._tickets[value] = Ticket(user_id, session_id, now + ttl_seconds)
        return value, ttl_seconds

    def redeem(self, value: str) -> Ticket | None:
        with self._lock:
            ticket = self._tickets.pop(value, None)
        if ticket is None or ticket.expires < time.monotonic():
            return None
        return ticket


tickets = TicketStore()
