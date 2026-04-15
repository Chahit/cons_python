import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from styles import apply_global_styles, page_header, skeleton_loader


def _fmt_inr(val):
    try:
        v = float(val)
    except Exception:
        return "₹0"
    if v >= 1_00_00_000: return f"₹{v/1_00_00_000:.1f}Cr"
    if v >= 1_00_000:    return f"₹{v/1_00_000:.1f}L"
    if v >= 1_000:       return f"₹{v/1_000:.0f}K"
    return f"₹{int(v)}"


def render(engine):
    apply_global_styles()
    page_header(
        title="Sales Rep Performance",
        subtitle="Monitor field rep ROI, tours, partner coverage, and revenue generation.",
        icon="💼",
        accent_color="#10b981",
    )
    skel = st.empty()
    with skel.container():
        skeleton_loader(n_metric_cards=4, n_rows=2, label="Fetching performance metrics...")
    df = engine.get_sales_rep_leaderboard()
    skel.empty()

    if df.empty:
        st.warning("No sales rep activity logged (or data requires syncing). Only active employees are shown.")
        return

    # ── Search / Select Rep ───────────────────────────────────────────────────
    rep_names = ["🌐 All Reps (Leaderboard)"] + df["sales_rep_name"].tolist()
    selected_rep = st.selectbox(
        "🔍 Select a Sales Rep for Detailed Analysis",
        rep_names,
        key="sales_rep_selector"
    )

    st.markdown("---")

    # ═══════════════════════════════════════════════════════════════════════════
    # INDIVIDUAL REP DRILLDOWN VIEW
    # ═══════════════════════════════════════════════════════════════════════════
    if selected_rep != "🌐 All Reps (Leaderboard)":
        rep_row = df[df["sales_rep_name"] == selected_rep].iloc[0]
        rep_uid = int(rep_row["user_id"])

        # ── Back button ────────────────────────────────────────────────────────
        _back_col, _ = st.columns([1, 4])
        with _back_col:
            if st.button("← Back to Leaderboard", key="srep_back_btn", use_container_width=True):
                st.session_state["sales_rep_selector"] = "🌐 All Reps (Leaderboard)"
                st.rerun()

        st.subheader(f"👤 {selected_rep} — Performance Dashboard")

        # ── Individual KPI cards ─────────────────────────────────────────────
        k1, k2, k3, k4, k5, k6 = st.columns(6)
        k1.metric("Total Revenue", _fmt_inr(rep_row.get("total_revenue", 0)))
        k2.metric("Orders Closed", f"{int(rep_row.get('total_orders', 0)):,}")
        k3.metric("True ROI", f"{min(int(rep_row.get('revenue_roi', 0)), 9999):,}x")
        k4.metric("Partners Served", f"{int(rep_row.get('unique_customers', 0)):,}")
        k5.metric("Expenses Claimed", _fmt_inr(rep_row.get("total_expenses", 0)))
        k6.metric("Issues Logged", f"{int(rep_row.get('issues_logged', 0)):,}")

        st.markdown("")

        # ── Monthly Revenue + Forecast chart ────────────────────────────────
        with st.spinner("Loading monthly revenue data & forecast…"):
            monthly_df = engine.get_sales_rep_monthly_revenue(rep_uid, forecast_months=3)

        if monthly_df.empty:
            st.info("No transaction history found for this rep.")
        else:
            st.subheader("📈 Monthly Revenue — Actual vs. Forecast")
            actual_df   = monthly_df[monthly_df["type"] == "Actual"]
            forecast_df = monthly_df[monthly_df["type"] == "Forecast"]

            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=actual_df["month"], y=actual_df["revenue"],
                mode="lines+markers", name="Actual Revenue",
                line=dict(color="#10b981", width=3), marker=dict(size=8, color="#10b981"),
                hovertemplate="<b>%{x}</b><br>Revenue: Rs %{y:,.0f}<extra></extra>"
            ))
            if not forecast_df.empty:
                connect_df = pd.concat([actual_df.tail(1), forecast_df], ignore_index=True)
                fig.add_trace(go.Scatter(
                    x=connect_df["month"], y=connect_df["revenue"],
                    mode="lines+markers", name="Forecasted Revenue",
                    line=dict(color="#f59e0b", width=2, dash="dash"),
                    marker=dict(size=8, color="#f59e0b", symbol="diamond"),
                    hovertemplate="<b>%{x}</b><br>Forecast: Rs %{y:,.0f}<extra></extra>"
                ))
                fig.add_trace(go.Scatter(
                    x=forecast_df["month"].tolist() + forecast_df["month"].tolist()[::-1],
                    y=(forecast_df["revenue"] * 1.15).tolist() + (forecast_df["revenue"] * 0.85).tolist()[::-1],
                    fill="toself", fillcolor="rgba(245,158,11,0.12)",
                    line=dict(color="rgba(0,0,0,0)"), name="Forecast Range (±15%)",
                    hoverinfo="skip", showlegend=True
                ))
            fig.update_layout(
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                xaxis=dict(title="Month", showgrid=False),
                yaxis=dict(title="Revenue (Rs)", tickformat=",.0f", showgrid=True,
                           gridcolor="rgba(255,255,255,0.07)"),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                margin=dict(l=0, r=0, t=10, b=0), hovermode="x unified"
            )
            st.plotly_chart(fig, use_container_width=True)

            # ── Month-over-month delta table ────────────────────────────────
            if len(actual_df) > 1:
                st.subheader("📊 Month-over-Month Revenue Change")
                delta_df = actual_df[["month", "revenue"]].copy()
                delta_df["prev_revenue"] = delta_df["revenue"].shift(1)
                delta_df["change (Rs)"] = delta_df["revenue"] - delta_df["prev_revenue"]
                delta_df["change (%)"] = ((delta_df["change (Rs)"] / delta_df["prev_revenue"].replace(0, np.nan)) * 100).round(1)
                delta_df = delta_df.dropna(subset=["prev_revenue"])
                delta_df["revenue"] = delta_df["revenue"].astype(int)
                delta_df["change (Rs)"] = delta_df["change (Rs)"].astype(int)
                delta_df.rename(columns={"month": "Month", "revenue": "Revenue (Rs)"}, inplace=True)
                st.dataframe(
                    delta_df[["Month", "Revenue (Rs)", "change (Rs)", "change (%)"]],
                    column_config={
                        "Revenue (Rs)": st.column_config.NumberColumn(format="₹%d"),
                        "change (Rs)": st.column_config.NumberColumn(format="₹%d"),
                        "change (%)": st.column_config.NumberColumn(format="%.1f%%"),
                    },
                    hide_index=True, use_container_width=True
                )

        return

    # ═══════════════════════════════════════════════════════════════════════════
    # ALL REPS LEADERBOARD VIEW
    # ═══════════════════════════════════════════════════════════════════════════
    total_reps      = len(df)
    total_revenue_all = df["total_revenue"].sum() if "total_revenue" in df.columns else 0
    total_tours     = df["total_tours"].sum()
    total_expenses  = df["total_expenses"].sum()
    avg_roi         = df["revenue_roi"].replace([np.inf, -np.inf], np.nan).mean()

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Active Regional Reps", f"{total_reps}")
    col2.metric("Total Revenue", _fmt_inr(total_revenue_all))
    col3.metric("Total Area Tours", f"{int(total_tours)}")
    col4.metric("Total Expenses", _fmt_inr(total_expenses))
    col5.metric("Avg Rep ROI", f"{int(avg_roi) if pd.notnull(avg_roi) else 0}x")
    st.markdown("---")

    st.subheader("🏆 Sales Rep Leaderboard (Active Employees Only)")
    display_df = df[[
        "sales_rep_name", "total_orders", "total_revenue", "unique_customers",
        "total_tours", "total_expenses", "revenue_roi", "issues_logged"
    ]].copy()
    display_df.rename(columns={
        "sales_rep_name": "Sales Rep",
        "total_orders": "Orders",
        "total_revenue": "Revenue (Rs)",
        "unique_customers": "Partners Served",
        "total_tours": "Tours",
        "total_expenses": "Expenses (Rs)",
        "revenue_roi": "ROI (x)",
        "issues_logged": "Issues Logged",
    }, inplace=True)
    display_df["Revenue (Rs)"] = display_df["Revenue (Rs)"].fillna(0).astype(int)
    display_df["Expenses (Rs)"] = display_df["Expenses (Rs)"].fillna(0).astype(int)
    display_df["ROI (x)"] = display_df["ROI (x)"].replace([np.inf, -np.inf], 9999).fillna(0).astype(int)

    st.dataframe(
        display_df,
        column_config={
            "Revenue (Rs)": st.column_config.NumberColumn(format="₹%d"),
            "Expenses (Rs)": st.column_config.NumberColumn(format="₹%d"),
            "ROI (x)": st.column_config.NumberColumn(format="%dx"),
            "Orders": st.column_config.NumberColumn(format="%d"),
        },
        hide_index=True, use_container_width=True, height=450
    )

    st.markdown("---")

    # ── ROI Scatter + Partner Coverage ───────────────────────────────────────
    colA, colB = st.columns(2)
    with colA:
        st.subheader("💸 Expense vs Revenue Yield")
        if df["total_expenses"].sum() > 0:
            fig = px.scatter(
                df, x="total_expenses", y="total_revenue",
                size="unique_customers",
                hover_name="sales_rep_name", text="sales_rep_name",
                labels={
                    "total_revenue": "Total Revenue (Rs)",
                    "total_expenses": "Field Expenses (Rs)",
                },
            )
            fig.update_traces(textposition="top center", textfont_size=10)
            fig.update_layout(
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                margin=dict(l=0, r=0, t=10, b=0), showlegend=False
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Insufficient expense data.")

    with colB:
        st.subheader("📦 Partner Coverage per Rep")
        coverage_df = df.sort_values("unique_customers", ascending=False)
        fig_cov = px.bar(
            coverage_df, x="sales_rep_name", y="unique_customers",
            color="unique_customers",
            color_continuous_scale=["#1e40af", "#3b82f6", "#10b981"],
            labels={"unique_customers": "Partners Served", "sales_rep_name": "Rep"},
            text="unique_customers",
        )
        fig_cov.update_traces(texttemplate="%{text}", textposition="outside")
        fig_cov.update_layout(
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            coloraxis_showscale=False, margin=dict(l=0, r=0, t=10, b=0),
        )
        st.plotly_chart(fig_cov, use_container_width=True)

    # ── Service & Issue Management ────────────────────────────────────────────
    st.markdown("---")
    st.subheader("⚠️ Partner Issue Management by Rep")
    st.caption("High orders with 0 issues may indicate gaps in after-sales follow-up.")

    issue_df = df.sort_values("issues_logged", ascending=False).head(10)
    if issue_df["issues_logged"].sum() > 0:
        fig_issues = px.bar(
            issue_df, x="sales_rep_name",
            y=["issues_logged", "total_orders"],
            barmode="group",
            labels={"sales_rep_name": "Sales Rep", "value": "Count", "variable": "Metric"},
            color_discrete_map={"issues_logged": "#f59e0b", "total_orders": "#3b82f6"},
        )
        fig_issues.update_layout(
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            margin=dict(l=0, r=0, t=10, b=0)
        )
        st.plotly_chart(fig_issues, use_container_width=True)
    else:
        st.info("No partner issues logged by reps yet.")

    # ── Revenue Efficiency Table ──────────────────────────────────────────────
    st.markdown("---")
    st.subheader("📐 Revenue Efficiency Analysis")
    eff_df = df[["sales_rep_name", "total_revenue", "total_orders", "total_expenses",
                 "unique_customers"]].copy()
    eff_df["Rev per Order"] = (eff_df["total_revenue"] / eff_df["total_orders"].replace(0, np.nan)).fillna(0).round(0).astype(int)
    eff_df["Rev per Partner"] = (eff_df["total_revenue"] / eff_df["unique_customers"].replace(0, np.nan)).fillna(0).round(0).astype(int)
    eff_df["Cost per Order"] = (eff_df["total_expenses"] / eff_df["total_orders"].replace(0, np.nan)).fillna(0).round(0).astype(int)
    eff_df = eff_df[["sales_rep_name", "Rev per Order", "Rev per Partner", "Cost per Order"]].rename(
        columns={"sales_rep_name": "Sales Rep"}
    )
    st.dataframe(
        eff_df,
        column_config={
            "Rev per Order":   st.column_config.NumberColumn("Avg Revenue/Order (Rs)", format="₹%d"),
            "Rev per Partner": st.column_config.NumberColumn("Avg Revenue/Partner (Rs)", format="₹%d"),
            "Cost per Order":  st.column_config.NumberColumn("Avg Cost/Order (Rs)", format="₹%d"),
        },
        hide_index=True, use_container_width=True
    )
