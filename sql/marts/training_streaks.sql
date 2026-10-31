-- QUESTION: What are my longest streaks of training on consecutive days?
-- Classic "gaps and islands" problem. Trick: number the training days 1, 2, 3, ... in date order.
-- Inside a streak, the date and the row number both go up by 1 every day, so (date - row_number) stays
-- the SAME. When a day is skipped, the date jumps by 2 but the row number only by 1, so the value changes.
-- That value is therefore a label for the streak.
--
--   date        row_number   date - row_number
--   2026-03-01  1            2026-02-28   <- streak A
--   2026-03-02  2            2026-02-28   <- streak A
--   2026-03-03  3            2026-02-28   <- streak A
--   2026-03-05  4            2026-03-01   <- streak B (03-04 was skipped)
CREATE OR REPLACE VIEW marts.training_streaks AS
WITH training_days AS (                            -- one row per day with at least one activity
    SELECT DISTINCT activity_date
    FROM core.fact_activities
),
labeled AS (
    SELECT
        activity_date,
        activity_date - (ROW_NUMBER() OVER (ORDER BY activity_date))::int AS streak_label
    FROM training_days
)
SELECT
    MIN(activity_date)  AS streak_start,
    MAX(activity_date)  AS streak_end,
    COUNT(*)            AS days
FROM labeled
GROUP BY streak_label;

-- Example: SELECT * FROM marts.training_streaks ORDER BY days DESC LIMIT 5;
