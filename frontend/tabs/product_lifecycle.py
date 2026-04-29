import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import sys, os
from datetime import date, timedelta
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from styles import apply_global_styles, section_header, page_caption, page_header, skeleton_loader


# ── Duration preset chips ─────────────────────────────────────────────────────
_LC_PRESETS = [
    {"label": "15 Days",  "days": 15},
    {"label": "1 Month",  "days": 30},
    {"label": "2 Months", "days": 60},
    {"label": "3 Months", "days": 90},
    {"label": "6 Months", "days": 180},
    {"label": "1 Year",   "days": 365},
]


def _render_lifecycle_date_picker() -> tuple:
    """
    Calendar date-range picker for Product Lifecycle.
    Returns (start_date, end_date, date_label, span_days).
    """
    st.markdown("""
    <style>
    div[data-testid="column"] .stButton>button {
        border-radius: 20px !important; font-size: 12px !important;
        padding: 4px 14px !important; border: 1px solid #374151 !important;
        background: #1e2235 !important; color: #a78bfa !important;
        transition: all 0.18s ease !important;
    }
    div[data-testid="column"] .stButton>button:hover {
        background: #ec4899 !important; border-color: #ec4899 !important;
        color: #fff !important;
    }
    </style>
    """, unsafe_allow_html=True)

    today = date.today()
    if "lc_date_start" not in st.session_state:
        st.session_state["lc_date_start"] = today - timedelta(days=365)
    if "lc_date_end" not in st.session_state:
        st.session_state["lc_date_end"] = today

    # Header
    st.markdown("""
    <div style='background:linear-gradient(135deg,rgba(236,72,153,0.06),rgba(236,72,153,0.02));
         border:1px solid rgba(236,72,153,0.25);border-radius:14px;
         padding:14px 20px;margin-bottom:14px;'>
      <div style='font-size:11px;font-weight:700;text-transform:uppercase;
           letter-spacing:0.12em;color:#ec4899;margin-bottom:8px;'>
        📅 Date Range — Lifecycle Analysis Window
      </div>
      <div style='font-size:12px;color:#64748b;'>
        Select any date window — Growing / Declining stages recompute dynamically for that period
      </div>
    </div>
    """, unsafe_allow_html=True)

    # Duration chips
    st.markdown("<div style='font-size:11px;color:#64748b;margin-bottom:5px;font-weight:600;'>⚡ Quick Select</div>",
                unsafe_allow_html=True)
    preset_cols = st.columns(len(_LC_PRESETS))
    for i, p in enumerate(_LC_PRESETS):
        with preset_cols[i]:
            if st.button(p["label"], key=f"lc_preset_{i}"):
                st.session_state["lc_date_end"]   = today
                st.session_state["lc_date_start"] = today - timedelta(days=p["days"])

    # Month chips (last 6 months)
    st.markdown("<div style='font-size:11px;color:#64748b;margin-top:8px;margin-bottom:4px;'>📆 Specific Month</div>",
                unsafe_allow_html=True)
    month_chips = []
    _ref = today.replace(day=1)
    for i in range(6):
        m_start = _ref
        m_end   = (_ref.replace(month=_ref.month % 12 + 1, day=1) - timedelta(days=1)
                   if _ref.month < 12 else _ref.replace(month=12, day=31))
        month_chips.append({"label": _ref.strftime("%b %Y"),
                            "start": m_start, "end": min(m_end, today)})
        _ref = (_ref - timedelta(days=1)).replace(day=1)
    month_cols = st.columns(6)
    for i, mc in enumerate(month_chips):
        with month_cols[i]:
            if st.button(mc["label"], key=f"lc_month_{i}"):
                st.session_state["lc_date_start"] = mc["start"]
                st.session_state["lc_date_end"]   = mc["end"]

    # Manual pickers
    st.markdown("<div style='font-size:11px;color:#64748b;margin-top:10px;margin-bottom:4px;'>🗓️ Custom Range</div>",
                unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1.5, 1.5, 1])
    with c1:
        new_start = st.date_input("Start Date", value=st.session_state["lc_date_start"],
                                  max_value=today, key="lc_cal_start")
    with c2:
        new_end = st.date_input("End Date", value=st.session_state["lc_date_end"],
                                min_value=new_start, max_value=today, key="lc_cal_end")
    with c3:
        st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        if st.button("✅ Apply", key="lc_apply_range", use_container_width=True):
            st.session_state["lc_date_start"] = new_start
            st.session_state["lc_date_end"]   = new_end

    sel_start  = st.session_state["lc_date_start"]
    sel_end    = st.session_state["lc_date_end"]
    if sel_end < sel_start:
        sel_end = sel_start
    span_days  = max((sel_end - sel_start).days, 1)
    date_label = f"{sel_start.strftime('%d %b %Y')} → {sel_end.strftime('%d %b %Y')}  ({span_days}d)"

    # Active badge
    st.markdown(
        f"""
        <div style='background:rgba(15,26,43,0.9);border:1px solid #1e3a5f;border-radius:8px;
             padding:8px 16px;margin-top:8px;display:flex;align-items:center;gap:10px;'>
          <span style='font-size:15px;'>📅</span>
          <span style='color:#f9a8d4;font-size:13px;font-weight:600;'>Analysis Window</span>
          <span style='color:#475569;'>–</span>
          <span style='color:#64748b;font-size:12px;'>
            <b style='color:#7eb8f0;'>{sel_start.strftime('%d %b %Y')}</b>
            &nbsp;→&nbsp;
            <b style='color:#7eb8f0;'>{sel_end.strftime('%d %b %Y')}</b>
          </span>
          <span style='margin-left:auto;font-size:11px;color:#4b5563;'>{span_days} day window</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    return sel_start, sel_end, date_label, span_days


def render(ai):
    apply_global_styles()
    page_header(
        title="Product Lifecycle Intelligence",
        subtitle="Track product growth velocity, detect cannibalization, and predict end-of-life timelines.",
        icon="📈",
        accent_color="#ec4899",
    )
    skel = st.empty()
    with skel.container():
        skeleton_loader(n_metric_cards=4, n_rows=3, label="Analyzing product lifecycles...")
    ai.ensure_product_lifecycle()
    skel.empty()

    summary = ai.get_product_velocity_summary()
    if summary.get("status") != "ok":
        st.warning("No product lifecycle data available. Ensure transaction data is loaded.")
        return

    # ── Calendar date-range picker ────────────────────────────────────────────
    sel_start, sel_end, date_label, span_days = _render_lifecycle_date_picker()
    ts_start = pd.Timestamp(sel_start)
    ts_end   = pd.Timestamp(sel_end)

    # ── Category / Product filters ────────────────────────────────────────────
    st.markdown(
        """
        <div style="
            background:rgba(236,72,153,0.07);
            border:1px solid rgba(236,72,153,0.25);
            border-radius:10px;
            padding:14px 18px 8px 18px;
            margin-bottom:18px;
        ">
        <p style="color:#ec4899;font-weight:700;font-size:0.95rem;margin-bottom:10px;">
            🎛️ Global Filters — applied to Velocity Scorecard &amp; Trend Drilldown
        </p>
        """,
        unsafe_allow_html=True,
    )
    gf2, gf3 = st.columns([1, 2])
    with gf2:
        categories = ["All"] + (ai.get_product_categories() or [])
        selected_category = st.selectbox(
            "Product Category", categories, key="global_category",
            help="Filter by product category",
        )
    with gf3:
        product_options = ["All"] + (
            ai.get_products_for_category(selected_category if selected_category != "All" else None) or []
        )
        selected_product = st.selectbox(
            "Specific Product", product_options, key="global_product",
            help="Drill into a single SKU from master_products",
        )
    st.markdown("</div>", unsafe_allow_html=True)

    api_cat  = None if selected_category == "All" else selected_category
    api_prod = None if selected_product == "All" else selected_product
    use_individual = (api_prod is not None) or (api_cat is not None)

    # ── Slice in-memory monthly data to the selected date window ──────────────
    def _slice_monthly(df):
        """Return only rows within [sel_start, sel_end]."""
        if df is None or df.empty or "sale_month" not in df.columns:
            return df
        months = pd.to_datetime(df["sale_month"])
        return df[(months >= ts_start) & (months <= ts_end)].copy()

    df_pm_sliced  = _slice_monthly(getattr(ai, "df_product_monthly", None))
    df_ind_sliced = _slice_monthly(getattr(ai, "df_individual_product_monthly", None))

    # api_period no longer used — date range is now exact
    api_period = None

    # ------------------------------------------------------------------
    # Summary metrics
    # ------------------------------------------------------------------
    section_header("Lifecycle Overview")
    m1, m2, m3, m4, m5, m6 = st.columns(6)
    with m1:
        st.metric("Total Products", summary["total_products"])
    with m2:
        st.metric("Growing 🚀", summary["growing"])
    with m3:
        st.metric("Mature 📊", summary["mature"])
    with m4:
        st.metric("Plateauing ⏸", summary["plateauing"])
    with m5:
        st.metric("Declining 📉", summary["declining"])
    with m6:
        st.metric("End-of-Life ⚠", summary["end_of_life"])

    # ------------------------------------------------------------------
    # Lifecycle stage distribution
    # ------------------------------------------------------------------
    st.markdown("---")
    velocity_df = ai.get_velocity_data()   # unfiltered for overview charts

    color_map = {
        "Growing": "#27ae60",
        "Mature": "#2980b9",
        "Plateauing": "#f39c12",
        "Declining": "#e74c3c",
        "End-of-Life": "#7f8c8d",
    }

    if not velocity_df.empty:
        ch1, ch2 = st.columns([1, 2])
        with ch1:
            stage_counts = velocity_df["lifecycle_stage"].value_counts().reset_index()
            stage_counts.columns = ["Stage", "Count"]
            fig_pie = px.pie(
                stage_counts, names="Stage", values="Count",
                title="Lifecycle Stage Distribution",
                color="Stage", color_discrete_map=color_map,
                hole=0.35,
            )
            fig_pie.update_layout(height=350)
            st.plotly_chart(fig_pie, use_container_width=True)

        with ch2:
            st.markdown("<p style='text-align:center; font-weight:600; margin-bottom:0;'>Revenue vs Growth Quadrant</p>", unsafe_allow_html=True)
            quad_df = velocity_df.copy()
            quad_df["avg_monthly_revenue"] = quad_df["avg_monthly_revenue"].fillna(0)
            quad_df["growth_3m_pct"] = quad_df["growth_3m_pct"].fillna(0)
            med_rev    = quad_df["avg_monthly_revenue"].median()
            med_growth = quad_df["growth_3m_pct"].median()
            fig_quad = px.scatter(
                quad_df,
                x="avg_monthly_revenue",
                y="growth_3m_pct",
                color="lifecycle_stage",
                color_discrete_map=color_map,
                hover_name="product_name",
                hover_data=["velocity_score"],
                labels={
                    "avg_monthly_revenue": "Avg Monthly Revenue (Rs)",
                    "growth_3m_pct": "3M Growth (%)",
                },
            )
            fig_quad.add_hline(y=med_growth, line_dash="dash", line_color="gray",
                               annotation_text="Median Growth", annotation_position="top right")
            fig_quad.add_vline(x=med_rev, line_dash="dash", line_color="gray",
                               annotation_text="Median Revenue", annotation_position="top left")
            fig_quad.update_layout(height=350, margin=dict(l=0, r=0, t=30, b=0))
            st.plotly_chart(fig_quad, use_container_width=True)

    # ------------------------------------------------------------------
    # Growth Velocity Table  (filtered by period + category + product)
    # ------------------------------------------------------------------
    section_header("Growth Velocity Scorecard")

    scf1, scf2 = st.columns([1, 3])
    with scf1:
        base_stages = (
            sorted(velocity_df["lifecycle_stage"].unique().tolist())
            if not velocity_df.empty
            else []
        )
        stage_filter = st.selectbox("Filter by Stage", ["All"] + base_stages, key="vel_stage")
    with scf2:
        prod_search = st.text_input("Search Product / Group Name", "", key="vel_search")

    # Recompute velocity on the date-sliced monthly data
    if use_individual and df_ind_sliced is not None and not df_ind_sliced.empty:
        ind_src = df_ind_sliced.copy()
        if api_cat:
            ind_src = ind_src[ind_src["product_category"] == api_cat]
        if api_prod:
            ind_src = ind_src[ind_src["product_name"] == api_prod]
        filtered = ai._compute_velocity_for_df(ind_src) if not ind_src.empty else pd.DataFrame()
    elif df_pm_sliced is not None and not df_pm_sliced.empty:
        filtered = ai._compute_velocity_for_df(df_pm_sliced)
    else:
        filtered = pd.DataFrame()

    if stage_filter != "All" and not filtered.empty:
        filtered = filtered[filtered["lifecycle_stage"] == stage_filter]
    if prod_search and not filtered.empty:
        filtered = filtered[filtered["product_name"].str.contains(prod_search, case=False, na=False)]

    st.caption(f"ℹ️ Showing data for: **{date_label}**"
               + (f" | Category: **{api_cat}**" if api_cat else "")
               + (f" | Product: **{api_prod}**" if api_prod else ""))

    if filtered.empty:
        st.info("No products match the selected filters.")
    else:
        # Attach sparklines from the date-sliced source
        df_monthly_src_spark = df_ind_sliced if use_individual else df_pm_sliced
        if df_monthly_src_spark is not None and not df_monthly_src_spark.empty:
            sparklines = (
                df_monthly_src_spark
                .sort_values("sale_month")
                .groupby("product_name")["monthly_revenue"]
                .apply(list)
                .reset_index(name="revenue_trend")
            )
            filtered = filtered.merge(sparklines, on="product_name", how="left")

        display_cols = [c for c in [
            "product_name", "product_category", "product_group",
            "revenue_trend", "velocity_score", "growth_3m_pct",
            "slope_pct", "avg_monthly_revenue", "current_revenue", "peak_distance_pct",
            "months_since_peak", "buyer_trend", "revenue_cv",
        ] if c in filtered.columns]

        stages_order = ["Growing", "Mature", "Plateauing", "Declining", "End-of-Life"]
        present_stages = [s for s in stages_order if s in filtered["lifecycle_stage"].values]

        for stage in present_stages:
            stage_df = filtered[filtered["lifecycle_stage"] == stage]
            color = color_map.get(stage, "#888")
            st.markdown(
                f"<h4 style='color:{color}; margin-top:20px; margin-bottom:8px; border-bottom:1px solid #333; padding-bottom:4px;'>"
                f"{stage} <span style='color:#666; font-size:14px; font-weight:normal;'>({len(stage_df)} products)</span></h4>",
                unsafe_allow_html=True,
            )
            st.dataframe(
                stage_df[display_cols],
                column_config={
                    "product_name":        "Product / Group",
                    "product_category":    "Category",
                    "product_group":       "Group",
                    "revenue_trend":       st.column_config.LineChartColumn("Trend", y_min=0),
                    "velocity_score":      st.column_config.NumberColumn("Velocity", format="%.3f"),
                    "growth_3m_pct":       st.column_config.NumberColumn("3M Growth %", format="%+.1f%%"),
                    "slope_pct":           st.column_config.NumberColumn("Trend Slope %", format="%+.1f%%"),
                    "avg_monthly_revenue": st.column_config.NumberColumn("Avg Monthly Rev", format="Rs %.0f"),
                    "current_revenue":     st.column_config.NumberColumn("Current Rev", format="Rs %.0f"),
                    "peak_distance_pct":   st.column_config.NumberColumn("From Peak %", format="%.1f%%"),
                    "months_since_peak":   "Months Since Peak",
                    "buyer_trend":         st.column_config.NumberColumn("Buyer Trend", format="%+.2f"),
                    "revenue_cv":          st.column_config.NumberColumn("Volatility (CV)", format="%.2f"),
                },
                use_container_width=True,
                hide_index=True,
            )

    # ------------------------------------------------------------------
    # Individual Product Trend Drilldown
    # ------------------------------------------------------------------
    section_header("Product Trend Drilldown")

    # Build the product selection pool from the velocity data being shown
    drilldown_pool_df = velocity_df if not use_individual else filtered
    if not drilldown_pool_df.empty:
        product_options_drill = sorted(drilldown_pool_df["product_name"].unique().tolist())
        # Pre-select the global product filter if set
        default_idx = 0
        if api_prod and api_prod in product_options_drill:
            default_idx = product_options_drill.index(api_prod)
        selected_product_drill = st.selectbox(
            "Select Product / Group",
            product_options_drill,
            index=default_idx,
            key="trend_product",
        )

        # Use the date-sliced monthly data for drilldown chart
        src_monthly = df_ind_sliced if use_individual else df_pm_sliced
        if src_monthly is not None and not src_monthly.empty:
            trend_data = src_monthly[src_monthly["product_name"] == selected_product_drill].sort_values("sale_month").copy()
        else:
            trend_data = pd.DataFrame()

        if not trend_data.empty:
            src_df = drilldown_pool_df
            prod_info = src_df[src_df["product_name"] == selected_product_drill]
            if not prod_info.empty:
                p = prod_info.iloc[0]
                i1, i2, i3, i4 = st.columns(4)
                with i1:
                    st.metric("Lifecycle Stage", p["lifecycle_stage"])
                with i2:
                    st.metric("Velocity Score", f"{p['velocity_score']:.3f}")
                with i3:
                    st.metric("3M Growth", f"{p['growth_3m_pct']:+.1f}%")
                with i4:
                    st.metric("From Peak", f"{p['peak_distance_pct']:.1f}%")

            tr1, tr2 = st.columns(2)
            with tr1:
                fig_rev = px.line(
                    trend_data, x="sale_month", y="monthly_revenue",
                    title=f"Revenue — {selected_product_drill}  ({date_label})",
                    labels={"monthly_revenue": "Revenue (Rs)", "sale_month": "Month"},
                    markers=True,
                    color_discrete_sequence=["#ec4899"],
                )
                fig_rev.update_layout(height=350)
                st.plotly_chart(fig_rev, use_container_width=True)

            with tr2:
                fig_buyers = px.bar(
                    trend_data, x="sale_month", y="monthly_buyer_count",
                    title=f"Monthly Buyer Count — {selected_product_drill}",
                    labels={"monthly_buyer_count": "Buyers", "sale_month": "Month"},
                    color_discrete_sequence=["#3498db"],
                )
                fig_buyers.update_layout(height=350)
                st.plotly_chart(fig_buyers, use_container_width=True)
        else:
            st.info("No trend data available for this product in the selected period.")

    # ------------------------------------------------------------------
    # Cannibalization Detection
    # ------------------------------------------------------------------
    section_header("Cannibalization Detection")
    st.caption("Products where a growing product may be replacing a declining one (based on MBA association rules).")

    cannibal_df = ai.get_cannibalization_data()
    if cannibal_df.empty:
        st.success("No cannibalization patterns detected.")
    else:
        st.warning(f"Detected **{len(cannibal_df)}** potential cannibalization pairs.")
        display_cols = [c for c in [
            "cannibal_product", "cannibal_growth_3m_pct", "victim_product",
            "victim_growth_3m_pct", "association_confidence", "association_lift",
            "cannibalization_score", "estimated_revenue_shift",
        ] if c in cannibal_df.columns]
        st.dataframe(
            cannibal_df[display_cols],
            column_config={
                "cannibal_product":       "Replacing Product ↑",
                "cannibal_growth_3m_pct": st.column_config.NumberColumn("Its Growth %", format="%+.1f%%"),
                "victim_product":         "Being Replaced ↓",
                "victim_growth_3m_pct":   st.column_config.NumberColumn("Its Decline %", format="%+.1f%%"),
                "association_confidence": st.column_config.NumberColumn("Confidence", format="%.2f"),
                "association_lift":       st.column_config.NumberColumn("Lift", format="%.2f"),
                "cannibalization_score":  st.column_config.NumberColumn("Score", format="%.3f"),
                "estimated_revenue_shift":st.column_config.NumberColumn("Est. Rev Shift/3M", format="Rs %.0f"),
            },
            use_container_width=True,
            hide_index=True,
        )

        if len(cannibal_df) >= 2:
            all_prods = list(set(cannibal_df["cannibal_product"].tolist() + cannibal_df["victim_product"].tolist()))
            fig_sankey = go.Figure(go.Sankey(
                arrangement="snap",
                node=dict(
                    label=all_prods,
                    color=["#27ae60" if p in cannibal_df["cannibal_product"].values else "#e74c3c" for p in all_prods],
                ),
                link=dict(
                    source=[all_prods.index(r["cannibal_product"]) for _, r in cannibal_df.iterrows()],
                    target=[all_prods.index(r["victim_product"]) for _, r in cannibal_df.iterrows()],
                    value=cannibal_df["estimated_revenue_shift"].tolist(),
                ),
            ))
            fig_sankey.update_layout(title="Cannibalization Flow (Green = Growing, Red = Declining)", height=400)
            st.plotly_chart(fig_sankey, use_container_width=True)

    # ------------------------------------------------------------------
    # End-of-Life Predictions
    # ------------------------------------------------------------------
    section_header("End-of-Life Predictions")
    st.caption("Products at risk of becoming obsolete, with estimated timelines and recommended actions.")

    eol_filter = st.selectbox("Urgency Filter", ["All", "Critical", "High", "Medium", "Low"], key="eol_urgency")
    eol_df = ai.get_eol_predictions(urgency_filter=eol_filter if eol_filter != "All" else None)

    if eol_df.empty:
        st.success("No products flagged for end-of-life risk under the selected filter.")
    else:
        urgency_colors = {"Critical": "🔴", "High": "🟠", "Medium": "🟡", "Low": "🟢"}
        eol_display = eol_df.copy()
        eol_display["urgency_icon"] = eol_display["urgency"].map(urgency_colors).fillna("") + " " + eol_display["urgency"]

        display_cols = [c for c in [
            "product_name", "urgency_icon", "lifecycle_stage", "eol_risk_score",
            "est_months_to_zero", "current_revenue", "growth_3m_pct",
            "peak_distance_pct", "buyer_trend", "total_stock", "max_age_days",
            "suggested_action",
        ] if c in eol_display.columns]
        st.dataframe(
            eol_display[display_cols],
            column_config={
                "product_name":       "Product",
                "urgency_icon":       "Urgency",
                "lifecycle_stage":    "Stage",
                "eol_risk_score":     st.column_config.NumberColumn("Risk Score", format="%.3f"),
                "est_months_to_zero": st.column_config.NumberColumn("Est. Months to Zero", format="%.1f"),
                "current_revenue":    st.column_config.NumberColumn("Current Rev", format="Rs %.0f"),
                "growth_3m_pct":      st.column_config.NumberColumn("3M Growth %", format="%+.1f%%"),
                "peak_distance_pct":  st.column_config.NumberColumn("From Peak %", format="%.1f%%"),
                "buyer_trend":        st.column_config.NumberColumn("Buyer Trend", format="%+.2f"),
                "total_stock":        st.column_config.NumberColumn("Stock Qty", format="%.0f"),
                "max_age_days":       st.column_config.NumberColumn("Max Age (Days)", format="%.0f"),
                "suggested_action":   "Suggested Action",
            },
            use_container_width=True,
            hide_index=True,
        )

        if len(eol_df) > 3:
            fig_eol = px.scatter(
                eol_df, x="est_months_to_zero", y="eol_risk_score",
                size="current_revenue", color="urgency",
                color_discrete_map={
                    "Critical": "#e74c3c", "High": "#e67e22",
                    "Medium": "#f1c40f", "Low": "#27ae60",
                },
                hover_name="product_name",
                title="EOL Risk vs. Estimated Time to Zero Revenue",
                labels={
                    "est_months_to_zero": "Estimated Months to Zero Revenue",
                    "eol_risk_score": "EOL Risk Score",
                },
            )
            fig_eol.update_layout(height=400)
            st.plotly_chart(fig_eol, use_container_width=True)

        # ──────────────────────────────────────────────────────
        # Clearance Action Generator
        # ──────────────────────────────────────────────────────
        st.markdown("---")
        st.subheader("🏷️ Clearance Action Generator")
        st.caption("Instantly generate a discount bundle or liquidation deal for flagged products.")

        critical_products = eol_df[eol_df["urgency"].isin(["Critical", "High"])]["product_name"].tolist() if "urgency" in eol_df.columns else []
        if critical_products:
            chosen_eol = st.selectbox("Select Product to Act On", critical_products, key="eol_action_product")
            eol_row = eol_df[eol_df["product_name"] == chosen_eol].iloc[0]
            curr_rev = float(eol_row.get("current_revenue", 0) or 0)
            months_left = float(eol_row.get("est_months_to_zero", 0) or 0)

            act1, act2, act3 = st.columns(3)
            with act1:
                discount_pct = st.slider("Discount %", 5, 50, 20, 5, key="eol_discount")
                clearance_price = curr_rev * (1 - discount_pct / 100)
                st.metric("Estimated Clearance Revenue/Mo", f"₹{clearance_price:,.0f}")
            with act2:
                bundle_with = st.text_input("Bundle with Product (optional)", "", key="eol_bundle")
            with act3:
                st.markdown("<br>", unsafe_allow_html=True)
                if st.button("Generate Offer Script", key="eol_gen_script"):
                    bundle_line = f" We're bundling it with **{bundle_with}** for added value." if bundle_with else ""
                    script = (
                        f"**Flash Deal — Limited Stock Alert!**\n\n"
                        f"Dear Partner, we have a special **{discount_pct}% discount** on **{chosen_eol}** "
                        f"(only ~{months_left:.0f} months of active inventory left)!{bundle_line}\n\n"
                        f"Act fast — this offer expires when stock runs out. Contact your sales rep today!"
                    )
                    st.info(script)
        else:
            st.success("No Critical/High urgency products requiring immediate clearance action.")


# ── Helper: sparkline period cutoff ──────────────────────────────────────────
def _sparkline_cutoff(df: pd.DataFrame, period: str):
    if "sale_month" not in df.columns:
        return None
    max_month = pd.to_datetime(df["sale_month"]).max()
    if pd.isna(max_month):
        return None
    if period == "Monthly":
        return max_month - pd.DateOffset(months=1)
    if period == "Quarterly":
        return max_month - pd.DateOffset(months=3)
    if period == "Yearly":
        return max_month - pd.DateOffset(months=12)
    return None
