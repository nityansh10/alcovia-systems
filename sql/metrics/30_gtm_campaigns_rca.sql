-- =====================================================================
-- GTM tracker / CAMPAIGN PERFORMANCE + RCA
-- Attribution: first touch. A lead carries the ad_id that created it; revenue
-- follows that lead through enrollment -> invoice -> Razorpay payment.
-- =====================================================================

-- name: ad_creative_performance
-- Every creative live in the range, ranked by CTR. The bottom of this list is the refresh queue.
WITH m AS (
    SELECT ad_id,
           SUM(impressions) AS impressions, SUM(link_clicks) AS clicks,
           SUM(spend_inr)   AS spend,       SUM(meta_leads)  AS meta_leads
    FROM ad_daily_metrics
    WHERE date BETWEEN DATE '{{start_date}}' AND DATE '{{end_date}}'
    GROUP BY ad_id
),
outcome AS (
    SELECT l.ad_id,
           COUNT(*) FILTER (WHERE q.lead_id IS NOT NULL)  AS qualified,
           COUNT(DISTINCT e.lead_id)                      AS signed_up,
           COALESCE(SUM(p.amount_inr), 0)                 AS revenue
    FROM leads l
    LEFT JOIN lead_stage_events q ON q.lead_id = l.lead_id AND q.stage = 'qualified'
    LEFT JOIN enrollments e       ON e.lead_id = l.lead_id
    LEFT JOIN invoices i          ON i.enrollment_id = e.enrollment_id
    LEFT JOIN payments p          ON p.invoice_id = i.invoice_id
    WHERE l.ad_id IS NOT NULL
      AND l.created_at::date BETWEEN DATE '{{start_date}}' AND DATE '{{end_date}}'
    GROUP BY l.ad_id
)
SELECT c.objective, a.ad_id, a.name, a.creative_type, a.hook,
       m.impressions, m.clicks,
       ROUND((100.0 * m.clicks / NULLIF(m.impressions, 0))::numeric, 2)   AS ctr_pct,
       ROUND(m.spend::numeric, 0)                                           AS spend_inr,
       ROUND((m.spend / NULLIF(m.meta_leads, 0))::numeric, 0)               AS cpl_inr,
       o.qualified,
       ROUND((m.spend / NULLIF(o.qualified, 0))::numeric, 0)                AS cpql_inr,
       o.signed_up,
       ROUND((COALESCE(o.revenue, 0) / NULLIF(m.spend, 0))::numeric, 2)     AS roas,
       RANK() OVER (PARTITION BY c.objective ORDER BY m.clicks * 1.0 / NULLIF(m.impressions, 0) DESC) AS ctr_rank
FROM m
JOIN ads a USING (ad_id) JOIN ad_sets s USING (ad_set_id) JOIN campaigns c USING (campaign_id)
LEFT JOIN outcome o USING (ad_id)
ORDER BY c.objective, ctr_pct DESC;

-- name: ad_set_frequency
-- Latest 7-day frequency per ad set inside the range. 3+ = the audience has seen it too often.
SELECT s.ad_set_id, s.name, c.objective, f.week_ending, f.frequency,
       CASE WHEN f.frequency >= 3   THEN 'change now'
            WHEN f.frequency >= 2.5 THEN 'watch'
            ELSE 'healthy' END                                              AS status
FROM ad_set_weekly_frequency f
JOIN ad_sets s USING (ad_set_id) JOIN campaigns c USING (campaign_id)
WHERE f.week_ending = (SELECT MAX(week_ending) FROM ad_set_weekly_frequency x
                       WHERE x.ad_set_id = f.ad_set_id
                         AND x.week_ending <= DATE '{{end_date}}' + 6)
ORDER BY f.frequency DESC;

-- name: landing_page_health
-- Current range vs the previous range of equal length.
WITH cur AS (
    SELECT landing_page_id,
           SUM(sessions) s, SUM(bounces) b, SUM(form_submits) f,
           PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY p75_load_ms) AS load_ms
    FROM landing_page_daily
    WHERE date BETWEEN DATE '{{start_date}}' AND DATE '{{end_date}}'
    GROUP BY 1
),
prev AS (
    SELECT landing_page_id,
           SUM(sessions) s, SUM(bounces) b,
           PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY p75_load_ms) AS load_ms
    FROM landing_page_daily
    WHERE date BETWEEN DATE '{{start_date}}' - (DATE '{{end_date}}' - DATE '{{start_date}}' + 1)::int
                   AND DATE '{{start_date}}' - 1
    GROUP BY 1
)
SELECT lp.name, lp.url, cur.s AS sessions,
       ROUND((100.0 * cur.b / NULLIF(cur.s, 0))::numeric, 1)               AS bounce_pct,
       ROUND((100.0 * cur.b / NULLIF(cur.s, 0) - 100.0 * prev.b / NULLIF(prev.s, 0))::numeric, 1) AS bounce_change_pts,
       ROUND((100.0 * cur.f / NULLIF(cur.s, 0))::numeric, 2)               AS form_cvr_pct,
       ROUND(cur.load_ms::numeric, 0)                                      AS p75_load_ms,
       ROUND(prev.load_ms::numeric, 0)                                     AS prev_p75_load_ms,
       CASE WHEN cur.load_ms > 3000 OR 100.0 * cur.b / NULLIF(cur.s, 0) > 60 THEN 'fix'
            WHEN cur.load_ms > 2500 THEN 'watch'
            ELSE 'healthy' END                                              AS status
FROM cur JOIN landing_pages lp USING (landing_page_id)
LEFT JOIN prev USING (landing_page_id)
ORDER BY status, bounce_pct DESC;

-- name: rca_decision_matrix
-- One row per ad set. The decision is a rule, not an opinion, so the weekly
-- review argues about the thresholds once and then just reads the column.
--
-- Rules are evaluated top-down; the first match wins.
--   LEARNING : < Rs 15,000 spend in the window -> not enough signal, leave alone
--   DROP     : CPQL > 1.5x target and no sign-ups to show for it -> the audience is wrong
--   REFRESH  : frequency >= 3, or CTR fell >= 20% half-over-half -> the audience is fine, the creative is tired
--   SCALE    : CPQL <= target, frequency < 2.5, CTR not falling  -> +20% budget every 3 days
--   HOLD     : everything else
WITH bounds AS (
    SELECT DATE '{{start_date}}' AS s, DATE '{{end_date}}' AS e,
           DATE '{{start_date}}' + ((DATE '{{end_date}}' - DATE '{{start_date}}') / 2)::int AS mid
),
perf AS (
    SELECT a.ad_set_id,
           SUM(m.spend_inr)                                                         AS spend,
           SUM(m.link_clicks) FILTER (WHERE m.date <= b.mid) * 1.0
             / NULLIF(SUM(m.impressions) FILTER (WHERE m.date <= b.mid), 0)         AS ctr_first_half,
           SUM(m.link_clicks) FILTER (WHERE m.date > b.mid) * 1.0
             / NULLIF(SUM(m.impressions) FILTER (WHERE m.date > b.mid), 0)          AS ctr_second_half
    FROM ad_daily_metrics m JOIN ads a USING (ad_id), bounds b
    WHERE m.date BETWEEN b.s AND b.e
    GROUP BY a.ad_set_id
),
quality AS (
    SELECT a.ad_set_id,
           COUNT(DISTINCT q.lead_id) AS qualified,
           COUNT(DISTINCT w.lead_id) AS signed_up
    FROM leads l JOIN ads a USING (ad_id)
    LEFT JOIN lead_stage_events q ON q.lead_id = l.lead_id AND q.stage = 'qualified'
    LEFT JOIN lead_stage_events w ON w.lead_id = l.lead_id AND w.stage = 'won'
    WHERE l.created_at::date BETWEEN DATE '{{start_date}}' AND DATE '{{end_date}}'
    GROUP BY a.ad_set_id
),
freq AS (
    SELECT DISTINCT ON (ad_set_id) ad_set_id, frequency
    FROM ad_set_weekly_frequency
    WHERE week_ending <= DATE '{{end_date}}' + 6
    ORDER BY ad_set_id, week_ending DESC
),
tgt AS (
    SELECT target AS cpql_target FROM monthly_targets
    WHERE metric = 'cpql_max' AND month = date_trunc('month', DATE '{{end_date}}')::date
),
scored AS (
    SELECT s.ad_set_id, s.name AS ad_set, c.objective,
           p.spend, q.qualified, q.signed_up,
           p.spend / NULLIF(q.qualified, 0)                                         AS cpql,
           (SELECT cpql_target FROM tgt)                                            AS cpql_target,
           f.frequency,
           (p.ctr_second_half - p.ctr_first_half) / NULLIF(p.ctr_first_half, 0)     AS ctr_change
    FROM perf p
    JOIN ad_sets s USING (ad_set_id) JOIN campaigns c USING (campaign_id)
    LEFT JOIN quality q USING (ad_set_id)
    LEFT JOIN freq f USING (ad_set_id)
    WHERE c.objective = 'program'
)
SELECT ad_set, objective,
       ROUND(spend::numeric, 0)                     AS spend_inr,
       qualified, signed_up,
       ROUND(cpql::numeric, 0)                      AS cpql_inr,
       cpql_target,
       frequency,
       ROUND((100 * ctr_change)::numeric, 1)        AS ctr_change_pct,
       CASE
         WHEN spend < 15000                                                     THEN 'LEARNING'
         WHEN cpql IS NULL OR (cpql > 1.5 * cpql_target AND COALESCE(signed_up, 0) = 0) THEN 'DROP'
         WHEN frequency >= 3 OR ctr_change <= -0.20                             THEN 'REFRESH'
         WHEN cpql <= cpql_target AND COALESCE(frequency, 0) < 2.5 AND ctr_change > -0.10 THEN 'SCALE'
         ELSE 'HOLD'
       END                                          AS decision
FROM scored
ORDER BY spend DESC;
