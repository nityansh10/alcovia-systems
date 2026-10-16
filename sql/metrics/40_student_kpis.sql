-- =====================================================================
-- STUDENT DASHBOARD KPIs - three lenses
--   QUANTITY     did Alcovia conduct it?          (delivery team is accountable)
--   QUALITY      did Alcovians like it?            (program design is accountable)
--   PERFORMANCE  how did the Alcovian do?          (student + advisor are accountable)
-- Placeholders: {{start_date}} {{end_date}} {{as_of}}
-- =====================================================================

-- name: delivery_quantity
-- Lens 1. Every promised touchpoint, scheduled vs actually conducted.
SELECT kind,
       COUNT(*)                                                      AS scheduled,
       COUNT(conducted_on)                                           AS conducted,
       ROUND((100.0 * COUNT(conducted_on) / NULLIF(COUNT(*), 0))::numeric, 1) AS conducted_pct
FROM activities
WHERE scheduled_on BETWEEN DATE '{{start_date}}' AND LEAST(DATE '{{end_date}}', DATE '{{as_of}}')
GROUP BY kind
UNION ALL
SELECT 'daily_quiz', COUNT(*), COUNT(*) FILTER (WHERE published),
       ROUND((100.0 * COUNT(*) FILTER (WHERE published) / NULLIF(COUNT(*), 0))::numeric, 1)
FROM quizzes
WHERE quiz_date BETWEEN DATE '{{start_date}}' AND LEAST(DATE '{{end_date}}', DATE '{{as_of}}')
ORDER BY conducted_pct;

-- name: experience_quality
-- Lens 2. Showing up is the first vote; the rating is the second.
SELECT a.kind,
       COUNT(*)                                                      AS invited,
       ROUND((100.0 * COUNT(*) FILTER (WHERE p.attended) / NULLIF(COUNT(*), 0))::numeric, 1)          AS attendance_pct,
       ROUND(AVG(p.rating)::numeric, 2)                              AS avg_rating,
       ROUND((100.0 * COUNT(p.rating) / NULLIF(COUNT(*) FILTER (WHERE p.attended), 0))::numeric, 1)   AS rating_response_pct,
       ROUND((100.0 * COUNT(*) FILTER (WHERE p.rating >= 4) / NULLIF(COUNT(p.rating), 0))::numeric, 1) AS pct_rated_4_plus
FROM activities a
JOIN activity_participants p USING (activity_id)
WHERE a.conducted_on BETWEEN DATE '{{start_date}}' AND DATE '{{end_date}}'
GROUP BY a.kind
UNION ALL
SELECT 'daily_quiz',
       COUNT(*),
       NULL,
       NULL,
       ROUND((100.0 * COUNT(liked) / COUNT(*))::numeric, 1),
       ROUND((100.0 * COUNT(*) FILTER (WHERE liked) / NULLIF(COUNT(liked), 0))::numeric, 1)
FROM quiz_attempts qa JOIN quizzes q USING (quiz_id)
WHERE q.quiz_date BETWEEN DATE '{{start_date}}' AND DATE '{{end_date}}'
ORDER BY avg_rating NULLS LAST;

-- name: student_scorecard
-- Lens 3. One row per Alcovian. This is the table the weekly review runs on.
WITH days_in AS (
    SELECT s.student_id,
           GREATEST(1, LEAST(DATE '{{end_date}}', DATE '{{as_of}}')
                       - GREATEST(DATE '{{start_date}}', s.joined_on) + 1) AS n_days
    FROM students s
),
focus AS (
    SELECT student_id,
           SUM(actual_min)                                                     AS focus_min,
           AVG(CASE WHEN status = 'completed' THEN 1.0 ELSE 0 END)             AS focus_completion,
           SUM(actual_min) FILTER (WHERE in_planned_block)                     AS focus_in_block_min
    FROM focus_sessions
    WHERE started_at::date BETWEEN DATE '{{start_date}}' AND DATE '{{end_date}}'
    GROUP BY 1
),
plan AS (
    SELECT student_id, SUM(planned_min) AS planned_self_study_min
    FROM timetable_blocks
    WHERE kind = 'self_study' AND date BETWEEN DATE '{{start_date}}' AND LEAST(DATE '{{end_date}}', DATE '{{as_of}}')
    GROUP BY 1
),
quiz AS (
    SELECT qa.student_id, COUNT(*) AS attempts, AVG(qa.score_pct) AS avg_score
    FROM quiz_attempts qa JOIN quizzes q USING (quiz_id)
    WHERE q.quiz_date BETWEEN DATE '{{start_date}}' AND DATE '{{end_date}}'
    GROUP BY 1
),
quiz_days AS (
    SELECT COUNT(*) AS published FROM quizzes
    WHERE published AND quiz_date BETWEEN DATE '{{start_date}}' AND LEAST(DATE '{{end_date}}', DATE '{{as_of}}')
),
task AS (
    SELECT student_id,
           COUNT(*)                                                            AS due,
           COUNT(completed_on)                                                 AS done,
           COUNT(*) FILTER (WHERE completed_on <= due_on)                      AS on_time,
           -- 1 - mean absolute % error of the student's own estimate
           1 - AVG(LEAST(1.0, ABS(actual_min - estimated_min) * 1.0 / estimated_min))
               FILTER (WHERE actual_min IS NOT NULL)                           AS estimate_accuracy
    FROM tasks
    WHERE due_on BETWEEN DATE '{{start_date}}' AND LEAST(DATE '{{end_date}}', DATE '{{as_of}}')
    GROUP BY 1
),
chapter_top AS (
    SELECT sub.student_id, ch.chapter_id, ch.planned_quarter, COALESCE(MAX(ev.stage), 0) AS top_stage
    FROM chapters ch
    JOIN subjects sub USING (subject_id)
    LEFT JOIN chapter_stage_events ev ON ev.chapter_id = ch.chapter_id AND ev.reached_on <= DATE '{{as_of}}'
    GROUP BY 1, 2, 3
),
syllabus AS (
    -- Academic year starts 1 April. Each quarter owns 25% of the syllabus.
    -- Expected-by-now = all chapters of finished quarters + a pro-rata share of the current one.
    SELECT student_id,
           SUM(CASE WHEN planned_quarter < q_now THEN 1
                    WHEN planned_quarter = q_now THEN q_elapsed ELSE 0 END)                      AS expected_started,
           COUNT(*) FILTER (WHERE top_stage >= 1)                                                AS started,
           AVG(top_stage * 20.0) FILTER (WHERE planned_quarter < q_now)                          AS readiness_due,
           COUNT(*) FILTER (WHERE top_stage >= 4) * 1.0 / NULLIF(COUNT(*) FILTER (WHERE top_stage >= 1), 0) AS rigour_share
    FROM chapter_top,
         (SELECT EXTRACT(QUARTER FROM DATE '{{as_of}}' - INTERVAL '3 months')::int AS q_now,
                 (DATE '{{as_of}}' - date_trunc('quarter', DATE '{{as_of}}')::date) / 91.0 AS q_elapsed) qn
    GROUP BY 1
),
exam AS (
    SELECT sub.student_id, AVG(r.score_pct - t.target_pct) AS gap_to_target
    FROM exam_results r
    JOIN subjects sub USING (subject_id)
    JOIN exam_targets t ON t.subject_id = r.subject_id AND t.exam_type = r.exam_type
    WHERE r.exam_date = (SELECT MAX(exam_date) FROM exam_results WHERE exam_date <= DATE '{{as_of}}')
    GROUP BY 1
),
wear AS (
    SELECT student_id, AVG(active_min) AS active_min, AVG(sleep_min) / 60.0 AS sleep_h, AVG(recovery_pct) AS recovery
    FROM wearable_daily
    WHERE date BETWEEN DATE '{{start_date}}' AND DATE '{{end_date}}'
    GROUP BY 1
),
growth AS (
    SELECT p.student_id, AVG(CASE WHEN p.attended THEN 1.0 ELSE 0 END) AS attendance
    FROM activity_participants p JOIN activities a USING (activity_id)
    WHERE a.conducted_on BETWEEN DATE '{{start_date}}' AND DATE '{{end_date}}'
    GROUP BY 1
),
roadmap AS (
    SELECT student_id,
           COUNT(*) FILTER (WHERE done_on IS NOT NULL AND done_on <= due_on) * 1.0 / NULLIF(COUNT(*), 0) AS milestones_on_time
    FROM roadmap_milestones
    WHERE due_on BETWEEN DATE '{{start_date}}' AND LEAST(DATE '{{end_date}}', DATE '{{as_of}}')
    GROUP BY 1
)
SELECT s.name, s.grade, s.board, adv.name AS advisor, s.pod,
       ROUND((COALESCE(f.focus_min, 0) * 1.0 / d.n_days)::numeric, 1)                 AS focus_min_per_day,
       ROUND((100 * f.focus_completion)::numeric, 0)                                   AS focus_completion_pct,
       ROUND((100.0 * f.focus_in_block_min / NULLIF(pl.planned_self_study_min, 0))::numeric, 0) AS timetable_adherence_pct,
       ROUND((100.0 * COALESCE(qz.attempts, 0) / NULLIF((SELECT published FROM quiz_days), 0))::numeric, 0) AS quiz_participation_pct,
       ROUND(qz.avg_score::numeric, 0)                                                 AS quiz_avg_score,
       ROUND((100.0 * t.done / NULLIF(t.due, 0))::numeric, 0)                          AS task_completion_pct,
       ROUND((100.0 * t.on_time / NULLIF(t.due, 0))::numeric, 0)                       AS deadline_adherence_pct,
       ROUND((100 * t.estimate_accuracy)::numeric, 0)                                  AS time_estimate_accuracy_pct,
       ROUND((100.0 * sy.started / NULLIF(sy.expected_started, 0))::numeric, 0)        AS syllabus_pace_pct,
       ROUND(sy.readiness_due::numeric, 0)                                             AS chapter_readiness,
       ROUND((100 * sy.rigour_share)::numeric, 0)                                      AS rigour_pct,
       ROUND(ex.gap_to_target::numeric, 1)                                             AS exam_gap_pts,
       ROUND(w.active_min::numeric, 0)                                                 AS active_min,
       ROUND(w.sleep_h::numeric, 1)                                                    AS sleep_h,
       ROUND(w.recovery::numeric, 0)                                                   AS recovery_pct,
       ROUND((100 * g.attendance)::numeric, 0)                                         AS session_attendance_pct,
       ROUND((100 * rm.milestones_on_time)::numeric, 0)                                AS milestones_on_time_pct
FROM students s
JOIN advisors adv USING (advisor_id)
JOIN days_in d USING (student_id)
LEFT JOIN focus f USING (student_id)
LEFT JOIN plan pl USING (student_id)
LEFT JOIN quiz qz USING (student_id)
LEFT JOIN task t USING (student_id)
LEFT JOIN syllabus sy USING (student_id)
LEFT JOIN exam ex USING (student_id)
LEFT JOIN wear w USING (student_id)
LEFT JOIN growth g USING (student_id)
LEFT JOIN roadmap rm USING (student_id)
ORDER BY s.name;

-- name: soft_skill_trend
-- The 11 workshop rubric skills, cohort average by month.
SELECT date_trunc('month', a.conducted_on)::date AS month, sk.skill, ROUND(AVG(sk.score)::numeric, 2) AS avg_score
FROM soft_skill_scores sk JOIN activities a USING (activity_id)
WHERE a.conducted_on BETWEEN DATE '{{start_date}}' AND DATE '{{end_date}}'
GROUP BY 1, 2
ORDER BY 2, 1;

-- name: advisor_input_metrics
-- What the advisor controls. If these are low, student numbers above are not trustworthy.
SELECT adv.name AS advisor,
       COUNT(DISTINCT s.student_id)                                                    AS students,
       ROUND((100.0 * COUNT(t.target_pct) FILTER (WHERE t.parent_aligned_on IS NOT NULL)
              / NULLIF(COUNT(t.target_pct), 0))::numeric, 0)                           AS targets_parent_aligned_pct,
       -- input cadence: students who logged a chapter step in the last 7 days
       ROUND((100.0 * COUNT(DISTINCT s.student_id) FILTER (WHERE EXISTS (
                 SELECT 1 FROM chapter_stage_events ev JOIN chapters c USING (chapter_id) JOIN subjects sb USING (subject_id)
                 WHERE sb.student_id = s.student_id AND ev.reached_on > DATE '{{as_of}}' - 7))
              / NULLIF(COUNT(DISTINCT s.student_id), 0))::numeric, 0)                  AS students_logging_weekly_pct
FROM advisors adv
JOIN students s USING (advisor_id)
LEFT JOIN exam_targets t ON t.student_id = s.student_id
GROUP BY adv.name
ORDER BY adv.name;

-- name: escalation_effectiveness
-- Automated nudges: how many fired, and did the behaviour actually recover?
SELECT rule, notified,
       COUNT(*)                                                                        AS fired,
       ROUND((100.0 * COUNT(resolved_on) / COUNT(*))::numeric, 0)                      AS resolved_pct,
       ROUND(AVG(resolved_on - triggered_on)::numeric, 1)                              AS avg_days_to_resolve
FROM escalations
WHERE triggered_on BETWEEN DATE '{{start_date}}' AND DATE '{{end_date}}'
GROUP BY rule, notified
ORDER BY fired DESC;
