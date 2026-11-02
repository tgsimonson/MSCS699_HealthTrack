-- =====================================================================
-- HealthTrack 05_validation_tests.sql
-- executable checks for constraints, domain rules, triggers, audit,
-- and row-level security. every test runs in a subtransaction and is
-- rolled back, so the sample data is unchanged afterward.
-- the script exits with an error if any test fails.
-- =====================================================================

SET search_path = healthtrack, public;
\set QUIET on
\pset footer off

CREATE TEMP TABLE test_results (n serial, area text, name text, passed boolean, detail text);

-- t(area, name, statement, check_query, expected_sqlstate, as_user, as_role)
--   expected_sqlstate set   -> statement must fail with that SQLSTATE
--   expected_sqlstate null  -> statement runs, then check_query must return true
--   as_user/as_role set     -> runs as the API database role with that request context
CREATE FUNCTION pg_temp.t(p_area text, p_name text, p_stmt text, p_check text DEFAULT NULL,
                          p_state text DEFAULT NULL, p_user uuid DEFAULT NULL, p_role text DEFAULT NULL)
RETURNS void LANGUAGE plpgsql AS $f$
DECLARE
    ok  boolean := false;
    got text;
BEGIN
    BEGIN
        IF p_user IS NOT NULL THEN
            PERFORM set_config('app.user_id', p_user::text, true);
            PERFORM set_config('app.user_role', p_role, true);
            EXECUTE 'SET LOCAL ROLE healthtrack_api';
        END IF;
        IF p_stmt IS NOT NULL THEN EXECUTE p_stmt; END IF;
        IF p_state IS NULL THEN
            EXECUTE p_check INTO ok;
            got := 'check returned ' || coalesce(ok::text, 'null');
        END IF;
        RAISE EXCEPTION USING ERRCODE = 'P0099', MESSAGE = 'rollback test';
    EXCEPTION WHEN OTHERS THEN
        IF SQLSTATE = 'P0099' THEN
            IF p_state IS NOT NULL THEN ok := false; got := 'expected ' || p_state || ', no error raised'; END IF;
        ELSE
            got := SQLSTATE || ' ' || SQLERRM;
            ok  := (p_state IS NOT NULL AND SQLSTATE = p_state);
        END IF;
    END;
    INSERT INTO test_results (area, name, passed, detail) VALUES (p_area, p_name, ok, got);
END $f$;

-- sample identifiers
\set dana '00000000-0000-4000-a000-000000000001'
\set marcus '00000000-0000-4000-a000-000000000002'
\set raman '00000000-0000-4000-a000-000000000003'
\set karen '00000000-0000-4000-a000-000000000005'
\set jordan '00000000-0000-4000-a000-000000000006'
\set robert '00000000-0000-4000-a000-000000000011'

-- ---------------------------------------------------------------- vitals
SELECT pg_temp.t('vital_signs', 'heart rate of 400 bpm is rejected (hard limit 20 to 300)',
  $$INSERT INTO vital_signs (patient_id, device_id, recorded_at, context, heart_rate)
    VALUES ('00000000-0000-4000-b000-000000000001', '00000000-0000-4000-c000-000000000011', '2026-10-20 09:00-06', 'rest', 400)$$,
  NULL, '23514');
SELECT pg_temp.t('vital_signs', 'systolic pressure below diastolic is rejected',
  $$INSERT INTO vital_signs (patient_id, device_id, recorded_at, context, systolic_bp, diastolic_bp)
    VALUES ('00000000-0000-4000-b000-000000000001', '00000000-0000-4000-c000-000000000012', '2026-10-20 09:00-06', 'rest', 80, 90)$$,
  NULL, '23514');
SELECT pg_temp.t('vital_signs', 'blood pressure must include both systolic and diastolic',
  $$INSERT INTO vital_signs (patient_id, device_id, recorded_at, context, systolic_bp)
    VALUES ('00000000-0000-4000-b000-000000000001', '00000000-0000-4000-c000-000000000012', '2026-10-20 09:00-06', 'rest', 130)$$,
  NULL, '23514');
SELECT pg_temp.t('vital_signs', 'reading with no measurement is rejected',
  $$INSERT INTO vital_signs (patient_id, device_id, recorded_at, context)
    VALUES ('00000000-0000-4000-b000-000000000001', '00000000-0000-4000-c000-000000000011', '2026-10-20 09:00-06', 'rest')$$,
  NULL, '23514');
SELECT pg_temp.t('vital_signs', 'manual reading without entered_by is rejected',
  $$INSERT INTO vital_signs (patient_id, recorded_at, context, heart_rate, source)
    VALUES ('00000000-0000-4000-b000-000000000001', '2026-10-20 09:00-06', 'rest', 70, 'manual')$$,
  NULL, '23514');
SELECT pg_temp.t('vital_signs', 'device reading without device_id is rejected',
  $$INSERT INTO vital_signs (patient_id, recorded_at, context, heart_rate)
    VALUES ('00000000-0000-4000-b000-000000000001', '2026-10-20 09:00-06', 'rest', 70)$$,
  NULL, '23514');
SELECT pg_temp.t('vital_signs', 'reading timestamped in the future is rejected',
  $$INSERT INTO vital_signs (patient_id, device_id, recorded_at, context, heart_rate)
    VALUES ('00000000-0000-4000-b000-000000000001', '00000000-0000-4000-c000-000000000011', now() + interval '1 day', 'rest', 70)$$,
  NULL, '22007');
SELECT pg_temp.t('vital_signs', 'replayed upload with the same idempotency key is rejected',
  $$INSERT INTO vital_signs (patient_id, device_id, recorded_at, context, heart_rate, idempotency_key)
    SELECT patient_id, device_id, recorded_at, context, heart_rate, idempotency_key
      FROM vital_signs WHERE idempotency_key IS NOT NULL ORDER BY vital_id LIMIT 1$$,
  NULL, '23505');
SELECT pg_temp.t('vital_signs', 'possible but unlikely heart rate (245) is stored and flagged suspect',
  $$INSERT INTO vital_signs (patient_id, device_id, recorded_at, context, heart_rate, idempotency_key)
    VALUES ('00000000-0000-4000-b000-000000000001', '00000000-0000-4000-c000-000000000011', '2026-10-20 09:00-06', 'exercise', 245, 'test-suspect-0001')$$,
  $$SELECT quality = 'suspect' FROM vital_signs WHERE idempotency_key = 'test-suspect-0001'$$);
SELECT pg_temp.t('vital_signs', 'narrow pulse pressure (120/110) is flagged suspect',
  $$INSERT INTO vital_signs (patient_id, device_id, recorded_at, context, systolic_bp, diastolic_bp, idempotency_key)
    VALUES ('00000000-0000-4000-b000-000000000001', '00000000-0000-4000-c000-000000000012', '2026-10-20 09:00-06', 'rest', 120, 110, 'test-suspect-0002')$$,
  $$SELECT quality = 'suspect' FROM vital_signs WHERE idempotency_key = 'test-suspect-0002'$$);

-- ---------------------------------------------------------------- patients
SELECT pg_temp.t('patients', 'patient younger than 18 at the qualifying event is rejected',
  $$INSERT INTO patients (mrn, first_name, last_name, date_of_birth, sex, qualifying_event, qualifying_event_date,
                          referral_date, clinical_risk_category)
    VALUES ('HT-199999', 'Test', 'Minor', '2010-01-01', 'male', 'pci', '2026-10-01', '2026-10-02', 'low')$$,
  NULL, '23514');
SELECT pg_temp.t('patients', 'active patient cannot be high risk (home program is low or moderate only)',
  $$UPDATE patients SET clinical_risk_category = 'high' WHERE mrn = 'HT-100001'$$, NULL, '23514');
SELECT pg_temp.t('patients', 'graduated status requires a graduation date',
  $$UPDATE patients SET program_status = 'graduated' WHERE mrn = 'HT-100001'$$, NULL, '23514');
SELECT pg_temp.t('patients', 'active status requires an enrollment date',
  $$UPDATE patients SET program_status = 'active' WHERE mrn = 'HT-100007'$$, NULL, '23514');
SELECT pg_temp.t('patients', 'malformed MRN is rejected',
  $$UPDATE patients SET mrn = 'ht 1' WHERE mrn = 'HT-100001'$$, NULL, '23514');
SELECT pg_temp.t('patients', 'patient login must be a patient account, not staff',
  $$UPDATE patients SET user_id = '00000000-0000-4000-a000-000000000001' WHERE mrn = 'HT-100007'$$, NULL, '23514');

-- ---------------------------------------------------------------- care team
SELECT pg_temp.t('care_team', 'a second current primary clinician is rejected',
  $$INSERT INTO care_team_assignments (patient_id, user_id, team_role)
    VALUES ('00000000-0000-4000-b000-000000000001', '00000000-0000-4000-a000-000000000002', 'primary_clinician')$$,
  NULL, '23505');
SELECT pg_temp.t('care_team', 'supervising physician must hold the physician role',
  $$INSERT INTO care_team_assignments (patient_id, user_id, team_role)
    VALUES ('00000000-0000-4000-b000-000000000007', '00000000-0000-4000-a000-000000000001', 'supervising_physician')$$,
  NULL, '23514');

-- ---------------------------------------------------------------- prescriptions
SELECT pg_temp.t('prescriptions', 'target zone minimum above maximum is rejected',
  $$INSERT INTO exercise_prescriptions (patient_id, resting_hr_baseline, target_hr_min, target_hr_max, hr_ceiling,
                                        sessions_per_week, session_minutes, prescribed_by)
    VALUES ('00000000-0000-4000-b000-000000000001', 68, 120, 100, 130, 3, 30, '00000000-0000-4000-a000-000000000003')$$,
  NULL, '23514');
SELECT pg_temp.t('prescriptions', 'prescription signed by a non-physician is rejected',
  $$INSERT INTO exercise_prescriptions (patient_id, resting_hr_baseline, target_hr_min, target_hr_max, hr_ceiling,
                                        sessions_per_week, session_minutes, prescribed_by)
    VALUES ('00000000-0000-4000-b000-000000000001', 68, 100, 120, 130, 3, 30, '00000000-0000-4000-a000-000000000001')$$,
  NULL, '23514');
SELECT pg_temp.t('prescriptions', 'new prescription becomes version 2 and closes version 1',
  $$INSERT INTO exercise_prescriptions (patient_id, resting_hr_baseline, target_hr_min, target_hr_max, hr_ceiling,
                                        sessions_per_week, session_minutes, prescribed_by)
    VALUES ('00000000-0000-4000-b000-000000000001', 66, 102, 122, 132, 3, 35, '00000000-0000-4000-a000-000000000003')$$,
  $$SELECT count(*) FILTER (WHERE effective_to IS NULL) = 1
       AND max(version) = 2
       AND bool_and(effective_to IS NOT NULL) FILTER (WHERE version = 1)
      FROM exercise_prescriptions WHERE patient_id = '00000000-0000-4000-b000-000000000001'$$);

-- ---------------------------------------------------------------- sessions
SELECT pg_temp.t('sessions', 'perceived exertion outside the Borg 6 to 20 scale is rejected',
  $$UPDATE exercise_sessions SET rpe = 25
     WHERE session_id = (SELECT session_id FROM exercise_sessions ORDER BY started_at LIMIT 1)$$, NULL, '23514');
SELECT pg_temp.t('sessions', 'overlapping sessions for the same patient are rejected',
  $$INSERT INTO exercise_sessions (patient_id, prescription_id, status, started_at, ended_at)
    SELECT patient_id, prescription_id, 'completed', started_at + interval '5 minutes', ended_at + interval '5 minutes'
      FROM exercise_sessions WHERE patient_id = '00000000-0000-4000-b000-000000000001' ORDER BY started_at LIMIT 1$$,
  NULL, '23P01');
SELECT pg_temp.t('sessions', 'minutes in zone longer than the session is rejected',
  $$UPDATE exercise_sessions SET minutes_in_zone = 500
     WHERE session_id = (SELECT session_id FROM exercise_sessions ORDER BY started_at LIMIT 1)$$, NULL, '23514');
SELECT pg_temp.t('sessions', 'completed session must have an end time',
  $$UPDATE exercise_sessions SET ended_at = NULL
     WHERE session_id = (SELECT session_id FROM exercise_sessions ORDER BY started_at LIMIT 1)$$, NULL, '23514');

-- ---------------------------------------------------------------- daily activity
SELECT pg_temp.t('daily_activity', 'active plus sedentary minutes over 24 hours is rejected',
  $$UPDATE daily_activity SET active_minutes = 900, sedentary_minutes = 900
     WHERE patient_id = '00000000-0000-4000-b000-000000000001' AND activity_date = '2026-10-10'$$, NULL, '23514');

-- ---------------------------------------------------------------- appointments
SELECT pg_temp.t('appointments', 'double-booking a clinician is rejected',
  $$INSERT INTO appointments (patient_id, clinician_id, appointment_type, scheduled_start, scheduled_end)
    VALUES ('00000000-0000-4000-b000-000000000008', '00000000-0000-4000-a000-000000000001', 'ad_hoc',
            '2026-10-29 10:05-06', '2026-10-29 10:25-06')$$, NULL, '23P01');
SELECT pg_temp.t('appointments', 'cancelling without a reason is rejected',
  $$UPDATE appointments SET status = 'cancelled'
     WHERE patient_id = '00000000-0000-4000-b000-000000000007'$$, NULL, '23514');
SELECT pg_temp.t('appointments', 'a second graduation assessment is rejected',
  $$INSERT INTO appointments (patient_id, clinician_id, appointment_type, scheduled_start, scheduled_end)
    VALUES ('00000000-0000-4000-b000-000000000006', '00000000-0000-4000-a000-000000000002', 'graduation_assessment',
            '2026-11-10 13:00-07', '2026-11-10 14:00-07')$$, NULL, '23505');
SELECT pg_temp.t('appointments', 'appointment shorter than 10 minutes is rejected',
  $$INSERT INTO appointments (patient_id, clinician_id, appointment_type, scheduled_start, scheduled_end)
    VALUES ('00000000-0000-4000-b000-000000000008', '00000000-0000-4000-a000-000000000001', 'ad_hoc',
            '2026-11-10 13:00-07', '2026-11-10 13:05-07')$$, NULL, '23514');

-- ---------------------------------------------------------------- alerts
SELECT pg_temp.t('alerts', 'critical rule cannot be given a suppression window',
  $$UPDATE alert_rules SET suppression_minutes = 30 WHERE rule_code = 'HR_ABOVE_CEILING'$$, NULL, '23514');
SELECT pg_temp.t('alerts', 'duplicate open alert for the same condition is rejected',
  $$INSERT INTO alerts (patient_id, rule_id, severity, title, dedup_key)
    SELECT patient_id, rule_id, severity, title, dedup_key FROM alerts
     WHERE alert_id = '00000000-0000-4000-f000-000000000002'$$, NULL, '23505');
SELECT pg_temp.t('alerts', 'a patient account cannot acknowledge an alert',
  $$UPDATE alerts SET status = 'acknowledged', acknowledged_by = '00000000-0000-4000-a000-000000000013',
                      acknowledged_at = now()
     WHERE alert_id = '00000000-0000-4000-f000-000000000005'$$, NULL, '23514');
SELECT pg_temp.t('alerts', 'resolving without a resolution note is rejected',
  $$UPDATE alerts SET status = 'resolved', resolved_by = '00000000-0000-4000-a000-000000000001', resolved_at = now()
     WHERE alert_id = '00000000-0000-4000-f000-000000000005'$$, NULL, '23514');
SELECT pg_temp.t('alerts', 'acknowledging an alert writes an alert_events history row',
  $$UPDATE alerts SET status = 'acknowledged', acknowledged_by = '00000000-0000-4000-a000-000000000001',
                      acknowledged_at = '2026-10-25 08:00-06'
     WHERE alert_id = '00000000-0000-4000-f000-000000000005'$$,
  $$SELECT count(*) = 2 AND bool_or(event_type = 'acknowledged') FROM alert_events
     WHERE alert_id = '00000000-0000-4000-f000-000000000005'$$);
SELECT pg_temp.t('alerts', 'only low-severity alerts may be delivered as a digest',
  $$UPDATE escalation_policies SET deliver_as_digest = true WHERE severity = 'critical'$$, NULL, '23514');
SELECT pg_temp.t('alerts', 'notification payload missing required keys is rejected',
  $$INSERT INTO notifications (alert_id, recipient_user_id, channel, payload)
    VALUES ('00000000-0000-4000-f000-000000000005', '00000000-0000-4000-a000-000000000001', 'email', '{"title": "x"}')$$,
  NULL, '23514');
SELECT pg_temp.t('alerts', 'alert history rows cannot be edited',
  $$UPDATE alert_events SET note = 'changed'$$, NULL, '42501');

-- ---------------------------------------------------------------- risk
SELECT pg_temp.t('risk', 'risk level is derived from the score bands (score 80 stored as high)',
  $$INSERT INTO risk_assessments (patient_id, model_name, model_version, window_start, window_end, risk_score, risk_level)
    VALUES ('00000000-0000-4000-b000-000000000001', 'htrisk-gbm', '0.1.0', now() - interval '14 days', now(), 80, 'low')$$,
  $$SELECT risk_level = 'high' FROM risk_assessments WHERE risk_score = 80$$);
SELECT pg_temp.t('risk', 'risk score above 100 is rejected',
  $$UPDATE risk_assessments SET risk_score = 101
     WHERE assessment_id = '00000000-0000-4000-9000-000000000011'$$, NULL, '23514');
SELECT pg_temp.t('risk', 'approving a recommendation requires a reviewer',
  $$UPDATE care_recommendations SET status = 'approved' WHERE status = 'pending_review'$$, NULL, '23514');
SELECT pg_temp.t('risk', 'a patient account cannot review a recommendation',
  $$UPDATE care_recommendations SET status = 'approved', reviewed_by = '00000000-0000-4000-a000-000000000014',
                                    reviewed_at = now()
     WHERE patient_id = '00000000-0000-4000-b000-000000000004'$$, NULL, '23514');

-- ---------------------------------------------------------------- audit
SELECT pg_temp.t('audit', 'audit log rows cannot be updated',
  $$UPDATE audit_log SET outcome = 'success' WHERE outcome = 'denied'$$, NULL, '42501');
SELECT pg_temp.t('audit', 'audit log rows cannot be deleted',
  $$DELETE FROM audit_log$$, NULL, '42501');
SELECT pg_temp.t('audit', 'audit log cannot be truncated',
  $$TRUNCATE audit_log$$, NULL, '42501');
SELECT pg_temp.t('audit', 'a PHI update is audited by column name without storing the value',
  $$SELECT set_config('app.user_id', '00000000-0000-4000-a000-000000000001', true);
    UPDATE patients SET phone = '+17195559999' WHERE mrn = 'HT-100001'$$,
  $$SELECT details -> 'changed_columns' ? 'phone' AND details::text NOT LIKE '%5559999%'
           AND actor_user_id = '00000000-0000-4000-a000-000000000001'
      FROM audit_log ORDER BY audit_id DESC LIMIT 1$$);

-- ---------------------------------------------------------------- row-level security
SELECT pg_temp.t('row_level_security', 'clinician Dana sees only her 4 current patients', NULL,
  $$SELECT count(*) = 4 FROM patients$$, NULL, :'dana', 'clinician');
SELECT pg_temp.t('row_level_security', 'clinician Marcus sees 3 patients (ended coverage does not count)', NULL,
  $$SELECT count(*) = 3 FROM patients$$, NULL, :'marcus', 'clinician');
SELECT pg_temp.t('row_level_security', 'clinician cannot read vitals of a patient outside her care team', NULL,
  $$SELECT count(*) = 0 FROM vital_signs WHERE patient_id = '00000000-0000-4000-b000-000000000005'$$, NULL, :'dana', 'clinician');
SELECT pg_temp.t('row_level_security', 'clinician cannot write vitals for a patient outside her care team',
  $$INSERT INTO vital_signs (patient_id, recorded_at, context, heart_rate, source, entered_by)
    VALUES ('00000000-0000-4000-b000-000000000005', '2026-10-20 09:00-06', 'rest', 70, 'manual',
            '00000000-0000-4000-a000-000000000001')$$, NULL, '42501', :'dana', 'clinician');
SELECT pg_temp.t('row_level_security', 'patient Robert sees only his own record and readings', NULL,
  $$SELECT (SELECT count(*) FROM patients) = 1
       AND (SELECT count(*) FROM vital_signs WHERE patient_id <> '00000000-0000-4000-b000-000000000001') = 0
       AND (SELECT count(*) FROM vital_signs) > 0$$, NULL, :'robert', 'patient');
SELECT pg_temp.t('row_level_security', 'administrator sees patient demographics but no vital signs', NULL,
  $$SELECT (SELECT count(*) FROM patients) = 8 AND (SELECT count(*) FROM vital_signs) = 0$$, NULL, :'karen', 'admin');
SELECT pg_temp.t('row_level_security', 'IT administrator sees no patient data', NULL,
  $$SELECT (SELECT count(*) FROM patients) = 0 AND (SELECT count(*) FROM vital_signs) = 0
       AND (SELECT count(*) FROM alerts) = 0$$, NULL, :'jordan', 'it_admin');
SELECT pg_temp.t('row_level_security', 'administrator still sees aggregate program metrics', NULL,
  $$SELECT patients_total = 8 FROM v_program_metrics$$, NULL, :'karen', 'admin');
SELECT pg_temp.t('row_level_security', 'worklist view respects row-level security for clinicians', NULL,
  $$SELECT count(*) = 4 FROM v_patient_overview$$, NULL, :'dana', 'clinician');
SELECT pg_temp.t('row_level_security', 'clinicians cannot read the audit log', NULL,
  $$SELECT count(*) = 0 FROM audit_log$$, NULL, :'dana', 'clinician');
SELECT pg_temp.t('row_level_security', 'API role cannot update the audit log even with a valid context',
  $$UPDATE audit_log SET outcome = 'success'$$, NULL, '42501', :'karen', 'admin');
SELECT pg_temp.t('row_level_security', 'no request context means no patient rows', NULL,
  $$SELECT count(*) = 0 FROM patients$$, NULL, '00000000-0000-0000-0000-000000000000', '');

-- ---------------------------------------------------------------- report
\pset footer on
\echo
\echo '== validation test results'
SELECT n AS "#", area, name, CASE WHEN passed THEN 'PASS' ELSE 'FAIL' END AS result,
       CASE WHEN passed THEN '' ELSE detail END AS failure_detail
  FROM test_results ORDER BY n;

SELECT count(*) AS total, count(*) FILTER (WHERE passed) AS passed, count(*) FILTER (WHERE NOT passed) AS failed
  FROM test_results;

DO $$
DECLARE f int;
BEGIN
    SELECT count(*) INTO f FROM test_results WHERE NOT passed;
    IF f > 0 THEN RAISE EXCEPTION '% validation test(s) failed', f; END IF;
END $$;
