import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import sys, os
from datetime import date, timedelta
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


@st.cache_data(ttl=120, show_spinner=False)
def _fetch_rep_period_stats(_engine, start: date, end: date) -> pd.DataFrame:
    """Revenue & orders per sales rep for the selected date window.
    Starts from transactions (same as Sales Analyzer) so the total always
    matches 538.72 Cr. Transactions with no active rep are grouped as
    'Unattributed' rather than being silently dropped.
    Uses INNER JOIN due_payment — identical filter to Sales Analyzer.
    """
    if _engine is None:
        return pd.DataFrame()
    try:
        return pd.read_sql(
            """
            SELECT
                COALESCE(u.id, -1)                            AS user_id,
                COALESCE(
                    NULLIF(TRIM(
                        COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,'')
                    ), ''),
                    u.username,
                    'Unattributed'
                )                                             AS sales_rep_name,
                COALESCE(u.username, 'unattributed')          AS username,
                COUNT(DISTINCT t.id)                          AS period_orders,
                COALESCE(SUM(tp.net_amt), 0)                  AS period_revenue,
                COUNT(DISTINCT t.party_id)                    AS period_partners
            FROM transactions_dsr t
            JOIN transactions_dsr_products tp ON tp.dsr_id = t.id
            JOIN due_payment dp ON dp.dsr_id = t.id
                 AND dp.is_active = TRUE AND dp.deleted_at IS NULL
            LEFT JOIN auth_user u ON u.id = t.user_id AND u.is_active = TRUE
            WHERE LOWER(CAST(t.is_approved AS TEXT)) = 'true'
              AND t.date BETWEEN %(s)s AND %(e)s
            GROUP BY u.id, u.first_name, u.last_name, u.username
            ORDER BY period_revenue DESC
            """,
            _engine,
            params={"s": start, "e": end},
        )
    except Exception:
        return pd.DataFrame()


def _render_date_picker() -> tuple:
    """Render a date-range picker chip bar identical to the Sales Analyzer."""
    st.markdown("""
    <style>
    div[data-testid="column"] .stButton>button{
        border-radius:20px!important;font-size:12px!important;
        padding:4px 14px!important;border:1px solid #374151!important;
        background:#1e2235!important;color:#10b981!important;
        transition:all 0.18s ease!important;
    }
    div[data-testid="column"] .stButton>button:hover{
        background:#059669!important;border-color:#059669!important;color:#fff!important;
    }
    </style>""", unsafe_allow_html=True)

    today = date.today()
    if "srep_date_start" not in st.session_state:
        st.session_state["srep_date_start"] = today - timedelta(days=365)
    if "srep_date_end" not in st.session_state:
        st.session_state["srep_date_end"] = today

    st.markdown("<div style='font-size:11px;color:#64748b;margin-bottom:4px;'>🗓️ Custom Range</div>",
                unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1.5, 1.5, 1])
    with c1:
        new_start = st.date_input("Start Date", value=st.session_state["srep_date_start"],
                                  max_value=today, key="srep_cal_start")
    with c2:
        new_end = st.date_input("End Date", value=st.session_state["srep_date_end"],
                                min_value=new_start, max_value=today, key="srep_cal_end")
    with c3:
        st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        if st.button("✅ Apply", key="srep_apply", use_container_width=True):
            st.session_state["srep_date_start"] = new_start
            st.session_state["srep_date_end"]   = new_end

    sel_start = st.session_state["srep_date_start"]
    sel_end   = st.session_state["srep_date_end"]
    if sel_end < sel_start:
        sel_end = sel_start
    span = max((sel_end - sel_start).days, 1)

    st.markdown(f"""
    <div style='background:rgba(15,26,43,0.9);border:1px solid #1e3a5f;border-radius:8px;
         padding:8px 16px;margin-top:8px;display:flex;align-items:center;gap:10px;'>
      <span style='font-size:15px;'>📅</span>
      <span style='color:#6ee7b7;font-size:13px;font-weight:600;'>Active Window</span>
      <span style='color:#475569;'>–</span>
      <span style='color:#64748b;font-size:12px;'>
        <b style='color:#7eb8f0;'>{sel_start.strftime('%d %b %Y')}</b>
        &nbsp;→&nbsp;
        <b style='color:#7eb8f0;'>{sel_end.strftime('%d %b %Y')}</b>
      </span>
      <span style='margin-left:auto;font-size:11px;color:#4b5563;'>{span} day window</span>
    </div>""", unsafe_allow_html=True)

    return sel_start, sel_end, span


def render(engine):
    apply_global_styles()
    page_header(
        title="Sales Rep Performance",
        subtitle="Monitor field rep ROI, tours, partner coverage, and revenue generation.",
        icon="💼",
        accent_color="#10b981",
    )

    # ── Date Picker ───────────────────────────────────────────────────────────
    sel_start, sel_end, span_days = _render_date_picker()
    date_label = f"{sel_start.strftime('%d %b %Y')} → {sel_end.strftime('%d %b %Y')}"
    st.markdown("---")

    # ── Fetch period-specific stats directly from DB ──────────────────────────
    _db_engine = getattr(engine, "engine", None)
    period_df = _fetch_rep_period_stats(_db_engine, sel_start, sel_end)

    skel = st.empty()
    with skel.container():
        skeleton_loader(n_metric_cards=4, n_rows=2, label="Fetching performance metrics...")
    df_all = engine.get_sales_rep_leaderboard()   # all-time for context
    skel.empty()

    if df_all.empty and period_df.empty:
        st.warning("No sales rep activity logged (or data requires syncing). Only active employees are shown.")
        return

    # Merge period revenue onto leaderboard
    if not period_df.empty:
        period_df["sales_rep_name"] = period_df["sales_rep_name"].str.strip()
        period_df["sales_rep_name"] = np.where(
            period_df["sales_rep_name"] == "",
            period_df["username"],
            period_df["sales_rep_name"],
        )
        df = df_all.merge(
            period_df[["sales_rep_name", "period_revenue", "period_orders", "period_partners"]],
            on="sales_rep_name", how="left",
        )
        df["period_revenue"]  = df["period_revenue"].fillna(0)
        df["period_orders"]   = df["period_orders"].fillna(0).astype(int)
        df["period_partners"] = df["period_partners"].fillna(0).astype(int)
    else:
        df = df_all.copy()
        df["period_revenue"]  = 0
        df["period_orders"]   = 0
        df["period_partners"] = 0

    if df.empty:
        st.warning("No sales rep activity found.")
        return


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
    total_reps        = len(df)
    period_rev_total  = df["period_revenue"].sum() if "period_revenue" in df.columns else 0
    total_revenue_all = df["total_revenue"].sum() if "total_revenue" in df.columns else 0
    total_tours       = df["total_tours"].sum()
    total_expenses    = df["total_expenses"].sum()
    avg_roi           = df["revenue_roi"].replace([np.inf, -np.inf], np.nan).mean()
    period_orders_tot = int(df["period_orders"].sum()) if "period_orders" in df.columns else 0

    col1, col2, col3, col4, col5, col6 = st.columns(6)
    col1.metric("Active Regional Reps",       f"{total_reps}")
    col2.metric(f"Revenue ({date_label})",    _fmt_inr(period_rev_total))
    col3.metric(f"Orders ({date_label})",     f"{period_orders_tot:,}")
    col4.metric("All-Time Revenue",           _fmt_inr(total_revenue_all))
    col5.metric("Total Expenses (All-Time)",  _fmt_inr(total_expenses))
    col6.metric("Avg Rep ROI",                f"{int(avg_roi) if pd.notnull(avg_roi) else 0}x")
    st.markdown("---")

    st.subheader(f"🏆 Sales Rep Leaderboard — {date_label}")
    disp_cols = ["sales_rep_name", "period_revenue", "period_orders", "period_partners",
                 "total_revenue", "total_tours", "total_expenses", "revenue_roi", "issues_logged"]
    disp_cols = [c for c in disp_cols if c in df.columns]
    display_df = df[disp_cols].copy()
    display_df = display_df.sort_values("period_revenue", ascending=False)
    display_df.rename(columns={
        "sales_rep_name":   "Sales Rep",
        "period_revenue":   f"Revenue ({date_label})",
        "period_orders":    f"Orders ({date_label})",
        "period_partners":  f"Partners ({date_label})",
        "total_revenue":    "All-Time Revenue (Rs)",
        "total_tours":      "Tours",
        "total_expenses":   "Expenses (Rs)",
        "revenue_roi":      "ROI (x)",
        "issues_logged":    "Issues",
    }, inplace=True)
    for col in ["All-Time Revenue (Rs)", "Expenses (Rs)"]:
        if col in display_df.columns:
            display_df[col] = display_df[col].fillna(0).astype(int)
    if "ROI (x)" in display_df.columns:
        display_df["ROI (x)"] = display_df["ROI (x)"].replace([np.inf, -np.inf], 9999).fillna(0).astype(int)

    st.dataframe(
        display_df,
        column_config={
            f"Revenue ({date_label})":  st.column_config.NumberColumn(format="₹%d"),
            "All-Time Revenue (Rs)":    st.column_config.NumberColumn(format="₹%d"),
            "Expenses (Rs)":            st.column_config.NumberColumn(format="₹%d"),

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
