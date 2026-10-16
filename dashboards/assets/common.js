/* Alcovia dashboards - shared helpers (no build step, no framework).
   Dates are ISO strings throughout: 'YYYY-MM-DD' compares correctly as text. */
(function () {
  const A = (window.Alc = {});

  // ---------- data ----------
  A.table = (data, name) => {
    const t = data.tables[name];
    return t.rows.map((r) => Object.fromEntries(t.cols.map((c, i) => [c, r[i]])));
  };
  A.day = (ts) => (ts ? ts.slice(0, 10) : null);
  A.within = (d, r) => d != null && d >= r.start && d <= r.end;
  A.addDays = (iso, n) => {
    const d = new Date(iso + "T00:00:00Z");
    d.setUTCDate(d.getUTCDate() + n);
    return d.toISOString().slice(0, 10);
  };
  A.diffDays = (a, b) => Math.round((new Date(b + "T00:00:00Z") - new Date(a + "T00:00:00Z")) / 86400000);
  A.monthStart = (iso) => iso.slice(0, 8) + "01";
  A.monthEnd = (iso) => { const m = A.monthStart(iso); const d = new Date(m + "T00:00:00Z"); d.setUTCMonth(d.getUTCMonth() + 1); d.setUTCDate(0); return d.toISOString().slice(0, 10); };
  A.months = (r) => { const out = []; let m = A.monthStart(r.start); while (m <= r.end) { out.push(m); m = A.addDays(A.monthEnd(m), 1); } return out; };
  A.weekStart = (iso) => { const d = new Date(iso + "T00:00:00Z"); const wd = (d.getUTCDay() + 6) % 7; return A.addDays(iso, -wd); };
  A.sum = (a, f = (x) => x) => a.reduce((s, x) => s + (Number(f(x)) || 0), 0);
  A.avg = (a, f = (x) => x) => { const v = a.map(f).filter((x) => x != null && !Number.isNaN(Number(x))); return v.length ? A.sum(v) / v.length : null; };
  A.groupBy = (a, f) => a.reduce((m, x) => { const k = f(x); (m[k] ||= []).push(x); return m; }, {});
  A.median = (a) => { const v = a.filter((x) => x != null).sort((x, y) => x - y); if (!v.length) return null; const h = v.length >> 1; return v.length % 2 ? v[h] : (v[h - 1] + v[h]) / 2; };

  // ---------- formatting ----------
  A.inr = (v, exact) => {
    if (v == null || Number.isNaN(v)) return "-";
    const n = Math.abs(v), s = v < 0 ? "-" : "";
    if (exact) return s + "₹" + Math.round(n).toLocaleString("en-IN");
    if (n >= 1e7) return s + "₹" + (n / 1e7).toFixed(2) + " Cr";
    if (n >= 1e5) return s + "₹" + (n / 1e5).toFixed(1) + " L";
    if (n >= 1e3) return s + "₹" + (n / 1e3).toFixed(1) + "k";
    return s + "₹" + Math.round(n);
  };
  A.int = (v) => (v == null || Number.isNaN(v) ? "-" : Math.round(v).toLocaleString("en-IN"));
  A.pct = (v, d = 0) => (v == null || !Number.isFinite(v) ? "-" : (v * 100).toFixed(d) + "%");
  A.dec = (v, d = 1) => (v == null || !Number.isFinite(v) ? "-" : Number(v).toFixed(d));
  A.dateLabel = (iso) => new Date(iso + "T00:00:00Z").toLocaleDateString("en-IN", { day: "numeric", month: "short", timeZone: "UTC" });
  A.monthLabel = (iso) => new Date(iso + "T00:00:00Z").toLocaleDateString("en-IN", { month: "short", year: "2-digit", timeZone: "UTC" });
  A.el = (tag, attrs = {}, text) => { const e = document.createElement(tag); for (const [k, v] of Object.entries(attrs)) { if (k === "class") e.className = v; else e.setAttribute(k, v); } if (text != null) e.textContent = text; return e; };
  A.pill = (kind, label) => { const s = A.el("span", { class: "pill " + kind }, label); return s; };

  // ---------- local per-viewer memory (optional) ----------
  A.mem = {
    get(k, d) { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : d; } catch { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* storage blocked: fine */ } },
  };

  // ---------- date range control ----------
  // presets are relative to the data's as-of date, so the dummy data always has a full view
  A.rangeControl = (host, { asOf, minDate, key, onChange, defaultPreset = "last_month" }) => {
    const presets = [
      ["this_month", "This month", () => ({ start: A.monthStart(asOf), end: asOf })],
      ["last_month", "Last month", () => { const e = A.addDays(A.monthStart(asOf), -1); return { start: A.monthStart(e), end: e }; }],
      ["last_30", "Last 30 days", () => ({ start: A.addDays(asOf, -29), end: asOf })],
      ["last_90", "Last 90 days", () => ({ start: A.addDays(asOf, -89), end: asOf })],
      ["qtd", "Quarter to date", () => { const m = Number(asOf.slice(5, 7)); const qm = String(m - ((m - 1) % 3)).padStart(2, "0"); return { start: asOf.slice(0, 5) + qm + "-01", end: asOf }; }],
      ["fytd", "FY to date", () => ({ start: minDate, end: asOf })],
    ];
    const seg = A.el("div", { class: "seg", role: "group", "aria-label": "Date range" });
    const custom = A.el("div", { class: "custom" });
    const from = A.el("input", { type: "date", id: key + "-from", min: minDate, max: asOf, "aria-label": "From date" });
    const to = A.el("input", { type: "date", id: key + "-to", min: minDate, max: asOf, "aria-label": "To date" });
    custom.append(from, A.el("span", {}, "to"), to);
    const label = A.el("div", { class: "rangelabel" });
    host.append(seg, custom, label);

    let state = A.mem.get(key, { preset: defaultPreset });
    const resolve = () => {
      if (state.preset === "custom" && state.start && state.end) return { start: state.start, end: state.end, preset: "custom", label: "Custom" };
      const p = presets.find((x) => x[0] === state.preset) || presets[1];
      return { ...p[2](), preset: p[0], label: p[1] };
    };
    const apply = () => {
      const r = resolve();
      for (const b of seg.children) b.setAttribute("aria-pressed", String(b.dataset.p === r.preset));
      from.value = r.start; to.value = r.end;
      label.replaceChildren(A.el("b", {}, r.label), document.createTextNode(` · ${A.dateLabel(r.start)} - ${A.dateLabel(r.end)} ${r.end.slice(0, 4)} · ${A.diffDays(r.start, r.end) + 1} days · data through ${A.dateLabel(asOf)}`));
      A.mem.set(key, state);
      onChange(r);
    };
    for (const [id, name] of presets) {
      const b = A.el("button", { type: "button", "data-p": id }, name);
      b.addEventListener("click", () => { state = { preset: id }; apply(); });
      seg.append(b);
    }
    const onCustom = () => {
      if (!from.value || !to.value) return;
      let [s, e] = [from.value, to.value];
      if (s > e) [s, e] = [e, s];
      state = { preset: "custom", start: s < minDate ? minDate : s, end: e > asOf ? asOf : e };
      apply();
    };
    from.addEventListener("change", onCustom); to.addEventListener("change", onCustom);
    apply();
  };

  // ---------- sortable table ----------
  // cols: [{key, label, num?, fmt?(v,row) -> string|Node, sort?(row) -> value}]
  A.renderTable = (host, cols, rows, { sortKey, sortDir = "desc", limit, empty = "No rows in this range." } = {}) => {
    host.replaceChildren();
    if (!rows.length) { host.append(A.el("div", { class: "empty" }, empty)); return; }
    let key = sortKey, dir = sortDir;
    const tbl = A.el("table"), thead = A.el("thead"), tbody = A.el("tbody"), hr = A.el("tr");
    const val = (c, r) => (c.sort ? c.sort(r) : r[c.key]);
    const draw = () => {
      const sorted = key ? [...rows].sort((a, b) => {
        const c = cols.find((x) => x.key === key); const x = val(c, a), y = val(c, b);
        if (x == null) return 1; if (y == null) return -1;
        return (x < y ? -1 : x > y ? 1 : 0) * (dir === "asc" ? 1 : -1);
      }) : rows;
      tbody.replaceChildren();
      for (const r of limit ? sorted.slice(0, limit) : sorted) {
        const tr = A.el("tr");
        for (const c of cols) {
          const td = A.el("td", { class: (c.num ? "n " : "") + (c.cls || "") });
          const v = c.fmt ? c.fmt(r[c.key], r) : r[c.key];
          if (v instanceof Node) td.append(v); else td.textContent = v == null ? "-" : v;
          tr.append(td);
        }
        tbody.append(tr);
      }
      for (const th of hr.children) th.setAttribute("aria-sort", th.dataset.k === key ? (dir === "asc" ? "ascending" : "descending") : "none");
    };
    for (const c of cols) {
      const th = A.el("th", { class: c.num ? "n" : "", tabindex: "0", "data-k": c.key, scope: "col" }, c.label);
      const go = () => { if (key === c.key) dir = dir === "asc" ? "desc" : "asc"; else { key = c.key; dir = c.num ? "desc" : "asc"; } draw(); };
      th.addEventListener("click", go);
      th.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } });
      hr.append(th);
    }
    thead.append(hr); tbl.append(thead, tbody); host.append(tbl); draw();
  };

  // inline bar with an optional target tick
  A.barCell = (value, max, target, color) => {
    const w = A.el("div", { class: "bar-cell" });
    const tr = A.el("div", { class: "track" });
    const i = A.el("i"); i.style.width = Math.max(0, Math.min(100, (value / (max || 1)) * 100)) + "%";
    if (color) i.style.background = color;
    tr.append(i);
    if (target != null) { const b = A.el("b"); b.style.left = Math.min(100, (target / (max || 1)) * 100) + "%"; tr.append(b); }
    w.append(tr);
    return w;
  };

  // ---------- charts (Chart.js, themed from CSS tokens) ----------
  const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  A.color = css;
  const charts = new Map();
  A.chart = (canvasId, config) => {
    const cv = document.getElementById(canvasId);
    if (!cv || !window.Chart) return;
    if (charts.has(canvasId)) charts.get(canvasId).destroy();
    const ink2 = css("--ink-2"), line = css("--line"), muted = css("--muted");
    Chart.defaults.font.family = css("--font-ui");
    Chart.defaults.font.size = 12;
    Chart.defaults.color = muted;
    const base = {
      responsive: true, maintainAspectRatio: false, animation: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: css("--surface"), titleColor: css("--ink"), bodyColor: ink2, borderColor: line, borderWidth: 1,
          padding: 10, boxPadding: 4, usePointStyle: true, titleFont: { weight: "600" },
          bodyFont: { family: css("--font-num") },
        },
      },
      scales: {},
    };
    for (const ax of ["x", "y"]) {
      base.scales[ax] = { grid: { color: line, drawTicks: false }, border: { color: line }, ticks: { color: muted, padding: 6 } };
    }
    base.scales.x.grid.display = false;
    const merged = deepMerge(base, config.options || {});
    charts.set(canvasId, new Chart(cv, { ...config, options: merged }));
  };
  function deepMerge(a, b) {
    const o = Array.isArray(a) ? [...a] : { ...a };
    for (const [k, v] of Object.entries(b)) o[k] = v && typeof v === "object" && !Array.isArray(v) && a[k] && typeof a[k] === "object" ? deepMerge(a[k], v) : v;
    return o;
  }
  A.barStyle = { borderRadius: 4, borderSkipped: "start", maxBarThickness: 28, categoryPercentage: 0.72, barPercentage: 0.9 };
  A.onTheme = (fn) => {
    try { matchMedia("(prefers-color-scheme: dark)").addEventListener("change", fn); } catch { /* old browsers */ }
    new MutationObserver(fn).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  };
})();
