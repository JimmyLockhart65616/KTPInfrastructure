-- One row per capture CREDIT with its wall-clock time: the per-credit feed
-- flag_swing needs to split a cap's swing across its cappers. Neither
-- capture_credit_fact (per player+flag totals) nor capture_event_fact (per
-- event, cappers counted not named) carries both the player and the time.
--
-- `game_time` is not on ktp_flag_captures at all, so it comes from the flag
-- transition this credit belongs to: nearest ownership row for the same
-- half and flag within three seconds of the credit. The two tables are
-- written by different paths and disagree by about a second on real matches
-- (state 21:49:44 vs credit 21:49:43 on 1789348403-ATL2), which is why the
-- join is a nearest-within-tolerance and not an equality. A correlated
-- subquery keeps it one row per credit; a range JOIN would multiply them.
--
-- Same warmup-bleed guard as capture_credit_fact.sql. `team` is mapped to
-- the engine side the way objective_timeline_fact does, because the TSV
-- layer int-coerces a column named team.
SELECT
    c.half,
    c.player_id,
    CASE LOWER(c.team)
      WHEN 'allies' THEN 1
      WHEN 'axis' THEN 2
      ELSE NULL
    END AS team,
    c.flag_name,
    c.event_time,
    UNIX_TIMESTAMP(c.event_time) AS event_unix,
    (SELECT f.game_time
       FROM ktp_flag_state_events f
      WHERE f.match_id = c.match_id
        AND f.half = c.half
        AND f.flag_name = c.flag_name
        AND f.is_initial = 0
        AND ABS(UNIX_TIMESTAMP(f.event_time) - UNIX_TIMESTAMP(c.event_time)) <= 3
      ORDER BY ABS(UNIX_TIMESTAMP(f.event_time) - UNIX_TIMESTAMP(c.event_time)),
               f.game_time
      LIMIT 1) AS game_time
FROM ktp_flag_captures c
LEFT JOIN ktp_matches m
  ON m.match_id = c.match_id AND m.half = c.half
WHERE c.match_id = {{MATCH_ID}}
  AND (m.start_time IS NULL OR c.event_time > m.start_time)
ORDER BY c.half, c.event_time, c.flag_name, c.player_id;
