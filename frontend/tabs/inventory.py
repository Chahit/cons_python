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

    # ── Ageing Distribution (fault-tolerant: uses named cols or derives from max_age_days) ──
    st.subheader("📊 Portfolio Ageing Distribution")
    color_map_age = {
        "0-30 Days": "#10b981", "31-60 Days": "#f59e0b",
        "61-90 Days": "#f97316", "90+ Days": "#ef4444",
    }
    age_col_map = {
        "age_0_30":   "0-30 Days",
        "age_31_60":  "31-60 Days",
        "age_61_90":  "61-90 Days",
        "age_90_plus":"90+ Days",
    }
    available_age_cols = {k: v for k, v in age_col_map.items() if k in stats_df.columns}
    if available_age_cols:
        age_sums = stats_df[list(available_age_cols.keys())].sum()
        age_df = pd.DataFrame({
            "Bucket": list(available_age_cols.values()),
            "Units": [age_sums[c] for c in available_age_cols.keys()]
        })
    elif "max_age_days" in stats_df.columns:
        # Derive buckets from max_age_days — counts SKUs falling into each age band
        _d = stats_df["max_age_days"].fillna(0)
        qty_col = next((c for c in ["total_stock_qty", "qty", "stock_qty"] if c in stats_df.columns), None)
        def _bucket_sum(mask):
            if qty_col:
                return stats_df.loc[mask, qty_col].sum()
            return int(mask.sum())
        age_df = pd.DataFrame({
            "Bucket": ["0-30 Days", "31-60 Days", "61-90 Days", "90+ Days"],
            "Units": [
                _bucket_sum(_d <= 30),
                _bucket_sum((_d > 30) & (_d <= 60)),
                _bucket_sum((_d > 60) & (_d <= 90)),
                _bucket_sum(_d > 90),
            ]
        })
    else:
        age_df = pd.DataFrame()

    if not age_df.empty:
        fig = px.bar(
            age_df, x="Bucket", y="Units",
            color="Bucket",
            color_discrete_map=color_map_age,
            title="Stock Units by Age Bucket (derived from max age per SKU)"
        )
        fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", showlegend=False, height=300)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Ageing data not available in the current stock view.")

    # ── State-wise Dead Stock Heatmap ──────────────────────────────────
    if not df_dead.empty:
        st.subheader("🗺️ State-wise Dead Stock Exposure")
        state_col = next((c for c in ["state", "partner_state", "buyer_state"] if c in df_dead.columns), None)
        cat_col = next((c for c in ["category", "product_category", "dead_stock_item"] if c in df_dead.columns), None)
        qty_col = next((c for c in ["buyer_past_purchase_qty", "total_qty", "qty"] if c in df_dead.columns), None)

        if state_col and qty_col:
            grp_cols = [state_col] + ([cat_col] if cat_col else [])
            state_agg = df_dead.groupby(grp_cols)[qty_col].sum().reset_index()
            state_agg.columns = grp_cols + ["Total Qty at Risk"]
            fig_state = px.bar(
                state_agg, x=state_col, y="Total Qty at Risk",
                color=cat_col if cat_col else state_col,
                title="Dead Stock Quantity at Risk by State & Category",
                labels={state_col: "State", qty_col: "Qty at Risk"},
                barmode="stack",
            )
            fig_state.update_layout(
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                height=320, margin=dict(l=0, r=0, t=40, b=0)
            )
            st.plotly_chart(fig_state, use_container_width=True)

    st.markdown("---")

    valid_items = stats_df["product_name"].unique()
    if len(valid_items) == 0:
        banner("✅ No critical dead stock found — nothing older than 60 days with more than 10 units.", "green")
        return
    else:
        items = sorted(valid_items)

    selected_item = st.selectbox("📦 Select Dead Stock Item to clear", items)

    stock_details = ai.get_stock_details(selected_item)

    if stock_details is not None:
        c1, c2, c3, c4 = st.columns(4)
        total_qty = stock_details.get('total_stock_qty', 0)

        # ── Pull cost_price from master_products if available ──────────
        cost_price = stock_details.get('cost_price', None)
        cost_label = ""
        if cost_price is None or cost_price == 0:
            # Try to get from master_products via engine
            mp = getattr(ai, "df_master_products", None)
            if mp is not None and not mp.empty:
                name_col = next((c for c in ["product_name", "name", "item_name"] if c in mp.columns), None)
                cost_col = next((c for c in ["cost_price", "unit_cost", "purchase_price"] if c in mp.columns), None)
                if name_col and cost_col:
                    match = mp[mp[name_col].str.lower() == selected_item.lower()]
                    if not match.empty:
                        cost_price = float(match.iloc[0][cost_col])
            if cost_price is None or cost_price == 0:
                cost_price = 1000
                cost_label = " (est.)"

        capital_locked = total_qty * cost_price

        c1.metric("Units to Clear", f"{total_qty} Units")
        c2.metric(f"Capital Locked{cost_label}", f"Rs {capital_locked:,.0f}")
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

    if selected_item:
        # Leads logic relies on the df_dead structure which maps item -> potential buyer
        leads = df_dead[df_dead["dead_stock_item"] == selected_item].copy()
        
        # Merge Clustering state to find lookalike audiences
        if not leads.empty and getattr(ai, "df_partner_features", None) is not None:
            pf = ai.df_partner_features.reset_index()
            # If company_name isn't there, it might be the index
            if "company_name" not in pf.columns and "index" in pf.columns:
                pf = pf.rename(columns={"index": "company_name"})
            
            leads = leads.merge(
                pf[["company_name", "cluster_label"]] if "cluster_label" in pf.columns else pf[["company_name"]],
                left_on="potential_buyer", right_on="company_name", how="left"
            )
            leads["Audience Type"] = "Past Buyer"
            
            # Find lookalikes (same cluster, but haven't bought this yet)
            if "cluster_label" in leads.columns and "cluster_label" in pf.columns:
                buyer_clusters = leads["cluster_label"].dropna().unique()
                if len(buyer_clusters) > 0:
                    lookalikes = pf[pf["cluster_label"].isin(buyer_clusters) & ~pf["company_name"].isin(leads["potential_buyer"])].copy()
                    if not lookalikes.empty:
                        if "recent_90_revenue" in lookalikes.columns:
                            lookalikes = lookalikes.sort_values("recent_90_revenue", ascending=False).head(10)
                        else:
                            lookalikes = lookalikes.head(10)
                            
                        lookalike_df = pd.DataFrame({
                            "potential_buyer": lookalikes["company_name"],
                            "mobile_no": "Lookalike",
                            "buyer_past_purchase_qty": 0,
                            "last_purchase_date": "Never",
                            "Audience Type": f"Lookalike (Cluster: {lookalikes.iloc[0]['cluster_label']})"
                        })
                        leads = pd.concat([leads, lookalike_df], ignore_index=True)

        leads = leads.sort_values("buyer_past_purchase_qty", ascending=False)
        
        col_hdr, col_dl = st.columns([3, 1])
        with col_hdr:
            section_header(f"Target Buyers — {selected_item} ({len(leads)} leads)")
        with col_dl:
            csv_cols = [c for c in ["potential_buyer", "mobile_no", "buyer_past_purchase_qty", "Audience Type", "last_purchase_date"] if c in leads.columns]
            csv = leads[csv_cols].to_csv(index=False)
            st.download_button("⬇️ Export Campaign List", csv, f"leads_{selected_item.replace(' ', '_')}.csv", "text/csv", use_container_width=True)

        disp_cols = [c for c in ["potential_buyer", "mobile_no", "Audience Type", "buyer_past_purchase_qty", "last_purchase_date"] if c in leads.columns]
        inv_disp = leads[disp_cols].copy()
        if "buyer_past_purchase_qty" in inv_disp.columns:
            inv_disp["buyer_past_purchase_qty"] = inv_disp["buyer_past_purchase_qty"].apply(
                lambda v: str(int(float(v))) if v == v else ""
            )
        for _oc in inv_disp.select_dtypes(include=["object"]).columns:
            inv_disp[_oc] = inv_disp[_oc].fillna("").astype(str)
        inv_disp = inv_disp.rename(columns={
            "potential_buyer":"Partner Name", "mobile_no":"Contact Number",
            "Audience Type":"Audience Strategy", "buyer_past_purchase_qty":"Past Qty Bought",
            "last_purchase_date":"Last Purchase",
        })
        st.dataframe(inv_disp, use_container_width=True, hide_index=True)

