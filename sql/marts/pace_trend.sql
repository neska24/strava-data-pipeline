-- QUESTION: Am I getting faster?
-- For every run: its pace, and the average pace of the last 5 runs (a "moving average"),
-- which smooths out single slow or fast days so the trend is visible.
CREATE OR REPLACE VIEW marts.pace_trend AS
SELECT
    activity_id,
    activity_date,
    distance_km,
    pace_min_per_km,
    ROUND(
        AVG(pace_min_per_km) OVER (
            ORDER BY start_time_local                      -- go through the runs in time order
            ROWS BETWEEN 4 PRECEDING AND CURRENT ROW       -- this run + the 4 before it = 5 runs
        ), 2)                                              AS pace_5_run_avg
FROM core.fact_activities
WHERE category = 'run'
  AND pace_min_per_km BETWEEN 2.5 AND 12;                  -- drop GPS errors and runs that were mostly walking

-- Example: SELECT * FROM marts.pace_trend ORDER BY activity_date DESC LIMIT 20;
