# Problem 4 · Student dashboard: KPIs, capture, where it lives, timeline

Live prototype: `dashboards/student/index.html`. SQL: `sql/metrics/40_student_kpis.sql`. Schema: `sql/schema/02_student.sql`.

## 1. Three lenses, three different owners

| Lens | Question | Who is accountable | Typical failure it catches |
|---|---|---|---|
| **Quantity** | Did Alcovia conduct it? | Delivery team / program ops | Mentor calls quietly slipping from 4 a month to 2 |
| **Quality** | Did Alcovians like it? | Program design | Sessions held on schedule that students skip or rate 3/5 |
| **Performance** | How did the Alcovian do? | Student + academic advisor | A student attending everything while their syllabus falls behind |

Keeping them apart stops one lens from hiding a problem in another. If performance falls, the board shows whether we failed to deliver, delivered something students didn't value, or delivered well and the student still struggled. Each of those needs a different fix.

## 2. KPI catalogue

Formulas are the ones implemented in SQL and on the board. "Target" is where the cell turns green.

### Day level
| Activity | Quantity (did we run it) | Quality (did they like it) | Performance (how did they do) | Captured by |
|---|---|---|---|---|
| Timetable | % of students with a timetable for the week (target 100%) | Self-study blocks kept vs edited after the fact | **Timetable adherence** = focus minutes inside planned self-study blocks ÷ planned self-study minutes | App timetable + Google Calendar sync |
| 8pm quiz | Quizzes published ÷ days (target 100%) | % thumbs-up on the result screen; participation trend | Participation % · avg score · score trend by topic | n8n publishes; app records attempt and score |
| Focus time | Days a study block was offered | Completed ÷ started sessions (a high abandon rate means the blocks are too long) | **Focus min/day** (green ≥ 40) | App, `focus_session_*` events |
| Active minutes | (n/a) | Wearable connected and syncing ≥ 6 days a week | Avg active minutes/day · strain | WHOOP API, HealthKit, Health Connect (Samsung, Garmin) |
| Active recovery | (n/a) | (same) | Sleep hours (green ≥ 7.5) · recovery % · weekday vs weekend sleep gap | (same) |

### Week level: academic roadmap
| Activity | Quantity | Quality | Performance | Captured by |
|---|---|---|---|---|
| Academic sessions 1 & 2 | Held ÷ scheduled (target 95%) | Attendance · 1-tap rating · % rated 4–5 | Tasks assigned in the session that get done | Calendar → `activities`; QR check-in; push rating 30 min after the session |
| Goal setting & trend analysis | % subjects with targets per exam type · **% targets agreed with parents** | (n/a) | **Exam score vs target** (green within 2 pts) | Advisor, once per term; report card photo → advisor confirms |
| Time management | % students with weekly plan updated | (n/a) | **Task completion rate** · **Deadline adherence** · **Time estimation accuracy** = 1 − mean(abs(actual − estimate) ÷ estimate) | App tasks; actual minutes come from linked focus sessions |
| Syllabus completion | Chapters mapped to quarters (25% per quarter) | (n/a) | **Syllabus pace** = chapters started ÷ chapters expected by today · **Chapter readiness** = furthest rigour step × 20 · **Rigour %** = chapters at step ≥ 4 ÷ chapters started | 1 tap at the end of a focus session; the app blocks step 3 below 70% and step 5 below 80% |

**The five-step chapter rigour,** as stored in `chapter_stage_events`:

| Step | Meaning | Unlock rule | Readiness score |
|---|---|---|---|
| 1 | Read | tap | 20 |
| 2 | Notes / recall method | tap | 40 |
| 3 | End-of-chapter / worksheet practice | score ≥ 70% | 60 |
| 4 | Timed past paper | score entered | 80 |
| 5 | Exam-ready | past paper ≥ 80% | 100 |

### Month level
| Activity | Quantity | Quality | Performance |
|---|---|---|---|
| Career workshops (2/month) | Held ÷ planned · seats filled | Attendance · rating · % rated 4–5 | **11-skill facilitator rubric** (engagement, teamwork, crisis management, adaptability, public speaking …), cohort trend by month |
| Pod session | Held per pod | Attendance · rating | Pod members who complete their personal milestone that month |
| Peer session | Pairings made ÷ planned | Attendance · rating (both sides) | Peer's chapter readiness in the paired subject, before vs after |
| Mentor call | Calls held ÷ 1 per student | Rating · "would talk to them again" | Career-roadmap step unlocked by the call |
| Personal branding | Shoots done ÷ 1 per student · clips posted | Student approves the edit | Reach on Alcovia's Instagram (the team manages it) · LinkedIn posts by the student |

### Quarter level and roadmaps
| Activity | Quantity | Quality | Performance |
|---|---|---|---|
| Podcast shoot | Episodes recorded ÷ students | Rating · student would share it | Episode published; career clarity score before vs after |
| Competition prep | Students with a competition this quarter | Rating | Placed / participated / withdrew |
| Parent-child workshop | Held · % families with a parent present | Parent rating | (relationship, so not scored) |
| Out-of-city experience | Held · attendance | Rating | (experience, so not scored) |
| Quarter theme (social work / entrepreneurship / summer school) | Teams formed, weekly check-ins held | Mid-quarter pulse | Project shipped · applications submitted vs planned |
| Career roadmap | Roadmap exists | (n/a) | **Binary: done / not done** per milestone |
| Personal roadmap | Monthly milestone set | (n/a) | Milestones done on time % |
| Academic roadmap | Monthly sprint plan set | (n/a) | Syllabus pace + rigour % (above) |

### Advisor input metrics (they control whether the numbers above are trustworthy)
| Input | Metric | Target |
|---|---|---|
| Targets agreed with students and parents, with the logic written down | % exam targets with `parent_aligned_on` set | 100% |
| Guardrails: month-level chapter plan per subject | % subjects with chapters mapped to quarters | 100% |
| Input cadence | % students who logged a chapter step in the last 7 days | ≥ 90% |
| Automations fed | Escalations fired → % resolved, days to resolve | ≥ 60% resolved |
| Tutor trigger at X% deviation | Subjects ≥ 10 pts under target with a tutor plan within 7 days | 100% |
| Monthly sprints from missed timelines | Students behind on pace who have a sprint milestone this month | 100% |

## 3. What a non-subject-expert advisor can do for non-tuition subjects

Advisors don't teach content. They own **the process around the content**, and that is where most students fail:

1. **Set the target from trend, not hope.** The last 3 exam scores plus the subject affinity map (likes it / scores well despite disliking it) give each exam type a stretch-but-real target. Agree it with the parent.
2. **Turn the syllabus into a calendar.** 25% per quarter; chapters placed into weekly self-study blocks around school, tuition and activities.
3. **Enforce the five-step rigour.** An advisor doesn't need to know physics to see that a chapter stuck at "notes" for 3 weeks never got practised, or that practice accuracy is 55%.
4. **Source the practice material:** past papers, school worksheets, timed conditions.
5. **Pair peers.** Match a student who is exam-ready in a chapter with one who is stuck on it (peer session).
6. **Escalate on a rule, not a feeling.** 10+ points below target in two exams, or readiness under 40 at month end, triggers tutor support automatically (`06_student_escalations`).

## 4. Capture with minimal human intervention

| Data | Who types it | Effort per week |
|---|---|---|
| Focus minutes, quiz attempts, app usage, tasks done | Nobody (app events) | 0 |
| Sleep, recovery, active minutes | Nobody (wearable sync) | 0 |
| Chapter step reached | Student, 1 tap after a focus session (+ a score at steps 3–5) | ~2 min |
| Session held and attended | Calendar event + QR check-in at the door | 0 |
| Session rating | Student, 1 tap on a push 30 min after the session | ~10 sec each |
| Workshop soft-skill rubric | Facilitator, one form per workshop (11 skills × 1–5, pre-filled roster) | ~10 min per workshop |
| Exam results | Student uploads a report-card photo; advisor confirms the numbers | ~5 min per term |
| Targets, roadmap milestones | Advisor, at onboarding and monthly | ~15 min per student per month |

Everything else (pace, readiness, adherence, flags, escalations, parent digests) is computed.

## 5. Where it shows up

| Surface | Audience | Content | Build |
|---|---|---|---|
| **Advisor cockpit** (already in the app: `advisor_cockpit_viewed`, `advisor_student_progress_tab_viewed`) | Advisors, in the weekly session | The single-student view: scorecard vs cohort, subject table, milestones, nudges | FSE adds the progress tab payload from the SQL view |
| **Progress board** (web, internal) | Founders, program lead | Three lenses, cohort scorecard, advisor input health | Metabase on Supabase for v1; the prototype here is the spec |
| **Parent WhatsApp digest** (Sunday) | Parents | 5 lines: focus, quiz, tasks on time, syllabus pace, one thing to praise. Advisor approves before send. | `07_weekly_parent_digest` |
| **Student Home card** | Teen | "This week: 4h 10m focused · 3 chapters moved · pod rank 2/5" | One card, reads the same view |

## 6. Flag thresholds (green / amber / red)

| Metric | Green ≥ | Amber ≥ | Red below |
|---|---|---|---|
| Focus min/day | 40 | 15 | 15 |
| Quiz participation | 70% | 50% | 50% |
| Task completion | 80% | 60% | 60% |
| Deadline adherence | 70% | 50% | 50% |
| Syllabus pace | 95% | 80% | 80% |
| Chapter readiness | 60 | 40 | 40 |
| Exam vs target | −2 pts | −8 pts | −8 pts |
| Session attendance | 85% | 70% | 70% |
| Sleep | 7.5 h | 6.5 h | 6.5 h |

**At risk** = 3 or more red flags. **Watch** = at least 1 red flag, or 3 or more amber. The thresholds live in data (`escalation_thresholds`, plus the `RULES` block in the board), so the Friday review tunes them in one place.

## 7. Timeline

| Week | Deliverable |
|---|---|
| Nov W1–W2 | Schema live in Supabase; advisors' current ClickUp folders mapped to tables; a one-time backfill of Q1–Q2 chapter status by advisors (about 1 hour per student) |
| Nov W3–W4 | Capture: QR check-in, post-session rating push, rubric form, chapter step at the end of focus |
| Dec W1–W2 | **Progress board v1** in Metabase; escalation rules live for one pod |
| Dec W3 | Advisor cockpit progress tab; weekly review moves off ClickUp docs |
| Jan W1–W2 | Parent digest live; thresholds tuned on 4 weeks of real data |

Leadership has a working cohort view **6 weeks after day one**; advisors run their weekly review from it by **week 7**.
