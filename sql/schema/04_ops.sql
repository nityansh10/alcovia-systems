-- =====================================================================
-- Operational tables the n8n workflows rely on. These are what make the
-- automations "not break silently": every job leaves a heartbeat, every
-- failure leaves a row, every threshold lives in data instead of in a node.
-- =====================================================================

-- Last successful run per scheduled job (written by each workflow's "Heartbeat" node).
CREATE TABLE sync_runs (
    job             VARCHAR     PRIMARY KEY,
    finished_at     TIMESTAMP   NOT NULL,
    rows_written    INTEGER
);

-- How stale each job may get before the hourly watchdog in 00_error_handler raises it.
CREATE TABLE sync_sla (
    job             VARCHAR     PRIMARY KEY,
    max_age         INTERVAL    NOT NULL
);
INSERT INTO sync_sla VALUES
    ('meta_ads_daily',   INTERVAL '26 hours'),
    ('mixpanel_export',  INTERVAL '26 hours'),
    ('wearables_nightly', INTERVAL '26 hours');

CREATE TABLE sync_failures (
    workflow        VARCHAR     NOT NULL,
    failed_at       TIMESTAMP   NOT NULL,
    message         VARCHAR
);

-- Rules for 06_student_escalations. Tuned in the weekly review, not in n8n.
CREATE TABLE escalation_thresholds (
    task_overdue_student_days   SMALLINT NOT NULL,   -- nudge the student
    task_overdue_parent_days    SMALLINT NOT NULL,   -- then tell the parent
    quiz_missed_days            SMALLINT NOT NULL,
    no_focus_days               SMALLINT NOT NULL,
    readiness_gap_pts           SMALLINT NOT NULL    -- exam score this far under target -> tutor support
);
INSERT INTO escalation_thresholds VALUES (2, 5, 3, 3, 10);

-- Quiz content is written ahead; 05_daily_quiz only publishes.
CREATE TABLE quiz_bank (
    quiz_id         VARCHAR     PRIMARY KEY,
    scheduled_for   DATE        NOT NULL UNIQUE,
    topic           VARCHAR     NOT NULL
);

-- Which student has which wearable connected. OAuth tokens stay in api.alcovia.life, never here.
CREATE TABLE wearable_connections (
    student_id      VARCHAR     NOT NULL,
    provider        VARCHAR     NOT NULL CHECK (provider IN ('whoop','apple_health','health_connect','garmin')),
    whoop_user_id   VARCHAR,
    active          BOOLEAN     NOT NULL DEFAULT TRUE,
    PRIMARY KEY (student_id, provider)
);

-- Snapshot of sql/metrics/40_student_kpis.sql#student_scorecard for the last 7 days,
-- written every Sunday 17:55 (pg_cron) so the 18:00 parent digest reads a frozen week.
CREATE TABLE weekly_scorecard (
    week_ending             DATE        NOT NULL,
    student_id              VARCHAR     NOT NULL,
    name                    VARCHAR     NOT NULL,
    advisor_clickup_id      VARCHAR,
    focus_min_per_day       NUMERIC(6,1),
    quiz_participation_pct  NUMERIC(5,1),
    deadline_adherence_pct  NUMERIC(5,1),
    syllabus_pace_pct       NUMERIC(5,1),
    chapter_readiness       NUMERIC(5,1),
    PRIMARY KEY (week_ending, student_id)
);
