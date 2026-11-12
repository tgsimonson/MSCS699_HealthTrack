"""schema update: device registry, device links on readings and activity, activity distance

Revision ID: 0002_device_registry
Revises: 0001_initial
Create Date: 2026-11-05

Adds the devices table so each reading can be traced to the band, cuff, or oximeter that produced it,
links vital_signs and daily_activity to devices, and adds distance_m to daily_activity. Existing rows
keep device_id NULL, so the upgrade is safe on a populated database.
"""
import sqlalchemy as sa
from alembic import op

from app.models.enums import DeviceStatus, DeviceType
from migrations.helpers import create_enum_types, drop_enum_types, enum_col, ts

revision = "0002_device_registry"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    create_enum_types((DeviceType, "device_type"), (DeviceStatus, "device_status"))
    op.create_table(
        "devices",
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("patient_id", sa.Uuid()),
        sa.Column("device_type", enum_col(DeviceType, "device_type"), nullable=False),
        sa.Column("manufacturer", sa.String(60), nullable=False),
        sa.Column("model", sa.String(60), nullable=False),
        sa.Column("serial_number", sa.String(60), nullable=False),
        sa.Column("status", enum_col(DeviceStatus, "device_status"), nullable=False),
        sa.Column("last_sync_at", ts()),
        sa.Column("created_at", ts(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", ts(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("device_id", name=op.f("pk_devices")),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.patient_id"], name=op.f("fk_devices_patient_id_patients"),
                                ondelete="SET NULL"),
        sa.UniqueConstraint("manufacturer", "serial_number", name=op.f("uq_devices_manufacturer_serial_number")),
        sa.CheckConstraint("status <> 'active' OR patient_id IS NOT NULL", name=op.f("ck_devices_active_has_patient")),
    )
    op.create_index("ix_devices_patient", "devices", ["patient_id"])

    with op.batch_alter_table("vital_signs") as batch:
        batch.add_column(sa.Column("device_id", sa.Uuid()))
        batch.create_foreign_key("fk_vital_signs_device_id_devices", "devices", ["device_id"], ["device_id"],
                                 ondelete="SET NULL")
        batch.create_index("ix_vital_signs_device", ["device_id"])

    with op.batch_alter_table("daily_activity") as batch:
        batch.add_column(sa.Column("device_id", sa.Uuid()))
        batch.add_column(sa.Column("distance_m", sa.Integer()))
        batch.create_foreign_key("fk_daily_activity_device_id_devices", "devices", ["device_id"], ["device_id"],
                                 ondelete="SET NULL")
        batch.create_check_constraint(op.f("ck_daily_activity_distance_range"),
                                      "distance_m IS NULL OR distance_m BETWEEN 0 AND 100000")


def downgrade() -> None:
    with op.batch_alter_table("daily_activity") as batch:
        batch.drop_constraint(op.f("ck_daily_activity_distance_range"), type_="check")
        batch.drop_constraint("fk_daily_activity_device_id_devices", type_="foreignkey")
        batch.drop_column("distance_m")
        batch.drop_column("device_id")
    with op.batch_alter_table("vital_signs") as batch:
        batch.drop_index("ix_vital_signs_device")
        batch.drop_constraint("fk_vital_signs_device_id_devices", type_="foreignkey")
        batch.drop_column("device_id")
    op.drop_index("ix_devices_patient", table_name="devices")
    op.drop_table("devices")
    drop_enum_types("device_type", "device_status")
