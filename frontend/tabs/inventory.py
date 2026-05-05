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
            "Bucket":          ["0-30 Days", "31-60 Days", "61-90 Days", "90+ Days"],
            "Stock Value (Rs)": [
                age_sums["age_0_30"],
                age_sums["age_31_60"],
                age_sums["age_61_90"],
                age_sums["age_90_plus"],
            ],
        })
        bucket_colors = {
            "0-30 Days":  "#10b981",
            "31-60 Days": "#f59e0b",
            "61-90 Days": "#f97316",
            "90+ Days":   "#ef4444",
        }
        fig = px.bar(
            age_df, x="Bucket", y="Stock Value (Rs)",
            color="Bucket",
            color_discrete_map=bucket_colors,
            text="Stock Value (Rs)",
            title="Total Capital Locked by Age Bucket",
        )
        fig.update_traces(
            texttemplate="Rs %{text:,.0f}",
            textposition="outside",
        )
        fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            showlegend=True,
            legend_title_text="Time Period",
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1,
            ),
            height=360,
            xaxis=dict(
                title="Age Bucket (Days Since Last Sale)",
                tickfont=dict(size=13),
            ),
            yaxis=dict(title="Capital Locked (Rs)"),
            uniformtext_minsize=10,
            uniformtext_mode="hide",
        )
        # Add a legend annotation explaining each bucket colour
        for i, (bucket, color) in enumerate(bucket_colors.items()):
            fig.add_annotation(
                x=i, y=0, xref="x", yref="y",
                text=f"<span style='color:{color}'>▇</span> {bucket}",
                showarrow=False, yshift=-28,
                font=dict(size=11),
                xanchor="center",
            )
        st.plotly_chart(fig, use_container_width=True)
    else:
        # Fallback: derive age buckets from max_age_days in stats_df
        if "max_age_days" in stats_df.columns and "total_stock_qty" in stats_df.columns:
            s = stats_df.copy()
            s["max_age_days"] = pd.to_numeric(s["max_age_days"], errors="coerce").fillna(0)
            s["total_stock_qty"] = pd.to_numeric(s["total_stock_qty"], errors="coerce").fillna(0)
            b0  = s[s["max_age_days"] <= 30]["total_stock_qty"].sum()
            b31 = s[(s["max_age_days"] > 30) & (s["max_age_days"] <= 60)]["total_stock_qty"].sum()
            b61 = s[(s["max_age_days"] > 60) & (s["max_age_days"] <= 90)]["total_stock_qty"].sum()
            b90 = s[s["max_age_days"] > 90]["total_stock_qty"].sum()
            age_df2 = pd.DataFrame({
                "Bucket":      ["0-30 Days", "31-60 Days", "61-90 Days", "90+ Days"],
                "Stock Units": [b0, b31, b61, b90],
            })
            bucket_colors2 = {
                "0-30 Days":  "#10b981",
                "31-60 Days": "#f59e0b",
                "61-90 Days": "#f97316",
                "90+ Days":   "#ef4444",
            }
            fig2 = px.bar(
                age_df2, x="Bucket", y="Stock Units",
                color="Bucket",
                color_discrete_map=bucket_colors2,
                text="Stock Units",
                title="Stock Units by Age Bucket",
            )
            fig2.update_traces(texttemplate="%{text:,.0f} units", textposition="outside")
            fig2.update_layout(
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                showlegend=True,
                legend_title_text="Time Period",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                height=340,
            )
            st.plotly_chart(fig2, use_container_width=True)

    st.markdown("---")

    valid_items = stats_df["product_name"].unique()
    if len(valid_items) == 0:
        banner("✅ No dead stock currently in inventory — warehouse is clean!", "green")
        return


    # ── Priority filter ──────────────────────────────────────────────────────
    all_priorities = ["All", "Critical", "High", "Medium", "Low"]

    # Build priority map from stats
    priority_map: dict = {}
    for item in valid_items:
        details = ai.get_stock_details(item)
        if details:
            priority_map[item] = details.get("priority", "Low")
        else:
            priority_map[item] = "Low"

    col_pf1, col_pf2 = st.columns([1, 3])
    with col_pf1:
        priority_filter = st.selectbox(
            "🔴 Filter by Priority",
            all_priorities,
            index=0,
        )

    if priority_filter != "All":
        filtered_items = sorted([it for it, pr in priority_map.items() if pr == priority_filter])
    else:
        filtered_items = sorted(valid_items)

    if not filtered_items:
        banner(f"No dead stock items found with priority: **{priority_filter}**", "orange")
        return

    # ── Category → Product Hierarchy Filter ─────────────────────────────────
    # Build category → product mapping from df_dead
    cat_product_map: dict = {}   # category → list of products
    product_cat_map: dict = {}   # product  → category
    if not df_dead.empty and "product_category" in df_dead.columns and "dead_stock_item" in df_dead.columns:
        for _, row in df_dead[["dead_stock_item", "product_category"]].drop_duplicates().iterrows():
            prod = row["dead_stock_item"]
            cat  = str(row.get("product_category", "General") or "General")
            product_cat_map[prod] = cat
            cat_product_map.setdefault(cat, set()).add(prod)
        # Convert sets to sorted lists
        cat_product_map = {k: sorted(v) for k, v in cat_product_map.items()}

    # Intersect with the priority-filtered list
    all_cats = sorted(cat_product_map.keys()) if cat_product_map else []

    with col_pf2:
        if all_cats:
            selected_category = st.selectbox(
                "📂 Filter by Product Category",
                ["All Categories"] + all_cats,
                index=0,
                key="inv_cat_filter",
            )
        else:
            selected_category = "All Categories"
            st.info("Category data not available — all items shown.")

    # Determine which products to show in dropdown
    if selected_category != "All Categories" and selected_category in cat_product_map:
        # Only items in selected category that also passed priority filter
        candidate_items = sorted(set(filtered_items) & set(cat_product_map[selected_category]))
    else:
        candidate_items = filtered_items

    if not candidate_items:
        banner(f"No items found for category **{selected_category}** with priority **{priority_filter}**.", "orange")
        return

    selected_item = st.selectbox("📦 Select Dead Stock Item to clear", candidate_items)

    # ── Stock KPIs ───────────────────────────────────────────────────────────
    stock_details = ai.get_stock_details(selected_item)
    if stock_details is not None:
        c1, c2, c3 = st.columns(3)
        total_qty = stock_details.get("total_stock_qty", 0)
        c1.metric("Units to Clear", f"{total_qty} Units")
        c2.metric("Max Age in WH", f"{stock_details.get('max_age_days', 0)} Days")
        c3.metric(
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
    leads = df_dead[df_dead["dead_stock_item"] == selected_item].copy()

    # ── Ensure required columns with defaults ──────────────────────────────
    # The DB view uses `historical_qty_bought` — alias it to the name the UI expects
    if "buyer_past_purchase_qty" not in leads.columns:
        if "historical_qty_bought" in leads.columns:
            leads["buyer_past_purchase_qty"] = leads["historical_qty_bought"]
        else:
            leads["buyer_past_purchase_qty"] = 0

    for col, default in [
        ("Audience Type",      "Past Buyer"),
        ("mobile_no",          "—"),
        ("purchase_txn_count", 1),
        ("last_purchase_date", "Unknown"),
        ("state_name",         "Unknown"),
    ]:
        if col not in leads.columns:
            leads[col] = default
        elif col == "Audience Type":
            leads[col] = "Past Buyer"

    # ── Pull contact numbers for lookalike partners from df_dead itself ──────
    contact_lookup: dict = {}
    if not df_dead.empty and "mobile_no" in df_dead.columns and "potential_buyer" in df_dead.columns:
        _cl = df_dead[["potential_buyer", "mobile_no"]].dropna(subset=["potential_buyer"])
        _cl = _cl[_cl["mobile_no"].notna() & (_cl["mobile_no"] != "")]
        contact_lookup = dict(zip(_cl["potential_buyer"], _cl["mobile_no"]))

    # State lookup for lookalike partners
    state_lookup: dict = {}
    if not df_dead.empty and "state_name" in df_dead.columns and "potential_buyer" in df_dead.columns:
        _sl = df_dead[["potential_buyer", "state_name"]].dropna(subset=["potential_buyer"])
        state_lookup = dict(zip(_sl["potential_buyer"], _sl["state_name"]))

    # ── Find lookalike audiences from cluster data ───────────────────────────
    pf = getattr(ai, "df_partner_features", None)
    if not leads.empty and pf is not None:
        pf_reset = pf.reset_index()
        if "company_name" not in pf_reset.columns and "index" in pf_reset.columns:
            pf_reset = pf_reset.rename(columns={"index": "company_name"})

        if "cluster_label" in pf_reset.columns:
            leads = leads.merge(
                pf_reset[["company_name", "cluster_label"]],
                left_on="potential_buyer",
                right_on="company_name",
                how="left",
            )
            # Drop any duplicate columns created by the merge (e.g. company_name_x / company_name_y)
            leads = leads.loc[:, ~leads.columns.duplicated()]
            leads["Audience Type"] = "Past Buyer"

            buyer_clusters = leads["cluster_label"].dropna().unique()

            if len(buyer_clusters) > 0:
                already_buying = set(leads["potential_buyer"].dropna().str.lower())
                lookalike_pool = pf_reset[
                    pf_reset["cluster_label"].isin(buyer_clusters)
                    & ~pf_reset["company_name"].str.lower().isin(already_buying)
                ].copy()

                if not lookalike_pool.empty:
                    if "recent_90_revenue" in lookalike_pool.columns:
                        lookalike_pool = lookalike_pool.sort_values(
                            "recent_90_revenue", ascending=False
                        )
                    lookalike_pool = lookalike_pool.head(10)

                    lookalike_rows = []
                    for _, row in lookalike_pool.iterrows():
                        company     = row["company_name"]
                        cluster_lbl = str(row.get("cluster_label", "Unknown"))
                        if len(cluster_lbl) > 25:
                            cluster_lbl = cluster_lbl[:22] + "..."
                        mobile = contact_lookup.get(company, "—")
                        state  = state_lookup.get(company, "Unknown")
                        lookalike_rows.append({
                            "potential_buyer":        company,
                            "mobile_no":              mobile,
                            "buyer_past_purchase_qty": 0,
                            "purchase_txn_count":     0,
                            "last_purchase_date":     pd.NaT,
                            "state_name":             state,
                            "Audience Type":          f"Lookalike ({cluster_lbl})",
                            "cluster_label":          row.get("cluster_label", "Unknown"),
                        })

                    if lookalike_rows:
                        lookalike_df = pd.DataFrame(lookalike_rows)
                        leads = pd.concat([leads, lookalike_df], ignore_index=True)

    # Final safety — stamp Audience Type
    if "Audience Type" not in leads.columns:
        leads["Audience Type"] = "Past Buyer"

    # Clean up mobile_no display
    if "mobile_no" in leads.columns:
        leads["mobile_no"] = (
            leads["mobile_no"]
            .fillna("—")
            .astype(str)
            .str.strip()
            .replace({"": "—", "nan": "—", "None": "—"})
        )

    # Clean up state_name
    if "state_name" in leads.columns:
        leads["state_name"] = (
            leads["state_name"]
            .fillna("Unknown")
            .astype(str)
            .str.strip()
            .replace({"": "Unknown", "nan": "Unknown", "None": "Unknown"})
        )

    # Ensure numeric columns
    leads["buyer_past_purchase_qty"] = pd.to_numeric(leads["buyer_past_purchase_qty"], errors="coerce").fillna(0).astype(int)
    leads["purchase_txn_count"]      = pd.to_numeric(leads["purchase_txn_count"],      errors="coerce").fillna(1).astype(int)

    # Compute avg_qty_per_txn for purchase pattern column
    leads["avg_qty_per_txn"] = (
        leads["buyer_past_purchase_qty"] / leads["purchase_txn_count"].replace(0, 1)
    ).round(0).astype(int)

    # ── Purchase Pattern label ────────────────────────────────────────────────
    # "Bulk Buyer" → bought in few large orders   (avg_qty ≥ 100 or ≤ 2 txns for decent qty)
    # "Frequent"   → bought many smaller orders
    # "One-time"   → only 1 transaction
    def _purchase_pattern(row):
        qty  = int(row["buyer_past_purchase_qty"])
        txns = int(row["purchase_txn_count"])
        avg  = int(row["avg_qty_per_txn"])
        if txns == 0 or qty == 0:
            return "No History"
        if txns == 1:
            return f"One-time ({qty} units)"
        if avg >= 100 or (txns <= 2 and qty >= 50):
            return f"Bulk Buyer ({txns} orders, avg {avg}/order)"
        return f"Frequent ({txns} orders, avg {avg}/order)"

    # Guard: remove any duplicate columns before apply (prevents DataFrame return)
    leads = leads.loc[:, ~leads.columns.duplicated()]
    leads["purchase_pattern"] = leads.apply(_purchase_pattern, axis=1, result_type="reduce")

    leads = leads.sort_values("buyer_past_purchase_qty", ascending=False)

    # ── Header + Export ──────────────────────────────────────────────────────
    col_hdr, col_dl = st.columns([3, 1])
    with col_hdr:
        section_header(f"Target Buyers — {selected_item} ({len(leads)} leads)")
    with col_dl:
        _export_cols = [c for c in [
            "potential_buyer", "mobile_no", "state_name", "Audience Type",
            "buyer_past_purchase_qty", "purchase_txn_count", "purchase_pattern",
            "last_purchase_date",
        ] if c in leads.columns]
        csv = leads[_export_cols].to_csv(index=False)
        st.download_button(
            "⬇️ Export Campaign List",
            csv,
            f"leads_{selected_item.replace(' ', '_')}.csv",
            "text/csv",
            use_container_width=True,
        )

    # ── Display table ────────────────────────────────────────────────────────
    _display_cols = [c for c in [
        "potential_buyer", "mobile_no", "state_name", "Audience Type",
        "buyer_past_purchase_qty", "purchase_pattern", "last_purchase_date",
    ] if c in leads.columns]

    st.dataframe(
        leads[_display_cols],
        column_config={
            "potential_buyer":        "Partner Name",
            "mobile_no":              "Contact Number",
            "state_name":             "Area (State)",
            "Audience Type":          "Audience Strategy",
            "buyer_past_purchase_qty": st.column_config.NumberColumn(
                "Total Qty Bought", format="%d"
            ),
            "purchase_pattern":       "Purchase Pattern",
            "last_purchase_date":     "Last Purchase",
        },
        use_container_width=True,
        hide_index=True,
    )

    # ── Purchase Pattern legend ───────────────────────────────────────────────
    st.markdown(
        """
        <div style="
            background: rgba(245,158,11,0.08);
            border-left: 3px solid #f59e0b;
            border-radius: 6px;
            padding: 10px 16px;
            margin-top: 8px;
            font-size: 0.85rem;
            line-height: 1.7;
        ">
        <b>📦 Purchase Pattern Guide:</b><br/>
        &bull; <b>Bulk Buyer</b> — bought large quantities in few orders. Target with bulk-discount offers.<br/>
        &bull; <b>Frequent</b> — buys regularly in smaller lots. Target with replenishment campaigns.<br/>
        &bull; <b>One-time</b> — bought once. Target with reactivation scripts.<br/>
        &bull; <b>No History</b> — Lookalike partner, has never bought this item.
        </div>
        """,
        unsafe_allow_html=True,
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
