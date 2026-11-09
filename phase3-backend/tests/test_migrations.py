"""migration scripts build the same schema as the models, and upgrade/downgrade cleanly"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from app.models import Base

ROOT = Path(__file__).resolve().parents[1]
PG = (os.getenv("HT_TEST_DATABASE_URL") or "").startswith("postgresql")


@pytest.fixture
def mig_url(tmp_path):
    if PG:
        pytest.skip("migration tests use a throwaway sqlite file; postgres migrations are checked with alembic check")
    return f"sqlite:///{tmp_path / 'migrations.db'}"


def cfg(url: str) -> Config:
    c = Config(str(ROOT / "alembic.ini"))
    c.set_main_option("script_location", str(ROOT / "migrations"))
    c.cmd_opts = type("o", (), {"x": [f"url={url}"]})()
    return c


def test_upgrade_head_matches_models(mig_url):
    command.upgrade(cfg(mig_url), "head")
    eng = create_engine(mig_url)
    with eng.connect() as conn:
        diffs = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diffs == [], f"models and migrations differ: {diffs}"


def test_schema_update_0002_adds_device_registry(mig_url):
    c = cfg(mig_url)
    command.upgrade(c, "0001_initial")
    insp = inspect(create_engine(mig_url))
    assert "devices" not in insp.get_table_names()
    assert "device_id" not in {col["name"] for col in insp.get_columns("vital_signs")}
    command.upgrade(c, "head")
    insp = inspect(create_engine(mig_url))
    assert "devices" in insp.get_table_names()
    assert {"device_id", "distance_m"} <= {col["name"] for col in insp.get_columns("daily_activity")}


def test_downgrade_to_base_and_back(mig_url):
    c = cfg(mig_url)
    command.upgrade(c, "head")
    command.downgrade(c, "base")
    assert set(inspect(create_engine(mig_url)).get_table_names()) <= {"alembic_version"}
    command.upgrade(c, "head")
    assert "vital_signs" in inspect(create_engine(mig_url)).get_table_names()
