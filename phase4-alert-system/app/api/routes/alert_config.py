"""alert configuration: program rules, escalation policies, exercise prescriptions, and per-patient thresholds"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.alerts.engine import ThresholdResolver
from app.api.deps import DB, CurrentUser, PatientAccess, require_roles
from app.api.responses import AUTHED, PATIENT_SCOPED, R404, R422
from app.errors import NotFoundError
from app.models import AlertRule, EscalationPolicy, ExercisePrescription, Patient, User
from app.models.enums import AlertSeverity, AuditAction, UserRole
from app.repositories import AuditRepository
from app.repositories.alerts import AlertRepository
from app.schemas.alerts import (AlertRuleOut, AlertRuleUpdate, EffectiveThreshold, EscalationPolicyOut,
                                EscalationPolicyUpdate, PrescriptionIn, PrescriptionOut, ThresholdOverrideIn)

router = APIRouter(tags=["Alert Configuration"])
Reader = Annotated[User, Depends(require_roles(UserRole.clinician, UserRole.physician, UserRole.admin))]
Physician = Annotated[User, Depends(require_roles(UserRole.physician))]
CareTeamRead = Annotated[Patient, Depends(PatientAccess(entity="alert_configuration"))]
CareTeamOnly = Annotated[Patient, Depends(PatientAccess(allow_patient=False, entity="alert_configuration"))]
CareTeamWrite = Annotated[Patient, Depends(PatientAccess(allow_patient=False, entity="alert_configuration",
                                                         action=AuditAction.update))]
PhysicianWrite = Annotated[Patient, Depends(PatientAccess(allow_patient=False, care_roles={UserRole.physician},
                                                          entity="alert_configuration", action=AuditAction.update))]


@router.get("/alert-rules", response_model=list[AlertRuleOut], summary="List alert rules", responses=AUTHED,
            description="**Roles:** clinician, physician, admin. Every program rule with its default threshold, "
                        "the prescription field that personalizes it (if any), severity, consecutive-reading "
                        "requirement, and suppression window.")
def list_rules(db: DB, user: Reader) -> list[AlertRule]:
    return AlertRepository(db).list_rules()


@router.patch("/alert-rules/{rule_code}", response_model=AlertRuleOut, summary="Change a program rule",
              responses={**AUTHED, **R404, **R422},
              description="**Roles:** physician (medical director decision). Changes apply to every patient that "
                          "has no override or prescription value for the rule. Critical rules must keep "
                          "`suppression_minutes` at 0. The reason and changed fields are written to the audit log.")
def update_rule(rule_code: str, body: AlertRuleUpdate, db: DB, user: Physician) -> AlertRule:
    changes = body.model_dump(exclude_unset=True, exclude={"reason"})
    rule, changed = AlertRepository(db).update_rule(rule_code, changes, user)
    AuditRepository(db).record(AuditAction.update, "alert_rules", actor=user, entity_id=rule_code,
                               details={"changed_columns": changed, "reason": body.reason})
    return rule


@router.get("/escalation-policies", response_model=list[EscalationPolicyOut], summary="List escalation policies",
            responses=AUTHED, description="**Roles:** clinician, physician, admin.")
def list_policies(db: DB, user: Reader) -> list[EscalationPolicy]:
    return AlertRepository(db).list_policies()


@router.put("/escalation-policies/{severity}", response_model=EscalationPolicyOut,
            summary="Change an escalation policy", responses={**AUTHED, **R404, **R422},
            description="**Roles:** physician or admin. Critical alerts must escalate within 30 minutes and cannot "
                        "be delivered as a digest; only low severity can use the digest. The dashboard channel is "
                        "always included.")
def update_policy(severity: AlertSeverity, body: EscalationPolicyUpdate, db: DB,
                  user: Annotated[User, Depends(require_roles(UserRole.physician, UserRole.admin))]
                  ) -> EscalationPolicy:
    data = body.model_dump(exclude={"reason"})
    data["channels"] = [c.value for c in body.channels]
    pol = AlertRepository(db).update_policy(severity, data, user)
    AuditRepository(db).record(AuditAction.update, "escalation_policies", actor=user, entity_id=severity.value,
                               details={"reason": body.reason})
    return pol


@router.get("/patients/{patient_id}/prescription", response_model=PrescriptionOut,
            summary="Current exercise prescription", responses=PATIENT_SCOPED,
            description="**Roles:** patient (self), clinician and physician (care team). The prescription supplies "
                        "this patient's heart rate ceiling, SpO2 floor, and exercise blood pressure limit.")
def get_prescription(db: DB, user: CurrentUser, patient: CareTeamRead) -> ExercisePrescription:
    rx = AlertRepository(db).current_prescription(patient.patient_id)
    if rx is None:
        raise NotFoundError("no exercise prescription on file")
    AuditRepository(db).record(AuditAction.read, "exercise_prescriptions", actor=user, patient_id=patient.patient_id)
    return rx


@router.put("/patients/{patient_id}/prescription", response_model=PrescriptionOut,
            status_code=status.HTTP_201_CREATED, summary="Issue a new prescription version",
            responses={**PATIENT_SCOPED, **R422},
            description="**Roles:** physician (care team). Creates a new version and closes the previous one at "
                        "the same instant, so earlier alerts can still be traced to the limits in force then. Alert "
                        "evaluation uses the new limits from the next reading.")
def put_prescription(body: PrescriptionIn, db: DB, user: CurrentUser, patient: PhysicianWrite) -> ExercisePrescription:
    rx = AlertRepository(db).set_prescription(patient.patient_id, body.model_dump(), user)
    AuditRepository(db).record(AuditAction.create, "exercise_prescriptions", actor=user, entity_id=rx.prescription_id,
                               patient_id=patient.patient_id, details={"version": rx.version})
    return rx


@router.get("/patients/{patient_id}/alert-thresholds", response_model=list[EffectiveThreshold],
            summary="Effective thresholds for one patient", responses=PATIENT_SCOPED,
            description="**Roles:** clinician and physician (care team). The threshold actually applied for each "
                        "active rule and where it came from: `override` (set for this patient), `prescription`, or "
                        "`default`. The dashboard uses this to draw threshold bands and color abnormal readings.")
def effective_thresholds(db: DB, user: CurrentUser, patient: CareTeamOnly) -> list[EffectiveThreshold]:
    repo = AlertRepository(db)
    resolver = ThresholdResolver(repo, patient.patient_id)
    out = []
    for rule in repo.list_rules(active_only=True):
        value, source = resolver.resolve(rule)
        ov = resolver.overrides.get(rule.rule_id)
        out.append(EffectiveThreshold(rule_code=rule.rule_code, name=rule.name, rule_type=rule.rule_type,
                                      metric=rule.metric, comparator=rule.comparator, threshold=value, source=source,
                                      severity=rule.severity, applies_to_context=rule.applies_to_context,
                                      consecutive_required=rule.consecutive_required,
                                      is_customizable=rule.is_customizable,
                                      override_reason=ov.reason if ov else None,
                                      override_set_by=ov.set_by if ov else None,
                                      override_since=ov.effective_from if ov else None))
    AuditRepository(db).record(AuditAction.read, "alert_configuration", actor=user, patient_id=patient.patient_id)
    return out


@router.post("/patients/{patient_id}/alert-thresholds", response_model=list[EffectiveThreshold],
             status_code=status.HTTP_201_CREATED, summary="Set a patient-specific threshold",
             responses={**PATIENT_SCOPED, **R422},
             description="**Roles:** clinician and physician (care team). Overrides one customizable rule for this "
                         "patient. A clinical reason is required. Rules personalized by the prescription (heart rate "
                         "ceiling, SpO2 floor, exercise blood pressure) change through the prescription instead. "
                         "Setting a new value closes the previous override; history is kept.")
def set_threshold(body: ThresholdOverrideIn, db: DB, user: CurrentUser, patient: CareTeamWrite
                  ) -> list[EffectiveThreshold]:
    repo = AlertRepository(db)
    rule = repo.get_rule(body.rule_code)
    ov = repo.set_override(patient.patient_id, rule, body.threshold_value, body.reason, user)
    AuditRepository(db).record(AuditAction.create, "patient_alert_thresholds", actor=user, entity_id=ov.override_id,
                               patient_id=patient.patient_id, details={"rule": rule.rule_code})
    return effective_thresholds(db, user, patient)


@router.delete("/patients/{patient_id}/alert-thresholds/{rule_code}", status_code=status.HTTP_204_NO_CONTENT,
               summary="Remove a patient-specific threshold", responses=PATIENT_SCOPED,
               description="**Roles:** clinician and physician (care team). The rule falls back to the prescription "
                           "or program default. The override row is closed, not deleted.")
def end_threshold(rule_code: str, db: DB, user: CurrentUser, patient: CareTeamWrite) -> None:
    repo = AlertRepository(db)
    rule = repo.get_rule(rule_code)
    repo.end_override(patient.patient_id, rule)
    AuditRepository(db).record(AuditAction.update, "patient_alert_thresholds", actor=user,
                               patient_id=patient.patient_id, details={"rule": rule_code, "ended": True})
