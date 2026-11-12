"""background jobs started with the api: notification dispatch, escalation checks, and pattern detection

dispatch waits on a wake-up event (set the moment an alert queues notifications) with a short poll as a fallback,
so critical messages leave within milliseconds and nothing is stranded if a wake-up is missed. the database
work runs in a worker thread so the event loop keeps serving websocket clients.
"""
from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from typing import Any

from app.config import get_settings
from app.logging_config import get_logger
from app.models.base import utcnow

log = get_logger("alerts.workers")


def run_dispatch(session_factory: Callable) -> dict[str, int]:
    from app.alerts.notifications import Dispatcher
    with session_factory() as db:
        stats = Dispatcher(db).dispatch_due(utcnow())
        db.commit()
    return stats


def run_escalations(session_factory: Callable) -> int:
    from app.alerts.engine import AlertEngine
    from app.alerts.service import alert_event
    from app.realtime.broker import broker
    with session_factory() as db:
        escalated = AlertEngine(db).run_escalations(utcnow())
        db.commit()
        for a in escalated:
            broker.publish(alert_event(a, "escalated"))
    if escalated:
        workers.wake()
    return len(escalated)


def run_patterns(session_factory: Callable) -> int:
    from app.alerts.engine import AlertEngine
    from app.alerts.service import publish_outcomes
    with session_factory() as db:
        outcomes = AlertEngine(db).evaluate_patterns(now=utcnow())
        db.commit()
        publish_outcomes(outcomes)
    return sum(1 for o in outcomes if o.action == "created")


class AlertWorkers:
    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._wake: asyncio.Event | None = None
        self._tasks: list[asyncio.Task] = []
        self.runs: dict[str, int] = {"dispatch": 0, "escalations": 0, "patterns": 0}

    @property
    def running(self) -> bool:
        return bool(self._tasks)

    async def start(self, session_factory: Callable | None = None) -> None:
        if session_factory is None:
            from app.db import SessionLocal
            session_factory = SessionLocal
        s = get_settings()
        self._loop, self._wake = asyncio.get_running_loop(), asyncio.Event()
        self._tasks = [
            asyncio.create_task(self._dispatch_loop(session_factory, s.dispatch_poll_seconds), name="dispatch"),
            asyncio.create_task(self._every(s.escalation_check_seconds, "escalations", run_escalations, session_factory),
                                name="escalations"),
            asyncio.create_task(self._every(s.pattern_check_minutes * 60, "patterns", run_patterns, session_factory),
                                name="patterns"),
        ]
        log.info("alert workers started", extra={"ctx": {"poll_s": s.dispatch_poll_seconds,
                                                         "escalation_s": s.escalation_check_seconds,
                                                         "pattern_min": s.pattern_check_minutes}})

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await t
        self._tasks, self._loop, self._wake = [], None, None

    def wake(self) -> None:
        """thread-safe: ask the dispatcher to run now (no-op when workers are not running, as in tests)"""
        if self._loop is not None and self._wake is not None:
            with contextlib.suppress(RuntimeError):
                self._loop.call_soon_threadsafe(self._wake.set)

    async def _dispatch_loop(self, session_factory: Callable, poll: float) -> None:
        assert self._wake is not None
        while True:
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._wake.wait(), timeout=poll)
            self._wake.clear()
            await self._run("dispatch", run_dispatch, session_factory)

    async def _every(self, seconds: float, name: str, fn: Callable, session_factory: Callable) -> None:
        while True:
            await asyncio.sleep(seconds)
            await self._run(name, fn, session_factory)

    async def _run(self, name: str, fn: Callable, session_factory: Callable) -> Any:
        try:
            result = await asyncio.to_thread(fn, session_factory)
            self.runs[name] += 1
            return result
        except Exception:                 # a failed run is logged and retried on the next cycle
            log.exception("alert job failed", extra={"ctx": {"job": name}})
            return None


workers = AlertWorkers()
