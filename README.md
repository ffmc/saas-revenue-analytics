# Fieldnote SaaS revenue analytics

A portfolio project that builds the revenue reporting for Fieldnote, a fictional company that sells team-planning software on monthly and annual subscriptions. Its Finance, Sales and Product teams each report a different monthly recurring revenue (MRR), so the goal is one set of numbers everyone uses: how much recurring revenue comes in each month, why it went up or down, and which customers stay or leave.

The raw billing and product data lands in Snowflake, dbt cleans, models and tests it, and Airflow runs the whole refresh every day. The result is a finance dashboard and a way to ask questions in plain English, both reading from the same metric definitions.

**Status: in progress.** Done so far: Snowflake setup, raw data load, a cleaned layer and the dbt project connected to it. Next: the revenue models, tests, metric definitions in code, the dashboard and the Airflow schedule (see the [build guide](docs/build-guide.md)).

## The business case

Fieldnote sells four plans (Free, Starter, Pro and Business), priced per seat and billed monthly or annually in Spain, the UK and the US. It's preparing to raise a Series B, and every investor asks for the same three numbers: MRR, net revenue retention and churn. Today Finance, Sales and Product each pull those numbers their own way and get different answers, which is a problem in front of investors and makes it hard to decide anything internally.

The CFO's [brief](docs/brief.md) asks for one version of the truth that refreshes itself and that their team can query without filing a ticket. It would count as a failure if there were still three MRR numbers, if a metric appeared on screen without a written definition, or if someone had to run the pipeline by hand.

## Questions it answers

**Revenue**
- What is MRR this month in euros, and how much of the change came from new customers, upgrades, downgrades, cancellations and customers coming back?
- Does MRR reconcile to what we invoiced?

**Retention**
- Of the customers who started paying in a given month, how many are still paying a year later?
- How much of their revenue did we keep (gross revenue retention), and how much did it grow with upgrades (net revenue retention)?

**Churn**
- Which customers leave most often: by plan, country, monthly or annual billing, acquisition channel, and whether they set up their workspace properly in the first 14 days?

**Growth and unit economics**
- How many signups start a trial, and how many trials turn into paying customers?
- What is the average revenue per account, and the lifetime value of a customer on each plan?

**Failed payments**
- How much revenue is at risk from failed card payments, and how much do payment retries recover?
- How much MRR do we lose to failed payments compared with customers who choose to cancel?

**Self-service**
- Can the CFO ask "What was NRR for Q1 cohorts on the Pro plan?" in plain English and get the answer, with the SQL behind it, from the same definitions as the dashboard?

Each of these metrics has one written definition in [metrics.md](docs/metrics.md), agreed before any model was built.

## How it's built

```
Stripe + Segment simulator ─┐
ECB exchange rates (real) ──┴─> Snowflake RAW ─> SILVER (notebooks) ─> dbt intermediate + marts (GOLD)
                                                                         └─> semantic layer ─> Streamlit app + Cortex Analyst
                    └──────────────────── orchestrated daily by Airflow ────────────────────┘
```

| Step | What happens | Tools |
|---|---|---|
| Source data | A simulator writes daily billing (Stripe) and product usage (Segment) files, and real exchange rates come from the European Central Bank | Python |
| Raw load | Files land in Snowflake exactly as delivered, with the file name and row kept for traceability | Snowflake, Python |
| Cleaning | One clean table per source object: correct types, duplicates removed, nested lists split into their own tables | Snowflake notebooks, SQL |
| Modeling | Subscription history, MRR per customer per month, then the marts behind each question: MRR bridge, retention cohorts, churn drivers, trial funnel, payments | dbt, SQL |
| Testing | Data tests on every source and model, plus a check that MRR matches an answer key to the cent for every customer and month | dbt |
| Metrics | Every metric defined once in code, used by both the dashboard and the plain-English questions | dbt MetricFlow, Snowflake Cortex Analyst |
| Reporting | A dashboard with one page per question area, plus an "Ask the data" page | Streamlit in Snowflake |
| Orchestration | A daily Airflow run loads, builds and tests everything, and alerts on failure. Pull requests are linted and tested before merging | Airflow, GitHub Actions |

### Design decisions

- **Data that behaves like the real thing.** The simulated data follows the shape of Stripe API objects and Segment events, with the problems real feeds have: daily re-deliveries of full records, duplicates, late events, a schema change mid-history, grandfathered prices, prorations and failed payments. All 15 are listed in [source-data.md](docs/source-data.md).
- **MRR checked to the cent.** The simulator also writes an answer key, and a test compares the model's MRR to it for every customer and month.
- **Currency handled on purpose.** Revenue is converted to euros at the month-end exchange rate, and retention uses a constant rate so currency moves don't look like upgrades or churn.
- **Access by role.** Loading, transforming and reporting each have their own role and warehouse, service accounts use key pairs, and a monthly credit cap limits spend.

## Repo map

| Folder | What's in it |
|---|---|
| `simulator/` | Stripe and Segment data generator |
| `ingestion/` | Exchange rate download and the Snowflake loader |
| `snowflake/` | Account setup (`setup.sql`) and the cleaning notebook |
| `dbt/` | dbt project: sources, intermediate models and marts |
| `airflow/` | The daily DAG (phase 11) |
| `docs/` | [Brief](docs/brief.md), [metric definitions](docs/metrics.md), [source data](docs/source-data.md), [build guide](docs/build-guide.md), [setup](docs/setup.md) |

Billing and product data are simulated. Exchange rates are real.

## Run it yourself

The setup steps and commands are in [docs/setup.md](docs/setup.md).
