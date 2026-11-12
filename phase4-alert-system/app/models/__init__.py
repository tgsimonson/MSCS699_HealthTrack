"""import every model so Base.metadata is complete for alembic and tests"""
from app.models.alerting import (Alert, AlertEvent, AlertRule, EscalationPolicy, ExercisePrescription, Notification,
                                 PatientAlertThreshold)
from app.models.audit import AuditLog
from app.models.base import Base
from app.models.monitoring import DailyActivity, Device, VitalSign
from app.models.patient import CareTeamAssignment, Patient
from app.models.user import AuthSession, User

__all__ = ["Alert", "AlertEvent", "AlertRule", "AuditLog", "AuthSession", "Base", "CareTeamAssignment",
           "DailyActivity", "Device", "EscalationPolicy", "ExercisePrescription", "Notification", "Patient",
           "PatientAlertThreshold", "User", "VitalSign"]
