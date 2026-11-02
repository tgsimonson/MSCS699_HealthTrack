-- =====================================================================
-- HealthTrack 02_security.sql
-- database roles, least-privilege grants, append-only audit log,
-- automatic PHI change auditing, and row-level security
-- =====================================================================
-- request context: for every request the API runs, inside its transaction,
--   SET LOCAL app.user_id   = '<uuid from the verified JWT>';
--   SET LOCAL app.user_role = '<role from the verified JWT>';
--   SET LOCAL app.request_id = '<uuid>';
-- the policies and audit triggers below read these settings.
-- =====================================================================

BEGIN;
SET search_path = healthtrack, public;

-- ---------------------------------------------------------------------
-- roles (NOLOGIN groups; login users and passwords come from the
-- deployment secrets manager, never from source control)
-- ---------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'healthtrack_owner')     THEN CREATE ROLE healthtrack_owner NOLOGIN; END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'healthtrack_api')       THEN CREATE ROLE healthtrack_api NOLOGIN; END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'healthtrack_analytics') THEN CREATE ROLE healthtrack_analytics NOLOGIN; END IF;
END $$;

-- ---------------------------------------------------------------------
-- request-context helpers
-- ---------------------------------------------------------------------
CREATE FUNCTION app_user_id() RETURNS uuid LANGUAGE sql STABLE AS $$
    SELECT nullif(current_setting('app.user_id', true), '')::uuid;
$$;

CREATE FUNCTION app_user_role() RETURNS user_role LANGUAGE sql STABLE AS $$
    SELECT nullif(current_setting('app.user_role', true), '')::healthtrack.user_role;
$$;

-- core authorization rule: may the current user see this patient's PHI?
--   patient              -> only their own record
--   clinician/physician  -> patients on their current care team
--   admin, it_admin      -> no clinical PHI (admins use aggregate views)
CREATE FUNCTION can_access_patient(p_patient uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = healthtrack, pg_temp AS $$
    SELECT CASE healthtrack.app_user_role()
        WHEN 'patient' THEN EXISTS (
            SELECT 1 FROM patients p
             WHERE p.patient_id = p_patient AND p.user_id = healthtrack.app_user_id())
        WHEN 'clinician' THEN EXISTS (
            SELECT 1 FROM care_team_assignments c
             WHERE c.patient_id = p_patient AND c.user_id = healthtrack.app_user_id()
               AND c.start_date <= current_date AND c.end_date IS NULL)
        WHEN 'physician' THEN EXISTS (
            SELECT 1 FROM care_team_assignments c
             WHERE c.patient_id = p_patient AND c.user_id = healthtrack.app_user_id()
               AND c.start_date <= current_date AND c.end_date IS NULL)
        ELSE false
    END;
$$;
COMMENT ON FUNCTION can_access_patient(uuid) IS 'Row-level authorization rule shared by every patient-scoped policy.';

-- ---------------------------------------------------------------------
-- append-only audit log and alert history
-- ---------------------------------------------------------------------
CREATE FUNCTION forbid_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% is append-only; % is not permitted', TG_TABLE_NAME, TG_OP
          USING ERRCODE = '42501';
END $$;

CREATE TRIGGER audit_log_append_only  BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION forbid_change();
CREATE TRIGGER audit_log_no_truncate  BEFORE TRUNCATE ON audit_log
    FOR EACH STATEMENT EXECUTE FUNCTION forbid_change();
CREATE TRIGGER alert_events_append_only BEFORE UPDATE ON alert_events
    FOR EACH ROW EXECUTE FUNCTION forbid_change();

-- ---------------------------------------------------------------------
-- automatic auditing of PHI writes (reads are audited by the API layer)
-- records column names that changed, never the PHI values
-- ---------------------------------------------------------------------
CREATE FUNCTION audit_phi_change() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = healthtrack, pg_temp AS $$
DECLARE
    rec      jsonb := to_jsonb(coalesce(NEW, OLD));
    pk_col   text  := TG_ARGV[0];
    changed  jsonb := '[]';
BEGIN
    IF TG_OP = 'UPDATE' THEN
        SELECT coalesce(jsonb_agg(n.key), '[]') INTO changed
          FROM jsonb_each(to_jsonb(NEW)) n
          JOIN jsonb_each(to_jsonb(OLD)) o USING (key)
         WHERE n.value IS DISTINCT FROM o.value AND n.key NOT IN ('updated_at');
        IF changed = '[]' THEN RETURN NULL; END IF;
    END IF;
    INSERT INTO audit_log (actor_user_id, actor_role, action, entity_type, entity_id, patient_id,
                           request_id, details)
    VALUES (app_user_id(), app_user_role(),
            CASE TG_OP WHEN 'INSERT' THEN 'create' WHEN 'UPDATE' THEN 'update' ELSE 'delete' END::audit_action,
            TG_TABLE_NAME, rec ->> pk_col, (rec ->> 'patient_id')::uuid,
            nullif(current_setting('app.request_id', true), '')::uuid,
            CASE WHEN TG_OP = 'UPDATE' THEN jsonb_build_object('changed_columns', changed) ELSE '{}' END);
    RETURN NULL;
END $$;

DO $$
DECLARE
    -- table, primary key column, which operations to audit
    spec text[];
    specs text[][] := ARRAY[
        ARRAY['patients',                 'patient_id',        'INSERT OR UPDATE OR DELETE'],
        ARRAY['caregivers',               'caregiver_id',      'INSERT OR UPDATE OR DELETE'],
        ARRAY['care_team_assignments',    'assignment_id',     'INSERT OR UPDATE OR DELETE'],
        ARRAY['exercise_prescriptions',   'prescription_id',   'INSERT OR UPDATE OR DELETE'],
        ARRAY['patient_alert_thresholds', 'override_id',       'INSERT OR UPDATE OR DELETE'],
        ARRAY['appointments',             'appointment_id',    'INSERT OR UPDATE OR DELETE'],
        ARRAY['alerts',                   'alert_id',          'UPDATE OR DELETE'],
        ARRAY['care_recommendations',     'recommendation_id', 'UPDATE OR DELETE'],
        -- high-volume device data: inserts are audited per batch by the API
        ARRAY['vital_signs',              'vital_id',          'UPDATE OR DELETE'],
        ARRAY['exercise_sessions',        'session_id',        'UPDATE OR DELETE'],
        ARRAY['daily_activity',           'activity_date',     'UPDATE OR DELETE'],
        ARRAY['symptom_reports',          'symptom_id',        'UPDATE OR DELETE']];
BEGIN
    FOREACH spec SLICE 1 IN ARRAY specs LOOP
        EXECUTE format('CREATE TRIGGER %I AFTER %s ON healthtrack.%I
                        FOR EACH ROW EXECUTE FUNCTION healthtrack.audit_phi_change(%L)',
                       spec[1] || '_audit_trg', spec[3], spec[1], spec[2]);
    END LOOP;
END $$;

-- ---------------------------------------------------------------------
-- ownership and least-privilege grants
-- ---------------------------------------------------------------------
REVOKE ALL ON SCHEMA healthtrack FROM PUBLIC;
GRANT USAGE ON SCHEMA healthtrack TO healthtrack_api, healthtrack_analytics;

GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA healthtrack TO healthtrack_api;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA healthtrack TO healthtrack_api;
-- deletes only where the design allows them (no hard delete of patients or clinical history)
GRANT DELETE ON auth_sessions, caregivers, devices, notifications TO healthtrack_api;
-- history tables: insert and read only
REVOKE UPDATE ON audit_log, alert_events FROM healthtrack_api;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA healthtrack TO healthtrack_api;

-- ---------------------------------------------------------------------
-- row-level security (defense in depth behind API authorization)
-- the owner and superusers bypass these policies; the API role does not
-- ---------------------------------------------------------------------
ALTER TABLE patients ENABLE ROW LEVEL SECURITY;
CREATE POLICY patients_read ON patients FOR SELECT TO healthtrack_api
    USING (deleted_at IS NULL AND (can_access_patient(patient_id)
           OR app_user_role() = 'admin' OR created_by = app_user_id()));
CREATE POLICY patients_insert ON patients FOR INSERT TO healthtrack_api
    WITH CHECK (app_user_role() IN ('admin', 'clinician', 'physician') AND created_by = app_user_id());
CREATE POLICY patients_update ON patients FOR UPDATE TO healthtrack_api
    USING (can_access_patient(patient_id) OR app_user_role() = 'admin')
    WITH CHECK (can_access_patient(patient_id) OR app_user_role() = 'admin');

ALTER TABLE care_team_assignments ENABLE ROW LEVEL SECURITY;
CREATE POLICY care_team_read ON care_team_assignments FOR SELECT TO healthtrack_api
    USING (can_access_patient(patient_id) OR app_user_role() = 'admin');
CREATE POLICY care_team_write ON care_team_assignments FOR ALL TO healthtrack_api
    USING (app_user_role() IN ('admin', 'physician'))
    WITH CHECK (app_user_role() IN ('admin', 'physician'));

-- clinical tables share one rule: can_access_patient(patient_id)
DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['caregivers', 'exercise_prescriptions', 'devices', 'exercise_sessions',
                             'vital_signs', 'daily_activity', 'symptom_reports', 'appointments',
                             'patient_alert_thresholds', 'alerts', 'risk_assessments',
                             'care_recommendations'] LOOP
        EXECUTE format('ALTER TABLE healthtrack.%I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('CREATE POLICY %I ON healthtrack.%I FOR ALL TO healthtrack_api
                        USING (healthtrack.can_access_patient(patient_id))
                        WITH CHECK (healthtrack.can_access_patient(patient_id))', t || '_care_team', t);
    END LOOP;
END $$;

-- device inventory: IT administrators manage unassigned devices
CREATE POLICY devices_it_admin ON devices FOR ALL TO healthtrack_api
    USING (app_user_role() = 'it_admin' AND patient_id IS NULL)
    WITH CHECK (app_user_role() = 'it_admin' AND patient_id IS NULL);

-- child tables reach the patient through their parent
ALTER TABLE risk_factors ENABLE ROW LEVEL SECURITY;
CREATE POLICY risk_factors_care_team ON risk_factors FOR ALL TO healthtrack_api
    USING (EXISTS (SELECT 1 FROM risk_assessments r
                    WHERE r.assessment_id = risk_factors.assessment_id));

ALTER TABLE alert_events ENABLE ROW LEVEL SECURITY;
CREATE POLICY alert_events_care_team ON alert_events FOR ALL TO healthtrack_api
    USING (EXISTS (SELECT 1 FROM alerts a WHERE a.alert_id = alert_events.alert_id))
    WITH CHECK (EXISTS (SELECT 1 FROM alerts a WHERE a.alert_id = alert_events.alert_id));

ALTER TABLE notifications ENABLE ROW LEVEL SECURITY;
CREATE POLICY notifications_recipient ON notifications FOR ALL TO healthtrack_api
    USING (recipient_user_id = app_user_id()
           OR EXISTS (SELECT 1 FROM alerts a WHERE a.alert_id = notifications.alert_id));

-- the audit log is readable only by administrators; anyone may append
ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;
CREATE POLICY audit_append ON audit_log FOR INSERT TO healthtrack_api WITH CHECK (true);
CREATE POLICY audit_read   ON audit_log FOR SELECT TO healthtrack_api
    USING (app_user_role() IN ('admin', 'it_admin'));

-- refresh sessions belong to their user (login runs with app.user_id unset, so
-- the auth service inserts through the owner-level create_auth_session helper)
ALTER TABLE auth_sessions ENABLE ROW LEVEL SECURITY;
CREATE POLICY auth_sessions_own ON auth_sessions FOR ALL TO healthtrack_api
    USING (user_id = app_user_id()) WITH CHECK (user_id = app_user_id());

CREATE FUNCTION create_auth_session(p_user uuid, p_token_hash char(64), p_ttl interval,
                                    p_ip inet, p_agent varchar) RETURNS uuid
LANGUAGE sql SECURITY DEFINER SET search_path = healthtrack, pg_temp AS $$
    INSERT INTO auth_sessions (user_id, refresh_token_hash, expires_at, ip_address, user_agent)
    VALUES (p_user, p_token_hash, now() + p_ttl, p_ip, p_agent)
    RETURNING session_id;
$$;
GRANT EXECUTE ON FUNCTION create_auth_session(uuid, char, interval, inet, varchar) TO healthtrack_api;

COMMIT;
