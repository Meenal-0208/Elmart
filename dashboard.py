"""
dashboard.py
------------
Right-hand side of the split screen: "Live Admin Dashboard".
Shows KPI cards, six live Plotly charts, and an editable inventory table
(paginated, with per-row Save buttons that write straight back to DuckDB).
"""
from __future__ import annotations

from nicegui import ui

import charts
import styles as S
from chatbot import CRMChatbot
from database import Database
from products import CATEGORY_LIST
from simulation import SimulationState

TABLE_PAGE_SIZE = 12


def _fmt_inr(value: float) -> str:
    return f"₹{value:,.0f}"


def build_dashboard_ui(db: Database, state: SimulationState):
    """Builds the dashboard UI. Returns a `refresh()` callback that updates
    KPI numbers and all charts from the current simulation state."""

    kpi_labels: dict[str, ui.label] = {}
    kpi_subs: dict[str, ui.label] = {}
    plot_elements: dict[str, ui.plotly] = {}
    events_container = None

    # ------------------------------------------------------------------ #
    # header
    # ------------------------------------------------------------------ #
    with ui.column().classes("w-full gap-1").style("padding: 14px 18px 0 18px;"):
        with ui.row().classes("items-center gap-2"):
            ui.icon("insights", color="pink-8").style("font-size:26px;")
            ui.label("Live Admin Dashboard").classes("rd-logo-title")
        sim_clock_label = ui.label().style(f"font-size:12px;color:{S.TEXT_SECONDARY};margin-top:-6px;")

    dashboard_scroll = ui.scroll_area().classes("w-full").style(
        "height: calc(100vh - 76px); padding: 0 18px 24px 18px;")

    with dashboard_scroll:
        # ------------------------------------------------------------ #
        # KPI cards
        # ------------------------------------------------------------ #
        kpi_defs = [
            ("revenue", "Revenue", "payments", "pink-3"),
            ("profit", "Profit", "trending_up", "pink-5"),
            ("orders", "Orders", "shopping_cart", "pink-7"),
            ("customers", "Customers Today", "groups", "pink-4"),
            ("budget", "Budget Remaining", "account_balance_wallet", "pink-8"),
            ("inv_value", "Inventory Value", "warehouse", "pink-6"),
            ("inv_health", "Inventory Health", "health_and_safety", "pink-9"),
        ]
        with ui.row().classes("w-full gap-3").style("flex-wrap:wrap;"):
            for key, title, icon, color in kpi_defs:
                with ui.card().tight().classes("rd-kpi-card").style(
                        "min-width:190px;flex:1 1 190px;"):
                    with ui.row().classes("items-center gap-2 q-pa-sm"):
                        ui.icon(icon, color=color).style("font-size:26px;")
                        with ui.column().classes("gap-0"):
                            ui.label(title).style(
                                f"font-size:12px;color:{S.TEXT_SECONDARY};font-weight:600;")
                            kpi_labels[key] = ui.label("—").style(
                                f"font-size:20px;font-weight:800;color:{S.TEXT_PRIMARY};")
                            kpi_subs[key] = ui.label("").style(
                                f"font-size:11px;color:{S.TEXT_SECONDARY};")

        # ------------------------------------------------------------ #
        # charts grid
        # ------------------------------------------------------------ #
        ui.label("Analytics").classes("rd-section-title").style("margin-top:14px;")
        with ui.grid(columns=2).classes("w-full gap-3"):
            with ui.card().classes("rd-card q-pa-sm"):
                plot_elements["revenue_profit"] = ui.plotly(
                    charts.revenue_vs_profit_fig(state.history)).classes("w-full")
            with ui.card().classes("rd-card q-pa-sm"):
                plot_elements["revenue_category"] = ui.plotly(
                    charts.revenue_by_category_fig(db.revenue_by_category())).classes("w-full")
            with ui.card().classes("rd-card q-pa-sm"):
                plot_elements["sales_trend"] = ui.plotly(
                    charts.sales_trend_fig(state.history)).classes("w-full")
            with ui.card().classes("rd-card q-pa-sm"):
                plot_elements["hourly_customers"] = ui.plotly(
                    charts.hourly_customers_fig(db.hourly_customers_today(state.sim_day))).classes("w-full")
            with ui.card().classes("rd-card q-pa-sm"):
                plot_elements["top_products"] = ui.plotly(
                    charts.top_products_fig(db.top_products(10))).classes("w-full")
            with ui.card().classes("rd-card q-pa-sm"):
                plot_elements["inventory_status"] = ui.plotly(
                    charts.inventory_status_fig(db.inventory_status_counts())).classes("w-full")

        # ------------------------------------------------------------ #
        # live events feed
        # ------------------------------------------------------------ #
        ui.label("Live Activity Feed").classes("rd-section-title").style("margin-top:8px;")
        with ui.card().classes("rd-card w-full q-pa-sm"):
            events_container = ui.column().classes("gap-1").style(
                "max-height:140px;overflow-y:auto;")

        # ------------------------------------------------------------ #
        # CRM Assistant chatbot
        # ------------------------------------------------------------ #
        bot = CRMChatbot(db, state)

        ui.label("CRM Assistant").classes("rd-section-title").style("margin-top:8px;")
        with ui.card().classes("rd-card w-full q-pa-sm"):
            chat_scroll = ui.scroll_area().classes("w-full").style("height:230px;")
            with chat_scroll:
                chat_column = ui.column().classes("w-full gap-1").style("padding:2px 4px;")

            def add_message(role: str, text: str):
                with chat_column:
                    if role == "bot":
                        with ui.row().classes("items-start no-wrap gap-2 w-full"):
                            ui.icon("smart_toy", color="pink-6").style("font-size:18px;margin-top:3px;")
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

            add_message("bot", "Hi! I'm your CRM Assistant. Ask me about customers, revenue, "
                                "top products, or inventory — or tap a suggestion below.")

            def send_message(text: str = ""):
                msg = (text or chat_input.value or "").strip()
                if not msg:
                    return
                add_message("user", msg)
                add_message("bot", bot.answer(msg))
                chat_input.value = ""

            with ui.row().classes("w-full gap-1 q-mt-xs").style("flex-wrap:wrap;"):
                for suggestion in ["Top customers", "Revenue today", "Customer segments",
                                    "Low stock", "Top products", "Inactive customers"]:
                    ui.button(suggestion, on_click=lambda s=suggestion: send_message(s)) \
                        .props('outline dense color="pink-6"').style("font-size:11px;")

            with ui.row().classes("w-full items-center gap-2 q-mt-xs no-wrap"):
                chat_input = ui.input(placeholder="Ask about customers, sales, inventory…") \
                    .props("dense outlined").classes("flex-grow") \
                    .on("keydown.enter", lambda: send_message())
                ui.button(icon="send", on_click=lambda: send_message()) \
                    .props('unelevated round color="pink-6"')

        # ------------------------------------------------------------ #
        # editable inventory table
        # ------------------------------------------------------------ #
        ui.label("Editable Inventory Table").classes("rd-section-title").style("margin-top:8px;")

        table_state = {"page": 0, "category": "All"}
        table_body = ui.column().classes("w-full gap-1")
        table_pager_label = ui.label()

        def save_row(product_id: str, sp_input, cp_input, disc_input, stock_input):
            db.update_product_fields(
                product_id,
                selling_price=float(sp_input.value),
                cost_price=float(cp_input.value),
                discount=float(disc_input.value),
                quantity=int(stock_input.value),
            )
            ui.notify(f"Saved changes for {product_id}", type="positive", position="top")

        def render_table_page():
            table_body.clear()
            page = table_state["page"]
            category = table_state["category"]
            rows = db.paginated_products(page, TABLE_PAGE_SIZE, category)
            total = db.product_count(category)
            max_page = max(0, (total - 1) // TABLE_PAGE_SIZE)
            table_state["page"] = min(page, max_page)

            with table_body:
                with ui.row().classes("w-full items-center gap-2 q-pa-xs").style(
                        f"background:{S.PRIMARY};border-radius:10px;font-weight:700;font-size:12px;"):
                    ui.label("Product").style("width:26%;color:#FFFFFF;")
                    ui.label("Selling Price").style("width:15%;color:#FFFFFF;")
                    ui.label("Cost Price").style("width:15%;color:#FFFFFF;")
                    ui.label("Discount %").style("width:13%;color:#FFFFFF;")
                    ui.label("Stock").style("width:13%;color:#FFFFFF;")
                    ui.label("").style("width:14%;")

                for _, row in rows.iterrows():
                    with ui.row().classes("w-full items-center gap-2 q-pa-xs").style(
                            f"border-bottom:1px solid {S.BORDER};"):
                        ui.label(row["name"]).style(
                            "width:26%;font-size:12px;overflow:hidden;text-overflow:ellipsis;"
                            "white-space:nowrap;").tooltip(row["name"])
                        sp_input = ui.number(value=float(row["selling_price"]), min=0, step=10,
                                              format="%.0f").props("dense outlined").style("width:15%;")
                        cp_input = ui.number(value=float(row["cost_price"]), min=0, step=10,
                                              format="%.0f").props("dense outlined").style("width:15%;")
                        disc_input = ui.number(value=float(row["discount"]), min=0, max=80, step=5,
                                                format="%.0f").props("dense outlined").style("width:13%;")
                        stock_input = ui.number(value=int(row["quantity"]), min=0, step=1,
                                                 format="%.0f").props("dense outlined").style("width:13%;")
                        ui.button("Save", icon="save",
                                  on_click=lambda pid=row["id"], sp=sp_input, cp=cp_input,
                                  di=disc_input, st=stock_input: save_row(pid, sp, cp, di, st)) \
                            .props('unelevated color="pink-6"').style("width:14%;font-size:11px;")

            table_pager_label.text = f"Page {table_state['page'] + 1} of {max_page + 1} · {total} products"

        with ui.row().classes("w-full items-center gap-3 q-mb-xs"):
            table_category_select = ui.select(["All"] + CATEGORY_LIST, value="All",
                                                label="Filter category") \
                .props("dense outlined").style("width:220px;")

            def on_table_category_change(e):
                table_state["category"] = table_category_select.value or "All"
                table_state["page"] = 0
                render_table_page()

            table_category_select.on_value_change(on_table_category_change)

            def prev_page():
                if table_state["page"] > 0:
                    table_state["page"] -= 1
                    render_table_page()

            def next_page():
                table_state["page"] += 1
                render_table_page()

            ui.button(icon="chevron_left", on_click=prev_page).props('flat round color="pink-6"')
            table_pager_label
            ui.button(icon="chevron_right", on_click=next_page).props('flat round color="pink-6"')

        render_table_page()

    # ------------------------------------------------------------------ #
    # refresh callback (called every simulation tick)
    # ------------------------------------------------------------------ #
    def refresh():
        sim_clock_label.text = (
            f"Simulated time: {state.sim_clock.strftime('%A, %d %b %Y — %H:%M')}  "
            f"(Day {state.sim_day + 1})"
        )

        kpi_labels["revenue"].text = _fmt_inr(state.revenue)
        kpi_labels["profit"].text = _fmt_inr(state.net_profit)
        kpi_subs["profit"].text = "profit" if state.net_profit >= 0 else "loss"
        kpi_labels["orders"].text = f"{state.orders:,}"
        kpi_labels["customers"].text = f"{state.customers_today:,} / {100_000:,}"
        kpi_labels["budget"].text = _fmt_inr(state.budget_remaining)
        kpi_subs["budget"].text = "of ₹20,00,000 initial"
        kpi_labels["inv_value"].text = _fmt_inr(state.inventory_value)
        health = state.inventory_health
        kpi_labels["inv_health"].text = f"{health:.1f}%"
        kpi_subs["inv_health"].text = (
            "Healthy" if health >= 80 else "Needs attention" if health >= 50 else "Critical"
        )

        plot_elements["revenue_profit"].figure = charts.revenue_vs_profit_fig(state.history)
        plot_elements["revenue_profit"].update()
        plot_elements["revenue_category"].figure = charts.revenue_by_category_fig(db.revenue_by_category())
        plot_elements["revenue_category"].update()
        plot_elements["sales_trend"].figure = charts.sales_trend_fig(state.history)
        plot_elements["sales_trend"].update()
        plot_elements["hourly_customers"].figure = charts.hourly_customers_fig(
            db.hourly_customers_today(state.sim_day))
        plot_elements["hourly_customers"].update()
        plot_elements["top_products"].figure = charts.top_products_fig(db.top_products(10))
        plot_elements["top_products"].update()
        plot_elements["inventory_status"].figure = charts.inventory_status_fig(
            db.inventory_status_counts())
        plot_elements["inventory_status"].update()

        events_container.clear()
        with events_container:
            for event in list(state.recent_events)[:8]:
                ui.label(event).style(f"font-size:12px;color:{S.TEXT_PRIMARY};")

    refresh()
    return refresh
