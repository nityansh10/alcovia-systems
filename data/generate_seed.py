"""
Deterministic dummy-data generator for the Alcovia GTM tracker and student dashboard.

Every row is shaped exactly like the tables in sql/schema/, so the same seed
feeds three consumers:
    data/seed/*.csv            -> loaded by data/run_metrics.py into DuckDB to test the SQL
    dashboards/gtm/data.js     -> the GTM tracker (computes metrics client-side per date range)
    dashboards/student/data.js -> the student dashboard

The numbers are fake, but the mechanics are not: funnel stages happen in time order,
ad CTR decays as an audience saturates, 7-day frequency comes from a reach curve,
revenue only exists where a Razorpay payment exists, trials renew or lapse on their
end date. That way the dashboards show patterns a real account would show.

Run:  python data/generate_seed.py
"""
from __future__ import annotations

import csv
import json
import math
import random
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEED_DIR = ROOT / "data" / "seed"
START = date(2026, 4, 1)
AS_OF = date(2026, 10, 15)          # last complete day of data
R = random.Random(20261101)          # fixed seed: same output every run

TRIAL_PRICE = 45_000
FULL_PRICE = 180_000
SEAT_PRICE = 3_999


def days(a: date, b: date):
    d = a
    while d <= b:
        yield d
        d += timedelta(days=1)


def ts(d: date, hour_lo=9, hour_hi=22) -> datetime:
    return datetime(d.year, d.month, d.day, R.randint(hour_lo, hour_hi), R.randint(0, 59))


def add_months(d: date, n: int) -> date:
    m = d.month - 1 + n
    y = d.year + m // 12
    m = m % 12 + 1
    last = [31, 29 if y % 4 == 0 else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
    return date(y, m, min(d.day, last))


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


T: dict[str, list[dict]] = {}


def emit(table: str, row: dict):
    T.setdefault(table, []).append(row)


# =====================================================================
# GTM
# =====================================================================
def build_gtm():
    # ---- landing pages -------------------------------------------------
    lps = [
        ("lp_parent", "Program - Parent LP", "alcovia.life/roadmap", "program_parent", 2100, 0.44),
        ("lp_teen", "Program - Teen LP", "alcovia.life/ambition", "program_teen", 2400, 0.50),
        ("lp_wsp", "Workshop checkout", "alcovia.life/workshop", "workshop_checkout", 1700, 0.36),
    ]
    for lp_id, name, url, purpose, *_ in lps:
        emit("landing_pages", dict(landing_page_id=lp_id, name=name, url=url, purpose=purpose))
    lp_meta = {l[0]: dict(load=l[4], bounce=l[5]) for l in lps}

    # ---- campaigns / ad sets / ads ------------------------------------
    camp = [
        ("cmp_prg_ncr", "PRG | Parents | Delhi NCR | Lead form", "program", date(2026, 4, 1)),
        ("cmp_prg_metro", "PRG | Parents | Mumbai + Bengaluru | LP", "program", date(2026, 4, 1)),
        ("cmp_prg_teen", "PRG | Teens 14-17 | Ambition LP", "program", date(2026, 5, 15)),
        ("cmp_prg_rtg", "PRG | Retargeting | Site visitors 30d", "program", date(2026, 4, 20)),
        ("cmp_wsp", "WSP | Career Discovery Workshops", "workshop", date(2026, 4, 1)),
    ]
    # ad_set_id, campaign, name, audience, audience_size, ad budget/day, lead quality factor
    sets = [
        ("as_ncr_g9", "cmp_prg_ncr", "Parents of Class 8-10 | Interests: CBSE, IIT-JEE", "Parents 35-50, NCR", 260_000, 1.00),
        ("as_ncr_lal", "cmp_prg_ncr", "Lookalike 1% | Enrolled parents", "LAL 1%, NCR", 180_000, 1.25),
        ("as_metro_g9", "cmp_prg_metro", "Parents | Mumbai + Bengaluru | Education interests", "Parents 35-50, MUM+BLR", 420_000, 0.85),
        ("as_metro_ib", "cmp_prg_metro", "Parents | IB/IGCSE school followers", "Parents, IB schools", 95_000, 1.30),
        ("as_teen_broad", "cmp_prg_teen", "Teens 14-17 | Broad | Reels", "Teens 14-17, metros", 900_000, 0.55),
        ("as_rtg_30d", "cmp_prg_rtg", "Website visitors 30d | excl. leads", "Retargeting pool", 22_000, 1.40),
        ("as_wsp_parents", "cmp_wsp", "Parents | Workshop | NCR", "Parents 35-50, NCR", 300_000, 1.00),
        ("as_wsp_teens", "cmp_wsp", "Teens | Workshop | NCR + metros", "Teens 14-17", 650_000, 0.80),
    ]
    # ad_id, ad_set, name, type, hook, lp, launched, paused, base CTR, daily budget, fatigue/day
    ads = [
        ("ad_01", "as_ncr_g9", "Roadmap-in-60-min | video", "video", "Your teen's 5-year roadmap in one 60-minute session", "lp_parent", date(2026, 4, 1), date(2026, 7, 10), 0.016, 1400, 0.008),
        ("ad_02", "as_ncr_g9", "After-4pm | static", "static", "What toppers do between 4pm and 10pm", "lp_parent", date(2026, 4, 1), date(2026, 6, 5), 0.009, 900, 0.010),
        ("ad_03", "as_ncr_g9", "Stream-choice-Class-9 | carousel", "carousel", "Class 9 is the year that decides streams. Most parents find out in Class 11.", "lp_parent", date(2026, 6, 6), None, 0.019, 1500, 0.006),
        ("ad_04", "as_ncr_g9", "Parent-testimonial-Meera | video", "video", "\"My son stopped needing reminders\" - Meera, parent", "lp_parent", date(2026, 7, 11), None, 0.021, 1500, 0.007),
        ("ad_05", "as_ncr_lal", "Advisor-not-tutor | reel", "reel", "An advisor is not a tutor. Here is what changes.", "lp_parent", date(2026, 4, 5), None, 0.018, 1200, 0.005),
        ("ad_06", "as_ncr_lal", "Focus-2hrs | static", "static", "How Alcovians study 2 focused hours a day without a fight", "lp_parent", date(2026, 5, 1), date(2026, 8, 20), 0.012, 900, 0.009),
        ("ad_07", "as_ncr_lal", "Podcast-clip-teen-host | reel", "reel", "A 15-year-old interviewed a CXO. Watch.", "lp_parent", date(2026, 8, 21), None, 0.024, 1300, 0.006),
        ("ad_08", "as_metro_g9", "Roadmap-in-60-min | video", "video", "Your teen's 5-year roadmap in one 60-minute session", "lp_parent", date(2026, 4, 1), None, 0.011, 1300, 0.004),
        ("ad_09", "as_metro_g9", "Report-card-anxiety | static", "static", "Report card day should not be a surprise", "lp_parent", date(2026, 4, 1), date(2026, 9, 1), 0.007, 1000, 0.004),
        ("ad_10", "as_metro_g9", "Career-simulation | carousel", "carousel", "Be a doctor for 90 minutes: our career simulation workshops", "lp_parent", date(2026, 9, 2), None, 0.015, 1100, 0.005),
        ("ad_11", "as_metro_ib", "IB-roadmap | static", "static", "IB parents: the Extended Essay starts in Grade 10, not 11", "lp_parent", date(2026, 4, 10), None, 0.020, 900, 0.009),
        ("ad_12", "as_metro_ib", "Summer-school-acceptances | carousel", "carousel", "From Grade 10 to Stanford Pre-Collegiate: the timeline", "lp_parent", date(2026, 6, 15), None, 0.017, 800, 0.010),
        ("ad_13", "as_teen_broad", "Realm-game | reel", "reel", "Study 25 minutes. Hatch a dragon. Conquer the map.", "lp_teen", date(2026, 5, 15), None, 0.022, 1200, 0.003),
        ("ad_14", "as_teen_broad", "Day-in-life-designer | reel", "reel", "A day in the life of a product designer at 26", "lp_teen", date(2026, 5, 15), date(2026, 8, 1), 0.014, 900, 0.004),
        ("ad_15", "as_teen_broad", "Pod-sessions | video", "video", "Five teens. Two hours. No parents. Real talk.", "lp_teen", date(2026, 8, 2), None, 0.018, 1000, 0.003),
        ("ad_16", "as_rtg_30d", "Retarget-testimonial | video", "video", "\"My son stopped needing reminders\" - Meera, parent", "lp_parent", date(2026, 4, 20), None, 0.028, 700, 0.012),
        ("ad_17", "as_rtg_30d", "Retarget-offer-trial | static", "static", "Start with a 3-month trial. Decide with data.", "lp_parent", date(2026, 4, 20), None, 0.031, 600, 0.013),
        ("ad_18", "as_wsp_parents", "WSP-doctor-sim | carousel", "carousel", "Saturday workshop: your teen runs an ER for 90 minutes", "lp_wsp", date(2026, 4, 1), date(2026, 7, 1), 0.017, 900, 0.006),
        ("ad_19", "as_wsp_parents", "WSP-founder-sim | video", "video", "Saturday workshop: build a startup in 2 hours", "lp_wsp", date(2026, 7, 2), None, 0.019, 1000, 0.006),
        ("ad_20", "as_wsp_teens", "WSP-lawyer-sim | reel", "reel", "Argue a real case. Win it. Saturday, 3pm.", "lp_wsp", date(2026, 4, 1), None, 0.013, 700, 0.003),
        ("ad_21", "as_wsp_teens", "WSP-generic-careers | static", "static", "Confused about careers? Join our workshop", "lp_wsp", date(2026, 6, 1), None, 0.006, 600, 0.002),
    ]

    for cid, name, obj, started in camp:
        emit("campaigns", dict(campaign_id=cid, name=name, objective=obj, status="active", started_on=started))
    set_info = {}
    for sid, cid, name, aud, size, quality in sets:
        emit("ad_sets", dict(ad_set_id=sid, campaign_id=cid, name=name, audience=aud))
        set_info[sid] = dict(campaign=cid, size=size, quality=quality,
                             objective=next(c[2] for c in camp if c[0] == cid))
    ad_info = {}
    for a in ads:
        aid, sid, name, ctype, hook, lp, launched, paused, ctr, budget, fatigue = a
        emit("ads", dict(ad_id=aid, ad_set_id=sid, name=name, creative_type=ctype, hook=hook,
                         landing_page_id=lp, launched_on=launched, paused_on=paused))
        ad_info[aid] = dict(set=sid, lp=lp, launched=launched, paused=paused, ctr=ctr,
                            budget=budget, fatigue=fatigue)

    # ---- daily delivery ----------------------------------------------
    lp_clicks: dict[tuple, int] = {}
    set_week_impr: dict[tuple, int] = {}
    meta_leads_by_day: list[tuple[date, str, int]] = []
    for d in days(START, AS_OF):
        for aid, a in ad_info.items():
            if d < a["launched"] or (a["paused"] and d >= a["paused"]):
                continue
            s = set_info[a["set"]]
            age = (d - a["launched"]).days
            weekend = d.weekday() >= 5
            spend = a["budget"] * 0.8 * R.uniform(0.85, 1.12) * (1.08 if weekend else 1.0)
            cpm = R.uniform(170, 250) * (1.35 if s["size"] < 50_000 else 1.0)
            impr = int(spend / cpm * 1000)
            daily_freq = 1.08 + 0.002 * age + (0.25 if s["size"] < 50_000 else 0)
            reach = int(impr / daily_freq)
            ctr = a["ctr"] * max(0.42, 1 - a["fatigue"] * age) * R.uniform(0.85, 1.15)
            clicks = max(0, int(impr * ctr))
            if a["lp"] == "lp_parent" and s["campaign"] == "cmp_prg_ncr":
                cvr = 0.05                   # Meta instant form: higher submit rate
            elif a["lp"] == "lp_wsp":
                cvr = 0.085                  # checkout starts
            else:
                cvr = 0.03 * (0.72 if (a["lp"] == "lp_teen" and d >= date(2026, 9, 10)) else 1.0)
            leads = sum(1 for _ in range(clicks) if R.random() < cvr)
            emit("ad_daily_metrics", dict(date=d, ad_id=aid, impressions=impr, reach=reach,
                                          link_clicks=clicks, spend_inr=round(spend, 2), meta_leads=leads))
            lp_clicks[(d, a["lp"])] = lp_clicks.get((d, a["lp"]), 0) + clicks
            wk_end = d + timedelta(days=(6 - d.weekday()))           # week ends Sunday
            set_week_impr[(wk_end, a["set"])] = set_week_impr.get((wk_end, a["set"]), 0) + impr
            if leads:
                meta_leads_by_day.append((d, aid, leads))

    # 7-day frequency from a saturation curve: reach = S * (1 - e^(-I/S)).
    # The audience "remembers" prior weeks, so effective pool shrinks over time.
    first_week: dict[str, date] = {}
    for (wk, sid), impr in sorted(set_week_impr.items()):
        if wk > AS_OF + timedelta(days=6):
            continue
        first_week.setdefault(sid, wk)
        weeks_live = (wk - first_week[sid]).days // 7
        pool = set_info[sid]["size"] * max(0.12, 1 - 0.06 * weeks_live)
        if sid == "as_rtg_30d":
            pool = set_info[sid]["size"] * 0.55          # retargeting pool refills with new site visitors
        reach = int(pool * (1 - math.exp(-impr / pool)))
        emit("ad_set_weekly_frequency", dict(week_ending=wk, ad_set_id=sid, impressions=impr,
                                             reach=reach, frequency=round(impr / max(reach, 1), 2)))

    # ---- landing page health -----------------------------------------
    for d in days(START, AS_OF):
        for lp_id, m in lp_meta.items():
            organic = R.randint(25, 60) if lp_id != "lp_wsp" else R.randint(10, 30)
            sessions = int(lp_clicks.get((d, lp_id), 0) * 0.86) + organic
            load = m["load"]
            if lp_id == "lp_teen" and d >= date(2026, 9, 10):
                load = 4900                  # autoplay hero video shipped on 10 Sep
            if lp_id == "lp_parent" and date(2026, 6, 20) <= d <= date(2026, 6, 27):
                load = 3900                  # unoptimised testimonial images, fixed in a week
            p75 = int(load * R.uniform(0.92, 1.1))
            bounce_rate = clamp(m["bounce"] + max(0, (p75 - 2500)) / 10000 * 1.1 + R.uniform(-0.03, 0.03), 0.2, 0.9)
            bounces = int(sessions * bounce_rate)
            starts = int((sessions - bounces) * R.uniform(0.30, 0.40))
            submits = int(starts * R.uniform(0.48, 0.62))
            emit("landing_page_daily", dict(date=d, landing_page_id=lp_id, sessions=sessions, bounces=bounces,
                                            form_starts=starts, form_submits=submits, p75_load_ms=p75))

    # ---- workshops ---------------------------------------------------
    professions = ["Doctor", "Founder", "Lawyer", "Product Designer", "Investment Banker", "Architect",
                   "Journalist", "Psychologist", "Game Developer", "Diplomat", "Chef-Entrepreneur",
                   "Data Scientist", "Film Director", "Aerospace Engineer"]
    workshops = []
    d = date(2026, 4, 11)
    i = 0
    while d <= date(2026, 11, 7):
        wid = f"ws_{d:%Y%m%d}"
        prof = professions[i % len(professions)]
        workshops.append(dict(workshop_id=wid, title=f"A day as a {prof}", profession=prof,
                              held_on=d, seat_price_inr=SEAT_PRICE, capacity=40))
        d += timedelta(days=14)
        i += 1
    for w in workshops:
        emit("workshops", w)

    def next_workshop(on: date):
        for w in workshops:
            if w["held_on"] > on:
                return w
        return None

    seats_sold: dict[str, int] = {}
    lead_seq = 0
    pay_seq = 0

    def new_lead(created: datetime, source: str, ad_id=None):
        nonlocal lead_seq
        lead_seq += 1
        lid = f"cu_{lead_seq:05d}"
        emit("leads", dict(lead_id=lid, created_at=created, source=source, ad_id=ad_id,
                           teen_grade=R.choice([8, 9, 9, 10, 10, 11, 12]),
                           city=R.choice(["Delhi", "Gurugram", "Noida", "Mumbai", "Bengaluru", "Delhi", "Gurugram"])))
        return lid

    def buy_seat(on: date, ad_id=None):
        nonlocal pay_seq
        w = next_workshop(on)
        if not w or seats_sold.get(w["workshop_id"], 0) >= w["capacity"]:
            return None
        seats_sold[w["workshop_id"]] = seats_sold.get(w["workshop_id"], 0) + 1
        pay_seq += 1
        pid = f"pay_W{pay_seq:05d}"
        when = ts(on)
        emit("payments", dict(payment_id=pid, captured_at=when, amount_inr=SEAT_PRICE, revenue_line="workshop",
                              invoice_id=None, workshop_id=w["workshop_id"]))
        lid = new_lead(when, "workshop", ad_id)
        attended = (w["held_on"] <= AS_OF) and R.random() < 0.86
        emit("workshop_seats", dict(seat_id=f"seat_{pay_seq:05d}", workshop_id=w["workshop_id"], payment_id=pid,
                                    lead_id=lid, attended=attended))
        return lid, w

    # ---- leads ------------------------------------------------------
    program_leads: list[tuple[str, datetime, str, float]] = []   # lead_id, created, source, quality
    for d, aid, n in meta_leads_by_day:
        s = set_info[ad_info[aid]["set"]]
        for _ in range(n):
            if s["objective"] == "workshop":
                if R.random() < 0.34:                       # checkout started -> paid
                    res = buy_seat(d, aid)
                    if res:
                        lid, w = res
                        if R.random() < 0.35:               # parent asks about the program at/after the workshop
                            program_leads.append((lid, datetime.combine(w["held_on"], datetime.min.time()) + timedelta(hours=18), "workshop", 1.15))
            else:
                created = ts(d, 7, 23)
                program_leads.append((new_lead(created, "meta_ads", aid), created, "meta_ads", s["quality"]))
    for d in days(START, AS_OF):
        for _ in range(R.choice([0, 0, 1, 1, 2])):
            res = buy_seat(d)                                  # organic seat sales (Instagram, WhatsApp)
            if res and R.random() < 0.30:
                lid, w = res
                program_leads.append((lid, datetime.combine(w["held_on"], datetime.min.time()) + timedelta(hours=18), "workshop", 1.15))
        for src, rate, q in (("organic_instagram", 0.9, 1.05), ("referral", 0.55, 1.6), ("website", 0.6, 1.0)):
            n = sum(1 for _ in range(4) if R.random() < rate / 4)
            for _ in range(n):
                created = ts(d)
                program_leads.append((new_lead(created, src), created, src, q))

    # ---- funnel journeys ---------------------------------------------
    as_of_end = datetime.combine(AS_OF, datetime.max.time())
    won: list[tuple[str, datetime]] = []

    def stage(lid, name, at):
        if at <= as_of_end:
            emit("lead_stage_events", dict(lead_id=lid, stage=name, occurred_at=at))
            return True
        return False

    for lid, created, src, q in program_leads:
        t = created
        if created > as_of_end:
            continue
        base_q = {"meta_ads": 0.25, "organic_instagram": 0.40, "referral": 0.70, "website": 0.38, "workshop": 0.55}[src]
        t += timedelta(hours=R.randint(2, 40))
        if R.random() > clamp(base_q * q, 0.05, 0.92):
            stage(lid, "disqualified", t)
            continue
        if not stage(lid, "qualified", t):
            continue
        t += timedelta(hours=R.randint(4, 60))
        if R.random() > 0.78:
            stage(lid, "lost", t + timedelta(days=14))
            continue
        if not stage(lid, "discovery_scheduled", t):
            continue
        t += timedelta(days=R.randint(1, 4))
        show = 0.64 + (0.18 if src == "referral" else 0) + (0.08 if t.month >= 8 else 0)  # AI call reminders live from Aug
        if R.random() > show:
            stage(lid, "discovery_no_show", t)
            stage(lid, "lost", t + timedelta(days=10))
            continue
        if not stage(lid, "discovery_attended", t):
            continue
        t += timedelta(days=R.randint(1, 3))
        if R.random() > 0.84:
            stage(lid, "lost", t + timedelta(days=7))
            continue
        if not stage(lid, "ambition_scheduled", t):
            continue
        t += timedelta(days=R.randint(2, 6))
        if R.random() > 0.76:
            stage(lid, "ambition_no_show", t)
            stage(lid, "lost", t + timedelta(days=7))
            continue
        if not stage(lid, "ambition_attended", t):
            continue
        t += timedelta(days=R.randint(3, 8))
        if R.random() > 0.83:
            stage(lid, "lost", t + timedelta(days=7))
            continue
        if not stage(lid, "architect_done", t):
            continue
        t += timedelta(days=R.randint(1, 7))
        if R.random() > 0.33:
            stage(lid, "lost", t + timedelta(days=5))
            continue
        if stage(lid, "won", t):
            won.append((lid, t))

    # ---- enrollments, invoices, payments -----------------------------
    first = ["Aarav", "Vihaan", "Ishaan", "Kabir", "Reyansh", "Arjun", "Advait", "Dhruv", "Ayaan", "Rudra",
             "Anika", "Myra", "Kiara", "Saanvi", "Aadhya", "Ira", "Navya", "Tara", "Zoya", "Meher", "Riya", "Siya"]
    last = ["Sharma", "Mehta", "Kapoor", "Bansal", "Malhotra", "Gupta", "Reddy", "Iyer", "Khanna", "Arora",
            "Chopra", "Jain", "Nair", "Singh", "Agarwal", "Bhatia", "Sethi", "Rao"]
    enr_seq = 0
    inv_seq = 0

    def enroll(lid, name, plan, start, renewed_from=None):
        nonlocal enr_seq, inv_seq, pay_seq
        enr_seq += 1
        eid = f"enr_{enr_seq:04d}"
        price = TRIAL_PRICE if plan == "trial_3m" else FULL_PRICE
        end = add_months(start, 3 if plan == "trial_3m" else 12) - timedelta(days=1)
        emit("enrollments", dict(enrollment_id=eid, lead_id=lid, student_name=name, plan=plan,
                                 start_date=start, end_date=end, price_inr=price, renewed_from=renewed_from))
        inv_seq += 1
        iid = f"inv_{inv_seq:04d}"
        issued = start - timedelta(days=R.randint(0, 3)) if renewed_from is None else start - timedelta(days=7)
        pay_lag = R.choice([0, 0, 1, 2, 3, 5, 8, 12, 19, 30])
        pay_day = issued + timedelta(days=pay_lag)
        status = "paid" if pay_day <= AS_OF and R.random() > 0.05 else "issued"
        if issued > AS_OF:
            return eid, end
        emit("invoices", dict(invoice_id=iid, enrollment_id=eid, issued_on=issued,
                              due_on=issued + timedelta(days=7), amount_inr=price, status=status))
        if status == "paid":
            pay_seq += 1
            emit("payments", dict(payment_id=f"pay_P{pay_seq:05d}", captured_at=ts(pay_day), amount_inr=price,
                                  revenue_line="program_trial" if plan == "trial_3m" else "program_full",
                                  invoice_id=iid, workshop_id=None))
        return eid, end

    for lid, t in won:
        name = f"{R.choice(first)} {R.choice(last)}"
        plan = "trial_3m" if R.random() < 0.62 else "full_program"
        start = t.date() + timedelta(days=R.randint(0, 5))
        if start > AS_OF:
            start = AS_OF
        eid, end = enroll(lid, name, plan, start)
        # trial -> full program renewal, decided a week before the trial ends
        if plan == "trial_3m" and end - timedelta(days=7) <= AS_OF and R.random() < 0.56:
            enroll(lid, name, "full_program", end + timedelta(days=1), renewed_from=eid)

    # ---- targets ----------------------------------------------------
    m = START
    k = 0
    while m <= date(2026, 12, 1):
        prog = 1_000_000 + 300_000 * k
        wsp = 190_000 + 10_000 * k
        for metric, val in (("revenue_total", prog + wsp), ("revenue_program", prog), ("revenue_workshop", wsp),
                            ("students_onboarded", 14 + k), ("qualified_leads", 95 + 6 * k), ("cpql_max", 2000)):
            emit("monthly_targets", dict(month=m, metric=metric, target=val))
        m = add_months(m, 1)
        k += 1


# =====================================================================
# STUDENTS
# =====================================================================
SKILLS = ["engagement", "teamwork", "crisis_management", "adaptability", "public_speaking", "problem_solving",
          "leadership", "creativity", "communication", "curiosity", "empathy"]
QUIZ_TOPICS = ["Sports", "Indian history", "Logical reasoning", "Brand logos", "Science in the news", "Geography",
               "Business & startups", "Art & music", "World affairs", "Riddles & puzzles", "Space", "Economics basics"]


def build_students():
    advisors = [("adv_riya", "Riya Malhotra"), ("adv_kabir", "Kabir Sethi"), ("adv_ananya", "Ananya Iyer")]
    for aid, name in advisors:
        emit("advisors", dict(advisor_id=aid, name=name))

    roster = [
        # name, grade, board, engagement 0-1, academic skill 0-1, wearable
        ("Aarav Mehta", 10, "CBSE", 0.92, 0.80, "whoop"), ("Anika Kapoor", 9, "CBSE", 0.85, 0.72, "apple_watch"),
        ("Vihaan Bansal", 11, "CBSE", 0.40, 0.65, None), ("Myra Khanna", 10, "ICSE", 0.78, 0.88, "whoop"),
        ("Kabir Arora", 9, "CBSE", 0.25, 0.45, None), ("Saanvi Reddy", 10, "IB", 0.70, 0.83, "garmin"),
        ("Ishaan Gupta", 8, "CBSE", 0.55, 0.58, None), ("Kiara Jain", 11, "IGCSE", 0.33, 0.70, "apple_watch"),
        ("Reyansh Nair", 10, "CBSE", 0.65, 0.52, "samsung"), ("Ira Bhatia", 9, "ICSE", 0.88, 0.67, "whoop"),
        ("Dhruv Singh", 11, "CBSE", 0.20, 0.60, None), ("Aadhya Rao", 8, "CBSE", 0.60, 0.75, None),
        ("Arjun Chopra", 10, "CBSE", 0.47, 0.40, "samsung"), ("Tara Agarwal", 9, "IB", 0.74, 0.79, None),
        ("Ayaan Sharma", 10, "CBSE", 0.35, 0.55, None), ("Navya Iyer", 11, "CBSE", 0.81, 0.90, "whoop"),
        ("Rudra Malhotra", 9, "ICSE", 0.15, 0.50, None), ("Zoya Sethi", 10, "CBSE", 0.58, 0.62, None),
        ("Advait Kapoor", 8, "CBSE", 0.45, 0.68, None), ("Meher Gupta", 9, "CBSE", 0.67, 0.57, "apple_watch"),
        ("Siya Mehta", 10, "IGCSE", 0.30, 0.74, None), ("Riya Bansal", 11, "CBSE", 0.52, 0.47, None),
        ("Dev Arora", 9, "CBSE", 0.62, 0.66, None), ("Naira Khanna", 10, "CBSE", 0.76, 0.71, None),
    ]
    subj_by_board = {
        "CBSE": ["Mathematics", "Science", "Social Science", "English", "Hindi"],
        "ICSE": ["Mathematics", "Physics", "Chemistry", "History & Civics", "English"],
        "IB": ["Mathematics AA", "Physics", "Economics", "English A", "French B"],
        "IGCSE": ["Mathematics", "Physics", "Business Studies", "English", "Computer Science"],
    }
    pods = ["Pod Aurora", "Pod Banyan", "Pod Comet", "Pod Delta", "Pod Ember"]
    students = []
    for i, (name, grade, board, eng, skill, wear) in enumerate(roster):
        sid = f"stu_{i + 1:02d}"
        joined = START + timedelta(days=R.choice([0, 0, 0, 7, 14, 21, 35, 49, 63, 90, 120]))
        st = dict(student_id=sid, name=name, grade=grade, board=board, advisor_id=advisors[i % 3][0],
                  pod=pods[i % 5], joined_on=joined, wearable=wear)
        emit("students", st)
        students.append(dict(st, eng=eng, skill=skill))

    # ---- quizzes ----------------------------------------------------
    quiz_ids = {}
    for n, d in enumerate(days(START, AS_OF)):
        qid = f"qz_{d:%Y%m%d}"
        published = R.random() > 0.04
        emit("quizzes", dict(quiz_id=qid, quiz_date=d, topic=QUIZ_TOPICS[n % len(QUIZ_TOPICS)], published=published))
        quiz_ids[d] = (qid, published)

    task_seq = sess_seq = mile_seq = esc_seq = 0
    for st in students:
        sid, eng, skill = st["student_id"], st["eng"], st["skill"]
        # ---- subjects, chapters, rigour stages -----------------------
        for j, sname in enumerate(subj_by_board[st["board"]]):
            sub_id = f"{sid}_s{j + 1}"
            affinity = R.choice(["likes", "neutral", "neutral", "dislikes"])
            emit("subjects", dict(subject_id=sub_id, student_id=sid, name=sname, affinity=affinity,
                                  has_tutor=R.random() < (0.6 if sname.startswith(("Math", "Phys", "Chem", "Science")) else 0.15)))
            aff = {"likes": 0.12, "neutral": 0.0, "dislikes": -0.12}[affinity]
            readiness_sum = 0
            for c in range(12):
                chid = f"{sub_id}_c{c + 1:02d}"
                q = c // 3 + 1                                  # 3 chapters per quarter = 25% per quarter
                emit("chapters", dict(chapter_id=chid, subject_id=sub_id, name=f"{sname} - Ch {c + 1}", planned_quarter=q))
                q_start = add_months(date(2026, 4, 1), 3 * (q - 1))
                if q_start > AS_OF:
                    continue
                p = clamp(0.55 + 0.40 * eng + 0.2 * skill + aff - (0.15 if q == 3 else 0), 0.05, 0.98)
                d = max(q_start, st["joined_on"]) + timedelta(days=R.randint(0, 25))
                top = 0
                for stg in range(1, 6):
                    if d > AS_OF or R.random() > p:
                        break
                    acc = None
                    if stg >= 3:
                        acc = round(clamp(R.gauss(68 + 22 * skill + aff * 40 + stg * 3, 8), 30, 99), 1)
                        if (stg in (3, 4) and acc < 70) or (stg == 5 and acc < 80):
                            break                                # the app blocks the step below threshold
                    emit("chapter_stage_events", dict(chapter_id=chid, stage=stg, reached_on=d, accuracy_pct=acc))
                    top = stg
                    d += timedelta(days=R.randint(2, 9))
                    p *= 0.95
                readiness_sum += top * 20 if q <= 2 else 0
            # ---- targets and results ---------------------------------
            ready = readiness_sum / (6 * 100)                       # Q1+Q2 chapters, 0-1
            for et in ("unit_test", "half_yearly"):
                tgt = round(clamp(70 + 22 * skill + aff * 30 + R.uniform(-3, 3), 55, 96))
                emit("exam_targets", dict(student_id=sid, subject_id=sub_id, exam_type=et, target_pct=tgt,
                                          parent_aligned_on=(st["joined_on"] + timedelta(days=R.randint(5, 20))) if R.random() < 0.8 else None))
                exam_day = date(2026, 7, 14) if et == "unit_test" else date(2026, 9, 22)
                if exam_day > st["joined_on"] + timedelta(days=20):
                    score = clamp(tgt - 13 + 22 * ready + R.gauss(0, 5), 30, 99)
                    emit("exam_results", dict(subject_id=sub_id, exam_type=et, exam_date=exam_day, score_pct=round(score, 1)))

        # ---- day-level rhythm ----------------------------------------
        focus_user = eng > 0.62
        miss_streak = 0
        last_focus = st["joined_on"]
        for d in days(st["joined_on"], AS_OF):
            wkd = d.weekday()
            ss_min = 150 if wkd >= 5 else R.choice([90, 105, 120])
            emit("timetable_blocks", dict(student_id=sid, date=d, kind="self_study", planned_min=ss_min))
            if wkd < 5 and R.random() < 0.5:
                emit("timetable_blocks", dict(student_id=sid, date=d, kind="tuition", planned_min=R.choice([60, 90])))
            emit("timetable_blocks", dict(student_id=sid, date=d, kind="extracurricular", planned_min=R.choice([45, 60, 90])))
            emit("timetable_blocks", dict(student_id=sid, date=d, kind="free", planned_min=R.choice([45, 60, 75])))

            # focus sessions
            p_focus = (0.30 + 0.55 * eng) if focus_user else (0.10 * eng)
            fm = 0
            if R.random() < p_focus:
                for _ in range(R.choice([1, 1, 2, 2, 3])):
                    sess_seq += 1
                    planned = R.choice([25, 25, 45, 50, 60])
                    done = R.random() < 0.55 + 0.35 * eng
                    actual = planned if done else R.randint(3, planned - 5)
                    emit("focus_sessions", dict(session_id=f"fs_{sess_seq:06d}", student_id=sid,
                                                started_at=ts(d, 16, 21), planned_min=planned, actual_min=actual,
                                                status="completed" if done else "abandoned",
                                                in_planned_block=R.random() < 0.55 + 0.35 * eng))
                    fm += actual
                last_focus = d
            # app foreground minutes (browse, excluding the locked focus screen)
            if R.random() < 0.18 + 0.55 * eng:
                emit("app_daily_usage", dict(student_id=sid, date=d,
                                             foreground_min=round(clamp(R.lognormvariate(0.9 + 0.8 * eng, 0.55), 0.3, 25), 2)))
            # 8pm quiz
            qid, published = quiz_ids[d]
            if published and R.random() < 0.25 + 0.6 * eng:
                emit("quiz_attempts", dict(quiz_id=qid, student_id=sid,
                                           score_pct=round(clamp(R.gauss(52 + 30 * skill, 14), 0, 100), 0),
                                           liked=(R.random() < 0.78) if R.random() < 0.6 else None))
                miss_streak = 0
            else:
                miss_streak += 1
                if miss_streak == 3:
                    esc_seq += 1
                    emit("escalations", dict(escalation_id=f"esc_{esc_seq:05d}", student_id=sid, rule="quiz_missed_3d",
                                             triggered_on=d, notified="student",
                                             resolved_on=d + timedelta(days=R.randint(1, 5)) if R.random() < 0.6 else None))
            if focus_user and (d - last_focus).days == 3:
                esc_seq += 1
                emit("escalations", dict(escalation_id=f"esc_{esc_seq:05d}", student_id=sid, rule="no_focus_3d",
                                         triggered_on=d, notified="student",
                                         resolved_on=d + timedelta(days=R.randint(1, 4)) if R.random() < 0.7 else None))
            # wearables
            if st["wearable"] and R.random() < 0.9:
                emit("wearable_daily", dict(student_id=sid, date=d,
                                            active_min=int(clamp(R.gauss(48 + (25 if wkd >= 5 else 0), 18), 5, 180)),
                                            strain=round(clamp(R.gauss(11, 3), 2, 20), 1) if st["wearable"] == "whoop" else None,
                                            sleep_min=int(clamp(R.gauss(445 - (35 if wkd < 5 else -20), 45), 280, 600)),
                                            recovery_pct=round(clamp(R.gauss(62, 16), 8, 99), 0)))

            # tasks: advisor assigns Mon/Thu, self tasks random
            n_tasks = (2 if wkd in (0, 3) else 0) + (1 if R.random() < 0.15 + 0.3 * eng else 0)
            for k in range(n_tasks):
                task_seq += 1
                src = "advisor" if k < 2 and wkd in (0, 3) else "self"
                due = d + timedelta(days=R.randint(1, 5))
                est = R.choice([30, 45, 60, 90, 120])
                completed = None
                actual = None
                if R.random() < 0.6 + 0.38 * eng:
                    lag = R.randint(-4, 3) - (1 if eng > 0.6 else 0)
                    c_day = max(d, due - timedelta(days=1) + timedelta(days=lag))
                    if c_day <= AS_OF:
                        completed = c_day
                        actual = int(est * clamp(R.lognormvariate(0.15 - 0.2 * eng, 0.35), 0.5, 3))
                emit("tasks", dict(task_id=f"tk_{task_seq:06d}", student_id=sid, source=src, created_on=d, due_on=due,
                                   estimated_min=est, actual_min=actual, completed_on=completed))
                if src == "advisor" and (completed is None or completed > due + timedelta(days=2)) and due + timedelta(days=2) <= AS_OF:
                    esc_seq += 1
                    emit("escalations", dict(escalation_id=f"esc_{esc_seq:05d}", student_id=sid, rule="task_overdue",
                                             triggered_on=due + timedelta(days=2),
                                             notified="parent" if R.random() < 0.3 else "student", resolved_on=completed))

        # ---- roadmap milestones --------------------------------------
        m = add_months(date(st["joined_on"].year, st["joined_on"].month, 1), 1)
        while m <= date(2026, 11, 1):
            for rm, title in (("personal", "Monthly personal milestone"), ("academic", "Monthly syllabus sprint")):
                mile_seq += 1
                due = m + timedelta(days=27)
                done = due - timedelta(days=R.randint(-5, 10)) if R.random() < 0.4 + 0.5 * eng else None
                emit("roadmap_milestones", dict(milestone_id=f"ms_{mile_seq:05d}", student_id=sid, roadmap=rm,
                                                title=f"{title} - {m:%b}", due_on=due,
                                                done_on=done if (done and done <= AS_OF) else None))
            m = add_months(m, 1)
        for k, title in enumerate(["Career interest inventory", "Two mentor calls in chosen field", "Shadow a professional for a day"]):
            mile_seq += 1
            due = st["joined_on"] + timedelta(days=45 * (k + 1))
            done = due - timedelta(days=R.randint(-6, 12)) if R.random() < 0.35 + 0.5 * eng else None
            emit("roadmap_milestones", dict(milestone_id=f"ms_{mile_seq:05d}", student_id=sid, roadmap="career",
                                            title=title, due_on=due, done_on=done if (done and done <= AS_OF) else None))

    # ---- program delivery: activities --------------------------------
    act_seq = 0
    by_id = {s["student_id"]: s for s in students}

    def activity(kind, title, sched, members, p_conduct, rating_mu, skills=False):
        nonlocal act_seq
        act_seq += 1
        aid = f"act_{act_seq:05d}"
        conducted = sched if (sched <= AS_OF and R.random() < p_conduct) else None
        emit("activities", dict(activity_id=aid, kind=kind, title=title, scheduled_on=sched, conducted_on=conducted))
        if conducted is None:
            return
        for sid in members:
            s = by_id[sid]
            if s["joined_on"] > sched:
                continue
            att = R.random() < 0.6 + 0.35 * s["eng"]
            rating = int(clamp(round(R.gauss(rating_mu + 0.4 * (s["eng"] - 0.5), 0.7)), 1, 5)) if att and R.random() < 0.55 + 0.4 * s["eng"] else None
            emit("activity_participants", dict(activity_id=aid, student_id=sid, attended=att, rating=rating))
            if skills and att:
                weeks_in = (sched - s["joined_on"]).days / 7
                for sk in SKILLS:
                    emit("soft_skill_scores", dict(activity_id=aid, student_id=sid, skill=sk,
                                                   score=int(clamp(round(R.gauss(2.6 + 0.9 * s["eng"] + 0.03 * weeks_in, 0.7)), 1, 5))))

    all_ids = [s["student_id"] for s in students]
    # weekly academic sessions (2 per student per week)
    for s in students:
        d = s["joined_on"] + timedelta(days=(1 - s["joined_on"].weekday()) % 7)
        while d <= AS_OF + timedelta(days=13):
            for n, off in ((1, 0), (2, 3)):
                activity("academic_session", f"Academic session {n} - {s['name'].split()[0]}", d + timedelta(days=off),
                         [s["student_id"]], 0.93, 3.9)
            d += timedelta(days=7)
    # fortnightly workshops (whole cohort) with soft-skill rubric
    d = date(2026, 4, 11)
    profs = ["Doctor", "Founder", "Lawyer", "Product Designer", "Investment Banker", "Architect", "Journalist",
             "Psychologist", "Game Developer", "Diplomat", "Chef-Entrepreneur", "Data Scientist", "Film Director", "Aerospace Engineer"]
    i = 0
    while d <= AS_OF + timedelta(days=28):
        activity("workshop", f"Career workshop: {profs[i % len(profs)]}", d, all_ids, 0.97, 4.3, skills=True)
        d += timedelta(days=14)
        i += 1
    # monthly: pods, peer, mentor calls, branding shoots
    m = date(2026, 4, 1)
    while m <= date(2026, 11, 1):
        for p in sorted({s["pod"] for s in students}):
            members = [s["student_id"] for s in students if s["pod"] == p]
            activity("pod", f"{p} - {m:%b}", m + timedelta(days=R.randint(8, 20)), members, 0.9, 4.2)
        for s in students:
            activity("peer_session", f"Peer session - {s['name'].split()[0]} - {m:%b}", m + timedelta(days=R.randint(5, 25)), [s["student_id"]], 0.82, 4.0)
            activity("mentor_call", f"Mentor call - {s['name'].split()[0]} - {m:%b}", m + timedelta(days=R.randint(5, 25)), [s["student_id"]], 0.76, 4.5)
            activity("branding_shoot", f"Branding shoot - {s['name'].split()[0]} - {m:%b}", m + timedelta(days=R.randint(5, 25)), [s["student_id"]], 0.68, 4.1)
        m = add_months(m, 1)
    # quarterly
    for q_start in (date(2026, 4, 1), date(2026, 7, 1), date(2026, 10, 1)):
        for s in students:
            activity("podcast", f"Podcast shoot - {s['name'].split()[0]} - Q{(q_start.month - 1) // 3 + 1}", q_start + timedelta(days=R.randint(20, 80)), [s["student_id"]], 0.8, 4.6)
            activity("competition_prep", f"Competition prep - {s['name'].split()[0]} - Q{(q_start.month - 1) // 3 + 1}", q_start + timedelta(days=R.randint(10, 70)), [s["student_id"]], 0.85, 4.0)
        activity("parent_child", f"Parent-child workshop - Q{(q_start.month - 1) // 3 + 1}", q_start + timedelta(days=R.randint(30, 60)), all_ids, 0.95, 4.5)
        activity("out_of_city", f"Out-of-city experience - Q{(q_start.month - 1) // 3 + 1}", q_start + timedelta(days=R.randint(40, 80)), all_ids, 0.9, 4.7)


# =====================================================================
# APP EVENTS (mirrors the Mixpanel summary in the brief: 30 Aug - 13 Oct, 20 students)
# =====================================================================
def build_app_events():
    feature_map = [
        ("home_viewed", "home", "home"), ("daily_login_reward_claimed", "home", "home"),
        ("dashboard_widget_clicked", "home", "home"),
        ("territory_map_viewed", "realm", "focus_game"), ("conquest_sheet_opened", "realm", "focus_game"),
        ("dragon_sanctuary_viewed", "realm", "focus_game"),
        ("focus_timer_viewed", "focus_timer", "focus_game"), ("focus_session_started", "focus_timer", "focus_game"),
        ("focus_session_completed", "focus_timer", "focus_game"), ("focus_session_abandoned", "focus_timer", "focus_game"),
        ("focus_egg_hatched", "focus_timer", "focus_game"),
        ("rankings_global_viewed", "rankings", "focus_game"), ("streak_banner_clicked", "streak", "focus_game"),
        ("side_quest_completed", "side_quests", "focus_game"),
        ("syllabus_card_clicked", "syllabus", "study"), ("chapter_revision_completed", "syllabus", "study"),
        ("study_planner_viewed", "study_planner", "study"), ("academic_history_viewed", "academic_history", "study"),
        ("attendance_card_clicked", "attendance", "study"),
        ("goals_list_viewed", "goals", "plan"), ("todo_list_viewed", "tasks", "plan"), ("sessions_list_viewed", "sessions", "plan"),
        ("wellness_dashboard_viewed", "wellness", "wellness"), ("wellness_onboarding_connect_completed", "wellness", "wellness"),
        ("time_usage_dashboard_viewed", "wellness", "wellness"),
        ("quiz_summary_viewed", "quiz", "home"),
    ]
    for ev, feat, area in feature_map:
        emit("event_feature_map", dict(event=ev, feature=feat, area=area))

    a, b = date(2026, 8, 30), date(2026, 10, 13)
    seq = 0

    def ev(sid, name, d, dur=None, test=False):
        nonlocal seq
        seq += 1
        emit("app_events", dict(insert_id=f"mp_{seq:07d}", distinct_id=sid, event=name, ts=ts(d, 7, 23),
                                duration_sec=dur, is_test_device=test))

    # 20 students: 13 active in the final week, 7 silent for the last 14 days
    profiles = []
    for i in range(20):
        sid = f"stu_{i + 1:02d}"
        dormant = i >= 13
        profiles.append(dict(sid=sid, dormant=dormant,
                             realm=i < 13, focus_try=i < 11, focus_regular=i < 5,
                             syllabus=i < 10, syllabus_recent=i == 0, wellness=i < 13, whoop=i == 2,
                             streak=i == 1, rankings=i == 4, goals_done=i == 6, planner=i < 6, history=i < 4))
    for p in profiles:
        last_day = date(2026, 9, 28) if p["dormant"] else b
        for d in days(a, last_day):
            active = R.random() < (0.24 if not p["dormant"] else 0.20)
            if not active:
                continue
            ev(p["sid"], "home_viewed", d)
            ev(p["sid"], "daily_login_reward_claimed", d)
            ev(p["sid"], "app_session_ended", d, dur=int(clamp(R.lognormvariate(6.30, 0.6), 20, 3600)))
            if p["realm"] and R.random() < 0.5:
                ev(p["sid"], "territory_map_viewed", d)
            if p["focus_try"] and (p["focus_regular"] and R.random() < 0.8 or R.random() < 0.02):
                ev(p["sid"], "focus_session_started", d)
                ev(p["sid"], "focus_session_completed" if R.random() < 0.7 else "focus_session_abandoned", d, dur=60 * R.choice([25, 25, 45]))
            if p["syllabus"] and (d < date(2026, 9, 20) and R.random() < 0.12 or p["syllabus_recent"] and R.random() < 0.3):
                ev(p["sid"], "syllabus_card_clicked", d)
            if p["wellness"] and d < date(2026, 9, 25) and R.random() < 0.05:
                ev(p["sid"], "wellness_dashboard_viewed", d)
            if p["planner"] and d < date(2026, 9, 25) and R.random() < 0.05:
                ev(p["sid"], "study_planner_viewed", d)
            if p["history"] and d < date(2026, 9, 25) and R.random() < 0.04:
                ev(p["sid"], "academic_history_viewed", d)
        # guarantee the "at least once" behaviours the brief reports
        for flag, name in (("whoop", "wellness_onboarding_connect_completed"), ("streak", "streak_banner_clicked"),
                           ("rankings", "rankings_global_viewed"), ("goals_done", "goals_list_viewed")):
            if p[flag]:
                ev(p["sid"], name, date(2026, 9, 12))
        for flag, name in (("realm", "territory_map_viewed"), ("focus_try", "focus_timer_viewed"),
                           ("syllabus", "syllabus_card_clicked"), ("wellness", "wellness_dashboard_viewed"),
                           ("planner", "study_planner_viewed"), ("history", "academic_history_viewed")):
            if p[flag]:
                ev(p["sid"], name, date(2026, 9, 3))
        if p["realm"] and not p["dormant"]:
            ev(p["sid"], "territory_map_viewed", date(2026, 10, 10))
            ev(p["sid"], "home_viewed", date(2026, 10, 10))
        if p["syllabus_recent"]:
            ev(p["sid"], "syllabus_card_clicked", date(2026, 10, 9))
    for d in days(a, b):                                            # two internal test devices
        for t in ("test_device_ios", "test_device_android"):
            ev(t, "home_viewed", d, test=True)
            ev(t, "app_session_ended", d, dur=900, test=True)


# =====================================================================
# OUTPUT
# =====================================================================
def fmt(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(v, date):
        return v.isoformat()
    return v


def write_csvs():
    SEED_DIR.mkdir(parents=True, exist_ok=True)
    for name, rows in T.items():
        with open(SEED_DIR / f"{name}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            for r in rows:
                w.writerow({k: fmt(v) for k, v in r.items()})


def columnar(name, cols=None, where=None):
    rows = T.get(name, [])
    if where:
        rows = [r for r in rows if where(r)]
    cols = cols or list(rows[0].keys())

    def j(v):
        v = fmt(v)
        return None if v == "" else v
    return dict(cols=cols, rows=[[j(r[c]) for c in cols] for r in rows])


def write_dashboard_data():
    gtm_tables = ["monthly_targets", "campaigns", "ad_sets", "ads", "landing_pages", "ad_daily_metrics",
                  "ad_set_weekly_frequency", "landing_page_daily", "leads", "lead_stage_events", "workshops",
                  "enrollments", "invoices", "payments", "workshop_seats"]
    gtm = dict(as_of=AS_OF.isoformat(), start=START.isoformat(),
               tables={t: columnar(t) for t in gtm_tables})
    stu_tables = ["advisors", "students", "subjects", "chapters", "chapter_stage_events", "exam_targets", "exam_results",
                  "tasks", "focus_sessions", "quizzes", "quiz_attempts", "wearable_daily", "app_daily_usage",
                  "activities", "activity_participants", "soft_skill_scores", "roadmap_milestones", "escalations"]
    stu = dict(as_of=AS_OF.isoformat(), start=START.isoformat(),
               tables={t: columnar(t) for t in stu_tables})
    stu["tables"]["timetable_blocks"] = columnar("timetable_blocks", where=lambda r: r["kind"] == "self_study")
    for folder, var, payload in (("gtm", "GTM_DATA", gtm), ("student", "STUDENT_DATA", stu)):
        out = ROOT / "dashboards" / folder / "data.js"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(f"// Generated by data/generate_seed.py - dummy data, do not edit by hand\n"
                       f"window.{var} = {json.dumps(payload, separators=(',', ':'))};\n", encoding="utf-8")
        print(f"  {out.relative_to(ROOT)}  {out.stat().st_size / 1024:,.0f} KB")


if __name__ == "__main__":
    build_gtm()
    build_students()
    build_app_events()
    write_csvs()
    print(f"Seed written to {SEED_DIR.relative_to(ROOT)}:")
    for name, rows in sorted(T.items()):
        print(f"  {name:<26} {len(rows):>7,} rows")
    write_dashboard_data()
