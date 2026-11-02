-- =====================================================================
-- HealthTrack: build the database from scratch
-- usage:  createdb healthtrack
--         psql -d healthtrack -v ON_ERROR_STOP=1 -f 00_run_all.sql
-- run as a superuser or a role allowed to create extensions and roles
-- =====================================================================
\set ON_ERROR_STOP on
\echo '== 01 schema'
\i 01_schema.sql
\echo '== 02 security'
\i 02_security.sql
\echo '== 03 views'
\i 03_views.sql
\echo '== 04 sample data'
\i 04_sample_data.sql
\echo '== 05 validation tests'
\i 05_validation_tests.sql
