-- QUESTION: What are my fastest 5 km, 10 km and half marathon runs?
-- Note: Strava's activity list only has the average pace of the whole run, so a "10 km PB" here is
-- the fastest run whose total distance was about 10 km (not the fastest 10 km inside a longer run).
CREATE OR REPLACE VIEW marts.personal_bests AS
WITH runs AS (                                     -- step 1: put every run into a distance bucket
    SELECT
        activity_id,
        activity_date,
        distance_km,
        pace_min_per_km,
        CASE
            WHEN distance_km BETWEEN 4.9  AND 5.5  THEN '5K'
            WHEN distance_km BETWEEN 9.8  AND 10.8 THEN '10K'
            WHEN distance_km BETWEEN 21.0 AND 22.0 THEN 'Half marathon'
        END                                        AS distance_bucket,
        CASE                                       -- official distance, to estimate the finish time
            WHEN distance_km BETWEEN 4.9  AND 5.5  THEN 5
            WHEN distance_km BETWEEN 9.8  AND 10.8 THEN 10
            WHEN distance_km BETWEEN 21.0 AND 22.0 THEN 21.0975
        END                                        AS official_km
    FROM core.fact_activities
    WHERE category = 'run'
      AND pace_min_per_km BETWEEN 2.5 AND 12
),
ranked AS (                                        -- step 2: rank the runs inside each bucket, fastest = 1
    SELECT
        *,
        ROW_NUMBER() OVER (PARTITION BY distance_bucket ORDER BY pace_min_per_km) AS rank
    FROM runs
    WHERE distance_bucket IS NOT NULL
)
SELECT                                             -- step 3: keep the top 3 of each bucket
    distance_bucket,
    rank,
    activity_id,
    activity_date,
    distance_km,
    pace_min_per_km,
    MAKE_INTERVAL(secs => ROUND(pace_min_per_km * 60 * official_km)) AS estimated_time
FROM ranked
WHERE rank <= 3;

-- Example: SELECT * FROM marts.personal_bests ORDER BY distance_bucket, rank;
