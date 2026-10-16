/* GTM tracker - every number recomputed from raw rows for the selected range.
   The logic mirrors sql/metrics/10-30_*.sql so the dashboard and the SQL agree. */
(function () {
  const A = window.Alc, D = window.GTM_DATA, AS_OF = D.as_of;
  const T = (n) => A.table(D, n);

  // ---------- load + index ----------
  const targets = {};
  for (const t of T("monthly_targets")) (targets[t.month] ||= {})[t.metric] = Number(t.target);
  const campaigns = Object.fromEntries(T("campaigns").map((c) => [c.campaign_id, c]));
  const adSets = Object.fromEntries(T("ad_sets").map((s) => [s.ad_set_id, { ...s, objective: campaigns[s.campaign_id].objective }]));
  const ads = Object.fromEntries(T("ads").map((a) => [a.ad_id, { ...a, objective: adSets[a.ad_set_id].objective }]));
  const adDaily = T("ad_daily_metrics");
  const freq = T("ad_set_weekly_frequency");
  const lps = Object.fromEntries(T("landing_pages").map((l) => [l.landing_page_id, l]));
  const lpDaily = T("landing_page_daily");
  const leads = T("leads").map((l) => ({ ...l, day: A.day(l.created_at) }));
  const stages = {};
  for (const e of T("lead_stage_events")) (stages[e.lead_id] ||= {})[e.stage] = e.occurred_at;
  const enrollments = T("enrollments");
  const invoices = T("invoices");
  const payments = T("payments").map((p) => ({ ...p, day: A.day(p.captured_at) }));
  const workshops = T("workshops");
  const seats = T("workshop_seats");
  const payByInvoice = Object.fromEntries(payments.filter((p) => p.invoice_id).map((p) => [p.invoice_id, p]));
  const enrById = Object.fromEntries(enrollments.map((e) => [e.enrollment_id, e]));
  const firstEnrByLead = {};
  for (const e of enrollments) if (!e.renewed_from) firstEnrByLead[e.lead_id] = e;
  const paidLead = new Set(invoices.filter((i) => i.status === "paid").map((i) => enrById[i.enrollment_id]).filter((e) => !e.renewed_from).map((e) => e.lead_id));
  const revenueByLead = {};
  for (const i of invoices) { const p = payByInvoice[i.invoice_id]; if (p) { const l = enrById[i.enrollment_id].lead_id; revenueByLead[l] = (revenueByLead[l] || 0) + Number(p.amount_inr); } }
  const isProgramLead = (l) => l.source !== "workshop" || !!stages[l.lead_id];
  const LINE = { program_full: "Full program", program_trial: "3-month trial", workshop: "Workshop" };

  let R = null, objective = "program";

  // ---------- revenue ----------
  function proratedTarget(metric, r) {
    let t = 0;
    for (const m of A.months(r)) {
      const me = A.monthEnd(m), days = A.diffDays(m, me) + 1;
      const s = r.start > m ? r.start : m, e = r.end < me ? r.end : me;
      t += ((targets[m] || {})[metric] || 0) * ((A.diffDays(s, e) + 1) / days);
    }
    return t;
  }

  function tiles() {
    const pay = payments.filter((p) => A.within(p.day, R));
    const rev = A.sum(pay, (p) => p.amount_inr);
    const tgt = proratedTarget("revenue_total", R);
    const onb = enrollments.filter((e) => !e.renewed_from && A.within(e.start_date, R)).length;
    const onbT = proratedTarget("students_onboarded", R);
    const cohort = leads.filter((l) => A.within(l.day, R) && isProgramLead(l));
    const q = cohort.filter((l) => stages[l.lead_id]?.qualified);
    const spend = A.sum(adDaily.filter((m) => A.within(m.date, R) && ads[m.ad_id].objective === "program"), (m) => m.spend_inr);
    const cpql = spend / Math.max(1, q.filter((l) => l.source === "meta_ads").length);
    const cpqlT = (targets[A.monthStart(R.end)] || {}).cpql_max || 2000;
    const unpaid = unpaidAsOf(R.end > AS_OF ? AS_OF : R.end);
    const host = document.getElementById("tiles");
    host.replaceChildren();
    const tile = (k, v, s, meter, status) => {
      const t = A.el("div", { class: "tile" });
      t.append(A.el("span", { class: "k" }, k));
      const vv = A.el("span", { class: "v" }, v); t.append(vv);
      const ss = A.el("span", { class: "s" }); if (status) { ss.append(status, document.createTextNode(" ")); } ss.append(document.createTextNode(s)); t.append(ss);
      if (meter != null) { const m = A.el("div", { class: "meter" }); const i = A.el("i"); i.style.width = Math.min(100, meter * 100) + "%"; if (meter < 0.9) i.style.background = "var(--serious)"; m.append(i); t.append(m); }
      host.append(t);
    };
    const ach = rev / (tgt || 1);
    tile("Revenue vs target", A.inr(rev), `${A.pct(ach)} of ${A.inr(tgt)}`, ach, A.pill(ach >= 1 ? "good" : ach >= 0.9 ? "warn" : "critical", ach >= 1 ? "ON TARGET" : ach >= 0.9 ? "CLOSE" : "BEHIND"));
    tile("Students onboarded", A.int(onb), `target ${A.int(onbT)}`, onb / (onbT || 1));
    tile("Cost per qualified lead", A.inr(cpql, true), `target ≤ ${A.inr(cpqlT, true)}`, null, A.pill(cpql <= cpqlT ? "good" : cpql <= cpqlT * 1.25 ? "warn" : "critical", cpql <= cpqlT ? "OK" : "HIGH"));
    const conv = cohort.filter((l) => paidLead.has(l.lead_id)).length / Math.max(1, cohort.length);
    tile("Lead → paid sign-up", A.pct(conv, 1), `${cohort.filter((l) => paidLead.has(l.lead_id)).length} of ${A.int(cohort.length)} leads in range`);
    tile("Unpaid invoices", A.inr(A.sum(unpaid, (u) => u.amount_inr)), `${unpaid.length} invoices · ${unpaid.filter((u) => u.overdue > 30).length} over 30 days`, null, unpaid.some((u) => u.overdue > 30) ? A.pill("critical", "CHASE") : null);
    const ren = renewalsFrom(R.end > AS_OF ? AS_OF : R.end);
    tile("Trial renewals, next 30 days", A.int(ren.length), `${A.inr(ren.length * 180000)} at stake`);
  }

  function revenueChart() {
    const months = A.months(R);
    const pay = payments.filter((p) => A.within(p.day, R));
    const legend = document.getElementById("rev-legend");
    legend.replaceChildren();
    const add = (cls, color, label) => { const s = A.el("span"); const i = A.el("i", { class: cls }); i.style.background = color; s.append(i, document.createTextNode(label)); legend.append(s); };
    if (months.length >= 2) {
      document.getElementById("rev-sub").textContent = "Monthly cash collected by revenue line, against the monthly target";
      add("", "var(--s1)", "Full program"); add("", "var(--s2)", "3-month trial"); add("", "var(--s3)", "Workshop"); add("line", "var(--target)", "Target (pro-rated)");
      const by = (line, m) => A.sum(pay.filter((p) => p.revenue_line === line && A.monthStart(p.day) === m), (p) => p.amount_inr);
      const ds = ["program_full", "program_trial", "workshop"].map((line, i) => ({
        type: "bar", label: LINE[line], data: months.map((m) => by(line, m)), backgroundColor: A.color(["--s1", "--s2", "--s3"][i]),
        stack: "rev", ...A.barStyle, borderRadius: 0, borderColor: A.color("--surface"), borderWidth: { top: 2 },
      }));
      const tg = months.map((m) => { const me = A.monthEnd(m); return proratedTarget("revenue_total", { start: R.start > m ? R.start : m, end: R.end < me ? R.end : me }); });
      ds.push({ type: "line", label: "Target", data: tg, borderColor: A.color("--target"), backgroundColor: A.color("--target"), borderWidth: 2, pointRadius: 4, pointStyle: "line", stepped: "middle", showLine: false, pointHoverRadius: 6 });
      ds[2].borderRadius = { topLeft: 4, topRight: 4 };
      A.chart("c-rev", { data: { labels: months.map(A.monthLabel), datasets: ds }, options: {
        scales: { x: { stacked: true }, y: { stacked: true, ticks: { callback: (v) => A.inr(v) } } },
        plugins: { tooltip: { callbacks: { label: (c) => ` ${c.dataset.label}: ${A.inr(c.parsed.y, true)}`, footer: (items) => `Total: ${A.inr(A.sum(items.filter((i) => i.dataset.type === "bar"), (i) => i.parsed.y), true)}` } } },
      } });
    } else {
      document.getElementById("rev-sub").textContent = "Cumulative cash collected vs the target pace for the month";
      add("line", "var(--s1)", "Actual, cumulative"); add("line", "var(--target)", "Target pace");
      const days = []; for (let d = R.start; d <= R.end; d = A.addDays(d, 1)) days.push(d);
      let run = 0; const act = [], tgt = [];
      for (const d of days) {
        run += A.sum(pay.filter((p) => p.day === d), (p) => p.amount_inr);
        act.push(d <= AS_OF ? run : null);
        tgt.push(proratedTarget("revenue_total", { start: R.start, end: d }));
      }
      A.chart("c-rev", { type: "line", data: { labels: days.map(A.dateLabel), datasets: [
        { label: "Actual", data: act, borderColor: A.color("--s1"), backgroundColor: A.color("--s1") + "22", fill: true, borderWidth: 2, pointRadius: 0, tension: 0.2 },
        { label: "Target pace", data: tgt, borderColor: A.color("--target"), borderWidth: 1.5, pointRadius: 0 },
      ] }, options: { scales: { y: { ticks: { callback: (v) => A.inr(v) } }, x: { ticks: { maxTicksLimit: 8 } } },
        plugins: { tooltip: { callbacks: { label: (c) => ` ${c.dataset.label}: ${A.inr(c.parsed.y, true)}` } } } } });
    }
  }

  function revenueMix() {
    const pay = payments.filter((p) => A.within(p.day, R));
    const total = A.sum(pay, (p) => p.amount_inr) || 1;
    const host = document.getElementById("mix");
    host.replaceChildren();
    const bar = A.el("div"); bar.style.cssText = "display:flex;height:14px;border-radius:4px;overflow:hidden;gap:2px;margin:6px 0 14px";
    const rows = [["program_full", "--s1"], ["program_trial", "--s2"], ["workshop", "--s3"]].map(([line, c]) => {
      const v = A.sum(pay.filter((p) => p.revenue_line === line), (p) => p.amount_inr);
      const seg = A.el("i"); seg.style.cssText = `flex:${v} 0 0;background:var(${c})`; seg.title = `${LINE[line]}: ${A.inr(v, true)}`; bar.append(seg);
      return { line, c, v, n: pay.filter((p) => p.revenue_line === line).length };
    });
    host.append(bar);
    const tbl = A.el("table"); const tb = A.el("tbody");
    for (const r of rows) {
      const tr = A.el("tr"); const k = A.el("td"); const sw = A.el("i"); sw.style.cssText = `display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:8px;background:var(${r.c})`;
      k.append(sw, document.createTextNode(LINE[r.line]));
      tr.append(k, A.el("td", { class: "n" }, A.inr(r.v)), A.el("td", { class: "n muted" }, A.pct(r.v / total)), A.el("td", { class: "n muted" }, `${r.n} pmts`));
      tb.append(tr);
    }
    const prog = rows[0].v + rows[1].v;
    const tr = A.el("tr"); tr.append(A.el("td", {}, "Program : workshop"), A.el("td", { class: "n" }, `${A.dec(prog / Math.max(1, rows[2].v), 1)} : 1`), A.el("td"), A.el("td"));
    tb.append(tr); tbl.append(tb); host.append(tbl);
    const wsT = proratedTarget("revenue_workshop", R), prT = proratedTarget("revenue_program", R);
    host.append(A.el("p", { class: "note" }, `Program ${A.pct(prog / (prT || 1))} of target · Workshop ${A.pct(rows[2].v / (wsT || 1))} of target`));
  }

  function onboarding() {
    const r = R.start > A.addDays(R.end, -150) ? { start: A.monthStart(A.addDays(R.end, -150)), end: R.end } : R;  // always show trend context
    const months = A.months(r).filter((m) => m >= D.start.slice(0, 8) + "01");
    const first = enrollments.filter((e) => !e.renewed_from);
    const cnt = (plan, m) => first.filter((e) => e.plan === plan && A.monthStart(e.start_date) === m && e.start_date <= R.end).length;
    A.chart("c-onb", { data: { labels: months.map(A.monthLabel), datasets: [
      { type: "bar", label: "Full program", data: months.map((m) => cnt("full_program", m)), backgroundColor: A.color("--s1"), stack: "s", ...A.barStyle, borderRadius: 0, borderColor: A.color("--surface"), borderWidth: { top: 2 } },
      { type: "bar", label: "3-month trial", data: months.map((m) => cnt("trial_3m", m)), backgroundColor: A.color("--s2"), stack: "s", ...A.barStyle, borderRadius: { topLeft: 4, topRight: 4 } },
      { type: "line", label: "Target", data: months.map((m) => (targets[m] || {}).students_onboarded), borderColor: A.color("--target"), backgroundColor: A.color("--target"), pointStyle: "line", pointRadius: 9, borderWidth: 2, showLine: false },
    ] }, options: { scales: { x: { stacked: true }, y: { stacked: true, ticks: { precision: 0 } } } } });
  }

  function workshopTable() {
    const ws = workshops.filter((w) => A.within(w.held_on, R) && w.held_on <= AS_OF);
    const rows = ws.map((w) => {
      const s = seats.filter((x) => x.workshop_id === w.workshop_id);
      const became = s.filter((x) => firstEnrByLead[x.lead_id]).length;
      return { held_on: w.held_on, title: w.title, sold: s.length, fill: s.length / w.capacity, revenue: s.length * Number(w.seat_price_inr), attended: s.filter((x) => x.attended === "true" || x.attended === true).length / Math.max(1, s.length), became };
    });
    A.renderTable(document.getElementById("t-wsp"), [
      { key: "held_on", label: "Date", fmt: (v) => A.dateLabel(v) },
      { key: "title", label: "Workshop" },
      { key: "sold", label: "Seats", num: true, fmt: (v) => `${v} / 40` },
      { key: "fill", label: "Fill", num: true, fmt: (v) => A.barCell(v, 1, 0.75, v >= 0.75 ? "var(--s3)" : "var(--serious)") },
      { key: "revenue", label: "Revenue", num: true, fmt: (v) => A.inr(v, true) },
      { key: "attended", label: "Showed up", num: true, fmt: (v) => A.pct(v) },
      { key: "became", label: "Became students", num: true },
    ], rows, { sortKey: "held_on", sortDir: "desc", empty: "No workshop was held in this range." });
  }

  function unpaidAsOf(ref) {
    return invoices.filter((i) => i.issued_on <= ref && !(payByInvoice[i.invoice_id] && payByInvoice[i.invoice_id].day <= ref))
      .map((i) => { const e = enrById[i.enrollment_id]; return { ...i, student: e.student_name, plan: e.plan, amount_inr: Number(i.amount_inr), overdue: A.diffDays(i.due_on, ref) }; });
  }
  function renewalsFrom(ref) {
    const renewed = new Map(enrollments.filter((e) => e.renewed_from).map((e) => [e.renewed_from, e]));
    return enrollments.filter((e) => e.plan === "trial_3m" && e.end_date >= ref && e.end_date <= A.addDays(ref, 30))
      .filter((e) => { const r = renewed.get(e.enrollment_id); return !r || A.addDays(r.start_date, -7) > ref; })
      .map((e) => ({ ...e, left: A.diffDays(ref, e.end_date) }));
  }

  function unpaidTable() {
    const ref = R.end > AS_OF ? AS_OF : R.end;
    const rows = unpaidAsOf(ref);
    document.getElementById("unpaid-sub").textContent = `As of ${A.dateLabel(ref)} · ${A.inr(A.sum(rows, (r) => r.amount_inr), true)} outstanding across ${rows.length} invoices`;
    A.renderTable(document.getElementById("t-unpaid"), [
      { key: "student", label: "Student" },
      { key: "plan", label: "Plan", fmt: (v) => (v === "trial_3m" ? "Trial" : "Full") },
      { key: "amount_inr", label: "Amount", num: true, fmt: (v) => A.inr(v, true) },
      { key: "due_on", label: "Due", fmt: (v) => A.dateLabel(v) },
      { key: "overdue", label: "Status", num: true, fmt: (v) => v <= 0 ? A.pill("neutral", "NOT DUE") : v <= 7 ? A.pill("warn", `${v}D LATE`) : v <= 30 ? A.pill("serious", `${v}D LATE`) : A.pill("critical", `${v}D LATE`) },
    ], rows, { sortKey: "overdue", empty: "Every invoice issued by this date was paid." });
  }

  function renewalTable() {
    const ref = R.end > AS_OF ? AS_OF : R.end;
    const rows = renewalsFrom(ref);
    document.getElementById("renew-sub").textContent = `3-month trials ending in the 30 days after ${A.dateLabel(ref)} with no full-program sign-up yet. n8n works this list at T-21, T-14 and T-7.`;
    A.renderTable(document.getElementById("t-renew"), [
      { key: "student_name", label: "Student" },
      { key: "start_date", label: "Started", fmt: (v) => A.dateLabel(v) },
      { key: "end_date", label: "Trial ends", fmt: (v) => A.dateLabel(v) },
      { key: "left", label: "Next step", num: true, fmt: (v) => v <= 7 ? A.pill("critical", `${v}D · CALL`) : v <= 14 ? A.pill("serious", `${v}D · ARCHITECT REVIEW`) : A.pill("neutral", `${v}D · REPORT SENT`) },
    ], rows, { sortKey: "left", sortDir: "asc", empty: "No trials end in the next 30 days." });
  }

  // ---------- funnel ----------
  function funnel() {
    const cohort = leads.filter((l) => A.within(l.day, R) && isProgramLead(l));
    const has = (l, s) => !!(stages[l.lead_id] || {})[s];
    const n = (s) => cohort.filter((l) => has(l, s)).length;
    const steps = [
      ["Total leads", cohort.length, "Meta + organic + workshop"],
      ["Qualified", n("qualified"), "ClickUp: fits age, city, intent"],
      ["Discovery call set", n("discovery_scheduled"), ""],
      ["Discovery attended", n("discovery_attended"), "show-up"],
      ["Ambition interview set", n("ambition_scheduled"), ""],
      ["Ambition interview done", n("ambition_attended"), "with the teen"],
      ["Architect session", n("architect_done"), "parents + teen, roadmap"],
      ["Signed up", n("won"), "trial or full program"],
    ];
    const host = document.getElementById("funnel-steps");
    host.replaceChildren();
    const max = steps[0][1] || 1;
    steps.forEach(([label, v, hint], i) => {
      if (i > 0) {
        const prev = steps[i - 1][1];
        const c = A.el("div", { class: "fconv" });
        const rate = v / Math.max(1, prev);
        c.append(A.el("b", {}, A.pct(rate)), document.createTextNode(" carry on"));
        if (i === 3) c.append(A.pill(rate >= 0.75 ? "good" : rate >= 0.65 ? "warn" : "critical", `SHOW-UP ${A.pct(rate)}`));
        if (i === 5) { const drop = 1 - v / Math.max(1, steps[3][1]); c.append(A.pill(drop <= 0.3 ? "good" : drop <= 0.4 ? "warn" : "critical", `DROP-OFF ${A.pct(drop)} since discovery`)); }
        host.append(c);
      }
      const row = A.el("div", { class: "fstep" });
      const lb = A.el("div", { class: "lbl" }, label); if (hint) lb.append(A.el("small", {}, hint));
      const tr = A.el("div", { class: "track" }); const bar = A.el("i"); bar.style.width = Math.max(0.6, (v / max) * 100) + "%";
      if (i === steps.length - 1) bar.style.background = "var(--s3)";
      tr.append(bar);
      row.append(lb, tr, A.el("div", { class: "val" }, A.int(v)));
      host.append(row);
    });

    // sources
    const srcRows = Object.entries(A.groupBy(cohort, (l) => l.source)).map(([s, ls]) => ({
      source: { meta_ads: "Meta ads", organic_instagram: "Instagram (organic)", referral: "Referral", website: "Website", workshop: "Workshop buyers" }[s] || s,
      paid: s === "meta_ads", leads: ls.length, qualified: ls.filter((l) => has(l, "qualified")).length / ls.length, won: ls.filter((l) => has(l, "won")).length,
    }));
    A.renderTable(document.getElementById("t-source"), [
      { key: "source", label: "Source", fmt: (v, r) => { const s = A.el("span", {}, v + " "); if (!r.paid) s.append(A.pill("neutral", "ORGANIC")); return s; } },
      { key: "leads", label: "Leads", num: true },
      { key: "qualified", label: "Qualified", num: true, fmt: (v) => A.pct(v) },
      { key: "won", label: "Signed", num: true },
    ], srcRows, { sortKey: "leads" });

    // journey
    const jr = [];
    for (const [name, pick] of [["Signed up", (s) => s.won], ["Dropped off", (s) => !s.won && (s.lost || s.disqualified)]]) {
      const d = cohort.map((l) => { const s = stages[l.lead_id] || {}; const end = pick(s); if (!end) return null; return (new Date(end.replace(" ", "T")) - new Date(l.created_at.replace(" ", "T"))) / 864e5; }).filter((x) => x != null);
      jr.push({ outcome: name, leads: d.length, avg: A.avg(d), med: A.median(d) });
    }
    A.renderTable(document.getElementById("t-journey"), [
      { key: "outcome", label: "Outcome" }, { key: "leads", label: "Leads", num: true },
      { key: "avg", label: "Avg days", num: true, fmt: (v) => A.dec(v) }, { key: "med", label: "Median", num: true, fmt: (v) => A.dec(v) },
    ], jr, {});
    const open = cohort.filter((l) => { const s = stages[l.lead_id] || {}; return !s.won && !s.lost && !s.disqualified; }).length;
    document.getElementById("t-journey").append(A.el("p", { class: "note" }, `${open} leads from this range are still open, so recent ranges understate sign-ups.`));

    // weekly leads
    const r = A.diffDays(R.start, R.end) < 56 ? { start: A.addDays(R.end, -83), end: R.end } : R;
    const weeks = []; for (let w = A.weekStart(r.start < D.start ? D.start : r.start); w <= r.end; w = A.addDays(w, 7)) weeks.push(w);
    const inW = leads.filter((l) => l.day >= weeks[0] && l.day <= r.end && isProgramLead(l));
    const byWeek = A.groupBy(inW, (l) => A.weekStart(l.day));
    const k = (w, f) => (byWeek[w] || []).filter(f).length;
    A.chart("c-leads", { data: { labels: weeks.map((w) => A.dateLabel(w)), datasets: [
      { type: "bar", label: "Paid (Meta)", data: weeks.map((w) => k(w, (l) => l.source === "meta_ads")), backgroundColor: A.color("--s1"), stack: "l", ...A.barStyle, borderRadius: 0, borderColor: A.color("--surface"), borderWidth: { top: 2 } },
      { type: "bar", label: "Organic", data: weeks.map((w) => k(w, (l) => !l.ad_id && l.source !== "workshop")), backgroundColor: A.color("--s2"), stack: "l", ...A.barStyle, borderRadius: 0, borderColor: A.color("--surface"), borderWidth: { top: 2 } },
      { type: "bar", label: "From workshops", data: weeks.map((w) => k(w, (l) => l.source === "workshop")), backgroundColor: A.color("--s3"), stack: "l", ...A.barStyle, borderRadius: { topLeft: 4, topRight: 4 } },
    ] }, options: { scales: { x: { stacked: true }, y: { stacked: true, ticks: { precision: 0 } } } } });
  }

  // ---------- campaigns ----------
  function adPerf(r) {
    const m = A.groupBy(adDaily.filter((x) => A.within(x.date, r)), (x) => x.ad_id);
    const leadBy = A.groupBy(leads.filter((l) => l.ad_id && A.within(l.day, r)), (l) => l.ad_id);
    return Object.entries(m).map(([id, rows]) => {
      const ad = ads[id], ls = leadBy[id] || [];
      const impr = A.sum(rows, (x) => x.impressions), clicks = A.sum(rows, (x) => x.link_clicks), spend = A.sum(rows, (x) => x.spend_inr), ml = A.sum(rows, (x) => x.meta_leads);
      const q = ls.filter((l) => stages[l.lead_id]?.qualified).length;
      const won = ls.filter((l) => firstEnrByLead[l.lead_id]).length;
      const rev = A.sum(ls, (l) => revenueByLead[l.lead_id] || 0) + (ad.objective === "workshop" ? ls.length * 3999 : 0);
      return { id, name: ad.name.split(" | ")[0], hook: ad.hook, type: ad.creative_type, objective: ad.objective, set: ad.ad_set_id, impr, clicks, ctr: clicks / Math.max(1, impr), spend, cpl: spend / Math.max(1, ml), q, cpql: q ? spend / q : null, won, seats: ad.objective === "workshop" ? ls.length : null, roas: rev / Math.max(1, spend) };
    });
  }

  function adsTable() {
    const rows = adPerf(R).filter((a) => a.objective === objective);
    const eligible = rows.filter((a) => a.impr >= 5000).sort((a, b) => b.ctr - a.ctr);
    const top = new Set(eligible.slice(0, 3).map((a) => a.id)), bottom = new Set(eligible.slice(-3).map((a) => a.id));
    const cols = [
      { key: "ctr", label: "", sort: (r) => r.ctr, fmt: (v, r) => top.has(r.id) ? A.pill("good", "TOP CTR") : bottom.has(r.id) && !top.has(r.id) ? A.pill("serious", "REFRESH") : A.el("span", { class: "muted" }, "") },
      { key: "name", label: "Creative" },
      { key: "hook", label: "Hook", cls: "wrap" },
      { key: "type", label: "Format" },
      { key: "impr", label: "Impressions", num: true, fmt: A.int },
      { key: "ctr2", label: "CTR", num: true, sort: (r) => r.ctr, fmt: (v, r) => A.pct(r.ctr, 2) },
      { key: "spend", label: "Spend", num: true, fmt: (v) => A.inr(v, true) },
      { key: "cpl", label: objective === "workshop" ? "Cost / checkout" : "CPL", num: true, fmt: (v) => A.inr(v, true) },
    ];
    if (objective === "program") cols.push(
      { key: "q", label: "Qualified", num: true },
      { key: "cpql", label: "CPQL", num: true, fmt: (v) => A.inr(v, true) },
      { key: "won", label: "Signed", num: true });
    else cols.push({ key: "seats", label: "Seats sold", num: true }, { key: "cps", label: "Cost / seat", num: true, sort: (r) => r.spend / Math.max(1, r.seats), fmt: (v, r) => A.inr(r.spend / Math.max(1, r.seats), true) });
    cols.push({ key: "roas", label: "ROAS", num: true, fmt: (v) => A.dec(v, 1) + "×" });
    A.renderTable(document.getElementById("t-ads"), cols, rows, { sortKey: "ctr2", empty: "No creative ran in this range." });
  }

  function latestFreq(r) {
    const ref = A.addDays(r.end, 6);
    const out = {};
    for (const f of freq) if (f.week_ending <= ref && (!out[f.ad_set_id] || f.week_ending > out[f.ad_set_id].week_ending)) out[f.ad_set_id] = f;
    return out;
  }

  const thresholdPlugin = (axis, value, colorVar) => ({
    id: "th" + axis + value,
    afterDatasetsDraw(chart) {
      const sc = chart.scales[axis]; if (!sc) return; const px = sc.getPixelForValue(value); const { ctx, chartArea: a } = chart;
      ctx.save(); ctx.strokeStyle = A.color(colorVar); ctx.lineWidth = 1.5; ctx.beginPath();
      if (axis === "x") { ctx.moveTo(px, a.top); ctx.lineTo(px, a.bottom); } else { ctx.moveTo(a.left, px); ctx.lineTo(a.right, px); }
      ctx.stroke(); ctx.restore();
    },
  });

  function freqChart() {
    const lf = latestFreq(R);
    const rows = Object.values(lf).map((f) => ({ name: adSets[f.ad_set_id].name.split(" | ").slice(0, 2).join(" · "), f: Number(f.frequency), wk: f.week_ending })).sort((a, b) => b.f - a.f);
    const col = (v) => A.color(v >= 3 ? "--critical" : v >= 2.5 ? "--warn" : "--s1");
    A.chart("c-freq", { type: "bar", data: { labels: rows.map((r) => r.name), datasets: [{ label: "7-day frequency", data: rows.map((r) => r.f), backgroundColor: rows.map((r) => col(r.f)), ...A.barStyle, borderSkipped: "start" }] },
      options: { indexAxis: "y", scales: { x: { min: 0, suggestedMax: 4, grid: { display: true } }, y: { grid: { display: false }, ticks: { autoSkip: false, font: { size: 11 } } } },
        plugins: { tooltip: { callbacks: { label: (c) => ` ${c.parsed.x.toFixed(2)}× · week ending ${A.dateLabel(rows[c.dataIndex].wk)}${c.parsed.x >= 3 ? " · change now" : ""}` } } } },
      plugins: [thresholdPlugin("x", 3, "--critical")] });
  }

  function lpHealth() {
    const len = A.diffDays(R.start, R.end) + 1;
    const P = { start: A.addDays(R.start, -len), end: A.addDays(R.start, -1) };
    const agg = (r) => {
      const g = A.groupBy(lpDaily.filter((x) => A.within(x.date, r)), (x) => x.landing_page_id);
      return Object.fromEntries(Object.entries(g).map(([id, rows]) => [id, { s: A.sum(rows, (x) => x.sessions), b: A.sum(rows, (x) => x.bounces), f: A.sum(rows, (x) => x.form_submits), load: A.median(rows.map((x) => Number(x.p75_load_ms))) }]));
    };
    const cur = agg(R), prev = agg(P);
    const rows = Object.entries(cur).map(([id, c]) => {
      const p = prev[id]; const br = c.b / c.s;
      return { name: lps[id].name, url: lps[id].url, sessions: c.s, bounce: br, dBounce: p ? br - p.b / p.s : null, cvr: c.f / c.s, load: c.load, pload: p ? p.load : null };
    });
    A.renderTable(document.getElementById("t-lp"), [
      { key: "name", label: "Page" },
      { key: "sessions", label: "Sessions", num: true, fmt: A.int },
      { key: "bounce", label: "Bounce", num: true, fmt: (v) => A.pct(v, 1) },
      { key: "dBounce", label: "vs prev", num: true, fmt: (v) => v == null ? "-" : (v >= 0 ? "+" : "") + (v * 100).toFixed(1) + " pts" },
      { key: "cvr", label: "Form CVR", num: true, fmt: (v) => A.pct(v, 1) },
      { key: "load", label: "Load p75", num: true, fmt: (v, r) => `${(v / 1000).toFixed(1)}s` + (r.pload ? ` (was ${(r.pload / 1000).toFixed(1)}s)` : "") },
      { key: "st", label: "Status", sort: (r) => r.load, fmt: (v, r) => r.load > 3000 || r.bounce > 0.6 ? A.pill("critical", "FIX") : r.load > 2500 ? A.pill("warn", "WATCH") : A.pill("good", "HEALTHY") },
    ], rows, { sortKey: "st" });

    const r = A.diffDays(R.start, R.end) < 56 ? { start: A.addDays(R.end, -83), end: R.end } : R;
    const weeks = []; for (let w = A.weekStart(r.start < D.start ? D.start : r.start); w <= r.end; w = A.addDays(w, 7)) weeks.push(w);
    const by = A.groupBy(lpDaily.filter((x) => x.date >= weeks[0] && x.date <= r.end), (x) => x.landing_page_id + "|" + A.weekStart(x.date));
    const series = [["lp_parent", "--s1", "Parent LP"], ["lp_teen", "--s2", "Teen LP"], ["lp_wsp", "--s3", "Workshop checkout"]];
    A.chart("c-lp", { type: "line", data: { labels: weeks.map(A.dateLabel), datasets: series.map(([id, c, name]) => ({
      label: name, data: weeks.map((w) => { const rows = by[id + "|" + w]; return rows ? A.median(rows.map((x) => Number(x.p75_load_ms))) / 1000 : null; }),
      borderColor: A.color(c), backgroundColor: A.color(c), borderWidth: 2, pointRadius: 0, pointHoverRadius: 4, tension: 0.25 })) },
      options: { scales: { y: { min: 0, suggestedMax: 5.5, ticks: { callback: (v) => v + "s" } } }, plugins: { tooltip: { callbacks: { label: (c) => ` ${c.dataset.label}: ${c.parsed.y.toFixed(2)}s` } } } },
      plugins: [thresholdPlugin("y", 3, "--critical")] });
  }

  // ---------- RCA ----------
  function rca() {
    const mid = A.addDays(R.start, Math.floor(A.diffDays(R.start, R.end) / 2));
    const lf = latestFreq(R);
    const cpqlT = (targets[A.monthStart(R.end)] || {}).cpql_max || 2000;
    const bySet = A.groupBy(adPerf(R).filter((a) => a.objective === "program"), (a) => a.set);
    const daily = adDaily.filter((x) => A.within(x.date, R));
    const rows = Object.entries(bySet).map(([sid, ads_]) => {
      const spend = A.sum(ads_, (a) => a.spend), q = A.sum(ads_, (a) => a.q), won = A.sum(ads_, (a) => a.won);
      const ids = new Set(ads_.map((a) => a.id));
      const h1 = daily.filter((x) => ids.has(x.ad_id) && x.date <= mid), h2 = daily.filter((x) => ids.has(x.ad_id) && x.date > mid);
      const c1 = A.sum(h1, (x) => x.link_clicks) / Math.max(1, A.sum(h1, (x) => x.impressions));
      const c2 = A.sum(h2, (x) => x.link_clicks) / Math.max(1, A.sum(h2, (x) => x.impressions));
      const ctrChange = c1 ? (c2 - c1) / c1 : 0;
      const f = lf[sid] ? Number(lf[sid].frequency) : 0;
      const cpql = q ? spend / q : null;
      let d, why;
      if (spend < 15000) { d = "LEARNING"; why = `only ${A.inr(spend)} spent`; }
      else if (cpql == null || (cpql > 1.5 * cpqlT && won === 0)) { d = "DROP"; why = cpql == null ? "no qualified leads" : `CPQL ${A.dec(cpql / cpqlT, 1)}× target, 0 sign-ups`; }
      else if (f >= 3 || ctrChange <= -0.2) { d = "REFRESH"; why = f >= 3 ? `frequency ${f.toFixed(1)}` : `CTR ${A.pct(ctrChange)}`; }
      else if (cpql <= cpqlT && f < 2.5 && ctrChange > -0.1) { d = "SCALE"; why = `CPQL ${A.inr(cpql, true)}, fresh audience`; }
      else { d = "HOLD"; why = cpql > cpqlT ? `CPQL above target, not bad enough to drop` : `frequency ${f.toFixed(1)} rising`; }
      return { set: adSets[sid].name, short: adSets[sid].name.split(" | ").slice(0, 2).join(" · "), spend, q, won, cpql, f, ctrChange, d, why };
    });
    const pill = { LEARNING: "neutral", DROP: "critical", REFRESH: "serious", SCALE: "good", HOLD: "warn" };
    A.renderTable(document.getElementById("t-rca"), [
      { key: "d", label: "Decision", fmt: (v) => A.pill(pill[v], v), sort: (r) => ["DROP", "REFRESH", "SCALE", "HOLD", "LEARNING"].indexOf(r.d) },
      { key: "set", label: "Ad set", cls: "wrap" },
      { key: "spend", label: "Spend", num: true, fmt: (v) => A.inr(v) },
      { key: "q", label: "Qual.", num: true },
      { key: "cpql", label: "CPQL", num: true, fmt: (v) => A.inr(v, true) },
      { key: "f", label: "Freq", num: true, fmt: (v) => v.toFixed(1) },
      { key: "ctrChange", label: "CTR Δ", num: true, fmt: (v) => (v >= 0 ? "+" : "") + (v * 100).toFixed(0) + "%" },
      { key: "won", label: "Signed", num: true },
      { key: "why", label: "Why", cls: "wrap" },
    ], rows, { sortKey: "d", sortDir: "asc" });

    document.getElementById("rca-sub").textContent = `Program ad sets. Up = expensive leads (target ${A.inr(cpqlT, true)}); right = tired audience (3+).`;
    const statusVar = { LEARNING: "--muted", DROP: "--critical", REFRESH: "--serious", SCALE: "--good", HOLD: "--warn" };
    const pts = rows.filter((r) => r.cpql != null);
    A.chart("c-rca", { type: "scatter", data: { datasets: [{ label: "Ad sets", data: pts.map((r) => ({ x: r.f, y: r.cpql })),
      pointRadius: 7, pointHoverRadius: 9, pointHitRadius: 14, borderColor: A.color("--surface"), borderWidth: 2, backgroundColor: pts.map((r) => A.color(statusVar[r.d])) }] },
      options: { interaction: { mode: "nearest", intersect: false },
        scales: { x: { min: 0, suggestedMax: 4.5, title: { display: true, text: "7-day frequency" }, grid: { display: true } }, y: { min: 0, title: { display: true, text: "Cost per qualified lead" }, ticks: { callback: (v) => A.inr(v) } } },
        plugins: { tooltip: { callbacks: { title: (it) => pts[it[0].dataIndex].short, label: (c) => { const r = pts[c.dataIndex]; return [` ${r.d}: ${r.why}`, ` CPQL ${A.inr(r.cpql, true)} · freq ${r.f.toFixed(2)}`]; } } } } },
      plugins: [thresholdPlugin("x", 3, "--critical"), thresholdPlugin("y", cpqlT, "--target"), {
        id: "labels", afterDatasetsDraw(chart) {
          const { ctx } = chart; const meta = chart.getDatasetMeta(0); ctx.save(); ctx.font = `11px ${A.color("--font-ui")}`; ctx.fillStyle = A.color("--ink-2");
          meta.data.forEach((p, i) => { const t = pts[i].short.split(" · ")[1] || pts[i].short; ctx.fillText(t.length > 22 ? t.slice(0, 21) + "…" : t, p.x + 10, p.y + 4); });
          ctx.restore();
        } }] });
  }

  // ---------- wiring ----------
  function renderAll() {
    tiles(); revenueChart(); revenueMix(); onboarding(); workshopTable(); unpaidTable(); renewalTable();
    funnel(); adsTable(); freqChart(); lpHealth(); rca();
  }
  document.querySelectorAll("#obj-toggle button").forEach((b) => b.addEventListener("click", () => {
    objective = b.dataset.o;
    document.querySelectorAll("#obj-toggle button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    adsTable();
  }));
  A.rangeControl(document.getElementById("filters"), { asOf: AS_OF, minDate: D.start, key: "alc-gtm-range", defaultPreset: "last_month", onChange: (r) => { R = r; renderAll(); } });
  A.onTheme(() => R && renderAll());
})();
