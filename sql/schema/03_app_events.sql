-- =====================================================================
-- Raw product analytics, landed from Mixpanel's Raw Export API by n8n
-- (nightly). Event names are the ones the current app already fires.
-- =====================================================================

CREATE TABLE app_events (
    insert_id       VARCHAR     PRIMARY KEY,        -- Mixpanel $insert_id (dedupe key)
    distinct_id     VARCHAR     NOT NULL,           -- = students.student_id after identify()
    event           VARCHAR     NOT NULL,           -- e.g. focus_session_completed, quiz_summary_viewed
    ts              TIMESTAMP   NOT NULL,
    duration_sec    INTEGER,                        -- app_session_ended, focus_session_* only
    is_test_device  BOOLEAN     NOT NULL DEFAULT FALSE
);

-- Event -> product area. Kept as data so adding an event never means a code change.
CREATE TABLE event_feature_map (
    event           VARCHAR     PRIMARY KEY,
    feature         VARCHAR     NOT NULL,           -- home | realm | focus_timer | syllabus | quiz | wellness | rankings | streak | goals | study_planner | tasks
    area            VARCHAR     NOT NULL            -- home | study | plan | focus_game | wellness
);
