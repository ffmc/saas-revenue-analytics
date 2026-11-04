# Stakeholder brief

**From:** CFO, Fieldnote
**To:** Analytics Engineering

## Situation
Fieldnote is a B2B team-planning SaaS: Free, Starter, Pro and Business plans, monthly or annual, priced per seat, sold in Spain (EUR), the UK (GBP) and the US (USD). We are preparing a Series B. Every investor asks for MRR, net revenue retention and churn, and today Finance, Sales and Product each give a different number. I want one version of the truth that refreshes itself and that my team can query without filing a ticket.

## What I want to see
1. **MRR and its movements.** Monthly MRR in EUR with a bridge: new, expansion, contraction, churn, reactivation. It must reconcile to what we invoiced.
2. **Retention.** Logo retention, gross revenue retention (GRR) and net revenue retention (NRR) by monthly signup cohort, as a cohort heatmap.
3. **Why customers churn.** Churn rate by plan, country, billing interval, acquisition channel, and by whether the account was activated in its first 14 days.
4. **Funnel and unit economics.** Signup to trial to paid conversion, ARPA, and a simple LTV by plan.
5. **Involuntary churn.** Revenue at risk from failed payments, the dunning recovery rate, and MRR lost to payment failure compared with customers choosing to cancel.
6. **Ask in plain language.** "What was NRR for Q1 cohorts on the Pro plan?" answered from the same governed metrics as the dashboard, with the SQL shown.
7. **Trust.** Daily refresh with nobody touching it. Tests block bad data. Freshness alerts. The FX method is written down. Every metric has one definition, in `metrics.md`.

## Non-goals
Forecasting or ML, marketing attribution (possible phase 2), real-time data.

## What would make this a failure even if it works
- Three MRR numbers again.
- A metric on screen that isn't defined in the semantic layer.
- A pipeline that needs someone to run it by hand.
