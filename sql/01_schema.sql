-- Layered warehouse: raw (exactly what the API returned) -> staging (typed, cleaned) -> core (model) -> marts (answers)
CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS staging;
CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS marts;

-- RAW: one row per Strava activity, the full JSON payload as delivered by the API.
-- Re-running the load never creates duplicates (primary key + upsert in extract_load.py).
CREATE TABLE IF NOT EXISTS raw.strava_activities (
    activity_id  BIGINT PRIMARY KEY,
    payload      JSONB       NOT NULL,
    fetched_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- RAW: detailed activity (one extra API call per run), mainly for Strava's "best efforts".
CREATE TABLE IF NOT EXISTS raw.strava_activity_details (
    activity_id  BIGINT PRIMARY KEY,
    payload      JSONB       NOT NULL,
    fetched_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Bookkeeping for every pipeline run (useful for monitoring and debugging).
CREATE TABLE IF NOT EXISTS raw.load_runs (
    run_id        BIGSERIAL PRIMARY KEY,
    started_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at   TIMESTAMPTZ,
    rows_fetched  INTEGER,
    status        TEXT NOT NULL DEFAULT 'running'   -- running | success | failed
);
