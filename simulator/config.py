from datetime import date

SEED = 20240101
START = date(2024, 1, 1)
SCHEMA_CHANGE = date(2025, 6, 1)
PRICE_INCREASE = date(2025, 3, 1)

COUNTRIES = {"ES": ("eur", 0.45), "GB": ("gbp", 0.30), "US": ("usd", 0.25)}
CHANNELS = {"organic": 0.40, "paid_search": 0.30, "referral": 0.20, "partner": 0.10}

# Signups per day ramp from SIGNUPS_START to SIGNUPS_START + SIGNUPS_GROWTH * months
SIGNUPS_START = 2.0
SIGNUPS_GROWTH = 0.06

PLAN_MIX = {"free": 0.35, "starter": 0.30, "pro": 0.25, "business": 0.10}
ANNUAL_SHARE = 0.25
SEATS = {"free": (1, 3), "starter": (2, 5), "pro": (3, 12), "business": (10, 40)}

# Monthly per-seat list prices in minor units; annual = 10x monthly
PRICES = {
    "starter": {"eur": 800, "gbp": 700, "usd": 900},
    "pro": {"eur": 1500, "gbp": 1300, "usd": 1600},
    "business": {"eur": 2500, "gbp": 2100, "usd": 2700},
}
PRO_PRICE_AFTER_INCREASE = {"eur": 1700, "gbp": 1500, "usd": 1800}

TRIAL_DAYS = 14
ACTIVATION_RATE = {"organic": 0.45, "paid_search": 0.35, "referral": 0.55, "partner": 0.60}
TRIAL_CONVERSION = {True: 0.50, False: 0.15}

# Monthly voluntary churn probability by plan, multiplied by activation factor
MONTHLY_CHURN = {"starter": 0.035, "pro": 0.022, "business": 0.012}
ACTIVATION_CHURN_FACTOR = {True: 0.6, False: 1.5}
ANNUAL_CHURN_DISCOUNT = 0.5

# Monthly probabilities of in-life changes for paid subscriptions
SEAT_ADD = 0.10
SEAT_REMOVE = 0.025
UPGRADE = 0.02
DOWNGRADE = 0.005
TO_FREE = 0.002

# Free plan behaviour (monthly)
FREE_UPGRADE = {True: 0.04, False: 0.01}
FREE_CANCEL = 0.02

REACTIVATION = 0.015

COUPONS = {
    "WELCOME20": {"percent_off": 20.0, "duration": "repeating", "duration_in_months": 3},
    "PARTNER10": {"percent_off": 10.0, "duration": "forever", "duration_in_months": None},
}
WELCOME_COUPON_SHARE = 0.10

FIRST_PAYMENT_SUCCESS = 0.95
RETRY_DAYS = [3, 7, 14]
RETRY_SUCCESS = 0.27
REFUND_RATE = 0.008

FEATURES = ["timeline_view", "board_view", "report_export", "calendar_sync"]
KEY_FEATURE = "timeline_view"
USAGE_PER_DAY = {"free": 0.10, "paid": 0.25}

DUPLICATE_RATE = 0.01
LATE_EVENT_RATE = 0.03
