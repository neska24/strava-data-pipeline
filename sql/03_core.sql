-- CORE: a small star schema.
-- dim_sport maps Strava's many sport types to a few categories.
CREATE TABLE IF NOT EXISTS core.dim_sport (
    sport_type  TEXT PRIMARY KEY,
    category    TEXT NOT NULL      -- run | ride | swim | hike | strength | other
);

INSERT INTO core.dim_sport (sport_type, category) VALUES
    ('Run', 'run'), ('TrailRun', 'run'), ('VirtualRun', 'run'),
    ('Ride', 'ride'), ('VirtualRide', 'ride'), ('GravelRide', 'ride'), ('MountainBikeRide', 'ride'),
    ('Swim', 'swim'),
    ('Hike', 'hike'), ('Walk', 'hike'),
    ('WeightTraining', 'strength'), ('Workout', 'strength'), ('Crossfit', 'strength'),
    ('Yoga', 'other')
ON CONFLICT (sport_type) DO NOTHING;

-- fact_activities: one row per activity with the measures the marts need.
CREATE OR REPLACE VIEW core.fact_activities AS
SELECT
    a.activity_id,
    a.start_time_local::date                                   AS activity_date,
    a.start_time_local,
    a.sport_type,
    COALESCE(s.category, 'other')                              AS category,
    a.distance_km,
    a.moving_time_s,
    a.elevation_gain_m,
    a.avg_heartrate,
    a.relative_effort,
    a.is_indoor,
    -- pace (min/km) only makes sense for activities on foot with a real distance
    CASE WHEN s.category IN ('run', 'hike') AND a.distance_km > 0.5
         THEN round(a.moving_time_s / 60.0 / a.distance_km, 2) END AS pace_min_per_km
FROM staging.activities a
LEFT JOIN core.dim_sport s USING (sport_type);

-- fact_best_efforts: the fastest time over a standard distance inside each run.
CREATE OR REPLACE VIEW core.fact_best_efforts AS
SELECT
    activity_id,
    start_time_local::date                                        AS activity_date,
    effort_name,
    distance_m,
    elapsed_time_s,
    round(elapsed_time_s / 60.0 / (distance_m / 1000), 2)         AS pace_min_per_km
FROM staging.best_efforts
WHERE distance_m > 0;
