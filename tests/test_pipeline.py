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

NO_DETAIL = lambda token, activity_id: {"id": activity_id, "best_efforts": []}

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
    assert extract_load.run(fetch=fake_fetch, get_token=lambda: "t", fetch_detail=NO_DETAIL) == 0  # full load
    assert extract_load.run(fetch=fake_fetch, get_token=lambda: "t", fetch_detail=NO_DETAIL) == 0  # incremental

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
    assert extract_load.run(fetch=broken_fetch, get_token=lambda: "t", fetch_detail=NO_DETAIL) == 1
    with psycopg.connect(db) as conn:
        assert conn.execute("SELECT status FROM raw.load_runs").fetchone()[0] == "failed"


def _run(i, day, km, pace_min, sport="Run"):
    """A hand-made activity on a given date (UTC morning) with an exact distance and pace."""
    a = fake_activity(i, datetime(2026, 3, day, 0, 0, tzinfo=timezone.utc))
    a.update(sport_type=sport, type=sport, distance=km * 1000,
             moving_time=int(km * pace_min * 60), map={"summary_polyline": "abc"})
    return a


def test_marts(db):
    acts = [
        _run(1, 2, 5.0, 5.0), _run(2, 3, 5.2, 4.5), _run(3, 4, 10.0, 5.5),   # Mon-Wed: 3-day streak
        _run(4, 6, 21.1, 6.0), _run(5, 7, 30.0, 0, sport="Ride"),             # Fri-Sat: 2-day streak
        _run(6, 7, 5.0, 1.0),                                                  # impossible pace -> filtered out
    ]
    acts[4]["moving_time"] = 3600
    # best efforts (names exactly as Strava sends them: "5K", "10K", "Half-Marathon"): run 3 (10 km) contains the fastest 5 km (20:00), faster than the 5 km run 2 (23:24)
    efforts = {
        1_000_002: [("5K", 5000, 1404, "2026-03-03T07:00:00Z")],
        1_000_003: [("5K", 5000, 1200, "2026-03-04T07:00:00Z"), ("10K", 10000, 3300, "2026-03-04T07:00:00Z")],
        1_000_004: [("Half-Marathon", 21097, 7500, "2026-03-06T07:00:00Z")],
    }
    def detail(token, activity_id):
        return {"id": activity_id, "best_efforts": [
            {"name": n, "distance": d, "elapsed_time": t, "start_date_local": sd}
            for n, d, t, sd in efforts.get(activity_id, [])]}
    assert extract_load.run(fetch=lambda t, after: acts, get_token=lambda: "t", fetch_detail=detail) == 0

    with psycopg.connect(db) as conn:
        q = lambda sql: conn.execute(sql).fetchall()
        # weekly_volume: totals per week & category add up
        wk = q("SELECT week_start::text, category, activities, distance_km::float FROM marts.weekly_volume "
               "ORDER BY category")
        assert ("2026-03-02", "ride", 1, 30.0) in wk
        assert ("2026-03-02", "run", 5, 46.3) in wk
        # pace_trend: bad pace removed, moving average of the first two runs = (5.0 + 4.5) / 2
        pt = q("SELECT pace_min_per_km::float, pace_5_run_avg::float FROM marts.pace_trend ORDER BY activity_date")
        assert len(pt) == 4 and pt[1] == (4.5, 4.75)
        # personal_bests (from best efforts): the 5 km inside the 10 km run is the PB
        pb = q("SELECT distance, rank, activity_id, time::text FROM marts.personal_bests ORDER BY distance, rank")
        assert ("5K", 1, 1_000_003, "00:20:00") in pb and ("5K", 2, 1_000_002, "00:23:24") in pb
        assert {r[0] for r in pb} == {"5K", "10K", "Half marathon"}
        # details were only fetched for runs (5 runs, not the ride)
        assert conn.execute("SELECT count(*) FROM raw.strava_activity_details").fetchone()[0] == 5
        # training_streaks: Mon-Wed (3 days) and Fri-Sat (2 days)
        st = q("SELECT streak_start::text, days FROM marts.training_streaks ORDER BY streak_start")
        assert st == [("2026-03-02", 3), ("2026-03-06", 2)]


def test_details_backfill_respects_rate_limit(db, monkeypatch):
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    acts = [_run(i, 1 + i % 28, 5.0, 5.0) for i in range(10)]
    monkeypatch.setattr(extract_load, "DETAILS_PER_RUN", 4)
    calls = []
    def limited(token, activity_id):
        calls.append(activity_id)
        if len(calls) == 7:                       # Strava says "too many requests" on the 7th call
            raise extract_load.RateLimited()
        return {"id": activity_id, "best_efforts": []}

    run = lambda: extract_load.run(fetch=lambda t, a: acts, get_token=lambda: "t", fetch_detail=limited)
    assert run() == 0                             # run 1: 4 details (the limit per run)
    assert run() == 0                             # run 2: 2 details, then rate limited -> stops, still success
    assert run() == 0                             # run 3: the last 4
    with psycopg.connect(db) as conn:
        assert conn.execute("SELECT count(*) FROM raw.strava_activity_details").fetchone()[0] == 10
        assert [r[0] for r in conn.execute("SELECT status FROM raw.load_runs").fetchall()] == ["success"] * 3
