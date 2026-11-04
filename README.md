# Fieldnote SaaS revenue analytics

Subscription revenue analytics for a fictional B2B SaaS, built on Snowflake and dbt: MRR and its movements, cohort retention, churn drivers, payments, and AI-assisted questions over governed metrics.

- `docs/brief.md`: what the CFO asked for
- `docs/metrics.md`: metric definitions
- `docs/source-data.md`: raw tables and their quirks (and what is simulated)
- `docs/build-guide.md`: the build, phase by phase

## Quickstart: get the raw tables loaded

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

## Daily refresh
```bash
python simulator/simulate.py && python ingestion/fx.py && python ingestion/load.py
```
The simulator replays deterministically from 2024-01-01 and writes only yesterday's files; the loader skips files already loaded. If you miss days, run the simulator once with `--backfill`.
