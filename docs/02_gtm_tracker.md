# Problem 2 · GTM tracker: metric definitions

Live prototype: `dashboards/gtm/index.html` (every number recomputes for the selected date range). SQL: `sql/metrics/10_gtm_revenue.sql`, `20_gtm_funnel.sql`, `30_gtm_campaigns_rca.sql`. The dashboard JS and the SQL return identical figures for the same window (checked on September 2026: revenue ₹23.8L at 87% of target, funnel 687 → 201 → 151 → 113 → 93 → 73 → 56 → 8, CPQL ₹2,081).

## Definitions the team has to agree on once

| Metric | Definition | Why this way |
|---|---|---|
| **Revenue** | Cash captured in Razorpay in the range (`payments.captured_at`) | Invoiced-but-unpaid isn't revenue. It has its own tile. |
| **Target vs achievement** | Monthly target, pro-rated by days when the range covers part of a month | A "last 15 days" view is compared with 15 days of target, not a full month |
| **3-month trial vs full program** | `payments.revenue_line` set from Razorpay `notes.plan` | Put the plan in the payment notes at checkout, so nobody has to classify payments later |
| **Students onboarded** | First enrolment per student by start date; renewals excluded | A trial converting to full is a renewal, not a new student |
| **Workshop revenue** | Seat payments (`notes.workshop_id` set), ₹3,999 each | Also tracks the workshop's second job: seat buyers who later enrol |
| **Invoice generated, not paid** | Issued on or before the reference date with no captured payment by then; aged 1–7 / 8–30 / 30+ days after due | Historical ranges show what was unpaid *at that time* |
| **Upcoming renewals** | Trials ending in the next 30 days with no full-program enrolment | This list drives the T-21 / T-14 / T-7 renewal workflow |
| **Funnel (cohort)** | Leads **created** in the range, followed to their current stage | Answers "how good were this month's leads?" |
| **Show-up rate** | Discovery attended ÷ discovery scheduled | The stage the Smallest.ai reminder calls exist to lift |
| **Ambition interview drop-off** | 1 − ambition attended ÷ discovery attended | Shows where parent intent and teen intent come apart |
| **Cost per qualified lead** | Program ad spend in range ÷ Meta leads in the cohort that reached *qualified* | CPL rewards cheap junk leads; CPQL doesn't |
| **Program conversion %** | Cohort leads that signed up **and paid** ÷ cohort leads | "Pay and sign up for the duration we are reviewing", as the brief puts it |
| **Organic leads** | Leads with no `ad_id` (Instagram organic, referral, website) | Workshop buyers are reported separately |
| **Average lead journey** | Days from lead created to *won*, and to *lost/disqualified*, reported separately | One blended average hides that losses happen in ~1 day and wins take ~3 weeks |
| **CTR** | Link clicks ÷ impressions per creative | Top 3 = keep; bottom 3 (min 5k impressions) = refresh queue |
| **Frequency** | Meta's 7-day ad-set frequency (de-duplicated reach) | Daily rows can't be summed into weekly reach, so it's pulled separately |
| **Landing page health** | Bounce %, form CVR, p75 LCP vs the previous equal-length period | Catches the teen-LP regression on 10 Sep (autoplay video: 2.4s → 4.9s) |

## RCA rules (scale / refresh / drop)

Rules are evaluated top-down per ad set and the first match wins (`30_gtm_campaigns_rca.sql#rca_decision_matrix`):

1. **LEARNING:** under ₹15,000 spent in the window. Leave it alone.
2. **DROP:** CPQL above 1.5× target and no sign-ups. The audience is wrong; new creative won't fix that.
3. **REFRESH:** frequency 3 or more, or CTR down 20%+ (first half vs second half of the window). The audience is fine and the creative is tired.
4. **SCALE:** CPQL at or under target, frequency under 2.5, CTR not falling. Add 20% budget every 3 days while CPQL holds.
5. **HOLD:** everything else.

In the September dummy data this flags *Teens 14–17 Broad Reels* as **DROP**: it has the second-highest CTR of any program ad but the leads don't qualify. A CTR-only report would have scaled it.

## Sources and refresh

| Data | Source | Workflow | Freshness |
|---|---|---|---|
| Spend, impressions, clicks, leads | Meta Marketing API | `02_meta_ads_daily` | Daily 06:00 IST |
| Lead stages | ClickUp status-change webhook | `03_clickup_funnel_stages` | Real time |
| Payments, invoices, seats | Razorpay webhooks (signature verified) | `01_razorpay_to_revenue` | Real time |
| Landing page speed and bounce | Vercel / GA4 export | (add in week 3) | Daily |
| Targets | Founders, once a month | Supabase table | Monthly |
