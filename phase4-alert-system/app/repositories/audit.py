"""append-only audit log writer and reader"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.logging_config import get_logger, request_id_var
from app.models import AuditLog, User
from app.models.enums import AuditAction
from app.repositories.base import PageResult, paginate

log = get_logger("audit")


class AuditRepository:
    def __init__(self, session: Session) -> None:
        self.s = session

    def record(self, action: AuditAction, entity_type: str, *, actor: User | None = None,
               entity_id: Any = None, patient_id: uuid.UUID | None = None, outcome: str = "success",
               details: dict[str, Any] | None = None) -> AuditLog:
        """write one audit entry; details must never contain phi values (counts and column names only)"""
        rid = request_id_var.get()
        entry = AuditLog(actor_user_id=actor.user_id if actor else None, actor_role=actor.role if actor else None,
                         action=action, entity_type=entity_type,
                         entity_id=str(entity_id) if entity_id is not None else None, patient_id=patient_id,
                         outcome=outcome, request_id=None if rid == "-" else rid, details=details or {})
        self.s.add(entry)
        self.s.flush()
        log.info("audit", extra={"ctx": {"action": action.value, "entity": entity_type, "outcome": outcome}})
        return entry

    def list(self, *, patient_id: uuid.UUID | None = None, actor_user_id: uuid.UUID | None = None,
             action: AuditAction | None = None, start: datetime | None = None, end: datetime | None = None,
             page: int = 1, page_size: int = 50) -> PageResult[AuditLog]:
        stmt = select(AuditLog)
        if patient_id:
            stmt = stmt.where(AuditLog.patient_id == patient_id)
        if actor_user_id:
            stmt = stmt.where(AuditLog.actor_user_id == actor_user_id)
        if action:
            stmt = stmt.where(AuditLog.action == action)
        if start:
            stmt = stmt.where(AuditLog.occurred_at >= start)
        if end:
            stmt = stmt.where(AuditLog.occurred_at < end)
        return paginate(self.s, stmt.order_by(AuditLog.occurred_at.desc(), AuditLog.audit_id.desc()), page, page_size)
