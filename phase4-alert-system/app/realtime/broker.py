"""in-process publish/subscribe for live events (new readings, alert changes, notifications)

publishers are ordinary request threads; each subscriber is a websocket connection with its own asyncio queue.
publish() is thread-safe: it hands each event to the subscriber's event loop with call_soon_threadsafe, so a
reading committed in a worker thread reaches connected dashboards without polling. events are filtered per
subscriber by care-team scope before they are queued, so a clinician never receives another team's patients.

one process only; running several api workers needs a shared bus (for example redis pub/sub) behind the same
publish() interface.
"""
from __future__ import annotations

import asyncio
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.logging_config import get_logger

log = get_logger("realtime")


@dataclass(eq=False)
class Subscription:
    user_id: uuid.UUID
    scope: set[uuid.UUID]
    loop: asyncio.AbstractEventLoop
    queue: asyncio.Queue
    vitals_for: set[uuid.UUID] | None = None      # None: readings for every patient in scope
    dropped: int = 0
    connected_at: float = field(default_factory=time.time)

    def wants(self, event: dict[str, Any]) -> bool:
        target_user = event.get("user_id")
        if target_user is not None:
            return target_user == str(self.user_id)
        pid = event.get("patient_id")
        if pid is None:
            return event.get("type") == "system"
        pid = uuid.UUID(pid)
        if pid not in self.scope:
            return False
        if event.get("type") == "vital" and self.vitals_for is not None and pid not in self.vitals_for:
            return False
        return True

    def offer(self, event: dict[str, Any]) -> None:
        """runs on the subscriber's loop; a slow client loses its oldest events rather than stalling publishers"""
        if self.queue.full():
            try:
                self.queue.get_nowait()
                self.dropped += 1
            except asyncio.QueueEmpty:
                pass
        self.queue.put_nowait(event)


class Broker:
    def __init__(self, queue_size: int = 1000) -> None:
        self._subs: set[Subscription] = set()
        self._lock = threading.Lock()
        self.queue_size = queue_size
        self.published = 0

    def subscribe(self, user_id: uuid.UUID, scope: set[uuid.UUID]) -> Subscription:
        sub = Subscription(user_id=user_id, scope=set(scope), loop=asyncio.get_running_loop(),
                           queue=asyncio.Queue(maxsize=self.queue_size))
        with self._lock:
            self._subs.add(sub)
        log.info("stream subscribed", extra={"ctx": {"user_id": str(user_id), "patients": len(scope),
                                                     "subscribers": len(self._subs)}})
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        with self._lock:
            self._subs.discard(sub)
        log.info("stream closed", extra={"ctx": {"user_id": str(sub.user_id), "dropped": sub.dropped}})

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subs)

    def publish(self, event: dict[str, Any]) -> int:
        """queue an event for every interested subscriber; returns how many received it"""
        event.setdefault("published_at", datetime.now(timezone.utc).isoformat(timespec="milliseconds"))
        with self._lock:
            subs = list(self._subs)
        delivered = 0
        for sub in subs:
            if not sub.wants(event):
                continue
            try:
                sub.loop.call_soon_threadsafe(sub.offer, event)
                delivered += 1
            except RuntimeError:             # the subscriber's loop has closed
                self.unsubscribe(sub)
        self.published += 1
        return delivered


broker = Broker()
