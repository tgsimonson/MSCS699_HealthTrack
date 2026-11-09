"""shared helpers for migration scripts"""
from __future__ import annotations

import enum

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


def is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def create_enum_types(*specs: tuple[type[enum.Enum], str]) -> None:
    """create postgres enum types once up front (several tables share a type)"""
    if is_postgres():
        for py_enum, name in specs:
            postgresql.ENUM(*[m.value for m in py_enum], name=name).create(op.get_bind(), checkfirst=True)


def drop_enum_types(*names: str) -> None:
    if is_postgres():
        for name in names:
            postgresql.ENUM(name=name).drop(op.get_bind(), checkfirst=True)


def enum_col(py_enum: type[enum.Enum], name: str) -> sa.types.TypeEngine:
    """postgres: reference the existing type; sqlite: varchar plus a check constraint"""
    values = [m.value for m in py_enum]
    if is_postgres():
        return postgresql.ENUM(*values, name=name, create_type=False)
    return sa.Enum(*values, name=name, create_constraint=True)


def ts(**kw) -> sa.DateTime:  # noqa: ANN003
    return sa.DateTime(timezone=True, **kw)
