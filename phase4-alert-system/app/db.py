"""engine and session factory; works with sqlite (default) and postgresql"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings


def make_engine(url: str, echo: bool = False) -> Engine:
    if url.startswith("sqlite"):
        kwargs: dict = {"connect_args": {"check_same_thread": False, "timeout": 15}}
        if url in ("sqlite://", "sqlite:///:memory:"):
            # one shared connection so every session sees the same in-memory database
            kwargs["poolclass"] = StaticPool
        engine = create_engine(url, echo=echo, **kwargs)

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):  # noqa: ANN001
            # the pysqlite driver never emits BEGIN itself, so a SAVEPOINT would become the outermost
            # transaction and releasing it would commit; take over transaction control (sqlalchemy's recipe)
            dbapi_conn.isolation_level = None
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")      # sqlite ignores foreign keys unless asked
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.close()

        @event.listens_for(engine, "begin")
        def _sqlite_begin(conn):  # noqa: ANN001
            # immediate: take the write lock up front. every api request writes (at least its audit row), and a
            # deferred transaction that upgrades from read to write after another writer fails at once with
            # SQLITE_BUSY instead of waiting; immediate transactions queue on the busy timeout instead
            conn.exec_driver_sql("BEGIN IMMEDIATE")

        return engine
    return create_engine(url, echo=echo, pool_size=10, max_overflow=20, pool_pre_ping=True, pool_recycle=1800)


_settings = get_settings()
engine: Engine = make_engine(_settings.database_url, _settings.sql_echo)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """fastapi dependency: one session per request, committed on success, rolled back on error"""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@contextmanager
def _session_scope() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_session_factory():  # noqa: ANN201
    """fastapi dependency for code that opens its own short sessions (the websocket); tests override it"""
    return _session_scope
