-- create_tables.sql -- star schema for the Memphis events warehouse.
-- Design: docs/schema-design.md. Safe to re-run: every statement is idempotent.
-- Load order is dimensions first, then fact_events (see src/load.py).

BEGIN;

-- ---------------------------------------------------------------------------
-- Dimensions
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS dim_event_type (
    event_type_id    smallint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_type_name  text NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS dim_event_category (
    event_category_id    smallint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_category_name  text NOT NULL UNIQUE
);

-- group_id is the source id from data/reference/groups.json, not generated.
-- is_catch_all marks "Random Group" (id 29), the bucket for events with no group.
CREATE TABLE IF NOT EXISTS dim_group (
    group_id           integer PRIMARY KEY,
    group_name         text NOT NULL UNIQUE,
    group_description  text,
    is_catch_all       boolean NOT NULL DEFAULT false
);

-- At most one catch-all group.
CREATE UNIQUE INDEX IF NOT EXISTS dim_group_one_catch_all
    ON dim_group (is_catch_all) WHERE is_catch_all;

-- One row per calendar day, not only days with events.
CREATE TABLE IF NOT EXISTS dim_date (
    date_key     integer PRIMARY KEY,               -- YYYYMMDD
    full_date    date NOT NULL UNIQUE,
    year         smallint NOT NULL,
    quarter      smallint NOT NULL CHECK (quarter BETWEEN 1 AND 4),
    month        smallint NOT NULL CHECK (month BETWEEN 1 AND 12),
    month_name   text NOT NULL,
    month_start  date NOT NULL,
    day_of_week  smallint NOT NULL CHECK (day_of_week BETWEEN 1 AND 7),  -- ISO: 1 = Monday
    day_name     text NOT NULL,
    is_weekend   boolean NOT NULL
);

-- ---------------------------------------------------------------------------
-- Fact table: one row per event (grain). event_id is Contentful's sys.id.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS fact_events (
    event_id           text PRIMARY KEY CHECK (event_id <> ''),
    date_key           integer NOT NULL REFERENCES dim_date (date_key),
    event_date         date NOT NULL,
    event_time         time,                         -- local America/Chicago wall clock; NULL if unknown
    event_type_id      smallint NOT NULL REFERENCES dim_event_type (event_type_id),
    event_category_id  smallint NOT NULL REFERENCES dim_event_category (event_category_id),
    group_id           integer NOT NULL REFERENCES dim_group (group_id),
    name               text NOT NULL CHECK (name <> ''),
    description        text,
    short_intro        text,
    created_at         timestamptz NOT NULL,
    updated_at         timestamptz NOT NULL,
    is_active          boolean NOT NULL DEFAULT true,
    loaded_at          timestamptz NOT NULL DEFAULT now(),
    -- date_key must match event_date
    CONSTRAINT fact_events_date_key_matches CHECK (
        date_key = (EXTRACT(year FROM event_date)::int * 10000
                  + EXTRACT(month FROM event_date)::int * 100
                  + EXTRACT(day FROM event_date)::int)
    )
);

CREATE INDEX IF NOT EXISTS fact_events_event_date_idx ON fact_events (event_date, event_time);
CREATE INDEX IF NOT EXISTS fact_events_date_key_idx   ON fact_events (date_key);
CREATE INDEX IF NOT EXISTS fact_events_category_idx   ON fact_events (event_category_id);
CREATE INDEX IF NOT EXISTS fact_events_group_idx      ON fact_events (group_id);
CREATE INDEX IF NOT EXISTS fact_events_created_idx    ON fact_events (created_at);

-- ---------------------------------------------------------------------------
-- Static dimension values (the cleaned, standardized sets from transform.py)
-- ---------------------------------------------------------------------------

INSERT INTO dim_event_type (event_type_name)
VALUES ('In-Person'), ('Virtual'), ('Hybrid')
ON CONFLICT (event_type_name) DO NOTHING;

INSERT INTO dim_event_category (event_category_name)
VALUES ('Networking'), ('Tech Talk'), ('Workshop'), ('Entrepreneur'),
       ('Conference'), ('Hackathon'), ('AI')
ON CONFLICT (event_category_name) DO NOTHING;

-- ---------------------------------------------------------------------------
-- dim_date seed: 2025-09-01 through 2035-12-31. load.py extends it if an
-- event ever falls past the last row.
-- ---------------------------------------------------------------------------

INSERT INTO dim_date (date_key, full_date, year, quarter, month, month_name,
                      month_start, day_of_week, day_name, is_weekend)
SELECT
    EXTRACT(year FROM d)::int * 10000 + EXTRACT(month FROM d)::int * 100 + EXTRACT(day FROM d)::int,
    d::date,
    EXTRACT(year FROM d)::smallint,
    EXTRACT(quarter FROM d)::smallint,
    EXTRACT(month FROM d)::smallint,
    trim(to_char(d, 'Month')),
    date_trunc('month', d)::date,
    EXTRACT(isodow FROM d)::smallint,
    trim(to_char(d, 'Day')),
    EXTRACT(isodow FROM d) IN (6, 7)
FROM generate_series('2025-09-01'::date, '2035-12-31'::date, interval '1 day') AS g(d)
ON CONFLICT (date_key) DO NOTHING;

COMMIT;

-- dim_group is filled by load.py from data/reference/groups.json (including
-- is_catch_all = true for id 29), before fact_events is loaded.
