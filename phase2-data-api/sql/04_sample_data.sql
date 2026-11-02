-- =====================================================================
-- HealthTrack 04_sample_data.sql
-- synthetic test data: every person and record below is fictitious
-- covers stable, improving, declining, non-adherent, exertion-spike,
-- graduated, referred, and paused patient profiles
-- deterministic: setseed() makes every run produce identical readings
-- =====================================================================
-- mock login for every sample account: HealthTrack-Demo-2026!
-- =====================================================================

BEGIN;
SET search_path = healthtrack, public;
DO $$ BEGIN PERFORM setseed(0.2026); END $$;

-- ---------------------------------------------------------------------
-- users: staff (a000...0x) and patient logins (a000...1x)
-- ---------------------------------------------------------------------
INSERT INTO users (user_id, email, password_hash, role, first_name, last_name, credentials, phone, mfa_enabled) VALUES
('00000000-0000-4000-a000-000000000001', 'dana.whitfield@healthtrack.example',  crypt('HealthTrack-Demo-2026!', gen_salt('bf', 10)), 'clinician', 'Dana',   'Whitfield', 'RN',  '+17195550101', true),
('00000000-0000-4000-a000-000000000002', 'marcus.lee@healthtrack.example',      crypt('HealthTrack-Demo-2026!', gen_salt('bf', 10)), 'clinician', 'Marcus', 'Lee',       'CEP', '+17195550102', true),
('00000000-0000-4000-a000-000000000003', 'priya.raman@healthtrack.example',     crypt('HealthTrack-Demo-2026!', gen_salt('bf', 10)), 'physician', 'Priya',  'Raman',     'MD',  '+17195550103', true),
('00000000-0000-4000-a000-000000000004', 'samuel.ortiz@healthtrack.example',    crypt('HealthTrack-Demo-2026!', gen_salt('bf', 10)), 'physician', 'Samuel', 'Ortiz',     'MD',  '+17195550104', true),
('00000000-0000-4000-a000-000000000005', 'karen.holt@healthtrack.example',      crypt('HealthTrack-Demo-2026!', gen_salt('bf', 10)), 'admin',     'Karen',  'Holt',      NULL,  '+17195550105', true),
('00000000-0000-4000-a000-000000000006', 'jordan.pike@healthtrack.example',     crypt('HealthTrack-Demo-2026!', gen_salt('bf', 10)), 'it_admin',  'Jordan', 'Pike',      NULL,  '+17195550106', true),
('00000000-0000-4000-a000-000000000011', 'r.alvarez@mail.example',  crypt('HealthTrack-Demo-2026!', gen_salt('bf', 10)), 'patient', 'Robert', 'Alvarez',  NULL, '+17195550111', false),
('00000000-0000-4000-a000-000000000012', 'l.chen@mail.example',     crypt('HealthTrack-Demo-2026!', gen_salt('bf', 10)), 'patient', 'Linda',  'Chen',     NULL, '+17195550112', false),
('00000000-0000-4000-a000-000000000013', 'j.whitaker@mail.example', crypt('HealthTrack-Demo-2026!', gen_salt('bf', 10)), 'patient', 'James',  'Whitaker', NULL, '+17195550113', false),
('00000000-0000-4000-a000-000000000014', 'm.gonzales@mail.example', crypt('HealthTrack-Demo-2026!', gen_salt('bf', 10)), 'patient', 'Maria',  'Gonzales', NULL, '+17195550114', false),
('00000000-0000-4000-a000-000000000015', 't.reed@mail.example',     crypt('HealthTrack-Demo-2026!', gen_salt('bf', 10)), 'patient', 'Thomas', 'Reed',     NULL, '+17195550115', false),
('00000000-0000-4000-a000-000000000016', 'a.brooks@mail.example',   crypt('HealthTrack-Demo-2026!', gen_salt('bf', 10)), 'patient', 'Angela', 'Brooks',   NULL, '+17195550116', false);

-- ---------------------------------------------------------------------
-- patients (b000...0x)
-- ---------------------------------------------------------------------
INSERT INTO patients (patient_id, user_id, mrn, first_name, last_name, date_of_birth, sex, phone, email, postal_code,
                      qualifying_event, qualifying_event_date, referral_date, enrollment_date, graduation_date,
                      program_status, clinical_risk_category, created_by) VALUES
('00000000-0000-4000-b000-000000000001', '00000000-0000-4000-a000-000000000011', 'HT-100001', 'Robert', 'Alvarez',  '1962-03-14', 'male',   '+17195550111', 'r.alvarez@mail.example',  '80920', 'myocardial_infarction',    '2026-09-08', '2026-09-15', '2026-09-28', NULL,         'active',    'low',      '00000000-0000-4000-a000-000000000005'),
('00000000-0000-4000-b000-000000000002', '00000000-0000-4000-a000-000000000012', 'HT-100002', 'Linda',  'Chen',     '1968-07-02', 'female', '+17195550112', 'l.chen@mail.example',     '80918', 'pci',                      '2026-09-10', '2026-09-17', '2026-09-28', NULL,         'active',    'moderate', '00000000-0000-4000-a000-000000000005'),
('00000000-0000-4000-b000-000000000003', '00000000-0000-4000-a000-000000000013', 'HT-100003', 'James',  'Whitaker', '1955-11-23', 'male',   '+17195550113', 'j.whitaker@mail.example', '80906', 'cabg',                     '2026-08-24', '2026-09-08', '2026-09-21', NULL,         'active',    'moderate', '00000000-0000-4000-a000-000000000005'),
('00000000-0000-4000-b000-000000000004', '00000000-0000-4000-a000-000000000014', 'HT-100004', 'Maria',  'Gonzales', '1974-05-09', 'female', '+17195550114', 'm.gonzales@mail.example', '80916', 'pci',                      '2026-09-14', '2026-09-22', '2026-10-01', NULL,         'active',    'low',      '00000000-0000-4000-a000-000000000005'),
('00000000-0000-4000-b000-000000000005', '00000000-0000-4000-a000-000000000015', 'HT-100005', 'Thomas', 'Reed',     '1959-01-30', 'male',   '+17195550115', 't.reed@mail.example',     '80921', 'valve_surgery',            '2026-08-31', '2026-09-21', '2026-10-01', NULL,         'active',    'moderate', '00000000-0000-4000-a000-000000000005'),
('00000000-0000-4000-b000-000000000006', '00000000-0000-4000-a000-000000000016', 'HT-100006', 'Angela', 'Brooks',   '1966-09-18', 'female', '+17195550116', 'a.brooks@mail.example',   '80919', 'stable_angina',            '2026-06-02', '2026-06-10', '2026-06-22', '2026-10-02', 'graduated', 'low',      '00000000-0000-4000-a000-000000000005'),
('00000000-0000-4000-b000-000000000007', NULL,                                   'HT-100007', 'Kevin',  'O''Neil',  '1971-04-27', 'male',   '+17195550117', NULL,                      '80910', 'myocardial_infarction',    '2026-10-14', '2026-10-22', NULL,         NULL,         'referred',  'low',      '00000000-0000-4000-a000-000000000005'),
('00000000-0000-4000-b000-000000000008', NULL,                                   'HT-100008', 'Susan',  'Patel',    '1957-12-05', 'female', '+17195550118', NULL,                      '80917', 'heart_failure_reduced_ef', '2026-08-03', '2026-08-12', '2026-08-24', NULL,         'paused',    'moderate', '00000000-0000-4000-a000-000000000005');

INSERT INTO caregivers (patient_id, full_name, relationship, phone, is_emergency_contact, receives_alerts) VALUES
('00000000-0000-4000-b000-000000000001', 'Elena Alvarez',  'spouse',   '+17195550121', true, false),
('00000000-0000-4000-b000-000000000003', 'Rachel Whitaker','daughter', '+17195550123', true, true),
('00000000-0000-4000-b000-000000000005', 'Carol Reed',     'spouse',   '+17195550125', true, false);

-- ---------------------------------------------------------------------
-- care teams
-- ---------------------------------------------------------------------
INSERT INTO care_team_assignments (patient_id, user_id, team_role, start_date, end_date, assigned_by) VALUES
('00000000-0000-4000-b000-000000000001', '00000000-0000-4000-a000-000000000001', 'primary_clinician',     '2026-09-15', NULL, '00000000-0000-4000-a000-000000000005'),
('00000000-0000-4000-b000-000000000001', '00000000-0000-4000-a000-000000000003', 'supervising_physician', '2026-09-15', NULL, '00000000-0000-4000-a000-000000000005'),
('00000000-0000-4000-b000-000000000002', '00000000-0000-4000-a000-000000000001', 'primary_clinician',     '2026-09-17', NULL, '00000000-0000-4000-a000-000000000005'),
('00000000-0000-4000-b000-000000000002', '00000000-0000-4000-a000-000000000003', 'supervising_physician', '2026-09-17', NULL, '00000000-0000-4000-a000-000000000005'),
('00000000-0000-4000-b000-000000000003', '00000000-0000-4000-a000-000000000001', 'primary_clinician',     '2026-09-08', NULL, '00000000-0000-4000-a000-000000000005'),
('00000000-0000-4000-b000-000000000003', '00000000-0000-4000-a000-000000000003', 'supervising_physician', '2026-09-08', NULL, '00000000-0000-4000-a000-000000000005'),
('00000000-0000-4000-b000-000000000004', '00000000-0000-4000-a000-000000000002', 'primary_clinician',     '2026-09-22', NULL, '00000000-0000-4000-a000-000000000005'),
('00000000-0000-4000-b000-000000000004', '00000000-0000-4000-a000-000000000003', 'supervising_physician', '2026-09-22', NULL, '00000000-0000-4000-a000-000000000005'),
('00000000-0000-4000-b000-000000000005', '00000000-0000-4000-a000-000000000002', 'primary_clinician',     '2026-09-21', NULL, '00000000-0000-4000-a000-000000000005'),
('00000000-0000-4000-b000-000000000005', '00000000-0000-4000-a000-000000000004', 'supervising_physician', '2026-09-21', NULL, '00000000-0000-4000-a000-000000000005'),
('00000000-0000-4000-b000-000000000006', '00000000-0000-4000-a000-000000000002', 'primary_clinician',     '2026-06-10', '2026-10-02', '00000000-0000-4000-a000-000000000005'),
('00000000-0000-4000-b000-000000000006', '00000000-0000-4000-a000-000000000004', 'supervising_physician', '2026-06-10', '2026-10-02', '00000000-0000-4000-a000-000000000005'),
('00000000-0000-4000-b000-000000000007', '00000000-0000-4000-a000-000000000002', 'primary_clinician',     '2026-10-22', NULL, '00000000-0000-4000-a000-000000000005'),
('00000000-0000-4000-b000-000000000007', '00000000-0000-4000-a000-000000000004', 'supervising_physician', '2026-10-22', NULL, '00000000-0000-4000-a000-000000000005'),
('00000000-0000-4000-b000-000000000008', '00000000-0000-4000-a000-000000000001', 'primary_clinician',     '2026-08-12', NULL, '00000000-0000-4000-a000-000000000005'),
('00000000-0000-4000-b000-000000000008', '00000000-0000-4000-a000-000000000003', 'supervising_physician', '2026-08-12', NULL, '00000000-0000-4000-a000-000000000005'),
-- vacation coverage: Marcus covers Linda Chen for two weeks
('00000000-0000-4000-b000-000000000002', '00000000-0000-4000-a000-000000000002', 'covering_clinician',    '2026-10-05', '2026-10-16', '00000000-0000-4000-a000-000000000005');

-- ---------------------------------------------------------------------
-- exercise prescriptions (Linda Chen has two versions: zone raised at week 4)
-- ---------------------------------------------------------------------
INSERT INTO exercise_prescriptions (prescription_id, patient_id, resting_hr_baseline, target_hr_min, target_hr_max, hr_ceiling,
                                    max_exercise_sbp, min_spo2, sessions_per_week, session_minutes, effective_from, prescribed_by, notes) VALUES
('00000000-0000-4000-d000-000000000001', '00000000-0000-4000-b000-000000000001', 68, 98,  118, 130, 200, 90, 3, 30, '2026-09-28 12:00-06', '00000000-0000-4000-a000-000000000003', 'Treadmill walking; zone from symptom-limited exercise test.'),
('00000000-0000-4000-d000-000000000002', '00000000-0000-4000-b000-000000000002', 74, 100, 120, 132, 200, 90, 3, 30, '2026-09-28 12:00-06', '00000000-0000-4000-a000-000000000003', 'Stationary bike.'),
('00000000-0000-4000-d000-000000000003', '00000000-0000-4000-b000-000000000003', 70, 95,  112, 125, 190, 90, 3, 30, '2026-09-21 12:00-06', '00000000-0000-4000-a000-000000000003', 'Post-CABG; sternal precautions, no upper-body resistance.'),
('00000000-0000-4000-d000-000000000004', '00000000-0000-4000-b000-000000000004', 74, 100, 122, 135, 200, 90, 3, 30, '2026-10-01 12:00-06', '00000000-0000-4000-a000-000000000003', 'Walking program.'),
('00000000-0000-4000-d000-000000000005', '00000000-0000-4000-b000-000000000005', 66, 95,  115, 128, 180, 90, 3, 30, '2026-10-01 12:00-06', '00000000-0000-4000-a000-000000000004', 'Post-valve replacement; on beta-blocker, conservative ceiling.'),
('00000000-0000-4000-d000-000000000006', '00000000-0000-4000-b000-000000000006', 70, 100, 125, 138, 200, 90, 3, 40, '2026-06-22 12:00-06', '00000000-0000-4000-a000-000000000004', 'Graduated program.'),
('00000000-0000-4000-d000-000000000008', '00000000-0000-4000-b000-000000000008', 72, 92,  110, 120, 180, 92, 2, 20, '2026-08-24 12:00-06', '00000000-0000-4000-a000-000000000003', 'HFrEF; paused pending medication titration.');
UPDATE exercise_prescriptions SET effective_to = '2026-10-02 12:00-06' WHERE prescription_id = '00000000-0000-4000-d000-000000000006';
-- version 2 for Linda Chen closes version 1 automatically
INSERT INTO exercise_prescriptions (prescription_id, patient_id, resting_hr_baseline, target_hr_min, target_hr_max, hr_ceiling,
                                    max_exercise_sbp, min_spo2, sessions_per_week, session_minutes, effective_from, prescribed_by, notes) VALUES
('00000000-0000-4000-d000-000000000012', '00000000-0000-4000-b000-000000000002', 72, 105, 125, 135, 200, 90, 3, 30, '2026-10-19 12:00-06', '00000000-0000-4000-a000-000000000003', 'Progressed after week-3 review: tolerating zone well.');

-- ---------------------------------------------------------------------
-- devices (c000...pn: patient p, device n)
-- ---------------------------------------------------------------------
INSERT INTO devices (device_id, patient_id, device_type, manufacturer, model, serial_number, firmware_version, status, assigned_at, last_sync_at)
SELECT ('00000000-0000-4000-c000-0000000000' || p || n)::uuid,
       ('00000000-0000-4000-b000-00000000000' || p)::uuid,
       d.dtype, d.mfr, d.model, d.prefix || '-' || p || n || '0417', d.fw, 'active',
       '2026-09-28 10:00-06', '2026-10-25 20:00-06'
  FROM generate_series(1, 5) p
 CROSS JOIN (VALUES (1, 'heart_rate_band'::device_type,     'Corvane', 'HB-2 Chest Strap',  'HB2', '3.4.1'),
                    (2, 'blood_pressure_cuff'::device_type, 'Corvane', 'BP-Connect 5',      'BPC', '2.0.7'),
                    (3, 'pulse_oximeter'::device_type,      'Corvane', 'OX-1 Fingertip',    'OX1', '1.9.0')) d(n, dtype, mfr, model, prefix, fw);
-- spare unassigned inventory
INSERT INTO devices (device_id, device_type, manufacturer, model, serial_number, firmware_version, status) VALUES
('00000000-0000-4000-c000-000000000901', 'heart_rate_band', 'Corvane', 'HB-2 Chest Strap', 'HB2-9010417', '3.4.1', 'inactive');

-- ---------------------------------------------------------------------
-- simulation profiles for the five active patients
-- f runs from 0 at Oct 5 to 1 at Oct 25 and moves each value from start to end
-- ---------------------------------------------------------------------
CREATE TEMP TABLE sim (
    p int, patient_id uuid, offset_min int,
    rest_hr0 numeric, rest_hr1 numeric, ex_hr0 numeric, ex_hr1 numeric,
    ex_min0 numeric, ex_min1 numeric, rpe0 numeric, rpe1 numeric,
    sbp numeric, dbp numeric, spo2 numeric, steps0 numeric, steps1 numeric
) ON COMMIT DROP;
INSERT INTO sim VALUES
(1, '00000000-0000-4000-b000-000000000001',  0, 68, 66, 108, 109, 20, 20, 12, 12, 128, 78, 97, 7200, 7600),  -- stable, adherent
(2, '00000000-0000-4000-b000-000000000002', 30, 74, 71, 108, 116, 18, 22, 13, 12, 132, 82, 97, 5800, 7000),  -- improving
(3, '00000000-0000-4000-b000-000000000003', 60, 70, 80, 104, 109, 20, 10, 12, 15, 138, 84, 95, 6200, 3400),  -- declining tolerance
(4, '00000000-0000-4000-b000-000000000004',  0, 74, 76, 110, 110, 18, 18, 13, 13, 126, 80, 98, 3000, 2200),  -- non-adherent
(5, '00000000-0000-4000-b000-000000000005', 30, 66, 67, 104, 106, 20, 22, 12, 13, 124, 76, 97, 6800, 7200);  -- exertion spike Oct 21

CREATE TEMP TABLE sim_sessions ON COMMIT DROP AS
SELECT s.p, s.patient_id, d::date AS session_date,
       (d::date - DATE '2026-10-05') / 20.0                                   AS f,
       ((d::date + time '09:00') + make_interval(mins => s.offset_min)) AT TIME ZONE 'America/Denver' AS started_at,
       round(s.ex_min0 + (s.ex_min1 - s.ex_min0) * (d::date - DATE '2026-10-05') / 20.0)::int AS ex_min,
       gen_random_uuid()                                                     AS session_id
  FROM sim s
 CROSS JOIN generate_series(DATE '2026-10-05', DATE '2026-10-23', interval '1 day') d
 WHERE extract(isodow FROM d) IN (1, 3, 5)
   -- Maria Gonzales stops attending after Oct 14
   AND NOT (s.p = 4 AND d::date > DATE '2026-10-14');

INSERT INTO exercise_sessions (session_id, patient_id, prescription_id, device_id, session_type, status,
                               started_at, ended_at, rpe)
SELECT ss.session_id, ss.patient_id, rx.prescription_id,
       ('00000000-0000-4000-c000-0000000000' || ss.p || '1')::uuid,
       'aerobic',
       CASE WHEN 10 + ss.ex_min < rx.session_minutes - 5 THEN 'partial' ELSE 'completed' END::session_status,
       ss.started_at,
       ss.started_at + make_interval(mins => 10 + ss.ex_min),
       round(s.rpe0 + (s.rpe1 - s.rpe0) * ss.f)
  FROM sim_sessions ss
  JOIN sim s USING (p)
  JOIN exercise_prescriptions rx ON rx.patient_id = ss.patient_id
   AND rx.effective_from <= ss.started_at
   AND (rx.effective_to IS NULL OR rx.effective_to > ss.started_at);

-- minute-by-minute heart rate from the chest strap: 5 min warmup, exercise, 5 min cooldown
INSERT INTO vital_signs (patient_id, device_id, session_id, recorded_at, received_at, context, heart_rate, source, idempotency_key)
SELECT ss.patient_id,
       ('00000000-0000-4000-c000-0000000000' || ss.p || '1')::uuid,
       ss.session_id,
       ss.started_at + make_interval(mins => m),
       ss.started_at + make_interval(mins => 10 + ss.ex_min + 2),
       CASE WHEN m < 5 THEN 'warmup' WHEN m < 5 + ss.ex_min THEN 'exercise' ELSE 'cooldown' END::reading_context,
       CASE
           -- Thomas Reed, Oct 21: heart rate climbs past his 128 bpm ceiling for three minutes
           WHEN ss.p = 5 AND ss.session_date = DATE '2026-10-21' AND m BETWEEN 17 AND 19
                THEN (ARRAY[133, 138, 141])[m - 16]
           WHEN m < 5 THEN round(rh + (eh - rh) * (m + 1) / 6.0 + (random() - 0.5) * 4)
           WHEN m < 5 + ss.ex_min THEN round(eh + 3 * sin(m / 3.0) + (random() - 0.5) * 8)
           ELSE round(eh - (eh - rh - 10) * (m - 4 - ss.ex_min) / 5.0 + (random() - 0.5) * 4)
       END::smallint,
       'device',
       'hb-' || ss.p || '-' || to_char(ss.started_at + make_interval(mins => m), 'YYYYMMDDHH24MI')
  FROM sim_sessions ss
  JOIN sim s USING (p)
 CROSS JOIN LATERAL (SELECT s.rest_hr0 + (s.rest_hr1 - s.rest_hr0) * ss.f AS rh,
                            s.ex_hr0   + (s.ex_hr1   - s.ex_hr0)   * ss.f AS eh) lvl
 CROSS JOIN LATERAL generate_series(0, 9 + ss.ex_min) m
 ORDER BY ss.p, ss.started_at, m;

-- pre- and post-session blood pressure (cuff) and SpO2 (oximeter)
INSERT INTO vital_signs (patient_id, device_id, session_id, recorded_at, received_at, context,
                         heart_rate, systolic_bp, diastolic_bp, source, idempotency_key)
SELECT ss.patient_id, ('00000000-0000-4000-c000-0000000000' || ss.p || '2')::uuid, ss.session_id,
       t.at, t.at + interval '1 minute', t.ctx,
       round(t.hr)::smallint,
       round(t.sbp + (random() - 0.5) * 8)::smallint,
       round(t.dbp + (random() - 0.5) * 6)::smallint,
       'device', 'bp-' || ss.p || '-' || to_char(t.at, 'YYYYMMDDHH24MI')
  FROM sim_sessions ss
  JOIN sim s USING (p)
 CROSS JOIN LATERAL (VALUES
       (ss.started_at - interval '3 minutes', 'rest'::reading_context,
        s.rest_hr0 + (s.rest_hr1 - s.rest_hr0) * ss.f + 4, s.sbp, s.dbp),
       (ss.started_at + make_interval(mins => 10 + ss.ex_min + 3), 'recovery'::reading_context,
        s.rest_hr0 + (s.rest_hr1 - s.rest_hr0) * ss.f + 14,
        s.sbp + CASE WHEN ss.p = 5 AND ss.session_date = DATE '2026-10-21' THEN 50 ELSE 12 END,
        s.dbp + 2)) t(at, ctx, hr, sbp, dbp);

INSERT INTO vital_signs (patient_id, device_id, session_id, recorded_at, received_at, context, spo2, source, idempotency_key)
SELECT ss.patient_id, ('00000000-0000-4000-c000-0000000000' || ss.p || '3')::uuid, ss.session_id,
       t.at, t.at + interval '1 minute', t.ctx,
       least(100, round(s.spo2 + (random() - 0.5) * 2 - t.drop))::smallint,
       'device', 'ox-' || ss.p || '-' || to_char(t.at, 'YYYYMMDDHH24MI')
  FROM sim_sessions ss
  JOIN sim s USING (p)
 CROSS JOIN LATERAL (VALUES
       (ss.started_at - interval '2 minutes', 'rest'::reading_context, 0),
       (ss.started_at + make_interval(mins => 10 + ss.ex_min + 4), 'recovery'::reading_context, 1)) t(at, ctx, drop);

-- morning resting readings at 07:00 local, every day Oct 5 to 25
-- (Maria Gonzales stops syncing after Oct 16)
INSERT INTO vital_signs (patient_id, device_id, recorded_at, received_at, context,
                         heart_rate, systolic_bp, diastolic_bp, source, idempotency_key)
SELECT s.patient_id, ('00000000-0000-4000-c000-0000000000' || s.p || '2')::uuid,
       (d::date + time '07:00') AT TIME ZONE 'America/Denver',
       (d::date + time '07:01') AT TIME ZONE 'America/Denver',
       'rest',
       round(s.rest_hr0 + (s.rest_hr1 - s.rest_hr0) * (d::date - DATE '2026-10-05') / 20.0 + (random() - 0.5) * 4)::smallint,
       round(s.sbp + (random() - 0.5) * 10)::smallint,
       round(s.dbp + (random() - 0.5) * 6)::smallint,
       'device', 'bp-' || s.p || '-' || to_char(d, 'YYYYMMDD') || '0700'
  FROM sim s
 CROSS JOIN generate_series(DATE '2026-10-05', DATE '2026-10-25', interval '1 day') d
 WHERE NOT (s.p = 4 AND d::date > DATE '2026-10-16');

-- one manual entry by a clinician during a telehealth check-in
INSERT INTO vital_signs (patient_id, recorded_at, received_at, context, heart_rate, systolic_bp, diastolic_bp,
                         source, entered_by)
VALUES ('00000000-0000-4000-b000-000000000003', '2026-10-22 11:05-06', '2026-10-22 11:06-06', 'rest',
        81, 146, 88, 'manual', '00000000-0000-4000-a000-000000000001');

-- derive avg HR, peak HR, minutes in zone, minutes above ceiling from the readings
DO $$ BEGIN PERFORM healthtrack.compute_session_metrics(session_id) FROM healthtrack.exercise_sessions; END $$;

-- daily activity from the activity tracker
INSERT INTO daily_activity (patient_id, activity_date, steps, active_minutes, sedentary_minutes, resting_hr, source, device_id)
SELECT s.patient_id, d::date,
       round(s.steps0 + (s.steps1 - s.steps0) * (d::date - DATE '2026-10-05') / 20.0 + (random() - 0.5) * 1200)::int,
       round((s.steps0 + (s.steps1 - s.steps0) * (d::date - DATE '2026-10-05') / 20.0) / 150 + (random() - 0.5) * 10)::smallint,
       round(560 + (random() - 0.5) * 80)::smallint,
       round(s.rest_hr0 + (s.rest_hr1 - s.rest_hr0) * (d::date - DATE '2026-10-05') / 20.0 - 2 + (random() - 0.5) * 3)::smallint,
       'device', ('00000000-0000-4000-c000-0000000000' || s.p || '1')::uuid
  FROM sim s
 CROSS JOIN generate_series(DATE '2026-10-05', DATE '2026-10-25', interval '1 day') d
 WHERE NOT (s.p = 4 AND d::date > DATE '2026-10-16');

-- post-session effort and symptom reports
INSERT INTO symptom_reports (patient_id, session_id, reported_at, symptom, severity, description)
SELECT ss.patient_id, ss.session_id, ss.started_at + make_interval(mins => 10 + ss.ex_min + 6), x.symptom, x.sev, x.descr
  FROM sim_sessions ss
  JOIN (VALUES (3, DATE '2026-10-19', 'unusual_fatigue'::symptom_type,     4, 'Tired for the rest of the afternoon.'),
               (3, DATE '2026-10-23', 'shortness_of_breath'::symptom_type, 5, 'Short of breath on the stairs after session.'),
               (2, DATE '2026-10-07', 'leg_pain'::symptom_type,            2, 'Mild calf soreness.')) x(p, d, symptom, sev, descr)
    ON x.p = ss.p AND x.d = ss.session_date;

-- ---------------------------------------------------------------------
-- appointments
-- ---------------------------------------------------------------------
INSERT INTO appointments (patient_id, clinician_id, appointment_type, modality, status, scheduled_start, scheduled_end, notes, created_by) VALUES
('00000000-0000-4000-b000-000000000001', '00000000-0000-4000-a000-000000000001', 'intake', 'in_person', 'completed', '2026-09-28 09:00-06', '2026-09-28 10:00-06', 'Device kit issued and paired.', '00000000-0000-4000-a000-000000000005'),
('00000000-0000-4000-b000-000000000002', '00000000-0000-4000-a000-000000000001', 'intake', 'in_person', 'completed', '2026-09-28 10:30-06', '2026-09-28 11:30-06', 'Device kit issued and paired.', '00000000-0000-4000-a000-000000000005'),
('00000000-0000-4000-b000-000000000003', '00000000-0000-4000-a000-000000000001', 'intake', 'in_person', 'completed', '2026-09-21 09:00-06', '2026-09-21 10:00-06', 'Device kit issued and paired.', '00000000-0000-4000-a000-000000000005'),
('00000000-0000-4000-b000-000000000004', '00000000-0000-4000-a000-000000000002', 'intake', 'in_person', 'completed', '2026-10-01 09:00-06', '2026-10-01 10:00-06', 'Device kit issued and paired.', '00000000-0000-4000-a000-000000000005'),
('00000000-0000-4000-b000-000000000005', '00000000-0000-4000-a000-000000000002', 'intake', 'in_person', 'completed', '2026-10-01 10:30-06', '2026-10-01 11:30-06', 'Device kit issued and paired.', '00000000-0000-4000-a000-000000000005'),
('00000000-0000-4000-b000-000000000006', '00000000-0000-4000-a000-000000000002', 'graduation_assessment', 'in_person', 'completed', '2026-10-02 13:00-06', '2026-10-02 14:00-06', 'Six-minute walk improved 22 percent. Graduated.', '00000000-0000-4000-a000-000000000005'),
('00000000-0000-4000-b000-000000000007', '00000000-0000-4000-a000-000000000002', 'intake', 'in_person', 'scheduled', '2026-11-02 09:00-07', '2026-11-02 10:00-07', NULL, '00000000-0000-4000-a000-000000000005');

-- weekly telehealth check-ins on Thursdays; Maria Gonzales missed Oct 22
INSERT INTO appointments (patient_id, clinician_id, appointment_type, modality, status, scheduled_start, scheduled_end, created_by)
SELECT x.patient_id, x.clinician_id, 'weekly_checkin', 'telehealth_video',
       CASE WHEN d::date > DATE '2026-10-28' THEN 'scheduled'
            WHEN x.patient_id = '00000000-0000-4000-b000-000000000004' AND d::date = DATE '2026-10-22' THEN 'missed'
            ELSE 'completed' END::appointment_status,
       (d::date + x.t) AT TIME ZONE 'America/Denver',
       (d::date + x.t + interval '20 minutes') AT TIME ZONE 'America/Denver',
       x.clinician_id
  FROM generate_series(DATE '2026-10-08', DATE '2026-10-29', interval '7 days') d
 CROSS JOIN (VALUES ('00000000-0000-4000-b000-000000000001'::uuid, '00000000-0000-4000-a000-000000000001'::uuid, time '10:00'),
                    ('00000000-0000-4000-b000-000000000002'::uuid, '00000000-0000-4000-a000-000000000001'::uuid, time '10:30'),
                    ('00000000-0000-4000-b000-000000000003'::uuid, '00000000-0000-4000-a000-000000000001'::uuid, time '11:00'),
                    ('00000000-0000-4000-b000-000000000004'::uuid, '00000000-0000-4000-a000-000000000002'::uuid, time '10:00'),
                    ('00000000-0000-4000-b000-000000000005'::uuid, '00000000-0000-4000-a000-000000000002'::uuid, time '10:30')) x(patient_id, clinician_id, t);

-- ---------------------------------------------------------------------
-- alert configuration
-- ---------------------------------------------------------------------
INSERT INTO alert_rules (rule_id, rule_code, name, description, rule_type, metric, comparator, default_threshold,
                         applies_to_context, evaluation_window_minutes, consecutive_required, severity,
                         suppression_minutes, is_customizable) VALUES
('00000000-0000-4000-e000-000000000001', 'HR_ABOVE_CEILING',     'Heart rate above prescribed ceiling', 'Exercise heart rate above the patient''s prescription hr_ceiling for consecutive readings. Default applies only when no prescription exists.', 'threshold', 'heart_rate', '>', 150, '{warmup,exercise,cooldown}', 0, 2, 'critical', 0, false),
('00000000-0000-4000-e000-000000000002', 'SPO2_LOW',             'Low oxygen saturation',               'SpO2 below the prescription min_spo2 on consecutive readings.', 'threshold', 'spo2', '<', 90, NULL, 0, 2, 'critical', 0, false),
('00000000-0000-4000-e000-000000000003', 'EXERCISE_SBP_HIGH',    'Exercise blood pressure high',        'Systolic pressure during or right after exercise above prescription max_exercise_sbp.', 'threshold', 'systolic_bp', '>', 200, '{exercise,cooldown,recovery}', 0, 1, 'high', 30, false),
('00000000-0000-4000-e000-000000000004', 'RESTING_SBP_HIGH',     'Resting systolic pressure high',      'Resting systolic pressure at or above threshold.', 'threshold', 'systolic_bp', '>=', 160, '{rest}', 0, 1, 'moderate', 720, true),
('00000000-0000-4000-e000-000000000005', 'RESTING_SBP_LOW',      'Resting systolic pressure low',       'Resting systolic pressure below threshold.', 'threshold', 'systolic_bp', '<', 90, '{rest}', 0, 1, 'high', 240, true),
('00000000-0000-4000-e000-000000000006', 'RESTING_HR_HIGH',      'Resting heart rate high',             'Resting heart rate above threshold on consecutive readings.', 'threshold', 'heart_rate', '>', 100, '{rest}', 0, 2, 'moderate', 720, true),
('00000000-0000-4000-e000-000000000007', 'RESTING_HR_RISE',      'Resting heart rate trending up',      '7-day average resting heart rate exceeds the prescription baseline by more than the threshold (bpm).', 'pattern', 'resting_hr_7d_minus_baseline', '>', 8, NULL, 10080, 1, 'moderate', 1440, true),
('00000000-0000-4000-e000-000000000008', 'MISSED_SESSIONS',      'Consecutive missed sessions',         'Number of consecutive scheduled sessions with no session record.', 'pattern', 'consecutive_missed_sessions', '>=', 2, NULL, 20160, 1, 'high', 1440, true),
('00000000-0000-4000-e000-000000000009', 'ZONE_MINUTES_DECLINE', 'Minutes in zone declining',           'Week-over-week change in total minutes in target zone at or below the threshold (percent).', 'pattern', 'minutes_in_zone_wow_pct', '<=', -25, NULL, 20160, 1, 'moderate', 1440, true),
('00000000-0000-4000-e000-000000000010', 'SYMPTOM_CHEST_PAIN',   'Chest pain reported',                 'Any patient report of chest pain.', 'symptom', 'symptom:chest_pain', '>=', 1, NULL, 0, 1, 'critical', 0, false),
('00000000-0000-4000-e000-000000000011', 'SYMPTOM_REPORTED',     'Significant symptom reported',        'Any other symptom reported at or above the severity threshold (0 to 10).', 'symptom', 'symptom:any', '>=', 5, NULL, 0, 1, 'high', 240, true),
('00000000-0000-4000-e000-000000000012', 'DATA_GAP',             'No data received',                    'Hours since the last reading from any device.', 'data_gap', 'hours_since_last_reading', '>=', 48, NULL, 0, 1, 'low', 1440, true);

INSERT INTO patient_alert_thresholds (patient_id, rule_id, threshold_value, reason, set_by, effective_from) VALUES
('00000000-0000-4000-b000-000000000003', '00000000-0000-4000-e000-000000000004', 150, 'Post-CABG: cardiology requests tighter resting BP control.', '00000000-0000-4000-a000-000000000003', '2026-09-21 12:00-06'),
('00000000-0000-4000-b000-000000000005', '00000000-0000-4000-e000-000000000006', 90,  'On beta-blocker; baseline resting HR in the 60s, so 90 is abnormal for him.', '00000000-0000-4000-a000-000000000004', '2026-10-01 12:00-06');

INSERT INTO escalation_policies (severity, ack_timeout_minutes, escalate_to, max_escalation_level, channels, deliver_as_digest, updated_by) VALUES
('critical', 15,   'supervising_physician', 2, '{dashboard,sms,email}', false, '00000000-0000-4000-a000-000000000004'),
('high',     60,   'supervising_physician', 2, '{dashboard,email}',     false, '00000000-0000-4000-a000-000000000004'),
('moderate', 240,  'supervising_physician', 1, '{dashboard}',           false, '00000000-0000-4000-a000-000000000004'),
('low',      1440, 'primary_clinician',     0, '{dashboard}',           true,  '00000000-0000-4000-a000-000000000004');

INSERT INTO risk_level_bands (level, min_score, max_score, color_hex, label) VALUES
('low',      0,  34,  '#2E7D5B', 'Low risk'),
('moderate', 34, 67,  '#B7862B', 'Moderate risk'),
('high',     67, 100, '#B23B3B', 'High risk');

-- ---------------------------------------------------------------------
-- alerts consistent with the readings above (history rows are written by trigger)
-- ---------------------------------------------------------------------
-- 1. Thomas Reed: heart rate above 128 ceiling on Oct 21 (critical, resolved)
INSERT INTO alerts (alert_id, patient_id, rule_id, vital_id, session_id, severity, title, triggering_values,
                    threshold_applied, dedup_key, triggered_at)
SELECT '00000000-0000-4000-f000-000000000001', v.patient_id, '00000000-0000-4000-e000-000000000001', v.vital_id, v.session_id,
       'critical', 'Heart rate 138 bpm above ceiling of 128 bpm',
       jsonb_build_object('heart_rate', array[133, 138], 'ceiling', 128, 'consecutive', 2, 'context', 'exercise'),
       128, 'HR_ABOVE_CEILING:' || v.session_id, v.recorded_at + interval '20 seconds'
  FROM vital_signs v
 WHERE v.patient_id = '00000000-0000-4000-b000-000000000005' AND v.heart_rate = 138
   AND v.recorded_at::date = DATE '2026-10-21';

-- 2. Maria Gonzales: two consecutive missed sessions (high, acknowledged, still open on worklist)
INSERT INTO alerts (alert_id, patient_id, rule_id, severity, title, triggering_values, threshold_applied, dedup_key, triggered_at) VALUES
('00000000-0000-4000-f000-000000000002', '00000000-0000-4000-b000-000000000004', '00000000-0000-4000-e000-000000000008', 'high',
 'Missed 2 consecutive sessions (Oct 16, Oct 19)', '{"missed_dates": ["2026-10-16", "2026-10-19"], "consecutive": 2}', 2,
 'MISSED_SESSIONS:streak:2026-10-16', '2026-10-19 18:00-06');

-- 3. James Whitaker: shortness of breath after Oct 23 session (high, resolved)
INSERT INTO alerts (alert_id, patient_id, rule_id, symptom_id, session_id, severity, title, triggering_values, threshold_applied, dedup_key, triggered_at)
SELECT '00000000-0000-4000-f000-000000000003', sr.patient_id, '00000000-0000-4000-e000-000000000011', sr.symptom_id, sr.session_id,
       'high', 'Shortness of breath reported, severity 5 of 10',
       jsonb_build_object('symptom', 'shortness_of_breath', 'severity', 5), 5,
       'SYMPTOM_REPORTED:' || sr.symptom_id, sr.reported_at + interval '30 seconds'
  FROM symptom_reports sr WHERE sr.symptom = 'shortness_of_breath';

-- 4. James Whitaker: minutes in zone down week over week (moderate, escalated after no ack)
INSERT INTO alerts (alert_id, patient_id, rule_id, severity, title, triggering_values, threshold_applied, dedup_key, triggered_at) VALUES
('00000000-0000-4000-f000-000000000004', '00000000-0000-4000-b000-000000000003', '00000000-0000-4000-e000-000000000009', 'moderate',
 'Minutes in target zone down 28 percent week over week', '{"week_start": "2026-10-19", "minutes_this_week": 33, "minutes_last_week": 46, "change_pct": -28}', -25,
 'ZONE_MINUTES_DECLINE:2026-10-19', '2026-10-23 21:00-06');

-- 5. James Whitaker: resting heart rate up 9 bpm over baseline (moderate, open)
INSERT INTO alerts (alert_id, patient_id, rule_id, severity, title, triggering_values, threshold_applied, dedup_key, triggered_at) VALUES
('00000000-0000-4000-f000-000000000005', '00000000-0000-4000-b000-000000000003', '00000000-0000-4000-e000-000000000007', 'moderate',
 '7-day resting heart rate 79 bpm, 9 above baseline of 70', '{"avg_resting_hr_7d": 79, "baseline": 70, "delta": 9}', 8,
 'RESTING_HR_RISE:2026-10-25', '2026-10-25 07:05-06');

-- 6. Maria Gonzales: no data for 48 hours (low, open, goes to daily digest)
INSERT INTO alerts (alert_id, patient_id, rule_id, severity, title, triggering_values, threshold_applied, dedup_key, triggered_at) VALUES
('00000000-0000-4000-f000-000000000006', '00000000-0000-4000-b000-000000000004', '00000000-0000-4000-e000-000000000012', 'low',
 'No readings received for 48 hours', '{"last_reading_at": "2026-10-16T07:00:00-06:00", "hours": 48}', 48,
 'DATA_GAP:since:2026-10-16', '2026-10-18 07:00-06');

-- workflow updates recorded under the acting clinician (alert_events and audit_log pick this up)
DO $$ BEGIN PERFORM set_config('app.user_id', '00000000-0000-4000-a000-000000000002', true),
                   set_config('app.user_role', 'clinician', true); END $$;
UPDATE alerts SET status = 'acknowledged', acknowledged_by = '00000000-0000-4000-a000-000000000002',
                  acknowledged_at = triggered_at + interval '3 minutes'
 WHERE alert_id = '00000000-0000-4000-f000-000000000001';
UPDATE alerts SET status = 'resolved', resolved_by = '00000000-0000-4000-a000-000000000002',
                  resolved_at = triggered_at + interval '22 minutes',
                  resolution_note = 'Called patient during session. Stopped exercise, no symptoms, HR back to 92 within 4 minutes. Cleared to resume Friday at lower treadmill grade; Dr. Ortiz notified.'
 WHERE alert_id = '00000000-0000-4000-f000-000000000001';
UPDATE alerts SET status = 'acknowledged', acknowledged_by = '00000000-0000-4000-a000-000000000002',
                  acknowledged_at = '2026-10-20 09:15-06'
 WHERE alert_id = '00000000-0000-4000-f000-000000000002';

DO $$ BEGIN PERFORM set_config('app.user_id', '00000000-0000-4000-a000-000000000001', true); END $$;
UPDATE alerts SET status = 'acknowledged', acknowledged_by = '00000000-0000-4000-a000-000000000001',
                  acknowledged_at = triggered_at + interval '41 minutes'
 WHERE alert_id = '00000000-0000-4000-f000-000000000003';
UPDATE alerts SET status = 'resolved', resolved_by = '00000000-0000-4000-a000-000000000001',
                  resolved_at = triggered_at + interval '55 minutes',
                  resolution_note = 'Phone assessment: resolved at rest within 10 minutes, no chest pain. Reviewed pacing on stairs; flagged for Thursday check-in.'
 WHERE alert_id = '00000000-0000-4000-f000-000000000003';

-- no acknowledgment within the 240-minute moderate timeout, so the system escalates
DO $$ BEGIN PERFORM set_config('app.user_id', '', true); END $$;
UPDATE alerts SET status = 'escalated', escalation_level = 1, escalated_at = triggered_at + interval '240 minutes'
 WHERE alert_id = '00000000-0000-4000-f000-000000000004';

INSERT INTO alert_events (alert_id, event_type, actor_user_id, occurred_at, note) VALUES
('00000000-0000-4000-f000-000000000002', 'comment', '00000000-0000-4000-a000-000000000002', '2026-10-20 09:16-06', 'Called twice, left voicemail. Will retry Thursday.');

-- notifications (payloads follow the documented notification schema)
INSERT INTO notifications (alert_id, recipient_user_id, channel, status, payload, attempts, queued_at, sent_at, delivered_at, read_at)
SELECT a.alert_id, n.recipient, n.channel, 'delivered',
       jsonb_build_object('alert_id', a.alert_id, 'patient_id', a.patient_id, 'severity', a.severity,
                          'rule_code', r.rule_code, 'title', a.title, 'triggered_at', a.triggered_at,
                          'triggering_values', a.triggering_values),
       1, a.triggered_at, a.triggered_at + interval '2 seconds', a.triggered_at + interval '5 seconds',
       a.triggered_at + interval '2 minutes'
  FROM alerts a
  JOIN alert_rules r USING (rule_id)
  JOIN (VALUES ('00000000-0000-4000-f000-000000000001'::uuid, '00000000-0000-4000-a000-000000000002'::uuid, 'dashboard'::notification_channel),
               ('00000000-0000-4000-f000-000000000001'::uuid, '00000000-0000-4000-a000-000000000002'::uuid, 'sms'::notification_channel),
               ('00000000-0000-4000-f000-000000000002'::uuid, '00000000-0000-4000-a000-000000000002'::uuid, 'dashboard'::notification_channel),
               ('00000000-0000-4000-f000-000000000002'::uuid, '00000000-0000-4000-a000-000000000002'::uuid, 'email'::notification_channel),
               ('00000000-0000-4000-f000-000000000003'::uuid, '00000000-0000-4000-a000-000000000001'::uuid, 'dashboard'::notification_channel),
               ('00000000-0000-4000-f000-000000000004'::uuid, '00000000-0000-4000-a000-000000000001'::uuid, 'dashboard'::notification_channel),
               ('00000000-0000-4000-f000-000000000004'::uuid, '00000000-0000-4000-a000-000000000003'::uuid, 'dashboard'::notification_channel),
               ('00000000-0000-4000-f000-000000000005'::uuid, '00000000-0000-4000-a000-000000000001'::uuid, 'dashboard'::notification_channel))
       n(alert_id, recipient, channel) ON n.alert_id = a.alert_id;
UPDATE notifications SET read_at = NULL, delivered_at = sent_at + interval '3 seconds'
 WHERE alert_id IN ('00000000-0000-4000-f000-000000000004', '00000000-0000-4000-f000-000000000005');

-- ---------------------------------------------------------------------
-- weekly risk assessments with explanations and recommendations
-- ---------------------------------------------------------------------
INSERT INTO risk_assessments (assessment_id, patient_id, assessed_at, model_name, model_version, window_start, window_end,
                              risk_score, risk_level, dropout_probability, decline_probability)
SELECT ('00000000-0000-4000-9000-0000000000' || x.p || w.n)::uuid,
       ('00000000-0000-4000-b000-00000000000' || x.p)::uuid,
       w.at, 'htrisk-gbm', '0.1.0', w.at - interval '14 days', w.at,
       x.scores[w.n], 'low', x.dropout[w.n], x.decline[w.n]
  FROM (VALUES (1, ARRAY[12, 10, 9],  ARRAY[0.06, 0.05, 0.04], ARRAY[0.05, 0.04, 0.04]),
               (2, ARRAY[30, 26, 22], ARRAY[0.12, 0.10, 0.08], ARRAY[0.15, 0.12, 0.10]),
               (3, ARRAY[35, 52, 71], ARRAY[0.14, 0.22, 0.31], ARRAY[0.20, 0.38, 0.57]),
               (4, ARRAY[18, 45, 72], ARRAY[0.10, 0.41, 0.68], ARRAY[0.08, 0.14, 0.21]),
               (5, ARRAY[25, 24, 41], ARRAY[0.09, 0.09, 0.12], ARRAY[0.12, 0.11, 0.33])) x(p, scores, dropout, decline)
 CROSS JOIN (VALUES (1, timestamptz '2026-10-11 23:00-06'),
                    (2, timestamptz '2026-10-18 23:00-06'),
                    (3, timestamptz '2026-10-25 23:00-06')) w(n, at);
-- risk_level above is a placeholder; the trigger sets it from risk_level_bands

INSERT INTO risk_factors (assessment_id, factor_code, label, observed_value, reference_value, contribution, rank) VALUES
('00000000-0000-4000-9000-000000000033', 'zone_minutes_trend',  'Minutes in target zone, week over week', '-28 percent',        '0 percent',      0.34, 1),
('00000000-0000-4000-9000-000000000033', 'resting_hr_delta',    '7-day resting heart rate vs baseline',   '+9 bpm',             '+0 bpm',         0.27, 2),
('00000000-0000-4000-9000-000000000033', 'rpe_trend',           'Average perceived exertion',             '15 (Borg)',          '12 (Borg)',      0.18, 3),
('00000000-0000-4000-9000-000000000033', 'symptom_reports_14d', 'Symptom reports in last 14 days',        '2',                  '0',              0.12, 4),
('00000000-0000-4000-9000-000000000043', 'missed_sessions',     'Consecutive missed sessions',            '4',                  '0',              0.46, 1),
('00000000-0000-4000-9000-000000000043', 'data_gap_hours',      'Hours since last reading',               '232',                '24',             0.22, 2),
('00000000-0000-4000-9000-000000000043', 'missed_checkin',      'Missed weekly check-in',                 'Oct 22',             'none',           0.11, 3),
('00000000-0000-4000-9000-000000000053', 'hr_ceiling_breach',   'Minutes above HR ceiling (14 days)',     '3',                  '0',              0.29, 1),
('00000000-0000-4000-9000-000000000053', 'recovery_sbp',        'Post-exercise systolic pressure',        '171 mmHg',           '136 mmHg',       0.17, 2),
('00000000-0000-4000-9000-000000000013', 'adherence_pct',       'Session adherence (14 days)',            '100 percent',        '80 percent',    -0.21, 1);

INSERT INTO care_recommendations (assessment_id, patient_id, recommendation_text, source, status, reviewed_by, reviewed_at, review_note, created_at) VALUES
('00000000-0000-4000-9000-000000000033', '00000000-0000-4000-b000-000000000003', 'Consider an earlier telehealth check-in to review fatigue, breathlessness, and medication changes.', 'system', 'approved', '00000000-0000-4000-a000-000000000003', '2026-10-26 08:10-06', 'Agree. Moved check-in to Monday; ordering BNP.', '2026-10-25 23:00-06'),
('00000000-0000-4000-9000-000000000033', '00000000-0000-4000-b000-000000000003', 'Consider reducing target session duration to 20 minutes until symptoms are reassessed.', 'system', 'pending_review', NULL, NULL, NULL, '2026-10-25 23:00-06'),
('00000000-0000-4000-9000-000000000043', '00000000-0000-4000-b000-000000000004', 'Consider outreach on barriers to attendance (schedule, transportation, device problems) and offer a caregiver call.', 'system', 'pending_review', NULL, NULL, NULL, '2026-10-25 23:00-06'),
('00000000-0000-4000-9000-000000000053', '00000000-0000-4000-b000-000000000005', 'Consider re-checking the heart rate ceiling against beta-blocker timing before sessions.', 'system', 'approved', '00000000-0000-4000-a000-000000000004', '2026-10-26 09:30-06', 'Confirmed he took his dose late on Oct 21. Reinforced timing.', '2026-10-25 23:00-06');

-- ---------------------------------------------------------------------
-- representative audit entries written by the API layer (reads and logins)
-- ---------------------------------------------------------------------
INSERT INTO audit_log (occurred_at, actor_user_id, actor_role, action, entity_type, entity_id, patient_id, outcome, ip_address, details) VALUES
('2026-10-21 09:40-06', '00000000-0000-4000-a000-000000000002', 'clinician', 'login',        'auth',        NULL, NULL, 'success', '10.20.4.17', '{"mfa": true}'),
('2026-10-21 09:51-06', '00000000-0000-4000-a000-000000000002', 'clinician', 'read',         'vital_signs', NULL, '00000000-0000-4000-b000-000000000005', 'success', '10.20.4.17', '{"endpoint": "GET /patients/{id}/vitals", "rows": 34}'),
('2026-10-21 09:52-06', '00000000-0000-4000-a000-000000000002', 'clinician', 'acknowledge',  'alerts',      '00000000-0000-4000-f000-000000000001', '00000000-0000-4000-b000-000000000005', 'success', '10.20.4.17', '{}'),
('2026-10-22 14:03-06', '00000000-0000-4000-a000-000000000001', 'clinician', 'read',         'patients',    '00000000-0000-4000-b000-000000000005', '00000000-0000-4000-b000-000000000005', 'denied',  '10.20.4.22', '{"reason": "not on care team"}'),
('2026-10-23 02:14-06', NULL,                                   NULL,        'login_failed', 'auth',        NULL, NULL, 'denied',  '203.0.113.50', '{"email": "karen.holt@healthtrack.example", "attempt": 3}'),
('2026-10-26 08:05-06', '00000000-0000-4000-a000-000000000005', 'admin',     'export',       'program_metrics', NULL, NULL, 'success', '10.20.4.30', '{"format": "csv"}');

-- refresh-token sessions (only SHA-256 hashes of the tokens are stored)
INSERT INTO auth_sessions (user_id, refresh_token_hash, issued_at, expires_at, revoked_at, ip_address, user_agent) VALUES
('00000000-0000-4000-a000-000000000002', encode(digest('demo-refresh-token-marcus', 'sha256'), 'hex'), now() - interval '2 hours', now() + interval '10 hours', NULL, '10.20.4.17', 'HealthTrack Dashboard (Chrome)'),
('00000000-0000-4000-a000-000000000011', encode(digest('demo-refresh-token-robert', 'sha256'), 'hex'), now() - interval '3 days', now() + interval '4 days', now() - interval '1 day', '198.51.100.24', 'HealthTrack Patient App (iOS)');

COMMIT;

-- summary
SELECT 'users' AS t, count(*) FROM healthtrack.users UNION ALL
SELECT 'patients', count(*) FROM healthtrack.patients UNION ALL
SELECT 'exercise_sessions', count(*) FROM healthtrack.exercise_sessions UNION ALL
SELECT 'vital_signs', count(*) FROM healthtrack.vital_signs UNION ALL
SELECT 'daily_activity', count(*) FROM healthtrack.daily_activity UNION ALL
SELECT 'appointments', count(*) FROM healthtrack.appointments UNION ALL
SELECT 'alerts', count(*) FROM healthtrack.alerts UNION ALL
SELECT 'alert_events', count(*) FROM healthtrack.alert_events UNION ALL
SELECT 'risk_assessments', count(*) FROM healthtrack.risk_assessments UNION ALL
SELECT 'audit_log', count(*) FROM healthtrack.audit_log;
