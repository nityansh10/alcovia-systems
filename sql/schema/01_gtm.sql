-- =====================================================================
-- Alcovia GTM data model (Postgres / Supabase; also runs on DuckDB)
--
-- One rule drives this schema: every number on the GTM tracker must be
-- computable from a row that a system wrote, not a person.
--   Meta Marketing API  -> campaigns, ad_sets, ads, ad_daily_metrics
--   Landing page RUM    -> landing_page_daily
--   ClickUp CRM         -> leads, lead_stage_events (status-change webhooks)
--   Razorpay webhooks   -> invoices, payments, workshop_seats
--   Ops (monthly, once) -> monthly_targets
-- =====================================================================

-- ---------- Targets ----------------------------------------------------
CREATE TABLE monthly_targets (
    month           DATE        NOT NULL,           -- first day of month
    metric          VARCHAR     NOT NULL,           -- revenue_total | revenue_program | revenue_workshop | students_onboarded | qualified_leads | cpql_max
    target          NUMERIC(14,2) NOT NULL,
    PRIMARY KEY (month, metric)
);

-- ---------- Paid media (Meta) -----------------------------------------
CREATE TABLE campaigns (
    campaign_id     VARCHAR     PRIMARY KEY,        -- Meta campaign id
    name            VARCHAR     NOT NULL,
    objective       VARCHAR     NOT NULL CHECK (objective IN ('program','workshop')),
    status          VARCHAR     NOT NULL CHECK (status IN ('active','paused')),
    started_on      DATE        NOT NULL
);

CREATE TABLE landing_pages (
    landing_page_id VARCHAR     PRIMARY KEY,
    name            VARCHAR     NOT NULL,
    url             VARCHAR     NOT NULL,
    purpose         VARCHAR     NOT NULL            -- program_parent | program_teen | workshop_checkout
);

CREATE TABLE ad_sets (
    ad_set_id       VARCHAR     PRIMARY KEY,
    campaign_id     VARCHAR     NOT NULL REFERENCES campaigns(campaign_id),
    name            VARCHAR     NOT NULL,
    audience        VARCHAR     NOT NULL
);

CREATE TABLE ads (
    ad_id           VARCHAR     PRIMARY KEY,
    ad_set_id       VARCHAR     NOT NULL REFERENCES ad_sets(ad_set_id),
    name            VARCHAR     NOT NULL,
    creative_type   VARCHAR     NOT NULL CHECK (creative_type IN ('video','static','carousel','reel')),
    hook            VARCHAR     NOT NULL,           -- the one-line angle of the creative
    landing_page_id VARCHAR     NOT NULL REFERENCES landing_pages(landing_page_id),
    launched_on     DATE        NOT NULL,
    paused_on       DATE                            -- NULL = still live
);

-- One row per ad per day, pulled by n8n at 06:00 IST (yesterday's insights).
CREATE TABLE ad_daily_metrics (
    date            DATE        NOT NULL,
    ad_id           VARCHAR     NOT NULL REFERENCES ads(ad_id),
    impressions     INTEGER     NOT NULL,
    reach           INTEGER     NOT NULL,           -- unique people that day
    link_clicks     INTEGER     NOT NULL,
    spend_inr       NUMERIC(12,2) NOT NULL,
    meta_leads      INTEGER     NOT NULL,           -- lead-form submits / checkout starts as Meta counts them
    PRIMARY KEY (date, ad_id)
);

-- Rolling 7-day frequency per ad set needs reach de-duplicated across days,
-- which daily rows cannot give. n8n pulls it directly with time_increment=7.
CREATE TABLE ad_set_weekly_frequency (
    week_ending     DATE        NOT NULL,
    ad_set_id       VARCHAR     NOT NULL REFERENCES ad_sets(ad_set_id),
    impressions     INTEGER     NOT NULL,
    reach           INTEGER     NOT NULL,
    frequency       NUMERIC(6,2) NOT NULL,          -- impressions / reach over the 7 days
    PRIMARY KEY (week_ending, ad_set_id)
);

CREATE TABLE landing_page_daily (
    date            DATE        NOT NULL,
    landing_page_id VARCHAR     NOT NULL REFERENCES landing_pages(landing_page_id),
    sessions        INTEGER     NOT NULL,
    bounces         INTEGER     NOT NULL,           -- left without scroll/interaction
    form_starts     INTEGER     NOT NULL,
    form_submits    INTEGER     NOT NULL,
    p75_load_ms     INTEGER     NOT NULL,           -- Largest Contentful Paint, 75th percentile
    PRIMARY KEY (date, landing_page_id)
);

-- ---------- Funnel (ClickUp is the system of record) -------------------
CREATE TABLE leads (
    lead_id         VARCHAR     PRIMARY KEY,        -- = ClickUp task id
    created_at      TIMESTAMP   NOT NULL,
    source          VARCHAR     NOT NULL CHECK (source IN ('meta_ads','organic_instagram','referral','website','workshop')),
    ad_id           VARCHAR     REFERENCES ads(ad_id),  -- set only for meta_ads
    teen_grade      SMALLINT,
    city            VARCHAR
);

-- Append-only log written by the ClickUp "status changed" webhook.
-- A lead's funnel position is always derived from this log, never stored.
CREATE TABLE lead_stage_events (
    lead_id         VARCHAR     NOT NULL REFERENCES leads(lead_id),
    stage           VARCHAR     NOT NULL CHECK (stage IN (
                        'qualified','disqualified',
                        'discovery_scheduled','discovery_attended','discovery_no_show',
                        'ambition_scheduled','ambition_attended','ambition_no_show',
                        'architect_done','won','lost')),
    occurred_at     TIMESTAMP   NOT NULL,
    PRIMARY KEY (lead_id, stage)
);

-- ---------- Revenue (Razorpay is the system of record) -----------------
CREATE TABLE workshops (
    workshop_id     VARCHAR     PRIMARY KEY,
    title           VARCHAR     NOT NULL,
    profession      VARCHAR     NOT NULL,
    held_on         DATE        NOT NULL,
    seat_price_inr  NUMERIC(10,2) NOT NULL DEFAULT 3999,
    capacity        SMALLINT    NOT NULL
);

CREATE TABLE enrollments (
    enrollment_id   VARCHAR     PRIMARY KEY,
    lead_id         VARCHAR     REFERENCES leads(lead_id),
    student_name    VARCHAR     NOT NULL,
    plan            VARCHAR     NOT NULL CHECK (plan IN ('trial_3m','full_program')),
    start_date      DATE        NOT NULL,
    end_date        DATE        NOT NULL,
    price_inr       NUMERIC(12,2) NOT NULL,
    renewed_from    VARCHAR     REFERENCES enrollments(enrollment_id)  -- trial -> full conversion
);

CREATE TABLE invoices (
    invoice_id      VARCHAR     PRIMARY KEY,        -- Razorpay invoice id
    enrollment_id   VARCHAR     NOT NULL REFERENCES enrollments(enrollment_id),
    issued_on       DATE        NOT NULL,
    due_on          DATE        NOT NULL,
    amount_inr      NUMERIC(12,2) NOT NULL,
    status          VARCHAR     NOT NULL CHECK (status IN ('issued','paid','cancelled'))
);

-- Every captured Razorpay payment. Revenue on the tracker = cash collected.
CREATE TABLE payments (
    payment_id      VARCHAR     PRIMARY KEY,        -- Razorpay pay_xxx (idempotency key for the webhook)
    captured_at     TIMESTAMP   NOT NULL,
    amount_inr      NUMERIC(12,2) NOT NULL,
    revenue_line    VARCHAR     NOT NULL CHECK (revenue_line IN ('program_trial','program_full','workshop')),
    invoice_id      VARCHAR     REFERENCES invoices(invoice_id),      -- program payments
    workshop_id     VARCHAR     REFERENCES workshops(workshop_id)     -- workshop seat payments
);

CREATE TABLE workshop_seats (
    seat_id         VARCHAR     PRIMARY KEY,
    workshop_id     VARCHAR     NOT NULL REFERENCES workshops(workshop_id),
    payment_id      VARCHAR     NOT NULL REFERENCES payments(payment_id),
    lead_id         VARCHAR     REFERENCES leads(lead_id),  -- every buyer becomes a 'workshop' lead
    attended        BOOLEAN     NOT NULL
);
