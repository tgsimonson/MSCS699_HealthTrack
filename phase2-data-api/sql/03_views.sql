-- =====================================================================
-- HealthTrack 03_views.sql
-- analytics views for dashboards, adherence, alert response, and
-- program metrics, then ownership transfer to the owner role
-- =====================================================================
-- patient-level views use security_invoker so row-level security still
-- applies to whoever queries them. v_program_metrics is aggregate-only
-- (no PHI) and is the administrator's window into the program.
-- =====================================================================

BEGIN;
SET search_path = healthtrack, public;

-- current snapshot per patient for the clinician worklist
CREATE VIEW v_patient_overview WITH (security_invoker = true) AS
SELECT p.patient_id,
       p.mrn,
       p.first_name,
       p.last_name,
       p.program_status,
       p.clinical_risk_category,
       p.enrollment_date,
       pc.user_id                         AS primary_clinician_id,
       sp.user_id                         AS supervising_physician_id,
       rx.prescription_id                 AS current_prescription_id,
       rx.target_hr_min,
       rx.target_hr_max,
       rx.hr_ceiling,
       rx.sessions_per_week,
       (SELECT count(*) FROM exercise_sessions s
         WHERE s.patient_id = p.patient_id AND s.status IN ('completed', 'partial'))  AS sessions_completed,
       p.target_sessions,
       (SELECT max(v.recorded_at) FROM vital_signs v WHERE v.patient_id = p.patient_id) AS last_reading_at,
       (SELECT count(*) FROM alerts a
         WHERE a.patient_id = p.patient_id AND a.status IN ('open', 'acknowledged', 'escalated')) AS open_alerts,
       (SELECT min(a.severity) FROM alerts a
         WHERE a.patient_id = p.patient_id AND a.status IN ('open', 'acknowledged', 'escalated')) AS worst_open_severity,
       ra.risk_score                      AS latest_risk_score,
       ra.risk_level                      AS latest_risk_level
  FROM patients p
  LEFT JOIN care_team_assignments pc ON pc.patient_id = p.patient_id AND pc.end_date IS NULL
                                    AND pc.team_role = 'primary_clinician'
  LEFT JOIN care_team_assignments sp ON sp.patient_id = p.patient_id AND sp.end_date IS NULL
                                    AND sp.team_role = 'supervising_physician'
  LEFT JOIN exercise_prescriptions rx ON rx.patient_id = p.patient_id AND rx.effective_to IS NULL
  LEFT JOIN LATERAL (SELECT r.risk_score, r.risk_level FROM risk_assessments r
                      WHERE r.patient_id = p.patient_id
                      ORDER BY r.assessed_at DESC LIMIT 1) ra ON true
 WHERE p.deleted_at IS NULL;

-- weekly adherence: sessions done versus prescribed, and minutes in zone
CREATE VIEW v_weekly_adherence WITH (security_invoker = true) AS
WITH weeks AS (
    SELECT s.patient_id,
           date_trunc('week', s.started_at AT TIME ZONE p.timezone)::date AS week_start,
           count(*) FILTER (WHERE s.status IN ('completed', 'partial'))    AS sessions_done,
           sum(s.minutes_in_zone)                                          AS minutes_in_zone,
           round(avg(s.avg_hr))                                            AS avg_exercise_hr,
           round(avg(s.rpe), 1)                                            AS avg_rpe
      FROM exercise_sessions s
      JOIN patients p ON p.patient_id = s.patient_id
     GROUP BY s.patient_id, week_start
)
SELECT w.patient_id,
       w.week_start,
       w.sessions_done,
       rx.sessions_per_week                                                        AS sessions_prescribed,
       round(100.0 * least(w.sessions_done, rx.sessions_per_week) / rx.sessions_per_week, 1) AS adherence_pct,
       w.minutes_in_zone,
       w.avg_exercise_hr,
       w.avg_rpe
  FROM weeks w
  JOIN exercise_prescriptions rx
    ON rx.patient_id = w.patient_id
   AND rx.effective_from <= (w.week_start + 6)::timestamp
   AND (rx.effective_to IS NULL OR rx.effective_to > w.week_start::timestamp);

-- daily vital summary for trend charts and model features
CREATE VIEW v_daily_vital_summary WITH (security_invoker = true) AS
SELECT v.patient_id,
       (v.recorded_at AT TIME ZONE p.timezone)::date            AS reading_date,
       v.context,
       count(*)                                                 AS readings,
       round(avg(v.heart_rate))                                 AS avg_hr,
       min(v.heart_rate)                                        AS min_hr,
       max(v.heart_rate)                                        AS max_hr,
       round(avg(v.systolic_bp))                                AS avg_sbp,
       round(avg(v.diastolic_bp))                               AS avg_dbp,
       min(v.spo2)                                              AS min_spo2,
       count(*) FILTER (WHERE v.quality <> 'valid')             AS flagged_readings
  FROM vital_signs v
  JOIN patients p ON p.patient_id = v.patient_id
 GROUP BY v.patient_id, reading_date, v.context;

-- alert response times for quality review and threshold tuning
CREATE VIEW v_alert_response WITH (security_invoker = true) AS
SELECT a.alert_id,
       a.patient_id,
       r.rule_code,
       a.severity,
       a.status,
       a.triggered_at,
       a.acknowledged_at,
       a.resolved_at,
       a.escalation_level,
       round(extract(epoch FROM a.acknowledged_at - a.triggered_at) / 60.0, 1) AS minutes_to_ack,
       round(extract(epoch FROM a.resolved_at - a.triggered_at) / 60.0, 1)     AS minutes_to_resolve
  FROM alerts a
  JOIN alert_rules r ON r.rule_id = a.rule_id;

-- program metrics: aggregate only, no identifiers (administrator view)
CREATE VIEW v_program_metrics AS
SELECT
    (SELECT count(*) FROM patients WHERE deleted_at IS NULL)                                AS patients_total,
    (SELECT count(*) FROM patients WHERE program_status = 'referred'  AND deleted_at IS NULL) AS referred,
    (SELECT count(*) FROM patients WHERE program_status = 'active'    AND deleted_at IS NULL) AS active,
    (SELECT count(*) FROM patients WHERE program_status = 'paused'    AND deleted_at IS NULL) AS paused,
    (SELECT count(*) FROM patients WHERE program_status = 'graduated' AND deleted_at IS NULL) AS graduated,
    (SELECT count(*) FROM patients WHERE program_status = 'withdrawn' AND deleted_at IS NULL) AS withdrawn,
    (SELECT round(100.0 * count(*) FILTER (WHERE program_status = 'graduated')
                  / nullif(count(*) FILTER (WHERE program_status IN ('graduated', 'withdrawn')), 0), 1)
       FROM patients WHERE deleted_at IS NULL)                                             AS completion_rate_pct,
    (SELECT count(*) FROM exercise_sessions WHERE status IN ('completed', 'partial'))       AS sessions_completed,
    (SELECT count(*) FROM alerts WHERE severity = 'critical')                               AS alerts_critical,
    (SELECT count(*) FROM alerts WHERE severity = 'high')                                   AS alerts_high,
    (SELECT count(*) FROM alerts WHERE severity = 'moderate')                               AS alerts_moderate,
    (SELECT count(*) FROM alerts WHERE severity = 'low')                                    AS alerts_low,
    (SELECT round(avg(extract(epoch FROM acknowledged_at - triggered_at) / 60.0)::numeric, 1)
       FROM alerts WHERE severity = 'critical' AND acknowledged_at IS NOT NULL)             AS critical_avg_minutes_to_ack;
COMMENT ON VIEW v_program_metrics IS 'Aggregate program metrics with no patient identifiers. Runs with owner rights so administrators can see totals without row access to PHI.';

GRANT SELECT ON v_patient_overview, v_weekly_adherence, v_daily_vital_summary, v_alert_response,
                v_program_metrics TO healthtrack_api;
GRANT SELECT ON v_program_metrics TO healthtrack_analytics;

-- ---------------------------------------------------------------------
-- transfer ownership so SECURITY DEFINER functions run as a non-superuser
-- ---------------------------------------------------------------------
DO $$
DECLARE r record;
BEGIN
    EXECUTE 'ALTER SCHEMA healthtrack OWNER TO healthtrack_owner';
    FOR r IN SELECT c.relname, c.relkind FROM pg_class c
               JOIN pg_namespace n ON n.oid = c.relnamespace
              WHERE n.nspname = 'healthtrack' AND c.relkind IN ('r', 'v') LOOP
        EXECUTE format('ALTER %s healthtrack.%I OWNER TO healthtrack_owner',
                       CASE r.relkind WHEN 'v' THEN 'VIEW' ELSE 'TABLE' END, r.relname);
    END LOOP;
    FOR r IN SELECT p.oid::regprocedure AS sig FROM pg_proc p
               JOIN pg_namespace n ON n.oid = p.pronamespace
              WHERE n.nspname = 'healthtrack' LOOP
        EXECUTE format('ALTER FUNCTION %s OWNER TO healthtrack_owner', r.sig);
    END LOOP;
    FOR r IN SELECT t.typname FROM pg_type t
               JOIN pg_namespace n ON n.oid = t.typnamespace
              WHERE n.nspname = 'healthtrack' AND t.typtype = 'e' LOOP
        EXECUTE format('ALTER TYPE healthtrack.%I OWNER TO healthtrack_owner', r.typname);
    END LOOP;
END $$;

COMMIT;
