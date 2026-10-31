-- STAGING: typed columns pulled out of the JSON, units converted, nothing else.
CREATE OR REPLACE VIEW staging.activities AS
SELECT
    activity_id,
    payload->>'name'                                        AS name,
    payload->>'sport_type'                                  AS sport_type,
    (payload->>'start_date')::timestamptz                   AS start_time_utc,
    -- Strava's start_date_local is the local wall-clock time written with a 'Z'; keep it as a plain timestamp
    replace(payload->>'start_date_local', 'Z', '')::timestamp AS start_time_local,
    payload->>'timezone'                                    AS timezone,
    round((payload->>'distance')::numeric / 1000, 3)        AS distance_km,
    (payload->>'moving_time')::int                          AS moving_time_s,
    (payload->>'elapsed_time')::int                         AS elapsed_time_s,
    (payload->>'total_elevation_gain')::numeric             AS elevation_gain_m,
    (payload->>'average_heartrate')::numeric                AS avg_heartrate,
    (payload->>'max_heartrate')::numeric                    AS max_heartrate,
    (payload->>'suffer_score')::numeric                     AS relative_effort,
    (payload->>'trainer')::boolean                          AS is_indoor,
    payload->>'visibility'                                  AS visibility,
    payload->>'device_name'                                 AS device_name,
    NULLIF(payload->'map'->>'summary_polyline', '')         AS polyline,
    fetched_at
FROM raw.strava_activities;
