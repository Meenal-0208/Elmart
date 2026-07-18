"""
database.py
------------
DuckDB data-access layer for the Retail Analytics Platform.
All reads/writes for products, orders and the hourly customer log go
through this module so the rest of the app never talks to SQL directly.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

import duckdb
import pandas as pd
import polars as pl


class Database:
    """Thin wrapper around an in-memory DuckDB connection."""

    def __init__(self, db_path: str = ":memory:"):
        self.conn = duckdb.connect(db_path)
        self._create_schema()

    # ------------------------------------------------------------------ #
    # schema
    # ------------------------------------------------------------------ #
    def _create_schema(self) -> None:
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id             VARCHAR PRIMARY KEY,
                name           VARCHAR,
                brand          VARCHAR,
                category       VARCHAR,
                cost_price     DOUBLE,
                selling_price  DOUBLE,
                discount       DOUBLE,
                quantity       INTEGER,
                rating         DOUBLE,
                image          VARCHAR,
                flash_sale     BOOLEAN,
                trending       BOOLEAN
            );
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                order_id       VARCHAR PRIMARY KEY,
                product_id     VARCHAR,
                product_name   VARCHAR,
                category       VARCHAR,
                quantity       INTEGER,
                unit_price     DOUBLE,
                unit_cost      DOUBLE,
                total          DOUBLE,
                profit         DOUBLE,
                is_return      BOOLEAN,
                manual         BOOLEAN,
                ts             TIMESTAMP,
                customer_id    VARCHAR,
                delivery_date  TIMESTAMP,
                confirmation_no VARCHAR,
                payment_method VARCHAR
            );
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS customer_log (
                sim_day        INTEGER,
                hour           INTEGER,
                customers      INTEGER,
                ts             TIMESTAMP
            );
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS customers (
                customer_id    VARCHAR PRIMARY KEY,
                name           VARCHAR,
                email          VARCHAR,
                phone          VARCHAR,
                city           VARCHAR,
                segment        VARCHAR,
                joined_date    TIMESTAMP,
                total_orders   INTEGER,
                total_spent    DOUBLE,
                last_order_ts  TIMESTAMP,
                loyalty_points INTEGER
            );
        """)

    # ------------------------------------------------------------------ #
    # products
    # ------------------------------------------------------------------ #
    def is_empty(self) -> bool:
        return self.conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0

    def insert_products(self, df: pl.DataFrame) -> None:
        pdf = df.to_pandas()
        self.conn.register("df_products", pdf)
        self.conn.execute("INSERT INTO products SELECT * FROM df_products")
        self.conn.unregister("df_products")

    def get_products_df(self) -> pd.DataFrame:
        return self.conn.execute("SELECT * FROM products").fetchdf()

    def get_product(self, product_id: str) -> Optional[pd.Series]:
        df = self.conn.execute("SELECT * FROM products WHERE id = ?", [product_id]).fetchdf()
        if df.empty:
            return None
        return df.iloc[0]

    def get_categories(self) -> list[str]:
        rows = self.conn.execute("SELECT DISTINCT category FROM products ORDER BY category").fetchall()
        return [r[0] for r in rows]

    def update_product_fields(self, product_id: str, **fields) -> None:
        """Generic update for arbitrary numeric columns, e.g.
        update_product_fields('P0001', selling_price=999.0, quantity=10)"""
        if not fields:
            return
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [product_id]
        self.conn.execute(f"UPDATE products SET {set_clause} WHERE id = ?", values)

    def adjust_quantity(self, product_id: str, delta: int) -> None:
        self.conn.execute(
            "UPDATE products SET quantity = GREATEST(quantity + ?, 0) WHERE id = ?",
            [delta, product_id],
        )

    def set_flash_sale(self, product_id: str, active: bool) -> None:
        self.conn.execute("UPDATE products SET flash_sale = ? WHERE id = ?", [active, product_id])

    def nudge_price(self, product_id: str, pct_change: float) -> None:
        self.conn.execute(
            "UPDATE products SET selling_price = GREATEST(ROUND(selling_price * (1 + ?), 0), cost_price * 1.02) "
            "WHERE id = ?",
            [pct_change, product_id],
        )

    def random_products(self, n: int = 1, only_in_stock: bool = True) -> pd.DataFrame:
        clause = "WHERE quantity > 0" if only_in_stock else ""
        return self.conn.execute(
            f"SELECT * FROM products {clause} ORDER BY random() LIMIT ?", [n]
        ).fetchdf()

    def weighted_random_products(self, n: int = 1) -> pd.DataFrame:
        """Favor trending / flash-sale / higher-rated products, like real shoppers would."""
        return self.conn.execute(
            f"""
            SELECT * FROM products
            WHERE quantity > 0
            ORDER BY random() * (1.0 / (1.0 + rating))
                     - (CASE WHEN trending THEN 0.4 ELSE 0 END)
                     - (CASE WHEN flash_sale THEN 0.5 ELSE 0 END)
            LIMIT ?
            """,
            [n],
        ).fetchdf()

    # ------------------------------------------------------------------ #
    # orders
    # ------------------------------------------------------------------ #
    def insert_order(self, order: dict) -> None:
        self.conn.execute(
            """INSERT INTO orders VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [
                order["order_id"], order["product_id"], order["product_name"],
                order["category"], order["quantity"], order["unit_price"],
                order["unit_cost"], order["total"], order["profit"],
                order["is_return"], order["manual"], order["ts"],
                order.get("customer_id", "GUEST"), order.get("delivery_date"),
                order.get("confirmation_no", order["order_id"]),
                order.get("payment_method"),
            ],
        )

    def get_orders_df(self) -> pd.DataFrame:
        return self.conn.execute("SELECT * FROM orders ORDER BY ts").fetchdf()

    def total_revenue(self) -> float:
        val = self.conn.execute(
            "SELECT COALESCE(SUM(total),0) FROM orders WHERE is_return = FALSE"
        ).fetchone()[0]
        return float(val)

    def total_cogs(self) -> float:
        val = self.conn.execute(
            "SELECT COALESCE(SUM(unit_cost * quantity),0) FROM orders WHERE is_return = FALSE"
        ).fetchone()[0]
        return float(val)

    def total_returns_value(self) -> float:
        val = self.conn.execute(
            "SELECT COALESCE(SUM(total),0) FROM orders WHERE is_return = TRUE"
        ).fetchone()[0]
        return float(val)

    def order_count(self) -> int:
        return int(self.conn.execute(
            "SELECT COUNT(*) FROM orders WHERE is_return = FALSE"
        ).fetchone()[0])

    def revenue_by_category(self) -> pd.DataFrame:
        return self.conn.execute("""
            SELECT category, SUM(total) AS revenue
            FROM orders WHERE is_return = FALSE
            GROUP BY category ORDER BY revenue DESC
        """).fetchdf()

    def top_products(self, limit: int = 10) -> pd.DataFrame:
        return self.conn.execute("""
            SELECT product_name, SUM(total) AS revenue, SUM(quantity) AS units
            FROM orders WHERE is_return = FALSE
            GROUP BY product_name ORDER BY revenue DESC LIMIT ?
        """, [limit]).fetchdf()

    def inventory_value(self) -> float:
        val = self.conn.execute(
            "SELECT COALESCE(SUM(quantity * cost_price),0) FROM products"
        ).fetchone()[0]
        return float(val)

    def inventory_status_counts(self) -> pd.DataFrame:
        return self.conn.execute("""
            SELECT
                CASE
                    WHEN quantity = 0 THEN 'Out of Stock'
                    WHEN quantity <= 15 THEN 'Low Stock'
                    WHEN quantity <= 150 THEN 'In Stock'
                    ELSE 'Overstocked'
                END AS status,
                COUNT(*) AS count
            FROM products
            GROUP BY status
        """).fetchdf()

    def inventory_health_pct(self) -> float:
        row = self.conn.execute("""
            SELECT
                SUM(CASE WHEN quantity > 15 THEN 1 ELSE 0 END) AS healthy,
                COUNT(*) AS total
            FROM products
        """).fetchone()
        healthy, total = row
        if not total:
            return 100.0
        return round(100.0 * healthy / total, 1)

    def paginated_products(self, page: int, page_size: int = 15,
                            category: Optional[str] = None) -> pd.DataFrame:
        offset = page * page_size
        if category and category != "All":
            return self.conn.execute(
                "SELECT * FROM products WHERE category = ? ORDER BY id LIMIT ? OFFSET ?",
                [category, page_size, offset],
            ).fetchdf()
        return self.conn.execute(
            "SELECT * FROM products ORDER BY id LIMIT ? OFFSET ?",
            [page_size, offset],
        ).fetchdf()

    def product_count(self, category: Optional[str] = None) -> int:
        if category and category != "All":
            return int(self.conn.execute(
                "SELECT COUNT(*) FROM products WHERE category = ?", [category]
            ).fetchone()[0])
        return int(self.conn.execute("SELECT COUNT(*) FROM products").fetchone()[0])

    # ------------------------------------------------------------------ #
    # customer log
    # ------------------------------------------------------------------ #
    def log_customers(self, sim_day: int, hour: int, customers: int) -> None:
        self.conn.execute(
            "INSERT INTO customer_log VALUES (?, ?, ?, ?)",
            [sim_day, hour, customers, datetime.now()],
        )

    def hourly_customers_today(self, sim_day: int) -> pd.DataFrame:
        return self.conn.execute("""
            SELECT hour, SUM(customers) AS customers
            FROM customer_log
            WHERE sim_day = ?
            GROUP BY hour ORDER BY hour
        """, [sim_day]).fetchdf()

    def customers_today(self, sim_day: int) -> int:
        val = self.conn.execute(
            "SELECT COALESCE(SUM(customers),0) FROM customer_log WHERE sim_day = ?",
            [sim_day],
        ).fetchone()[0]
        return int(val)

    # ------------------------------------------------------------------ #
    # CRM customers
    # ------------------------------------------------------------------ #
    def customers_is_empty(self) -> bool:
        return self.conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0] == 0

    def insert_customers(self, df: pd.DataFrame) -> None:
        self.conn.register("df_customers", df)
        self.conn.execute("INSERT INTO customers SELECT * FROM df_customers")
        self.conn.unregister("df_customers")

    def get_customers_df(self) -> pd.DataFrame:
        return self.conn.execute("SELECT * FROM customers").fetchdf()

    def customer_count(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0])

    def top_customers(self, limit: int = 5) -> pd.DataFrame:
        return self.conn.execute("""
            SELECT * FROM customers
            WHERE total_orders > 0
            ORDER BY total_spent DESC LIMIT ?
        """, [limit]).fetchdf()

    def segment_counts(self) -> pd.DataFrame:
        return self.conn.execute("""
            SELECT segment, COUNT(*) AS count, COALESCE(SUM(total_spent),0) AS total_spent
            FROM customers GROUP BY segment ORDER BY total_spent DESC
        """).fetchdf()

    def search_customers(self, term: str) -> pd.DataFrame:
        like = f"%{term.lower().strip()}%"
        return self.conn.execute("""
            SELECT * FROM customers
            WHERE lower(name) LIKE ? OR lower(customer_id) LIKE ? OR lower(city) LIKE ?
            ORDER BY total_spent DESC LIMIT 5
        """, [like, like, like]).fetchdf()

    def random_customer_ids(self, n: int) -> list[str]:
        """Pick n random existing customers, e.g. to attribute simulated orders."""
        if n <= 0:
            return []
        rows = self.conn.execute(
            "SELECT customer_id FROM customers ORDER BY random() LIMIT ?", [n]
        ).fetchall()
        return [r[0] for r in rows]

    def record_customer_order(self, customer_id: str, amount: float, ts) -> None:
        """Updates a customer's order count / lifetime spend / segment /
        loyalty points after a new (non-return) order is booked against them."""
        row = self.conn.execute(
            "SELECT total_orders, total_spent FROM customers WHERE customer_id = ?",
            [customer_id],
        ).fetchone()
        if row is None:
            return
        total_orders = int(row[0]) + 1
        total_spent = float(row[1]) + amount
        if total_spent >= 75_000 or total_orders >= 15:
            segment = "VIP"
        elif total_orders >= 3:
            segment = "Regular"
        else:
            segment = "New"
        loyalty_points = int(total_spent // 100)
        self.conn.execute(
            "UPDATE customers SET total_orders=?, total_spent=?, last_order_ts=?, "
            "segment=?, loyalty_points=? WHERE customer_id=?",
            [total_orders, total_spent, ts, segment, loyalty_points, customer_id],
        )

    def get_customer(self, customer_id: str):
        df = self.conn.execute(
            "SELECT * FROM customers WHERE customer_id = ?", [customer_id]
        ).fetchdf()
        if df.empty:
            return None
        return df.iloc[0]

    # ------------------------------------------------------------------ #
    # storefront chatbot support: product search, recommendations, orders
    # ------------------------------------------------------------------ #
    def search_products(self, term: str, limit: int = 5) -> pd.DataFrame:
        words = [w for w in re.split(r"\s+", term.lower().strip()) if w]
        if not words:
            return pd.DataFrame()
        conditions = []
        params: list = []
        for w in words:
            like = f"%{w}%"
            conditions.append("(lower(name) LIKE ? OR lower(brand) LIKE ? OR lower(category) LIKE ?)")
            params.extend([like, like, like])
        where_clause = " AND ".join(conditions)
        params.append(limit)
        return self.conn.execute(
            f"SELECT * FROM products WHERE {where_clause} ORDER BY rating DESC LIMIT ?",
            params,
        ).fetchdf()

    def trending_products(self, limit: int = 5) -> pd.DataFrame:
        return self.conn.execute("""
            SELECT * FROM products WHERE trending = TRUE AND quantity > 0
            ORDER BY rating DESC LIMIT ?
        """, [limit]).fetchdf()

    def flash_sale_products(self, limit: int = 5) -> pd.DataFrame:
        return self.conn.execute("""
            SELECT * FROM products WHERE flash_sale = TRUE AND quantity > 0
            ORDER BY discount DESC LIMIT ?
        """, [limit]).fetchdf()

    def top_rated_products(self, category: Optional[str] = None, limit: int = 5) -> pd.DataFrame:
        if category:
            return self.conn.execute("""
                SELECT * FROM products WHERE lower(category) = lower(?) AND quantity > 0
                ORDER BY rating DESC LIMIT ?
            """, [category, limit]).fetchdf()
        return self.conn.execute("""
            SELECT * FROM products WHERE quantity > 0 ORDER BY rating DESC LIMIT ?
        """, [limit]).fetchdf()

    def customer_orders(self, customer_id: str, limit: int = 5) -> pd.DataFrame:
        return self.conn.execute("""
            SELECT confirmation_no, MIN(ts) AS ts, MIN(delivery_date) AS delivery_date,
                   STRING_AGG(product_name, ', ') AS items,
                   SUM(quantity) AS total_units, SUM(total) AS total,
                   MAX(payment_method) AS payment_method
            FROM orders
            WHERE customer_id = ? AND is_return = FALSE
            GROUP BY confirmation_no
            ORDER BY ts DESC LIMIT ?
        """, [customer_id, limit]).fetchdf()

    def find_order(self, customer_id: str, confirmation_no: str):
        df = self.conn.execute("""
            SELECT confirmation_no, MIN(ts) AS ts, MIN(delivery_date) AS delivery_date,
                   STRING_AGG(product_name, ', ') AS items,
                   SUM(quantity) AS total_units, SUM(total) AS total,
                   MAX(payment_method) AS payment_method
            FROM orders
            WHERE customer_id = ? AND lower(confirmation_no) = lower(?)
            GROUP BY confirmation_no
        """, [customer_id, confirmation_no]).fetchdf()
        if df.empty:
            return None
        return df.iloc[0]
