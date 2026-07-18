"""
customers.py
-------------
Generates the synthetic CRM customer base for Elmart using Faker.

Each customer starts out in the "New" segment with zero orders/spend. As the
business simulation (simulation.py) and the shopper's own checkout (store.py)
create orders against these customers, Database.record_customer_order()
updates their order count, lifetime spend, last-order timestamp and segment
(New -> Regular -> VIP) live, so the CRM Assistant chatbot always answers
from real, current data rather than a static seed.

One special customer, CUST-YOU, represents the person using the Elmart
storefront in this browser tab - every "Add to Cart" checkout is booked
against that profile, so questions like "find customer You" reflect the
shopper's own purchases.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta

import pandas as pd
from faker import Faker

fake = Faker()
Faker.seed(7)
random.seed(7)

CITIES = [
    "Mumbai", "Delhi", "Bengaluru", "Hyderabad", "Chennai", "Kolkata", "Pune",
    "Ahmedabad", "Jaipur", "Lucknow", "Surat", "Indore", "Nagpur", "Kochi",
    "Chandigarh", "Bhopal", "Patna", "Coimbatore",
]


def generate_customers(n: int = 150) -> pd.DataFrame:
    """Builds a fresh CRM customer roster (all starting at zero activity)."""
    now = datetime.now()
    rows = []
    for i in range(n):
        name = fake.name()
        slug = name.lower().replace(" ", ".").replace("'", "")
        rows.append({
            "customer_id": f"CUST{i + 1:04d}",
            "name": name,
            "email": f"{slug}{random.randint(1, 999)}@example.com",
            "phone": fake.phone_number(),
            "city": random.choice(CITIES),
            "segment": "New",
            "joined_date": now - timedelta(days=random.randint(10, 720)),
            "total_orders": 0,
            "total_spent": 0.0,
            "last_order_ts": pd.NaT,
            "loyalty_points": 0,
        })

    # The shopper using the storefront in this tab - all of their real
    # checkouts land on this profile.
    rows.append({
        "customer_id": "CUST-YOU",
        "name": "You (Storefront Shopper)",
        "email": "you@elmart.local",
        "phone": "-",
        "city": "Delhi NCR",
        "segment": "New",
        "joined_date": now,
        "total_orders": 0,
        "total_spent": 0.0,
        "last_order_ts": pd.NaT,
        "loyalty_points": 0,
    })

    return pd.DataFrame(rows)
