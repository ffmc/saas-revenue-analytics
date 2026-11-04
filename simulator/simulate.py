"""Simulates Fieldnote's Stripe billing and Segment product events.

Replays deterministically from config.START to --until with a fixed seed, so any
day's files are identical across runs. Writes NDJSON landing files plus a
ground-truth MRR file used only for reconciliation tests.
"""
import argparse
import calendar
import csv
import json
import math
import random
import string
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import config as C

ALPHABET = string.ascii_letters + string.digits
WORDS_A = ["Blue", "North", "Bright", "Quiet", "Swift", "Iron", "Green", "Clear", "Bold", "Silver", "Coral", "Amber"]
WORDS_B = ["Harbor", "Peak", "Field", "Forge", "Lane", "Grove", "Bridge", "Stone", "River", "Atlas", "Orbit", "Pine"]
WORDS_C = ["Studio", "Labs", "Partners", "Group", "Works", "Co", "Digital", "Logistics", "Health", "Media"]


def ts(d, sec=0):
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp()) + sec


def ts_date(t):
    return datetime.fromtimestamp(t, timezone.utc).date()


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def add_months(d, n):
    m = d.month - 1 + n
    y, m = d.year + m // 12, m % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def is_month_end(d):
    return (d + timedelta(days=1)).day == 1


class Sim:
    def __init__(self, until):
        self.rng = random.Random(C.SEED)
        self.until = until
        self.out = defaultdict(list)          # (day, path) -> json lines
        self.tasks = defaultdict(list)        # day -> [(kind, id)]
        self.dirty = {}                       # (path, id) -> object, flushed once per day
        self.customers, self.subs, self.invoices, self.charges = {}, {}, {}, {}
        self.products, self.prices, self.coupons = {}, {}, {}
        self.price_index = {}                 # (plan, interval, currency) -> current price id
        self.mrr = {}                         # (month, customer) -> cents
        self.ever_paid = set()

    # ---------- helpers ----------
    def id(self, prefix, n=14):
        return prefix + "".join(self.rng.choice(ALPHABET) for _ in range(n))

    def pick(self, weights):
        r, acc = self.rng.random(), 0.0
        for k, w in weights.items():
            acc += w
            if r < acc:
                return k
        return k

    def poisson(self, lam):
        l, k, p = math.exp(-lam), 0, 1.0
        while True:
            p *= self.rng.random()
            if p <= l:
                return k
            k += 1

    def daily(self, monthly_p):
        return self.rng.random() < monthly_p / 30

    def touch(self, path, obj):
        self.dirty[(path, obj["id"])] = obj

    def emit(self, day, path, obj):
        rec = {k: v for k, v in obj.items() if not k.startswith("_")}
        if path == "stripe/customers":
            meta = dict(rec["metadata"])
            if day >= C.SCHEMA_CHANGE:
                meta["signup_channel"] = meta.pop("acquisition_channel")
            rec["metadata"] = meta
        if path == "stripe/invoices" and day >= C.SCHEMA_CHANGE:
            rec["total_excluding_tax"] = rec["total"]
        line = json.dumps(rec, separators=(",", ":"))
        self.out[(day, path)].append(line)
        if self.rng.random() < C.DUPLICATE_RATE:
            self.out[(day + timedelta(days=1), path)].append(line)

    def flush(self, day):
        for (path, _), obj in self.dirty.items():
            self.emit(day, path, obj)
        self.dirty = {}

    def track(self, cust, event, t, props=None, user=None):
        received = t + self.rng.randint(1, 30)
        if self.rng.random() < C.LATE_EVENT_RATE:
            received = t + self.rng.randint(86400, 3 * 86400)
        rec = {
            "messageId": self.id("msg_", 20),
            "type": "track",
            "event": event,
            "userId": user or self.rng.choice(cust["_users"]),
            "timestamp": iso(t),
            "receivedAt": iso(received),
            "context": {"groupId": cust["metadata"]["workspace_id"], "library": {"name": "analytics-node", "version": "6.2.0"}},
            "properties": props or {},
        }
        line = json.dumps(rec, separators=(",", ":"))
        day = ts_date(received)
        self.out[(day, "segment/tracks")].append(line)
        if self.rng.random() < C.DUPLICATE_RATE:
            self.out[(day, "segment/tracks")].append(line)

    # ---------- catalog ----------
    def create_catalog(self, day):
        t = ts(day) - 30 * 86400
        for plan in ["free", "starter", "pro", "business"]:
            pid = self.id("prod_")
            self.products[plan] = pid
            self.touch("stripe/products", {"id": pid, "object": "product", "name": f"Fieldnote {plan.title()}", "active": True, "created": t, "livemode": False})
        for cur in ["eur", "gbp", "usd"]:
            self.add_price("free", "month", cur, 0, t)
            for plan, by_cur in C.PRICES.items():
                self.add_price(plan, "month", cur, by_cur[cur], t)
                self.add_price(plan, "year", cur, by_cur[cur] * 10, t)
        for cid, c in C.COUPONS.items():
            self.coupons[cid] = {"id": cid, "object": "coupon", "percent_off": c["percent_off"], "duration": c["duration"],
                                 "duration_in_months": c["duration_in_months"], "created": t, "valid": True, "livemode": False}
            self.touch("stripe/coupons", self.coupons[cid])

    def add_price(self, plan, interval, cur, amount, t):
        pid = self.id("price_", 24)
        price = {"id": pid, "object": "price", "product": self.products[plan], "currency": cur, "unit_amount": amount,
                 "recurring": {"interval": interval, "interval_count": 1, "usage_type": "licensed"},
                 "nickname": f"{plan}_{interval}ly_{cur}", "active": True, "created": t, "livemode": False, "_plan": plan}
        self.prices[pid] = price
        old = self.price_index.get((plan, interval, cur))
        if old:
            self.prices[old]["active"] = False
            self.touch("stripe/prices", self.prices[old])
        self.price_index[(plan, interval, cur)] = pid
        self.touch("stripe/prices", price)

    def price_increase(self, day):
        for cur, amount in C.PRO_PRICE_AFTER_INCREASE.items():
            self.add_price("pro", "month", cur, amount, ts(day))
            self.add_price("pro", "year", cur, amount * 10, ts(day))

    # ---------- customers ----------
    def signup(self, day):
        country = self.pick({k: v[1] for k, v in C.COUNTRIES.items()})
        cur = C.COUNTRIES[country][0]
        channel = self.pick(C.CHANNELS)
        name = f"{self.rng.choice(WORDS_A)} {self.rng.choice(WORDS_B)} {self.rng.choice(WORDS_C)}"
        t = ts(day, self.rng.randint(0, 86399))
        owner = self.id("usr_", 10)
        cust = {
            "id": self.id("cus_"), "object": "customer", "created": t, "name": name,
            "email": f"billing@{name.lower().replace(' ', '')}.example", "currency": cur,
            "address": {"country": country}, "delinquent": False, "livemode": False,
            "metadata": {"workspace_id": self.id("ws_", 10), "acquisition_channel": channel},
            "_users": [owner], "_activated": self.rng.random() < C.ACTIVATION_RATE[channel],
            "_signup_day": day, "_live_sub": None, "_last_paid_plan": None,
        }
        self.customers[cust["id"]] = cust
        self.touch("stripe/customers", cust)
        self.track(cust, "signed_up", t, {"plan": "pending"}, owner)
        self.track(cust, "workspace_created", t + 60, {}, owner)
        self.onboarding(cust, day, t)

        plan = self.pick(C.PLAN_MIX)
        interval = "year" if plan != "free" and self.rng.random() < C.ANNUAL_SHARE else "month"
        seats = self.rng.randint(*C.SEATS[plan])
        if plan == "free":
            self.new_sub(cust, day, t, "free", "month", seats, trial=False)
        else:
            coupon = None
            if channel == "partner":
                coupon = "PARTNER10"
            elif interval == "month" and self.rng.random() < C.WELCOME_COUPON_SHARE:
                coupon = "WELCOME20"
            self.new_sub(cust, day, t, plan, interval, seats, trial=True, coupon=coupon)

    def onboarding(self, cust, day, t):
        invites = self.rng.randint(3, 8) if cust["_activated"] else self.rng.randint(0, 4)
        for _ in range(invites):
            et = t + self.rng.randint(600, C.TRIAL_DAYS * 86400 - 600)
            uid = self.id("usr_", 10)
            cust["_users"].append(uid)
            self.track(cust, "invited_teammate", et, {"invitee_id": uid}, cust["_users"][0])
        if cust["_activated"]:
            self.track(cust, "feature_used", t + self.rng.randint(3600, 10 * 86400), {"feature": C.KEY_FEATURE}, cust["_users"][0])

    # ---------- subscriptions ----------
    def new_sub(self, cust, day, t, plan, interval, seats, trial, coupon=None):
        price_id = self.price_index[(plan, interval, cust["currency"])]
        sub = {
            "id": self.id("sub_"), "object": "subscription", "customer": cust["id"], "created": t, "start_date": t,
            "status": "active", "currency": cust["currency"], "collection_method": "charge_automatically",
            "cancel_at_period_end": False, "canceled_at": None, "ended_at": None,
            "cancellation_details": {"reason": None, "feedback": None},
            "trial_start": None, "trial_end": None, "current_period_start": t, "current_period_end": None,
            "discount": None, "latest_invoice": None, "livemode": False, "metadata": {},
            "items": {"object": "list", "data": [{"id": self.id("si_"), "object": "subscription_item", "created": t,
                                                  "price": self.price_ref(price_id), "quantity": seats}]},
            "_plan": plan, "_interval": interval, "_churning": False,
        }
        self.subs[sub["id"]] = sub
        cust["_live_sub"] = sub["id"]
        if coupon:
            c = self.coupons[coupon]
            end = ts(add_months(day, c["duration_in_months"]), t - ts(day)) if c["duration_in_months"] else None
            sub["discount"] = {"id": self.id("di_"), "object": "discount", "coupon": dict(c), "customer": cust["id"],
                               "subscription": sub["id"], "start": t, "end": end}
        if plan == "free":
            sub["current_period_end"] = self.period_end(t, interval)
            self.tasks[ts_date(sub["current_period_end"])].append(("period_end", sub["id"]))
            self.touch("stripe/subscriptions", sub)
            return sub
        if trial:
            sub["status"] = "trialing"
            sub["trial_start"] = t
            sub["trial_end"] = t + C.TRIAL_DAYS * 86400
            sub["current_period_end"] = sub["trial_end"]
            self.invoice(sub, day, t, "subscription_create", [(0, sub["items"]["data"][0], t, sub["trial_end"], False)])
            converts = self.rng.random() < C.TRIAL_CONVERSION[cust["_activated"]]
            if not converts:
                self.tasks[day + timedelta(days=self.rng.randint(1, C.TRIAL_DAYS - 1))].append(("cancel_request", sub["id"]))
            self.tasks[ts_date(sub["trial_end"])].append(("period_end", sub["id"]))
        else:
            self.start_paid_period(sub, day, t, "subscription_create")
        self.touch("stripe/subscriptions", sub)
        return sub

    def price_ref(self, pid):
        return {k: v for k, v in self.prices[pid].items() if not k.startswith("_")}

    def period_end(self, t, interval):
        d = ts_date(t)
        return ts(add_months(d, 12 if interval == "year" else 1), t - ts(d))

    def sub_amount(self, sub):
        return sum(i["price"]["unit_amount"] * i["quantity"] for i in sub["items"]["data"])

    def discount_pct(self, sub, at):
        d = sub["discount"]
        if d and (d["end"] is None or d["end"] > at):
            return d["coupon"]["percent_off"]
        return 0.0

    def start_paid_period(self, sub, day, t, reason):
        cust = self.customers[sub["customer"]]
        sub["status"] = "active"
        sub["current_period_start"] = t
        sub["current_period_end"] = self.period_end(t, sub["_interval"])
        self.ever_paid.add(cust["id"])
        cust["_last_paid_plan"] = sub["_plan"]
        item = sub["items"]["data"][0]
        inv = self.invoice(sub, day, t, reason, [(item["price"]["unit_amount"] * item["quantity"], item, t, sub["current_period_end"], False)])
        self.pay(inv, day, t)
        p = C.MONTHLY_CHURN[sub["_plan"]] * C.ACTIVATION_CHURN_FACTOR[cust["_activated"]]
        if sub["_interval"] == "year":
            p = (1 - (1 - p) ** 12) * C.ANNUAL_CHURN_DISCOUNT
        end_day = ts_date(sub["current_period_end"])
        sub["_churning"] = self.rng.random() < p
        if sub["_churning"]:
            span = (end_day - day).days
            lead = self.rng.randint(1, max(1, min(span - 1, 60 if sub["_interval"] == "year" else span - 1)))
            self.tasks[end_day - timedelta(days=lead)].append(("cancel_request", sub["id"]))
        self.tasks[end_day].append(("period_end", sub["id"]))

    def end_sub(self, sub, day, t, reason):
        cust = self.customers[sub["customer"]]
        sub["status"] = "canceled"
        sub["ended_at"] = t
        sub["canceled_at"] = sub["canceled_at"] or t
        sub["cancellation_details"] = {"reason": reason, "feedback": None}
        cust["_live_sub"] = None
        self.touch("stripe/subscriptions", sub)

    # ---------- invoices and payments ----------
    def invoice(self, sub, day, t, reason, lines):
        pct = self.discount_pct(sub, t)
        data = []
        for amount, item, start, end, proration in lines:
            data.append({"id": self.id("il_"), "object": "line_item", "amount": amount, "currency": sub["currency"],
                         "description": f"{item['quantity']} × {item['price']['nickname']}", "proration": proration,
                         "quantity": item["quantity"], "price": {"id": item["price"]["id"]},
                         "period": {"start": start, "end": end}, "subscription": sub["id"]})
        subtotal = sum(l["amount"] for l in data)
        disc = round(subtotal * pct / 100) if subtotal > 0 else 0
        total = subtotal - disc
        inv = {
            "id": self.id("in_"), "object": "invoice", "customer": sub["customer"], "subscription": sub["id"],
            "billing_reason": reason, "collection_method": "charge_automatically", "currency": sub["currency"],
            "created": t, "period_start": lines[0][2], "period_end": lines[0][3],
            "subtotal": subtotal, "total": total, "amount_due": total, "amount_paid": 0, "amount_remaining": total,
            "total_discount_amounts": [{"amount": disc, "discount": sub["discount"]["id"]}] if disc else [],
            "attempt_count": 0, "attempted": False, "next_payment_attempt": None,
            "status": "paid" if total == 0 else "open",
            "status_transitions": {"finalized_at": t, "paid_at": t if total == 0 else None, "marked_uncollectible_at": None},
            "lines": {"object": "list", "data": data}, "livemode": False, "_sub": sub["id"],
        }
        self.invoices[inv["id"]] = inv
        sub["latest_invoice"] = inv["id"]
        self.touch("stripe/invoices", inv)
        return inv

    def pay(self, inv, day, t, retry_index=0):
        if inv["total"] == 0:
            return
        sub = self.subs[inv["_sub"]]
        cust = self.customers[inv["customer"]]
        p = C.FIRST_PAYMENT_SUCCESS if retry_index == 0 or inv["billing_reason"] == "subscription_update" else C.RETRY_SUCCESS
        if inv["billing_reason"] == "subscription_update":
            p = 1.0
        ok = self.rng.random() < p
        inv["attempt_count"] += 1
        inv["attempted"] = True
        ch = {"id": self.id("ch_", 24), "object": "charge", "amount": inv["total"], "currency": inv["currency"], "created": t,
              "customer": cust["id"], "invoice": inv["id"], "paid": ok, "status": "succeeded" if ok else "failed",
              "failure_code": None if ok else self.rng.choice(["card_declined", "insufficient_funds", "expired_card"]),
              "refunded": False, "amount_refunded": 0, "outcome": {"type": "authorized" if ok else "issuer_declined"}, "livemode": False}
        ch["failure_message"] = None if ok else ch["failure_code"].replace("_", " ").capitalize() + "."
        self.charges[ch["id"]] = ch
        self.touch("stripe/charges", ch)
        if ok:
            inv.update(status="paid", amount_paid=inv["total"], amount_remaining=0, next_payment_attempt=None)
            inv["status_transitions"]["paid_at"] = t
            if sub["status"] == "past_due":
                sub["status"] = "active"
                self.touch("stripe/subscriptions", sub)
            if cust["delinquent"]:
                cust["delinquent"] = False
                self.touch("stripe/customers", cust)
            if self.rng.random() < C.REFUND_RATE:
                self.tasks[day + timedelta(days=self.rng.randint(1, 10))].append(("refund", ch["id"]))
        elif retry_index < len(C.RETRY_DAYS):
            nxt = day + timedelta(days=C.RETRY_DAYS[retry_index] - (C.RETRY_DAYS[retry_index - 1] if retry_index else 0))
            inv["next_payment_attempt"] = ts(nxt, t - ts(day))
            self.tasks[nxt].append(("retry", inv["id"]))
            if sub["status"] != "past_due":
                sub["status"] = "past_due"
                self.touch("stripe/subscriptions", sub)
            if not cust["delinquent"]:
                cust["delinquent"] = True
                self.touch("stripe/customers", cust)
        else:
            inv.update(status="uncollectible", next_payment_attempt=None)
            inv["status_transitions"]["marked_uncollectible_at"] = t
            self.end_sub(sub, day, t, "payment_failed")
        self.touch("stripe/invoices", inv)

    # ---------- daily behaviour ----------
    def run_task(self, kind, oid, day):
        t = ts(day, self.rng.randint(0, 86399))
        if kind == "cancel_request":
            sub = self.subs[oid]
            if sub["status"] in ("active", "trialing", "past_due") and not sub["cancel_at_period_end"] and sub["_plan"] != "free":
                sub["cancel_at_period_end"] = True
                sub["canceled_at"] = t
                self.touch("stripe/subscriptions", sub)
        elif kind == "period_end":
            sub = self.subs[oid]
            if sub["status"] == "canceled" or ts_date(sub["current_period_end"]) != day:
                return
            t = sub["current_period_end"]
            if sub["cancel_at_period_end"]:
                self.end_sub(sub, day, t, "cancellation_requested")
            elif sub["_plan"] == "free":
                sub["current_period_start"] = t
                sub["current_period_end"] = self.period_end(t, "month")
                self.tasks[ts_date(sub["current_period_end"])].append(("period_end", sub["id"]))
                self.touch("stripe/subscriptions", sub)
            else:
                self.start_paid_period(sub, day, t, "subscription_cycle")
                self.touch("stripe/subscriptions", sub)
        elif kind == "retry":
            inv = self.invoices[oid]
            if inv["status"] == "open" and self.subs[inv["_sub"]]["status"] != "canceled":
                self.pay(inv, day, t, retry_index=inv["attempt_count"])
        elif kind == "refund":
            ch = self.charges[oid]
            ch.update(refunded=True, amount_refunded=ch["amount"])
            self.touch("stripe/charges", ch)
            self.touch("stripe/refunds", {"id": self.id("re_", 24), "object": "refund", "amount": ch["amount"], "charge": ch["id"],
                                          "currency": ch["currency"], "created": t, "reason": "requested_by_customer", "status": "succeeded"})

    def change_plan(self, sub, cust, day, plan=None, seats=None):
        item = sub["items"]["data"][0]
        old_price, old_qty = item["price"], item["quantity"]
        old_amount = old_price["unit_amount"] * old_qty
        t = ts(day, self.rng.randint(0, 86399))
        if plan:
            sub["_plan"] = plan
            item["price"] = self.price_ref(self.price_index[(plan, sub["_interval"], cust["currency"])])
        if seats:
            if seats > item["quantity"]:
                for _ in range(seats - item["quantity"]):
                    uid = self.id("usr_", 10)
                    cust["_users"].append(uid)
                    self.track(cust, "invited_teammate", t, {"invitee_id": uid}, cust["_users"][0])
                self.track(cust, "seat_added", t + 5, {"seats_added": seats - item["quantity"], "seats_total": seats}, cust["_users"][0])
            item["quantity"] = seats
        new_amount = item["price"]["unit_amount"] * item["quantity"]
        if new_amount > old_amount and sub["status"] == "active":
            frac = (sub["current_period_end"] - t) / (sub["current_period_end"] - sub["current_period_start"])
            lines = [(-round(old_amount * frac), {"price": old_price, "quantity": old_qty}, t, sub["current_period_end"], True),
                     (round(new_amount * frac), item, t, sub["current_period_end"], True)]
            inv = self.invoice(sub, day, t, "subscription_update", lines)
            self.pay(inv, day, t)
        self.touch("stripe/subscriptions", sub)

    def daily_subs(self, day):
        order = ["starter", "pro", "business"]
        for cust in list(self.customers.values()):
            sid = cust["_live_sub"]
            if sid is None:
                if cust["id"] in self.ever_paid and self.daily(C.REACTIVATION):
                    plan = cust["_last_paid_plan"]
                    self.new_sub(cust, day, ts(day, self.rng.randint(0, 86399)), plan, "month", self.rng.randint(*C.SEATS[plan]), trial=False)
                continue
            sub = self.subs[sid]
            if sub["_plan"] == "free":
                if self.daily(C.FREE_UPGRADE[cust["_activated"]]):
                    plan = self.pick({"starter": 0.6, "pro": 0.35, "business": 0.05})
                    sub["_plan"], sub["_interval"] = plan, "year" if self.rng.random() < 0.2 else "month"
                    item = sub["items"]["data"][0]
                    item["price"] = self.price_ref(self.price_index[(plan, sub["_interval"], cust["currency"])])
                    item["quantity"] = self.rng.randint(*C.SEATS[plan])
                    self.start_paid_period(sub, day, ts(day, self.rng.randint(0, 86399)), "subscription_update")
                    self.touch("stripe/subscriptions", sub)
                elif self.daily(C.FREE_CANCEL):
                    self.end_sub(sub, day, ts(day, self.rng.randint(0, 86399)), "cancellation_requested")
            elif sub["status"] == "active" and not sub["cancel_at_period_end"]:
                seats = sub["items"]["data"][0]["quantity"]
                i = order.index(sub["_plan"])
                if self.daily(C.SEAT_ADD):
                    self.change_plan(sub, cust, day, seats=seats + self.rng.randint(1, max(1, seats // 3)))
                elif sub["_interval"] == "month":
                    if self.daily(C.SEAT_REMOVE) and seats > 1:
                        self.change_plan(sub, cust, day, seats=max(1, seats - self.rng.randint(1, max(1, seats // 5))))
                    elif self.daily(C.UPGRADE) and i < 2:
                        self.change_plan(sub, cust, day, plan=order[i + 1])
                    elif self.daily(C.DOWNGRADE) and i > 0:
                        self.change_plan(sub, cust, day, plan=order[i - 1])
                    elif self.daily(C.TO_FREE):
                        sub["_plan"], sub["_churning"] = "free", False
                        item = sub["items"]["data"][0]
                        item["price"] = self.price_ref(self.price_index[("free", "month", cust["currency"])])
                        item["quantity"] = 1
                        self.touch("stripe/subscriptions", sub)
            if cust["_live_sub"]:
                live = self.subs[cust["_live_sub"]]
                rate = C.USAGE_PER_DAY["free" if live["_plan"] == "free" else "paid"]
                in_onboarding = (day - cust["_signup_day"]).days < C.TRIAL_DAYS
                features = [f for f in C.FEATURES if not (in_onboarding and not cust["_activated"] and f == C.KEY_FEATURE)]
                for _ in range(self.poisson(rate)):
                    self.track(cust, "feature_used", ts(day, self.rng.randint(0, 86399)), {"feature": self.rng.choice(features)})

    def snapshot_mrr(self, day):
        month = day.strftime("%Y-%m")
        at = ts(day, 86399)
        for cust in self.customers.values():
            total = 0.0
            sid = cust["_live_sub"]
            if sid:
                sub = self.subs[sid]
                if sub["status"] in ("active", "past_due"):
                    amount = self.sub_amount(sub) / (12 if sub["_interval"] == "year" else 1)
                    total = amount * (1 - self.discount_pct(sub, at) / 100)
            if total > 0:
                self.mrr[(month, cust["id"])] = round(total)

    # ---------- main loop ----------
    def run(self):
        day = C.START
        while day <= self.until:
            if day == C.START:
                self.create_catalog(day)
            if day == C.PRICE_INCREASE:
                self.price_increase(day)
            months = (day.year - C.START.year) * 12 + day.month - C.START.month
            for _ in range(self.poisson(C.SIGNUPS_START + C.SIGNUPS_GROWTH * months)):
                self.signup(day)
            for kind, oid in self.tasks.pop(day, []):
                self.run_task(kind, oid, day)
            self.daily_subs(day)
            self.flush(day)
            if is_month_end(day):
                self.snapshot_mrr(day)
            day += timedelta(days=1)

    def ground_truth(self):
        months = sorted({m for m, _ in self.mrr})
        rows, seen = [], set()
        custs = sorted({c for _, c in self.mrr})
        for m_i, m in enumerate(months):
            prev_m = months[m_i - 1] if m_i else None
            for c in custs:
                cur = self.mrr.get((m, c), 0)
                prev = self.mrr.get((prev_m, c), 0) if prev_m else 0
                if not cur and not prev:
                    continue
                if prev == 0:
                    movement = "reactivation" if c in seen else "new"
                elif cur == 0:
                    movement = "churn"
                elif cur > prev:
                    movement = "expansion"
                elif cur < prev:
                    movement = "contraction"
                else:
                    movement = "retained"
                if cur:
                    seen.add(c)
                rows.append((m, c, self.customers[c]["currency"], cur / 100, prev / 100, movement))
        return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--until", type=date.fromisoformat, default=date.today() - timedelta(days=1))
    ap.add_argument("--backfill", action="store_true", help="write every day's files, not only --until")
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parent.parent / "landing")
    a = ap.parse_args()

    sim = Sim(a.until)
    sim.run()
    first = C.START if a.backfill else a.until
    written = 0
    for (day, path), lines in sorted(sim.out.items()):
        if first <= day <= a.until:
            f = a.out / path / f"{day.isoformat()}.jsonl"
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("\n".join(lines) + "\n")
            written += len(lines)
    gt = a.out / "ground_truth" / "mrr_monthly.csv"
    gt.parent.mkdir(parents=True, exist_ok=True)
    with gt.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["month", "customer_id", "currency", "mrr", "previous_mrr", "movement"])
        for m, c, cur, mrr, prev, mv in sim.ground_truth():
            w.writerow([m, c, cur, f"{mrr:.2f}", f"{prev:.2f}", mv])
    print(f"{len(sim.customers)} customers, {written} records written to {a.out}")


if __name__ == "__main__":
    main()
