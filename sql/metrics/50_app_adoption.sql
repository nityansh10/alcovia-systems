-- =====================================================================
-- APP ADOPTION - reproduces the brief's Mixpanel summary from raw events,
-- then decomposes "minutes per student per day" so we know which lever moves it.
--
--   avg min / student / day  =  daily active share  x  minutes per active day
--   (2.15 today)                 (who opens)            (what they do once inside)
--
-- Window: {{start_date}} .. {{end_date}}   ("this week" = last 7 days of the window)
-- =====================================================================

-- name: adoption_summary
WITH ev AS (
    SELECT * FROM app_events
    WHERE NOT is_test_device
      AND ts::date BETWEEN DATE '{{start_date}}' AND DATE '{{end_date}}'
),
weekly AS (
    SELECT date_trunc('week', ts)::date AS wk, COUNT(DISTINCT distinct_id) AS wau
    FROM ev GROUP BY 1
)
SELECT (SELECT COUNT(DISTINCT distinct_id) FROM ev)                                              AS students_active_in_window,
       -- full Mon-Sun weeks only; a 2-day stub week would understate actives
       (SELECT MIN(wau) FROM weekly WHERE wk >= DATE '{{start_date}}' AND wk + 6 <= DATE '{{end_date}}') AS min_weekly_active,
       (SELECT MAX(wau) FROM weekly WHERE wk >= DATE '{{start_date}}' AND wk + 6 <= DATE '{{end_date}}') AS max_weekly_active,
       (SELECT COUNT(DISTINCT distinct_id) FROM ev WHERE ts::date > DATE '{{end_date}}' - 7)     AS active_this_week,
       (SELECT COUNT(*) FROM (SELECT distinct_id FROM ev GROUP BY 1
                              HAVING MAX(ts)::date <= DATE '{{end_date}}' - 14) x)               AS dormant_14d;

-- name: feature_reach
-- Students who touched each feature in the window vs in the last 7 days.
SELECT m.area, m.feature,
       COUNT(DISTINCT e.distinct_id)                                                             AS students_ever,
       COUNT(DISTINCT e.distinct_id) FILTER (WHERE e.ts::date > DATE '{{end_date}}' - 7)         AS students_this_week,
       ROUND((100.0 * COUNT(DISTINCT e.distinct_id) FILTER (WHERE e.ts::date > DATE '{{end_date}}' - 7)
              / NULLIF(COUNT(DISTINCT e.distinct_id), 0))::numeric, 0)                           AS retained_pct
FROM app_events e
JOIN event_feature_map m USING (event)
WHERE NOT e.is_test_device
  AND e.ts::date BETWEEN DATE '{{start_date}}' AND DATE '{{end_date}}'
GROUP BY m.area, m.feature
ORDER BY students_ever DESC;

-- name: focus_regulars
-- "Regular" = a completed focus session in at least 3 distinct weeks of the window.
SELECT COUNT(*) FILTER (WHERE weeks >= 3) AS regular_focus_users,
       COUNT(*)                            AS ever_used_focus
FROM (
    SELECT distinct_id, COUNT(DISTINCT date_trunc('week', ts)) AS weeks
    FROM app_events
    WHERE event IN ('focus_session_started', 'focus_session_completed', 'focus_timer_viewed')
      AND NOT is_test_device
      AND ts::date BETWEEN DATE '{{start_date}}' AND DATE '{{end_date}}'
    GROUP BY 1
) x;

-- name: minutes_decomposition
-- The metric tree, computed. Denominator = enrolled students (20), not just actives,
-- because a student who never opens the app is exactly the problem.
WITH days AS (SELECT (DATE '{{end_date}}' - DATE '{{start_date}}' + 1) AS n),
enrolled AS (SELECT COUNT(DISTINCT distinct_id) AS n FROM app_events WHERE NOT is_test_device),
sess AS (
    SELECT distinct_id, ts::date AS d, SUM(duration_sec) / 60.0 AS minutes
    FROM app_events
    WHERE event = 'app_session_ended' AND NOT is_test_device
      AND ts::date BETWEEN DATE '{{start_date}}' AND DATE '{{end_date}}'
    GROUP BY 1, 2
)
SELECT ROUND((SUM(minutes) / ((SELECT n FROM enrolled) * (SELECT n FROM days)))::numeric, 2)      AS avg_min_per_student_day,
       ROUND((100.0 * COUNT(*) / ((SELECT n FROM enrolled) * (SELECT n FROM days)))::numeric, 1)  AS daily_active_share_pct,
       ROUND(AVG(minutes)::numeric, 1)                                                           AS min_per_active_day,
       30.0                                                                                      AS target_min_per_student_day
FROM sess;
