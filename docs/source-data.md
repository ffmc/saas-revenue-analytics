# Source data

## What is real and what is simulated
- **Billing (Stripe) and product events (Segment) are simulated** by `simulator/simulate.py`. Records follow the shape of Stripe API objects and Segment track calls. The company, customers and behaviour are invented; rates sit in realistic SMB SaaS ranges (about 3.5% monthly logo churn, NRR around 90–100%, trial conversion about 15% unactivated and 50% activated).
- **Exchange rates are real**, from the ECB data API.
- The simulator is deterministic (fixed seed): the same date always produces the same files.

## How records arrive
Each Stripe object is delivered again on every day it changes, as its full current state. That's how an incremental API extract on "objects updated today" behaves. So `RAW.STRIPE.SUBSCRIPTIONS` holds the full daily history of each subscription, and you must pick the latest state yourself.

Every raw table has the same columns:

| Column | Meaning |
|---|---|
| `RAW` | the record as delivered (VARIANT) |
| `_FILE` | stage path, e.g. `stripe/subscriptions/2025-03-14.jsonl.gz`. The date in the name is the delivery date. |
| `_FILE_ROW` | row number inside the file |
| `_LOADED_AT` | when Snowflake loaded it. All backfilled rows share roughly the same value, so don't use it to order history. |

## Tables

| Table | One row per | Key fields |
|---|---|---|
| `RAW.STRIPE.CUSTOMERS` | customer × day it changed | `id`, `created`, `currency`, `address.country`, `delinquent`, `metadata.workspace_id`, channel (see quirks) |
| `RAW.STRIPE.SUBSCRIPTIONS` | subscription × day it changed | `id`, `customer`, `status`, `items.data[]` (price, quantity), `current_period_start/end`, `trial_start/end`, `cancel_at_period_end`, `canceled_at`, `ended_at`, `cancellation_details.reason`, `discount` |
| `RAW.STRIPE.INVOICES` | invoice × day it changed | `id`, `subscription`, `billing_reason`, `status`, `subtotal`, `total`, `amount_paid`, `attempt_count`, `lines.data[]`, `status_transitions` |
| `RAW.STRIPE.CHARGES` | charge × day it changed | `id`, `invoice`, `status`, `amount`, `failure_code`, `refunded` |
| `RAW.STRIPE.REFUNDS` | refund | `id`, `charge`, `amount` |
| `RAW.STRIPE.PRODUCTS` | product | `id`, `name` |
| `RAW.STRIPE.PRICES` | price × day it changed | `id`, `product`, `currency`, `unit_amount`, `recurring.interval`, `nickname`, `active` |
| `RAW.STRIPE.COUPONS` | coupon | `id`, `percent_off`, `duration`, `duration_in_months` |
| `RAW.SEGMENT.TRACKS` | event (plus duplicates) | `messageId`, `event`, `userId`, `timestamp`, `receivedAt`, `context.groupId`, `properties` |
| `RAW.ECB.RATES` | currency × business day × extract file | `CURRENCY`, `TIME_PERIOD`, `OBS_VALUE` (string, units of currency per 1 EUR) |
| `RAW.GROUND_TRUTH.MRR_MONTHLY` | customer × month | answer key for reconciliation tests only |

Segment events: `signed_up`, `workspace_created`, `invited_teammate`, `feature_used` (`properties.feature`), `seat_added` (`properties.seats_added`, `seats_total`).

## Quirks you need to handle
1. **Latest state.** Pick the latest record per `id`: order by the delivery date in `_FILE`, then `_FILE_ROW`.
2. **Exact duplicates.** About 1% of Stripe records are delivered again the next day; about 1% of Segment events appear twice with the same `messageId`.
3. **Late events.** About 3% of Segment events arrive 1–3 days late. Files are partitioned by `receivedAt`, so an event can land in a later file than its `timestamp`.
4. **Schema change on 2025-06-01.** Customer `metadata.acquisition_channel` is renamed to `metadata.signup_channel` in records delivered from that date. Invoices gain `total_excluding_tax` from the same date. Old and new shapes both exist in the table.
5. **Units.** Amounts are integers in minor units (cents, pence). Timestamps are Unix seconds (UTC). Currency codes are lowercase in Stripe, uppercase in ECB.
6. **Annual prices.** `recurring.interval = 'year'` and `unit_amount` is the yearly price per seat.
7. **Price increase on 2025-03-01.** New Pro prices were created and the old ones set to `active = false`. Existing customers keep their old price (grandfathered), so active subscriptions reference inactive prices.
8. **Free plan.** Free subscriptions have a €0 price and produce no invoices. Moving between Free and a paid plan is an update to the **same** subscription, not a new one.
9. **Prorations.** Mid-period seat additions and upgrades create a `subscription_update` invoice with a negative line (unused time on the old price) and a positive line. Decreases take effect without credit.
10. **Trials.** Paid signups start `trialing` for 14 days and get a €0 `subscription_create` invoice. Trials that don't convert end as `canceled` without ever paying.
11. **Discounts.** `WELCOME20` (20% for 3 months, starting at subscription creation, so partly used up by the trial) and `PARTNER10` (10% forever, partner channel). Check `discount.end` against the date you're measuring.
12. **Failed payments.** A failed charge puts the invoice `open` and the subscription `past_due`. Retries happen 3, 7 and 14 days after the first failure. After the last one fails, the invoice is `uncollectible` and the subscription `canceled` with reason `payment_failed`.
13. **Refunds** set `refunded = true` on the charge but don't change the invoice status.
14. **Joining product events to billing.** Segment `context.groupId` = Stripe `customer.metadata.workspace_id`. There is no Stripe id in the events.
15. **ECB gaps.** No rates on weekends and TARGET holidays (e.g. 1 January). Daily extracts overlap by 10 days, so the same date and currency appear in several files.
