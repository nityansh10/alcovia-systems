-- =====================================================================
-- GTM tracker / FUNNEL
-- Cohort view: leads CREATED in the range, followed to wherever they are today.
-- (An activity view - "how many discovery calls happened this week" - is the
--  same log filtered on occurred_at instead; see funnel_activity below.)
-- =====================================================================

-- name: funnel_cohort
WITH cohort AS (
    SELECT l.lead_id, l.source, l.ad_id
    FROM leads l
    WHERE l.created_at::date BETWEEN DATE '{{start_date}}' AND DATE '{{end_date}}'
      AND (l.source <> 'workshop'
           -- a workshop seat buyer counts only once they ask about the program
           OR EXISTS (SELECT 1 FROM lead_stage_events e WHERE e.lead_id = l.lead_id))
),
reached AS (
    SELECT c.lead_id,
           BOOL_OR(e.stage = 'qualified')           AS qualified,
           BOOL_OR(e.stage = 'discovery_scheduled') AS disc_sched,
           BOOL_OR(e.stage = 'discovery_attended')  AS disc_att,
           BOOL_OR(e.stage = 'ambition_scheduled')  AS amb_sched,
           BOOL_OR(e.stage = 'ambition_attended')   AS amb_att,
           BOOL_OR(e.stage = 'architect_done')      AS architect,
           BOOL_OR(e.stage = 'won')                 AS won
    FROM cohort c LEFT JOIN lead_stage_events e USING (lead_id)
    GROUP BY c.lead_id
)
SELECT COUNT(*)                                          AS total_leads,
       COUNT(*) FILTER (WHERE qualified)                 AS qualified_leads,
       COUNT(*) FILTER (WHERE disc_sched)                AS discovery_set,
       COUNT(*) FILTER (WHERE disc_att)                  AS discovery_attended,
       ROUND((100.0 * COUNT(*) FILTER (WHERE disc_att)  / NULLIF(COUNT(*) FILTER (WHERE disc_sched), 0))::numeric, 1) AS discovery_show_up_pct,
       COUNT(*) FILTER (WHERE amb_sched)                 AS ambition_set,
       COUNT(*) FILTER (WHERE amb_att)                   AS ambition_done,
       -- drop-off between a completed discovery call and a completed ambition interview
       ROUND((100.0 - 100.0 * COUNT(*) FILTER (WHERE amb_att) / NULLIF(COUNT(*) FILTER (WHERE disc_att), 0))::numeric, 1) AS ambition_drop_off_pct,
       COUNT(*) FILTER (WHERE architect)                 AS architect_sessions,
       COUNT(*) FILTER (WHERE won)                       AS signed_up
FROM reached;

-- name: funnel_top_metrics
WITH cohort AS (                            -- same program-lead definition as funnel_cohort
    SELECT * FROM leads l
    WHERE created_at::date BETWEEN DATE '{{start_date}}' AND DATE '{{end_date}}'
      AND (source <> 'workshop' OR EXISTS (SELECT 1 FROM lead_stage_events e WHERE e.lead_id = l.lead_id))
),
spend AS (
    SELECT SUM(m.spend_inr) AS program_spend
    FROM ad_daily_metrics m
    JOIN ads a USING (ad_id) JOIN ad_sets s USING (ad_set_id) JOIN campaigns c USING (campaign_id)
    WHERE c.objective = 'program'
      AND m.date BETWEEN DATE '{{start_date}}' AND DATE '{{end_date}}'
),
paid AS (                                   -- signed up AND paid (invoice settled)
    SELECT DISTINCT e.lead_id
    FROM enrollments e JOIN invoices i USING (enrollment_id)
    WHERE e.renewed_from IS NULL AND i.status = 'paid'
),
q AS (
    SELECT c.lead_id, c.source, c.ad_id
    FROM cohort c JOIN lead_stage_events e ON e.lead_id = c.lead_id AND e.stage = 'qualified'
)
SELECT (SELECT program_spend FROM spend)                                            AS program_ad_spend_inr,
       (SELECT COUNT(*) FROM q WHERE source = 'meta_ads')                          AS paid_qualified_leads,
       ROUND(((SELECT program_spend FROM spend)
              / NULLIF((SELECT COUNT(*) FROM q WHERE source = 'meta_ads'), 0))::numeric, 0) AS cost_per_qualified_lead,
       (SELECT COUNT(*) FROM cohort WHERE ad_id IS NULL AND source <> 'workshop')  AS organic_leads,
       (SELECT COUNT(*) FROM cohort c JOIN paid p USING (lead_id))                 AS paid_signups_from_cohort,
       ROUND((100.0 * (SELECT COUNT(*) FROM cohort c JOIN paid p USING (lead_id))
              / NULLIF((SELECT COUNT(*) FROM q), 0))::numeric, 2)                  AS qualified_to_paid_pct,
       ROUND((100.0 * (SELECT COUNT(*) FROM cohort c JOIN paid p USING (lead_id))
              / NULLIF((SELECT COUNT(*) FROM cohort), 0))::numeric, 2)                 AS lead_to_paid_pct;

-- name: lead_journey_days
-- Average time a lead spends in the funnel before it signs up or drops off.
WITH ends AS (
    SELECT l.lead_id, l.created_at,
           MIN(e.occurred_at) FILTER (WHERE e.stage = 'won')                                  AS won_at,
           MIN(e.occurred_at) FILTER (WHERE e.stage IN ('lost', 'disqualified'))              AS dropped_at
    FROM leads l JOIN lead_stage_events e USING (lead_id)
    WHERE l.created_at::date BETWEEN DATE '{{start_date}}' AND DATE '{{end_date}}'
    GROUP BY l.lead_id, l.created_at
)
SELECT 'signed_up' AS outcome, COUNT(*) AS leads,
       ROUND(AVG(EXTRACT(EPOCH FROM (won_at - created_at)) / 86400)::numeric, 1)      AS avg_days,
       ROUND((PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM (won_at - created_at)) / 86400))::numeric, 1) AS median_days
FROM ends WHERE won_at IS NOT NULL
UNION ALL
SELECT 'dropped_off', COUNT(*),
       ROUND(AVG(EXTRACT(EPOCH FROM (dropped_at - created_at)) / 86400)::numeric, 1),
       ROUND((PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM (dropped_at - created_at)) / 86400))::numeric, 1)
FROM ends WHERE won_at IS NULL AND dropped_at IS NOT NULL;

-- name: leads_by_source
SELECT source,
       COUNT(*)                                                              AS leads,
       COUNT(*) FILTER (WHERE EXISTS (SELECT 1 FROM lead_stage_events e
                                      WHERE e.lead_id = l.lead_id AND e.stage = 'qualified')) AS qualified,
       COUNT(*) FILTER (WHERE EXISTS (SELECT 1 FROM lead_stage_events e
                                      WHERE e.lead_id = l.lead_id AND e.stage = 'won'))       AS signed_up
FROM leads l
WHERE created_at::date BETWEEN DATE '{{start_date}}' AND DATE '{{end_date}}'
GROUP BY source
ORDER BY leads DESC;

-- name: funnel_activity
-- Activity view for the weekly sales stand-up: what happened IN the range.
SELECT stage, COUNT(*) AS events
FROM lead_stage_events
WHERE occurred_at::date BETWEEN DATE '{{start_date}}' AND DATE '{{end_date}}'
GROUP BY stage
ORDER BY events DESC;
