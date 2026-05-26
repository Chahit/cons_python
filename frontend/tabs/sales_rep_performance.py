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


def _fetch_rep_territory_stats(engine, user_id: int) -> pd.DataFrame:
    """Fetches the state/city distribution of revenue for a specific rep."""
    if engine is None:
        return pd.DataFrame()
    try:
        return pd.read_sql(
            """
            SELECT 
                COALESCE(s.name, 'Unknown State')              AS state_name,
                COALESCE(c.name, 'Unknown City')               AS city_name,
                COALESCE(SUM(tp.net_amt), 0)                   AS revenue
            FROM transactions_dsr t
            JOIN transactions_dsr_products tp ON tp.dsr_id = t.id
            JOIN due_payment dp ON dp.dsr_id = t.id
                 AND dp.is_active = TRUE AND dp.deleted_at IS NULL
            LEFT JOIN master_party p ON p.id = t.party_id
            LEFT JOIN master_area_state mas ON mas.id = p.state_id
            LEFT JOIN master_state s ON s.id = mas.state_id
            LEFT JOIN master_area_city mac ON mac.id = p.city_id
            LEFT JOIN master_city c ON c.id = mac.city_id
            WHERE LOWER(CAST(t.is_approved AS TEXT)) = 'true'
              AND t.user_id = %(uid)s
            GROUP BY s.name, c.name
            ORDER BY revenue DESC
            LIMIT 15
            """,
            engine,
            params={"uid": user_id}
        )
    except Exception:
        return pd.DataFrame()


def _get_rep_badge(row, df_all) -> str:
    """Dynamic B2B achievement badging based on dynamic percentile metrics."""
    if df_all is None or df_all.empty or row.get("user_id") not in df_all["user_id"].values:
        return "⭐ Field Specialist"
    all_row = df_all[df_all["user_id"] == row["user_id"]].iloc[0]
    
    rev_90  = df_all["total_revenue"].quantile(0.90)
    roi_85  = df_all["revenue_roi"].quantile(0.85)
    cust_80 = df_all["unique_customers"].quantile(0.80)
    
    rev = all_row["total_revenue"]
    roi = all_row["revenue_roi"]
    cust = all_row["unique_customers"]
    
    if rev >= rev_90 and rev > 0:
        return "👑 Revenue Champion"
    if roi >= roi_85 and roi > 0:
        return "⚡ High ROI Leader"
    if cust >= cust_80 and cust > 0:
        return "🛡️ Partner Guardian"
    return "⭐ Field Specialist"


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
        st.warning("No sales rep activity logged. Only active employees are shown.")
        return

    # Use period_df directly as the leaderboard source — do NOT merge onto df_all.
    # Merging on sales_rep_name string drops 'Unattributed' rows (transactions
    # with no active user) causing ~13 Cr to vanish from the total.
    # period_df already contains all reps + unattributed, summing to 538.72 Cr.
    if not period_df.empty:
        period_df["sales_rep_name"] = period_df["sales_rep_name"].str.strip()
        period_df["sales_rep_name"] = np.where(
            period_df["sales_rep_name"] == "",
            period_df["username"],
            period_df["sales_rep_name"],
        )
        df = period_df.copy()
    else:
        # No period data — fall back to all-time leaderboard with zero period cols
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

        # ── BUG-01 & Wow Factor 2: Comparative KPI Cards & Badging ──
        all_time_row = None
        if df_all is not None and not df_all.empty and rep_uid in df_all["user_id"].values:
            all_time_row = df_all[df_all["user_id"] == rep_uid].iloc[0]

        tot_rev = all_time_row["total_revenue"] if all_time_row is not None else 0
        tot_ord = all_time_row["total_orders"] if all_time_row is not None else 0
        tot_roi = all_time_row["revenue_roi"] if all_time_row is not None else 0
        tot_cust = all_time_row["unique_customers"] if all_time_row is not None else 0
        tot_exp = all_time_row["total_expenses"] if all_time_row is not None else 0
        tot_iss = all_time_row["issues_logged"] if all_time_row is not None else 0

        per_rev = rep_row.get("period_revenue", 0)
        per_ord = rep_row.get("period_orders", 0)
        per_cust = rep_row.get("period_partners", 0)
        
        rep_badge = _get_rep_badge(rep_row, df_all)

        st.markdown("### 📊 Performance Baselines")
        k1, k2, k3 = st.columns(3)
        k1.metric(
            label="Revenue (Active Window / All-Time)",
            value=_fmt_inr(per_rev),
            delta=f"All-Time: {_fmt_inr(tot_rev)}",
            delta_color="off"
        )
        k2.metric(
            label="Orders Closed (Active Window / All-Time)",
            value=f"{int(per_ord):,}",
            delta=f"All-Time: {int(tot_ord):,}",
            delta_color="off"
        )
        k3.metric(
            label="Partners Served (Active Window / All-Time)",
            value=f"{int(per_cust):,}",
            delta=f"All-Time: {int(tot_cust):,}",
            delta_color="off"
        )

        st.markdown("<div style='margin-top: 10px;'></div>", unsafe_allow_html=True)
        k4, k5, k6 = st.columns(3)
        k4.metric(
            label="True ROI (Revenue/Expenses)",
            value=f"{min(int(tot_roi), 9999):,}x" if tot_roi > 0 else "0x",
            delta=f"Total Expenses: {_fmt_inr(tot_exp)}",
            delta_color="inverse"
        )
        k5.metric(
            label="Field Issues Logged",
            value=f"{int(tot_iss):,}",
            delta="All-Time Count",
            delta_color="off"
        )
        st.markdown(
            f"<div style='background:#161b2a;border-radius:8px;padding:10px 14px;border:1px solid #1e2433;height:84px;'>"
            f"<div style='font-size:11px;color:#64748b;font-weight:700;'>EMPLOYEE ACHIEVEMENT TIER</div>"
            f"<div style='font-size:18px;font-weight:800;color:#10b981;margin-top:4px;'>{rep_badge}</div>"
            f"<div style='font-size:10px;color:#475569;'>Calculated dynamically against regional standards</div>"
            f"</div>",
            unsafe_allow_html=True
        )
        st.markdown("<div style='margin-top: 16px;'></div>", unsafe_allow_html=True)

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

            # ── Wow Factor 3: Territory Performance ──
            st.markdown("<div style='margin-top: 16px;'></div>", unsafe_allow_html=True)
            with st.spinner("Analyzing regional sales distribution…"):
                territory_df = _fetch_rep_territory_stats(_db_engine, rep_uid)
            if not territory_df.empty:
                st.subheader("🗺️ Geographic Revenue Yield — State & City Drill-Down")
                fig_terr = px.bar(
                    territory_df, x="revenue", y="city_name",
                    orientation="h", color="state_name",
                    labels={"revenue": "Revenue (Rs)", "city_name": "City", "state_name": "State"},
                    color_discrete_sequence=px.colors.qualitative.Safe,
                    text="revenue",
                )
                fig_terr.update_traces(texttemplate="₹%{text:,.0f}", textposition="outside")
                fig_terr.update_layout(
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    height=max(240, len(territory_df) * 36),
                    xaxis=dict(title="Revenue (Rs)", tickformat=",.0f", showgrid=True,
                               gridcolor="rgba(255,255,255,0.07)"),
                    yaxis=dict(title="", showgrid=False, autorange="reversed"),
                    margin=dict(l=0, r=80, t=10, b=0),
                )
                st.plotly_chart(fig_terr, use_container_width=True)

        return

    # ═══════════════════════════════════════════════════════════════════════════
    # ALL REPS LEADERBOARD VIEW
    # ═══════════════════════════════════════════════════════════════════════════
    total_reps        = len(df)
    period_rev_total  = float(df["period_revenue"].sum()) if "period_revenue" in df.columns else 0
    total_tours       = df_all["total_tours"].sum() if "total_tours" in df_all.columns else 0
    total_expenses    = df_all["total_expenses"].sum() if "total_expenses" in df_all.columns else 0
    avg_roi           = df_all["revenue_roi"].replace([np.inf, -np.inf], np.nan).mean() if "revenue_roi" in df_all.columns else 0
    period_orders_tot = int(df["period_orders"].sum()) if "period_orders" in df.columns else 0
    period_parts_tot  = int(df["period_partners"].sum()) if "period_partners" in df.columns else 0

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Active Regional Reps",      f"{total_reps}")
    col2.metric(f"Revenue ({date_label})",   _fmt_inr(period_rev_total))
    col3.metric(f"Orders ({date_label})",    f"{period_orders_tot:,}")
    col4.metric(f"Partners ({date_label})",  f"{period_parts_tot:,}")
    col5.metric("Total Expenses (All-Time)", _fmt_inr(total_expenses))
    st.markdown("---")

    st.subheader(f"🏆 Sales Rep Leaderboard — {date_label}")
    disp_cols = ["sales_rep_name", "period_revenue", "period_orders", "period_partners"]
    disp_cols = [c for c in disp_cols if c in df.columns]
    display_df = df[disp_cols].copy()
    
    # Calculate performance achievement tiers
    display_df["Tier"] = df.apply(lambda r: _get_rep_badge(r, df_all), axis=1)
    
    # Order columns beautifully
    ordered_cols = ["sales_rep_name", "Tier"] + [c for c in disp_cols if c != "sales_rep_name"]
    display_df = display_df[ordered_cols]
    display_df = display_df.sort_values(f"Revenue ({date_label})" if f"Revenue ({date_label})" in display_df.columns else "sales_rep_name", ascending=False)
    
    display_df.rename(columns={
        "sales_rep_name":  "Sales Rep",
        "period_revenue":  f"Revenue ({date_label})",
        "period_orders":   f"Orders ({date_label})",
        "period_partners": f"Partners ({date_label})",
    }, inplace=True)

    st.dataframe(
        display_df,
        column_config={
            f"Revenue ({date_label})": st.column_config.NumberColumn(format="₹%d"),
            f"Orders ({date_label})": st.column_config.NumberColumn(format="%d"),
            f"Partners ({date_label})": st.column_config.NumberColumn(format="%d"),
        },
        hide_index=True, use_container_width=True, height=450
    )

    st.markdown("---")

    # ── ROI Scatter + Partner Coverage ───────────────────────────────────────
    colA, colB = st.columns(2)
    with colA:
        st.subheader("💸 Expense vs Revenue Yield")
        if not df_all.empty and "total_expenses" in df_all.columns and df_all["total_expenses"].sum() > 0:
            fig = px.scatter(
                df_all, x="total_expenses", y="total_revenue",
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
        if not df_all.empty and "unique_customers" in df_all.columns:
            coverage_df = df_all.sort_values("unique_customers", ascending=False)
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
        else:
            st.info("No partner coverage data available.")

    # ── Service & Issue Management ────────────────────────────────────────────
    st.markdown("---")
    st.subheader("⚠️ Partner Issue Management by Rep")
    st.caption("High orders with 0 issues may indicate gaps in after-sales follow-up.")

    if not df_all.empty and "issues_logged" in df_all.columns:
        issue_df = df_all.sort_values("issues_logged", ascending=False).head(10)
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
    else:
        st.info("No issues data available.")

    # ── Revenue Efficiency Table ──────────────────────────────────────────────
    st.markdown("---")
    st.subheader("📐 Revenue Efficiency Analysis")
    if not df_all.empty:
        eff_df = df_all[["sales_rep_name", "total_revenue", "total_orders", "total_expenses",
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
