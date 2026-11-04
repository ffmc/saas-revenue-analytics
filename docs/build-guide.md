# Build guide

The path from raw tables to a CFO dashboard with AI Q&A. Phases 0–1 are done for you; from phase 2 on, you build. Each phase lists what to learn first, the tasks, the traps, a check you can run, and what you'll say about it in an interview.

At 8 h/week the whole guide is about 10 weeks. Keep the SQL drills and error log from `job-hunting/Context/Study Plan - Analytics Engineer.md` running alongside; the SQL topics below say which week's drills pay off where.

Read `brief.md`, `metrics.md` and `source-data.md` before phase 2. They are the requirements.

---

## Phase 0 — Snowflake account and setup (done for you, 1 h to run)
**Goal:** a Snowflake account with role-based access, ready to load.

**Tasks**
1. Create a Snowflake trial: Enterprise edition, AWS. Before choosing the region, check that Cortex Analyst is available there (Snowflake docs, "Cortex Analyst" > availability), because phase 10 needs it.
2. Generate two key pairs (README has the commands) and run `snowflake/setup.sql` in a Snowsight worksheet.
3. Read `setup.sql` top to bottom until you can explain every block.

**Done when:** `SHOW GRANTS TO ROLE TRANSFORMER` lists SELECT on RAW tables and CREATE SCHEMA on SILVER and GOLD.

**Interview talking point:** "I separated loading, transforming and reporting into three roles with their own warehouses, so I could see the cost of each and nobody reads raw data from a dashboard. Service users authenticate with key pairs, and a resource monitor suspends warehouses at the credit cap."

## Phase 1 — Raw load (done for you, 1 h to run)
**Goal:** all raw tables populated.

**Tasks:** follow the README quickstart: simulator backfill, ECB backfill, `load.py`. Then explore in Snowsight: `SELECT RAW FROM RAW.STRIPE.SUBSCRIPTIONS LIMIT 20`, and click into the JSON.

**Done when:** the row-count query in the README returns non-zero counts for every table.

**Interview talking point:** "Raw lands as VARIANT exactly as delivered, with the file name and row number. Re-running the load is safe because COPY INTO skips files it has already loaded."

---

## Phase 2 — dbt project and sources (week 1, ~5 h)
**Goal:** a dbt project connected to Snowflake, with every raw table declared as a source.

**Learn first**
- dbt project structure: https://docs.getdbt.com/best-practices/how-we-structure/1-guide-overview
- Sources and freshness: https://docs.getdbt.com/docs/build/sources

**Tasks**
1. `pip install dbt-core dbt-snowflake` in the project venv; `dbt init fieldnote` inside a `dbt/` folder.
2. `profiles.yml` with two targets. `dev`: your own user, role TRANSFORMER, schema `DEV_<YOURNAME>`. `ci`: DBT_USER with key-pair auth, schema `CI`. Keep `profiles.yml` out of git.
3. Folders: `models/staging/stripe`, `models/staging/segment`, `models/staging/ecb`, `models/intermediate`, `models/marts`.
4. `_stripe__sources.yml` etc. declaring every RAW table, with descriptions copied from `source-data.md`.
5. Freshness on `_LOADED_AT` (warn after 1 day, error after 2) for Stripe and Segment.
6. Install `dbt_utils` via `packages.yml`.

**Traps**
- Snowflake uppercases unquoted identifiers. Write source names in lowercase in YAML and let dbt handle the case.
- Freshness on `_LOADED_AT` measures the pipeline, not the data. Say so in the description.

**Done when:** `dbt debug` passes and `dbt source freshness` runs.

**Interview talking point:** "Sources are documented with the quirks of each feed, so the next person knows about the schema change before they hit it."

## Phase 3 — Staging (weeks 1–2, ~10 h)
**Goal:** one clean, typed, deduplicated model per source object. No business logic.

**Learn first**
- Snowflake semi-structured data: `:` path syntax, `::` casts, `LATERAL FLATTEN`: https://docs.snowflake.com/en/sql-reference/functions/flatten
- SQL drills, weeks 1–2: `ROW_NUMBER`, `QUALIFY`, dedup.

**Tasks**
1. `stg_stripe__customers`, `stg_stripe__subscriptions`, `stg_stripe__invoices`, `stg_stripe__charges`, `stg_stripe__refunds`, `stg_stripe__prices`, `stg_stripe__products`, `stg_stripe__coupons`.
   - Keep the full history: one row per object per delivery, with a `delivered_on` date parsed from `_FILE`.
   - Remove exact duplicates (same id, same delivery date).
   - Cast cents to amounts (write a `cents_to_amount` macro), and Unix seconds to `TIMESTAMP_TZ`.
2. Flatten nested lists into their own models: `stg_stripe__subscription_items` (from `items.data`) and `stg_stripe__invoice_lines` (from `lines.data`).
3. `stg_segment__tracks`: dedup on `messageId`; keep both `event_at` (`timestamp`) and `received_at`; pull `context.groupId` out as `workspace_id`.
4. `stg_ecb__rates`: one row per currency and date (dedup across overlapping files); cast `OBS_VALUE` to a number.
5. Handle the 2025-06-01 schema change in `stg_stripe__customers` with `COALESCE` of the old and new keys into one `acquisition_channel` column.
6. Tests: `not_null` on ids, `accepted_values` on statuses and currencies, and a `unique` test on the dedup grain (id + delivered_on).

**Traps**
- Order history by `delivered_on` then `_FILE_ROW`, never by `_LOADED_AT` (see source-data.md).
- A customer's channel lives under two different keys depending on when the record was delivered. If you only read the new key, every customer who never changed after June 2025 has a NULL channel.
- Stripe currency is lowercase and ECB is uppercase. Pick one in staging.

**Done when:** `dbt build -s staging` is green, and a query shows zero customers with a NULL channel.

**Interview talking point:** "Staging keeps the full delivery history because the source re-sends full objects on change. Deciding the current state is a modeling decision, so it doesn't happen in staging."

## Phase 4 — Subscription history (week 3, ~6 h)
**Goal:** SCD Type 2 history of every subscription: what plan, seats, price and status it had on any date.

**Learn first**
- Kimball slowly changing dimensions (Type 2).
- dbt snapshots: https://docs.getdbt.com/docs/build/snapshots
- SQL drill, week 3: `LEAD`/`LAG`, gaps and islands.

**Tasks**
1. `int_subscriptions__history`: from staging, take one state per subscription per delivery date and add `valid_from = delivered_on` and `valid_to = LEAD(delivered_on)` (NULL for the current row). Join the item for price, quantity and interval.
2. Collapse consecutive rows where nothing relevant changed (status, price, quantity, discount): a gaps-and-islands exercise.
3. Write a custom generic test, `contiguous_ranges`, that fails if any subscription's `valid_to` doesn't equal its next row's `valid_from`.
4. **Snapshot exercise:** add a dbt snapshot on `stg_stripe__prices` (check strategy on `active` and `unit_amount`). Then write down why it isn't the main history mechanism here.

**Traps**
- The raw feed already contains history, because objects are re-delivered on change. A dbt snapshot only records what it sees each time it runs, so on a backfill it would capture just one state per subscription. Building history from the deliveries is the right call; know why.
- State is end of day: a subscription delivered on 2025-03-14 is in that state for the rest of that day.

**Done when:** for one subscription you pick by hand, the history rows tell its full story (trial, active, upgrade, past_due, canceled), and `contiguous_ranges` passes.

**Interview talking point:** "I didn't use a snapshot for subscriptions, because the extract already re-delivers full state on every change, and a snapshot would miss everything before its first run. I built SCD2 from delivery history and used a snapshot only where a source overwrites in place."

## Phase 5 — MRR spine and movements (weeks 3–4, ~10 h)
**Goal:** the core of the project. MRR per customer per month end, and the movement classification.

**Learn first**
- `metrics.md`, every word of the MRR section.
- SQL drill, week 4: date spines, cohorts.

**Tasks**
1. `int_month_ends`: one row per month end from 2024-01 to the last complete month (`dbt_utils.date_spine` or a generator).
2. `int_customer_mrr__monthly`: join the month ends to `int_subscriptions__history` where the month end falls inside `[valid_from, valid_to)`. Apply the MRR rules: status filter, annual / 12, discount active at month end, round per customer.
3. Densify: customers need a row with MRR 0 in months after they churn, or you can't detect churn. Build the customer × month grid from first paid month to the last month.
4. `int_mrr_movements`: compare with `LAG(mrr)`. Classify new, reactivation, expansion, contraction, churn, retained. Reactivation needs "had MRR at any earlier month" (a running `MAX` over previous rows).
5. `int_fx__month_end_rates`: for each month end and currency, the last ECB rate on or before that date. Weekends and 1 January have no rate.

**Traps**
- Annual plans: MRR is the yearly amount / 12, every month. Don't put the annual invoice into one month.
- Past-due subscriptions still count. Trialing ones don't.
- The `WELCOME20` discount starts at subscription creation, during the trial, so a customer may get only 2 months of it after paying.
- Grandfathered prices: use the price on the subscription item, not the current list price.
- A customer can churn and come back on a new subscription id. MRR is per customer, not per subscription.

**Done when:** for every month, `start MRR + new + reactivation + expansion − contraction − churn = end MRR` in native currency (write it as a query first; it becomes a test in phase 7).

**Interview talking point:** "MRR is a point-in-time measure, so I built a customer × month-end spine from SCD2 subscription history instead of summing invoices. Invoices answer a different question: cash. And I densified to zero after churn, because you can't classify churn from rows that don't exist."

## Phase 6 — Marts (week 5, ~8 h)
**Goal:** the star schema the dashboard and semantic layer read.

**Learn first**
- Kimball: grain, fact table types, conformed dimensions.
- Incremental models: https://docs.getdbt.com/docs/build/incremental-models

**Tasks**
1. Dimensions:
   - `dim_customers`: country, currency, acquisition channel, signup date, cohort month, activation flag (from Segment, rules in metrics.md), current plan.
   - `dim_plans` and `dim_dates`.
2. Facts:
   - `fct_mrr_monthly`: grain customer × month end. Native MRR, EUR MRR at that month's rate, movement, movement amount.
   - `fct_invoices`: grain invoice, latest state.
   - `fct_payment_attempts`: grain charge, with a first-attempt flag and recovered flag.
   - `fct_product_events`: grain event, **incremental** with merge on `message_id` and a 3-day lookback on `received_at` for late events.
3. Reporting marts: `mart_mrr_bridge` (grain month), `mart_cohort_retention` (grain cohort × months since start: logo, GRR and NRR in constant currency), `mart_trial_funnel`.
4. Write the grain in every model's YAML description.
5. Materializations: staging as views, intermediate as ephemeral or views, marts as tables, events incremental.

**Traps**
- Activation joins Segment to Stripe through `workspace_id`, not a Stripe id.
- The incremental lookback must use `received_at`, not `event_at`, or late events never arrive.
- Constant currency for NRR and GRR: convert both months at the later month's rate.

**Done when:** `dbt build` is green and the trial funnel shows about 15% conversion for unactivated and about 50% for activated accounts.

**Interview talking point:** "The events fact is incremental with a three-day lookback on received time, because about 3% of events arrive late; partitioning by event time would silently drop them."

## Phase 7 — Tests and reconciliation (week 6, ~6 h)
**Goal:** the pipeline stops itself before showing wrong numbers.

**Learn first:** data tests, generic and singular: https://docs.getdbt.com/docs/build/data-tests

**Tasks**
1. Generic tests on every mart: `unique` and `not_null` on keys, `relationships` from facts to dimensions, `accepted_values` on movement.
2. `dbt_utils.expression_is_true`: MRR ≥ 0; EUR MRR ≥ 0.
3. Singular test `assert_mrr_bridge_closes`: the phase 5 query; fails on any month where the bridge is off by more than 0.01.
4. Singular test `assert_mrr_matches_ground_truth`: compare `fct_mrr_monthly` (native currency) with `RAW.GROUND_TRUTH.MRR_MONTHLY`, joined on month and customer, full outer join. It fails on any difference. Declare the ground truth as a source, and use it **only** here.
5. Test severity: the ground-truth test is `error`; volume anomalies can be `warn`.

**Traps**
- A full outer join is essential: missing customers on either side are failures too.
- If the reconciliation fails, the bug is almost always in one of the phase 5 traps. Pick one failing customer and trace their raw subscription history by hand.

**Done when:** `dbt build` is green including both singular tests, and you broke something on purpose (for example, remove the discount logic) to watch the reconciliation test fail.

**Interview talking point:** "MRR reconciles to the cent against an independent answer key every run. When I removed the discount logic on purpose, the test caught it immediately, which is how I know the test works."

## Phase 8 — Documentation and grants (week 6, ~3 h)
**Goal:** a docs site someone else can navigate, and production access controlled by dbt.

**Learn first:** exposures (https://docs.getdbt.com/docs/build/exposures) and grants (https://docs.getdbt.com/reference/resource-configs/grants).

**Tasks**
1. Descriptions for every mart model and column; reuse long ones with doc blocks (`{% docs %}`).
2. An exposure for the Streamlit app (phase 10) listing the marts it reads.
3. `+grants: {select: ['REPORTER']}` on marts in `dbt_project.yml`.
4. `dbt docs generate` and `dbt docs serve`; screenshot the lineage graph for the README.

**Done when:** the lineage graph shows sources → staging → intermediate → marts → exposure, and REPORTER can select from a mart.

## Phase 9 — Semantic layer (week 7, ~8 h)
**Goal:** every metric in `metrics.md` defined once, in code, for both the dashboard and the AI.

**Learn first**
- MetricFlow: https://docs.getdbt.com/docs/build/about-metricflow, semantic models (https://docs.getdbt.com/docs/build/semantic-models), metrics (https://docs.getdbt.com/docs/build/metrics-overview), time spine (https://docs.getdbt.com/docs/build/metricflow-time-spine).
- Cortex Analyst semantic models or semantic views (Snowflake docs, "Cortex Analyst").

**Tasks**
1. `pip install dbt-metricflow`; add the required time spine model.
2. Semantic models on `fct_mrr_monthly`, `dim_customers` and `mart_trial_funnel`.
3. Metrics: `mrr_eur`, `new_mrr`, `expansion_mrr`, `contraction_mrr`, `churned_mrr`, `paying_customers`, `logo_churn_rate` (ratio), `arpa` (ratio), `trial_conversion_rate` (ratio).
4. Query them: `mf query --metrics mrr_eur --group-by metric_time__month`.
5. Write the Cortex Analyst semantic model (YAML on a stage, or a semantic view) over the same marts and metrics. Add 10 verified queries: the brief's questions with hand-checked SQL.

**Traps**
- NRR and GRR are cohort ratios that don't fit simple metric types well. Expose them from `mart_cohort_retention` as measures there, rather than forcing them into a derived metric that is subtly wrong.
- Two definitions of the same metric (MetricFlow and Cortex) can drift. Keep the names identical and test both against the same queries.

**Done when:** `mf query` matches the marts for 3 metrics, and Cortex Analyst answers your 10 verified questions correctly.

**Interview talking point:** "Metrics are defined once in the semantic layer, and the AI only answers from those definitions, so it can't invent its own version of churn."

## Phase 10 — Streamlit app with AI (week 8, ~8 h)
**Goal:** the CFO's dashboard, one page per brief objective, plus Ask the data.

**Learn first:** Streamlit in Snowflake (Snowflake docs, "Streamlit in Snowflake"), and the Cortex Analyst REST API from Streamlit.

**Tasks**
1. Create the app in Snowsight with the REPORTER role and REPORTING_WH. Grant REPORTER the `SNOWFLAKE.CORTEX_USER` database role.
2. Pages:
   - MRR bridge (objective 1)
   - Retention cohorts heatmap (2)
   - Churn drivers (3)
   - Funnel and unit economics (4)
   - Payments and involuntary churn (5)
   - Ask the data (6), showing the question, the generated SQL and the result
3. Styling: take colours and type from the Query Ink tokens (`sql-dbt-trainning/design_system/tokens.css`). Streamlit theming covers the basics; keep charts to one ink colour per metric family.
4. Every number on screen comes from a mart or a semantic-layer metric. No SQL inside the app that redefines a metric.

**Done when:** each brief objective 1–6 has a page that answers it, and the MRR on screen matches the ground truth for the latest month.

## Phase 11 — Automation and CI (week 9, ~6 h)
**Goal:** daily refresh with nobody touching it, and no broken model reaching production.

**Learn first:** GitHub Actions basics; dbt `state:modified` selection (optional).

**Tasks**
1. Push the repo to GitHub (public). Add secrets: account, both private keys.
2. `.github/workflows/daily.yml` on a schedule:
   - `simulate.py` (no flags = yesterday), `fx.py`, `load.py`
   - `dbt build --target prod`, then `dbt source freshness`
   - on failure, open a GitHub issue (or email)
3. `.github/workflows/ci.yml` on pull requests: `sqlfluff lint` (dbt templater) and `dbt build --target ci`.
4. `.github/workflows/docs.yml`: `dbt docs generate` and publish `target/` to GitHub Pages.

**Traps**
- The simulator replays from 2024 every run (a few seconds), and only writes yesterday's files. If a day is missed, run it once with `--backfill`; the loader skips files already loaded.
- Never commit keys. Write the key from a secret to a temp file in the workflow.

**Done when:** 3 scheduled runs succeed unattended, and a PR with a deliberately failing test is blocked.

## Phase 12 — Showcase (week 10, ~5 h)
**Goal:** someone can understand the project in five minutes without running anything.

**Tasks**
1. README:
   - the business problem (from the brief), architecture diagram, lineage screenshot
   - each brief objective and where it's met
   - design decisions: grain, SCD2 from deliveries, incremental lookback, constant-currency NRR, reconciliation
   - what is simulated, and what you'd do next
2. A 2–3 minute demo video: the MRR bridge, a cohort, one Ask the data question with its SQL.
3. Decide what happens after the trial: pay-as-you-go with auto-suspend (likely a few euros a month), or freeze it with the video and hosted docs as proof.
4. Add the project to `job-hunting/Context/Master.xlsx` first, then to the Analytics Engineer CV, following the bullet rules (ownership verb, scope, no invented metrics). Re-run `/ats-scoring` on a current posting to see the dbt and testing gaps move.

**Done when:** a friend who hasn't seen it can explain what it does after reading the README.
