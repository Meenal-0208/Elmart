"""
simulation.py
-------------
The live "business engine" behind the dashboard. Every tick (called by a
NiceGUI ui.timer every 2-3 seconds) this module:
  * spawns new customers (accelerated simulated clock, up to 100,000/day)
  * turns some of those customers into purchases
  * occasionally creates returns
  * randomly restocks / depletes inventory
  * starts & ends flash sales
  * nudges selling prices up/down slightly (market fluctuation)
  * accrues fixed business expenses (staff, rent, utilities, marketing, logistics)
  * keeps a rolling revenue/profit history used by the charts

A single shared `SimulationState` instance is created once in app.py and
imported by store.py / dashboard.py so every part of the UI reacts to the
same live numbers.
"""
from __future__ import annotations

import random
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np

from database import Database

# ----------------------------------------------------------------------------
# Business constants
# ----------------------------------------------------------------------------
INITIAL_BUDGET = 20_00_000.0  # ₹20,00,000

EMPLOYEES = 5
SALARY_PER_EMPLOYEE_PER_DAY = 1500.0
RENT_PER_DAY = 3000.0
UTILITIES_PER_DAY = 800.0
MARKETING_PER_DAY = 2200.0
LOGISTICS_PER_DAY = 1600.0

DAILY_EXPENSE_TOTAL = (
    EMPLOYEES * SALARY_PER_EMPLOYEE_PER_DAY
    + RENT_PER_DAY + UTILITIES_PER_DAY + MARKETING_PER_DAY + LOGISTICS_PER_DAY
)

MAX_CUSTOMERS_PER_DAY = 100_000
SIM_MINUTES_PER_TICK = 6  # accelerated clock: ~4 hours pass every 60 real seconds

# How often app.py's ui.timer actually calls SimulationState.tick(), in real
# seconds. Defined here (rather than in app.py) so any module - like the
# storefront's flash-sale countdown - can convert "ticks remaining" into a
# real wall-clock duration without importing app.py (which would be circular).
SIMULATION_INTERVAL_SECONDS = 2.5


@dataclass
class HistoryPoint:
    ts: datetime
    revenue: float
    profit: float
    orders: int


@dataclass
class SimulationState:
    db: Database

    sim_clock: datetime = field(default_factory=lambda: datetime.now().replace(
        hour=8, minute=0, second=0, microsecond=0))
    sim_day: int = 0

    cumulative_expenses: float = 0.0
    ticks: int = 0

    history: deque = field(default_factory=lambda: deque(maxlen=200))
    active_flash_sales: dict = field(default_factory=dict)  # product_id -> ticks_remaining
    recent_events: deque = field(default_factory=lambda: deque(maxlen=12))

    def __post_init__(self):
        self.history.append(HistoryPoint(self.sim_clock, 0.0, 0.0, 0))

    # ------------------------------------------------------------------ #
    # derived KPIs
    # ------------------------------------------------------------------ #
    @property
    def revenue(self) -> float:
        return self.db.total_revenue() - self.db.total_returns_value()

    @property
    def cogs(self) -> float:
        return self.db.total_cogs()

    @property
    def gross_profit(self) -> float:
        return self.revenue - self.cogs

    @property
    def net_profit(self) -> float:
        return self.gross_profit - self.cumulative_expenses

    @property
    def budget_remaining(self) -> float:
        return INITIAL_BUDGET + self.net_profit

    @property
    def orders(self) -> int:
        return self.db.order_count()

    @property
    def customers_today(self) -> int:
        return self.db.customers_today(self.sim_day)

    @property
    def inventory_value(self) -> float:
        return self.db.inventory_value()

    @property
    def inventory_health(self) -> float:
        return self.db.inventory_health_pct()

    # ------------------------------------------------------------------ #
    # simulation tick
    # ------------------------------------------------------------------ #
    def tick(self) -> None:
        self.ticks += 1
        prev_day = self.sim_day
        self.sim_clock += timedelta(minutes=SIM_MINUTES_PER_TICK)
        self.sim_day = (self.sim_clock - self.sim_clock.replace(
            hour=0, minute=0, second=0, microsecond=0)).days + self._day_offset()

        # detect a simulated day rollover using an internal counter instead of
        # relying on wall time, so the "day" always advances forward
        minutes_since_start = self.ticks * SIM_MINUTES_PER_TICK
        self.sim_day = minutes_since_start // (24 * 60)
        hour = (minutes_since_start // 60) % 24

        self._accrue_expenses()
        self._simulate_customers_and_orders(hour)
        self._simulate_returns()
        self._simulate_inventory_changes()
        self._simulate_flash_sales()
        self._simulate_price_updates()

        self.history.append(HistoryPoint(self.sim_clock, self.revenue, self.net_profit, self.orders))

    def _day_offset(self) -> int:
        return 0

    def _accrue_expenses(self) -> None:
        fraction_of_day = SIM_MINUTES_PER_TICK / (24 * 60)
        self.cumulative_expenses += DAILY_EXPENSE_TOTAL * fraction_of_day

    def _simulate_customers_and_orders(self, hour: int) -> None:
        # traffic shape: busier in morning/evening, quiet at night
        hourly_weight = {
            0: 0.1, 1: 0.05, 2: 0.05, 3: 0.05, 4: 0.05, 5: 0.1,
            6: 0.3, 7: 0.6, 8: 0.9, 9: 1.1, 10: 1.3, 11: 1.4,
            12: 1.5, 13: 1.4, 14: 1.2, 15: 1.2, 16: 1.3, 17: 1.5,
            18: 1.8, 19: 2.0, 20: 1.9, 21: 1.4, 22: 0.8, 23: 0.3,
        }.get(hour, 1.0)

        ticks_per_day = max(1, (24 * 60) // SIM_MINUTES_PER_TICK)
        base_customers_per_tick = MAX_CUSTOMERS_PER_DAY / ticks_per_day
        expected = base_customers_per_tick * hourly_weight / 1.1
        new_customers = int(np.random.poisson(max(expected, 0.1)))
        new_customers = max(0, new_customers)

        self.db.log_customers(self.sim_day, hour, new_customers)

        # only a fraction of customers convert into a purchase this tick
        conversion_rate = 0.028
        num_orders = int(np.random.binomial(max(new_customers, 0), conversion_rate)) if new_customers else 0
        num_orders = min(num_orders, 40)  # cap per-tick order creation for performance

        if num_orders <= 0:
            return

        products = self.db.weighted_random_products(num_orders)
        customer_ids = self.db.random_customer_ids(len(products))
        for (_, prod), customer_id in zip(products.iterrows(), customer_ids):
            qty_available = int(prod["quantity"])
            if qty_available <= 0:
                continue
            qty = min(random.randint(1, 3), qty_available)
            unit_price = float(prod["selling_price"])
            if prod["discount"] and prod["discount"] > 0:
                unit_price = round(unit_price * (1 - prod["discount"] / 100.0), 2)
            unit_cost = float(prod["cost_price"])
            total = round(unit_price * qty, 2)
            profit = round((unit_price - unit_cost) * qty, 2)

            self.db.insert_order({
                "order_id": uuid.uuid4().hex[:10],
                "product_id": prod["id"],
                "product_name": prod["name"],
                "category": prod["category"],
                "quantity": qty,
                "unit_price": unit_price,
                "unit_cost": unit_cost,
                "total": total,
                "profit": profit,
                "is_return": False,
                "manual": False,
                "ts": self.sim_clock,
                "customer_id": customer_id,
            })
            self.db.adjust_quantity(prod["id"], -qty)
            self.db.record_customer_order(customer_id, total, self.sim_clock)

        if num_orders:
            self._log_event(f"🛒 {num_orders} new order(s) placed")

    def _simulate_returns(self) -> None:
        orders_df = self.db.get_orders_df()
        if orders_df.empty:
            return
        non_returns = orders_df[~orders_df["is_return"]]
        if non_returns.empty:
            return
        if random.random() < 0.18:
            row = non_returns.sample(1).iloc[0]
            self.db.insert_order({
                "order_id": uuid.uuid4().hex[:10],
                "product_id": row["product_id"],
                "product_name": row["product_name"],
                "category": row["category"],
                "quantity": int(row["quantity"]),
                "unit_price": float(row["unit_price"]),
                "unit_cost": float(row["unit_cost"]),
                "total": -float(row["total"]),
                "profit": -float(row["profit"]),
                "is_return": True,
                "manual": False,
                "ts": self.sim_clock,
                "customer_id": row.get("customer_id", "GUEST"),
            })
            self.db.adjust_quantity(row["product_id"], int(row["quantity"]))
            self._log_event(f"↩️ Return processed for {row['product_name']}")

    def _simulate_inventory_changes(self) -> None:
        restock = self.db.random_products(random.randint(1, 4), only_in_stock=False)
        for _, prod in restock.iterrows():
            if prod["quantity"] < 40 and random.random() < 0.5:
                add_qty = random.randint(20, 120)
                self.db.adjust_quantity(prod["id"], add_qty)
                self._log_event(f"📦 Restocked {prod['name']} (+{add_qty})")

    def _simulate_flash_sales(self) -> None:
        # end expired flash sales
        expired = []
        for pid, remaining in self.active_flash_sales.items():
            remaining -= 1
            if remaining <= 0:
                self.db.set_flash_sale(pid, False)
                expired.append(pid)
            else:
                self.active_flash_sales[pid] = remaining
        for pid in expired:
            del self.active_flash_sales[pid]

        # start new flash sales occasionally
        if random.random() < 0.35 and len(self.active_flash_sales) < 15:
            candidates = self.db.random_products(random.randint(1, 3))
            for _, prod in candidates.iterrows():
                if prod["id"] not in self.active_flash_sales:
                    self.db.set_flash_sale(prod["id"], True)
                    self.active_flash_sales[prod["id"]] = random.randint(4, 10)
                    self._log_event(f"⚡ Flash sale started: {prod['name']}")

    def _simulate_price_updates(self) -> None:
        candidates = self.db.random_products(random.randint(2, 6), only_in_stock=False)
        for _, prod in candidates.iterrows():
            pct = np.random.uniform(-0.04, 0.05)
            self.db.nudge_price(prod["id"], pct)

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #
    def _log_event(self, text: str) -> None:
        self.recent_events.appendleft(f"{self.sim_clock.strftime('%H:%M')}  {text}")

    def budget_breakdown(self) -> dict:
        return {
            "Employees (5)": EMPLOYEES * SALARY_PER_EMPLOYEE_PER_DAY,
            "Rent": RENT_PER_DAY,
            "Utilities": UTILITIES_PER_DAY,
            "Marketing": MARKETING_PER_DAY,
            "Logistics": LOGISTICS_PER_DAY,
        }
