-- =====================================================================
-- GTM tracker / REVENUE
-- Placeholders: {{start_date}} {{end_date}} {{as_of}}  (dashboard date picker)
-- Revenue = cash captured in Razorpay (payments.captured_at), not invoiced value.
-- =====================================================================

-- name: revenue_vs_target
-- Target vs achievement for every month the selected range touches.
-- Partial months are pro-rated so a 15-day view is compared with 15 days of target.
WITH months AS (
    SELECT DISTINCT month
    FROM monthly_targets
    WHERE month BETWEEN date_trunc('month', DATE '{{start_date}}') AND DATE '{{end_date}}'
),
actual AS (
    SELECT date_trunc('month', captured_at)::date AS month,
           SUM(amount_inr)                                                AS revenue_total,
           SUM(amount_inr) FILTER (WHERE revenue_line <> 'workshop')      AS revenue_program,
           SUM(amount_inr) FILTER (WHERE revenue_line = 'workshop')       AS revenue_workshop
    FROM payments
    WHERE captured_at::date BETWEEN DATE '{{start_date}}' AND DATE '{{end_date}}'
    GROUP BY 1
),
target AS (
    SELECT m.month,
           -- days of this month that fall inside the selected range / days in month
           (LEAST(DATE '{{end_date}}', (m.month + INTERVAL '1 month' - INTERVAL '1 day')::date)
              - GREATEST(DATE '{{start_date}}', m.month) + 1) * 1.0
             / ((m.month + INTERVAL '1 month')::date - m.month)          AS share,
           MAX(t.target) FILTER (WHERE t.metric = 'revenue_total')       AS t_total,
           MAX(t.target) FILTER (WHERE t.metric = 'revenue_program')     AS t_program,
           MAX(t.target) FILTER (WHERE t.metric = 'revenue_workshop')    AS t_workshop
    FROM months m JOIN monthly_targets t USING (month)
    GROUP BY 1, 2
)
SELECT t.month,
       ROUND((t.t_total * t.share)::numeric, 0)                          AS target_total,
       COALESCE(a.revenue_total, 0)                                      AS actual_total,
       ROUND((100.0 * COALESCE(a.revenue_total, 0) / NULLIF(t.t_total * t.share, 0))::numeric, 1) AS pct_of_target,
       ROUND((t.t_program * t.share)::numeric, 0)                        AS target_program,
       COALESCE(a.revenue_program, 0)                                    AS actual_program,
       ROUND((t.t_workshop * t.share)::numeric, 0)                       AS target_workshop,
       COALESCE(a.revenue_workshop, 0)                                   AS actual_workshop
FROM target t LEFT JOIN actual a USING (month)
ORDER BY t.month;

-- name: revenue_by_line
-- Split: 3-month trial vs full program vs workshop, and program vs workshop.
SELECT revenue_line,
       COUNT(*)                                                          AS payments,
       SUM(amount_inr)                                                   AS revenue_inr,
       ROUND((100.0 * SUM(amount_inr) / SUM(SUM(amount_inr)) OVER ())::numeric, 1) AS share_pct,
       CASE WHEN revenue_line = 'workshop' THEN 'workshop' ELSE 'program' END AS bucket
FROM payments
WHERE captured_at::date BETWEEN DATE '{{start_date}}' AND DATE '{{end_date}}'
GROUP BY revenue_line
ORDER BY revenue_inr DESC;

-- name: students_onboarded_monthly
-- New students = first enrollment (renewals excluded), split by plan chosen.
SELECT date_trunc('month', start_date)::date                            AS month,
       COUNT(*)                                                          AS onboarded,
       COUNT(*) FILTER (WHERE plan = 'trial_3m')                         AS trial_3m,
       COUNT(*) FILTER (WHERE plan = 'full_program')                     AS full_program,
       MAX(t.target)                                                     AS target
FROM enrollments e
LEFT JOIN monthly_targets t
       ON t.month = date_trunc('month', e.start_date)::date AND t.metric = 'students_onboarded'
WHERE e.renewed_from IS NULL
  AND e.start_date BETWEEN DATE '{{start_date}}' AND DATE '{{end_date}}'
GROUP BY 1
ORDER BY 1;

-- name: workshop_performance
-- Fortnightly workshops at Rs 3,999/seat, straight from Razorpay seat payments.
SELECT w.held_on,
       w.title,
       COUNT(s.seat_id)                                                  AS seats_sold,
       w.capacity,
       ROUND((100.0 * COUNT(s.seat_id) / w.capacity)::numeric, 0)        AS fill_pct,
       SUM(p.amount_inr)                                                 AS revenue_inr,
       COUNT(*) FILTER (WHERE s.attended)                                AS attended,
       -- the workshop's second job: feeding the program funnel
       COUNT(DISTINCT e.enrollment_id)                                   AS became_students
FROM workshops w
LEFT JOIN workshop_seats s ON s.workshop_id = w.workshop_id
LEFT JOIN payments p       ON p.payment_id = s.payment_id
LEFT JOIN enrollments e    ON e.lead_id = s.lead_id AND e.renewed_from IS NULL
WHERE w.held_on BETWEEN DATE '{{start_date}}' AND DATE '{{end_date}}'
GROUP BY w.workshop_id, w.held_on, w.title, w.capacity
ORDER BY w.held_on;

-- name: unpaid_invoices
-- Invoice generated but not paid, aged as of the report date.
SELECT i.invoice_id,
       e.student_name,
       e.plan,
       i.issued_on,
       i.due_on,
       i.amount_inr,
       DATE '{{as_of}}' - i.due_on                                       AS days_overdue,
       CASE WHEN DATE '{{as_of}}' <= i.due_on THEN 'not due'
            WHEN DATE '{{as_of}}' - i.due_on <= 7  THEN '1-7 days'
            WHEN DATE '{{as_of}}' - i.due_on <= 30 THEN '8-30 days'
            ELSE '30+ days' END                                          AS aging_bucket
FROM invoices i
JOIN enrollments e USING (enrollment_id)
WHERE i.status = 'issued'
  AND i.issued_on <= DATE '{{as_of}}'
ORDER BY i.due_on;

-- name: upcoming_trial_renewals
-- 3-month trials ending in the next 30 days that have no full-program follow-on yet.
-- This list is what the n8n renewal workflow works through, T-21 / T-14 / T-7.
SELECT t.enrollment_id,
       t.student_name,
       t.start_date,
       t.end_date,
       t.end_date - DATE '{{as_of}}'                                     AS days_left,
       CASE WHEN t.end_date - DATE '{{as_of}}' <= 7  THEN 'call this week'
            WHEN t.end_date - DATE '{{as_of}}' <= 14 THEN 'architect review'
            ELSE 'progress report sent' END                              AS next_step
FROM enrollments t
WHERE t.plan = 'trial_3m'
  AND t.end_date BETWEEN DATE '{{as_of}}' AND DATE '{{as_of}}' + 30
  AND NOT EXISTS (SELECT 1 FROM enrollments r WHERE r.renewed_from = t.enrollment_id)
ORDER BY t.end_date;

-- name: trial_renewal_rate
-- Of trials that ended inside the range, how many converted to the full program.
SELECT COUNT(*)                                                          AS trials_ended,
       COUNT(r.enrollment_id)                                            AS renewed,
       ROUND((100.0 * COUNT(r.enrollment_id) / NULLIF(COUNT(*), 0))::numeric, 1) AS renewal_pct
FROM enrollments t
LEFT JOIN enrollments r ON r.renewed_from = t.enrollment_id
WHERE t.plan = 'trial_3m'
  AND t.end_date BETWEEN DATE '{{start_date}}' AND LEAST(DATE '{{end_date}}', DATE '{{as_of}}');
