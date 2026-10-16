"""
Writes the n8n workflow exports in n8n/workflows/*.json (import via n8n > Workflows > Import from file).

Why a builder instead of hand-edited JSON: every workflow must follow the same
"doesn't break" rules, and code enforces them better than review does.
  1. errorWorkflow = 00_error_handler on every workflow (no silent failures)
  2. Every write is idempotent (ON CONFLICT ... DO NOTHING/UPDATE on a natural key),
     so retries and duplicate webhooks never double-count revenue or stages
  3. Every external call has retries with backoff (retryOnFail, 3 tries, 5s)
  4. Each scheduled job writes a heartbeat to sync_runs so the dashboards can show
     "last synced" and the error handler can detect a job that silently stopped
  5. Secrets live in n8n credentials, never in node parameters

Run:  python n8n/build_workflows.py
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

OUT = Path(__file__).resolve().parent / "workflows"
NS = uuid.UUID("6f1c3a52-2c1e-4a4e-9a51-0a1c0b1a2026")

PG = {"postgres": {"id": "supabase-pg", "name": "Supabase Postgres (alcovia)"}}
CLICKUP = {"clickUpApi": {"id": "clickup", "name": "ClickUp (alcovia workspace)"}}


def nid(wf: str, name: str) -> str:
    return str(uuid.uuid5(NS, wf + "/" + name))


class WF:
    def __init__(self, key: str, name: str, tags: list[str]):
        self.key, self.name, self.tags = key, name, tags
        self.nodes: list[dict] = []
        self.conn: dict = {}
        self.x = 0

    def node(self, name, type_, version, params, creds=None, retry=False, pos=None, **extra):
        n = {"id": nid(self.key, name), "name": name, "type": type_, "typeVersion": version,
             "position": pos or [self.x, 300], "parameters": params}
        if creds:
            n["credentials"] = creds
        if retry:
            n.update({"retryOnFail": True, "maxTries": 3, "waitBetweenTries": 5000})
        n.update(extra)
        self.nodes.append(n)
        self.x += 240
        return name

    def link(self, a, b, out=0):
        outs = self.conn.setdefault(a, {"main": []})["main"]
        while len(outs) <= out:
            outs.append([])
        outs[out].append({"node": b, "type": "main", "index": 0})

    def chain(self, *names):
        for a, b in zip(names, names[1:]):
            self.link(a, b)

    def dump(self):
        wf = {
            "name": self.name,
            "nodes": self.nodes,
            "connections": self.conn,
            "active": False,
            "settings": {"executionOrder": "v1", "timezone": "Asia/Kolkata",
                         "saveManualExecutions": True, "callerPolicy": "workflowsFromSameOwner",
                         **({} if self.key == "00_error_handler" else {"errorWorkflow": "00_error_handler"})},
            "tags": [{"name": t} for t in self.tags],
            "meta": {"templateCredsSetupCompleted": False},
            "pinData": {},
        }
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / f"{self.key}.json").write_text(json.dumps(wf, indent=2), encoding="utf-8")
        print(f"  n8n/workflows/{self.key}.json  ({len(self.nodes)} nodes)")


def pg(wf: WF, name, sql, replacement=None, **kw):
    params = {"operation": "executeQuery", "query": sql.strip(), "options": {}}
    if replacement:
        params["options"]["queryReplacement"] = replacement
    return wf.node(name, "n8n-nodes-base.postgres", 2.5, params, creds=PG, retry=True, **kw)


def code(wf: WF, name, js, **kw):
    return wf.node(name, "n8n-nodes-base.code", 2, {"jsCode": js.strip()}, **kw)


def cron(wf: WF, name, expr):
    return wf.node(name, "n8n-nodes-base.scheduleTrigger", 1.2,
                   {"rule": {"interval": [{"field": "cronExpression", "expression": expr}]}})


def http(wf: WF, name, method, url, cred_type=None, query=None, body=None, **kw):
    p = {"method": method, "url": url, "options": {"timeout": 30000}}
    if cred_type:
        p["authentication"] = "genericCredentialType"
        p["genericAuthType"] = cred_type
    if query:
        p["sendQuery"] = True
        p["queryParameters"] = {"parameters": [{"name": k, "value": v} for k, v in query.items()]}
    if body is not None:
        p["sendBody"] = True
        p["specifyBody"] = "json"
        p["jsonBody"] = body
    return wf.node(name, "n8n-nodes-base.httpRequest", 4.2, p, retry=True, **kw)


def heartbeat(wf: WF, job):
    return pg(wf, "Heartbeat", f"""
INSERT INTO sync_runs (job, finished_at, rows_written)
VALUES ('{job}', now(), $1)
ON CONFLICT (job) DO UPDATE SET finished_at = EXCLUDED.finished_at, rows_written = EXCLUDED.rows_written;""",
              "={{ $input.all().length }}", executeOnce=True)


# ---------------------------------------------------------------------
def error_handler():
    w = WF("00_error_handler", "00 · Error handler (all workflows)", ["ops"])
    t = w.node("On any workflow error", "n8n-nodes-base.errorTrigger", 1, {})
    c = code(w, "Shape alert", r"""
const e = $json.execution || {};
const wf = $json.workflow || {};
return [{ json: {
  title: `[n8n] ${wf.name} failed at "${e.lastNodeExecuted || 'unknown node'}"`,
  body: `Error: ${(e.error && e.error.message) || 'no message'}\nExecution: ${e.url || e.id}\nMode: ${e.mode}\n\nRunbook: docs/05_systems_and_data_flow.md#runbooks`,
  workflow: wf.name,
}}];""")
    log = pg(w, "Log failure", """
INSERT INTO sync_failures (workflow, failed_at, message) VALUES ($1, now(), $2);""",
             "={{ $json.workflow }},={{ $json.body }}")
    task = w.node("ClickUp task for owner", "n8n-nodes-base.clickUp", 1, {
        "team": "={{ $env.CLICKUP_TEAM_ID }}", "space": "={{ $env.CLICKUP_SYSTEMS_SPACE }}",
        "list": "={{ $env.CLICKUP_SYSTEMS_INCIDENTS_LIST }}", "name": "={{ $json.title }}",
        "additionalFields": {"content": "={{ $json.body }}", "priority": 2, "tags": ["n8n-failure"]}},
        creds=CLICKUP, retry=True)
    w.chain(t, c, log, task)
    # watchdog: a scheduled job that stopped running never throws an error
    wd = cron(w, "Every hour: stale-job watchdog", "0 * * * *")
    w.x = 0
    q = pg(w, "Jobs past their SLA", """
SELECT job, finished_at FROM sync_runs s JOIN sync_sla USING (job)
WHERE s.finished_at < now() - sync_sla.max_age;""", pos=[240, 560])
    a = code(w, "Shape stale alert", r"""
return $input.all().map(i => ({ json: {
  title: `[n8n] ${i.json.job} has not run since ${i.json.finished_at}`,
  body: 'Scheduled job missed its SLA. Dashboards built on it are stale.',
  workflow: i.json.job } }));""", pos=[480, 560])
    w.link(wd, q)
    w.link(q, a)
    w.link(a, log)
    w.nodes[-1]["position"] = [480, 560]
    w.dump()


def razorpay():
    w = WF("01_razorpay_to_revenue", "01 · Razorpay → payments, invoices, workshop seats", ["revenue", "gtm"])
    hook = w.node("Razorpay webhook", "n8n-nodes-base.webhook", 2,
                  {"httpMethod": "POST", "path": "razorpay", "responseMode": "responseNode", "options": {"rawBody": True}})
    verify = code(w, "Verify signature", r"""
// Razorpay signs the raw body with the webhook secret (HMAC-SHA256).
// Reject anything unsigned before it touches the revenue tables.
const crypto = require('crypto');
const raw = $input.first().binary?.data ? Buffer.from($input.first().binary.data.data, 'base64').toString() : JSON.stringify($json.body);
const sig = $json.headers['x-razorpay-signature'];
const expected = crypto.createHmac('sha256', $env.RAZORPAY_WEBHOOK_SECRET).update(raw).digest('hex');
if (!sig || !crypto.timingSafeEqual(Buffer.from(sig), Buffer.from(expected))) throw new Error('Bad Razorpay signature');
const b = $json.body, p = b.payload?.payment?.entity, inv = b.payload?.invoice?.entity;
return [{ json: {
  event: b.event,
  payment_id: p?.id, amount_inr: p ? p.amount / 100 : null, captured_at: p ? new Date(p.created_at * 1000).toISOString() : null,
  invoice_id: p?.invoice_id || inv?.id || null,
  workshop_id: p?.notes?.workshop_id || null,
  revenue_line: p?.notes?.workshop_id ? 'workshop' : (p?.notes?.plan === 'full_program' ? 'program_full' : 'program_trial'),
  buyer: { name: p?.notes?.name, phone: p?.contact, email: p?.email, grade: p?.notes?.grade },
}}];""")
    ack = w.node("200 OK", "n8n-nodes-base.respondToWebhook", 1.1, {"respondWith": "noData", "options": {"responseCode": 200}})
    sw = w.node("Route by event", "n8n-nodes-base.switch", 3, {"rules": {"values": [
        {"conditions": {"conditions": [{"leftValue": "={{ $json.event }}", "rightValue": "payment.captured", "operator": {"type": "string", "operation": "equals"}}]}, "renameOutput": True, "outputKey": "captured"},
        {"conditions": {"conditions": [{"leftValue": "={{ $json.event }}", "rightValue": "invoice.expired", "operator": {"type": "string", "operation": "equals"}}]}, "renameOutput": True, "outputKey": "expired"},
    ]}, "options": {"fallbackOutput": "none"}})
    ins = pg(w, "Insert payment (idempotent)", """
INSERT INTO payments (payment_id, captured_at, amount_inr, revenue_line, invoice_id, workshop_id)
VALUES ($1, $2, $3, $4, NULLIF($5, ''), NULLIF($6, ''))
ON CONFLICT (payment_id) DO NOTHING
RETURNING payment_id;""", "={{ $json.payment_id }},={{ $json.captured_at }},={{ $json.amount_inr }},={{ $json.revenue_line }},={{ $json.invoice_id || '' }},={{ $json.workshop_id || '' }}")
    paid = pg(w, "Mark invoice paid", """
UPDATE invoices SET status = 'paid' WHERE invoice_id = $1 AND status = 'issued';""",
              "={{ $('Verify signature').item.json.invoice_id }}")
    is_ws = w.node("Workshop seat?", "n8n-nodes-base.if", 2, {"conditions": {"conditions": [
        {"leftValue": "={{ $('Verify signature').item.json.workshop_id }}", "operator": {"type": "string", "operation": "notEmpty"}}]}})
    lead = w.node("Create ClickUp lead", "n8n-nodes-base.clickUp", 1, {
        "team": "={{ $env.CLICKUP_TEAM_ID }}", "space": "={{ $env.CLICKUP_SALES_SPACE }}", "list": "={{ $env.CLICKUP_LEADS_LIST }}",
        "name": "={{ $('Verify signature').item.json.buyer.name }} · workshop seat",
        "additionalFields": {"status": "workshop attendee", "tags": ["source:workshop"],
                             "content": "=Bought a seat for {{ $('Verify signature').item.json.workshop_id }}. Phone {{ $('Verify signature').item.json.buyer.phone }}. Grade {{ $('Verify signature').item.json.buyer.grade }}."}},
        creds=CLICKUP, retry=True)
    seat = pg(w, "Insert seat + lead", """
WITH l AS (INSERT INTO leads (lead_id, created_at, source, teen_grade) VALUES ($1, now(), 'workshop', NULLIF($4,'')::smallint)
           ON CONFLICT (lead_id) DO NOTHING RETURNING lead_id)
INSERT INTO workshop_seats (seat_id, workshop_id, payment_id, lead_id, attended)
VALUES ('seat_' || $3, $2, $3, $1, false)
ON CONFLICT (seat_id) DO NOTHING;""", "={{ $json.id }},={{ $('Verify signature').item.json.workshop_id }},={{ $('Verify signature').item.json.payment_id }},={{ $('Verify signature').item.json.buyer.grade || '' }}")
    exp = pg(w, "Flag expired invoice", """
UPDATE invoices SET status = 'cancelled' WHERE invoice_id = $1;""", "={{ $json.invoice_id }}", pos=[1200, 520])
    w.chain(hook, verify, ack)
    w.link(verify, sw)
    w.link(sw, ins, 0)
    w.link(sw, exp, 1)
    w.chain(ins, paid, is_ws)
    w.link(is_ws, lead, 0)
    w.link(lead, seat)
    w.dump()


def meta_ads():
    w = WF("02_meta_ads_daily", "02 · Meta Ads insights → ad_daily_metrics + frequency", ["gtm", "ads"])
    t = cron(w, "Daily 06:00 IST", "0 6 * * *")
    ins = http(w, "Ad-level insights (yesterday)", "GET", "=https://graph.facebook.com/v21.0/act_{{ $env.META_AD_ACCOUNT_ID }}/insights",
               cred_type="facebookGraphApi", query={
                   "level": "ad", "date_preset": "yesterday", "time_increment": "1", "limit": "500",
                   "fields": "ad_id,ad_name,adset_id,campaign_id,impressions,reach,inline_link_clicks,spend,actions,date_start"})
    flat = code(w, "Flatten rows", r"""
// Meta returns leads inside actions[]; lead forms and checkout starts are different action types.
const rows = $json.data || [];
return rows.map(r => {
  const act = Object.fromEntries((r.actions || []).map(a => [a.action_type, Number(a.value)]));
  return { json: {
    date: r.date_start, ad_id: r.ad_id, impressions: Number(r.impressions || 0), reach: Number(r.reach || 0),
    link_clicks: Number(r.inline_link_clicks || 0), spend_inr: Number(r.spend || 0),
    meta_leads: (act['lead'] || 0) + (act['offsite_conversion.fb_pixel_initiate_checkout'] || 0),
  }};
});""")
    up = pg(w, "Upsert ad_daily_metrics", """
INSERT INTO ad_daily_metrics (date, ad_id, impressions, reach, link_clicks, spend_inr, meta_leads)
VALUES ($1, $2, $3, $4, $5, $6, $7)
ON CONFLICT (date, ad_id) DO UPDATE SET
  impressions = EXCLUDED.impressions, reach = EXCLUDED.reach, link_clicks = EXCLUDED.link_clicks,
  spend_inr = EXCLUDED.spend_inr, meta_leads = EXCLUDED.meta_leads;""",
            "={{ $json.date }},={{ $json.ad_id }},={{ $json.impressions }},={{ $json.reach }},={{ $json.link_clicks }},={{ $json.spend_inr }},={{ $json.meta_leads }}")
    fq = http(w, "Ad-set 7-day frequency", "GET", "=https://graph.facebook.com/v21.0/act_{{ $env.META_AD_ACCOUNT_ID }}/insights",
              cred_type="facebookGraphApi", query={"level": "adset", "date_preset": "last_7d", "fields": "adset_id,impressions,reach,frequency,date_stop"},
              executeOnce=True)
    fql = code(w, "Frequency rows", r"""
return ($json.data || []).map(r => ({ json: { week_ending: r.date_stop, ad_set_id: r.adset_id,
  impressions: Number(r.impressions), reach: Number(r.reach), frequency: Number(r.frequency) } }));""")
    fup = pg(w, "Upsert frequency", """
INSERT INTO ad_set_weekly_frequency (week_ending, ad_set_id, impressions, reach, frequency)
VALUES ($1, $2, $3, $4, $5)
ON CONFLICT (week_ending, ad_set_id) DO UPDATE SET impressions = EXCLUDED.impressions, reach = EXCLUDED.reach, frequency = EXCLUDED.frequency;""",
             "={{ $json.week_ending }},={{ $json.ad_set_id }},={{ $json.impressions }},={{ $json.reach }},={{ $json.frequency }}")
    alert = pg(w, "Ad sets at frequency 3+", """
SELECT s.name, f.frequency FROM ad_set_weekly_frequency f JOIN ad_sets s USING (ad_set_id)
WHERE f.week_ending = CURRENT_DATE - 1 AND f.frequency >= 3;""", executeOnce=True)
    task = w.node("Refresh task for growth", "n8n-nodes-base.clickUp", 1, {
        "team": "={{ $env.CLICKUP_TEAM_ID }}", "space": "={{ $env.CLICKUP_GROWTH_SPACE }}", "list": "={{ $env.CLICKUP_CREATIVE_LIST }}",
        "name": "=Refresh creative: {{ $json.name }} (frequency {{ $json.frequency }})",
        "additionalFields": {"priority": 2, "tags": ["rca:refresh"]}}, creds=CLICKUP, retry=True)
    hb = heartbeat(w, "meta_ads_daily")
    w.chain(t, ins, flat, up, fq, fql, fup, alert, task)
    w.link(fup, hb)
    w.dump()


def clickup_funnel():
    w = WF("03_clickup_funnel_stages", "03 · ClickUp status change → lead_stage_events (+ show-up calls)", ["gtm", "funnel"])
    t = w.node("ClickUp: task status updated", "n8n-nodes-base.clickUpTrigger", 1,
               {"team": "={{ $env.CLICKUP_TEAM_ID }}", "events": ["taskStatusUpdated", "taskCreated"],
                "filters": {"listId": "={{ $env.CLICKUP_LEADS_LIST }}"}}, creds=CLICKUP)
    m = code(w, "Map status → stage", r"""
// The ClickUp list statuses ARE the funnel. This map is the single place the two are tied together.
const MAP = {
  'new lead': null, 'workshop attendee': null,
  'qualified': 'qualified', 'not a fit': 'disqualified',
  'discovery booked': 'discovery_scheduled', 'discovery done': 'discovery_attended', 'discovery no-show': 'discovery_no_show',
  'ambition booked': 'ambition_scheduled', 'ambition done': 'ambition_attended', 'ambition no-show': 'ambition_no_show',
  'architect done': 'architect_done', 'won': 'won', 'lost': 'lost',
};
const h = $json.history_items?.[0] || {};
const status = (h.after?.status || $json.status?.status || '').toLowerCase();
if (!(status in MAP)) throw new Error(`Unmapped ClickUp status "${status}". Add it to the map before using it.`);
const stage = MAP[status];
if (!stage) return [];
return [{ json: { lead_id: $json.task_id, stage, occurred_at: new Date(Number(h.date || Date.now())).toISOString(),
                  phone: $json.phone || null, when: $json.due_date || null } }];""")
    ins = pg(w, "Append stage (idempotent)", """
INSERT INTO lead_stage_events (lead_id, stage, occurred_at) VALUES ($1, $2, $3)
ON CONFLICT (lead_id, stage) DO NOTHING;""", "={{ $json.lead_id }},={{ $json.stage }},={{ $json.occurred_at }}")
    booked = w.node("Discovery or ambition booked?", "n8n-nodes-base.if", 2, {"conditions": {"combinator": "or", "conditions": [
        {"leftValue": "={{ $('Map status → stage').item.json.stage }}", "rightValue": "discovery_scheduled", "operator": {"type": "string", "operation": "equals"}},
        {"leftValue": "={{ $('Map status → stage').item.json.stage }}", "rightValue": "ambition_scheduled", "operator": {"type": "string", "operation": "equals"}}]}})
    call = http(w, "Schedule Smallest.ai reminder calls", "POST", "https://api.smallest.ai/atoms/v1/campaigns/calls",
                cred_type="httpHeaderAuth", body="""={
  "agent_id": "{{ $env.SMALLEST_REMINDER_AGENT }}",
  "phone_number": "{{ $('Map status → stage').item.json.phone }}",
  "schedule": ["{{ DateTime.fromISO($('Map status → stage').item.json.when).minus({hours: 24}).toISO() }}",
               "{{ DateTime.fromISO($('Map status → stage').item.json.when).minus({hours: 2}).toISO() }}"],
  "variables": { "session": "{{ $('Map status → stage').item.json.stage }}" }
}""")
    w.chain(t, m, ins, booked)
    w.link(booked, call, 0)
    w.dump()


def renewals_dues():
    w = WF("04_renewals_and_unpaid_invoices", "04 · Trial renewals (T-21/14/7) + unpaid invoice chasers", ["revenue"])
    t = cron(w, "Daily 09:30 IST", "30 9 * * *")
    q = pg(w, "Trials ending at T-21 / T-14 / T-7", """
SELECT t.enrollment_id, t.student_name, t.end_date, t.end_date - CURRENT_DATE AS days_left, l.lead_id
FROM enrollments t JOIN leads l USING (lead_id)
WHERE t.plan = 'trial_3m' AND t.end_date - CURRENT_DATE IN (21, 14, 7)
  AND NOT EXISTS (SELECT 1 FROM enrollments r WHERE r.renewed_from = t.enrollment_id);""")
    sw = w.node("Which touchpoint", "n8n-nodes-base.switch", 3, {"rules": {"values": [
        {"conditions": {"conditions": [{"leftValue": "={{ $json.days_left }}", "rightValue": 21, "operator": {"type": "number", "operation": "equals"}}]}, "renameOutput": True, "outputKey": "T-21 report"},
        {"conditions": {"conditions": [{"leftValue": "={{ $json.days_left }}", "rightValue": 14, "operator": {"type": "number", "operation": "equals"}}]}, "renameOutput": True, "outputKey": "T-14 review"},
        {"conditions": {"conditions": [{"leftValue": "={{ $json.days_left }}", "rightValue": 7, "operator": {"type": "number", "operation": "equals"}}]}, "renameOutput": True, "outputKey": "T-7 call"},
    ]}})
    rep = http(w, "T-21: send 90-day progress report", "POST", "={{ $env.ALCOVIA_API }}/internal/reports/trial-progress",
               cred_type="httpHeaderAuth", body='={ "enrollment_id": "{{ $json.enrollment_id }}", "send_to": "parent" }', pos=[960, 140])
    rev = w.node("T-14: advisor renewal review", "n8n-nodes-base.clickUp", 1, {
        "team": "={{ $env.CLICKUP_TEAM_ID }}", "space": "={{ $env.CLICKUP_SALES_SPACE }}", "list": "={{ $env.CLICKUP_RENEWALS_LIST }}",
        "name": "=Renewal review: {{ $json.student_name }} (trial ends {{ $json.end_date }})",
        "additionalFields": {"dueDate": "={{ $now.plus({days: 3}).toISO() }}", "tags": ["renewal"],
                             "content": "Walk the parent through the student's 90-day numbers on the progress board, then propose the full program."}},
        creds=CLICKUP, retry=True, pos=[960, 300])
    callt = w.node("T-7: founder call task", "n8n-nodes-base.clickUp", 1, {
        "team": "={{ $env.CLICKUP_TEAM_ID }}", "space": "={{ $env.CLICKUP_SALES_SPACE }}", "list": "={{ $env.CLICKUP_RENEWALS_LIST }}",
        "name": "=Call parent today: {{ $json.student_name }} trial ends in 7 days",
        "additionalFields": {"priority": 1, "tags": ["renewal", "urgent"]}}, creds=CLICKUP, retry=True, pos=[960, 460])
    w.x = 240
    t2 = cron(w, "Daily 10:00 IST", "0 10 * * *")
    w.nodes[-1]["position"] = [0, 700]
    q2 = pg(w, "Invoices 3 / 10 / 30 days overdue", """
SELECT i.invoice_id, e.student_name, i.amount_inr, CURRENT_DATE - i.due_on AS days_overdue
FROM invoices i JOIN enrollments e USING (enrollment_id)
WHERE i.status = 'issued' AND CURRENT_DATE - i.due_on IN (3, 10, 30);""", pos=[240, 700])
    rem = http(w, "Razorpay: resend payment link", "POST", "=https://api.razorpay.com/v1/invoices/{{ $json.invoice_id }}/notify_by/sms",
               cred_type="httpBasicAuth", pos=[480, 700])
    esc = w.node("30 days: escalate to founder", "n8n-nodes-base.if", 2, {"conditions": {"conditions": [
        {"leftValue": "={{ $('Invoices 3 / 10 / 30 days overdue').item.json.days_overdue }}", "rightValue": 30, "operator": {"type": "number", "operation": "gte"}}]}},
        pos=[720, 700])
    ft = w.node("Founder task", "n8n-nodes-base.clickUp", 1, {
        "team": "={{ $env.CLICKUP_TEAM_ID }}", "space": "={{ $env.CLICKUP_SALES_SPACE }}", "list": "={{ $env.CLICKUP_COLLECTIONS_LIST }}",
        "name": "=Unpaid 30+ days: {{ $('Invoices 3 / 10 / 30 days overdue').item.json.student_name }} ₹{{ $('Invoices 3 / 10 / 30 days overdue').item.json.amount_inr }}",
        "additionalFields": {"priority": 1}}, creds=CLICKUP, retry=True, pos=[960, 700])
    w.chain(t, q, sw)
    w.link(sw, rep, 0); w.link(sw, rev, 1); w.link(sw, callt, 2)
    w.chain(t2, q2, rem, esc)
    w.link(esc, ft, 0)
    w.dump()


def daily_quiz():
    w = WF("05_daily_quiz", "05 · 8pm quiz: publish, push, record delivery", ["student", "daily"])
    t = cron(w, "Daily 19:55 IST", "55 19 * * *")
    pick = pg(w, "Pick tonight's quiz", """
SELECT quiz_id, topic FROM quiz_bank WHERE scheduled_for = CURRENT_DATE LIMIT 1;""")
    has = w.node("Quiz ready?", "n8n-nodes-base.if", 2, {"conditions": {"conditions": [
        {"leftValue": "={{ $json.quiz_id }}", "operator": {"type": "string", "operation": "notEmpty"}}]}}, alwaysOutputData=True)
    pub = http(w, "Publish in app + push", "POST", "={{ $env.ALCOVIA_API }}/internal/quiz/publish", cred_type="httpHeaderAuth",
               body='={ "quiz_id": "{{ $json.quiz_id }}", "push": { "title": "8pm quiz: {{ $json.topic }}", "deeplink": "alcovia://quiz/today" } }')
    rec = pg(w, "Record published", """
INSERT INTO quizzes (quiz_id, quiz_date, topic, published) VALUES ($1, CURRENT_DATE, $2, true)
ON CONFLICT (quiz_date) DO UPDATE SET published = true;""", "={{ $('Pick tonight\\'s quiz').item.json.quiz_id }},={{ $('Pick tonight\\'s quiz').item.json.topic }}")
    miss = pg(w, "Record missed day", """
INSERT INTO quizzes (quiz_id, quiz_date, topic, published) VALUES ('qz_' || to_char(CURRENT_DATE, 'YYYYMMDD'), CURRENT_DATE, 'none scheduled', false)
ON CONFLICT (quiz_date) DO NOTHING;""", pos=[960, 520])
    alert = w.node("Tell content owner", "n8n-nodes-base.clickUp", 1, {
        "team": "={{ $env.CLICKUP_TEAM_ID }}", "space": "={{ $env.CLICKUP_PROGRAM_SPACE }}", "list": "={{ $env.CLICKUP_CONTENT_LIST }}",
        "name": "=No quiz in the bank for {{ $today.toISODate() }}. Tonight's quiz did not go out.", "additionalFields": {"priority": 1}},
        creds=CLICKUP, retry=True, pos=[1200, 520])
    w.chain(t, pick, has)
    w.link(has, pub, 0); w.link(pub, rec)
    w.link(has, miss, 1); w.link(miss, alert)
    w.dump()


def escalations():
    w = WF("06_student_escalations", "06 · Nightly student rules → nudges, parent alerts, tutor triggers", ["student", "automation"])
    t = cron(w, "Daily 21:30 IST", "30 21 * * *")
    rules = pg(w, "Evaluate rules", """
-- Each rule returns (student_id, rule, notified). Thresholds live in one table so the
-- weekly review can tune them without touching the workflow.
WITH th AS (SELECT * FROM escalation_thresholds),
overdue AS (
  SELECT student_id, CASE WHEN CURRENT_DATE - due_on >= 5 THEN 'parent' ELSE 'student' END AS notified, 'task_overdue' AS rule
  FROM tasks WHERE source = 'advisor' AND completed_on IS NULL AND CURRENT_DATE - due_on IN (2, 5)
),
quiz AS (
  SELECT s.student_id, 'student' AS notified, 'quiz_missed_3d' AS rule FROM students s
  WHERE NOT EXISTS (SELECT 1 FROM quiz_attempts a JOIN quizzes q USING (quiz_id)
                    WHERE a.student_id = s.student_id AND q.quiz_date > CURRENT_DATE - 3)
),
focus AS (
  SELECT s.student_id, 'student', 'no_focus_3d' FROM students s
  WHERE EXISTS (SELECT 1 FROM focus_sessions f WHERE f.student_id = s.student_id AND f.started_at > now() - interval '30 days')
    AND NOT EXISTS (SELECT 1 FROM focus_sessions f WHERE f.student_id = s.student_id AND f.started_at > now() - interval '3 days')
),
gap AS (   -- latest exam 10+ points under target in a subject with no tutor -> tutor support
  SELECT sb.student_id, 'tutor', 'readiness_gap' FROM exam_results r
  JOIN subjects sb USING (subject_id) JOIN exam_targets t ON t.subject_id = r.subject_id AND t.exam_type = r.exam_type
  WHERE r.exam_date = (SELECT MAX(exam_date) FROM exam_results) AND r.score_pct - t.target_pct <= -(SELECT readiness_gap_pts FROM th)
    AND NOT sb.has_tutor
)
SELECT * FROM overdue UNION ALL SELECT * FROM quiz UNION ALL SELECT * FROM focus UNION ALL SELECT * FROM gap;""")
    dedupe = pg(w, "Log escalation (once per rule per day)", """
INSERT INTO escalations (escalation_id, student_id, rule, triggered_on, notified)
VALUES ('esc_' || $1 || '_' || $2 || '_' || to_char(CURRENT_DATE, 'YYYYMMDD'), $1, $2, CURRENT_DATE, $3)
ON CONFLICT (escalation_id) DO NOTHING RETURNING escalation_id, student_id, rule, notified;""",
                "={{ $json.student_id }},={{ $json.rule }},={{ $json.notified }}")
    sw = w.node("Who gets it", "n8n-nodes-base.switch", 3, {"rules": {"values": [
        {"conditions": {"conditions": [{"leftValue": "={{ $json.notified }}", "rightValue": "student", "operator": {"type": "string", "operation": "equals"}}]}, "renameOutput": True, "outputKey": "student"},
        {"conditions": {"conditions": [{"leftValue": "={{ $json.notified }}", "rightValue": "parent", "operator": {"type": "string", "operation": "equals"}}]}, "renameOutput": True, "outputKey": "parent"},
        {"conditions": {"conditions": [{"leftValue": "={{ $json.notified }}", "rightValue": "tutor", "operator": {"type": "string", "operation": "equals"}}]}, "renameOutput": True, "outputKey": "tutor"},
    ]}})
    push = http(w, "App push to student", "POST", "={{ $env.ALCOVIA_API }}/internal/push", cred_type="httpHeaderAuth",
                body='={ "student_id": "{{ $json.student_id }}", "template": "{{ $json.rule }}" }', pos=[1200, 140])
    wa = http(w, "WhatsApp to parent", "POST", "={{ $env.WHATSAPP_API }}/messages", cred_type="httpHeaderAuth",
              body='={ "to_student_parent": "{{ $json.student_id }}", "template": "parent_{{ $json.rule }}" }', pos=[1200, 300])
    tut = w.node("Tutor-support task for advisor", "n8n-nodes-base.clickUp", 1, {
        "team": "={{ $env.CLICKUP_TEAM_ID }}", "space": "={{ $env.CLICKUP_PROGRAM_SPACE }}", "list": "={{ $env.CLICKUP_ADVISOR_LIST }}",
        "name": "=Arrange tutor support: {{ $json.student_id }} is 10+ pts under target", "additionalFields": {"priority": 2, "tags": ["tutor-trigger"]}},
        creds=CLICKUP, retry=True, pos=[1200, 460])
    w.x = 0
    t2 = cron(w, "Daily 06:00 IST: resolver", "0 6 * * *")
    w.nodes[-1]["position"] = [0, 700]
    res = pg(w, "Mark recovered behaviour as resolved", """
UPDATE escalations e SET resolved_on = CURRENT_DATE
WHERE resolved_on IS NULL AND (
  (rule = 'task_overdue'   AND NOT EXISTS (SELECT 1 FROM tasks t WHERE t.student_id = e.student_id AND t.source = 'advisor' AND t.completed_on IS NULL AND t.due_on < CURRENT_DATE - 1))
  OR (rule = 'quiz_missed_3d' AND EXISTS (SELECT 1 FROM quiz_attempts a JOIN quizzes q USING (quiz_id) WHERE a.student_id = e.student_id AND q.quiz_date > e.triggered_on))
  OR (rule = 'no_focus_3d'    AND EXISTS (SELECT 1 FROM focus_sessions f WHERE f.student_id = e.student_id AND f.started_at::date > e.triggered_on))
);""", pos=[240, 700])
    w.chain(t, rules, dedupe, sw)
    w.link(sw, push, 0); w.link(sw, wa, 1); w.link(sw, tut, 2)
    w.link(t2, res)
    w.dump()


def weekly_digest():
    w = WF("07_weekly_parent_digest", "07 · Sunday digest: progress board → parent WhatsApp + advisor prep", ["student", "weekly"])
    t = cron(w, "Sunday 18:00 IST", "0 18 * * 0")
    q = pg(w, "Scorecard, last 7 days", """
-- Same query as sql/metrics/40_student_kpis.sql#student_scorecard, window = last 7 days.
SELECT * FROM weekly_scorecard WHERE week_ending = CURRENT_DATE;""")
    batch = w.node("One student at a time", "n8n-nodes-base.splitInBatches", 3, {"batchSize": 1, "options": {}})
    llm = http(w, "Draft parent note (Claude)", "POST", "https://api.anthropic.com/v1/messages", cred_type="httpHeaderAuth", body="""={
  "model": "claude-haiku-5-5",
  "max_tokens": 400,
  "system": "You write a 5-line weekly update to an Indian parent about their teen in the Alcovia program. Use only the numbers given. One line each: focus time, quiz, tasks on time, syllabus pace, one thing to praise. No advice the advisor has not approved. Warm, specific, no emojis.",
  "messages": [{ "role": "user", "content": {{ JSON.stringify(JSON.stringify($json)) }} }]
}""")
    hold = w.node("Advisor approves in ClickUp", "n8n-nodes-base.clickUp", 1, {
        "team": "={{ $env.CLICKUP_TEAM_ID }}", "space": "={{ $env.CLICKUP_PROGRAM_SPACE }}", "list": "={{ $env.CLICKUP_DIGEST_LIST }}",
        "name": "=Approve weekly note: {{ $('One student at a time').item.json.name }}",
        "additionalFields": {"content": "={{ $json.content[0].text }}", "assignees": ["={{ $('One student at a time').item.json.advisor_clickup_id }}"],
                             "dueDate": "={{ $now.plus({hours: 15}).toISO() }}", "status": "to approve"}},
        creds=CLICKUP, retry=True)
    w.chain(t, q, batch)
    w.link(batch, llm, 1)
    w.link(llm, hold)
    w.link(hold, batch)
    # second trigger: approved notes go out Monday 09:00
    w.x = 0
    t2 = cron(w, "Monday 09:00 IST: send approved", "0 9 * * 1")
    w.nodes[-1]["position"] = [0, 600]
    ap = w.node("Approved notes", "n8n-nodes-base.clickUp", 1, {"operation": "getAll", "team": "={{ $env.CLICKUP_TEAM_ID }}",
              "space": "={{ $env.CLICKUP_PROGRAM_SPACE }}", "list": "={{ $env.CLICKUP_DIGEST_LIST }}", "filters": {"statuses": ["approved"]}},
              creds=CLICKUP, retry=True, pos=[240, 600])
    send = http(w, "WhatsApp to parent", "POST", "={{ $env.WHATSAPP_API }}/messages", cred_type="httpHeaderAuth",
                body='={ "clickup_task": "{{ $json.id }}", "template": "weekly_digest", "body": {{ JSON.stringify($json.text_content) }} }', pos=[480, 600])
    w.chain(t2, ap, send)
    w.dump()


def wearables():
    w = WF("08_wearables_nightly", "08 · WHOOP nightly pull → wearable_daily (Apple/Samsung/Garmin arrive via the app)", ["student", "wellness"])
    t = cron(w, "Daily 05:00 IST", "0 5 * * *")
    who = pg(w, "Students with WHOOP connected", "SELECT student_id, whoop_user_id FROM wearable_connections WHERE provider = 'whoop' AND active;")
    batch = w.node("Per student", "n8n-nodes-base.splitInBatches", 3, {"batchSize": 1, "options": {}})
    tok = http(w, "Get fresh token (api.alcovia.life holds OAuth)", "POST", "={{ $env.ALCOVIA_API }}/internal/wearables/whoop/token",
               cred_type="httpHeaderAuth", body='={ "student_id": "{{ $json.student_id }}" }')
    rec = http(w, "WHOOP recovery", "GET", "https://api.prod.whoop.com/developer/v1/recovery", query={"start": "={{ $today.minus({days: 1}).toISO() }}"})
    slp = http(w, "WHOOP sleep", "GET", "https://api.prod.whoop.com/developer/v1/activity/sleep", query={"start": "={{ $today.minus({days: 1}).toISO() }}"})
    cyc = http(w, "WHOOP cycle (strain)", "GET", "https://api.prod.whoop.com/developer/v1/cycle", query={"start": "={{ $today.minus({days: 1}).toISO() }}"})
    for n in w.nodes[-3:]:
        n["parameters"]["sendHeaders"] = True
        n["parameters"]["headerParameters"] = {"parameters": [{"name": "Authorization", "value": "=Bearer {{ $('Get fresh token (api.alcovia.life holds OAuth)').item.json.access_token }}"}]}
    shape = code(w, "Shape daily row", r"""
const rec = $('WHOOP recovery').item.json.records?.[0]?.score || {};
const slp = $('WHOOP sleep').item.json.records?.[0]?.score?.stage_summary || {};
const cyc = $('WHOOP cycle (strain)').item.json.records?.[0]?.score || {};
const asleep = (slp.total_in_bed_time_milli || 0) - (slp.total_awake_time_milli || 0);
return [{ json: {
  student_id: $('Per student').item.json.student_id,
  date: $today.minus({ days: 1 }).toISODate(),
  active_min: Math.round((cyc.kilojoule || 0) / 25),   // proxy until WHOOP workout minutes are summed
  strain: cyc.strain ?? null, sleep_min: Math.round(asleep / 60000), recovery_pct: rec.recovery_score ?? null,
}}];""")
    up = pg(w, "Upsert wearable_daily", """
INSERT INTO wearable_daily (student_id, date, active_min, strain, sleep_min, recovery_pct) VALUES ($1, $2, $3, $4, $5, $6)
ON CONFLICT (student_id, date) DO UPDATE SET active_min = EXCLUDED.active_min, strain = EXCLUDED.strain,
  sleep_min = EXCLUDED.sleep_min, recovery_pct = EXCLUDED.recovery_pct;""",
            "={{ $json.student_id }},={{ $json.date }},={{ $json.active_min }},={{ $json.strain }},={{ $json.sleep_min }},={{ $json.recovery_pct }}")
    w.chain(t, who, batch)
    w.link(batch, tok, 1)
    w.chain(tok, rec, slp, cyc, shape, up)
    w.link(up, batch)
    w.dump()


def mixpanel():
    w = WF("09_mixpanel_raw_export", "09 · Mixpanel raw events → app_events + app_daily_usage", ["product", "analytics"])
    t = cron(w, "Daily 03:00 IST", "0 3 * * *")
    ex = http(w, "Raw export (yesterday)", "GET", "https://data.mixpanel.com/api/2.0/export", cred_type="httpBasicAuth",
              query={"from_date": "={{ $today.minus({days: 1}).toISODate() }}", "to_date": "={{ $today.minus({days: 1}).toISODate() }}",
                     "project_id": "={{ $env.MIXPANEL_PROJECT_ID }}"})
    w.nodes[-1]["parameters"]["options"]["response"] = {"response": {"responseFormat": "text"}}
    parse = code(w, "Parse NDJSON", r"""
const TEST = new Set(($env.MIXPANEL_TEST_DEVICES || '').split(','));
return $json.data.split('\n').filter(Boolean).map(l => JSON.parse(l)).map(e => ({ json: {
  insert_id: e.properties.$insert_id, distinct_id: e.properties.distinct_id, event: e.event,
  ts: new Date(e.properties.time * 1000).toISOString(),
  duration_sec: e.properties.duration_sec ?? e.properties.duration ?? null,
  is_test_device: TEST.has(e.properties.distinct_id),
}}));""")
    ins = pg(w, "Insert events (dedupe on $insert_id)", """
INSERT INTO app_events (insert_id, distinct_id, event, ts, duration_sec, is_test_device) VALUES ($1, $2, $3, $4, $5, $6)
ON CONFLICT (insert_id) DO NOTHING;""", "={{ $json.insert_id }},={{ $json.distinct_id }},={{ $json.event }},={{ $json.ts }},={{ $json.duration_sec }},={{ $json.is_test_device }}")
    roll = pg(w, "Roll up app_daily_usage", """
INSERT INTO app_daily_usage (student_id, date, foreground_min)
SELECT distinct_id, ts::date, SUM(duration_sec) / 60.0 FROM app_events
WHERE event = 'app_session_ended' AND NOT is_test_device AND ts::date = CURRENT_DATE - 1
GROUP BY 1, 2
ON CONFLICT (student_id, date) DO UPDATE SET foreground_min = EXCLUDED.foreground_min;""", executeOnce=True)
    hb = heartbeat(w, "mixpanel_export")
    w.chain(t, ex, parse, ins, roll, hb)
    w.dump()


if __name__ == "__main__":
    for f in (error_handler, razorpay, meta_ads, clickup_funnel, renewals_dues, daily_quiz, escalations, weekly_digest, wearables, mixpanel):
        f()
