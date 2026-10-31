# Strava data pipeline

An automated ELT pipeline that loads my Strava activities into PostgreSQL every day and models them
into analytics tables with SQL.

> **Status: in progress.** Extract & load, all four layers (raw → staging → core → marts) and tests are done. Next: a dashboard.

## Architecture

```
Strava API ──(Python, GitHub Actions, daily)──> PostgreSQL
                                                 ├── raw       JSON exactly as the API returned it
                                                 ├── staging   typed columns, units converted
                                                 ├── core      dim_sport + fact_activities
                                                 └── marts     answers: weekly volume, pace trend, PBs, streaks
                                                        └──> dashboard
```

**Design choices**
* **ELT, not ETL:** the raw JSON is stored first and transformed in SQL. If a transformation changes, nothing has to be downloaded again.
* **Incremental load:** each run only asks Strava for activities newer than the latest one in the database (minus one week, so edited activities are refreshed).
* **Idempotent:** `activity_id` is the primary key and the load is an upsert, so re-running a job never creates duplicates.
* **Observable:** every run is written to `raw.load_runs` with its status and row count.
* **Tested:** an end-to-end test runs the pipeline against a real PostgreSQL (in CI) with fake Strava data.

## Project structure

```
etl/extract_load.py        extract from Strava, load into raw
sql/01_schema.sql          schemas, raw tables
sql/02_staging.sql         staging.activities
sql/03_core.sql            core.dim_sport, core.fact_activities
sql/marts/                 analytics views: weekly_volume, pace_trend, personal_bests, training_streaks
tests/test_pipeline.py     end-to-end test
.github/workflows/         daily ETL job + tests on every push
```

## The marts

| View | Question | SQL technique |
|---|---|---|
| `marts.weekly_volume` | How much did I train each week, per sport? | `DATE_TRUNC`, `GROUP BY` |
| `marts.pace_trend` | Am I getting faster? | window function, 5-run moving average |
| `marts.personal_bests` | Fastest 5K, 10K and half marathon? | CTEs, `CASE`, `ROW_NUMBER() OVER (PARTITION BY ...)` |
| `marts.training_streaks` | Longest streaks of consecutive training days? | gaps-and-islands (`date - ROW_NUMBER()`) |

## Run it

```bash
pip install -r requirements.txt
cp .env.example .env      # fill in your database URL and Strava API credentials
export $(cat .env | xargs)
python -m etl.extract_load
```

**Tech:** Python, PostgreSQL, SQL (window functions, CTEs), GitHub Actions, pytest
