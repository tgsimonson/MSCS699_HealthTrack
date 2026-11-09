# HealthTrack Phase 3 test results

Generated 2026-11-09T04:57:24+00:00 on macOS-26.5.1-arm64-arm-64bit, Python 3.12.13.

## Summary

| Database | Tests | Passed | Failed | Errors | Skipped | Duration (s) |
|---|---|---|---|---|---|---|
| sqlite | 237 | 237 | 0 | 0 | 0 | 5.65 |

Line coverage of `app/`: **97.8%** (1746 of 1786 statements). Target from requirement NFR-16: 80%.

## Results by area (sqlite)

| Test module | What it covers | Passed | Failed | Skipped |
|---|---|---|---|---|
| `test_models.py` | SQLAlchemy models: field constraints, foreign keys, invalid data | 68 | 0 | 0 |
| `test_repositories.py` | Data access layer: CRUD, filtering, pagination, errors, logging | 50 | 0 | 0 |
| `test_schemas_security.py` | Request validation schemas and security primitives | 40 | 0 | 0 |
| `test_migrations.py` | Alembic migrations: create, schema update, downgrade, drift | 3 | 0 | 0 |
| `test_api_auth.py` | Auth endpoints: login, lockout, MFA, refresh rotation, logout | 13 | 0 | 0 |
| `test_api_patients.py` | Patient endpoints: CRUD, search, role and scope matrix, audit | 29 | 0 | 0 |
| `test_api_monitoring.py` | Vital sign, activity, and device endpoints; error handling | 34 | 0 | 0 |

## Failures

None. Every test passed.

## Coverage by module

| Module | Statements | Missed | Coverage |
|---|---|---|---|
| `app/__init__.py` | 1 | 0 | 100% |
| `app/api/__init__.py` | 0 | 0 | 100% |
| `app/api/deps.py` | 60 | 2 | 97% |
| `app/api/handlers.py` | 41 | 1 | 98% |
| `app/api/responses.py` | 15 | 0 | 100% |
| `app/api/routes/__init__.py` | 0 | 0 | 100% |
| `app/api/routes/activity.py` | 57 | 1 | 98% |
| `app/api/routes/auth.py` | 85 | 1 | 99% |
| `app/api/routes/patients.py` | 52 | 0 | 100% |
| `app/api/routes/vitals.py` | 82 | 1 | 99% |
| `app/config.py` | 40 | 2 | 95% |
| `app/db.py` | 34 | 9 | 74% |
| `app/errors.py` | 31 | 0 | 100% |
| `app/logging_config.py` | 36 | 2 | 94% |
| `app/main.py` | 59 | 1 | 98% |
| `app/models/__init__.py` | 6 | 0 | 100% |
| `app/models/audit.py` | 27 | 1 | 96% |
| `app/models/base.py` | 31 | 0 | 100% |
| `app/models/enums.py` | 70 | 0 | 100% |
| `app/models/monitoring.py` | 72 | 0 | 100% |
| `app/models/patient.py` | 86 | 0 | 100% |
| `app/models/user.py` | 43 | 2 | 95% |
| `app/repositories/__init__.py` | 5 | 0 | 100% |
| `app/repositories/audit.py` | 34 | 0 | 100% |
| `app/repositories/base.py` | 75 | 8 | 89% |
| `app/repositories/monitoring.py` | 210 | 2 | 99% |
| `app/repositories/patients.py` | 98 | 2 | 98% |
| `app/repositories/users.py` | 62 | 3 | 95% |
| `app/schemas/__init__.py` | 0 | 0 | 100% |
| `app/schemas/auth.py` | 24 | 0 | 100% |
| `app/schemas/common.py` | 30 | 0 | 100% |
| `app/schemas/monitoring.py` | 127 | 0 | 100% |
| `app/schemas/patient.py` | 110 | 1 | 99% |
| `app/security.py` | 83 | 1 | 99% |

## Slowest tests

| Test | Seconds |
|---|---|
| `test_api_monitoring::test_openapi_documents_errors_and_security` | 0.252 |
| `test_migrations::test_downgrade_to_base_and_back` | 0.237 |
| `test_api_patients::test_clinician_creates_patient` | 0.128 |
| `test_migrations::test_upgrade_head_matches_models` | 0.124 |
| `test_api_monitoring::test_default_window_is_last_24_hours` | 0.088 |
| `test_api_monitoring::test_get_patch_delete_single_reading` | 0.088 |
| `test_api_monitoring::test_filters` | 0.086 |
| `test_migrations::test_schema_update_0002_adds_device_registry` | 0.073 |
| `test_api_monitoring::test_latest_and_daily_summary` | 0.071 |
| `test_api_monitoring::test_history_summary_and_scope` | 0.068 |

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
