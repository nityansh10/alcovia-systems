-- =====================================================================
-- Alcovia student-progress data model (Postgres / Supabase; runs on DuckDB)
--
-- Capture principle: a human types a number only when no device or system
-- can produce it. Each table notes who writes it.
--   APP   = Alcovia app (api.alcovia.life), automatic
--   WEAR  = wearable sync (WHOOP API, HealthKit, Health Connect, Garmin)
--   N8N   = automation, derived
--   ADV   = academic advisor, one form per event
--   STU   = student, in-app tap (no free text)
-- =====================================================================

CREATE TABLE advisors (
    advisor_id      VARCHAR     PRIMARY KEY,
    name            VARCHAR     NOT NULL
);

CREATE TABLE students (
    student_id      VARCHAR     PRIMARY KEY,
    name            VARCHAR     NOT NULL,
    grade           SMALLINT    NOT NULL,
    board           VARCHAR     NOT NULL,           -- CBSE | ICSE | IB | IGCSE
    advisor_id      VARCHAR     NOT NULL REFERENCES advisors(advisor_id),
    pod             VARCHAR     NOT NULL,           -- 5-student peer pod
    joined_on       DATE        NOT NULL,
    wearable        VARCHAR                         -- whoop | apple_watch | samsung | garmin | NULL
);

-- ---------- Academics ---------------------------------------------------
CREATE TABLE subjects (                             -- ADV, once at onboarding
    subject_id      VARCHAR     PRIMARY KEY,
    student_id      VARCHAR     NOT NULL REFERENCES students(student_id),
    name            VARCHAR     NOT NULL,
    affinity        VARCHAR     NOT NULL CHECK (affinity IN ('likes','neutral','dislikes')),
    has_tutor       BOOLEAN     NOT NULL
);

CREATE TABLE chapters (                             -- ADV, from the school syllabus
    chapter_id      VARCHAR     PRIMARY KEY,
    subject_id      VARCHAR     NOT NULL REFERENCES subjects(subject_id),
    name            VARCHAR     NOT NULL,
    planned_quarter SMALLINT    NOT NULL CHECK (planned_quarter BETWEEN 1 AND 4)  -- 25% of syllabus per quarter
);

-- The five-step completion rigour. One row per step reached.
--   1 read   2 notes   3 practice >=70%   4 timed past paper   5 ready (>=80%)
-- Steps 3-5 carry the accuracy that unlocked them (STU enters score; APP
-- refuses to mark step 3 under 70% or step 5 under 80%).
CREATE TABLE chapter_stage_events (
    chapter_id      VARCHAR     NOT NULL REFERENCES chapters(chapter_id),
    stage           SMALLINT    NOT NULL CHECK (stage BETWEEN 1 AND 5),
    reached_on      DATE        NOT NULL,
    accuracy_pct    NUMERIC(5,2),
    PRIMARY KEY (chapter_id, stage)
);

CREATE TABLE exam_targets (                         -- ADV, signed off with parent
    student_id      VARCHAR     NOT NULL REFERENCES students(student_id),
    subject_id      VARCHAR     NOT NULL REFERENCES subjects(subject_id),
    exam_type       VARCHAR     NOT NULL CHECK (exam_type IN ('formative','unit_test','half_yearly','annual')),
    target_pct      NUMERIC(5,2) NOT NULL,
    parent_aligned_on DATE,                         -- NULL = target not yet agreed with parent
    PRIMARY KEY (subject_id, exam_type)
);

CREATE TABLE exam_results (                         -- STU photo of report card -> ADV confirms
    subject_id      VARCHAR     NOT NULL REFERENCES subjects(subject_id),
    exam_type       VARCHAR     NOT NULL,
    exam_date       DATE        NOT NULL,
    score_pct       NUMERIC(5,2) NOT NULL,
    PRIMARY KEY (subject_id, exam_type, exam_date)
);

-- ---------- Daily rhythm ------------------------------------------------
CREATE TABLE tasks (                                -- APP (advisor-assigned or self)
    task_id         VARCHAR     PRIMARY KEY,
    student_id      VARCHAR     NOT NULL REFERENCES students(student_id),
    source          VARCHAR     NOT NULL CHECK (source IN ('advisor','self')),
    created_on      DATE        NOT NULL,
    due_on          DATE        NOT NULL,
    estimated_min   INTEGER     NOT NULL,
    actual_min      INTEGER,                        -- from linked focus sessions
    completed_on    DATE
);

CREATE TABLE timetable_blocks (                     -- APP (timetable builder, Google Calendar sync)
    student_id      VARCHAR     NOT NULL REFERENCES students(student_id),
    date            DATE        NOT NULL,
    kind            VARCHAR     NOT NULL CHECK (kind IN ('self_study','tuition','extracurricular','free')),
    planned_min     INTEGER     NOT NULL,
    PRIMARY KEY (student_id, date, kind)
);

CREATE TABLE focus_sessions (                       -- APP (focus_session_started / completed / abandoned)
    session_id      VARCHAR     PRIMARY KEY,
    student_id      VARCHAR     NOT NULL REFERENCES students(student_id),
    started_at      TIMESTAMP   NOT NULL,
    planned_min     INTEGER     NOT NULL,
    actual_min      INTEGER     NOT NULL,
    status          VARCHAR     NOT NULL CHECK (status IN ('completed','abandoned')),
    in_planned_block BOOLEAN    NOT NULL            -- started inside a self_study timetable block
);

CREATE TABLE quizzes (                              -- N8N publishes the 8pm quiz
    quiz_id         VARCHAR     PRIMARY KEY,
    quiz_date       DATE        NOT NULL UNIQUE,
    topic           VARCHAR     NOT NULL,
    published       BOOLEAN     NOT NULL            -- did it actually go out at 8pm
);

CREATE TABLE quiz_attempts (                        -- APP
    quiz_id         VARCHAR     NOT NULL REFERENCES quizzes(quiz_id),
    student_id      VARCHAR     NOT NULL REFERENCES students(student_id),
    score_pct       NUMERIC(5,2) NOT NULL,
    liked           BOOLEAN,                        -- one-tap thumbs on the result screen
    PRIMARY KEY (quiz_id, student_id)
);

CREATE TABLE wearable_daily (                       -- WEAR, nightly
    student_id      VARCHAR     NOT NULL REFERENCES students(student_id),
    date            DATE        NOT NULL,
    active_min      INTEGER     NOT NULL,
    strain          NUMERIC(4,1),                   -- WHOOP 0-21; NULL for other sources
    sleep_min       INTEGER     NOT NULL,
    recovery_pct    NUMERIC(5,2),                   -- WHOOP recovery / HRV-derived readiness
    PRIMARY KEY (student_id, date)
);

CREATE TABLE app_daily_usage (                      -- N8N rollup of Mixpanel app_session_ended
    student_id      VARCHAR     NOT NULL REFERENCES students(student_id),
    date            DATE        NOT NULL,
    foreground_min  NUMERIC(6,2) NOT NULL,
    PRIMARY KEY (student_id, date)
);

-- ---------- Program delivery (week / month / quarter rhythm) -----------
-- One row per thing Alcovia promised to run. `conducted_on` NULL = it did not happen.
CREATE TABLE activities (                           -- N8N from ClickUp/Calendar; ADV ticks "conducted"
    activity_id     VARCHAR     PRIMARY KEY,
    kind            VARCHAR     NOT NULL CHECK (kind IN (
                        'academic_session','workshop','pod','peer_session','mentor_call',
                        'branding_shoot','podcast','competition_prep','parent_child','out_of_city')),
    title           VARCHAR     NOT NULL,
    scheduled_on    DATE        NOT NULL,
    conducted_on    DATE
);

CREATE TABLE activity_participants (                -- invite list from calendar; attendance by QR check-in
    activity_id     VARCHAR     NOT NULL REFERENCES activities(activity_id),
    student_id      VARCHAR     NOT NULL REFERENCES students(student_id),
    attended        BOOLEAN     NOT NULL,
    rating          SMALLINT    CHECK (rating BETWEEN 1 AND 5),  -- STU, push 30 min after end
    PRIMARY KEY (activity_id, student_id)
);

CREATE TABLE soft_skill_scores (                    -- facilitator rubric, one form per workshop
    activity_id     VARCHAR     NOT NULL REFERENCES activities(activity_id),
    student_id      VARCHAR     NOT NULL REFERENCES students(student_id),
    skill           VARCHAR     NOT NULL,           -- engagement, teamwork, crisis_management, ...
    score           SMALLINT    NOT NULL CHECK (score BETWEEN 1 AND 5),
    PRIMARY KEY (activity_id, student_id, skill)
);

CREATE TABLE roadmap_milestones (                   -- ADV sets; STU/ADV marks done
    milestone_id    VARCHAR     PRIMARY KEY,
    student_id      VARCHAR     NOT NULL REFERENCES students(student_id),
    roadmap         VARCHAR     NOT NULL CHECK (roadmap IN ('career','personal','academic')),
    title           VARCHAR     NOT NULL,
    due_on          DATE        NOT NULL,
    done_on         DATE
);

-- Every automated nudge or escalation n8n sends. This is how we prove the
-- system acted, and how we measure whether escalations fix anything.
CREATE TABLE escalations (
    escalation_id   VARCHAR     PRIMARY KEY,
    student_id      VARCHAR     NOT NULL REFERENCES students(student_id),
    rule            VARCHAR     NOT NULL,           -- task_overdue | syllabus_behind | readiness_gap | no_focus_3d | quiz_missed_3d
    triggered_on    DATE        NOT NULL,
    notified        VARCHAR     NOT NULL,           -- student | parent | advisor | tutor
    resolved_on     DATE
);
