# HealthTrack Phase 4 alert system: testing scenarios and results

Generated 2026-11-12T22:55:30+00:00 on macOS-26.5.1-arm64-arm-64bit, Python 3.12.13.

## Summary

| Database | Tests | Passed | Failed | Errors | Skipped | Duration (s) |
|---|---|---|---|---|---|---|
| sqlite | 305 | 305 | 0 | 0 | 0 | 10.70 |

Line coverage of `app/`: **96.1%** (3377 of 3515 statements). Target from requirement NFR-16: 80%.

## Testing scenarios

52 named scenarios (55 test cases), 52 passed. Each scenario is an automated test (a parametrized scenario runs once per case); the requirement column refers to the Phase 1 requirements matrix.

| ID | Scenario | Requirement | Result | Test |
|---|---|---|---|---|
| AS-01 | Exercise heart rate above the prescribed ceiling on 2 consecutive readings raises a critical alert and queues dashboard, SMS, and email for the primary clinician | FR-10, FR-12, FR-13 | PASS | `test_critical_hr_above_prescribed_ceiling` |
| AS-02 | The same heart rate does not alert for a patient whose prescribed ceiling is higher | FR-10 | PASS | `test_same_value_patient_specific` |
| AS-03 | A single breaching reading does not alert when the rule needs consecutive readings | FR-10 | PASS | `test_single_spike_filtered` |
| AS-04 | Breaching readings farther apart than the rule window are not consecutive | FR-10 | PASS | `test_consecutive_window` |
| AS-05 | Context filters: a resting reading never triggers the exercise ceiling rule, but two high resting readings trigger the resting rule | FR-10 | PASS | `test_context_filters` |
| AS-06 | Suspect readings (implausible values) are stored but never alert | FR-07, FR-10 | PASS | `test_suspect_never_alerts` |
| AS-07 | A patient override (beta-blocker, resting limit 90) takes precedence over the program default | FR-10 | PASS | `test_override_precedence` |
| AS-08 | Without a prescription the program default applies and is labeled as the source | FR-10 | PASS | `test_default_without_prescription` |
| AS-09 | SpO2 below the prescription floor raises a critical alert in any context | FR-10 | PASS | `test_spo2_low` |
| AS-10 | Blood pressure rules: exercise systolic above the prescribed maximum is high; resting systolic at or above 160 is moderate | FR-10 | PASS | `test_bp_rules` |
| AS-11 | Missed sessions: no exercise session for a week (3 prescribed per week) raises a high alert; the adherent control stays silent | FR-11 | PASS | `test_missed_sessions` |
| AS-12 | Minutes in the prescribed heart rate zone falling at least 25% week over week raises a moderate alert; the control stays silent | FR-11 | PASS | `test_zone_minutes_decline` |
| AS-13 | 7-day resting heart rate more than 8 bpm above the prescription baseline raises a moderate alert; the control stays silent | FR-11 | PASS | `test_resting_hr_rise` |
| AS-14 | Average daily steps falling at least 30% from the week before raises a moderate alert; the control stays silent | FR-11 | PASS | `test_steps_decline` |
| AS-15 | No readings for 48 hours raises a low-severity data-gap alert; recent data stays silent | FR-11 | PASS | `test_data_gap` |
| AS-16 | Too little history never looks like a decline: trends need 4+ days in each week and a minimum baseline | FR-11 | PASS | `test_insufficient_data` |
| AS-17 | Repeated breaches attach to the open alert instead of creating new alerts or notifications | FR-12 | PASS | `test_repeats_absorbed` |
| AS-18 | After resolution, the same moderate rule inside its suppression window is logged as suppressed with no notifications; after the window it alerts again | FR-12 | PASS | `test_suppression_window` |
| AS-19 | Critical alerts are never suppressed: a repeat right after resolution notifies again | FR-12 | PASS | `test_critical_never_suppressed` |
| AS-20 | An active high-severity alert masks a lower-severity alert on the same measurement | FR-12 | PASS | `test_masking` |
| AS-21 | Low-severity alerts reach the dashboard now and email in the next morning digest | FR-12 | PASS | `test_low_goes_to_digest` |
| AS-22 | Alert-storm cap: past the hourly limit, a patient's non-critical email and SMS go to the digest while the dashboard is still notified immediately | FR-12 | PASS | `test_storm_cap` |
| AS-23 | Critical notifications are dispatched before lower-priority ones that were queued earlier | FR-12 | PASS | `test_critical_first` |
| AS-24 | Notification payload carries alert id, patient id, severity, rule, triggering values, and time; email and SMS text carry no patient name, MRN, or measured values | FR-13, NFR-06 | PASS | `test_payload_and_minimum_necessary` |
| AS-25 | Dispatch sends every due message, logs a 'notified' history event per delivery, and writes email and SMS to the outbox when no gateway is configured | FR-13 | PASS | `test_dispatch_logs_delivery` |
| AS-26 | A failing channel retries with backoff (15 s, then 30 s) and is marked failed with a reason after 3 attempts, without blocking other channels | FR-13 | PASS | `test_retry_then_fail` |
| AS-27 | Low-severity email is held for the morning digest and several alerts go out as one message per recipient | FR-12 | PASS | `test_digest_groups_messages` |
| AS-28 | SMS needs a phone number on the recipient account, and the digest message lists each alert with its sign-in link | FR-13 | PASS | `test_sms_requires_phone_and_digest_text` |
| AS-29 | A clinician on the care team acknowledges an alert; who and when are recorded in the alert history and the audit log | FR-14, NFR-05 | PASS | `test_acknowledge` |
| AS-30 | Patients and administrators cannot acknowledge (403); a clinician outside the care team gets 404 and the attempt is audited | FR-14, NFR-04 | PASS | `test_ack_permissions [admin-403]` |
| AS-30 | Patients and administrators cannot acknowledge (403); a clinician outside the care team gets 404 and the attempt is audited | FR-14, NFR-04 | PASS | `test_ack_permissions [it-403]` |
| AS-30 | Patients and administrators cannot acknowledge (403); a clinician outside the care team gets 404 and the attempt is audited | FR-14, NFR-04 | PASS | `test_ack_permissions [marcus-404]` |
| AS-30 | Patients and administrators cannot acknowledge (403); a clinician outside the care team gets 404 and the attempt is audited | FR-14, NFR-04 | PASS | `test_ack_permissions [robert_login-403]` |
| AS-31 | Resolution needs a note, records acknowledgment if missing, and closed alerts reject further actions | FR-14 | PASS | `test_resolution_rules` |
| AS-32 | An unacknowledged critical alert escalates to the supervising physician at 15 minutes (not before), to the whole care team on every channel at 30 minutes, and stops at the maximum level | FR-15 | PASS | `test_escalation_ladder` |
| AS-33 | Acknowledging an alert stops escalation | FR-14, FR-15 | PASS | `test_ack_stops_escalation` |
| AS-34 | Moderate alerts escalate once (after 4 hours); low alerts never escalate | FR-15 | PASS | `test_policy_levels` |
| AS-35 | History search filters by patient, severity, status, rule, date range, and acknowledging user, with correct paging | FR-16 | PASS | `test_history_search` |
| AS-36 | Alert detail returns the full timeline (created, notified, acknowledged, resolved) and minutes from trigger to acknowledgment and resolution | FR-16 | PASS | `test_detail_timeline` |
| AS-37 | Metrics report counts by severity and status and minutes to acknowledge, for clinicians (their team) and admins (whole program) | FR-16, FR-26 | PASS | `test_metrics` |
| AS-38 | Only a physician changes program rules, the reason is audited, and a critical rule cannot be given a suppression window | FR-12, NFR-05 | PASS | `test_rule_changes` |
| AS-39 | A physician issues a new prescription version; the next reading is judged against the new ceiling | FR-02, FR-10 | PASS | `test_prescription_endpoint` |
| AS-40 | Patient-specific thresholds need a clinical reason, are refused for prescription-driven rules, and removing one falls back to the default | FR-10 | PASS | `test_patient_thresholds` |
| AS-41 | Escalation policies are validated: critical must escalate within 30 minutes, only low may use the digest, and the dashboard channel is required | FR-15 | PASS | `test_policy_updates` |
| AS-42 | A dashboard connected with a ticket receives the new readings and the critical alert pushed over the websocket within the 5-second target | FR-18, NFR-07 | PASS | `test_push_reading_and_alert` |
| AS-43 | Tickets are single-use; a reused or invalid ticket and a wrong origin are refused | NFR-03 | PASS | `test_ticket_rules` |
| AS-44 | Events are filtered by care team: a clinician never receives another team's patient | NFR-04 | PASS | `test_scope_filtering` |
| AS-45 | Subscribing to one patient narrows reading events, while alerts still arrive for every patient in scope | FR-18 | PASS | `test_subscription_narrows_vitals` |
| AS-46 | Dashboard notifications go only to their recipient's open sessions | FR-13 | PASS | `test_notification_goes_to_recipient` |
| AS-47 | A device batch that crosses the ceiling returns alerts_raised and the alert appears on the care team's worklist, with repeats folded into it | FR-10, FR-18 | PASS | `test_batch_raises_alert` |
| AS-48 | If alert evaluation fails, the reading is still stored and the request succeeds | NFR-12 | PASS | `test_evaluation_failure_never_loses_readings` |
| AS-49 | The monitoring worklist ranks the patient with a critical alert first and carries latest values and prescription limits | FR-17, NFR-15 | PASS | `test_worklist` |
| AS-50 | Uploading a day of activity re-checks trend rules, so a step decline alerts without waiting for the scheduled job | FR-11 | PASS | `test_activity_upload_triggers_patterns` |
| AS-51 | Migration 0003 adds the alerting tables with the 12 default rules and 4 escalation policies to an existing phase 3 database, and downgrades cleanly | NFR-17 | PASS | `test_schema_update_0003_adds_alerting` |
| AS-52 | Background workers send queued notifications as soon as they are woken, without waiting for the poll interval | NFR-07 | PASS | `test_workers_dispatch_on_wake` |

## Results by area (sqlite)

| Test module | What it covers | Passed | Failed | Skipped |
|---|---|---|---|---|
| `test_models.py` | SQLAlchemy models: field constraints, foreign keys, invalid data | 68 | 0 | 0 |
| `test_repositories.py` | Data access layer: CRUD, filtering, pagination, errors, logging | 50 | 0 | 0 |
| `test_schemas_security.py` | Request validation schemas and security primitives | 40 | 0 | 0 |
| `test_migrations.py` | Alembic migrations: create, schema update, downgrade, drift | 4 | 0 | 0 |
| `test_api_auth.py` | Auth endpoints: login, lockout, MFA, refresh rotation, logout | 13 | 0 | 0 |
| `test_api_patients.py` | Patient endpoints: CRUD, search, role and scope matrix, audit | 29 | 0 | 0 |
| `test_api_monitoring.py` | Vital sign, activity, and device endpoints; error handling | 34 | 0 | 0 |
| `test_alert_engine.py` | Alert engine: thresholds, patient limits, fatigue controls, escalation | 24 | 0 | 0 |
| `test_alert_patterns.py` | Activity pattern detection against a declining patient and a stable control | 9 | 0 | 0 |
| `test_notifications.py` | Notification payloads, channels, delivery logging, retries, digests | 7 | 0 | 0 |
| `test_api_alerts.py` | Alert API: ingestion integration, worklist, acknowledgment, roles, history, configuration | 19 | 0 | 0 |
| `test_realtime.py` | Live stream: websocket auth, push latency, scope filtering, workers | 8 | 0 | 0 |

## Failures

None. Every test passed.

## Coverage by module

| Module | Statements | Missed | Coverage |
|---|---|---|---|
| `app/__init__.py` | 1 | 0 | 100% |
| `app/alerts/__init__.py` | 0 | 0 | 100% |
| `app/alerts/defaults.py` | 18 | 0 | 100% |
| `app/alerts/engine.py` | 211 | 7 | 97% |
| `app/alerts/notifications.py` | 153 | 19 | 88% |
| `app/alerts/patterns.py` | 109 | 5 | 95% |
| `app/alerts/service.py` | 51 | 4 | 92% |
| `app/alerts/workers.py` | 83 | 24 | 71% |
| `app/api/__init__.py` | 0 | 0 | 100% |
| `app/api/deps.py` | 60 | 2 | 97% |
| `app/api/handlers.py` | 41 | 1 | 98% |
| `app/api/responses.py` | 15 | 0 | 100% |
| `app/api/routes/__init__.py` | 0 | 0 | 100% |
| `app/api/routes/activity.py` | 60 | 1 | 98% |
| `app/api/routes/alert_config.py` | 74 | 1 | 99% |
| `app/api/routes/alerts.py` | 110 | 2 | 98% |
| `app/api/routes/auth.py` | 85 | 1 | 99% |
| `app/api/routes/patients.py` | 52 | 0 | 100% |
| `app/api/routes/stream.py` | 134 | 10 | 93% |
| `app/api/routes/vitals.py` | 88 | 1 | 99% |
| `app/config.py` | 55 | 1 | 98% |
| `app/db.py` | 47 | 14 | 70% |
| `app/errors.py` | 31 | 0 | 100% |
| `app/logging_config.py` | 36 | 2 | 94% |
| `app/main.py` | 76 | 3 | 96% |
| `app/models/__init__.py` | 7 | 0 | 100% |
| `app/models/alerting.py` | 136 | 0 | 100% |
| `app/models/audit.py` | 27 | 1 | 96% |
| `app/models/base.py` | 31 | 0 | 100% |
| `app/models/enums.py` | 108 | 0 | 100% |
| `app/models/monitoring.py` | 72 | 0 | 100% |
| `app/models/patient.py` | 86 | 0 | 100% |
| `app/models/user.py` | 43 | 2 | 95% |
| `app/realtime/__init__.py` | 0 | 0 | 100% |
| `app/realtime/broker.py` | 76 | 5 | 93% |
| `app/realtime/tickets.py` | 29 | 0 | 100% |
| `app/repositories/__init__.py` | 5 | 0 | 100% |
| `app/repositories/alerts.py` | 221 | 17 | 92% |
| `app/repositories/audit.py` | 34 | 0 | 100% |
| `app/repositories/base.py` | 75 | 6 | 92% |
| `app/repositories/monitoring.py` | 226 | 2 | 99% |
| `app/repositories/patients.py` | 98 | 2 | 98% |
| `app/repositories/users.py` | 62 | 3 | 95% |
| `app/schemas/__init__.py` | 0 | 0 | 100% |
| `app/schemas/alerts.py` | 214 | 0 | 100% |
| `app/schemas/auth.py` | 24 | 0 | 100% |
| `app/schemas/common.py` | 30 | 0 | 100% |
| `app/schemas/monitoring.py` | 128 | 0 | 100% |
| `app/schemas/patient.py` | 110 | 1 | 99% |
| `app/security.py` | 83 | 1 | 99% |

## Slowest tests

| Test | Seconds |
|---|---|
| `test_api_monitoring::test_openapi_documents_errors_and_security` | 0.485 |
| `test_migrations::test_downgrade_to_base_and_back` | 0.302 |
| `test_migrations::test_upgrade_head_matches_models` | 0.189 |
| `test_migrations::test_schema_update_0003_adds_alerting` | 0.119 |
| `test_api_alerts::test_history_search` | 0.117 |
| `test_api_alerts::test_batch_raises_alert` | 0.108 |
| `test_realtime::test_subscription_narrows_vitals` | 0.104 |
| `test_api_alerts::test_jobs_endpoint_and_notifications` | 0.102 |
| `test_api_monitoring::test_filters` | 0.102 |
| `test_alert_patterns::test_repeated_pattern_runs_do_not_duplicate` | 0.101 |

## Complete list

### test_models.py

- PASS TestPatientConstraints::test_valid_patient_persists_with_defaults
- PASS TestPatientConstraints::test_duplicate_mrn_rejected
- PASS TestPatientConstraints::test_malformed_mrn_rejected_by_model_validator[ht-1]
- PASS TestPatientConstraints::test_malformed_mrn_rejected_by_model_validator[HT 100001]
- PASS TestPatientConstraints::test_malformed_mrn_rejected_by_model_validator[XXXXXXXXXXXXXXXXXXXXX]
- PASS TestPatientConstraints::test_malformed_mrn_rejected_by_model_validator[]
- PASS TestPatientConstraints::test_format_validators[phone-7195550111]
- PASS TestPatientConstraints::test_format_validators[postal_code-8092]
- PASS TestPatientConstraints::test_format_validators[email-nope]
- PASS TestPatientConstraints::test_email_is_normalized_to_lowercase
- PASS TestPatientConstraints::test_minor_at_qualifying_event_rejected
- PASS TestPatientConstraints::test_future_qualifying_event_rejected
- PASS TestPatientConstraints::test_event_after_referral_rejected
- PASS TestPatientConstraints::test_enrollment_before_referral_rejected
- PASS TestPatientConstraints::test_active_without_enrollment_date_rejected
- PASS TestPatientConstraints::test_referred_without_enrollment_date_allowed
- PASS TestPatientConstraints::test_graduated_requires_graduation_date
- PASS TestPatientConstraints::test_graduation_date_without_graduated_status_rejected
- PASS TestPatientConstraints::test_active_high_risk_rejected
- PASS TestPatientConstraints::test_paused_high_risk_allowed
- PASS TestPatientConstraints::test_target_sessions_range[0]
- PASS TestPatientConstraints::test_target_sessions_range[73]
- PASS TestPatientConstraints::test_blank_name_rejected
- PASS TestPatientConstraints::test_invalid_enum_value_rejected
- PASS TestCareTeam::test_second_current_primary_clinician_rejected
- PASS TestCareTeam::test_ended_assignment_does_not_block_new_primary
- PASS TestCareTeam::test_covering_clinicians_may_overlap
- PASS TestCareTeam::test_end_before_start_rejected
- PASS TestVitalSignConstraints::test_valid_reading_persists
- PASS TestVitalSignConstraints::test_hard_limits[kw0]
- PASS TestVitalSignConstraints::test_hard_limits[kw1]
- PASS TestVitalSignConstraints::test_hard_limits[kw2]
- PASS TestVitalSignConstraints::test_hard_limits[kw3]
- PASS TestVitalSignConstraints::test_hard_limits[kw4]
- PASS TestVitalSignConstraints::test_hard_limits[kw5]
- PASS TestVitalSignConstraints::test_reading_without_measurement_rejected
- PASS TestVitalSignConstraints::test_bp_must_be_paired
- PASS TestVitalSignConstraints::test_systolic_must_exceed_diastolic
- PASS TestVitalSignConstraints::test_manual_reading_requires_author
- PASS TestVitalSignConstraints::test_duplicate_idempotency_key_rejected
- PASS TestVitalSignConstraints::test_same_key_allowed_for_different_patients
- PASS TestVitalSignConstraints::test_naive_datetime_rejected
- PASS TestVitalSignConstraints::test_datetimes_round_trip_as_utc
- PASS TestVitalSignConstraints::test_quality_assessment[args0-valid]
- PASS TestVitalSignConstraints::test_quality_assessment[args1-suspect]
- PASS TestVitalSignConstraints::test_quality_assessment[args2-suspect]
- PASS TestVitalSignConstraints::test_quality_assessment[args3-suspect]
- PASS TestVitalSignConstraints::test_quality_assessment[args4-suspect]
- PASS TestVitalSignConstraints::test_quality_assessment[args5-suspect]
- PASS TestVitalSignConstraints::test_quality_assessment[args6-valid]
- PASS TestActivityAndDevices::test_valid_day_persists
- PASS TestActivityAndDevices::test_one_row_per_patient_per_day
- PASS TestActivityAndDevices::test_activity_limits[kw0]
- PASS TestActivityAndDevices::test_activity_limits[kw1]
- PASS TestActivityAndDevices::test_activity_limits[kw2]
- PASS TestActivityAndDevices::test_activity_limits[kw3]
- PASS TestActivityAndDevices::test_activity_limits[kw4]
- PASS TestActivityAndDevices::test_activity_limits[kw5]
- PASS TestActivityAndDevices::test_active_device_requires_patient
- PASS TestActivityAndDevices::test_duplicate_serial_rejected
- PASS TestForeignKeys::test_vital_for_missing_patient_rejected
- PASS TestForeignKeys::test_activity_for_missing_patient_rejected
- PASS TestForeignKeys::test_care_team_for_missing_user_rejected
- PASS TestForeignKeys::test_vital_with_unknown_device_rejected
- PASS TestForeignKeys::test_relationships_navigate_both_ways
- PASS TestForeignKeys::test_deleting_patient_cascades_to_monitoring_data
- PASS TestForeignKeys::test_user_who_entered_readings_cannot_be_deleted
- PASS TestAuditLog::test_audit_rows_cannot_be_updated_or_deleted

### test_repositories.py

- PASS TestPatientRepository::test_create_adds_two_care_team_members
- PASS TestPatientRepository::test_create_rejects_non_physician_supervisor
- PASS TestPatientRepository::test_create_rejects_staff_account_as_patient_login
- PASS TestPatientRepository::test_create_rejects_inactive_clinician
- PASS TestPatientRepository::test_duplicate_mrn_becomes_conflict_error
- PASS TestPatientRepository::test_check_violation_becomes_validation_error_and_session_survives
- PASS TestPatientRepository::test_model_validator_error_becomes_validation_error
- PASS TestPatientRepository::test_get_missing_raises_not_found
- PASS TestPatientRepository::test_list_scoped_to_clinician_care_team
- PASS TestPatientRepository::test_future_dated_assignment_grants_no_access
- PASS TestPatientRepository::test_list_filters_status_sort_and_paginates
- PASS TestPatientRepository::test_search_matches_name_or_mrn_case_insensitively
- PASS TestPatientRepository::test_update_reports_changed_columns_only
- PASS TestPatientRepository::test_soft_delete_hides_and_withdraws
- PASS TestPatientRepository::test_hard_delete_logs_warning
- PASS TestPatientRepository::test_create_is_logged
- PASS TestVitalSignRepository::test_create_assesses_quality
- PASS TestVitalSignRepository::test_manual_reading_records_author
- PASS TestVitalSignRepository::test_manual_reading_without_author_rejected
- PASS TestVitalSignRepository::test_device_reading_requires_device
- PASS TestVitalSignRepository::test_device_must_belong_to_patient
- PASS TestVitalSignRepository::test_inactive_device_rejected
- PASS TestVitalSignRepository::test_create_updates_device_last_sync
- PASS TestVitalSignRepository::test_duplicate_idempotency_key_is_conflict
- PASS TestVitalSignRepository::test_bulk_create_counts_duplicates_suspect_and_rejected
- PASS TestVitalSignRepository::test_bulk_create_accepts_mixed_measurement_types
- PASS TestVitalSignRepository::test_bulk_create_rejects_manual_rows
- PASS TestVitalSignRepository::test_list_filters_by_date_range_context_metric_quality
- PASS TestVitalSignRepository::test_end_is_exclusive
- PASS TestVitalSignRepository::test_invalid_ranges_rejected[delta0-after start]
- PASS TestVitalSignRepository::test_invalid_ranges_rejected[delta1-92 days]
- PASS TestVitalSignRepository::test_latest_ignores_suspect_readings
- PASS TestVitalSignRepository::test_daily_summary_aggregates_valid_readings_per_day
- PASS TestVitalSignRepository::test_update_only_context_and_quality
- PASS TestVitalSignRepository::test_delete_and_get_missing
- PASS TestActivityRepository::test_upsert_creates_then_replaces
- PASS TestActivityRepository::test_upsert_rejects_future_date_and_foreign_device
- PASS TestActivityRepository::test_check_violation_translated
- PASS TestActivityRepository::test_list_range_summary_and_delete
- PASS TestActivityRepository::test_empty_summary
- PASS TestDeviceRepository::test_register_list_get
- PASS TestDeviceRepository::test_duplicate_serial_conflict
- PASS TestUserAndAuditRepositories::test_email_lookup_is_case_insensitive
- PASS TestUserAndAuditRepositories::test_failed_logins_lock_account
- PASS TestUserAndAuditRepositories::test_sessions_revoke
- PASS TestUserAndAuditRepositories::test_duplicate_email_conflict
- PASS TestUserAndAuditRepositories::test_get_missing_user
- PASS TestUserAndAuditRepositories::test_audit_record_and_filter
- PASS TestErrorTranslation::test_operational_error_becomes_503_and_is_logged
- PASS TestErrorTranslation::test_unknown_foreign_key_message

### test_schemas_security.py

- PASS TestPatientSchemas::test_valid
- PASS TestPatientSchemas::test_invalid[override0]
- PASS TestPatientSchemas::test_invalid[override1]
- PASS TestPatientSchemas::test_invalid[override2]
- PASS TestPatientSchemas::test_invalid[override3]
- PASS TestPatientSchemas::test_invalid[override4]
- PASS TestPatientSchemas::test_invalid[override5]
- PASS TestPatientSchemas::test_invalid[override6]
- PASS TestPatientSchemas::test_invalid[override7]
- PASS TestPatientSchemas::test_invalid[override8]
- PASS TestPatientSchemas::test_invalid[override9]
- PASS TestPatientSchemas::test_invalid[override10]
- PASS TestPatientSchemas::test_invalid[override11]
- PASS TestPatientSchemas::test_update_is_partial_and_checks_date_order
- PASS TestMonitoringSchemas::test_valid
- PASS TestMonitoringSchemas::test_invalid[override0]
- PASS TestMonitoringSchemas::test_invalid[override1]
- PASS TestMonitoringSchemas::test_invalid[override2]
- PASS TestMonitoringSchemas::test_invalid[override3]
- PASS TestMonitoringSchemas::test_invalid[override4]
- PASS TestMonitoringSchemas::test_invalid[override5]
- PASS TestMonitoringSchemas::test_invalid[override6]
- PASS TestMonitoringSchemas::test_invalid[override7]
- PASS TestMonitoringSchemas::test_invalid[override8]
- PASS TestMonitoringSchemas::test_small_clock_skew_allowed
- PASS TestMonitoringSchemas::test_batch_size_limits
- PASS TestMonitoringSchemas::test_activity_minutes_fit_in_day
- PASS TestPasswords::test_hash_and_verify
- PASS TestPasswords::test_hashes_are_salted
- PASS TestPasswords::test_overlong_password_refused
- PASS TestTokens::test_round_trip
- PASS TestTokens::test_tampered_token_rejected
- PASS TestTokens::test_none_algorithm_rejected
- PASS TestTokens::test_expired_token_rejected
- PASS TestTokens::test_wrong_audience_rejected
- PASS TestTokens::test_refresh_tokens_are_random_and_hashed
- PASS TestTotpAndLimiter::test_rfc6238_reference_vector
- PASS TestTotpAndLimiter::test_verify_window
- PASS TestTotpAndLimiter::test_limiter_blocks_after_limit
- PASS test_unknown_email_dummy_hash_uses_configured_cost

### test_migrations.py

- PASS test_upgrade_head_matches_models
- PASS test_schema_update_0002_adds_device_registry
- PASS test_downgrade_to_base_and_back
- PASS test_schema_update_0003_adds_alerting

### test_api_auth.py

- PASS test_login_returns_tokens_and_profile
- PASS test_patient_refresh_lifetime_is_seven_days
- PASS test_bad_password_and_unknown_email_look_identical
- PASS test_five_failures_lock_the_account
- PASS test_inactive_account_cannot_log_in
- PASS test_mfa_required_when_enabled
- PASS test_login_is_audited_without_password
- PASS test_rate_limit_returns_429_with_retry_after
- PASS test_refresh_rotates_and_detects_reuse
- PASS test_refresh_with_unknown_token
- PASS test_logout_revokes_access_token_immediately
- PASS test_missing_garbage_and_stale_role_tokens
- PASS test_deactivated_user_token_stops_working

### test_api_patients.py

- PASS TestCreate::test_clinician_creates_patient
- PASS TestCreate::test_duplicate_mrn_409
- PASS TestCreate::test_validation_errors_list_each_field
- PASS TestCreate::test_unknown_field_rejected
- PASS TestCreate::test_supervisor_must_be_physician
- PASS TestCreate::test_patients_and_it_cannot_create[robert_login]
- PASS TestCreate::test_patients_and_it_cannot_create[it]
- PASS TestReadAndScope::test_get_matrix[robert_login-robert-200]
- PASS TestReadAndScope::test_get_matrix[robert_login-linda-404]
- PASS TestReadAndScope::test_get_matrix[dana-robert-200]
- PASS TestReadAndScope::test_get_matrix[dana-thomas-404]
- PASS TestReadAndScope::test_get_matrix[marcus-thomas-200]
- PASS TestReadAndScope::test_get_matrix[marcus-robert-404]
- PASS TestReadAndScope::test_get_matrix[raman-thomas-200]
- PASS TestReadAndScope::test_get_matrix[admin-thomas-200]
- PASS TestReadAndScope::test_get_matrix[it-robert-403]
- PASS TestReadAndScope::test_out_of_scope_is_404_and_audited_as_denied
- PASS TestReadAndScope::test_missing_patient_404
- PASS TestReadAndScope::test_malformed_id_422
- PASS TestReadAndScope::test_list_is_scoped_and_paginated
- PASS TestReadAndScope::test_list_filters_and_sort
- PASS TestReadAndScope::test_page_size_capped
- PASS TestReadAndScope::test_patients_cannot_list
- PASS TestReadAndScope::test_search_in_body_and_scoped
- PASS TestUpdateDelete::test_clinician_updates_and_audit_stores_column_names_only
- PASS TestUpdateDelete::test_patient_may_edit_contact_fields_only
- PASS TestUpdateDelete::test_rule_violation_on_update_is_422
- PASS TestUpdateDelete::test_graduate_requires_date
- PASS TestUpdateDelete::test_only_admin_soft_deletes

### test_api_monitoring.py

- PASS TestVitalCollection::test_patient_app_posts_reading
- PASS TestVitalCollection::test_suspect_value_stored_and_flagged
- PASS TestVitalCollection::test_invalid_readings_422_with_field[override0-heart_rate]
- PASS TestVitalCollection::test_invalid_readings_422_with_field[override1-context]
- PASS TestVitalCollection::test_invalid_readings_422_with_field[override2-recorded_at]
- PASS TestVitalCollection::test_bp_order_rule
- PASS TestVitalCollection::test_future_reading_rejected
- PASS TestVitalCollection::test_foreign_device_rejected
- PASS TestVitalCollection::test_duplicate_idempotency_key_409
- PASS TestVitalCollection::test_clinician_manual_entry_records_author
- PASS TestVitalCollection::test_patient_cannot_post_manual
- PASS TestVitalCollection::test_write_scope[robert_login-linda-404]
- PASS TestVitalCollection::test_write_scope[marcus-robert-404]
- PASS TestVitalCollection::test_write_scope[admin-robert-403]
- PASS TestVitalCollection::test_write_scope[it-robert-403]
- PASS TestVitalCollection::test_batch_upload_and_safe_replay
- PASS TestVitalCollection::test_batch_with_mixed_measurements
- PASS TestVitalCollection::test_batch_limits
- PASS TestVitalQueries::test_default_window_is_last_24_hours
- PASS TestVitalQueries::test_filters
- PASS TestVitalQueries::test_range_validation
- PASS TestVitalQueries::test_latest_and_daily_summary
- PASS TestVitalQueries::test_reads_are_audited_with_row_counts
- PASS TestVitalQueries::test_get_patch_delete_single_reading
- PASS TestActivityAndDevices::test_put_creates_201_then_replaces_200
- PASS TestActivityAndDevices::test_invalid_activity
- PASS TestActivityAndDevices::test_history_summary_and_scope
- PASS TestActivityAndDevices::test_delete_is_clinician_only
- PASS TestActivityAndDevices::test_devices
- PASS TestCrossCutting::test_health
- PASS TestCrossCutting::test_request_id_echoed_and_security_headers
- PASS TestCrossCutting::test_unknown_route_problem_json
- PASS TestCrossCutting::test_unhandled_error_is_500_without_internals
- PASS TestCrossCutting::test_openapi_documents_errors_and_security

### test_alert_engine.py

- PASS test_critical_hr_above_prescribed_ceiling
- PASS test_same_value_patient_specific
- PASS test_single_spike_filtered
- PASS test_consecutive_window
- PASS test_context_filters
- PASS test_suspect_never_alerts
- PASS test_override_precedence
- PASS test_default_without_prescription
- PASS test_spo2_low
- PASS test_bp_rules
- PASS test_comparators_and_resolver_order
- PASS test_repeats_absorbed
- PASS test_suppression_window
- PASS test_critical_never_suppressed
- PASS test_masking
- PASS test_storm_cap
- PASS test_low_goes_to_digest
- PASS test_escalation_ladder
- PASS test_ack_stops_escalation
- PASS test_policy_levels
- PASS test_resolution_rules
- PASS test_alert_events_are_append_only
- PASS test_prescription_versions
- PASS test_override_rejected_for_prescription_rules

### test_alert_patterns.py

- PASS test_missed_sessions
- PASS test_zone_minutes_decline
- PASS test_resting_hr_rise
- PASS test_steps_decline
- PASS test_data_gap
- PASS test_control_patient_completely_silent
- PASS test_insufficient_data
- PASS test_repeated_pattern_runs_do_not_duplicate
- PASS test_pattern_titles_are_readable

### test_notifications.py

- PASS test_payload_and_minimum_necessary
- PASS test_dispatch_logs_delivery
- PASS test_retry_then_fail
- PASS test_digest_groups_messages
- PASS test_critical_first
- PASS test_dashboard_channel_targets_one_user
- PASS test_sms_requires_phone_and_digest_text

### test_api_alerts.py

- PASS test_batch_raises_alert
- PASS test_evaluation_failure_never_loses_readings
- PASS test_worklist
- PASS test_acknowledge
- PASS test_ack_permissions[robert_login-403]
- PASS test_ack_permissions[admin-403]
- PASS test_ack_permissions[it-403]
- PASS test_ack_permissions[marcus-404]
- PASS test_resolve_via_api
- PASS test_history_search
- PASS test_detail_timeline
- PASS test_metrics
- PASS test_rule_changes
- PASS test_prescription_endpoint
- PASS test_patient_thresholds
- PASS test_policy_updates
- PASS test_activity_upload_triggers_patterns
- PASS test_jobs_endpoint_and_notifications
- PASS test_alert_status_enum_and_health

### test_realtime.py

- PASS test_push_reading_and_alert
- PASS test_ticket_rules
- PASS test_access_token_auth_for_non_browser_clients
- PASS test_scope_filtering
- PASS test_subscription_narrows_vitals
- PASS test_notification_goes_to_recipient
- PASS test_broker_drops_oldest_for_slow_clients
- PASS test_workers_dispatch_on_wake
