import streamlit as st
import pandas as pd
import plotly.express as px
import sys, os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from styles import apply_global_styles, section_header, banner, page_caption, page_header, skeleton_loader


def render(ai):
    apply_global_styles()
    page_header(
        title="Inventory Liquidation",
        subtitle="Identify dead stock items and proactively find the best partners to clear them.",
        icon="📦",
        accent_color="#f59e0b",
    )
    skel = st.empty()
    with skel.container():
        skeleton_loader(n_metric_cards=3, n_rows=2, label="Scanning inventory ageing...")
    ai.ensure_core_loaded()
    ai.ensure_clustering()
    skel.empty()

    df_dead = ai.get_dead_stock()
    stats_df = getattr(ai, "df_stock_stats", None)

    if stats_df is None or stats_df.empty:
        banner("✅ No inventory data available to analyze.", "green")
        return

    # ── Ageing Distribution ──────────────────────────────────────────────────
    st.subheader("📊 Portfolio Ageing Distribution")
    age_cols = ["age_0_30", "age_31_60", "age_61_90", "age_90_plus"]
    if all(c in stats_df.columns for c in age_cols):
        age_sums = stats_df[age_cols].sum()
        age_df = pd.DataFrame({
            "Bucket": ["0-30 Days", "31-60 Days", "61-90 Days", "90+ Days"],
            "Stock Value (Rs)": [
                age_sums["age_0_30"],
                age_sums["age_31_60"],
                age_sums["age_61_90"],
                age_sums["age_90_plus"],
            ],
        })
        fig = px.bar(
            age_df, x="Bucket", y="Stock Value (Rs)",
            color="Bucket",
            color_discrete_map={
                "0-30 Days": "#10b981",
                "31-60 Days": "#f59e0b",
                "61-90 Days": "#f97316",
                "90+ Days": "#ef4444",
            },
            title="Total Capital Locked by Age Bucket",
        )
        fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            showlegend=False,
            height=300,
        )
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("---")

    valid_items = stats_df["product_name"].unique()
    if len(valid_items) == 0:
        banner("✅ No critical dead stock found — nothing older than 60 days with more than 10 units.", "green")
        return

    items = sorted(valid_items)
    selected_item = st.selectbox("📦 Select Dead Stock Item to clear", items)

    # ── Stock KPIs ───────────────────────────────────────────────────────────
    stock_details = ai.get_stock_details(selected_item)
    if stock_details is not None:
        c1, c2, c3, c4 = st.columns(4)
        total_qty     = stock_details.get("total_stock_qty", 0)
        cost_price    = stock_details.get("cost_price", 1000)
        capital_locked = total_qty * cost_price
        c1.metric("Units to Clear", f"{total_qty} Units")
        c2.metric("Capital Locked", f"Rs {capital_locked:,.0f}")
        c3.metric("Max Age in WH", f"{stock_details.get('max_age_days', 0)} Days")
        c4.metric(
            "Priority",
            stock_details.get("priority", "High"),
            delta=stock_details.get("priority_delta", "Plan Sales"),
            delta_color="inverse",
        )
    elif selected_item:
        st.warning("Stock details not found in ageing view. Showing potential buyers only.")

    st.markdown("---")

    if not selected_item:
        return

    # ── Build leads table ────────────────────────────────────────────────────
    # df_dead already has real mobile_no from the DB view
    leads = df_dead[df_dead["dead_stock_item"] == selected_item].copy()

    # Ensure required columns with defaults
    for col, default in [
        ("Audience Type", "Past Buyer"),
        ("mobile_no", "—"),
        ("buyer_past_purchase_qty", 0),
        ("last_purchase_date", "Unknown"),
    ]:
        if col not in leads.columns:
            leads[col] = default
        elif col == "Audience Type":
            # Always stamp existing rows as Past Buyer
            leads[col] = "Past Buyer"

    # ── Pull contact numbers for lookalike partners from df_dead itself ──────
    # Build a company → mobile lookup from ALL leads (past buyers across all items)
    contact_lookup: dict = {}
    if not df_dead.empty and "mobile_no" in df_dead.columns and "potential_buyer" in df_dead.columns:
        _cl = df_dead[["potential_buyer", "mobile_no"]].dropna(subset=["potential_buyer"])
        _cl = _cl[_cl["mobile_no"].notna() & (_cl["mobile_no"] != "")]
        contact_lookup = dict(zip(_cl["potential_buyer"], _cl["mobile_no"]))

    # ── Find lookalike audiences from cluster data ───────────────────────────
    pf = getattr(ai, "df_partner_features", None)
    if not leads.empty and pf is not None:
        pf_reset = pf.reset_index()
        if "company_name" not in pf_reset.columns and "index" in pf_reset.columns:
            pf_reset = pf_reset.rename(columns={"index": "company_name"})

        if "cluster_label" in pf_reset.columns:
            # Merge cluster labels onto past buyers
            leads = leads.merge(
                pf_reset[["company_name", "cluster_label"]],
                left_on="potential_buyer",
                right_on="company_name",
                how="left",
            )
            # Re-stamp Audience Type (merge may create duplicate / NaN)
            leads["Audience Type"] = "Past Buyer"

            # Identify which clusters the buyers belong to
            buyer_clusters = leads["cluster_label"].dropna().unique()

            if len(buyer_clusters) > 0:
                # Find partners from same clusters that have NOT bought this item yet
                already_buying = set(leads["potential_buyer"].dropna().str.lower())
                lookalike_pool = pf_reset[
                    pf_reset["cluster_label"].isin(buyer_clusters)
                    & ~pf_reset["company_name"].str.lower().isin(already_buying)
                ].copy()

                if not lookalike_pool.empty:
                    # Sort by revenue if available, take top 10
                    if "recent_90_revenue" in lookalike_pool.columns:
                        lookalike_pool = lookalike_pool.sort_values(
                            "recent_90_revenue", ascending=False
                        )
                    lookalike_pool = lookalike_pool.head(10)

                    # Build per-row audience type using each partner's own cluster label
                    lookalike_rows = []
                    for _, row in lookalike_pool.iterrows():
                        company      = row["company_name"]
                        cluster_lbl  = str(row.get("cluster_label", "Unknown"))
                        # Shorten cluster label to keep it readable (max 25 chars)
                        if len(cluster_lbl) > 25:
                            cluster_lbl = cluster_lbl[:22] + "..."
                        # Try to find real contact number from the global contact lookup
                        mobile = contact_lookup.get(company, "—")
                        lookalike_rows.append({
                            "potential_buyer":       company,
                            "mobile_no":             mobile,
                            "buyer_past_purchase_qty": 0,
                            "last_purchase_date":    "Never",
                            "Audience Type":         f"Lookalike ({cluster_lbl})",
                            "cluster_label":         row.get("cluster_label", "Unknown"),
                        })

                    if lookalike_rows:
                        lookalike_df = pd.DataFrame(lookalike_rows)
                        leads = pd.concat([leads, lookalike_df], ignore_index=True)

    # Final safety-net — "Audience Type" must always exist
    if "Audience Type" not in leads.columns:
        leads["Audience Type"] = "Past Buyer"

    # Clean up mobile_no display: replace empty/null with dash
    if "mobile_no" in leads.columns:
        leads["mobile_no"] = (
            leads["mobile_no"]
            .fillna("—")
            .astype(str)
            .str.strip()
            .replace({"": "—", "nan": "—", "None": "—"})
        )

    leads = leads.sort_values("buyer_past_purchase_qty", ascending=False)

    # ── Header + Export ──────────────────────────────────────────────────────
    col_hdr, col_dl = st.columns([3, 1])
    with col_hdr:
        section_header(f"Target Buyers — {selected_item} ({len(leads)} leads)")
    with col_dl:
        _export_cols = [c for c in
            ["potential_buyer", "mobile_no", "Audience Type",
             "buyer_past_purchase_qty", "last_purchase_date"]
            if c in leads.columns]
        csv = leads[_export_cols].to_csv(index=False)
        st.download_button(
            "⬇️ Export Campaign List",
            csv,
            f"leads_{selected_item.replace(' ', '_')}.csv",
            "text/csv",
            use_container_width=True,
        )

    # ── Display table ────────────────────────────────────────────────────────
    _display_cols = [c for c in
        ["potential_buyer", "mobile_no", "Audience Type",
         "buyer_past_purchase_qty", "last_purchase_date"]
        if c in leads.columns]

    st.dataframe(
        leads[_display_cols],
        column_config={
            "potential_buyer": "Partner Name",
            "mobile_no": "Contact Number",
            "Audience Type": "Audience Strategy",
            "buyer_past_purchase_qty": st.column_config.NumberColumn(
                "Past Qty Bought", format="%d"
            ),
            "last_purchase_date": "Last Purchase",
        },
        use_container_width=True,
        hide_index=True,
    )

    # ── Summary callout ───────────────────────────────────────────────────────
    n_past   = int((leads["Audience Type"] == "Past Buyer").sum())
    n_lookal = len(leads) - n_past
    if n_lookal > 0:
        st.info(
            f"📌 **{n_past} proven buyers** identified who previously purchased this item.  \n"
            f"🎯 **{n_lookal} lookalike partners** from the same cluster segments have been added — "
            "they buy similar products but haven't purchased this item yet.",
            icon=None,
        )
