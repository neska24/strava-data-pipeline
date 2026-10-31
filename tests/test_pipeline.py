"""
End-to-end test with a local PostgreSQL and fake Strava data (no API calls).
Run:  DATABASE_URL=postgresql://... pytest -q
"""
import os
import random
from datetime import datetime, timedelta, timezone

import psycopg
import pytest

from etl import extract_load

SPORTS = [("Run", 10_000, 330), ("Ride", 40_000, 120), ("Hike", 8_000, 700), ("WeightTraining", 0, 0)]


def fake_activity(i: int, start: datetime) -> dict:
    sport, dist, sec_per_km = random.choice(SPORTS)
    dist = dist * random.uniform(0.5, 2.1)
    moving = int(dist / 1000 * sec_per_km) if dist else 3600
    return {
        "id": 1_000_000 + i, "name": f"Activity {i}", "sport_type": sport, "type": sport,
        "start_date": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "start_date_local": (start + timedelta(hours=9)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "timezone": "(GMT+09:00) Asia/Seoul", "distance": round(dist, 1),
        "moving_time": moving, "elapsed_time": moving + 120, "total_elevation_gain": 50.0,
        "average_heartrate": 140.0, "max_heartrate": 170.0, "suffer_score": 30.0,
        "trainer": sport == "WeightTraining", "visibility": "everyone", "device_name": "COROS PACE 3",
        "map": {"summary_polyline": "" if sport == "WeightTraining" else "abc"},
    }


@pytest.fixture()
def db():
    url = os.environ["DATABASE_URL"]
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS raw, staging, core, marts CASCADE")
    return url


def test_load_is_incremental_and_idempotent(db, monkeypatch):
    random.seed(1)
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    acts = [fake_activity(i, t0 + timedelta(days=i)) for i in range(60)]

    calls = []
    def fake_fetch(token, after):
        calls.append(after)
        return [a for a in acts if datetime.strptime(a["start_date"], "%Y-%m-%dT%H:%M:%SZ")
                .replace(tzinfo=timezone.utc).timestamp() > after]

    monkeypatch.setattr(extract_load, "get_access_token", lambda: "token")
    assert extract_load.run(fetch=fake_fetch, get_token=lambda: "t") == 0     # first full load
    assert extract_load.run(fetch=fake_fetch, get_token=lambda: "t") == 0     # second run: incremental

    with psycopg.connect(db) as conn:
        assert conn.execute("SELECT count(*) FROM raw.strava_activities").fetchone()[0] == 60   # no duplicates
        assert calls[0] == 0 and calls[1] > 0                                                 # 2nd run asks only for new ones
        runs = conn.execute("SELECT status, rows_fetched FROM raw.load_runs ORDER BY run_id").fetchall()
        assert [r[0] for r in runs] == ["success", "success"] and runs[1][1] < 60
        n, cats = conn.execute("SELECT count(*), count(DISTINCT category) FROM core.fact_activities").fetchone()
        assert n == 60 and cats >= 3
        bad_pace = conn.execute("SELECT count(*) FROM core.fact_activities "
                                "WHERE category = 'run' AND pace_min_per_km NOT BETWEEN 3 AND 10").fetchone()[0]
        assert bad_pace == 0


def test_failed_run_is_logged(db):
    def broken_fetch(token, after):
        raise RuntimeError("Strava is down")
    assert extract_load.run(fetch=broken_fetch, get_token=lambda: "t") == 1
    with psycopg.connect(db) as conn:
        assert conn.execute("SELECT status FROM raw.load_runs").fetchone()[0] == "failed"
