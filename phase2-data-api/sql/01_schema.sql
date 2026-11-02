-- =====================================================================
-- HealthTrack: home-based cardiac rehabilitation remote monitoring
-- 01_schema.sql : extensions, enumerated types, tables, constraints,
--                 indexes, and domain validation triggers
-- target: PostgreSQL 15 or later
-- =====================================================================

BEGIN;

CREATE EXTENSION IF NOT EXISTS citext;      -- case-insensitive email
CREATE EXTENSION IF NOT EXISTS btree_gist;  -- exclusion constraints on uuid + range
CREATE EXTENSION IF NOT EXISTS pgcrypto;    -- gen_random_uuid(), crypt() for sample data

CREATE SCHEMA IF NOT EXISTS healthtrack;
SET search_path = healthtrack, public;

-- ---------------------------------------------------------------------
-- enumerated types
-- ---------------------------------------------------------------------
CREATE TYPE user_role            AS ENUM ('patient', 'clinician', 'physician', 'admin', 'it_admin');
CREATE TYPE sex_at_birth         AS ENUM ('female', 'male', 'intersex', 'unknown');
CREATE TYPE qualifying_event     AS ENUM ('myocardial_infarction', 'pci', 'cabg', 'valve_surgery',
                                          'stable_angina', 'heart_failure_reduced_ef', 'heart_transplant');
CREATE TYPE program_status       AS ENUM ('referred', 'active', 'paused', 'graduated', 'withdrawn');
CREATE TYPE clinical_risk        AS ENUM ('low', 'moderate', 'high');
CREATE TYPE care_team_role       AS ENUM ('primary_clinician', 'supervising_physician', 'covering_clinician');
CREATE TYPE device_type          AS ENUM ('heart_rate_band', 'blood_pressure_cuff', 'pulse_oximeter', 'activity_tracker');
CREATE TYPE device_status        AS ENUM ('active', 'inactive', 'lost', 'retired');
CREATE TYPE reading_context      AS ENUM ('rest', 'warmup', 'exercise', 'cooldown', 'recovery');
CREATE TYPE reading_source       AS ENUM ('device', 'manual');
CREATE TYPE data_quality         AS ENUM ('valid', 'suspect', 'artifact');
CREATE TYPE session_type         AS ENUM ('aerobic', 'resistance', 'combined', 'flexibility');
CREATE TYPE session_status       AS ENUM ('in_progress', 'completed', 'partial', 'aborted');
CREATE TYPE symptom_type         AS ENUM ('chest_pain', 'shortness_of_breath', 'dizziness', 'palpitations',
                                          'unusual_fatigue', 'leg_pain', 'nausea', 'other');
CREATE TYPE appointment_type     AS ENUM ('intake', 'weekly_checkin', 'graduation_assessment', 'ad_hoc');
CREATE TYPE appointment_modality AS ENUM ('telehealth_video', 'phone', 'in_person');
CREATE TYPE appointment_status   AS ENUM ('scheduled', 'completed', 'missed', 'cancelled');
CREATE TYPE alert_rule_type      AS ENUM ('threshold', 'pattern', 'symptom', 'data_gap');
CREATE TYPE alert_severity       AS ENUM ('critical', 'high', 'moderate', 'low');
CREATE TYPE alert_status         AS ENUM ('open', 'acknowledged', 'escalated', 'resolved', 'suppressed');
CREATE TYPE alert_event_type     AS ENUM ('created', 'notified', 'acknowledged', 'escalated', 'resolved',
                                          'suppressed', 'comment');
CREATE TYPE notification_channel AS ENUM ('dashboard', 'email', 'sms');
CREATE TYPE notification_status  AS ENUM ('queued', 'sent', 'delivered', 'failed');
CREATE TYPE risk_level           AS ENUM ('low', 'moderate', 'high');
CREATE TYPE recommendation_status AS ENUM ('pending_review', 'approved', 'rejected');
CREATE TYPE audit_action         AS ENUM ('create', 'read', 'update', 'delete', 'login', 'login_failed',
                                          'logout', 'export', 'acknowledge');

-- ---------------------------------------------------------------------
-- shared trigger: maintain updated_at
-- ---------------------------------------------------------------------
CREATE FUNCTION set_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END $$;


-- =====================================================================
-- identity and access
-- =====================================================================
CREATE TABLE users (
    user_id               uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
    email                 citext       NOT NULL UNIQUE
                          CHECK (email ~ '^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$'),
    password_hash         text         NOT NULL
                          CHECK (password_hash ~ '^\$(2[aby]\$[0-9]{2}\$|argon2id\$)'),
    role                  user_role    NOT NULL,
    first_name            varchar(80)  NOT NULL CHECK (btrim(first_name) <> ''),
    last_name             varchar(80)  NOT NULL CHECK (btrim(last_name) <> ''),
    credentials           varchar(40),                      -- RN, CEP, MD
    phone                 varchar(16)  CHECK (phone ~ '^\+[1-9][0-9]{7,14}$'),  -- E.164
    is_active             boolean      NOT NULL DEFAULT true,
    mfa_enabled           boolean      NOT NULL DEFAULT false,
    failed_login_attempts smallint     NOT NULL DEFAULT 0 CHECK (failed_login_attempts BETWEEN 0 AND 100),
    locked_until          timestamptz,
    last_login_at         timestamptz,
    password_changed_at   timestamptz  NOT NULL DEFAULT now(),
    created_at            timestamptz  NOT NULL DEFAULT now(),
    updated_at            timestamptz  NOT NULL DEFAULT now()
);
COMMENT ON TABLE users IS 'Login accounts for patients and staff. Passwords stored only as bcrypt or Argon2id hashes.';

-- helper used by role-checking triggers
CREATE FUNCTION user_has_role(p_user uuid, p_roles user_role[]) RETURNS boolean
LANGUAGE sql STABLE AS $$
    SELECT EXISTS (SELECT 1 FROM healthtrack.users u
                   WHERE u.user_id = p_user AND u.role = ANY (p_roles) AND u.is_active);
$$;

CREATE TABLE auth_sessions (
    session_id          uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             uuid         NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
    refresh_token_hash  char(64)     NOT NULL UNIQUE CHECK (refresh_token_hash ~ '^[0-9a-f]{64}$'),  -- sha-256 hex
    issued_at           timestamptz  NOT NULL DEFAULT now(),
    expires_at          timestamptz  NOT NULL,
    revoked_at          timestamptz,
    ip_address          inet,
    user_agent          varchar(255),
    CONSTRAINT auth_sessions_expiry_ck CHECK (expires_at > issued_at AND expires_at <= issued_at + interval '7 days'),
    CONSTRAINT auth_sessions_revoked_ck CHECK (revoked_at IS NULL OR revoked_at >= issued_at)
);
COMMENT ON TABLE auth_sessions IS 'Refresh-token sessions. Only a SHA-256 hash of each refresh token is stored.';
CREATE INDEX auth_sessions_user_ix ON auth_sessions (user_id) WHERE revoked_at IS NULL;

-- =====================================================================
-- patient and care team
-- =====================================================================
CREATE TABLE patients (
    patient_id              uuid             PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                 uuid             UNIQUE REFERENCES users (user_id) ON DELETE SET NULL,
    mrn                     varchar(20)      NOT NULL UNIQUE CHECK (mrn ~ '^[A-Z0-9-]{6,20}$'),
    first_name              varchar(80)      NOT NULL CHECK (btrim(first_name) <> ''),
    last_name               varchar(80)      NOT NULL CHECK (btrim(last_name) <> ''),
    date_of_birth           date             NOT NULL CHECK (date_of_birth > DATE '1900-01-01'),
    sex                     sex_at_birth     NOT NULL,
    phone                   varchar(16)      CHECK (phone ~ '^\+[1-9][0-9]{7,14}$'),
    email                   citext           CHECK (email ~ '^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$'),
    postal_code             varchar(10)      CHECK (postal_code ~ '^[0-9]{5}(-[0-9]{4})?$'),
    timezone                varchar(40)      NOT NULL DEFAULT 'America/Denver',
    qualifying_event        qualifying_event NOT NULL,
    qualifying_event_date   date             NOT NULL,
    referral_date           date             NOT NULL,
    enrollment_date         date,
    graduation_date         date,
    program_status          program_status   NOT NULL DEFAULT 'referred',
    clinical_risk_category  clinical_risk    NOT NULL,
    target_sessions         smallint         NOT NULL DEFAULT 36 CHECK (target_sessions BETWEEN 1 AND 72),
    created_by              uuid             REFERENCES users (user_id),
    deleted_at              timestamptz,
    created_at              timestamptz      NOT NULL DEFAULT now(),
    updated_at              timestamptz      NOT NULL DEFAULT now(),
    -- adults only: at least 18 at the qualifying event
    CONSTRAINT patients_adult_ck         CHECK (date_of_birth <= qualifying_event_date - interval '18 years'),
    CONSTRAINT patients_event_order_ck   CHECK (qualifying_event_date <= referral_date),
    CONSTRAINT patients_enroll_order_ck  CHECK (enrollment_date IS NULL OR enrollment_date >= referral_date),
    CONSTRAINT patients_enrolled_ck      CHECK (program_status IN ('referred', 'withdrawn') OR enrollment_date IS NOT NULL),
    CONSTRAINT patients_graduated_ck     CHECK ((program_status = 'graduated') = (graduation_date IS NOT NULL)),
    CONSTRAINT patients_grad_order_ck    CHECK (graduation_date IS NULL OR graduation_date >= enrollment_date),
    -- home-based rehab is limited to clinically stable low- and moderate-risk patients
    CONSTRAINT patients_home_risk_ck     CHECK (program_status <> 'active' OR clinical_risk_category IN ('low', 'moderate'))
);
COMMENT ON TABLE patients IS 'Enrolled or referred rehab patients. Soft-deleted through deleted_at; never hard-deleted.';
COMMENT ON COLUMN patients.clinical_risk_category IS 'AACVPR exercise risk stratification at intake.';
CREATE INDEX patients_status_ix ON patients (program_status) WHERE deleted_at IS NULL;
CREATE INDEX patients_name_ix   ON patients (lower(last_name), lower(first_name));

CREATE TABLE caregivers (
    caregiver_id          uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id            uuid         NOT NULL REFERENCES patients (patient_id) ON DELETE CASCADE,
    full_name             varchar(160) NOT NULL CHECK (btrim(full_name) <> ''),
    relationship          varchar(40)  NOT NULL,
    phone                 varchar(16)  CHECK (phone ~ '^\+[1-9][0-9]{7,14}$'),
    email                 citext       CHECK (email ~ '^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$'),
    is_emergency_contact  boolean      NOT NULL DEFAULT false,
    receives_alerts       boolean      NOT NULL DEFAULT false,
    created_at            timestamptz  NOT NULL DEFAULT now(),
    updated_at            timestamptz  NOT NULL DEFAULT now(),
    CONSTRAINT caregivers_contact_ck CHECK (phone IS NOT NULL OR email IS NOT NULL)
);
CREATE INDEX caregivers_patient_ix ON caregivers (patient_id);

CREATE TABLE care_team_assignments (
    assignment_id  uuid            PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id     uuid            NOT NULL REFERENCES patients (patient_id) ON DELETE CASCADE,
    user_id        uuid            NOT NULL REFERENCES users (user_id),
    team_role      care_team_role  NOT NULL,
    start_date     date            NOT NULL DEFAULT current_date,
    end_date       date,
    assigned_by    uuid            REFERENCES users (user_id),
    created_at     timestamptz     NOT NULL DEFAULT now(),
    CONSTRAINT care_team_dates_ck CHECK (end_date IS NULL OR end_date >= start_date)
);
COMMENT ON TABLE care_team_assignments IS 'Who is responsible for each patient. Drives alert routing and row-level access.';
-- exactly one current primary clinician and one current supervising physician per patient
CREATE UNIQUE INDEX care_team_one_primary_ux ON care_team_assignments (patient_id, team_role)
    WHERE end_date IS NULL AND team_role IN ('primary_clinician', 'supervising_physician');
CREATE INDEX care_team_user_ix ON care_team_assignments (user_id) WHERE end_date IS NULL;

-- =====================================================================
-- exercise prescription and devices
-- =====================================================================
CREATE TABLE exercise_prescriptions (
    prescription_id      uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id           uuid         NOT NULL REFERENCES patients (patient_id) ON DELETE CASCADE,
    version              integer      NOT NULL CHECK (version >= 1),
    resting_hr_baseline  smallint     NOT NULL CHECK (resting_hr_baseline BETWEEN 30 AND 120),
    target_hr_min        smallint     NOT NULL,
    target_hr_max        smallint     NOT NULL,
    hr_ceiling           smallint     NOT NULL,
    max_exercise_sbp     smallint     NOT NULL DEFAULT 200 CHECK (max_exercise_sbp BETWEEN 140 AND 250),
    min_spo2             smallint     NOT NULL DEFAULT 90  CHECK (min_spo2 BETWEEN 85 AND 95),
    rpe_target_min       smallint     NOT NULL DEFAULT 11,
    rpe_target_max       smallint     NOT NULL DEFAULT 14,
    sessions_per_week    smallint     NOT NULL CHECK (sessions_per_week BETWEEN 1 AND 7),
    session_minutes      smallint     NOT NULL CHECK (session_minutes BETWEEN 10 AND 90),
    effective_from       timestamptz  NOT NULL DEFAULT now(),
    effective_to         timestamptz,
    prescribed_by        uuid         NOT NULL REFERENCES users (user_id),
    notes                text,
    created_at           timestamptz  NOT NULL DEFAULT now(),
    CONSTRAINT rx_hr_order_ck   CHECK (resting_hr_baseline < target_hr_min
                                       AND target_hr_min < target_hr_max
                                       AND target_hr_max < hr_ceiling
                                       AND target_hr_min >= 40 AND hr_ceiling <= 200),
    CONSTRAINT rx_rpe_ck        CHECK (rpe_target_min BETWEEN 6 AND 20 AND rpe_target_max BETWEEN 6 AND 20
                                       AND rpe_target_min <= rpe_target_max),
    CONSTRAINT rx_period_ck     CHECK (effective_to IS NULL OR effective_to > effective_from),
    CONSTRAINT rx_version_uq    UNIQUE (patient_id, version)
);
COMMENT ON TABLE exercise_prescriptions IS 'Versioned exercise prescription from the patient''s own exercise test. History is kept; one current version per patient.';
CREATE UNIQUE INDEX rx_one_current_ux ON exercise_prescriptions (patient_id) WHERE effective_to IS NULL;

CREATE TABLE devices (
    device_id         uuid           PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id        uuid           REFERENCES patients (patient_id) ON DELETE SET NULL,
    device_type       device_type    NOT NULL,
    manufacturer      varchar(60)    NOT NULL,
    model             varchar(60)    NOT NULL,
    serial_number     varchar(60)    NOT NULL,
    firmware_version  varchar(30),
    status            device_status  NOT NULL DEFAULT 'inactive',
    assigned_at       timestamptz,
    last_sync_at      timestamptz,
    created_at        timestamptz    NOT NULL DEFAULT now(),
    updated_at        timestamptz    NOT NULL DEFAULT now(),
    CONSTRAINT devices_serial_uq      UNIQUE (manufacturer, serial_number),
    CONSTRAINT devices_active_ck      CHECK (status <> 'active' OR (patient_id IS NOT NULL AND assigned_at IS NOT NULL))
);
CREATE INDEX devices_patient_ix ON devices (patient_id) WHERE status = 'active';

-- =====================================================================
-- monitoring data
-- =====================================================================
CREATE TABLE exercise_sessions (
    session_id             uuid            PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id             uuid            NOT NULL REFERENCES patients (patient_id) ON DELETE CASCADE,
    prescription_id        uuid            NOT NULL REFERENCES exercise_prescriptions (prescription_id),
    device_id              uuid            REFERENCES devices (device_id) ON DELETE SET NULL,
    session_type           session_type    NOT NULL DEFAULT 'aerobic',
    status                 session_status  NOT NULL DEFAULT 'in_progress',
    started_at             timestamptz     NOT NULL,
    ended_at               timestamptz,
    avg_hr                 smallint        CHECK (avg_hr BETWEEN 30 AND 250),
    peak_hr                smallint        CHECK (peak_hr BETWEEN 30 AND 250),
    minutes_in_zone        numeric(5,1)    CHECK (minutes_in_zone >= 0),
    minutes_above_ceiling  numeric(5,1)    CHECK (minutes_above_ceiling >= 0),
    rpe                    smallint        CHECK (rpe BETWEEN 6 AND 20),            -- Borg 6 to 20
    notes                  text,
    created_at             timestamptz     NOT NULL DEFAULT now(),
    updated_at             timestamptz     NOT NULL DEFAULT now(),
    CONSTRAINT sessions_time_ck      CHECK (ended_at IS NULL OR (ended_at > started_at
                                            AND ended_at <= started_at + interval '4 hours')),
    CONSTRAINT sessions_closed_ck    CHECK (status = 'in_progress' OR ended_at IS NOT NULL),
    CONSTRAINT sessions_peak_ck      CHECK (peak_hr IS NULL OR avg_hr IS NULL OR peak_hr >= avg_hr),
    CONSTRAINT sessions_zone_len_ck  CHECK (minutes_in_zone IS NULL OR ended_at IS NULL OR
                                            minutes_in_zone <= extract(epoch FROM ended_at - started_at) / 60.0),
    -- a patient cannot be in two sessions at once
    CONSTRAINT sessions_no_overlap   EXCLUDE USING gist (patient_id WITH =, tstzrange(started_at, ended_at) WITH &&)
                                     WHERE (ended_at IS NOT NULL)
);
CREATE INDEX sessions_patient_time_ix ON exercise_sessions (patient_id, started_at DESC);

CREATE TABLE vital_signs (
    vital_id         bigint           GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    patient_id       uuid             NOT NULL REFERENCES patients (patient_id) ON DELETE CASCADE,
    device_id        uuid             REFERENCES devices (device_id) ON DELETE SET NULL,
    session_id       uuid             REFERENCES exercise_sessions (session_id) ON DELETE SET NULL,
    recorded_at      timestamptz      NOT NULL,
    received_at      timestamptz      NOT NULL DEFAULT now(),
    context          reading_context  NOT NULL,
    heart_rate       smallint         CHECK (heart_rate   BETWEEN 20 AND 300),
    systolic_bp      smallint         CHECK (systolic_bp  BETWEEN 50 AND 300),
    diastolic_bp     smallint         CHECK (diastolic_bp BETWEEN 20 AND 200),
    spo2             smallint         CHECK (spo2         BETWEEN 50 AND 100),
    source           reading_source   NOT NULL DEFAULT 'device',
    entered_by       uuid             REFERENCES users (user_id),
    quality          data_quality     NOT NULL DEFAULT 'valid',
    idempotency_key  varchar(64)      CHECK (idempotency_key ~ '^[A-Za-z0-9._:-]{8,64}$'),
    CONSTRAINT vitals_any_value_ck   CHECK (num_nonnulls(heart_rate, systolic_bp, diastolic_bp, spo2) > 0),
    CONSTRAINT vitals_bp_pair_ck     CHECK ((systolic_bp IS NULL) = (diastolic_bp IS NULL)),
    CONSTRAINT vitals_bp_order_ck    CHECK (systolic_bp IS NULL OR systolic_bp > diastolic_bp),
    CONSTRAINT vitals_manual_ck      CHECK (source <> 'manual' OR entered_by IS NOT NULL),
    CONSTRAINT vitals_device_ck      CHECK (source <> 'device' OR device_id IS NOT NULL),
    CONSTRAINT vitals_received_ck    CHECK (received_at >= recorded_at - interval '5 minutes'),
    CONSTRAINT vitals_idempotency_uq UNIQUE (patient_id, idempotency_key)
);
COMMENT ON TABLE vital_signs IS 'Heart rate, blood pressure, and SpO2 readings. Hard CHECK limits reject impossible values; the plausibility trigger flags unlikely values as suspect.';
CREATE INDEX vitals_patient_time_ix ON vital_signs (patient_id, recorded_at DESC);
CREATE INDEX vitals_session_ix      ON vital_signs (session_id) WHERE session_id IS NOT NULL;
CREATE INDEX vitals_recorded_brin   ON vital_signs USING brin (recorded_at);

CREATE TABLE daily_activity (
    patient_id         uuid            NOT NULL REFERENCES patients (patient_id) ON DELETE CASCADE,
    activity_date      date            NOT NULL,
    steps              integer         NOT NULL CHECK (steps BETWEEN 0 AND 100000),
    active_minutes     smallint        NOT NULL CHECK (active_minutes BETWEEN 0 AND 1440),
    sedentary_minutes  smallint        CHECK (sedentary_minutes BETWEEN 0 AND 1440),
    resting_hr         smallint        CHECK (resting_hr BETWEEN 25 AND 150),
    source             reading_source  NOT NULL DEFAULT 'device',
    device_id          uuid            REFERENCES devices (device_id) ON DELETE SET NULL,
    created_at         timestamptz     NOT NULL DEFAULT now(),
    updated_at         timestamptz     NOT NULL DEFAULT now(),
    PRIMARY KEY (patient_id, activity_date),
    CONSTRAINT activity_minutes_ck CHECK (active_minutes + coalesce(sedentary_minutes, 0) <= 1440)
);

CREATE TABLE symptom_reports (
    symptom_id   uuid          PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id   uuid          NOT NULL REFERENCES patients (patient_id) ON DELETE CASCADE,
    session_id   uuid          REFERENCES exercise_sessions (session_id) ON DELETE SET NULL,
    reported_at  timestamptz   NOT NULL DEFAULT now(),
    symptom      symptom_type  NOT NULL,
    severity     smallint      NOT NULL CHECK (severity BETWEEN 0 AND 10),
    description  text,
    created_at   timestamptz   NOT NULL DEFAULT now(),
    CONSTRAINT symptoms_other_ck CHECK (symptom <> 'other' OR btrim(coalesce(description, '')) <> '')
);
CREATE INDEX symptoms_patient_time_ix ON symptom_reports (patient_id, reported_at DESC);

-- =====================================================================
-- appointments
-- =====================================================================
CREATE TABLE appointments (
    appointment_id    uuid                  PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id        uuid                  NOT NULL REFERENCES patients (patient_id) ON DELETE CASCADE,
    clinician_id      uuid                  NOT NULL REFERENCES users (user_id),
    appointment_type  appointment_type      NOT NULL,
    modality          appointment_modality  NOT NULL DEFAULT 'telehealth_video',
    status            appointment_status    NOT NULL DEFAULT 'scheduled',
    scheduled_start   timestamptz           NOT NULL,
    scheduled_end     timestamptz           NOT NULL,
    cancel_reason     varchar(255),
    notes             text,
    created_by        uuid                  REFERENCES users (user_id),
    created_at        timestamptz           NOT NULL DEFAULT now(),
    updated_at        timestamptz           NOT NULL DEFAULT now(),
    CONSTRAINT appt_length_ck   CHECK (scheduled_end - scheduled_start BETWEEN interval '10 minutes' AND interval '3 hours'),
    CONSTRAINT appt_cancel_ck   CHECK (status <> 'cancelled' OR cancel_reason IS NOT NULL),
    -- no double-booking of a clinician or a patient
    CONSTRAINT appt_clinician_no_overlap EXCLUDE USING gist
        (clinician_id WITH =, tstzrange(scheduled_start, scheduled_end) WITH &&)
        WHERE (status IN ('scheduled', 'completed')),
    CONSTRAINT appt_patient_no_overlap EXCLUDE USING gist
        (patient_id WITH =, tstzrange(scheduled_start, scheduled_end) WITH &&)
        WHERE (status IN ('scheduled', 'completed'))
);
CREATE UNIQUE INDEX appt_one_graduation_ux ON appointments (patient_id)
    WHERE appointment_type = 'graduation_assessment' AND status <> 'cancelled';
CREATE INDEX appt_clinician_time_ix ON appointments (clinician_id, scheduled_start);
CREATE INDEX appt_patient_time_ix   ON appointments (patient_id, scheduled_start);

-- =====================================================================
-- alerting
-- =====================================================================
CREATE TABLE alert_rules (
    rule_id                    uuid              PRIMARY KEY DEFAULT gen_random_uuid(),
    rule_code                  varchar(40)       NOT NULL UNIQUE CHECK (rule_code ~ '^[A-Z][A-Z0-9_]{2,39}$'),
    name                       varchar(120)      NOT NULL,
    description                text              NOT NULL,
    rule_type                  alert_rule_type   NOT NULL,
    metric                     varchar(40)       NOT NULL,
    comparator                 varchar(2)        NOT NULL CHECK (comparator IN ('>', '>=', '<', '<=', '=')),
    default_threshold          numeric(8,2)      NOT NULL,
    applies_to_context         reading_context[],           -- null means every context
    evaluation_window_minutes  integer           NOT NULL DEFAULT 0 CHECK (evaluation_window_minutes BETWEEN 0 AND 43200),
    consecutive_required       smallint          NOT NULL DEFAULT 1 CHECK (consecutive_required BETWEEN 1 AND 20),
    severity                   alert_severity    NOT NULL,
    suppression_minutes        integer           NOT NULL DEFAULT 60 CHECK (suppression_minutes BETWEEN 0 AND 10080),
    is_customizable            boolean           NOT NULL DEFAULT true,
    is_active                  boolean           NOT NULL DEFAULT true,
    updated_by                 uuid              REFERENCES users (user_id),
    created_at                 timestamptz       NOT NULL DEFAULT now(),
    updated_at                 timestamptz       NOT NULL DEFAULT now(),
    -- critical alerts are never suppressed
    CONSTRAINT rules_critical_ck CHECK (severity <> 'critical' OR suppression_minutes = 0)
);
COMMENT ON TABLE alert_rules IS 'Program-default alert rules. Thresholds may be overridden per patient in patient_alert_thresholds.';

CREATE TABLE patient_alert_thresholds (
    override_id      uuid          PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id       uuid          NOT NULL REFERENCES patients (patient_id) ON DELETE CASCADE,
    rule_id          uuid          NOT NULL REFERENCES alert_rules (rule_id),
    threshold_value  numeric(8,2)  NOT NULL,
    reason           text          NOT NULL CHECK (length(btrim(reason)) >= 5),
    set_by           uuid          NOT NULL REFERENCES users (user_id),
    effective_from   timestamptz   NOT NULL DEFAULT now(),
    effective_to     timestamptz,
    created_at       timestamptz   NOT NULL DEFAULT now(),
    CONSTRAINT thresholds_period_ck CHECK (effective_to IS NULL OR effective_to > effective_from)
);
CREATE UNIQUE INDEX thresholds_one_current_ux ON patient_alert_thresholds (patient_id, rule_id) WHERE effective_to IS NULL;

CREATE TABLE escalation_policies (
    severity               alert_severity          PRIMARY KEY,
    ack_timeout_minutes    integer                 NOT NULL CHECK (ack_timeout_minutes BETWEEN 1 AND 1440),
    escalate_to            care_team_role          NOT NULL,
    max_escalation_level   smallint                NOT NULL DEFAULT 2 CHECK (max_escalation_level BETWEEN 0 AND 3),
    channels               notification_channel[]  NOT NULL CHECK (cardinality(channels) >= 1),
    deliver_as_digest      boolean                 NOT NULL DEFAULT false,
    updated_by             uuid                    REFERENCES users (user_id),
    updated_at             timestamptz             NOT NULL DEFAULT now(),
    CONSTRAINT escalation_critical_ck CHECK (severity <> 'critical'
                                             OR (ack_timeout_minutes <= 30 AND NOT deliver_as_digest)),
    CONSTRAINT escalation_digest_ck   CHECK (NOT deliver_as_digest OR severity = 'low')
);

CREATE TABLE alerts (
    alert_id           uuid            PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id         uuid            NOT NULL REFERENCES patients (patient_id) ON DELETE CASCADE,
    rule_id            uuid            NOT NULL REFERENCES alert_rules (rule_id),
    vital_id           bigint          REFERENCES vital_signs (vital_id) ON DELETE SET NULL,
    session_id         uuid            REFERENCES exercise_sessions (session_id) ON DELETE SET NULL,
    symptom_id         uuid            REFERENCES symptom_reports (symptom_id) ON DELETE SET NULL,
    severity           alert_severity  NOT NULL,
    status             alert_status    NOT NULL DEFAULT 'open',
    title              varchar(160)    NOT NULL,
    triggering_values  jsonb           NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(triggering_values) = 'object'),
    threshold_applied  numeric(8,2),
    dedup_key          varchar(120)    NOT NULL,
    triggered_at       timestamptz     NOT NULL DEFAULT now(),
    acknowledged_at    timestamptz,
    acknowledged_by    uuid            REFERENCES users (user_id),
    escalation_level   smallint        NOT NULL DEFAULT 0 CHECK (escalation_level BETWEEN 0 AND 3),
    escalated_at       timestamptz,
    resolved_at        timestamptz,
    resolved_by        uuid            REFERENCES users (user_id),
    resolution_note    text,
    CONSTRAINT alerts_ack_ck       CHECK ((acknowledged_at IS NULL) = (acknowledged_by IS NULL)
                                          AND (acknowledged_at IS NULL OR acknowledged_at >= triggered_at)),
    CONSTRAINT alerts_ack_state_ck CHECK (status NOT IN ('acknowledged') OR acknowledged_at IS NOT NULL),
    CONSTRAINT alerts_escalate_ck  CHECK (status <> 'escalated' OR (escalation_level >= 1 AND escalated_at IS NOT NULL)),
    CONSTRAINT alerts_resolved_ck  CHECK ((status = 'resolved') = (resolved_at IS NOT NULL)
                                          AND (status <> 'resolved' OR (resolved_by IS NOT NULL
                                               AND btrim(coalesce(resolution_note, '')) <> ''
                                               AND resolved_at >= triggered_at)))
);
COMMENT ON COLUMN alerts.dedup_key IS 'Identifies the same underlying condition so repeats attach to one open alert instead of creating new ones.';
-- one open alert per patient, rule, and condition (duplicate suppression)
CREATE UNIQUE INDEX alerts_open_dedup_ux ON alerts (patient_id, rule_id, dedup_key)
    WHERE status IN ('open', 'acknowledged', 'escalated');
CREATE INDEX alerts_worklist_ix ON alerts (status, severity, triggered_at DESC);
CREATE INDEX alerts_patient_ix  ON alerts (patient_id, triggered_at DESC);

CREATE TABLE alert_events (
    event_id       bigint            GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    alert_id       uuid              NOT NULL REFERENCES alerts (alert_id) ON DELETE CASCADE,
    event_type     alert_event_type  NOT NULL,
    from_status    alert_status,
    to_status      alert_status,
    actor_user_id  uuid              REFERENCES users (user_id),      -- null means the system
    occurred_at    timestamptz       NOT NULL DEFAULT now(),
    note           text,
    payload        jsonb             NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(payload) = 'object')
);
COMMENT ON TABLE alert_events IS 'Append-only alert history: creation, notification, acknowledgment, escalation, resolution.';
CREATE INDEX alert_events_alert_ix ON alert_events (alert_id, occurred_at);

CREATE TABLE notifications (
    notification_id    uuid                  PRIMARY KEY DEFAULT gen_random_uuid(),
    alert_id           uuid                  NOT NULL REFERENCES alerts (alert_id) ON DELETE CASCADE,
    recipient_user_id  uuid                  NOT NULL REFERENCES users (user_id),
    channel            notification_channel  NOT NULL,
    status             notification_status   NOT NULL DEFAULT 'queued',
    payload            jsonb                 NOT NULL
                       CHECK (payload ?& ARRAY['alert_id', 'patient_id', 'severity', 'rule_code', 'triggered_at']),
    attempts           smallint              NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 10),
    queued_at          timestamptz           NOT NULL DEFAULT now(),
    sent_at            timestamptz,
    delivered_at       timestamptz,
    read_at            timestamptz,
    failure_reason     varchar(255),
    CONSTRAINT notif_sent_ck    CHECK (status NOT IN ('sent', 'delivered') OR sent_at IS NOT NULL),
    CONSTRAINT notif_failed_ck  CHECK (status <> 'failed' OR failure_reason IS NOT NULL),
    CONSTRAINT notif_order_ck   CHECK (delivered_at IS NULL OR delivered_at >= sent_at)
);
CREATE INDEX notifications_recipient_ix ON notifications (recipient_user_id, queued_at DESC);
CREATE INDEX notifications_pending_ix   ON notifications (queued_at) WHERE status = 'queued';

-- =====================================================================
-- risk assessment
-- =====================================================================
CREATE TABLE risk_level_bands (
    level      risk_level    PRIMARY KEY,
    min_score  numeric(5,2)  NOT NULL CHECK (min_score BETWEEN 0 AND 100),
    max_score  numeric(5,2)  NOT NULL CHECK (max_score BETWEEN 0 AND 100),
    color_hex  char(7)       NOT NULL CHECK (color_hex ~ '^#[0-9A-Fa-f]{6}$'),
    label      varchar(40)   NOT NULL,
    CONSTRAINT bands_order_ck CHECK (min_score < max_score),
    CONSTRAINT bands_no_overlap EXCLUDE USING gist (numrange(min_score, max_score, '[)') WITH &&)
);
COMMENT ON TABLE risk_level_bands IS 'Configurable score boundaries and display colors for risk levels.';

CREATE TABLE risk_assessments (
    assessment_id        uuid          PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id           uuid          NOT NULL REFERENCES patients (patient_id) ON DELETE CASCADE,
    assessed_at          timestamptz   NOT NULL DEFAULT now(),
    model_name           varchar(60)   NOT NULL,
    model_version        varchar(20)   NOT NULL CHECK (model_version ~ '^[0-9]+\.[0-9]+\.[0-9]+$'),
    window_start         timestamptz   NOT NULL,
    window_end           timestamptz   NOT NULL,
    risk_score           numeric(5,2)  NOT NULL CHECK (risk_score BETWEEN 0 AND 100),
    risk_level           risk_level    NOT NULL,
    dropout_probability  numeric(4,3)  CHECK (dropout_probability BETWEEN 0 AND 1),
    decline_probability  numeric(4,3)  CHECK (decline_probability BETWEEN 0 AND 1),
    created_at           timestamptz   NOT NULL DEFAULT now(),
    CONSTRAINT risk_window_ck CHECK (window_end > window_start AND window_end <= assessed_at + interval '1 minute')
);
CREATE INDEX risk_patient_time_ix ON risk_assessments (patient_id, assessed_at DESC);

CREATE TABLE risk_factors (
    factor_id       uuid           PRIMARY KEY DEFAULT gen_random_uuid(),
    assessment_id   uuid           NOT NULL REFERENCES risk_assessments (assessment_id) ON DELETE CASCADE,
    factor_code     varchar(40)    NOT NULL CHECK (factor_code ~ '^[a-z][a-z0-9_]{2,39}$'),
    label           varchar(120)   NOT NULL,
    observed_value  varchar(60)    NOT NULL,
    reference_value varchar(60),
    contribution    numeric(6,3)   NOT NULL,      -- signed share of the score
    rank            smallint       NOT NULL CHECK (rank BETWEEN 1 AND 20),
    CONSTRAINT factors_code_uq UNIQUE (assessment_id, factor_code),
    CONSTRAINT factors_rank_uq UNIQUE (assessment_id, rank)
);

CREATE TABLE care_recommendations (
    recommendation_id    uuid                   PRIMARY KEY DEFAULT gen_random_uuid(),
    assessment_id        uuid                   REFERENCES risk_assessments (assessment_id) ON DELETE SET NULL,
    patient_id           uuid                   NOT NULL REFERENCES patients (patient_id) ON DELETE CASCADE,
    recommendation_text  text                   NOT NULL CHECK (length(btrim(recommendation_text)) >= 10),
    source               varchar(20)            NOT NULL DEFAULT 'system' CHECK (source IN ('system', 'clinician')),
    status               recommendation_status  NOT NULL DEFAULT 'pending_review',
    reviewed_by          uuid                   REFERENCES users (user_id),
    reviewed_at          timestamptz,
    review_note          text,
    created_at           timestamptz            NOT NULL DEFAULT now(),
    CONSTRAINT rec_review_ck CHECK ((status = 'pending_review') = (reviewed_by IS NULL)
                                    AND (reviewed_by IS NULL) = (reviewed_at IS NULL)),
    CONSTRAINT rec_system_link_ck CHECK (source <> 'system' OR assessment_id IS NOT NULL)
);
COMMENT ON TABLE care_recommendations IS 'Recommendations with source = system are system-generated suggestions and require clinician review before use.';
CREATE INDEX rec_patient_ix ON care_recommendations (patient_id, created_at DESC);
CREATE INDEX rec_pending_ix ON care_recommendations (created_at) WHERE status = 'pending_review';

-- =====================================================================
-- audit log (append-only)
-- =====================================================================
CREATE TABLE audit_log (
    audit_id       bigint        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    occurred_at    timestamptz   NOT NULL DEFAULT now(),
    actor_user_id  uuid,                                   -- no FK so the log never changes when users change
    actor_role     user_role,
    action         audit_action  NOT NULL,
    entity_type    varchar(40)   NOT NULL,
    entity_id      text,
    patient_id     uuid,
    outcome        varchar(10)   NOT NULL DEFAULT 'success' CHECK (outcome IN ('success', 'denied', 'error')),
    request_id     uuid,
    ip_address     inet,
    details        jsonb         NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(details) = 'object')
);
COMMENT ON TABLE audit_log IS 'HIPAA audit trail. Records who touched which record, never the PHI values themselves. Append-only.';
CREATE INDEX audit_patient_ix ON audit_log (patient_id, occurred_at DESC) WHERE patient_id IS NOT NULL;
CREATE INDEX audit_actor_ix   ON audit_log (actor_user_id, occurred_at DESC);
CREATE INDEX audit_time_brin  ON audit_log USING brin (occurred_at);

-- =====================================================================
-- validation triggers
-- =====================================================================

-- updated_at maintenance
DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['users', 'patients', 'caregivers', 'devices', 'exercise_sessions',
                             'daily_activity', 'appointments', 'alert_rules'] LOOP
        EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE ON healthtrack.%I
                        FOR EACH ROW EXECUTE FUNCTION healthtrack.set_updated_at()', t || '_updated_at', t);
    END LOOP;
END $$;

-- role checks that a CHECK constraint cannot express (they reference another table)
CREATE FUNCTION validate_roles() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    care_roles user_role[] := ARRAY['clinician', 'physician']::user_role[];
BEGIN
    CASE TG_TABLE_NAME
    WHEN 'patients' THEN
        IF NEW.user_id IS NOT NULL AND NOT user_has_role(NEW.user_id, ARRAY['patient']::user_role[]) THEN
            RAISE EXCEPTION 'patients.user_id must reference an active patient account' USING ERRCODE = '23514';
        END IF;
    WHEN 'care_team_assignments' THEN
        IF NEW.team_role = 'supervising_physician' THEN
            IF NOT user_has_role(NEW.user_id, ARRAY['physician']::user_role[]) THEN
                RAISE EXCEPTION 'supervising_physician must be an active physician' USING ERRCODE = '23514';
            END IF;
        ELSIF NOT user_has_role(NEW.user_id, care_roles) THEN
            RAISE EXCEPTION 'care team members must be active clinicians or physicians' USING ERRCODE = '23514';
        END IF;
    WHEN 'exercise_prescriptions' THEN
        IF NOT user_has_role(NEW.prescribed_by, ARRAY['physician']::user_role[]) THEN
            RAISE EXCEPTION 'exercise prescriptions must be signed by an active physician' USING ERRCODE = '23514';
        END IF;
    WHEN 'patient_alert_thresholds' THEN
        IF NOT user_has_role(NEW.set_by, ARRAY['physician']::user_role[]) THEN
            RAISE EXCEPTION 'patient-specific thresholds must be set by an active physician' USING ERRCODE = '23514';
        END IF;
    WHEN 'appointments' THEN
        IF NOT user_has_role(NEW.clinician_id, care_roles) THEN
            RAISE EXCEPTION 'appointments must be assigned to a clinician or physician' USING ERRCODE = '23514';
        END IF;
    WHEN 'alerts' THEN
        IF (NEW.acknowledged_by IS NOT NULL AND NEW.acknowledged_by IS DISTINCT FROM OLD.acknowledged_by
                AND NOT user_has_role(NEW.acknowledged_by, care_roles))
           OR (NEW.resolved_by IS NOT NULL AND NEW.resolved_by IS DISTINCT FROM OLD.resolved_by
                AND NOT user_has_role(NEW.resolved_by, care_roles)) THEN
            RAISE EXCEPTION 'only clinicians and physicians may acknowledge or resolve alerts' USING ERRCODE = '23514';
        END IF;
    WHEN 'care_recommendations' THEN
        IF NEW.reviewed_by IS NOT NULL AND NOT user_has_role(NEW.reviewed_by, care_roles) THEN
            RAISE EXCEPTION 'recommendations must be reviewed by a clinician or physician' USING ERRCODE = '23514';
        END IF;
    ELSE
        NULL;
    END CASE;
    RETURN NEW;
END $$;

CREATE TRIGGER patients_roles_trg   BEFORE INSERT OR UPDATE OF user_id ON patients
    FOR EACH ROW EXECUTE FUNCTION validate_roles();
CREATE TRIGGER care_team_roles_trg  BEFORE INSERT OR UPDATE OF user_id, team_role ON care_team_assignments
    FOR EACH ROW EXECUTE FUNCTION validate_roles();
CREATE TRIGGER rx_roles_trg         BEFORE INSERT ON exercise_prescriptions
    FOR EACH ROW EXECUTE FUNCTION validate_roles();
CREATE TRIGGER thresholds_roles_trg BEFORE INSERT ON patient_alert_thresholds
    FOR EACH ROW EXECUTE FUNCTION validate_roles();
CREATE TRIGGER appt_roles_trg       BEFORE INSERT OR UPDATE OF clinician_id ON appointments
    FOR EACH ROW EXECUTE FUNCTION validate_roles();
CREATE TRIGGER alerts_roles_trg     BEFORE UPDATE OF acknowledged_by, resolved_by ON alerts
    FOR EACH ROW EXECUTE FUNCTION validate_roles();
CREATE TRIGGER rec_roles_trg        BEFORE INSERT OR UPDATE OF reviewed_by ON care_recommendations
    FOR EACH ROW EXECUTE FUNCTION validate_roles();

-- new prescription version closes the previous one and numbers itself
CREATE FUNCTION rx_versioning() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    SELECT coalesce(max(version), 0) + 1 INTO NEW.version
      FROM healthtrack.exercise_prescriptions WHERE patient_id = NEW.patient_id;
    UPDATE healthtrack.exercise_prescriptions
       SET effective_to = NEW.effective_from
     WHERE patient_id = NEW.patient_id AND effective_to IS NULL;
    RETURN NEW;
END $$;
CREATE TRIGGER rx_versioning_trg BEFORE INSERT ON exercise_prescriptions
    FOR EACH ROW EXECUTE FUNCTION rx_versioning();

-- thresholds: only customizable rules, and a new override closes the old one
CREATE FUNCTION threshold_override_check() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM healthtrack.alert_rules
                   WHERE rule_id = NEW.rule_id AND is_customizable) THEN
        RAISE EXCEPTION 'rule % does not allow patient-specific thresholds', NEW.rule_id USING ERRCODE = '23514';
    END IF;
    UPDATE healthtrack.patient_alert_thresholds
       SET effective_to = NEW.effective_from
     WHERE patient_id = NEW.patient_id AND rule_id = NEW.rule_id AND effective_to IS NULL;
    RETURN NEW;
END $$;
CREATE TRIGGER thresholds_check_trg BEFORE INSERT ON patient_alert_thresholds
    FOR EACH ROW EXECUTE FUNCTION threshold_override_check();

-- vital plausibility: reject future timestamps, flag unlikely values as suspect
CREATE FUNCTION vitals_plausibility() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.recorded_at > now() + interval '5 minutes' THEN
        RAISE EXCEPTION 'recorded_at % is in the future', NEW.recorded_at USING ERRCODE = '22007';
    END IF;
    IF NEW.quality = 'valid' AND (
           NEW.heart_rate   NOT BETWEEN 30 AND 220
        OR NEW.systolic_bp  NOT BETWEEN 70 AND 250
        OR NEW.diastolic_bp NOT BETWEEN 35 AND 140
        OR NEW.spo2 < 70
        OR (NEW.systolic_bp - NEW.diastolic_bp) < 15) THEN
        NEW.quality := 'suspect';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER vitals_plausibility_trg BEFORE INSERT OR UPDATE ON vital_signs
    FOR EACH ROW EXECUTE FUNCTION vitals_plausibility();

-- risk level must agree with the configured score bands
CREATE FUNCTION risk_level_from_band() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE banded risk_level;
BEGIN
    SELECT level INTO banded FROM healthtrack.risk_level_bands
     WHERE NEW.risk_score >= min_score
       AND (NEW.risk_score < max_score OR (max_score = 100 AND NEW.risk_score = 100));
    IF banded IS NULL THEN
        RAISE EXCEPTION 'no risk band covers score %', NEW.risk_score USING ERRCODE = '23514';
    END IF;
    NEW.risk_level := banded;
    RETURN NEW;
END $$;
CREATE TRIGGER risk_level_trg BEFORE INSERT OR UPDATE OF risk_score ON risk_assessments
    FOR EACH ROW EXECUTE FUNCTION risk_level_from_band();

-- every alert creation and status change is written to alert_events automatically
CREATE FUNCTION alert_history() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    actor uuid := nullif(current_setting('app.user_id', true), '')::uuid;
    evt   alert_event_type;
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO healthtrack.alert_events (alert_id, event_type, to_status, actor_user_id, occurred_at, payload)
        VALUES (NEW.alert_id, 'created', NEW.status, actor, NEW.triggered_at,
                jsonb_build_object('severity', NEW.severity, 'title', NEW.title));
    ELSIF NEW.status IS DISTINCT FROM OLD.status OR NEW.escalation_level IS DISTINCT FROM OLD.escalation_level THEN
        evt := CASE NEW.status
                   WHEN 'acknowledged' THEN 'acknowledged'
                   WHEN 'escalated'    THEN 'escalated'
                   WHEN 'resolved'     THEN 'resolved'
                   WHEN 'suppressed'   THEN 'suppressed'
                   ELSE 'comment' END;
        INSERT INTO healthtrack.alert_events (alert_id, event_type, from_status, to_status, actor_user_id,
                                              occurred_at, note, payload)
        VALUES (NEW.alert_id, evt, OLD.status, NEW.status,
                CASE WHEN evt = 'escalated' THEN NULL ELSE actor END,
                coalesce(CASE evt WHEN 'acknowledged' THEN NEW.acknowledged_at
                                  WHEN 'escalated'    THEN NEW.escalated_at
                                  WHEN 'resolved'     THEN NEW.resolved_at END, now()),
                CASE WHEN evt = 'resolved' THEN NEW.resolution_note END,
                jsonb_build_object('escalation_level', NEW.escalation_level));
    END IF;
    RETURN NULL;
END $$;
CREATE TRIGGER alerts_history_trg AFTER INSERT OR UPDATE ON alerts
    FOR EACH ROW EXECUTE FUNCTION alert_history();

-- derived session metrics from the stored readings (one reading per minute)
CREATE FUNCTION compute_session_metrics(p_session uuid) RETURNS void LANGUAGE sql AS $$
    UPDATE healthtrack.exercise_sessions s
       SET avg_hr                = m.avg_hr,
           peak_hr               = m.peak_hr,
           minutes_in_zone       = m.in_zone,
           minutes_above_ceiling = m.above
      FROM (SELECT round(avg(v.heart_rate) FILTER (WHERE v.context = 'exercise'))::smallint AS avg_hr,
                   max(v.heart_rate)::smallint                                         AS peak_hr,
                   count(*) FILTER (WHERE v.context = 'exercise' AND v.quality = 'valid'
                                    AND v.heart_rate BETWEEN rx.target_hr_min AND rx.target_hr_max)::numeric AS in_zone,
                   count(*) FILTER (WHERE v.quality = 'valid' AND v.heart_rate > rx.hr_ceiling)::numeric    AS above
              FROM healthtrack.exercise_sessions s2
              JOIN healthtrack.exercise_prescriptions rx ON rx.prescription_id = s2.prescription_id
              JOIN healthtrack.vital_signs v ON v.session_id = s2.session_id AND v.heart_rate IS NOT NULL
             WHERE s2.session_id = p_session) m
     WHERE s.session_id = p_session;
$$;
COMMENT ON FUNCTION compute_session_metrics(uuid) IS 'Recomputes avg HR, peak HR, minutes in target zone, and minutes above ceiling for one session.';

COMMIT;
