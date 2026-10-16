import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


EMAIL = "24f3001989@ds.study.iitm.ac.in"
QUESTION_ID = "q-ledger-agent-server"
API_URL = "https://exam.sanand.workers.dev/questionData"

QUIZ_SIGN = os.environ.get("QUIZ_SIGN")

CACHE_FILE = Path(__file__).with_name("orders_cache.json")

BUSINESS_TZ = ZoneInfo("Asia/Kolkata")

RATES = {
    "USD": 1.0,
    "EUR": 1.04,
    "INR": 0.01231,
}


app = FastAPI(title="Acme Appliances Ledger Agent")


class QuestionRequest(BaseModel):
    question: str


# ============================================================
# DATA
# ============================================================

def parse_timestamp(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"

    return datetime.fromisoformat(value)


def fetch_page(page: int) -> dict:
    if not QUIZ_SIGN:
        raise RuntimeError("QUIZ_SIGN is not set")

    params = {
        "email": EMAIL,
        "quizSign": QUIZ_SIGN,
        "questionId": QUESTION_ID,
        "path": "/orders",
        "page": page,
    }

    response = requests.get(
        API_URL,
        params=params,
        timeout=15,
    )

    response.raise_for_status()

    return response.json()


def download_orders():
    print("Downloading order ledger...")

    first = fetch_page(1)

    orders = list(first.get("orders", []))

    pages = int(first.get("pages", 1))

    for page in range(2, pages + 1):
        print(f"Downloading {page}/{pages}")
        data = fetch_page(page)
        orders.extend(data.get("orders", []))

    # Keep latest version of each order.
    latest = {}

    for order in orders:
        oid = order["id"]

        if oid not in latest:
            latest[oid] = order
            continue

        old_time = parse_timestamp(
            latest[oid]["updated_at"]
        )

        new_time = parse_timestamp(
            order["updated_at"]
        )

        if new_time > old_time:
            latest[oid] = order

    result = list(latest.values())

    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, separators=(",", ":"))

    print(f"Saved {len(result)} orders.")

    return result


def load_orders():
    if not CACHE_FILE.exists():
        raise RuntimeError(
            "orders_cache.json missing. "
            "Run: python server.py --download"
        )

    with open(CACHE_FILE, "r", encoding="utf-8") as f:
        return tuple(json.load(f))


# ============================================================
# MONEY / DATE
# ============================================================

def usd(order):
    return float(order["amount"]) * RATES[order["currency"]]


def round_money(value):
    return round(float(value) + 1e-9, 2)


def business_date(order):
    return parse_timestamp(
        order["created_at"]
    ).astimezone(BUSINESS_TZ)


# ============================================================
# QUESTION PARSING
# ============================================================

MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


REGIONS = [
    "North",
    "South",
    "East",
    "West",
    "Central",
]


def clean(q):
    return re.sub(
        r"\s+",
        " ",
        q.lower().strip(),
    )


def find_year(q):
    m = re.search(r"\b(20\d{2})\b", q)

    return int(m.group(1)) if m else None


def find_month(q):
    for name, number in MONTHS.items():
        if re.search(
            rf"\b{name}\b",
            q,
        ):
            return number

    return None


def find_region(q):
    for region in REGIONS:
        if re.search(
            rf"\b{region.lower()}\b",
            q,
        ):
            return region

    return None


def find_customer(q):
    m = re.search(
        r"\bc\d+\b",
        q,
        re.IGNORECASE,
    )

    return m.group(0).upper() if m else None


def find_product(q, orders):
    products = sorted(
        {
            order["product"]
            for order in orders
        },
        key=len,
        reverse=True,
    )

    for product in products:
        if product.lower() in q:
            return product

    return None


# ============================================================
# FILTERS
# ============================================================

def filter_orders(orders, q):

    year = find_year(q)
    month = find_month(q)
    region = find_region(q)
    customer = find_customer(q)
    product = find_product(q, orders)

    result = []

    for order in orders:

        dt = business_date(order)

        if year is not None:
            if dt.year != year:
                continue

        if month is not None:
            if dt.month != month:
                continue

        if region is not None:
            if order["region"].lower() != region.lower():
                continue

        if customer is not None:
            if order["customer"].upper() != customer:
                continue

        if product is not None:
            if order["product"].lower() != product.lower():
                continue

        result.append(order)

    return result


# ============================================================
# STATUS
# ============================================================

def is_paid(order):
    return order["status"].lower() == "paid"


def is_refunded(order):
    return order["status"].lower() in {
        "refunded",
        "refund",
    }


# ============================================================
# INTENT DETECTION
# ============================================================

def wants_average(q):
    return (
        "average" in q
        or "avg" in q
        or "on average" in q
        or "per order" in q
        and (
            "worth" in q
            or "value" in q
        )
    )


def wants_refund(q):
    return any(
        word in q
        for word in [
            "refund",
            "refunded",
            "refunding",
        ]
    )


def wants_count(q):
    return any(
        phrase in q
        for phrase in [
            "how many",
            "number of",
            "count",
            "number",
        ]
    )


def wants_units(q):
    return any(
        phrase in q
        for phrase in [
            "how many units",
            "units sold",
            "quantity",
            "units",
        ]
    )


def wants_product_ranking(q):
    return any(
        phrase in q
        for phrase in [
            "top-selling",
            "top selling",
            "best-selling",
            "best selling",
            "highest-selling",
            "highest selling",
            "most sold",
            "best product",
            "top product",
            "which product",
            "what product",
        ]
    )


def wants_customer_count(q):
    return (
        "customers" in q
        and wants_count(q)
    )


def wants_order_count(q):
    return (
        "orders" in q
        and wants_count(q)
    )


def wants_revenue(q):
    return any(
        phrase in q
        for phrase in [
            "revenue",
            "earned",
            "earn",
            "sales",
            "turnover",
            "income",
            "made",
        ]
    )


# ============================================================
# CALCULATIONS
# ============================================================

def paid_orders(orders):
    return [
        order
        for order in orders
        if is_paid(order)
    ]


def revenue(orders):
    return round_money(
        sum(
            usd(order)
            for order in paid_orders(orders)
        )
    )


def refund_amount(orders):
    return round_money(
        sum(
            usd(order)
            for order in orders
            if is_refunded(order)
        )
    )


def refund_count(orders):
    return sum(
        1
        for order in orders
        if is_refunded(order)
    )


def order_count(orders):
    return len(
        paid_orders(orders)
    )


def unit_count(orders):
    return sum(
        int(order["qty"])
        for order in paid_orders(orders)
    )


def customer_count(orders):
    return len(
        {
            order["customer"]
            for order in paid_orders(orders)
        }
    )


def average_order_value(orders):

    paid = paid_orders(orders)

    if not paid:
        return 0.0

    return round_money(
        sum(
            usd(order)
            for order in paid
        )
        / len(paid)
    )


def product_revenue(orders):

    totals = {}

    for order in paid_orders(orders):

        product = order["product"]

        totals[product] = (
            totals.get(product, 0)
            + usd(order)
        )

    if not totals:
        return None

    return max(
        totals,
        key=totals.get,
    )


def product_units(orders):

    totals = {}

    for order in paid_orders(orders):

        product = order["product"]

        totals[product] = (
            totals.get(product, 0)
            + int(order["qty"])
        )

    if not totals:
        return None

    return max(
        totals,
        key=totals.get,
    )


# ============================================================
# ANSWER ENGINE
# ============================================================

def answer_question(question):

    q = clean(question)

    orders = ORDERS

    filtered = filter_orders(
        orders,
        q,
    )

    # 1. Average value has priority.
    # This fixes phrases such as:
    # "On average, how many US dollars is a paid South order worth?"
    if wants_average(q):

        return average_order_value(
            filtered
        )

    # 2. Product ranking
    if wants_product_ranking(q):

        # If explicitly about units,
        # rank by quantity.
        if wants_units(q):
            return product_units(filtered)

        # Otherwise "top-selling" means
        # highest revenue.
        return product_revenue(filtered)

    # 3. Refunds
    if wants_refund(q):

        if wants_count(q):
            return refund_count(filtered)

        return refund_amount(filtered)

    # 4. Customer count
    if wants_customer_count(q):
        return customer_count(filtered)

    # 5. Order count
    if wants_order_count(q):
        return order_count(filtered)

    # 6. Units
    if wants_units(q):
        return unit_count(filtered)

    # 7. Revenue
    if wants_revenue(q):
        return revenue(filtered)

    raise ValueError(
        f"Could not determine question type: {question}"
    )


# ============================================================
# HTTP
# ============================================================

try:
    ORDERS = load_orders()

    print(
        f"Loaded {len(ORDERS)} orders."
    )

except Exception as exc:

    print(
        "ERROR loading orders:",
        exc,
    )

    ORDERS = tuple()


@app.get("/")
def health():
    return {
        "status": "ok",
        "orders_loaded": len(ORDERS),
    }


@app.post("/")
def ask(request: QuestionRequest):

    if not ORDERS:
        raise HTTPException(
            status_code=503,
            detail="Order data is unavailable",
        )

    try:

        answer = answer_question(
            request.question
        )

        return {
            "answer": answer
        }

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )


# ============================================================
# CACHE GENERATION
# ============================================================

if __name__ == "__main__":

    if (
        len(sys.argv) > 1
        and sys.argv[1] == "--download"
    ):
        download_orders()

    else:
        print(
            "Run with:"
        )
        print(
            "python server.py --download"
        )