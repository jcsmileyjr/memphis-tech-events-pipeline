-- create_api_user.sql -- read-only role for the stats API (api/).
-- NOT run by the API or any script. Run it yourself in pgAdmin as the
-- postgres user, connected to the Memphis events database.
--
-- 1. Replace CHANGE_ME below with a strong password (do not commit it).
-- 2. Put the same role name and password in .env as API_DB_USER / API_DB_PASSWORD.
--
-- Safe to re-run: the role is only created if missing; grants are idempotent.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'api_reader') THEN
        CREATE ROLE api_reader LOGIN PASSWORD 'CHANGE_ME';
    END IF;
END
$$;

-- CONNECT on the database you are currently connected to.
DO $$
BEGIN
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO api_reader', current_database());
END
$$;

GRANT USAGE ON SCHEMA public TO api_reader;

-- SELECT only, and only on the tables the API reads.
GRANT SELECT ON fact_events, dim_event_type, dim_event_category, dim_group TO api_reader;
