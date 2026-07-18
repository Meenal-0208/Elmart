"""
chatbot.py
----------
"CRM Assistant" - a rule-based chatbot embedded in the admin dashboard.

It runs entirely offline (no external API calls, no network needed): each
question typed by the admin is matched against a small set of CRM/business
intents with plain keyword/regex matching, and answered live from the same
DuckDB database and SimulationState the rest of the dashboard uses - so the
numbers it gives always match what's on screen.

Add new capabilities by appending (pattern, handler) pairs to `_INTENTS`.
"""
from __future__ import annotations

import re

import pandas as pd

from database import Database
from simulation import SimulationState


def _fmt_inr(value: float) -> str:
    return f"₹{value:,.0f}"


class CRMChatbot:
    """Keyword/intent-matching CRM assistant backed by live store data."""

    def __init__(self, db: Database, state: SimulationState):
        self.db = db
        self.state = state
        # Order matters: first matching pattern wins, so more specific
        # intents are listed before their more general neighbours.
        self._intents = [
            (r"\bhelp\b|\bwhat can you do\b|\bexamples?\b", self._help),
            (r"\b(hi|hello|hey)\b", self._greet),
            (r"\binactive\b|\bat risk\b|\blapsed\b|\bchurn", self._inactive_customers),
            (r"\bfind\b|\blook ?up\b|\bsearch\b", self._find_customer),
            (r"\btop\b.*\bcustomers?\b|\bbest customers?\b|\bvips?\b", self._top_customers),
            (r"\bsegment", self._segments),
            (r"\bhow many customers?\b|\btotal customers?\b|\bcustomer count\b", self._customer_count),
            (r"\bnew customers?\b", self._new_customers),
            (r"\btop\b.*\bproducts?\b|\bbest.?sell", self._top_products),
            (r"\bcategory\b|\bcategories\b", self._revenue_by_category),
            (r"\blow stock\b|\bout of stock\b|\brestock\b|\binventory\b", self._inventory),
            (r"\baverage order\b|\baov\b", self._aov),
            (r"\bprofit\b", self._profit),
            (r"\brevenue\b|\bsales\b", self._revenue),
            (r"\border", self._orders),
            (r"\bbudget\b", self._budget),
        ]

    def answer(self, text: str) -> str:
        q = (text or "").strip().lower()
        if not q:
            return "Ask me something about your customers, sales, or inventory 🙂"
        for pattern, handler in self._intents:
            if re.search(pattern, q):
                try:
                    return handler(q)
                except Exception:
                    return "I hit a snag pulling that up — try rephrasing your question."
        return self._fallback()

    # ------------------------------------------------------------------ #
    # intent handlers
    # ------------------------------------------------------------------ #
    def _greet(self, q: str) -> str:
        return ("Hi! I'm your CRM Assistant. Ask me about customers, revenue, "
                "top products, or inventory — or tap a suggestion below.")

    def _help(self, q: str) -> str:
        return (
            "Here's what I can help with:\n"
            "• \"Who are my top 5 customers?\"\n"
            "• \"How many customers do we have?\"\n"
            "• \"Show customer segments\"\n"
            "• \"Which customers are inactive?\"\n"
            "• \"Find customer <name>\"\n"
            "• \"What's today's revenue and profit?\"\n"
            "• \"Top selling products\"\n"
            "• \"Revenue by category\"\n"
            "• \"Any low stock items?\"\n"
            "• \"Budget remaining?\""
        )

    def _top_customers(self, q: str) -> str:
        m = re.search(r"top\s+(\d+)", q)
        limit = max(1, min(int(m.group(1)) if m else 5, 20))
        df = self.db.top_customers(limit)
        if df.empty:
            return "No customer purchase history yet — give the simulation a few ticks."
        lines = [f"🏆 Top {len(df)} customers by lifetime spend:"]
        for i, row in enumerate(df.itertuples(), start=1):
            lines.append(
                f"{i}. {row.name} ({row.segment}) — {_fmt_inr(row.total_spent)} "
                f"across {int(row.total_orders)} orders"
            )
        return "\n".join(lines)

    def _customer_count(self, q: str) -> str:
        n = self.db.customer_count()
        seg = self.db.segment_counts()
        seg_txt = ", ".join(f"{r.segment}: {int(r.count)}" for r in seg.itertuples())
        return f"We have {n:,} customers on file. Breakdown — {seg_txt}."

    def _segments(self, q: str) -> str:
        seg = self.db.segment_counts()
        if seg.empty:
            return "No customer data yet."
        lines = ["📊 Customer segments:"]
        for r in seg.itertuples():
            lines.append(f"• {r.segment}: {int(r.count)} customers, {_fmt_inr(r.total_spent)} total spend")
        return "\n".join(lines)

    def _inactive_customers(self, q: str) -> str:
        df = self.db.get_customers_df()
        active = df[df["total_orders"] > 0].copy()
        if active.empty:
            return "No repeat customers yet, so nobody to flag as inactive."
        now = self.state.sim_clock
        active["days_since"] = active["last_order_ts"].apply(
            lambda ts: (now - pd.to_datetime(ts)).days if pd.notnull(ts) else 999
        )
        at_risk = active[active["days_since"] >= 3].sort_values("days_since", ascending=False)
        if at_risk.empty:
            return "Good news — no customers look inactive right now."
        lines = [f"⚠️ {len(at_risk)} customer(s) haven't ordered in 3+ simulated days:"]
        for r in at_risk.head(8).itertuples():
            lines.append(f"• {r.name} — last order {int(r.days_since)}d ago ({r.segment})")
        return "\n".join(lines)

    def _find_customer(self, q: str) -> str:
        term = q
        for kw in ("find me", "look up", "lookup", "find", "search for", "search",
                   "customer named", "named", "customer", "up", "for", "a", "an", "the"):
            term = re.sub(rf"\b{re.escape(kw)}\b", " ", term)
        term = re.sub(r"[^a-z0-9 .'\-]", " ", term).strip()
        term = re.sub(r"\s+", " ", term)
        if not term:
            term = q.split()[-1]
        df = self.db.search_customers(term)
        if df.empty:
            return f"I couldn't find a customer matching \"{term}\". Try a first name or city."
        r = df.iloc[0]
        last_order = (pd.to_datetime(r["last_order_ts"]).strftime("%d %b %Y")
                      if pd.notnull(r["last_order_ts"]) else "never")
        extra = ""
        if len(df) > 1:
            extra = f"\n(+{len(df) - 1} more match{'es' if len(df) > 2 else ''} — try a more specific name)"
        return (
            f"👤 {r['name']} ({r['customer_id']}) — {r['segment']} · {r['city']}\n"
            f"Orders: {int(r['total_orders'])} · Spend: {_fmt_inr(r['total_spent'])} · "
            f"Loyalty pts: {int(r['loyalty_points'])} · Last order: {last_order}{extra}"
        )

    def _revenue(self, q: str) -> str:
        return f"💰 Revenue so far: {_fmt_inr(self.state.revenue)} · Gross profit: {_fmt_inr(self.state.gross_profit)}"

    def _profit(self, q: str) -> str:
        return (f"📈 Net profit: {_fmt_inr(self.state.net_profit)} "
                f"(after expenses of {_fmt_inr(self.state.cumulative_expenses)})")

    def _orders(self, q: str) -> str:
        return f"🧾 {self.state.orders:,} orders placed so far · {self.state.customers_today:,} customers today"

    def _aov(self, q: str) -> str:
        orders = self.state.orders
        if orders == 0:
            return "No orders yet to calculate an average order value."
        return f"🧮 Average order value: {_fmt_inr(self.state.revenue / orders)}"

    def _top_products(self, q: str) -> str:
        m = re.search(r"top\s+(\d+)", q)
        limit = max(1, min(int(m.group(1)) if m else 5, 20))
        df = self.db.top_products(limit)
        if df.empty:
            return "No sales yet to rank products."
        lines = [f"🔥 Top {len(df)} products by revenue:"]
        for i, r in enumerate(df.itertuples(), start=1):
            lines.append(f"{i}. {r.product_name} — {_fmt_inr(r.revenue)} ({int(r.units)} units)")
        return "\n".join(lines)

    def _revenue_by_category(self, q: str) -> str:
        df = self.db.revenue_by_category()
        if df.empty:
            return "No category revenue yet."
        lines = ["📦 Revenue by category:"]
        for r in df.head(8).itertuples():
            lines.append(f"• {r.category}: {_fmt_inr(r.revenue)}")
        return "\n".join(lines)

    def _inventory(self, q: str) -> str:
        counts = self.db.inventory_status_counts()
        lines = ["🏬 Inventory status:"]
        for r in counts.itertuples():
            lines.append(f"• {r.status}: {int(r.count)} products")
        lines.append(f"Overall inventory health: {self.state.inventory_health:.1f}%")
        return "\n".join(lines)

    def _budget(self, q: str) -> str:
        return f"🏦 Budget remaining: {_fmt_inr(self.state.budget_remaining)} of ₹20,00,000 initial"

    def _new_customers(self, q: str) -> str:
        df = self.db.get_customers_df()
        new_seg = df[df["segment"] == "New"]
        return (f"🆕 {len(new_seg)} customer(s) are currently in the 'New' segment "
                f"(haven't hit the Regular/VIP thresholds yet).")

    def _fallback(self) -> str:
        return ("I'm not sure about that one yet. Try asking about top customers, revenue, "
                "top products, inventory, or customer segments — or type \"help\" for examples.")
