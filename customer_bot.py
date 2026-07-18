"""
customer_bot.py
----------------
"Ask Elmart" - a live, rule-based customer support chatbot embedded in the
storefront itself (as opposed to chatbot.py's CRMChatbot, which is the
*admin's* internal assistant on the dashboard side).

Like the admin assistant, this runs entirely offline: no external API calls,
no network, no API key. Every answer is pulled straight from the same
DuckDB-backed Database and SimulationState the storefront and dashboard both
use, so "is this in stock", "where's my order" and "what's on sale" are
always answered with the exact live numbers the customer would see on the
page - never canned or made up.

Covers:
  - Product info & stock ("is the iPhone in stock", "how much is the Dell laptop")
  - Order status & tracking ("where's my order", "track ELM-AB12CD34")
  - Store policies (shipping, returns, payment methods)
  - Personalized product recommendations (trending / flash sale / top rated,
    optionally by category), using the shopper's own CRM segment for a
    personal touch
"""
from __future__ import annotations

import re

import pandas as pd

from database import Database
from products import CATEGORY_LIST
from simulation import SimulationState

# Mirrors the constants in store.py - duplicated here (rather than imported)
# to avoid a circular import between store.py and this module.
FREE_SHIPPING_THRESHOLD = 999.0
DELIVERY_ETA_MINUTES_OPTIONS = (30, 60)  # committed quick-commerce delivery window
SHOPPER_CUSTOMER_ID = "CUST-YOU"


def _fmt_inr(value: float) -> str:
    return f"₹{value:,.0f}"


def _strip_keywords(text: str, keywords: tuple[str, ...]) -> str:
    term = text
    for kw in keywords:
        term = re.sub(rf"\b{re.escape(kw)}\b", " ", term)
    term = re.sub(r"[^a-z0-9 .'\-]", " ", term)
    return re.sub(r"\s+", " ", term).strip()


class CustomerAssistant:
    """Keyword/intent-matching assistant for shoppers, backed by live data."""

    def __init__(self, db: Database, state: SimulationState):
        self.db = db
        self.state = state
        self._intents = [
            (r"\bhelp\b|\bwhat can you do\b|\bexamples?\b", self._help),
            (r"\b(hi|hello|hey)\b", self._greet),
            (r"\btrack\b|\bwhere.?s my order\b|\border status\b|\bmy orders?\b|"
             r"\bdelivery status\b", self._order_status),
            (r"\bshipping\b|\bfree shipping\b|\bdelivery time\b|\bhow long.*deliver", self._shipping_policy),
            (r"\breturn\b|\brefund\b|\bexchange\b|\bcancel\b", self._return_policy),
            (r"\bpayment\b|\bcash on delivery\b|\bcod\b|\bupi\b|\bcard\b|\bbilldesk\b", self._payment_policy),
            (r"\brecommend\b|\bsuggest\b|\bwhat should i buy\b|\bdeals?\b|\boffers?\b|"
             r"\bsales?\b|\btrending\b", self._recommend),
            (r"\bin stock\b|\bavailable\b|\bhow much\b|\bprice of\b|\bcost of\b|"
             r"\bdo you have\b|\bstock\b", self._stock_and_price),
        ]

    def answer(self, text: str) -> str:
        q = (text or "").strip().lower()
        if not q:
            return "Ask me about a product, your order, or our shipping & return policies 🙂"
        for pattern, handler in self._intents:
            if re.search(pattern, q):
                try:
                    return handler(q)
                except Exception:
                    return "I hit a snag looking that up — try rephrasing your question."
        return self._fallback(q)

    # ------------------------------------------------------------------ #
    # intent handlers
    # ------------------------------------------------------------------ #
    def _greet(self, q: str) -> str:
        return ("Hi, I'm the Elmart Assistant! Ask me if something's in stock, "
                "where your order is, our shipping/return policies, or for a "
                "recommendation.")

    def _help(self, q: str) -> str:
        return (
            "Here's what I can help with:\n"
            "• \"Is the Dell laptop in stock?\" / \"How much is the iPhone?\"\n"
            "• \"Where's my order?\" / \"Track ELM-AB12CD34\"\n"
            "• \"What's your shipping policy?\"\n"
            "• \"What's your return policy?\"\n"
            "• \"What payment methods do you accept?\"\n"
            "• \"Recommend something for me\" / \"Any deals on laptops?\""
        )

    def _stock_and_price(self, q: str) -> str:
        term = _strip_keywords(q, (
            "is", "the", "in", "stock", "available", "how", "much", "is the",
            "price", "of", "cost", "do", "you", "have", "a", "an", "for",
        ))
        if not term:
            return "Which product would you like me to check?"
        df = self.db.search_products(term, limit=3)
        if df.empty:
            return f"I couldn't find a product matching \"{term}\". Try a brand or product name."
        lines = []
        for r in df.itertuples():
            price = r.selling_price
            if r.discount and r.discount > 0:
                price = round(price * (1 - r.discount / 100.0), 2)
                price_txt = f"{_fmt_inr(price)} (was {_fmt_inr(r.selling_price)}, -{int(r.discount)}%)"
            else:
                price_txt = _fmt_inr(price)
            if r.quantity <= 0:
                stock_txt = "❌ Out of stock"
            elif r.quantity <= 15:
                stock_txt = f"⚠️ Only {int(r.quantity)} left"
            else:
                stock_txt = f"✅ In stock ({int(r.quantity)} units)"
            flags = []
            if r.flash_sale:
                flags.append("⚡ Flash Sale")
            if r.trending:
                flags.append("🔥 Trending")
            flag_txt = f" {' · '.join(flags)}" if flags else ""
            lines.append(f"**{r.name}** ({r.brand}) — {price_txt} · {stock_txt} · ⭐ {r.rating}{flag_txt}")
        return "\n".join(lines)

    def _order_status(self, q: str) -> str:
        m = re.search(r"\b(elm-[a-z0-9]+)\b", q)
        now = self.state.sim_clock
        if m:
            order = self.db.find_order(SHOPPER_CUSTOMER_ID, m.group(1).upper())
            if order is None:
                return f"I couldn't find an order matching \"{m.group(1).upper()}\"."
            return self._describe_order(order, now)

        orders = self.db.customer_orders(SHOPPER_CUSTOMER_ID, limit=5)
        if orders.empty:
            return "I don't see any orders on your account yet — once you check out, I can track it for you!"
        lines = [f"📦 Your last {len(orders)} order(s):"]
        for r in orders.itertuples():
            status = self._delivery_status(pd.to_datetime(r.ts), pd.to_datetime(r.delivery_date), now)
            lines.append(f"• #{r.confirmation_no} — {r.items} ({_fmt_inr(r.total)}) — {status}")
        return "\n".join(lines)

    def _describe_order(self, order, now) -> str:
        ts = pd.to_datetime(order["ts"])
        delivery_date = pd.to_datetime(order["delivery_date"])
        status = self._delivery_status(ts, delivery_date, now)
        payment_method = order.get("payment_method")
        payment_line = f"\nPaid via: {payment_method}" if payment_method else ""
        return (
            f"📦 Order #{order['confirmation_no']} — {order['items']} "
            f"({_fmt_inr(order['total'])})\n"
            f"Status: {status}\n"
            f"Committed delivery by: {delivery_date.strftime('%I:%M %p, %d %b')}"
            f"{payment_line}"
        )

    @staticmethod
    def _delivery_status(order_ts, delivery_date, now) -> str:
        if pd.isnull(delivery_date) or pd.isnull(order_ts):
            return "Processing"
        total_span = (delivery_date - order_ts).total_seconds()
        elapsed = (now - order_ts).total_seconds()
        progress = (elapsed / total_span) if total_span > 0 else 1.0
        if progress >= 1.0:
            return "✅ Delivered"
        elif progress >= 0.66:
            return "🚚 Out for delivery"
        elif progress >= 0.3:
            return "📦 Shipped"
        else:
            return "🛠️ Processing"

    def _shipping_policy(self, q: str) -> str:
        lo, hi = DELIVERY_ETA_MINUTES_OPTIONS
        return (
            f"⚡ Every order comes with a committed delivery time of either {lo} minutes or "
            f"{hi} minutes (1 hour), assigned at checkout. Orders above "
            f"{_fmt_inr(FREE_SHIPPING_THRESHOLD)} qualify for FREE delivery "
            f"(otherwise a small delivery fee applies at checkout)."
        )

    def _return_policy(self, q: str) -> str:
        return ("↩️ Most items can be returned within 7 days of delivery for a full refund, "
                "as long as they're unused and in original packaging. Refunds are credited "
                "back to your original payment method within 3-5 business days once the "
                "return is received.")

    def _payment_policy(self, q: str) -> str:
        return ("💳 We accept UPI, credit/debit cards, BillDesk (a secure third-party payment "
                "gateway covering cards/UPI/net banking), and Cash on Delivery (COD) on eligible "
                "orders. Payments are processed securely at checkout.")

    def _recommend(self, q: str) -> str:
        category = next((c for c in CATEGORY_LIST if c.lower() in q), None)

        if re.search(r"\bsales?\b|\bdeals?\b|\boffers?\b|\bflash\b", q):
            df = self.db.flash_sale_products(limit=5)
            heading = "⚡ Here's what's on Flash Sale right now:"
        elif re.search(r"\btrending\b", q):
            df = self.db.trending_products(limit=5)
            heading = "🔥 Trending with other shoppers right now:"
        else:
            df = self.db.top_rated_products(category=category, limit=5)
            heading = (f"⭐ Top-rated picks in {category}:" if category
                       else "⭐ Some of our top-rated picks:")

        if df.empty:
            df = self.db.top_rated_products(limit=5)
            heading = "⭐ Some of our top-rated picks:"
        if df.empty:
            return "I couldn't find anything to recommend right now — check back shortly!"

        customer = self.db.get_customer(SHOPPER_CUSTOMER_ID)
        intro = ""
        if customer is not None and customer["segment"] == "VIP":
            intro = "As one of our VIP shoppers, "
        elif customer is not None and customer["segment"] == "Regular":
            intro = "Since you shop with us often, "

        lines = [f"{intro}{heading}"]
        for r in df.itertuples():
            price = r.selling_price
            if r.discount and r.discount > 0:
                price = round(price * (1 - r.discount / 100.0), 2)
            lines.append(f"• {r.name} ({r.brand}) — {_fmt_inr(price)} · ⭐ {r.rating}")
        return "\n".join(lines)

    def _fallback(self, q: str) -> str:
        return ("I'm not sure about that one. Try asking if something's in stock, "
                "where your order is, our shipping/return policy, or for a "
                "recommendation — or type \"help\" for examples.")
