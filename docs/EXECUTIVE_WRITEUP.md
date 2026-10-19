# Alcovia · Product, Systems & Analytics Lead: executive write-up

**Live dashboards:** GTM tracker · Student progress board (links in the README)  ·  **Repo:** SQL, schemas, 10 n8n workflows, data generator, dashboards

---

## 1. The read

Four problems are on the table, but they come from **two missing systems**:

1. **There is no single data spine.** Revenue lives in Razorpay, the funnel in ClickUp statuses, ads in Meta, usage in Mixpanel, and student progress in documents and folders. Every question becomes a manual compile, so nobody asks the question weekly.
2. **"Shipped" is treated as "done".** Features get built (25 of them for 20 students) without a success metric, a review date or a kill rule, so adoption is nobody's job after launch.

Problems 1 and 4 turn out to be the **same problem from two sides.** The 30-minute usage target can only be reached through focus sessions, which is the phone-lock focus mode Problem 4 asks for. The advisor's student dashboard can only exist if students log in the app. Building one data spine, and making the app the place the weekly review happens, solves both together.

## 2. What I would do, in the order I would do it

| Order | Why first | What ships |
|---|---|---|
| **1 · Data spine** (Nov W1–W2) | Every other deliverable reads from it | Supabase schema (in repo), 5 ingestion workflows, error handler + watchdog |
| **2 · GTM tracker** (live by Nov W4) | The data already exists, revenue is at stake, and it takes the least engineering time | Metabase on Supabase using the SQL in this repo; the prototype here is the spec |
| **3 · App adoption bets** (Nov W3 → Jan) | Highest leverage, but needs discovery first | "Tonight's study block" on Home, Realm fed by focus, pod leagues, in-app 8pm quiz |
| **4 · Student progress board** (v1 Dec W2, advisor cockpit Dec W3) | Needs the capture changes from #3 to have data | Three-lens board, escalations, Sunday parent digest |
| **5 · Delivery operating system** (from day 1) | It's how 1–4 get run | Bet briefs, gates in ClickUp, Wed demo, Fri metrics review |

**Resource logic:** the full-stack engineer is the scarce resource, so I protect their time for what only code can do (app changes, ingestion, the cockpit tab). Internal dashboards go on **Metabase over Supabase**, which costs no front-end time; a custom build happens only if Metabase can't do something. The process designer owns everything that is a *process* rather than code: ClickUp pipelines, Razorpay checkout notes, advisor SOPs, QR check-in, rubric forms and the renewal playbook. I own metrics, SQL, specs, discovery, and the review cadence.

## 3. Team plan, November to January

```mermaid
gantt
    dateFormat YYYY-MM-DD
    axisFormat %d %b
    section Me (PM + analytics)
    Stakeholder + 20 student interviews     :m1, 2026-11-02, 5d
    Metric definitions + SQL (GTM)          :m2, 2026-11-02, 10d
    Bet briefs for app adoption             :m3, 2026-11-09, 5d
    Student KPI SQL + thresholds            :m4, 2026-11-16, 10d
    Weekly bet reviews (D+7 / D+28)         :m5, 2026-11-23, 60d
    section Full-stack engineer
    Supabase + Mixpanel identify + export   :f1, 2026-11-02, 7d
    n8n: Razorpay, Meta, ClickUp, errors    :f2, 2026-11-09, 8d
    Metabase GTM tracker                    :f3, 2026-11-19, 6d
    Bet 1 Study block + focus lock          :f4, 2026-11-23, 10d
    Bet 2 Realm fed by focus, Bet 4 quiz    :f5, 2026-12-07, 6d
    Escalations + digest workflows          :f6, 2026-12-14, 6d
    Advisor cockpit progress tab            :f7, 2026-12-21, 8d
    Bet 3 Pod leagues                       :f8, 2027-01-04, 8d
    section Process designer
    ClickUp pipeline = funnel stages        :p1, 2026-11-02, 7d
    Razorpay notes, invoice + renewal SOP   :p2, 2026-11-09, 7d
    Advisor SOPs + chapter backfill         :p3, 2026-11-16, 10d
    QR check-in, rating push, rubric forms  :p4, 2026-11-30, 8d
    Weekly review moves to the board        :p5, 2026-12-14, 10d
    Parent digest approval flow             :p6, 2027-01-04, 6d
```

| Milestone | Date | How we'll know |
|---|---|---|
| Data spine live, no silent failures | 13 Nov | All 5 ingestion jobs green in `sync_runs` for 5 days running |
| GTM tracker used in the Friday review | 27 Nov | Founders run the Friday review from it instead of ClickUp exports |
| Progress board drives the weekly review | 21 Dec | The advisor session starts on the board for all students |
| App: study block live for all 5 pods (one pod a week from 4 Dec) | 1 Jan | Students with a completed focus session per weekday ≥ 60% |
| App at 10 min / student / day | 31 Dec | `minutes_decomposition` |
| App at 20 min / student / day | 31 Jan | (same) |

## 4. Problem by problem (detail in `docs/`)

**1 · App adoption, 2.15 → 30 min** ([01_app_adoption.md](01_app_adoption.md))
My working hypothesis (from the seed data; the first thing to check in Mixpanel) is that 2.15 = 21% of students opening the app daily × 10.5 min per visit. Students who open it stay; most don't open it. Only a focus session can hold a teen for 25–45 minutes, so the plan makes the focus session the front door: Home opens on tonight's study block, one tap locks the phone, the Realm grows only from focus minutes, pods compete weekly, and the 8pm quiz becomes the daily habit. I'd report raw minutes but steer by **focused study minutes**, with completion and syllabus pace as guardrails so the number can't be gamed. With 20 users there are no A/B tests: the rollout goes one pod per week (a stepped-wedge design).

*What a hands-on test of the Android build showed (O1–O22 in the doc):* Home already opens on a "Today's Focus" card, so Bet 1 changes an existing card rather than adding a screen. Focus is a soft lock (leaving the app cracks the egg; other apps stay open), so the brief's hard lock is new work. The shortest session is 25 minutes, and a completed one pays about 29 coins against 700 for one castle upgrade. A finished session asks for the chapter only on extra screens afterwards (Bet 1 moves that choice to the start), and progress figures contradict themselves ("ON TRACK" at 0h of 59h; Chemistry 0/10 chapters shown as 14%). Power Rankings is a small list, not the 847 students promised at setup. There is no quiz in the app, and Wellness is empty without WHOOP.

**2 · GTM tracker** ([02_gtm_tracker.md](02_gtm_tracker.md), live dashboard)
Revenue vs target (pro-rated), trial / full / workshop split, onboarding, workshop fill and its program cross-sell, unpaid invoices with aging, and the trial renewal queue. The cohort funnel tracks show-up and ambition drop-off; CPQL is used instead of CPL; organic leads and journey days are reported separately for wins and losses. Creatives are ranked by CTR, frequency is flagged at 3+, and landing pages are checked for regressions. RCA is **rules, not opinions**: each ad set gets one of LEARNING / DROP / REFRESH / SCALE / HOLD. In the sample data the rules drop the teen ad set that has the 2nd-highest CTR, because its leads don't qualify.

**3 · Delivery structure** ([03_delivery_operating_system.md](03_delivery_operating_system.md))
Every OKR is a **bet** with a one-page brief: metric, baseline → target, guardrail, kill rule, cognitive-load budget, owner. It moves through Frame → Shape → Build → Pilot → Prove → Operate, with four gates enforced in ClickUp. Done means the metric moved or a decision was written down. The team runs a WIP limit of 2, three short rituals a week, and roughly 30% of capacity held back for proving and killing.

**4 · Student dashboard** ([04_student_dashboard.md](04_student_dashboard.md), live dashboard)
KPIs for every day / week / month / quarter activity through three lenses: **conducted** (delivery team), **liked** (program design), **performance** (student + advisor), plus advisor input metrics. More than 90% of the data is captured by systems (app events, wearables, calendar, QR check-in, one-tap ratings). A human types only chapter scores, rubric scores and targets. It shows up in four places: the advisor cockpit already in the app, a leadership board, a Sunday parent WhatsApp digest (advisor-approved) and a student Home card. v1 is ready 6 weeks in.

## 5. What makes it not break

Every automation logs failures to ClickUp and has a heartbeat checked hourly. Every write is idempotent, so a replayed Razorpay webhook can't double-count revenue. Thresholds live in tables and secrets in credentials. A five-minute Friday reconciliation checks Razorpay, Meta and ClickUp against the database. ([05_systems_and_data_flow.md](05_systems_and_data_flow.md))

## 6. What I checked, and what I'd confirm first

- **Checked:** the Android build hands-on (onboarding, a failed and a completed 25-min focus session, Realm, Power Rankings, Wellness, Academics; 22 findings in `01_app_adoption.md`). All 26 SQL queries run against the seed data (`python data/run_metrics.py`). The dashboards return the same numbers as the SQL for the same window. The generator reproduces the brief's Mixpanel figures, including the 2.15 baseline.
- **To confirm in week 1:** program prices (I assumed ₹45k for the trial and ₹1.8L for the full program), where the 8pm quiz runs today (it isn't in the app), how sessions are scheduled today, and wearable ownership across the 20 students.
