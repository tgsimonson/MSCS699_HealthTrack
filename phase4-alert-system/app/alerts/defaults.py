"""default alert rules and escalation policies (loaded by migration 0003; editable through the api afterward)

threshold resolution order for each reading: an active patient override, then the patient's current exercise
prescription (prescription_field), then the rule's default_threshold.
"""
from __future__ import annotations

import uuid

from app.models.enums import AlertRuleType, AlertSeverity, CareTeamRole

T, PAT, GAP = AlertRuleType.threshold, AlertRuleType.pattern, AlertRuleType.data_gap
CRIT, HIGH, MOD, LOW = AlertSeverity.critical, AlertSeverity.high, AlertSeverity.moderate, AlertSeverity.low
EXERTION = ["warmup", "exercise", "cooldown"]
POST_EXERTION = ["exercise", "cooldown", "recovery"]
REST = ["rest"]


def rule_uuid(code: str) -> uuid.UUID:
    """stable ids so seed data, tests, and documentation can refer to a rule by id"""
    return uuid.uuid5(uuid.NAMESPACE_URL, f"healthtrack/alert-rule/{code}")


# code, name, type, metric, comparator, default, prescription field, contexts, window min, consecutive, severity,
# suppression min, customizable, description
RULES = [
    ("HR_ABOVE_CEILING", "Heart rate above prescribed ceiling", T, "heart_rate", ">", 150, "hr_ceiling", EXERTION,
     30, 2, CRIT, 0, False,
     "Exercise heart rate above the prescription ceiling on consecutive readings. The 150 bpm default applies only "
     "when the patient has no prescription."),
    ("SPO2_LOW", "Low oxygen saturation", T, "spo2", "<", 90, "min_spo2", None, 30, 2, CRIT, 0, False,
     "SpO2 below the prescription floor on consecutive readings."),
    ("EXERCISE_SBP_HIGH", "Exercise blood pressure high", T, "systolic_bp", ">", 200, "max_exercise_sbp",
     POST_EXERTION, 0, 1, HIGH, 30, False,
     "Systolic pressure during or right after exercise above the prescription maximum."),
    ("RESTING_SBP_LOW", "Resting systolic pressure low", T, "systolic_bp", "<", 90, None, REST, 0, 1, HIGH, 240, True,
     "Resting systolic pressure below the threshold (possible hypotension or over-medication)."),
    ("RESTING_HR_LOW", "Resting heart rate low", T, "heart_rate", "<", 40, None, REST, 60, 2, HIGH, 240, True,
     "Resting heart rate below the threshold on consecutive readings (possible bradycardia)."),
    ("RESTING_SBP_HIGH", "Resting systolic pressure high", T, "systolic_bp", ">=", 160, None, REST, 0, 1, MOD, 720,
     True, "Resting systolic pressure at or above the threshold."),
    ("RESTING_HR_HIGH", "Resting heart rate high", T, "heart_rate", ">", 100, None, REST, 60, 2, MOD, 720, True,
     "Resting heart rate above the threshold on consecutive readings."),
    ("MISSED_SESSIONS", "Consecutive missed sessions", PAT, "consecutive_missed_sessions", ">=", 2, None, None,
     20160, 1, HIGH, 1440, True,
     "Prescribed sessions missed in a row, from the days since the last exercise session and the prescribed "
     "sessions per week."),
    ("RESTING_HR_RISE", "Resting heart rate trending up", PAT, "resting_hr_7d_minus_baseline", ">", 8, None, None,
     10080, 1, MOD, 1440, True,
     "7-day average resting heart rate exceeds the prescription baseline by more than the threshold (bpm)."),
    ("ZONE_MINUTES_DECLINE", "Minutes in target zone declining", PAT, "minutes_in_zone_wow_pct", "<=", -25, None,
     None, 20160, 1, MOD, 1440, True,
     "Week-over-week change in exercise minutes inside the prescribed heart rate zone at or below the threshold "
     "(percent)."),
    ("STEPS_DECLINE", "Daily steps declining", PAT, "steps_7d_vs_prior_pct", "<=", -30, None, None, 20160, 1, MOD,
     1440, True, "Average daily steps over the last 7 days compared with the 7 days before, at or below the threshold "
     "(percent)."),
    ("DATA_GAP", "No data received", GAP, "hours_since_last_reading", ">=", 48, None, None, 0, 1, LOW, 1440, True,
     "Hours since the last reading from any device."),
]

# severity, ack timeout min, escalate to, max level, channels, digest
POLICIES = [
    (CRIT, 15, CareTeamRole.supervising_physician, 2, ["dashboard", "sms", "email"], False),
    (HIGH, 60, CareTeamRole.supervising_physician, 2, ["dashboard", "email"], False),
    (MOD, 240, CareTeamRole.supervising_physician, 1, ["dashboard"], False),
    (LOW, 1440, CareTeamRole.primary_clinician, 0, ["dashboard", "email"], True),
]


def rule_rows() -> list[dict]:
    keys = ("rule_code", "name", "rule_type", "metric", "comparator", "default_threshold", "prescription_field",
            "applies_to_context", "evaluation_window_minutes", "consecutive_required", "severity",
            "suppression_minutes", "is_customizable", "description")
    return [{"rule_id": rule_uuid(r[0]), **dict(zip(keys, r, strict=True)), "is_active": True} for r in RULES]


def policy_rows() -> list[dict]:
    keys = ("severity", "ack_timeout_minutes", "escalate_to", "max_escalation_level", "channels", "deliver_as_digest")
    return [dict(zip(keys, p, strict=True)) for p in POLICIES]
