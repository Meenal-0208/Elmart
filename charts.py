"""
charts.py
---------
All Plotly figure builders used on the Admin Dashboard. Every figure shares
the same light-pink color palette so the dashboard feels cohesive.
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

import styles as S

PINK_SEQUENCE = ["#E64980", "#862E56", "#7048E8", "#1971C2", "#F08C00",
                 "#2F9E44", "#C2255C", "#D6336C"]

LAYOUT_DEFAULTS = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family="Segoe UI, sans-serif", color=S.TEXT_PRIMARY, size=12),
    margin=dict(l=10, r=10, t=40, b=10),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
)


def _apply_layout(fig: go.Figure, title: str, height: int = 260) -> go.Figure:
    fig.update_layout(title=dict(text=title, font=dict(size=14, color=S.ACCENT)),
                       height=height, **LAYOUT_DEFAULTS)
    return fig


def revenue_vs_profit_fig(history) -> go.Figure:
    times = [h.ts for h in history]
    revenue = [h.revenue for h in history]
    profit = [h.profit for h in history]

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=times, y=revenue, mode="lines", name="Revenue",
                              line=dict(color=S.PRIMARY_DARKER, width=3),
                              fill="tozeroy", fillcolor="rgba(166,30,77,0.10)"))
    fig.add_trace(go.Scatter(x=times, y=profit, mode="lines", name="Profit",
                              line=dict(color="#1971C2", width=3, dash="solid"),
                              fill="tozeroy", fillcolor="rgba(25,113,194,0.10)"))
    return _apply_layout(fig, "Revenue vs Profit")


def revenue_by_category_fig(df: pd.DataFrame) -> go.Figure:
    if df.empty:
        df = pd.DataFrame({"category": [], "revenue": []})
    fig = go.Figure(go.Bar(
        x=df["category"], y=df["revenue"],
        marker=dict(color=PINK_SEQUENCE * 5),
        text=[f"₹{v:,.0f}" for v in df["revenue"]],
        textposition="outside",
    ))
    fig.update_xaxes(tickangle=-35)
    return _apply_layout(fig, "Revenue by Category", height=300)


def sales_trend_fig(history) -> go.Figure:
    times = [h.ts for h in history]
    orders = [h.orders for h in history]
    fig = go.Figure(go.Scatter(
        x=times, y=orders, mode="lines+markers", name="Orders",
        line=dict(color=S.PRIMARY_DARKER, width=3),
        marker=dict(size=5, color=S.ACCENT),
    ))
    return _apply_layout(fig, "Sales Trend (Cumulative Orders)")


def hourly_customers_fig(df: pd.DataFrame) -> go.Figure:
    if df.empty:
        df = pd.DataFrame({"hour": list(range(24)), "customers": [0] * 24})
    fig = go.Figure(go.Bar(
        x=df["hour"], y=df["customers"],
        marker=dict(color=df["customers"], colorscale=[[0, "#F3D9E6"], [1, "#862E56"]]),
    ))
    fig.update_xaxes(title="Hour of Day", dtick=2)
    return _apply_layout(fig, "Hourly Customer Traffic")


def top_products_fig(df: pd.DataFrame) -> go.Figure:
    if df.empty:
        df = pd.DataFrame({"product_name": [], "revenue": []})
    df = df.sort_values("revenue")
    fig = go.Figure(go.Bar(
        x=df["revenue"], y=df["product_name"], orientation="h",
        marker=dict(color=S.PRIMARY_DARKER),
        text=[f"₹{v:,.0f}" for v in df["revenue"]],
        textposition="outside",
    ))
    return _apply_layout(fig, "Top 10 Products by Revenue", height=320)


def inventory_status_fig(df: pd.DataFrame) -> go.Figure:
    if df.empty:
        df = pd.DataFrame({"status": [], "count": []})
    colors_map = {
        "Out of Stock": S.DANGER, "Low Stock": S.WARNING,
        "In Stock": S.SUCCESS, "Overstocked": S.TRENDING,
    }
    colors = [colors_map.get(s, S.PRIMARY) for s in df["status"]]
    fig = go.Figure(go.Pie(
        labels=df["status"], values=df["count"], hole=0.55,
        marker=dict(colors=colors),
        textinfo="label+percent",
    ))
    return _apply_layout(fig, "Inventory Status", height=300)
