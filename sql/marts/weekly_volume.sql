-- QUESTION: How much did I train each week, per category (run, swim, ...)?
-- One row = one week + one category.
CREATE OR REPLACE VIEW marts.weekly_volume AS
SELECT
    DATE_TRUNC('week', activity_date)::date      AS week_start,   -- Monday of that week
    category,
    COUNT(*)                                      AS activities,
    ROUND(SUM(distance_km), 1)                    AS distance_km,
    ROUND(SUM(moving_time_s) / 3600.0, 1)         AS hours         -- seconds -> hours (3600.0 so it is not integer division)
FROM core.fact_activities
GROUP BY 1, 2;                                    -- 1, 2 = the first two columns (week_start, category)

-- Example: SELECT * FROM marts.weekly_volume WHERE category = 'run' ORDER BY week_start DESC LIMIT 10;
