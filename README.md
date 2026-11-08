# Fieldnote SaaS revenue analytics

Fieldnote is a fictional B2B SaaS getting ready for a Series B, and today Finance, Sales and Product each report a different MRR. This project builds one version of the truth on Snowflake and dbt: MRR and its movements, cohort retention, churn drivers and failed payments, all from governed metric definitions that refresh daily and can be queried in plain language.

**Status: in progress.** The Snowflake setup, raw load, Silver layer and dbt sources are built. The subscription history, MRR models, tests, semantic layer, dashboard and daily automation are next (see the [build guide](docs/build-guide.md)).

## What it answers
The CFO's [brief](docs/brief.md) asks for:

1. Monthly MRR in EUR with a bridge (new, expansion, contraction, churn, reactivation) that reconciles to what was invoiced.
2. Logo retention, GRR and NRR by signup cohort, as a heatmap.
3. Churn rate by plan, country, billing interval, acquisition channel and early activation.
4. Signup to trial to paid conversion, ARPA and a simple LTV by plan.
5. Revenue at risk from failed payments and the dunning recovery rate.
6. Plain-language questions ("What was NRR for Q1 cohorts on the Pro plan?") answered from the same metrics as the dashboard, with the SQL shown.
7. A daily refresh nobody has to run by hand, with tests that block bad data.

Every metric has one written definition in [metrics.md](docs/metrics.md), and nothing goes on a dashboard without one.

## How it's built

```
Stripe + Segment simulator ─┐
ECB exchange rates (real) ──┴─> Snowflake RAW ─> SILVER (notebooks) ─> dbt intermediate + marts (GOLD)
                                                                         └─> semantic layer ─> Streamlit app + Cortex Analyst
```

**Stack:** Snowflake, dbt, SQL, Python, Snowflake notebooks, dbt MetricFlow, Cortex Analyst, Streamlit, GitHub Actions.

The parts worth a look:

- **Data that behaves like the real thing.** Billing and product events are simulated in the shape of Stripe API objects and Segment track calls, with the problems real feeds have: daily re-deliveries of full objects, duplicates, late events, a schema change mid-history, grandfathered prices, prorations and failed payments. All 15 quirks are listed in [source-data.md](docs/source-data.md).
- **MRR checked to the cent.** The simulator writes an answer key, and a reconciliation test compares the model's MRR to it for every customer and month.
- **Currency handled on purpose.** Revenue is converted to EUR at the ECB month-end rate, and NRR and GRR use constant currency so exchange rate moves don't show up as expansion or churn.
- **Access by role.** Separate roles and warehouses for loading, transforming and reporting, key-pair service users and a credit cap on spend.

## Repo map

| Folder | What's in it |
|---|---|
| `simulator/` | Deterministic Stripe and Segment data generator |
| `ingestion/` | ECB rates download and the Snowflake loader |
| `snowflake/` | Account setup (`setup.sql`) and the Silver notebook |
| `dbt/` | dbt project: sources, intermediate models and marts |
| `docs/` | [Brief](docs/brief.md), [metric definitions](docs/metrics.md), [source data](docs/source-data.md), [build guide](docs/build-guide.md) |

Billing and product data are simulated. Exchange rates are real, from the ECB.

## Run it yourself

### Quickstart: get the raw tables loaded

**1. Python environment**
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

**2. Key pairs for the service users**
```bash
mkdir -p keys
for u in loader dbt; do
  openssl genrsa 2048 | openssl pkcs8 -topk8 -inform PEM -out keys/${u}_key.p8 -nocrypt
  openssl rsa -in keys/${u}_key.p8 -pubout -out keys/${u}_key.pub
done
```

**3. Snowflake.** Create a trial account (Enterprise, AWS, in a region where Cortex Analyst is available). Open `snowflake/setup.sql` in a Snowsight worksheet, replace the placeholders with your username and the two public keys (`keys/*.pub` without the BEGIN/END lines), and run it all.

**4. Generate and load data**
```bash
python simulator/simulate.py --backfill   # Stripe + Segment files, Jan 2024 to yesterday
python ingestion/fx.py --backfill         # ECB rates
cp .env.example .env                      # then fill in SNOWFLAKE_ACCOUNT
set -a; source .env; set +a
python ingestion/load.py
```

**5. Check** (in Snowsight)
```sql
SELECT 'stripe.customers' AS t, COUNT(*) FROM RAW.STRIPE.CUSTOMERS
UNION ALL SELECT 'stripe.subscriptions', COUNT(*) FROM RAW.STRIPE.SUBSCRIPTIONS
UNION ALL SELECT 'stripe.invoices', COUNT(*) FROM RAW.STRIPE.INVOICES
UNION ALL SELECT 'stripe.charges', COUNT(*) FROM RAW.STRIPE.CHARGES
UNION ALL SELECT 'stripe.refunds', COUNT(*) FROM RAW.STRIPE.REFUNDS
UNION ALL SELECT 'stripe.prices', COUNT(*) FROM RAW.STRIPE.PRICES
UNION ALL SELECT 'stripe.products', COUNT(*) FROM RAW.STRIPE.PRODUCTS
UNION ALL SELECT 'stripe.coupons', COUNT(*) FROM RAW.STRIPE.COUPONS
UNION ALL SELECT 'segment.tracks', COUNT(*) FROM RAW.SEGMENT.TRACKS
UNION ALL SELECT 'ecb.rates', COUNT(*) FROM RAW.ECB.RATES
UNION ALL SELECT 'ground_truth.mrr_monthly', COUNT(*) FROM RAW.GROUND_TRUTH.MRR_MONTHLY;
```

### Daily refresh
```bash
python simulator/simulate.py && python ingestion/fx.py && python ingestion/load.py
```
The simulator replays deterministically from 2024-01-01 and writes only yesterday's files; the loader skips files already loaded. If you miss days, run the simulator once with `--backfill`.
