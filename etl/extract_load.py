"""
Extract activities from the Strava API and load them into PostgreSQL (raw layer).

* Incremental: only asks Strava for activities newer than the latest one already in the database.
* Idempotent: running it twice never creates duplicates (upsert on activity_id).
* Every run is logged in raw.load_runs.

* Details backfill: for runs, the detailed activity (with Strava's "best efforts", e.g. the fastest 5 km
  inside a longer run) needs one extra API call per run. To stay inside Strava's rate limit, each pipeline
  run fetches at most DETAILS_PER_RUN of them (newest first); the rest are picked up by the next runs.

Environment variables: DATABASE_URL, STRAVA_CLIENT_ID, STRAVA_CLIENT_SECRET, STRAVA_REFRESH_TOKEN
Optional: FULL_REFRESH=1 to re-download everything, DETAILS_PER_RUN (default 80).
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
DETAILS_PER_RUN = int(os.getenv("DETAILS_PER_RUN", "80"))   # Strava allows ~100 read requests / 15 min


class RateLimited(Exception):
    pass


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


def fetch_activity_detail(token: str, activity_id: int) -> dict:
    """The detailed activity, including 'best_efforts' for runs."""
    r = requests.get(f"{API}/activities/{activity_id}", headers={"Authorization": f"Bearer {token}"},
                     params={"include_all_efforts": "false"}, timeout=30)
    if r.status_code == 429:
        raise RateLimited()
    r.raise_for_status()
    return r.json()


def runs_missing_details(conn, limit: int) -> list[int]:
    return [row[0] for row in conn.execute(
        """SELECT a.activity_id
           FROM raw.strava_activities a
           LEFT JOIN raw.strava_activity_details d USING (activity_id)
           WHERE d.activity_id IS NULL
             AND a.payload->>'sport_type' IN ('Run', 'TrailRun', 'VirtualRun')
           ORDER BY a.payload->>'start_date' DESC
           LIMIT %s""", (limit,)).fetchall()]


def load_details(conn, token: str, fetch_detail, limit: int) -> int:
    """Fetch and store details for up to `limit` runs. Stops quietly at the rate limit."""
    loaded = 0
    for activity_id in runs_missing_details(conn, limit):
        try:
            detail = fetch_detail(token, activity_id)
        except RateLimited:
            print("  rate limit reached, the remaining runs will be fetched next time")
            break
        conn.execute("""INSERT INTO raw.strava_activity_details (activity_id, payload, fetched_at)
                        VALUES (%s, %s, now())
                        ON CONFLICT (activity_id) DO UPDATE
                        SET payload = EXCLUDED.payload, fetched_at = EXCLUDED.fetched_at""",
                     (activity_id, json.dumps(detail)))
        loaded += 1
    return loaded


def setup_schema(conn) -> None:
    """Create / update all layers. Marts are views, so they always show the latest data."""
    files = [SQL_DIR / f for f in ["01_schema.sql", "02_staging.sql", "03_core.sql"]]
    files += sorted((SQL_DIR / "marts").glob("*.sql"))
    for f in files:
        conn.execute(f.read_text())


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


def run(fetch=fetch_activities, get_token=get_access_token, fetch_detail=fetch_activity_detail) -> int:
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        setup_schema(conn)
        run_id = conn.execute("INSERT INTO raw.load_runs DEFAULT VALUES RETURNING run_id").fetchone()[0]
        try:
            after = 0 if os.getenv("FULL_REFRESH") == "1" else max(0, latest_start_epoch(conn) - OVERLAP_S)
            print(f"Fetching activities after epoch {after} ...")
            token = get_token()
            activities = fetch(token, after)
            with conn.transaction():
                upsert(conn, activities)
            details = load_details(conn, token, fetch_detail, DETAILS_PER_RUN)
            missing = len(runs_missing_details(conn, 100_000))
            print(f"Loaded details for {details} runs ({missing} runs still without details)")
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
