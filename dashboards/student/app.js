/* Alcovian Progress Board - mirrors sql/metrics/40_student_kpis.sql.
   Three lenses: did Alcovia conduct it (quantity), did Alcovians like it (quality),
   how is each Alcovian doing (performance). */
(function () {
  const A = window.Alc, D = window.STUDENT_DATA, AS_OF = D.as_of;
  const T = (n) => A.table(D, n);
  const bool = (v) => v === true || v === "true";

  // ---------- load + index ----------
  const advisors = Object.fromEntries(T("advisors").map((a) => [a.advisor_id, a.name]));
  const students = T("students");
  const subjects = T("subjects");
  const subjBy = A.groupBy(subjects, (s) => s.student_id);
  const chapters = T("chapters");
  const subjOfChapter = Object.fromEntries(chapters.map((c) => [c.chapter_id, c.subject_id]));
  const studentOfSubj = Object.fromEntries(subjects.map((s) => [s.subject_id, s.student_id]));
  const chapBySubj = A.groupBy(chapters, (c) => c.subject_id);
  const stageEv = T("chapter_stage_events");
  const stageByCh = A.groupBy(stageEv, (e) => e.chapter_id);
  const targets = T("exam_targets"), results = T("exam_results");
  const tasks = A.groupBy(T("tasks"), (t) => t.student_id);
  const focus = A.groupBy(T("focus_sessions").map((f) => ({ ...f, day: A.day(f.started_at), actual_min: Number(f.actual_min) })), (f) => f.student_id);
  const blocks = A.groupBy(T("timetable_blocks"), (b) => b.student_id);
  const quizzes = T("quizzes");
  const quizDay = Object.fromEntries(quizzes.map((q) => [q.quiz_id, q.quiz_date]));
  const attempts = A.groupBy(T("quiz_attempts").map((a) => ({ ...a, day: quizDay[a.quiz_id] })), (a) => a.student_id);
  const wear = A.groupBy(T("wearable_daily"), (w) => w.student_id);
  const activities = T("activities");
  const actById = Object.fromEntries(activities.map((a) => [a.activity_id, a]));
  const parts = T("activity_participants").map((p) => ({ ...p, act: actById[p.activity_id], attended: bool(p.attended), rating: p.rating == null ? null : Number(p.rating) }));
  const partsBy = A.groupBy(parts, (p) => p.student_id);
  const skills = T("soft_skill_scores");
  const miles = A.groupBy(T("roadmap_milestones"), (m) => m.student_id);
  const esc = T("escalations");

  const KIND = {
    daily_quiz: ["8pm quiz", "Daily"], academic_session: ["Academic sessions", "Weekly"],
    workshop: ["Career workshops", "Monthly"], pod: ["Pod sessions", "Monthly"], peer_session: ["Peer sessions", "Monthly"],
    mentor_call: ["Mentor calls", "Monthly"], branding_shoot: ["Personal branding shoots", "Monthly"],
    podcast: ["Podcast shoots", "Quarterly"], competition_prep: ["Competition prep", "Quarterly"],
    parent_child: ["Parent-child workshop", "Quarterly"], out_of_city: ["Out-of-city experience", "Quarterly"],
  };
  const STAGE = ["Not started", "Read", "Notes", "Practice ≥70%", "Past paper", "Exam-ready"];
  const STAGE_COL = ["--surface-2", "#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#104281"];

  let R = null, advisor = "", selected = null;

  // ---------- thresholds (docs/04_student_dashboard.md) ----------
  const RULES = {
    focus: [40, 15], quiz: [0.7, 0.5], taskDone: [0.8, 0.6], onTime: [0.7, 0.5], pace: [0.95, 0.8],
    ready: [60, 40], gap: [-2, -8], attend: [0.85, 0.7], sleep: [7.5, 6.5], est: [0.75, 0.6],
  };
  const rag = (k, v) => { if (v == null || Number.isNaN(v)) return null; const [g, w] = RULES[k]; return v >= g ? "good" : v >= w ? "warn" : "critical"; };

  // ---------- per-student metrics ----------
  function quarterNow(ref) { const m = Number(ref.slice(5, 7)); return m >= 4 && m <= 6 ? 1 : m <= 9 && m >= 7 ? 2 : m >= 10 ? 3 : 4; }
  function qStart(ref) { const m = Number(ref.slice(5, 7)); const qm = m - ((m - 1) % 3); return ref.slice(0, 5) + String(qm).padStart(2, "0") + "-01"; }

  function metrics(s, r) {
    const end = r.end > AS_OF ? AS_OF : r.end;
    const start = r.start > s.joined_on ? r.start : s.joined_on;
    const n = Math.max(1, A.diffDays(start, end) + 1);
    const inR = (d) => d >= r.start && d <= end;
    const fs = (focus[s.student_id] || []).filter((f) => inR(f.day));
    const fm = A.sum(fs, (f) => f.actual_min);
    const planned = A.sum((blocks[s.student_id] || []).filter((b) => inR(b.date)), (b) => b.planned_min);
    const pub = quizzes.filter((q) => bool(q.published) && inR(q.quiz_date)).length;
    const qa = (attempts[s.student_id] || []).filter((a) => inR(a.day));
    const due = (tasks[s.student_id] || []).filter((t) => inR(t.due_on));
    const withAct = due.filter((t) => t.actual_min != null);
    // syllabus as of the range end
    const qn = quarterNow(end), qel = A.diffDays(qStart(end), end) / 91;
    let expected = 0, started = 0, readySum = 0, readyN = 0, deep = 0;
    const stageDist = [0, 0, 0, 0, 0, 0];
    for (const sub of subjBy[s.student_id] || []) for (const ch of chapBySubj[sub.subject_id] || []) {
      const top = Math.max(0, ...(stageByCh[ch.chapter_id] || []).filter((e) => e.reached_on <= end).map((e) => Number(e.stage)));
      const pq = Number(ch.planned_quarter);
      expected += pq < qn ? 1 : pq === qn ? qel : 0;
      if (top >= 1) started++;
      if (top >= 4) deep++;
      if (pq < qn) { readySum += top * 20; readyN++; stageDist[top]++; }
    }
    // latest exam vs target
    const subIds = new Set((subjBy[s.student_id] || []).map((x) => x.subject_id));
    const myRes = results.filter((x) => subIds.has(x.subject_id) && x.exam_date <= end);
    const lastDate = myRes.reduce((m, x) => (x.exam_date > m ? x.exam_date : m), "");
    const gaps = myRes.filter((x) => x.exam_date === lastDate).map((x) => { const t = targets.find((t) => t.subject_id === x.subject_id && t.exam_type === x.exam_type); return t ? Number(x.score_pct) - Number(t.target_pct) : null; }).filter((x) => x != null);
    const w = (wear[s.student_id] || []).filter((x) => inR(x.date));
    const ps = (partsBy[s.student_id] || []).filter((p) => p.act.conducted_on && inR(p.act.conducted_on));
    const ms = (miles[s.student_id] || []).filter((m) => inR(m.due_on));
    return {
      s, name: s.name, grade: s.grade, advisor: advisors[s.advisor_id],
      focus: fm / n, focusDone: fs.length ? fs.filter((f) => f.status === "completed").length / fs.length : null,
      adherence: planned ? A.sum(fs.filter((f) => bool(f.in_planned_block)), (f) => f.actual_min) / planned : null,
      quiz: pub ? qa.length / pub : null, quizScore: A.avg(qa, (a) => Number(a.score_pct)),
      taskDone: due.length ? due.filter((t) => t.completed_on).length / due.length : null,
      onTime: due.length ? due.filter((t) => t.completed_on && t.completed_on <= t.due_on).length / due.length : null,
      est: withAct.length ? 1 - A.avg(withAct, (t) => Math.min(1, Math.abs(t.actual_min - t.estimated_min) / t.estimated_min)) : null,
      pace: expected ? started / expected : null, ready: readyN ? readySum / readyN : null, rigour: started ? deep / started : null, stageDist,
      gap: gaps.length ? A.avg(gaps) : null, lastExam: lastDate,
      active: w.length ? A.avg(w, (x) => Number(x.active_min)) : null, sleep: w.length ? A.avg(w, (x) => Number(x.sleep_min)) / 60 : null,
      recovery: w.length ? A.avg(w, (x) => x.recovery_pct == null ? null : Number(x.recovery_pct)) : null,
      attend: ps.length ? ps.filter((p) => p.attended).length / ps.length : null,
      milestones: ms.length ? ms.filter((m) => m.done_on && m.done_on <= m.due_on).length / ms.length : null,
    };
  }
  function flags(m) {
    const f = { focus: rag("focus", m.focus), quiz: rag("quiz", m.quiz), taskDone: rag("taskDone", m.taskDone), onTime: rag("onTime", m.onTime),
      pace: rag("pace", m.pace), ready: rag("ready", m.ready), gap: rag("gap", m.gap), attend: rag("attend", m.attend), sleep: rag("sleep", m.sleep) };
    const vals = Object.values(f).filter(Boolean);
    const crit = vals.filter((x) => x === "critical").length, warn = vals.filter((x) => x === "warn").length;
    return { f, crit, warn, status: crit >= 3 ? "critical" : crit >= 1 || warn >= 3 ? "warn" : "good" };
  }
  const selStudents = () => students.filter((s) => !advisor || s.advisor_id === advisor);

  // ---------- lenses ----------
  function quantityRows() {
    const end = R.end > AS_OF ? AS_OF : R.end;
    const acts = activities.filter((a) => a.scheduled_on >= R.start && a.scheduled_on <= end);
    const rows = Object.entries(A.groupBy(acts, (a) => a.kind)).map(([k, xs]) => ({ kind: k, sched: xs.length, done: xs.filter((a) => a.conducted_on).length }));
    const qz = quizzes.filter((q) => q.quiz_date >= R.start && q.quiz_date <= end);
    rows.push({ kind: "daily_quiz", sched: qz.length, done: qz.filter((q) => bool(q.published)).length });
    return rows.map((r) => ({ ...r, rate: r.done / Math.max(1, r.sched) }));
  }
  function qualityRows() {
    const end = R.end > AS_OF ? AS_OF : R.end;
    const ps = parts.filter((p) => p.act.conducted_on && p.act.conducted_on >= R.start && p.act.conducted_on <= end);
    const rows = Object.entries(A.groupBy(ps, (p) => p.act.kind)).map(([k, xs]) => {
      const att = xs.filter((p) => p.attended), rated = att.filter((p) => p.rating != null);
      return { kind: k, invited: xs.length, attend: att.length / xs.length, rating: A.avg(rated, (p) => p.rating), resp: rated.length / Math.max(1, att.length), top: rated.length ? rated.filter((p) => p.rating >= 4).length / rated.length : null };
    });
    const qa = Object.values(attempts).flat().filter((a) => a.day >= R.start && a.day <= end);
    const rated = qa.filter((a) => a.liked != null);
    rows.push({ kind: "daily_quiz", invited: qa.length, attend: null, rating: null, resp: rated.length / Math.max(1, qa.length), top: rated.length ? rated.filter((a) => bool(a.liked)).length / rated.length : null });
    return rows;
  }

  function lenses(all) {
    const q = quantityRows(), ql = qualityRows();
    const sched = A.sum(q, (r) => r.sched), done = A.sum(q, (r) => r.done);
    const worstQ = [...q].sort((a, b) => a.rate - b.rate)[0];
    const sessions = ql.filter((r) => r.kind !== "daily_quiz");
    const att = A.sum(sessions, (r) => r.attend * r.invited) / Math.max(1, A.sum(sessions, (r) => r.invited));
    const rating = A.sum(sessions.filter((r) => r.rating), (r) => r.rating * r.invited) / Math.max(1, A.sum(sessions.filter((r) => r.rating), (r) => r.invited));
    const worstAtt = [...sessions].sort((a, b) => a.attend - b.attend)[0];
    const st = all.map((m) => flags(m).status);
    const host = document.getElementById("lenses");
    host.replaceChildren();
    const card = (k, q, big, sub, rows, status) => {
      const t = A.el("div", { class: "tile" });
      t.append(A.el("span", { class: "k" }, k), A.el("span", { class: "q" }, q));
      const v = A.el("span", { class: "v" }, big); t.append(v);
      const s = A.el("span", { class: "s" }); if (status) s.append(status, document.createTextNode(" ")); s.append(document.createTextNode(sub)); t.append(s);
      for (const [a, b] of rows) { const r = A.el("div", { class: "row" }); r.append(A.el("span", {}, a), A.el("b", {}, b)); t.append(r); }
      host.append(t);
    };
    const qr = done / Math.max(1, sched);
    card("Quantity", "Did Alcovia conduct it?", A.pct(qr), `${A.int(done)} of ${A.int(sched)} promised touchpoints held`, [
      ["Weakest", `${KIND[worstQ.kind][0]} ${A.pct(worstQ.rate)}`], ["Delivery bar", "95%"]], A.pill(qr >= 0.95 ? "good" : qr >= 0.85 ? "warn" : "critical", qr >= 0.95 ? "ON BAR" : "BELOW BAR"));
    card("Quality", "Did Alcovians like it?", `${A.dec(rating, 2)} / 5`, `average session rating · ${A.pct(att)} attendance`, [
      ["Lowest attendance", `${KIND[worstAtt.kind][0]} ${A.pct(worstAtt.attend)}`], ["Quiz liked", A.pct(ql.find((r) => r.kind === "daily_quiz").top)]]);
    const atRisk = st.filter((x) => x === "critical").length, watch = st.filter((x) => x === "warn").length;
    card("Performance", "How are Alcovians doing?", `${st.length - atRisk - watch} on track`, `of ${st.length} students · ${watch} to watch · ${atRisk} at risk`, [
      ["Median focus / day", `${A.dec(A.median(all.map((m) => m.focus)), 0)} min`], ["Median syllabus pace", A.pct(A.median(all.map((m) => m.pace)))]],
      atRisk ? A.pill("critical", `${atRisk} AT RISK`) : A.pill("good", "NONE AT RISK"));
  }

  function quantity() {
    const rows = quantityRows();
    const host = document.getElementById("q-list");
    host.replaceChildren();
    for (const cad of ["Daily", "Weekly", "Monthly", "Quarterly"]) {
      const rs = rows.filter((r) => KIND[r.kind][1] === cad);
      if (!rs.length) continue;
      host.append(A.el("div", { class: "cad" }, cad));
      for (const r of rs) {
        const row = A.el("div", { class: "qrow" });
        row.append(A.el("span", {}, KIND[r.kind][0]), A.barCell(r.rate, 1, 0.95, r.rate >= 0.95 ? "var(--s3)" : r.rate >= 0.85 ? "var(--warn)" : "var(--critical)"),
          A.el("span", { class: "n" }, `${r.done}/${r.sched}`), A.el("span", { class: "n" }, A.pct(r.rate)));
        host.append(row);
      }
    }
    const missed = rows.filter((r) => r.sched - r.done > 0).sort((a, b) => (b.sched - b.done) - (a.sched - a.done));
    A.chart("c-missed", { type: "bar", data: { labels: missed.map((r) => KIND[r.kind][0]), datasets: [{ label: "Missed", data: missed.map((r) => r.sched - r.done), backgroundColor: A.color("--s2"), ...A.barStyle }] },
      options: { indexAxis: "y", scales: { x: { ticks: { precision: 0 }, grid: { display: true } }, y: { grid: { display: false } } },
        plugins: { tooltip: { callbacks: { label: (c) => ` ${c.parsed.x} missed of ${missed[c.dataIndex].sched} scheduled` } } } } });
  }

  function quality() {
    A.renderTable(document.getElementById("t-quality"), [
      { key: "kind", label: "Touchpoint", fmt: (v) => KIND[v][0] },
      { key: "invited", label: "Invites", num: true, fmt: (v, r) => (r.kind === "daily_quiz" ? `${v} attempts` : v) },
      { key: "attend", label: "Attended", num: true, fmt: (v) => (v == null ? "-" : A.barCell(v, 1, 0.85, v >= 0.85 ? "var(--s3)" : v >= 0.7 ? "var(--warn)" : "var(--critical)")) },
      { key: "attendPct", label: "", num: true, sort: (r) => r.attend, fmt: (v, r) => A.pct(r.attend) },
      { key: "rating", label: "Rating", num: true, fmt: (v) => (v == null ? "-" : A.dec(v, 2)) },
      { key: "top", label: "Rated 4-5", num: true, fmt: (v, r) => (r.kind === "daily_quiz" ? `${A.pct(v)} liked` : A.pct(v)) },
      { key: "resp", label: "Response", num: true, fmt: (v) => A.pct(v) },
    ], qualityRows(), { sortKey: "attendPct", sortDir: "asc" });

    // soft-skill heat grid
    const end = R.end > AS_OF ? AS_OF : R.end;
    const r = A.diffDays(R.start, end) < 90 ? { start: A.monthStart(A.addDays(end, -150)), end } : { start: R.start, end };
    const ids = new Set(selStudents().map((s) => s.student_id));
    const sc = skills.filter((x) => ids.has(x.student_id)).map((x) => ({ ...x, m: A.monthStart(actById[x.activity_id].conducted_on) })).filter((x) => x.m >= A.monthStart(r.start) && x.m <= r.end);
    const months = [...new Set(sc.map((x) => x.m))].sort();
    const names = [...new Set(sc.map((x) => x.skill))];
    const g = A.groupBy(sc, (x) => x.skill + "|" + x.m);
    const host = document.getElementById("heat");
    host.replaceChildren();
    if (!months.length) { host.append(A.el("div", { class: "empty" }, "No workshops in this range.")); return; }
    const grid = A.el("div", { class: "heat" });
    grid.style.gridTemplateColumns = `minmax(110px, 1.4fr) repeat(${months.length}, minmax(38px, 1fr))`;
    grid.append(A.el("div"));
    for (const m of months) { const h = A.el("div", { class: "h" }, A.monthLabel(m)); h.style.justifyContent = "center"; grid.append(h); }
    for (const sk of names.sort()) {
      grid.append(A.el("div", { class: "h" }, sk.replace(/_/g, " ")));
      for (const m of months) {
        const v = A.avg(g[sk + "|" + m] || [], (x) => Number(x.score));
        const c = A.el("div", { class: "c", title: `${sk.replace(/_/g, " ")} · ${A.monthLabel(m)}: ${A.dec(v, 2)}` }, v == null ? "" : A.dec(v, 1));
        const pctMix = v == null ? 0 : Math.round(((v - 1) / 4) * 85 + 10);
        c.style.background = `color-mix(in srgb, var(--s1) ${pctMix}%, var(--surface-2))`;
        c.style.color = pctMix > 55 ? "#fff" : "var(--ink)";
        grid.append(c);
      }
    }
    host.append(grid);
  }

  // ---------- performance ----------
  function cell(key, v, fmtd) {
    const k = rag(key, v);
    if (k == null) return A.el("span", { class: "muted" }, "-");
    return A.pill(k, fmtd);
  }
  function scorecard(all) {
    const host = document.getElementById("t-score");
    A.renderTable(host, [
      { key: "status", label: "Status", sort: (m) => -(flags(m).crit * 10 + flags(m).warn), fmt: (v, m) => { const f = flags(m); return A.pill(f.status, f.status === "critical" ? "AT RISK" : f.status === "warn" ? "WATCH" : "ON TRACK"); } },
      { key: "name", label: "Student", fmt: (v, m) => `${v} · ${m.grade}` },
      { key: "advisor", label: "Advisor", fmt: (v) => v.split(" ")[0] },
      { key: "focus", label: "Focus min/day", num: true, fmt: (v) => cell("focus", v, A.dec(v, 0)) },
      { key: "quiz", label: "Quiz", num: true, fmt: (v) => cell("quiz", v, A.pct(v)) },
      { key: "taskDone", label: "Tasks done", num: true, fmt: (v) => cell("taskDone", v, A.pct(v)) },
      { key: "onTime", label: "On time", num: true, fmt: (v) => cell("onTime", v, A.pct(v)) },
      { key: "est", label: "Estimate acc.", num: true, fmt: (v) => cell("est", v, A.pct(v)) },
      { key: "pace", label: "Syllabus pace", num: true, fmt: (v) => cell("pace", v, A.pct(v)) },
      { key: "ready", label: "Readiness", num: true, fmt: (v) => cell("ready", v, A.dec(v, 0)) },
      { key: "gap", label: "Exam vs target", num: true, fmt: (v) => cell("gap", v, (v >= 0 ? "+" : "") + A.dec(v, 1)) },
      { key: "attend", label: "Sessions", num: true, fmt: (v) => cell("attend", v, A.pct(v)) },
      { key: "sleep", label: "Sleep", num: true, fmt: (v) => cell("sleep", v, A.dec(v, 1) + "h") },
    ], all, { sortKey: "status", sortDir: "asc" });
    const rows = host.querySelectorAll("tbody tr");
    const order = [...all].sort((a, b) => -(flags(a).crit * 10 + flags(a).warn) + (flags(b).crit * 10 + flags(b).warn));
    // re-bind clicks after every sort: rows carry the student name in column 2
    const bind = () => host.querySelectorAll("tbody tr").forEach((tr) => {
      const nm = tr.children[1].textContent.split(" · ")[0];
      if (selected && nm === selected.name) tr.classList.add("sel");
      tr.onclick = () => { selected = students.find((s) => s.name === nm); drill(); host.querySelectorAll("tr.sel").forEach((x) => x.classList.remove("sel")); tr.classList.add("sel"); document.getElementById("student").scrollIntoView({ behavior: "smooth" }); };
      tr.tabIndex = 0; tr.onkeydown = (e) => { if (e.key === "Enter") tr.onclick(); };
    });
    bind();
    host.querySelectorAll("th").forEach((th) => th.addEventListener("click", bind));
    if (!selected || !all.find((m) => m.s.student_id === selected.student_id)) selected = order[0]?.s || null;
    void rows;
  }

  function trends(all) {
    const end = R.end > AS_OF ? AS_OF : R.end;
    const r = A.diffDays(R.start, end) < 56 ? { start: A.addDays(end, -83), end } : { start: R.start, end };
    const weeks = []; for (let w = A.weekStart(r.start < D.start ? D.start : r.start); w <= end; w = A.addDays(w, 7)) weeks.push(w);
    const ss = all.map((m) => m.s);
    const fm = [], qz = [], ot = [];
    for (const w of weeks) {
      const we = A.addDays(w, 6) > end ? end : A.addDays(w, 6);
      const act = ss.filter((s) => s.joined_on <= we);
      const days = A.diffDays(w, we) + 1;
      fm.push(A.sum(act, (s) => A.sum((focus[s.student_id] || []).filter((f) => f.day >= w && f.day <= we), (f) => f.actual_min)) / Math.max(1, act.length * days));
      const pub = quizzes.filter((q) => bool(q.published) && q.quiz_date >= w && q.quiz_date <= we).length;
      qz.push(A.sum(act, (s) => (attempts[s.student_id] || []).filter((a) => a.day >= w && a.day <= we).length) / Math.max(1, act.length * pub));
      const due = act.flatMap((s) => (tasks[s.student_id] || []).filter((t) => t.due_on >= w && t.due_on <= we));
      ot.push(due.length ? due.filter((t) => t.completed_on && t.completed_on <= t.due_on).length / due.length : null);
    }
    const labels = weeks.map(A.dateLabel);
    const line = (c, data, label) => ({ label, data, borderColor: A.color(c), backgroundColor: A.color(c) + "22", borderWidth: 2, pointRadius: 0, pointHoverRadius: 4, tension: 0.25 });
    A.chart("c-focus", { type: "line", data: { labels, datasets: [{ ...line("--s1", fm, "Focus min/day"), fill: true }] },
      options: { scales: { y: { min: 0, ticks: { callback: (v) => v + "m" } }, x: { ticks: { maxTicksLimit: 8 } } }, plugins: { tooltip: { callbacks: { label: (c) => ` ${c.parsed.y.toFixed(1)} min/day` } } } } });
    A.chart("c-habits", { type: "line", data: { labels, datasets: [line("--s2", qz, "Quiz participation"), line("--s3", ot, "Tasks on time")] },
      options: { scales: { y: { min: 0, max: 1, ticks: { callback: (v) => v * 100 + "%" } }, x: { ticks: { maxTicksLimit: 8 } } }, plugins: { tooltip: { callbacks: { label: (c) => ` ${c.dataset.label}: ${A.pct(c.parsed.y)}` } } } } });
  }

  function stagesTable(all) {
    const lg = document.getElementById("stage-legend");
    lg.replaceChildren();
    STAGE.forEach((n, i) => { const s = A.el("span"); const sw = A.el("i"); sw.style.background = STAGE_COL[i].startsWith("--") ? `var(${STAGE_COL[i]})` : STAGE_COL[i]; s.append(sw, document.createTextNode(`${i} ${n}`)); lg.append(s); });
    A.renderTable(document.getElementById("t-stages"), [
      { key: "name", label: "Student" },
      { key: "dist", label: "Chapters due, by furthest step", sort: (m) => m.ready, fmt: (v, m) => {
        const tot = A.sum(m.stageDist) || 1; const bar = A.el("div", { class: "stages", title: m.stageDist.map((c, i) => `${STAGE[i]}: ${c}`).join(" · ") });
        m.stageDist.forEach((c, i) => { if (!c) return; const x = A.el("i"); x.style.flex = `${c} 0 0`; x.style.background = STAGE_COL[i].startsWith("--") ? `var(${STAGE_COL[i]})` : STAGE_COL[i]; bar.append(x); });
        void tot; return bar; } },
      { key: "ready", label: "Readiness", num: true, fmt: (v) => A.dec(v, 0) },
      { key: "rigour", label: "Full rigour", num: true, fmt: (v) => A.pct(v) },
    ], all, { sortKey: "dist", sortDir: "asc" });
  }

  // ---------- one student ----------
  function drill() {
    const host = document.getElementById("drill");
    host.replaceChildren();
    if (!selected) { host.append(A.el("div", { class: "empty" }, "Pick a student in the table above.")); return; }
    const all = selStudents().map((s) => metrics(s, R));
    const m = metrics(selected, R), f = flags(m);
    const med = (k) => A.median(all.map((x) => x[k]));
    const top = A.el("div", { class: "card" });
    const who = A.el("div", { class: "who" });
    who.append(A.el("h3", {}, selected.name), A.el("span", { class: "muted" }, `Grade ${selected.grade} · ${selected.board} · ${selected.pod} · advisor ${advisors[selected.advisor_id]} · joined ${A.dateLabel(selected.joined_on)} · wearable: ${selected.wearable ? selected.wearable.replace("_", " ") : "none"}`),
      A.pill(f.status, f.status === "critical" ? `AT RISK · ${f.crit} RED FLAGS` : f.status === "warn" ? "WATCH" : "ON TRACK"));
    const kp = A.el("div", { class: "kpis" });
    const k = (label, key, fmt, ragKey) => {
      const d = A.el("div", { class: "kpi" });
      d.append(A.el("span", { class: "k" }, label));
      const v = A.el("span", { class: "v" }, fmt(m[key]));
      const r = ragKey && rag(ragKey, m[key]); if (r) v.style.color = `var(--${r}-ink)`;
      d.append(v, A.el("span", { class: "vs" }, `cohort median ${fmt(med(key))}`));
      kp.append(d);
    };
    k("Focus min / day", "focus", (v) => A.dec(v, 0), "focus");
    k("Focus sessions finished", "focusDone", (v) => A.pct(v));
    k("Timetable adherence", "adherence", (v) => A.pct(v));
    k("Quiz participation", "quiz", (v) => A.pct(v), "quiz");
    k("Quiz score", "quizScore", (v) => A.dec(v, 0));
    k("Tasks on time", "onTime", (v) => A.pct(v), "onTime");
    k("Time estimate accuracy", "est", (v) => A.pct(v), "est");
    k("Syllabus pace", "pace", (v) => A.pct(v), "pace");
    k("Chapter readiness", "ready", (v) => A.dec(v, 0), "ready");
    k("Session attendance", "attend", (v) => A.pct(v), "attend");
    k("Milestones on time", "milestones", (v) => A.pct(v));
    if (m.sleep != null) { k("Sleep", "sleep", (v) => A.dec(v, 1) + "h", "sleep"); k("Active minutes", "active", (v) => A.dec(v, 0)); k("Recovery", "recovery", (v) => A.dec(v, 0) + "%"); }
    top.append(who, kp);
    host.append(top);

    // subjects
    const end = R.end > AS_OF ? AS_OF : R.end;
    const qn = quarterNow(end);
    const subRows = (subjBy[selected.student_id] || []).map((sub) => {
      const chs = chapBySubj[sub.subject_id] || [];
      const tops = chs.map((ch) => ({ q: Number(ch.planned_quarter), top: Math.max(0, ...(stageByCh[ch.chapter_id] || []).filter((e) => e.reached_on <= end).map((e) => Number(e.stage))) }));
      const dueC = tops.filter((t) => t.q < qn);
      const res = (et) => { const r = results.find((x) => x.subject_id === sub.subject_id && x.exam_type === et && x.exam_date <= end); const t = targets.find((x) => x.subject_id === sub.subject_id && x.exam_type === et); return { r: r ? Number(r.score_pct) : null, t: t ? Number(t.target_pct) : null, aligned: t && t.parent_aligned_on }; };
      const ut = res("unit_test"), hy = res("half_yearly");
      return { name: sub.name, affinity: sub.affinity, tutor: bool(sub.has_tutor), due: dueC.length, ready: A.avg(dueC, (t) => t.top * 20), done5: dueC.filter((t) => t.top === 5).length, ut, hy, gap: hy.r != null ? hy.r - hy.t : ut.r != null ? ut.r - ut.t : null };
    });
    const sc = A.el("div", { class: "card" });
    sc.append(A.el("h3", {}, "Subjects"), A.el("p", { class: "sub" }, "Readiness = average furthest rigour step × 20 for chapters planned in finished quarters. A gap of 10+ points below target for two exams triggers tutor support."));
    const t1 = A.el("div", { class: "tbl" }); sc.append(t1); host.append(sc);
    const ex = (o) => (o.r == null ? "-" : `${A.dec(o.r, 0)} / ${A.dec(o.t, 0)}`);
    A.renderTable(t1, [
      { key: "name", label: "Subject" },
      { key: "affinity", label: "Affinity" },
      { key: "tutor", label: "Tutor", fmt: (v) => (v ? "Yes" : "No") },
      { key: "ready", label: "Readiness", num: true, fmt: (v) => cell("ready", v, A.dec(v, 0)) },
      { key: "done5", label: "Exam-ready", num: true, fmt: (v, r) => `${v} of ${r.due}` },
      { key: "ut", label: "Unit test / target", num: true, sort: (r) => r.ut.r, fmt: (v) => ex(v) },
      { key: "hy", label: "Half-yearly / target", num: true, sort: (r) => r.hy.r, fmt: (v) => ex(v) },
      { key: "gap", label: "Latest gap", num: true, fmt: (v) => cell("gap", v, (v >= 0 ? "+" : "") + A.dec(v, 1)) },
      { key: "action", label: "Advisor action", sort: (r) => r.gap, cls: "wrap", fmt: (v, r) => r.gap != null && r.gap <= -10 ? (r.tutor ? "Tutor already in place: share chapter readiness with tutor" : "Trigger tutor support (deviation > 10 pts)") : r.ready != null && r.ready < 40 ? "Monthly sprint: finish practice step on overdue chapters" : "On plan" },
    ], subRows, { sortKey: "gap", sortDir: "asc" });

    // milestones + escalations
    const ms = (miles[selected.student_id] || []).filter((x) => x.due_on <= A.addDays(end, 30)).sort((a, b) => (a.due_on < b.due_on ? 1 : -1)).slice(0, 8);
    const c2 = A.el("div", { class: "card span-6" }); c2.style.gridColumn = "span 6";
    c2.append(A.el("h3", {}, "Roadmap milestones"), A.el("p", { class: "sub" }, "Career (done / not done), personal and academic monthly milestones"));
    const t2 = A.el("div", { class: "tbl" }); c2.append(t2);
    A.renderTable(t2, [
      { key: "roadmap", label: "Roadmap" }, { key: "title", label: "Milestone", cls: "wrap" }, { key: "due_on", label: "Due", fmt: (v) => A.dateLabel(v) },
      { key: "done_on", label: "Status", sort: (r) => r.done_on || "", fmt: (v, r) => v ? (v <= r.due_on ? A.pill("good", "DONE") : A.pill("warn", "DONE LATE")) : r.due_on > end ? A.pill("neutral", "UPCOMING") : A.pill("critical", "MISSED") },
    ], ms, { sortKey: "due_on" });
    const es = esc.filter((x) => x.student_id === selected.student_id && x.triggered_on >= R.start && x.triggered_on <= end).sort((a, b) => (a.triggered_on < b.triggered_on ? 1 : -1)).slice(0, 8);
    const c3 = A.el("div", { class: "card span-6" }); c3.style.gridColumn = "span 6";
    c3.append(A.el("h3", {}, "Automated nudges in range"), A.el("p", { class: "sub" }, "What n8n sent, to whom, and whether it worked"));
    const t3 = A.el("div", { class: "tbl" }); c3.append(t3);
    const RULE = { task_overdue: "Task overdue 2 days", quiz_missed_3d: "Missed quiz 3 days", no_focus_3d: "No focus session 3 days", syllabus_behind: "Syllabus behind", readiness_gap: "Readiness gap" };
    A.renderTable(t3, [
      { key: "triggered_on", label: "Date", fmt: (v) => A.dateLabel(v) }, { key: "rule", label: "Trigger", fmt: (v) => RULE[v] || v }, { key: "notified", label: "Sent to" },
      { key: "resolved_on", label: "Outcome", sort: (r) => r.resolved_on || "", fmt: (v, r) => v ? A.pill("good", `FIXED IN ${A.diffDays(r.triggered_on, v)}D`) : A.pill("serious", "OPEN") },
    ], es, { sortKey: "triggered_on", empty: "No nudges fired in this range." });
    host.append(c2, c3);
    if (matchMedia("(max-width: 960px)").matches) { c2.style.gridColumn = "span 12"; c3.style.gridColumn = "span 12"; }
  }

  // ---------- advisor inputs ----------
  function advisorInputs(all) {
    const end = R.end > AS_OF ? AS_OF : R.end;
    const rows = Object.entries(advisors).map(([id, name]) => {
      const ss = students.filter((s) => s.advisor_id === id);
      const ids = new Set(ss.map((s) => s.student_id));
      const tg = targets.filter((t) => ids.has(t.student_id));
      const logging = ss.filter((s) => stageEv.some((e) => studentOfSubj[subjOfChapter[e.chapter_id]] === s.student_id && e.reached_on > A.addDays(end, -7) && e.reached_on <= end)).length;
      const ms = all.filter((m) => ids.has(m.s.student_id));
      const acad = parts.filter((p) => ids.has(p.student_id) && p.act.kind === "academic_session" && p.act.conducted_on >= R.start && p.act.conducted_on <= end && p.rating != null);
      return { name, n: ss.length, aligned: tg.filter((t) => t.parent_aligned_on).length / Math.max(1, tg.length), logging: logging / Math.max(1, ss.length),
        risk: ms.filter((m) => flags(m).status === "critical").length, rating: A.avg(acad, (p) => p.rating) };
    });
    A.renderTable(document.getElementById("t-adv"), [
      { key: "name", label: "Advisor" }, { key: "n", label: "Students", num: true },
      { key: "aligned", label: "Targets agreed with parents", num: true, fmt: (v) => A.pill(v >= 0.95 ? "good" : v >= 0.8 ? "warn" : "critical", A.pct(v)) },
      { key: "logging", label: "Logged chapters this week", num: true, fmt: (v) => A.pill(v >= 0.9 ? "good" : v >= 0.7 ? "warn" : "critical", A.pct(v)) },
      { key: "rating", label: "Session rating", num: true, fmt: (v) => A.dec(v, 2) },
      { key: "risk", label: "At risk", num: true },
    ], rows, { sortKey: "name", sortDir: "asc" });

    const ids = new Set(selStudents().map((s) => s.student_id));
    const es = esc.filter((x) => ids.has(x.student_id) && x.triggered_on >= R.start && x.triggered_on <= end);
    const RULE = { task_overdue: "Task overdue 2 days", quiz_missed_3d: "Missed quiz 3 days in a row", no_focus_3d: "No focus session for 3 days" };
    const er = Object.entries(A.groupBy(es, (x) => x.rule + "|" + x.notified)).map(([k, xs]) => {
      const [rule, to] = k.split("|"); const res = xs.filter((x) => x.resolved_on);
      return { rule: RULE[rule] || rule, to, fired: xs.length, resolved: res.length / xs.length, days: A.avg(res, (x) => A.diffDays(x.triggered_on, x.resolved_on)) };
    });
    A.renderTable(document.getElementById("t-esc"), [
      { key: "rule", label: "Trigger", cls: "wrap" }, { key: "to", label: "Sent to" }, { key: "fired", label: "Fired", num: true },
      { key: "resolved", label: "Resolved", num: true, fmt: (v) => A.barCell(v, 1, null, v >= 0.6 ? "var(--s3)" : "var(--serious)") },
      { key: "resolvedPct", label: "", num: true, sort: (r) => r.resolved, fmt: (v, r) => A.pct(r.resolved) },
      { key: "days", label: "Days to fix", num: true, fmt: (v) => A.dec(v, 1) },
    ], er, { sortKey: "fired", empty: "No escalations fired in this range." });
    const parentRes = er.filter((r) => r.to === "parent"), stuRes = er.filter((r) => r.to === "student" && r.rule.startsWith("Task"));
    if (parentRes.length && stuRes.length) document.getElementById("t-esc").append(A.el("p", { class: "note" },
      `Overdue-task nudges to parents resolve ${A.pct(parentRes[0].resolved)} of the time vs ${A.pct(stuRes[0].resolved)} for nudges to students. This is the number that decides whether parent escalation is worth the friction.`));
  }

  // ---------- wiring ----------
  function renderAll() {
    const all = selStudents().map((s) => metrics(s, R));
    lenses(all); quantity(); quality(); scorecard(all); trends(all); stagesTable(all); drill(); advisorInputs(all);
  }
  const sel = document.getElementById("advisor");
  for (const [id, name] of Object.entries(advisors)) sel.append(A.el("option", { value: id }, name));
  advisor = A.mem.get("alc-stu-adv", ""); sel.value = advisor;
  sel.addEventListener("change", () => { advisor = sel.value; A.mem.set("alc-stu-adv", advisor); selected = null; renderAll(); });
  A.rangeControl(document.getElementById("filters"), { asOf: AS_OF, minDate: D.start, key: "alc-stu-range", defaultPreset: "last_30", onChange: (r) => { R = r; renderAll(); } });
  A.onTheme(() => R && renderAll());
})();
