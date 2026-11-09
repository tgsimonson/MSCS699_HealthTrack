"""append-only audit trail of who touched which record (never the phi values themselves)"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, Index, String, Uuid, event
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BigIntPK, Base, UTCDateTime, utcnow
from app.models.enums import AuditAction, UserRole, sa_enum


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_patient_time", "patient_id", "occurred_at"),
        Index("ix_audit_log_actor_time", "actor_user_id", "occurred_at"),
    )

    audit_id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)   # no fk: the log outlives account changes
    actor_role: Mapped[UserRole | None] = mapped_column(sa_enum(UserRole, "user_role"))
    action: Mapped[AuditAction] = mapped_column(sa_enum(AuditAction, "audit_action"), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(64))
    patient_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    outcome: Mapped[str] = mapped_column(String(10), default="success", nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


@event.listens_for(AuditLog, "before_update")
def _audit_immutable(_mapper, _conn, _target) -> None:  # noqa: ANN001
    raise PermissionError("audit_log is append-only")


@event.listens_for(AuditLog, "before_delete")
def _audit_undeletable(_mapper, _conn, _target) -> None:  # noqa: ANN001
    raise PermissionError("audit_log is append-only")
