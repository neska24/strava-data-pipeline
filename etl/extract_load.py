"""
Extract activities from the Strava API and load them into PostgreSQL (raw layer).

* Incremental: only asks Strava for activities newer than the latest one already in the database.
* Idempotent: running it twice never creates duplicates (upsert on activity_id).
* Every run is logged in raw.load_runs.

Environment variables: DATABASE_URL, STRAVA_CLIENT_ID, STRAVA_CLIENT_SECRET, STRAVA_REFRESH_TOKEN
Optional: FULL_REFRESH=1 to re-download everything.
"""
import json
import os
import sys
import time
from pathlib import Path

import psycopg
import requests

API = "https://www.strava.com/api/v3"
SQL_DIR = Path(__file__).resolve().parent.parent / "sql"
PER_PAGE = 200
OVERLAP_S = 7 * 24 * 3600   # re-fetch the last week, so edited activities (new name etc.) are updated too


def get_access_token() -> str:
    r = requests.post("https://www.strava.com/oauth/token", data={
        "client_id": os.environ["STRAVA_CLIENT_ID"],
        "client_secret": os.environ["STRAVA_CLIENT_SECRET"],
        "refresh_token": os.environ["STRAVA_REFRESH_TOKEN"],
        "grant_type": "refresh_token",
    }, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def fetch_activities(token: str, after_epoch: int) -> list[dict]:
    """All activities that started after `after_epoch` (unix seconds), page by page."""
    activities, page = [], 1
    while True:
        r = requests.get(f"{API}/athlete/activities",
                         headers={"Authorization": f"Bearer {token}"},
                         params={"after": after_epoch, "per_page": PER_PAGE, "page": page},
                         timeout=30)
        if r.status_code == 429:                       # rate limit: wait and retry the same page
            print("Rate limited, waiting 60 s ...")
            time.sleep(60)
            continue
        r.raise_for_status()
        batch = r.json()
        if not batch:
            return activities
        activities.extend(batch)
        print(f"  page {page}: {len(batch)} activities")
        page += 1


def setup_schema(conn) -> None:
    for f in ["01_schema.sql", "02_staging.sql", "03_core.sql"]:
        conn.execute((SQL_DIR / f).read_text())


def latest_start_epoch(conn) -> int:
    row = conn.execute(
        "SELECT EXTRACT(EPOCH FROM max((payload->>'start_date')::timestamptz))::bigint "
        "FROM raw.strava_activities").fetchone()
    return row[0] or 0


def upsert(conn, activities: list[dict]) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO raw.strava_activities (activity_id, payload, fetched_at)
               VALUES (%s, %s, now())
               ON CONFLICT (activity_id) DO UPDATE
               SET payload = EXCLUDED.payload, fetched_at = EXCLUDED.fetched_at""",
            [(a["id"], json.dumps(a)) for a in activities])


def run(fetch=fetch_activities, get_token=get_access_token) -> int:
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        setup_schema(conn)
        run_id = conn.execute("INSERT INTO raw.load_runs DEFAULT VALUES RETURNING run_id").fetchone()[0]
        try:
            after = 0 if os.getenv("FULL_REFRESH") == "1" else max(0, latest_start_epoch(conn) - OVERLAP_S)
            print(f"Fetching activities after epoch {after} ...")
            activities = fetch(get_token(), after)
            with conn.transaction():
                upsert(conn, activities)
            conn.execute("UPDATE raw.load_runs SET finished_at = now(), rows_fetched = %s, status = 'success' "
                         "WHERE run_id = %s", (len(activities), run_id))
            total = conn.execute("SELECT count(*) FROM raw.strava_activities").fetchone()[0]
            print(f"Loaded {len(activities)} activities. Total in database: {total}")
            return 0
        except Exception as e:
            conn.execute("UPDATE raw.load_runs SET finished_at = now(), status = 'failed' WHERE run_id = %s",
                         (run_id,))
            print(f"FAILED: {e}", file=sys.stderr)
            return 1


if __name__ == "__main__":
    sys.exit(run())
