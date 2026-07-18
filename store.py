"""
store.py
--------
Left-hand side of the split screen: "Modern Electronics Store".
Provides search, category & sort filters, flash-sale/trending toggles,
a scrollable product grid with infinite scroll, quantity selectors and an
"Add to Cart" button that stages items in a cart. A cart icon (with a live
item-count badge) opens a cart dialog where the customer reviews items and
taps "Pay Now" to open a checkout dialog, choose a payment method, and
complete a simulated payment — only then is a real order placed into the
live simulation so the Admin Dashboard on the right reacts instantly.
"""
from __future__ import annotations

import asyncio
import random
import time
import uuid
from datetime import datetime, timedelta

from nicegui import ui

import styles as S
from customer_bot import CustomerAssistant
from database import Database
from products import CATEGORY_LIST, bulk_discount_tiers_label, get_bulk_discount
from simulation import SimulationState, SIMULATION_INTERVAL_SECONDS

PAGE_CHUNK = 24
SORT_OPTIONS = {
    "Newest": "id ASC",
    "Price: Low to High": "selling_price ASC",
    "Price: High to Low": "selling_price DESC",
    "Rating: High to Low": "rating DESC",
    "Highest Discount": "discount DESC",
}

LOW_STOCK_THRESHOLD = 15          # show a low-stock warning at/below this many units
FREE_SHIPPING_THRESHOLD = 999.0   # ₹ cart subtotal that unlocks free shipping

# Committed quick-commerce delivery: every order promises delivery in either
# 30 minutes or 1 hour (chosen per order), instead of a multi-day estimate.
DELIVERY_ETA_MINUTES_OPTIONS = (30, 60)

PAYMENT_METHODS = ["UPI", "Credit / Debit Card", "BillDesk", "Cash on Delivery"]


def flash_sale_end_epoch_ms(state: SimulationState, product_id: str) -> int | None:
    """Return the epoch-millisecond timestamp when this product's active
    flash sale ends, or None if it isn't currently in a flash sale. Computed
    fresh from the simulation's remaining-ticks counter each time it's
    called, so it self-corrects on every refresh even though the on-screen
    countdown ticks down smoothly every second in the browser."""
    if state is None:
        return None
    remaining_ticks = state.active_flash_sales.get(product_id)
    if not remaining_ticks:
        return None
    remaining_seconds = remaining_ticks * SIMULATION_INTERVAL_SECONDS
    return int((time.time() + remaining_seconds) * 1000)


class StoreFilters:
    def __init__(self):
        self.search: str = ""
        self.category: str = "All"
        self.sort: str = "Newest"
        self.flash_only: bool = False
        self.trending_only: bool = False


def build_store_ui(db: Database, state: SimulationState):
    """Builds the storefront UI. Returns a `refresh()` callback that keeps the
    currently visible product cards (price / stock) in sync with the live
    simulation, without disturbing scroll position."""

    filters = StoreFilters()
    loaded_count = {"n": PAGE_CHUNK}
    card_refs: dict[str, dict] = {}

    # ------------------------------------------------------------------ #
    # cart state (nothing is purchased / deducted from inventory until
    # the customer opens the cart and pays)
    # ------------------------------------------------------------------ #
    cart_state: dict[str, int] = {}
    cart_badge = None
    cart_items_container = None
    cart_dialog = None
    payment_dialog = None
    pay_total_label = None
    pay_status_label = None
    pay_button = None
    confirm_dialog = None
    confirm_order_no_label = None
    confirm_items_label = None
    confirm_total_label = None
    confirm_delivery_label = None

    def compute_line(row, qty: int):
        product_discount = float(row["discount"] or 0)
        bulk_discount = get_bulk_discount(qty)
        unit_price = float(row["selling_price"])
        if product_discount > 0:
            unit_price = round(unit_price * (1 - product_discount / 100.0), 2)
        if bulk_discount > 0:
            unit_price = round(unit_price * (1 - bulk_discount / 100.0), 2)
        unit_cost = float(row["cost_price"])
        total = round(unit_price * qty, 2)
        profit = round((unit_price - unit_cost) * qty, 2)
        return {
            "unit_price": unit_price,
            "unit_cost": unit_cost,
            "total": total,
            "profit": profit,
            "product_discount": product_discount,
            "bulk_discount": bulk_discount,
        }

    def cart_grand_total() -> float:
        total = 0.0
        for pid, qty in cart_state.items():
            row = db.get_product(pid)
            if row is None:
                continue
            total += compute_line(row, qty)["total"]
        return round(total, 2)

    def update_cart_badge():
        if cart_badge is None:
            return
        count = sum(cart_state.values())
        cart_badge.text = str(count)
        cart_badge.style("display:inline-flex;" if count > 0 else "display:none;")

    # ------------------------------------------------------------------ #
    # query builder
    # ------------------------------------------------------------------ #
    def fetch_filtered(limit: int):
        clauses = []
        params = []
        if filters.search.strip():
            clauses.append("(LOWER(name) LIKE ? OR LOWER(brand) LIKE ?)")
            like = f"%{filters.search.strip().lower()}%"
            params += [like, like]
        if filters.category != "All":
            clauses.append("category = ?")
            params.append(filters.category)
        if filters.flash_only:
            clauses.append("flash_sale = TRUE")
        if filters.trending_only:
            clauses.append("trending = TRUE")

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        order_by = SORT_OPTIONS.get(filters.sort, "id ASC")
        query = f"SELECT * FROM products {where} ORDER BY {order_by} LIMIT ?"
        return db.conn.execute(query, params + [limit]).fetchdf()

    def result_total() -> int:
        clauses = []
        params = []
        if filters.search.strip():
            clauses.append("(LOWER(name) LIKE ? OR LOWER(brand) LIKE ?)")
            like = f"%{filters.search.strip().lower()}%"
            params += [like, like]
        if filters.category != "All":
            clauses.append("category = ?")
            params.append(filters.category)
        if filters.flash_only:
            clauses.append("flash_sale = TRUE")
        if filters.trending_only:
            clauses.append("trending = TRUE")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        return db.conn.execute(f"SELECT COUNT(*) FROM products {where}", params).fetchone()[0]

    # ------------------------------------------------------------------ #
    # cart action
    # ------------------------------------------------------------------ #
    def add_to_cart(product_id: str, qty_input: ui.number):
        """Stages the item in the cart. Nothing is charged or deducted from
        inventory yet — the customer still has to open the cart and pay."""
        row = db.get_product(product_id)
        if row is None:
            ui.notify("Product no longer available", type="warning")
            return
        qty = int(qty_input.value or 1)
        available = int(row["quantity"])
        if available <= 0:
            ui.notify(f"{row['name']} is out of stock", type="negative")
            return

        already_in_cart = cart_state.get(product_id, 0)
        addable = max(0, available - already_in_cart)
        qty = max(1, min(qty, addable)) if addable > 0 else 0
        if qty <= 0:
            ui.notify(f"No more {row['name']} available to add", type="warning")
            return

        cart_state[product_id] = already_in_cart + qty
        line = compute_line(row, cart_state[product_id])

        has_discount = line["product_discount"] > 0 or line["bulk_discount"] > 0
        if has_discount:
            ui.notify(f"🎈 Added {qty} x {row['name']} to cart — discount applied!",
                      type="positive", position="top")
            ui.run_javascript("window.elmartCelebrateDiscount && window.elmartCelebrateDiscount();")
        else:
            ui.notify(f"🛒 Added {qty} x {row['name']} to cart", type="positive",
                      position="top")
            ui.run_javascript("window.elmartCelebratePlain && window.elmartCelebratePlain();")

        update_cart_badge()

    def remove_from_cart(product_id: str):
        cart_state.pop(product_id, None)
        update_cart_badge()
        render_cart_items()

    async def process_payment(method: str):
        """Simulated payment: after a short 'processing' delay, turns every
        cart line into a real order, deducts inventory and clears the cart.

        BillDesk gets its own simulated gateway hop (redirect → verify →
        success with a transaction reference) before falling into the same
        order-placement flow as the other payment methods."""
        if not cart_state:
            return
        pay_button.props("loading")
        pay_button.disable()

        billdesk_txn_id = None
        if method == "BillDesk":
            pay_status_label.text = "🔒 Redirecting to BillDesk Secure Payment Gateway…"
            pay_status_label.style(f"color:{S.TEXT_SECONDARY};")
            await asyncio.sleep(1.1)
            billdesk_txn_id = "BDK" + uuid.uuid4().hex[:10].upper()
            pay_status_label.text = f"Verifying payment with BillDesk (Ref {billdesk_txn_id})…"
            await asyncio.sleep(1.2)
        else:
            pay_status_label.text = f"Processing payment via {method}…"
            pay_status_label.style(f"color:{S.TEXT_SECONDARY};")
            await asyncio.sleep(1.4)

        purchased = 0
        grand_total = 0.0
        any_discount = False
        order_ts = state.sim_clock if state else datetime.now()
        delivery_minutes = random.choice(DELIVERY_ETA_MINUTES_OPTIONS)
        delivery_dt = order_ts + timedelta(minutes=delivery_minutes)
        confirmation_no = "ELM-" + uuid.uuid4().hex[:8].upper()
        payment_method_label = f"BillDesk (Ref {billdesk_txn_id})" if method == "BillDesk" else method

        for product_id, qty in list(cart_state.items()):
            row = db.get_product(product_id)
            if row is None:
                continue
            available = int(row["quantity"])
            qty = max(0, min(qty, available))
            if qty <= 0:
                continue
            line = compute_line(row, qty)
            if line["product_discount"] > 0 or line["bulk_discount"] > 0:
                any_discount = True

            db.insert_order({
                "order_id": uuid.uuid4().hex[:10],
                "product_id": product_id,
                "product_name": row["name"],
                "category": row["category"],
                "quantity": qty,
                "unit_price": line["unit_price"],
                "unit_cost": line["unit_cost"],
                "total": line["total"],
                "profit": line["profit"],
                "is_return": False,
                "manual": True,
                "ts": order_ts,
                "customer_id": "CUST-YOU",
                "delivery_date": delivery_dt,
                "confirmation_no": confirmation_no,
                "payment_method": payment_method_label,
            })
            db.adjust_quantity(product_id, -qty)
            db.record_customer_order("CUST-YOU", line["total"], order_ts)
            if state is not None:
                state._log_event(f"🛍️ Customer bought {qty}x {row['name']}")
            purchased += qty
            grand_total += line["total"]

        cart_state.clear()
        pay_button.props(remove="loading")
        pay_button.enable()
        update_cart_badge()
        refresh_visible_cards()

        if purchased > 0:
            if method == "BillDesk":
                pay_status_label.text = (
                    f"✅ BillDesk Payment Success — Ref {billdesk_txn_id} — "
                    f"₹{grand_total:,.0f}"
                )
                ui.notify(f"✅ BillDesk Payment Success! Ref {billdesk_txn_id} · ₹{grand_total:,.0f}",
                          type="positive", position="top")
            else:
                pay_status_label.text = f"✅ Payment successful — {purchased} item(s), ₹{grand_total:,.0f}"
                ui.notify(f"✅ Payment of ₹{grand_total:,.0f} successful! Thank you for shopping.",
                          type="positive", position="top")
            pay_status_label.style(f"color:{S.SUCCESS};font-weight:700;")
            if any_discount:
                ui.run_javascript("window.elmartCelebrateDiscount && window.elmartCelebrateDiscount();")
            else:
                ui.run_javascript("window.elmartCelebratePlain && window.elmartCelebratePlain();")
            await asyncio.sleep(1.0)
            payment_dialog.close()
            cart_dialog.close()
            show_order_confirmation(purchased, grand_total, confirmation_no, delivery_dt,
                                     delivery_minutes, payment_method_label)
        else:
            pay_status_label.text = "Some items went out of stock — please review your cart."
            pay_status_label.style(f"color:{S.DANGER};")
            render_cart_items()

    def show_order_confirmation(purchased: int, grand_total: float, confirmation_no: str,
                                 delivery_dt: datetime, delivery_minutes: int,
                                 payment_method_label: str) -> None:
        """Populate and open the order-confirmation dialog with the same
        confirmation number / committed delivery ETA that was just persisted
        to the order, so tracking it later via the CRM chatbot matches
        exactly."""
        confirm_order_no_label.text = f"Order #{confirmation_no}"
        confirm_items_label.text = f"{purchased} item(s) purchased · Paid via {payment_method_label}"
        confirm_total_label.text = f"₹{grand_total:,.0f} paid"
        eta_label = "30 minutes" if delivery_minutes == 30 else "1 hour"
        confirm_delivery_label.text = (
            f"⚡ Arriving in {eta_label} — by {delivery_dt.strftime('%I:%M %p')}"
        )
        confirm_dialog.open()

    def open_payment_dialog():
        total = cart_grand_total()
        if total <= 0:
            ui.notify("Your cart is empty", type="warning")
            return
        pay_total_label.text = f"₹{total:,.0f}"
        pay_status_label.text = ""
        payment_dialog.open()

    def render_cart_items():
        cart_items_container.clear()
        with cart_items_container:
            if not cart_state:
                ui.label("Your cart is empty").style(
                    f"color:{S.TEXT_SECONDARY};padding:24px 4px;font-size:13px;")
            else:
                for pid, qty in list(cart_state.items()):
                    row = db.get_product(pid)
                    if row is None:
                        continue
                    line = compute_line(row, qty)
                    with ui.row().classes("items-center w-full gap-2 no-wrap").style(
                            f"padding:8px 0;border-bottom:1px solid {S.BORDER};"):
                        ui.image(row["image"]).style(
                            "width:44px;height:44px;object-fit:cover;border-radius:8px;flex-shrink:0;")
                        with ui.column().classes("gap-0").style("flex:1;min-width:0;"):
                            ui.label(row["name"]).style(
                                "font-weight:600;font-size:13px;white-space:nowrap;"
                                "overflow:hidden;text-overflow:ellipsis;").tooltip(row["name"])
                            ui.label(f"Qty {qty} · ₹{line['unit_price']:,.0f} each").style(
                                f"font-size:11px;color:{S.TEXT_SECONDARY};")
                        ui.label(f"₹{line['total']:,.0f}").style(
                            "font-weight:700;font-size:13px;white-space:nowrap;")
                        ui.button(icon="delete_outline",
                                  on_click=lambda pid=pid: remove_from_cart(pid)) \
                            .props('flat dense round color="grey-6"')
                with ui.row().classes("w-full items-center justify-between").style("padding-top:10px;"):
                    ui.label("Total").style("font-size:14px;font-weight:700;")
                    ui.label(f"₹{cart_grand_total():,.0f}").style(
                        f"font-size:17px;font-weight:800;color:{S.PRIMARY};")

                grand_total = cart_grand_total()
                progress = min(1.0, grand_total / FREE_SHIPPING_THRESHOLD)
                with ui.column().classes("w-full gap-1").style("margin-top:10px;"):
                    if grand_total >= FREE_SHIPPING_THRESHOLD:
                        ui.label("🚚 You've unlocked FREE shipping!").style(
                            f"font-size:12px;font-weight:700;color:{S.SUCCESS};")
                    else:
                        remaining = FREE_SHIPPING_THRESHOLD - grand_total
                        ui.label(f"🚚 Add ₹{remaining:,.0f} more for FREE shipping").style(
                            f"font-size:12px;font-weight:600;color:{S.TEXT_SECONDARY};")
                    ui.linear_progress(value=progress, show_value=False).props(
                        'color="pink-5" track-color="grey-3" rounded').style("height:8px;")

    def open_cart_dialog():
        render_cart_items()
        cart_dialog.open()

    # ------------------------------------------------------------------ #
    # card rendering
    # ------------------------------------------------------------------ #
    def make_product_card(row) -> None:
        pid = row["id"]
        with ui.card().tight().classes("rd-product-card").style("margin:6px;width:220px;"):
            ui.image(row["image"]).classes("rounded-borders").style(
                "height:120px;object-fit:cover;")
            with ui.column().classes("q-pa-sm gap-0").style("width:100%;"):
                badges = ui.row().classes("gap-1")
                with badges:
                    if row["flash_sale"]:
                        ui.label("⚡ FLASH").classes("rd-badge-flash")
                    if row["trending"]:
                        ui.label("🔥 TRENDING").classes("rd-badge-trending")
                    if row["discount"] and row["discount"] > 0:
                        ui.label(f"-{int(row['discount'])}%").classes("rd-badge-discount")
                    bulk_badge = ui.label("").classes("rd-badge-bulk").style("display:none;")

                flash_countdown = ui.html("").style("display:none;")

                ui.label(row["name"]).style(
                    "font-weight:700;font-size:13px;line-height:1.2;"
                    "height:32px;overflow:hidden;").tooltip(row["name"])
                ui.label(f"{row['brand']} · {row['category']}").style(
                    f"font-size:11px;color:{S.TEXT_SECONDARY};")
                ui.label(f"⭐ {row['rating']}").style("font-size:12px;")

                price_row = ui.row().classes("items-center gap-2")
                discounted = row["selling_price"]
                if row["discount"] and row["discount"] > 0:
                    discounted = round(row["selling_price"] * (1 - row["discount"] / 100.0), 2)
                with price_row:
                    price_label = ui.label(f"₹{discounted:,.0f}").classes("rd-price")
                    strike_label = None
                    if row["discount"] and row["discount"] > 0:
                        strike_label = ui.label(f"₹{row['selling_price']:,.0f}").classes("rd-strike")

                stock_label = ui.label()
                stock_label.text = (
                    f"In stock: {int(row['quantity'])}" if row["quantity"] > 0 else "Out of stock"
                )
                stock_label.style(f"font-size:11px;color:{S.TEXT_SECONDARY};")

                low_stock_label = ui.label("").classes("rd-low-stock").style("display:none;")

                with ui.row().classes("items-center gap-2 q-mt-xs") as action_row:
                    qty_input = ui.number(value=1, min=1,
                                           max=max(1, int(row["quantity"])),
                                           format="%.0f").props("dense outlined").style("width:64px;")
                    add_button = ui.button("Add to Cart", icon="add_shopping_cart",
                              on_click=lambda pid=pid, qi=qty_input: add_to_cart(pid, qi)) \
                        .props(f'unelevated color="pink-4"').style(
                        "border-radius:10px;font-size:11px;")

                ui.label(f"📦 Bulk discount: {bulk_discount_tiers_label()}").classes(
                    "rd-bulk-tiers").style("margin-top:2px;")
                total_label = ui.label().classes("rd-total-line")

            def update_total(row=row, qty_input=qty_input, total_label=total_label,
                              bulk_badge=bulk_badge):
                qty = int(qty_input.value or 1)
                product_discount = float(row["discount"] or 0)
                unit_price = float(row["selling_price"])
                if product_discount > 0:
                    unit_price = unit_price * (1 - product_discount / 100.0)
                bulk_discount = get_bulk_discount(qty)
                if bulk_discount > 0:
                    final_unit = unit_price * (1 - bulk_discount / 100.0)
                else:
                    final_unit = unit_price
                total = final_unit * qty
                if bulk_discount > 0:
                    total_label.text = f"Qty {qty}: ₹{total:,.0f} total (bulk -{int(bulk_discount)}% applied)"
                    bulk_badge.text = f"-{int(bulk_discount)}% BULK"
                    bulk_badge.style("display:inline-block;")
                else:
                    total_label.text = f"Qty {qty}: ₹{total:,.0f} total"
                    bulk_badge.style("display:none;")

            def update_availability(row=row, qty_input=qty_input, add_button=add_button,
                                     low_stock_label=low_stock_label):
                in_stock = int(row["quantity"])
                if in_stock <= 0:
                    add_button.text = "Out of Stock"
                    add_button.props('color="grey-5"')
                    add_button.disable()
                    qty_input.disable()
                    low_stock_label.style("display:none;")
                else:
                    add_button.text = "Add to Cart"
                    add_button.props('color="pink-4"')
                    add_button.enable()
                    qty_input.enable()
                    if in_stock <= LOW_STOCK_THRESHOLD:
                        low_stock_label.text = f"⚠️ Only {in_stock} left — order soon!"
                        low_stock_label.style("display:block;")
                    else:
                        low_stock_label.style("display:none;")

            def update_flash_countdown(row=row, flash_countdown=flash_countdown, pid=pid):
                end_ms = flash_sale_end_epoch_ms(state, pid) if row["flash_sale"] else None
                if end_ms is None:
                    flash_countdown.style("display:none;")
                else:
                    flash_countdown.content = (
                        f'<span class="rd-flash-countdown" data-end="{end_ms}">⏳ --:--</span>'
                    )
                    flash_countdown.style("display:inline-block;")

            qty_input.on_value_change(lambda e, fn=update_total: fn())
            update_total()
            update_availability()
            update_flash_countdown()

            card_refs[pid] = {
                "price_label": price_label,
                "strike_label": strike_label,
                "stock_label": stock_label,
                "qty_input": qty_input,
                "update_total": update_total,
                "update_availability": update_availability,
                "update_flash_countdown": update_flash_countdown,
            }

    # ------------------------------------------------------------------ #
    # grid population
    # ------------------------------------------------------------------ #
    grid_container = None
    status_label = None

    def rebuild_grid():
        card_refs.clear()
        grid_container.clear()
        loaded_count["n"] = PAGE_CHUNK
        rows = fetch_filtered(loaded_count["n"])
        total = result_total()
        with grid_container:
            for _, row in rows.iterrows():
                make_product_card(row)
        status_label.text = f"Showing {len(rows)} of {total} products"

    def load_more():
        total = result_total()
        if loaded_count["n"] >= total:
            return
        loaded_count["n"] += PAGE_CHUNK
        rows = fetch_filtered(loaded_count["n"])
        new_rows = rows.iloc[len(card_refs):]
        with grid_container:
            for _, row in new_rows.iterrows():
                make_product_card(row)
        status_label.text = f"Showing {len(card_refs)} of {total} products"

    def on_scroll(e):
        if e.vertical_percentage is not None and e.vertical_percentage > 0.85:
            load_more()

    def refresh_visible_cards():
        """Keep visible cards' price/stock in sync with DB without rebuilding."""
        for pid, refs in list(card_refs.items()):
            row = db.get_product(pid)
            if row is None:
                continue
            discounted = row["selling_price"]
            if row["discount"] and row["discount"] > 0:
                discounted = round(row["selling_price"] * (1 - row["discount"] / 100.0), 2)
            refs["price_label"].text = f"₹{discounted:,.0f}"
            if refs["strike_label"] is not None:
                refs["strike_label"].text = f"₹{row['selling_price']:,.0f}"
            in_stock = int(row["quantity"])
            refs["stock_label"].text = f"In stock: {in_stock}" if in_stock > 0 else "Out of stock"
            refs["qty_input"].props(f"max={max(1, in_stock)}")
            if "update_total" in refs:
                refs["update_total"](row=row)
            if "update_availability" in refs:
                refs["update_availability"](row=row)
            if "update_flash_countdown" in refs:
                refs["update_flash_countdown"](row=row)

    # ------------------------------------------------------------------ #
    # header / filter bar
    # ------------------------------------------------------------------ #
    with ui.column().classes("w-full gap-2").style("padding: 14px 18px 0 18px;"):
        with ui.row().classes("items-center gap-3 w-full"):
            ui.image("/assets/logo.png").style("width:44px;height:44px;")
            with ui.column().classes("gap-0"):
                ui.label("Elmart").classes("rd-logo-title")
                ui.label("Modern Electronics Store").style(
                    f"font-size:12px;color:{S.TEXT_SECONDARY};margin-top:-4px;")
            with ui.element("div").style("margin-left:auto;position:relative;"):
                ui.button(icon="shopping_cart", on_click=lambda: open_cart_dialog()) \
                    .props('unelevated color="pink-4" round') \
                    .style("border-radius:12px;").mark("cart-button")
                cart_badge = ui.label("0").style(
                    "position:absolute;top:-6px;right:-6px;background:"
                    f"{S.DANGER};color:white;font-size:11px;font-weight:700;"
                    "border-radius:999px;min-width:18px;height:18px;display:none;"
                    "align-items:center;justify-content:center;padding:0 4px;")
        ui.label("500 products · 20 categories · live inventory").style(
            f"font-size:12px;color:{S.TEXT_MUTED};margin-top:-2px;")
        ui.label("⚡ Committed delivery in 30 mins or 1 hour on every order").style(
            f"font-size:12px;font-weight:700;color:{S.PRIMARY};margin-top:2px;")

        with ui.row().classes("w-full gap-2 items-center"):
            search_input = ui.input(placeholder="Search products or brands...") \
                .props("dense outlined clearable").classes("col")
            category_select = ui.select(["All"] + CATEGORY_LIST, value="All",
                                         label="Category").props("dense outlined").style("width:200px;")
            sort_select = ui.select(list(SORT_OPTIONS.keys()), value="Newest",
                                     label="Sort by").props("dense outlined").style("width:190px;")

        with ui.row().classes("items-center gap-4"):
            flash_switch = ui.switch("Flash Sale Only").props('color="pink-6"')
            trending_switch = ui.switch("Trending Only").props('color="pink-6"')
            status_label = ui.label().style(f"font-size:12px;color:{S.TEXT_SECONDARY};margin-left:auto;")

    def on_filters_changed():
        filters.search = search_input.value or ""
        filters.category = category_select.value or "All"
        filters.sort = sort_select.value or "Newest"
        filters.flash_only = bool(flash_switch.value)
        filters.trending_only = bool(trending_switch.value)
        rebuild_grid()

    search_input.on("keydown.enter", lambda: on_filters_changed())
    search_input.on("blur", lambda: on_filters_changed())
    category_select.on_value_change(lambda e: on_filters_changed())
    sort_select.on_value_change(lambda e: on_filters_changed())
    flash_switch.on_value_change(lambda e: on_filters_changed())
    trending_switch.on_value_change(lambda e: on_filters_changed())

    # ------------------------------------------------------------------ #
    # cart dialog
    # ------------------------------------------------------------------ #
    with ui.dialog() as cart_dialog, ui.card().style("width:420px;max-width:92vw;"):
        with ui.row().classes("items-center w-full"):
            ui.label("🛒 Your Cart").style("font-size:16px;font-weight:700;")
            ui.space()
            ui.button(icon="close", on_click=cart_dialog.close).props("flat dense round")
        ui.separator()
        cart_items_container = ui.column().classes("w-full gap-0").style(
            "max-height:340px;overflow-y:auto;")
        ui.separator().classes("q-mt-sm")
        with ui.row().classes("w-full justify-end gap-2 q-mt-sm"):
            ui.button("Continue Shopping", on_click=cart_dialog.close).props(
                'flat color="grey-7"')
            ui.button("Pay Now", icon="payments", on_click=open_payment_dialog).props(
                'unelevated color="pink-4"').style("border-radius:10px;")

    # ------------------------------------------------------------------ #
    # payment dialog
    # ------------------------------------------------------------------ #
    with ui.dialog() as payment_dialog, ui.card().style("width:380px;max-width:92vw;"):
        ui.label("💳 Checkout").style("font-size:16px;font-weight:700;")
        ui.separator()
        with ui.row().classes("items-center justify-between w-full q-mt-sm"):
            ui.label("Amount to pay").style(f"font-size:13px;color:{S.TEXT_SECONDARY};")
            pay_total_label = ui.label("₹0").style(
                f"font-size:20px;font-weight:800;color:{S.PRIMARY};")
        ui.label("Choose a payment method").style(
            f"font-size:12px;color:{S.TEXT_SECONDARY};margin-top:8px;")
        method_select = ui.radio(PAYMENT_METHODS, value="UPI") \
            .props('color="pink-4" inline').style("margin-top:2px;")
        ui.label("💠 BillDesk is a secure third-party payment gateway (cards, UPI, net banking).").style(
            f"font-size:11px;color:{S.TEXT_MUTED};margin-top:2px;")
        pay_status_label = ui.label("").style("font-size:12px;min-height:18px;margin-top:6px;")
        with ui.row().classes("w-full justify-end gap-2 q-mt-sm"):
            ui.button("Cancel", on_click=payment_dialog.close).props('flat color="grey-7"')
            pay_button = ui.button(
                "Pay Now", icon="lock",
                on_click=lambda: process_payment(method_select.value)) \
                .props('unelevated color="pink-4"').style("border-radius:10px;")

    # ------------------------------------------------------------------ #
    # order confirmation dialog
    # ------------------------------------------------------------------ #
    with ui.dialog() as confirm_dialog, ui.card().style("width:380px;max-width:92vw;"):
        with ui.row().classes("items-center gap-2"):
            ui.icon("check_circle", color="green-6").style("font-size:28px;")
            ui.label("Order Confirmed!").style(f"font-size:18px;font-weight:800;color:{S.SUCCESS};")
        ui.separator().classes("q-mt-xs")
        confirm_order_no_label = ui.label().style(
            f"font-size:12px;color:{S.TEXT_SECONDARY};margin-top:8px;")
        confirm_items_label = ui.label().style("font-size:13px;margin-top:2px;")
        confirm_total_label = ui.label().style(
            f"font-size:22px;font-weight:800;color:{S.PRIMARY};margin-top:4px;")
        with ui.row().classes("items-center gap-3 w-full").style(
                f"margin-top:12px;background:{S.CARD_BG_ALT};border-radius:12px;padding:10px 12px;"):
            ui.icon("bolt", color="pink-6").style("font-size:28px;")
            with ui.column().classes("gap-0"):
                ui.label("Committed delivery").style(f"font-size:11px;color:{S.TEXT_SECONDARY};")
                confirm_delivery_label = ui.label().style("font-size:14px;font-weight:700;")
        with ui.row().classes("w-full justify-end q-mt-md"):
            ui.button("Continue Shopping", on_click=confirm_dialog.close).props(
                'unelevated color="pink-4"').style("border-radius:10px;")

    # ------------------------------------------------------------------ #
    # "Ask Elmart" live customer support chatbot (floating widget)
    # ------------------------------------------------------------------ #
    assistant = CustomerAssistant(db, state)

    with ui.dialog() as chat_dialog, ui.card().style(
            "width:380px;max-width:92vw;padding:0;overflow:hidden;border-radius:16px;"):
        with ui.row().classes("items-center gap-2 w-full").style(
                f"background:{S.PRIMARY};padding:12px 14px;"):
            ui.icon("support_agent", color="white").style("font-size:22px;")
            ui.label("Ask Elmart").style("color:#FFFFFF;font-weight:800;font-size:15px;")
            ui.space()
            ui.button(icon="close", on_click=chat_dialog.close).props("flat dense round color=white")

        with ui.column().classes("w-full gap-0").style("padding:10px 12px;"):
            chat_scroll = ui.scroll_area().classes("w-full").style("height:280px;")
            with chat_scroll:
                chat_column = ui.column().classes("w-full gap-1").style("padding:2px 4px;")

            def add_chat_message(role: str, text: str):
                with chat_column:
                    if role == "bot":
                        with ui.row().classes("items-start no-wrap gap-2 w-full"):
                            ui.icon("support_agent", color="pink-6").style("font-size:18px;margin-top:3px;")
                            ui.label(text).style(
                                f"background:{S.CARD_BG_ALT};color:{S.TEXT_PRIMARY};"
                                "border-radius:10px;padding:6px 10px;font-size:12.5px;"
                                "white-space:pre-line;max-width:85%;")
                    else:
                        with ui.row().classes("items-start no-wrap gap-2 w-full justify-end"):
                            ui.label(text).style(
                                f"background:{S.PRIMARY};color:#FFFFFF;"
                                "border-radius:10px;padding:6px 10px;font-size:12.5px;"
                                "white-space:pre-line;max-width:85%;")
                chat_scroll.scroll_to(percent=1.0)

            add_chat_message("bot", "Hi, I'm the Elmart Assistant! Ask me if something's in "
                                     "stock, where your order is, our policies, or tap a "
                                     "suggestion below.")

            def send_chat_message(text: str = ""):
                msg = (text or chat_input.value or "").strip()
                if not msg:
                    return
                add_chat_message("user", msg)
                add_chat_message("bot", assistant.answer(msg))
                chat_input.value = ""

            with ui.row().classes("w-full gap-1 q-mt-xs").style("flex-wrap:wrap;"):
                for suggestion in ["Is this in stock?", "Track my order", "Shipping policy",
                                    "Return policy", "Recommend something"]:
                    ui.button(suggestion, on_click=lambda s=suggestion: send_chat_message(s)) \
                        .props('outline dense color="pink-6"').style("font-size:10.5px;")

            with ui.row().classes("w-full items-center gap-2 q-mt-xs no-wrap"):
                chat_input = ui.input(placeholder="Ask a question…") \
                    .props("dense outlined").classes("flex-grow") \
                    .on("keydown.enter", lambda: send_chat_message())
                ui.button(icon="send", on_click=lambda: send_chat_message()) \
                    .props('unelevated round color="pink-6"')

    ui.button(icon="support_agent", on_click=chat_dialog.open).props(
        'unelevated round color="pink-6"').style(
        "position:fixed;bottom:22px;left:22px;z-index:999;width:56px;height:56px;"
        "box-shadow:0 6px 20px rgba(198,37,92,0.35);"
    ).tooltip("Ask Elmart")

    scroll_area = ui.scroll_area(on_scroll=on_scroll).classes("w-full").style(
        "height: calc(100vh - 190px); padding: 0 12px;")
    with scroll_area:
        grid_container = ui.row().classes("w-full gap-1").style(
            "flex-wrap:wrap;justify-content:flex-start;padding-bottom:30px;")

    rebuild_grid()

    return refresh_visible_cards
