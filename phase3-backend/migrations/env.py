"""alembic environment: url from HT_DATABASE_URL (or -x url=...), metadata from app.models"""
from __future__ import annotations

import os

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.models import Base

config = context.config
url = context.get_x_argument(as_dictionary=True).get("url") or os.getenv("HT_DATABASE_URL", "sqlite:///./healthtrack.db")
config.set_main_option("sqlalchemy.url", url)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = config.attributes.get("connection")
    if connectable is None:
        connectable = engine_from_config(config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.",
                                         poolclass=pool.NullPool)
        with connectable.connect() as connection:
            _run(connection)
    else:
        _run(connectable)


def _run(connection) -> None:  # noqa: ANN001
    if connection.dialect.name == "sqlite":
        # pragma must run outside a transaction; commit so alembic starts (and commits) its own
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.commit()
    # render_as_batch lets sqlite apply ALTER TABLE changes by copying the table
    context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True,
                      compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
