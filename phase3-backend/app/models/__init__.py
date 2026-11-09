"""import every model so Base.metadata is complete for alembic and tests"""
from app.models.audit import AuditLog
from app.models.base import Base
from app.models.monitoring import DailyActivity, Device, VitalSign
from app.models.patient import CareTeamAssignment, Patient
from app.models.user import AuthSession, User

__all__ = ["AuditLog", "AuthSession", "Base", "CareTeamAssignment", "DailyActivity", "Device", "Patient", "User",
           "VitalSign"]
