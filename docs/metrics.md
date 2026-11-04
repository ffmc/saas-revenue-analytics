# Metric definitions

Agreed with the CFO. The semantic layer implements exactly these; anything not here doesn't go on a dashboard.

## MRR
Measured at each month end (23:59:59 UTC on the last day of the month), per customer, in the customer's currency.

- Count subscriptions with status `active` or `past_due`. `trialing`, `canceled` and Free-plan subscriptions contribute 0.
- Amount = `unit_amount × quantity` for each item, divided by 12 for annual prices.
- Apply the subscription's discount if it is active at month end (`discount.end` is null or later than month end): multiply by `1 − percent_off / 100`.
- Round to cents per customer.

The simulator's answer key (`RAW.GROUND_TRUTH.MRR_MONTHLY`) uses this definition, so the model must match it to the cent.

## EUR conversion
GBP and USD are converted with the ECB reference rate of the last business day on or before month end (ECB publishes `GBP per EUR`, so `EUR = amount / rate`).

For retention ratios (NRR, GRR) both months use the **same** rate (the later month's), so currency moves don't show up as expansion or contraction. Report MRR itself at each month's own rate.

## MRR movements
For each customer and month, compare MRR with the previous month end:

| Movement | Rule |
|---|---|
| new | previous = 0, and the customer never had MRR before |
| reactivation | previous = 0, and the customer had MRR at some earlier month end |
| expansion | both > 0, current > previous |
| contraction | both > 0, current < previous |
| churn | previous > 0, current = 0 |
| retained | both > 0 and equal |

The bridge must close every month: `start MRR + new + reactivation + expansion − contraction − churn = end MRR`.

## Retention
- **Logo churn rate** (month M) = customers with movement `churn` in M / customers with MRR > 0 at the end of M−1.
- **NRR** (12 months, at M) = MRR at M of customers who had MRR at M−12 / their MRR at M−12. Constant currency.
- **GRR** (12 months, at M) = same cohort, but each customer's MRR at M is capped at their MRR at M−12. Constant currency.
- **Cohort** = month of the customer's first month end with MRR > 0.

## Activation
An account is activated if, within 14 days of its `signed_up` event (event `timestamp`, not `receivedAt`):
- at least 3 distinct `invited_teammate` events, and
- at least one `feature_used` with `properties.feature = 'timeline_view'`.

## Funnel and unit economics
- **Trial conversion** = trials whose subscription reached `active` or `past_due` after `trial_end` / trials that have ended.
- **ARPA** = MRR / customers with MRR > 0 at month end.
- **LTV (simple)** = ARPA / average monthly logo churn rate over the trailing 6 months, by plan.

## Payments
- **Involuntary churn** = churn where the subscription ended with `cancellation_details.reason = 'payment_failed'`.
- **Revenue at risk** = MRR of subscriptions in `past_due` at month end.
- **Dunning recovery rate** = invoices whose first payment attempt failed and were later paid / invoices whose first attempt failed (cohort by first failure month).
