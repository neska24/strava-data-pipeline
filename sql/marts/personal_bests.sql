-- QUESTION: What are my fastest 1 km, 5 km, 10 km and half marathon?
-- Uses Strava's "best efforts": the fastest time over each distance ANYWHERE inside a run.
-- So a fast 5 km in the middle of a 12 km run counts too (unlike using the total distance of a run).
-- The column list changed in this version, so the old view is dropped first.
DROP VIEW IF EXISTS marts.personal_bests;
CREATE VIEW marts.personal_bests AS
WITH ranked AS (
    SELECT
        CASE lower(effort_name)                            -- lower(): don't depend on how Strava capitalises
            WHEN '1k' THEN '1K' WHEN '5k' THEN '5K' WHEN '10k' THEN '10K'
            WHEN 'half-marathon' THEN 'Half marathon'
        END                                                AS distance,
        activity_id,
        activity_date,
        elapsed_time_s,
        pace_min_per_km,
        ROW_NUMBER() OVER (
            PARTITION BY effort_name                       -- a separate ranking for each distance
            ORDER BY elapsed_time_s, activity_date         -- fastest first; on a tie, the earlier run wins
        )                                                  AS rank
    FROM core.fact_best_efforts
    WHERE lower(effort_name) IN ('1k', '5k', '10k', 'half-marathon')
)
SELECT
    distance,
    rank,
    activity_id,
    activity_date,
    MAKE_INTERVAL(secs => elapsed_time_s)                  AS time,
    pace_min_per_km
FROM ranked
WHERE rank <= 3;

-- Example: SELECT * FROM marts.personal_bests ORDER BY distance, rank;
