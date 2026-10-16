# Problem 1 · App adoption: 2.15 → 30 minutes a day

## 1. What the 2.15 minutes is made of

The brief gives one number. Split into its two factors, it says something more useful.

```
avg minutes / student / day  =  share of students who open the app that day  ×  minutes per active day
          2.16               =               20.6 %                           ×        10.5 min
```

Source: `sql/metrics/50_app_adoption.sql#minutes_decomposition`, run on a Mixpanel-shaped replica of the brief's 30 Aug – 13 Oct window (20 students, test devices excluded). The replica reproduces every number in the brief: 13 active this week, 7 dormant for 14 days, Realm used by 13, focus timer tried by 11 and used regularly by 5, one student each on WHOOP, Streak and Rankings, and Syllabus opened by 10 but by only 1 this week.

**Reading it:** when students do open the app, they stay about 10 minutes. The gap is that four out of five students don't open it on a given day. More features won't fix that. The app needs a reason to be opened every day.

## 2. Where 30 minutes can actually come from

Only one activity in the app can hold a teenager for 25–45 minutes: a **focus session** (phone locked into the app while they study). Everything else is single-digit minutes.

| Daily activity | Realistic minutes | Already in the app? |
|---|---|---|
| One focus session in tonight's self-study block | 25–45 | Yes (Focus Timer → dragon eggs), used regularly by 5 of 20 |
| 8pm quiz | 4–6 | Partly (`quiz_summary_viewed` fires) |
| Realm / dragons / coins after the session | 2–4 | Yes, the most-used feature |
| Logging the chapter step just studied | 1 | Yes (Syllabus), but it is a separate trip nobody makes |
| **Total for a student who does all four** | **32–56** | |

The target ladder that follows:

| Date | Daily active share | Min per active day | Avg min / student / day |
|---|---|---|---|
| Today (Oct) | 21% | 10.5 | **2.15** |
| 31 Dec | 50% | 20 | **10** |
| 31 Jan | 70% | 29 | **20** |
| 31 Mar (stable state) | 80% | 38 | **30** |

**A pushback on the metric itself.** Raw app time can be gamed by a timer left running under a pillow, and it also rewards scrolling the feed. I would report it, but make the north-star **focused study minutes logged per student per day**. That is 30 minutes of the right kind. Three counter-metrics guard against gaming:
1. Completed vs abandoned sessions (`focus_session_completed` / `focus_session_abandoned`)
2. The share of focus minutes that fall inside a planned self-study block
3. Syllabus pace. If minutes rise while chapters don't move, the minutes are not real study.

This also ties Problem 1 to Problem 4. The brief asks for a phone-locking focus mode on the student dashboard, and it is the same feature that delivers the 30 minutes. **Problem 1 and Problem 4 share one data spine:** every minute that counts toward adoption is also a row the advisor's weekly review needs.

## 3. Why students don't come back (hypotheses, to test in week 1)

| # | Hypothesis | Evidence in the brief | Test in week 1 |
|---|---|---|---|
| H1 | **Nothing in the program requires the app.** Weekly advisor reviews run on ClickUp notes, so students learn that logging in the app changes nothing. | Study features are tried, then abandoned (Syllabus 10 → 1). | Ask the 3 advisors what they open before a review. |
| H2 | **Input cost with no payoff.** Syllabus and the Study Planner ask for data entry and give nothing back that night. | Planner and Academic history: 0 users this week. | Session replays (the bundle already links `@mixpanel/react-native-session-replay`) of 5 Syllabus visits. |
| H3 | **Leaderboards don't work at n=20.** A global ranking of 20 people where the same 3 always lead is demotivating. | Rankings: 1 user. Streak: 1 user. | Interview the bottom 10 by focus minutes. |
| H4 | **Wellness is a dead end without a wearable.** 13 opened it; 1 connected WHOOP. | 0 of 13 came back. | Count how many students own any wearable. |
| H5 | **The Realm is the hook and it is fed by the wrong thing.** If coins and territory come from logging in, the game doesn't pull students toward studying. | Realm is the most-used feature this week. | Check what earns coins today. |

Week 1 method: 20-minute calls with all 20 students (n is small enough to talk to everyone), 6 parents and 3 advisors, plus 10 session replays. With 20 users, talking to everyone beats any survey.

## 4. What to build, in order

Ranked by expected minutes per unit of engineering effort.

**Bet 1 · "Tonight's study block" as Home's first card** (Nov W4 – Dec W1, FSE ~8 days)
- Home opens on one card, *"Study block 6:30–7:15 · Physics Ch 4 · Start"*, pulled from the timetable. One tap starts a focus session.
- Focus lock: iOS Screen Time API (FamilyControls / ManagedSettings; the app already ships a `withAlcoviaScreenTimeReport` plugin) and Android lock-task / usage-access. Calls stay allowed for a parent-whitelisted number list, as the brief requires.
- At the end of the session: one tap on *"What step did you finish?"* writes the chapter step (read / notes / practice score). Syllabus gets logged as a byproduct of studying, which removes H2.
- Success metric: share of students with at least one completed focus session per weekday goes from 25% to 60% by 1 Jan (all 5 pods live).

**Bet 2 · The Realm is fed only by focus** (Nov W4–W5, FSE ~3 days)
- Territory and dragon progress come from completed focus minutes, not daily logins. The game the students already like becomes the reward for the behaviour we want.
- Guardrail: Realm weekly actives must not fall below 13.

**Bet 3 · Pod leagues replace global Rankings** (Dec W1–W2, FSE ~4 days)
- 5-student pods already exist as the peer unit (Pod sessions). Each week a pod competes on total focus minutes against another pod. Mid-table students then have a race they can win, and teammates have a reason to nudge each other.

**Bet 4 · The 8pm quiz is the daily habit** (Dec W1, FSE ~2 days, mostly content ops)
- Push at 20:00 (`05_daily_quiz` workflow), deep link to the quiz, 5 questions, and the streak counts quiz days only.

**Bet 5 · Advisors and parents look at the app's numbers** (Dec, process designer)
- The weekly advisor session opens the progress board for that student (it lives in the advisor cockpit the app already has). If it isn't logged, it doesn't count.
- The Sunday parent digest (`07_weekly_parent_digest`) leads with focus minutes. The person paying for the program sees the habit, which is the strongest retention lever we have.

**Cut or hide** (Nov W3, 1 day): hide Wellness for students without a connected wearable; fold Study Planner into the timetable; move Academic history under Profile. That takes Home from 25 features down to 3 jobs: study now, quiz tonight, see your progress.

## 5. Measuring change with 20 students

A/B tests are meaningless at n=20. Instead, **roll out one pod per week** (5 pods, a stepped-wedge design). Each pod is compared with its own previous 2 weeks and with pods that haven't received the change yet. That controls for exam season, holidays and novelty. The decision rule for each bet is set before launch, in the bet brief (see `03_delivery_operating_system.md`):

- **Scale:** the metric moved by at least half the targeted lift in 2 of the first 3 pods, and the guardrails held.
- **Iterate:** it moved by less than half, but session replays show a fixable friction point.
- **Kill:** no movement after 3 pods, or a guardrail broke.

## 6. Instrumentation gaps to close first (Nov W1–W2)

1. Call `identify()` on login so `distinct_id` = `student_id`. Otherwise the advisor board can't join app events.
2. Add `planned_block_id` to `focus_session_started`, so timetable adherence can be measured.
3. Add `screen` and `duration_sec` to `app_session_ended` (used in the decomposition).
4. Move the two test devices into Mixpanel's internal-user filter, so nobody has to remember to exclude them.
5. Run a nightly raw export to Postgres (`09_mixpanel_raw_export`), so the same SQL serves the dashboards and the digest.
