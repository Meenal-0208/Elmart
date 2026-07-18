"""
app.py
------
Entry point for Elmart - the Retail Analytics Platform.

Run with:
    python app.py

Opens a browser window with a 50/50 split screen:
  - Left  : Elmart storefront (500 products, 20 categories, real product photos)
  - Right : Live Admin Dashboard (KPIs, charts, editable inventory)

A background simulation (see simulation.py) mutates the DuckDB database
every 2.5 seconds - new customers, purchases, returns, restocks, flash
sales and price changes - and the UI refreshes instantly, no page reload.
"""
from __future__ import annotations

from pathlib import Path

from nicegui import app, ui

import styles as S
from customers import generate_customers
from dashboard import build_dashboard_ui
from database import Database
from products import generate_logo, generate_products
from simulation import SimulationState, SIMULATION_INTERVAL_SECONDS
from store import build_store_ui

BASE_DIR = Path(__file__).parent
ASSETS_DIR = BASE_DIR / "assets"


def bootstrap_database() -> Database:
    """Create the DuckDB database and seed it with 500 products the first
    time the app starts."""
    generate_logo()
    db = Database()
    if db.is_empty():
        products_df = generate_products(500)
        db.insert_products(products_df)
    if db.customers_is_empty():
        customers_df = generate_customers(150)
        db.insert_customers(customers_df)
    return db


@ui.page("/")
def main_page():
    ui.add_head_html(S.GLOBAL_CSS)
    ui.query("body").style(f"background:{S.BACKGROUND};")

    db: Database = app.state_db
    state: SimulationState = app.state_sim

    with ui.row().classes("w-full no-wrap gap-0").style(
            "margin:0;padding:0;height:100vh;overflow:hidden;"):

        # ---------------- LEFT: Storefront (50%) ---------------------- #
        with ui.column().style(
                f"width:50%;height:100vh;background:{S.BACKGROUND};"
                f"border-right:2px solid {S.BORDER};padding:0;gap:0;overflow:hidden;"):
            store_refresh = build_store_ui(db, state)

        # ---------------- RIGHT: Admin Dashboard (50%) ------------------ #
        with ui.column().style(
                f"width:50%;height:100vh;background:{S.BACKGROUND};padding:0;gap:0;overflow:hidden;"):
            dashboard_refresh = build_dashboard_ui(db, state)

    def tick():
        state.tick()
        dashboard_refresh()
        store_refresh()

    ui.timer(SIMULATION_INTERVAL_SECONDS, tick)


def create_app():
    app.state_db = bootstrap_database()
    app.state_sim = SimulationState(db=app.state_db)
    app.add_static_files("/assets", str(ASSETS_DIR))


create_app()

if __name__ in {"__main__", "__mp_main__"}:
    ui.run(
        title="Elmart | Retail Analytics Platform",
        favicon="🛍️",
        reload=False,
        port=8080,
        show=True,
        dark=False,
    )
