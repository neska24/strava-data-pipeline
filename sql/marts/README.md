# Marts: your SQL tasks

Each mart answers one question. Write each one as a `CREATE OR REPLACE VIEW marts.<name> AS ...` in its own file
(`sql/marts/<name>.sql`). Build on `core.fact_activities`, not on the raw table.

| # | File | Question | Columns | SQL you will practise |
|---|------|----------|---------|-----------------------|
| 1 | `weekly_volume.sql` | How much did I train each week, per category? | `week_start, category, activities, distance_km, hours` | `DATE_TRUNC`, `GROUP BY`, `SUM`, `COUNT` |
| 2 | `pace_trend.sql` | Am I getting faster? | `activity_date, pace_min_per_km, pace_5_run_avg` | window function: `AVG(...) OVER (ORDER BY ... ROWS BETWEEN 4 PRECEDING AND CURRENT ROW)` |
| 3 | `personal_bests.sql` | What is my fastest run for 5 km, 10 km and 21 km? | `distance_bucket, activity_id, activity_date, pace_min_per_km` | `CASE`, `ROW_NUMBER() OVER (PARTITION BY ... ORDER BY ...)`, CTE |
| 4 | `training_streaks.sql` | What are my longest streaks of consecutive training days? | `streak_start, streak_end, days` | "gaps and islands": `LAG` or `date - ROW_NUMBER()` trick |

Tips
* Start each one with a small `SELECT` and look at the result before you wrap it in `CREATE VIEW`.
* Runs only: `WHERE category = 'run'`.
* For 3, a "10 km run" can be 9.5–10.5 km. Decide the bucket edges yourself and write them in a comment.
