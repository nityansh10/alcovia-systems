# Alcovia · Product, Systems & Analytics Lead assignment

| | |
|---|---|
| **Executive write-up** | [docs/EXECUTIVE_WRITEUP.md](docs/EXECUTIVE_WRITEUP.md) |
| **GTM tracker (live)** | https://nityansh10.github.io/alcovia-systems/dashboards/gtm/ |
| **Student progress board (live)** | https://nityansh10.github.io/alcovia-systems/dashboards/student/ |

## What is in here

```
docs/
  EXECUTIVE_WRITEUP.md            approach, sequencing, team plan (Nov-Jan), summary of all four problems
  01_app_adoption.md              Problem 1: why 2.15 min, where 30 min can come from, the bets, how to test at n=20
  02_gtm_tracker.md               Problem 2: metric definitions and RCA rules
  03_delivery_operating_system.md Problem 3: bet -> frame -> shape -> build -> pilot -> prove -> operate
  04_student_dashboard.md         Problem 4: KPI catalogue in three lenses, capture plan, surfaces, timeline
  05_systems_and_data_flow.md     architecture, the "doesn't break" rules, runbooks
sql/
  schema/   01_gtm · 02_student · 03_app_events · 04_ops       (Postgres / Supabase)
  metrics/  10 revenue · 20 funnel · 30 campaigns + RCA · 40 student KPIs · 50 app adoption
n8n/
  build_workflows.py              generates the exports and enforces the reliability rules
  workflows/00-09_*.json          import into n8n: Workflows > Import from file
data/
  generate_seed.py                realistic dummy data (funnel timing, ad fatigue, renewals, rigour gates)
  run_metrics.py                  loads schema + seed into DuckDB and runs every query
  metric_snapshot.md              output of the last run
  seed/*.csv                      the dummy data
dashboards/
  gtm/  student/  assets/         static HTML + Chart.js, no build step
```

## Reproduce

```bash
pip install duckdb
python data/generate_seed.py      # writes data/seed/*.csv and dashboards/*/data.js
python data/run_metrics.py        # runs all 26 queries; non-zero exit if any fails
python n8n/build_workflows.py     # regenerates n8n/workflows/*.json
# open dashboards/index.html in a browser
```

The SQL is written in Postgres dialect so it runs unchanged on Supabase, and is tested on DuckDB. Placeholders `{{start_date}}`, `{{end_date}}` and `{{as_of}}` map to the dashboard date picker (in Metabase they become filter variables).

## Notes

- All dashboard data is dummy. The Mixpanel replica (`app_events`) is built to reproduce the figures in the brief, so `50_app_adoption.sql` can be checked against the real Mixpanel project.
- Event names in `event_feature_map` (e.g. `focus_session_completed`, `quiz_summary_viewed`, `territory_map_viewed`) come from the current Android build. The app (Expo / React Native, Mixpanel, Sentry) already fires them.
- Assumed prices: 3-month trial ₹45,000, full program ₹1,80,000, workshop seat ₹3,999 (given).
