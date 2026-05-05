import pandas as pd
import streamlit as st
import datetime, hashlib, random

import sys, os, re
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from ml_engine.services.export_service import (
    export_recommendation_plan_pdf,
    export_recommendation_plan_excel,
)
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from styles import apply_global_styles, section_header, page_caption, banner, page_header, skeleton_loader


# ── Helpers ───────────────────────────────────────────────────────────────────

def _inr(v):
    try: v = float(v)
    except: return "₹0"
    if v >= 1_00_00_000: return f"₹{v/1_00_00_000:.1f}Cr"
    if v >= 1_00_000:    return f"₹{v/1_00_000:.1f}L"
    if v >= 1_000:       return f"₹{v/1_000:.0f}K"
    return f"₹{v:.0f}"


@st.cache_data(ttl=120, show_spinner=False)
def _fetch_partner_context(_engine, partner_name: str):
    """Returns dict: recent_products list, days_since_last, top_categories, order_count."""
    try:
        df = pd.read_sql(
            """SELECT mp.product_name,
                      COALESCE(mpc.category_name, mg.group_name, 'General') AS category,
                      MAX(t.date)          AS last_date,
                      SUM(tp.qty)          AS total_qty,
                      COUNT(DISTINCT t.id) AS order_count
               FROM transactions_dsr t
               JOIN transactions_dsr_products tp ON tp.dsr_id = t.id
               JOIN master_products mp            ON mp.id = tp.product_id
               JOIN master_party p               ON p.id  = t.party_id
               LEFT JOIN master_group mg          ON mg.id = mp.group_id
               LEFT JOIN master_product_category mpc ON mpc.id = mg.category_id_id
               WHERE LOWER(CAST(t.is_approved AS TEXT)) = 'true'
                 AND p.company_name = %(name)s
               GROUP BY mp.product_name, mpc.category_name, mg.group_name
               ORDER BY last_date DESC
               LIMIT 20""",
            _engine, params={"name": partner_name},
        )
        if df.empty:
            return {}
        last_date = pd.to_datetime(df.iloc[0]["last_date"]).date()
        days_since = (datetime.date.today() - last_date).days
        return {
            "recent_products": df["product_name"].tolist(),
            "days_since_last": days_since,
            "last_product":    df.iloc[0]["product_name"],
            "top_categories":  df["category"].value_counts().head(3).index.tolist(),
            "order_count":     int(df["order_count"].sum()),
        }
    except Exception:
        return {}


@st.cache_data(ttl=120, show_spinner=False)
def _fetch_product_affinity_partners(_engine, product_name: str, all_assoc_df, partner_matrix):
    """
    For a given product, find partners most likely to buy it.
    Logic:
      1. Find assoc rules where product_b = product_name → trigger products
      2. Find partners who have bought those trigger products (from matrix)
      3. Exclude partners who already buy product_name heavily
      4. Score by confidence × lift, output ranked table
    """
    try:
        if all_assoc_df is None or all_assoc_df.empty:
            return pd.DataFrame()

        # Rules where this product is the recommendation
        rules = all_assoc_df[all_assoc_df["product_b"] == product_name].copy()
        if rules.empty:
            # Try product_a side too
            rules = all_assoc_df[all_assoc_df["product_a"] == product_name].rename(
                columns={"product_a": "product_b", "product_b": "product_a",
                         "confidence_a_to_b": "confidence_a_to_b"}
            )
        if rules.empty:
            return pd.DataFrame()

        # For each trigger product, find partners who bought it
        if partner_matrix is None or partner_matrix.empty:
            return pd.DataFrame()

        rows = []
        for _, rule in rules.iterrows():
            trigger = rule["product_a"]
            conf    = float(rule.get("confidence_a_to_b", 0) or 0)
            lift    = float(rule.get("lift_a_to_b", 0) or 0)
            freq    = int(rule.get("times_bought_together", 0) or 0)

            if trigger in partner_matrix.columns:
                bought_trigger = partner_matrix[partner_matrix[trigger] > 0]
                for pname in bought_trigger.index:
                    already = float(partner_matrix.at[pname, product_name]) if product_name in partner_matrix.columns else 0
                    score = conf * max(lift, 1.0) * (1 / (1 + already * 0.1))
                    rows.append({
                        "partner":         pname,
                        "trigger_product": trigger,
                        "confidence":      conf,
                        "lift":            lift,
                        "frequency":       freq,
                        "already_bought":  already > 0,
                        "score":           round(score, 4),
                    })

        if not rows:
            return pd.DataFrame()

        df_out = pd.DataFrame(rows)
        # Keep best rule per partner
        df_out = df_out.sort_values("score", ascending=False).drop_duplicates("partner")
        df_out = df_out.sort_values("score", ascending=False).reset_index(drop=True)
        df_out["rank"] = df_out.index + 1
        return df_out
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=300, show_spinner=False)
def _fetch_product_buyers_direct(_engine, product_name: str):
    """
    Query transaction history to find every partner who has actually bought
    this product. Returns company_name, mobile, state, order_count,
    total_qty, total_revenue, last_purchase_date.
    """
    try:
        sql = """
            SELECT
                mp.company_name,
                COALESCE(mp.mobile_no::text, '—')       AS mobile_no,
                COALESCE(mp.state_name, 'Unknown')       AS state_name,
                COUNT(DISTINCT t.id)                     AS order_count,
                SUM(tp.qty)                              AS total_qty,
                MAX(t.date)::date                        AS last_purchase_date,
                ROUND(SUM(tp.net_amt)::numeric, 0)       AS total_revenue
            FROM transactions_dsr t
            JOIN transactions_dsr_products tp ON tp.dsr_id = t.id
            JOIN master_products p            ON p.id = tp.product_id
            JOIN master_party mp              ON mp.id = t.party_id
            WHERE LOWER(CAST(t.is_approved AS TEXT)) = 'true'
              AND p.product_name = %(product_name)s
            GROUP BY mp.company_name, mp.mobile_no, mp.state_name
            ORDER BY total_qty DESC
        """
        df = pd.read_sql(sql, _engine, params={"product_name": product_name})
        df["last_purchase_date"] = pd.to_datetime(df["last_purchase_date"])
        return df
    except Exception:
        # Fallback without state join
        try:
            sql2 = """
                SELECT
                    mp.company_name,
                    COALESCE(mp.mobile_no::text, '—') AS mobile_no,
                    'Unknown'                          AS state_name,
                    COUNT(DISTINCT t.id)               AS order_count,
                    SUM(tp.qty)                        AS total_qty,
                    MAX(t.date)::date                  AS last_purchase_date,
                    ROUND(SUM(tp.net_amt)::numeric, 0) AS total_revenue
                FROM transactions_dsr t
                JOIN transactions_dsr_products tp ON tp.dsr_id = t.id
                JOIN master_products p            ON p.id = tp.product_id
                JOIN master_party mp              ON mp.id = t.party_id
                WHERE LOWER(CAST(t.is_approved AS TEXT)) = 'true'
                  AND p.product_name = %(product_name)s
                GROUP BY mp.company_name, mp.mobile_no
                ORDER BY total_qty DESC
            """
            df2 = pd.read_sql(sql2, _engine, params={"product_name": product_name})
            df2["last_purchase_date"] = pd.to_datetime(df2["last_purchase_date"])
            return df2
        except Exception:
            return pd.DataFrame()


@st.cache_data(ttl=300, show_spinner=False)
def _fetch_product_prospects(_engine, product_name: str,
                              trigger_products: tuple, existing_buyers: tuple):
    """
    Partners who buy trigger products (co-purchased with product_name in
    association rules) but have NEVER bought product_name themselves.
    Ranked by trigger product volume — these are the highest-conversion prospects.
    """
    try:
        if not trigger_products:
            return pd.DataFrame()
        sql = """
            SELECT
                mp.company_name,
                COALESCE(mp.mobile_no::text, '—')       AS mobile_no,
                COALESCE(mp.state_name, 'Unknown')       AS state_name,
                p.product_name                           AS trigger_product,
                COUNT(DISTINCT t.id)                     AS trigger_orders,
                SUM(tp.qty)                              AS trigger_qty,
                MAX(t.date)::date                        AS last_purchase_date
            FROM transactions_dsr t
            JOIN transactions_dsr_products tp ON tp.dsr_id = t.id
            JOIN master_products p            ON p.id = tp.product_id
            JOIN master_party mp              ON mp.id = t.party_id
            WHERE LOWER(CAST(t.is_approved AS TEXT)) = 'true'
              AND p.product_name = ANY(%(triggers)s)
            GROUP BY mp.company_name, mp.mobile_no, mp.state_name, p.product_name
            ORDER BY trigger_qty DESC
        """
        df = pd.read_sql(sql, _engine,
                         params={"triggers": list(trigger_products)})
        if df.empty:
            return pd.DataFrame()
        df["last_purchase_date"] = pd.to_datetime(df["last_purchase_date"])
        # Exclude partners who already buy this product
        excl = set(b.lower() for b in existing_buyers)
        df = df[~df["company_name"].str.lower().isin(excl)]
        # Best single trigger per partner
        df = (df.sort_values("trigger_qty", ascending=False)
                .drop_duplicates("company_name")
                .reset_index(drop=True))
        return df
    except Exception:
        return pd.DataFrame()


def _build_personalized_scripts(partner_name, rec_product, trigger_products,
                                 partner_ctx, cluster_label, health_segment):
    """
    Build WhatsApp + Email scripts from inventory/affinity signals.
    No discount language. References real purchase history.
    """
    seed = int(hashlib.md5(f"{partner_name}{rec_product}".encode()).hexdigest(), 16) % (2**31)
    rng  = random.Random(seed)

    last_prod    = partner_ctx.get("last_product", "your last order")
    days_since   = partner_ctx.get("days_since_last", 30)
    top_cats     = partner_ctx.get("top_categories", [])
    order_count  = partner_ctx.get("order_count", 0)
    top_cat_str  = top_cats[0] if top_cats else "your category"
    trigger_str  = trigger_products[0] if trigger_products else last_prod

    # WhatsApp (short, conversational, max 4 sentences)
    if days_since > 60:
        wa_opens = [
            f"Hi, it's been a while since your {last_prod} order — wanted to reach out before your next stock cycle.",
            f"Hey! Noticed a gap since your last {last_prod} — good time to touch base.",
        ]
    elif order_count >= 20:
        wa_opens = [
            f"Hey! Always good to connect with one of our regulars in {top_cat_str}.",
            f"Hi, checking in — you've been consistent with {trigger_str} and I had something relevant to share.",
        ]
    else:
        wa_opens = [
            f"Hi! A quick note based on your recent {trigger_str} orders.",
            f"Hey — following up on your {last_prod} order with something that fits well.",
        ]
    wa_open = rng.choice(wa_opens)

    wa_bodies = [
        f"We've been seeing strong demand for {rec_product} among partners in {top_cat_str} — and it pairs well with your current stock profile.",
        f"{rec_product} is moving well with partners who stock {trigger_str}. Based on your ordering pattern, it looks like a natural fit.",
        f"Partners with a similar {top_cat_str} mix as yours have been adding {rec_product} to their regular orders — thought it was worth flagging.",
    ]
    wa_body = rng.choice(wa_bodies)
    wa_close = rng.choice([
        f"Would it make sense to include it in your next order? Happy to sort the logistics.",
        f"Let me know if you'd like to add it — I can have it ready with your next {trigger_str} shipment.",
        f"Worth considering for your next cycle? I can send details.",
    ])
    whatsapp = f"{wa_open}\n\n{wa_body}\n\n{wa_close}"

    # Email subject
    subj_options = [
        f"{rec_product} — a natural addition to your {top_cat_str} stock",
        f"Based on your {trigger_str} orders — {rec_product}",
        f"Product note for your account: {rec_product}",
    ]
    email_subject = rng.choice(subj_options)

    # Email body
    segment_note = ""
    if health_segment in ("VIP", "Champion"):
        segment_note = f"As one of our stronger partners in {top_cat_str}, "
    elif health_segment in ("At Risk", "Critical"):
        segment_note = "I wanted to make sure we're staying in sync on your stock needs — "
    else:
        segment_note = f"Looking at your account in {top_cat_str}, "

    email_body = (
        f"Dear {partner_name},\n\n"
        f"{segment_note}I wanted to flag {rec_product} as something worth considering for your next order.\n\n"
        f"You've been ordering {trigger_str} regularly, and across our partner network, "
        f"{rec_product} consistently comes up alongside it. It's not a random recommendation — "
        f"it's based on what's actually moving with accounts that have a similar stock profile to yours.\n\n"
        f"If you'd like, I can put together the specifics — quantities, availability, and how it fits "
        f"your current order cycle. No pressure, just wanted to make sure it's on your radar "
        f"before your next replenishment.\n\n"
        f"Let me know if you'd like to discuss.\n\nBest regards"
    )

    return {"whatsapp": whatsapp, "email_subject": email_subject, "email_body": email_body}


def render(ai):
    apply_global_styles()

    page_header(
        title="Recommendation Hub",
        subtitle="Partner-specific action plan powered by cluster, churn, credit, peer gaps, and affinity signals.",
        icon="💡",
        accent_color="#f59e0b",
        badge_text="AI-Powered",
    )
    skel = st.empty()
    with skel.container():
        skeleton_loader(n_metric_cards=4, n_rows=4, label="Loading recommendation context...")
    ai.ensure_clustering()
    if ai.enable_realtime_partner_scoring:
        ai.ensure_churn_forecast()
        ai.ensure_credit_risk()
    skel.empty()
    ai.ensure_associations()

    if ai.matrix is None or ai.matrix.empty:
        st.warning("No partner matrix available. Refresh data and try again.")
        return

    states = sorted(ai.matrix["state"].dropna().unique().tolist())
    selected_state = st.selectbox("State / Region", states)
    partner_list = sorted(ai.matrix[ai.matrix["state"] == selected_state].index.unique().tolist())
    if not partner_list:
        st.warning("No partners found for selected state.")
        return

    selected_partner = st.selectbox("Partner", partner_list)
    top_n = st.slider("Top Actions", 1, 5, 3, 1)

    # ────────────────────────────── Tabs ──────────────────────────────────────
    tab_rec, tab_product = st.tabs([
        "📋 Recommendations", "🎯 Product → Partner",
    ])

    # ── Tab 2: Product → Partner Intelligence ────────────────────────────────
    with tab_product:
        section_header("🎯 Product → Partner Intelligence")
        st.caption(
            "Select a product to see **who is already buying it** and "
            "**who is the best prospect to pitch it to** — powered by "
            "direct transaction history and co-purchase affinity signals."
        )

        engine = getattr(ai, "engine", None)

        @st.cache_data(ttl=600, show_spinner=False)
        def _all_products_txn(_engine):
            try:
                df = pd.read_sql(
                    """SELECT DISTINCT p.product_name
                       FROM transactions_dsr t
                       JOIN transactions_dsr_products tp ON tp.dsr_id = t.id
                       JOIN master_products p ON p.id = tp.product_id
                       WHERE LOWER(CAST(t.is_approved AS TEXT)) = 'true'
                       ORDER BY p.product_name""",
                    _engine,
                )
                return sorted(df["product_name"].dropna().tolist())
            except Exception:
                return []

        all_products_txn = _all_products_txn(engine) if engine else []

        if not all_products_txn:
            _ar = ai.get_associations(
                search_term="", min_confidence=0.0, min_lift=0.0,
                min_support=1, include_low_support=True, limit=5000,
            )
            all_products_txn = sorted(set(
                list(_ar["product_a"].dropna().unique()) +
                list(_ar["product_b"].dropna().unique())
            )) if not _ar.empty else []

        if not all_products_txn:
            st.warning("No product data found. Ensure data is loaded.")
        else:
            p_col, _ = st.columns([3, 1])
            with p_col:
                sel_product = st.selectbox(
                    "Select a Product to Analyse",
                    all_products_txn,
                    key="prod_intel_sel",
                )

            with st.spinner("Fetching buyer intelligence from transaction history…"):
                buyers_df = (
                    _fetch_product_buyers_direct(engine, sel_product)
                    if engine else pd.DataFrame()
                )
                _assoc_prod = ai.get_associations(
                    search_term=sel_product, min_confidence=0.0, min_lift=0.0,
                    min_support=1, include_low_support=True, limit=300,
                )
                trigger_prods: tuple = ()
                if not _assoc_prod.empty:
                    t_from_b = _assoc_prod[_assoc_prod["product_b"] == sel_product]["product_a"].tolist()
                    t_from_a = _assoc_prod[_assoc_prod["product_a"] == sel_product]["product_b"].tolist()
                    trigger_prods = tuple(set(t_from_b + t_from_a))[:15]

                existing_names: tuple = tuple(buyers_df["company_name"].tolist()) if not buyers_df.empty else ()
                prospects_df = (
                    _fetch_product_prospects(engine, sel_product, trigger_prods, existing_names)
                    if (engine and trigger_prods) else pd.DataFrame()
                )

                if engine and not buyers_df.empty and hasattr(ai, "matrix") and ai.matrix is not None and "cluster_label" in ai.matrix.columns:
                    buyer_clusters = ai.matrix.loc[ai.matrix.index.intersection(existing_names), "cluster_label"]
                    if not buyer_clusters.empty:
                        top_clusters = buyer_clusters.value_counts().head(2).index.tolist()
                        cluster_prospects = ai.matrix[
                            ai.matrix["cluster_label"].isin(top_clusters) & 
                            (~ai.matrix.index.isin(existing_names))
                        ].copy()
                        if not cluster_prospects.empty:
                            cluster_prospects["company_name"] = cluster_prospects.index
                            cluster_prospects["mobile_no"] = "—"
                            cluster_prospects["state_name"] = cluster_prospects.get("state", "Unknown")
                            cluster_prospects["trigger_product"] = "Cluster Peer (" + cluster_prospects["cluster_label"].astype(str) + ")"
                            cluster_prospects["trigger_qty"] = 0
                            cluster_prospects["trigger_orders"] = 0
                            cluster_prospects["last_purchase_date"] = pd.NaT
                            cluster_df = cluster_prospects[["company_name", "mobile_no", "state_name", "trigger_product", "trigger_qty", "trigger_orders", "last_purchase_date"]]
                            
                            if prospects_df.empty:
                                prospects_df = cluster_df.reset_index(drop=True)
                            else:
                                prospects_df = pd.concat([prospects_df, cluster_df]).drop_duplicates(subset=["company_name"])
                                prospects_df = prospects_df.sort_values(["trigger_qty", "trigger_orders"], ascending=[False, False]).reset_index(drop=True)

            k1, k2, k3, k4 = st.columns(4)
            k1.metric("Proven Buyers", f"{len(buyers_df)}")
            k2.metric("Total Units Sold (All Time)",
                      f"{int(buyers_df['total_qty'].sum()):,}" if not buyers_df.empty else "0")
            k3.metric("Total Revenue Generated",
                      _inr(buyers_df["total_revenue"].sum()) if not buyers_df.empty else "₹0")
            k4.metric("High-Affinity Prospects", f"{len(prospects_df)}")
            st.markdown("---")

            buyer_tab, prospect_tab = st.tabs([
                f"✅ Proven Buyers ({len(buyers_df)})",
                f"🎯 High-Affinity Prospects ({len(prospects_df)})",
            ])

            with buyer_tab:
                st.caption(
                    "Partners who have **directly purchased** this product — "
                    "ranked by total quantity. Use for upsell / replenishment campaigns."
                )
                if buyers_df.empty:
                    st.info(f"No purchase history found for **{sel_product}**.")
                else:
                    buyers_df = buyers_df.copy()
                    buyers_df["rank"] = range(1, len(buyers_df) + 1)
                    buyers_df["days_since"] = buyers_df["last_purchase_date"].apply(
                        lambda d: (datetime.date.today() - pd.Timestamp(d).date()).days
                        if pd.notna(d) else 999
                    )
                    st.dataframe(
                        buyers_df[[
                            "rank", "company_name", "mobile_no", "state_name",
                            "order_count", "total_qty", "total_revenue", "days_since",
                        ]],
                        column_config={
                            "rank":          st.column_config.NumberColumn("#"),
                            "company_name":  "Partner",
                            "mobile_no":     "Contact",
                            "state_name":    "State",
                            "order_count":   st.column_config.NumberColumn("Orders"),
                            "total_qty":     st.column_config.NumberColumn("Total Units"),
                            "total_revenue": st.column_config.NumberColumn("Revenue (₹)", format="₹%d"),
                            "days_since":    st.column_config.NumberColumn("Days Since Last", format="%d d"),
                        },
                        use_container_width=True, hide_index=True,
                    )
                    st.download_button(
                        "⬇️ Export Buyer List",
                        buyers_df.to_csv(index=False),
                        f"buyers_{sel_product[:30].replace(' ', '_')}.csv",
                        "text/csv",
                    )

            with prospect_tab:
                st.caption(
                    f"Partners who regularly buy products **co-purchased with** "
                    f"**{sel_product}** but have never ordered it themselves. "
                    "Highest-conversion new opportunities."
                )
                if not trigger_prods:
                    st.info("No co-purchase signal available — not enough basket overlap in transaction history.")
                elif prospects_df.empty:
                    st.info("No prospects found. Product may already be widely distributed.")
                else:
                    prospects_df = prospects_df.copy()
                    prospects_df["rank"] = range(1, len(prospects_df) + 1)
                    prospects_df["days_since"] = prospects_df["last_purchase_date"].apply(
                        lambda d: (datetime.date.today() - pd.Timestamp(d).date()).days
                        if pd.notna(d) else 999
                    )
                    st.dataframe(
                        prospects_df[[
                            "rank", "company_name", "mobile_no", "state_name",
                            "trigger_product", "trigger_qty", "trigger_orders", "days_since",
                        ]],
                        column_config={
                            "rank":            st.column_config.NumberColumn("#"),
                            "company_name":    "Partner",
                            "mobile_no":       "Contact",
                            "state_name":      "State",
                            "trigger_product": "Because They Buy…",
                            "trigger_qty":     st.column_config.NumberColumn("Trigger Units"),
                            "trigger_orders":  st.column_config.NumberColumn("Trigger Orders"),
                            "days_since":      st.column_config.NumberColumn("Days Since Trigger", format="%d d"),
                        },
                        use_container_width=True, hide_index=True,
                    )
                    if trigger_prods:
                        st.caption(
                            f"📌 Co-purchase triggers: "
                            + ", ".join(trigger_prods[:5])
                            + (f" + {len(trigger_prods)-5} more" if len(trigger_prods) > 5 else "")
                        )
                    st.download_button(
                        "⬇️ Export Prospect List",
                        prospects_df.to_csv(index=False),
                        f"prospects_{sel_product[:30].replace(' ', '_')}.csv",
                        "text/csv",
                    )

    # ── Tab 1: Recommendations ────────────────────────────────────────────────
    with tab_rec:
        model_name = str(getattr(ai, "gemini_model", "gemini-1.5-flash"))
        key = str(getattr(ai, "gemini_api_key", "")).strip()




    # ── Recommendation Plan (cached per partner, triggered by button) ────────
    _plan_cache_key = f"_reco_plan_{selected_partner}_{top_n}"
    plan = st.session_state.get(_plan_cache_key, None)

    _btn_col, _info_col = st.columns([1, 4])
    with _btn_col:
        _gen_plan = st.button(
            "Generate Recommendation Plan",
            key="reco_plan_btn",
            help="Runs AI analysis to build a personalised action plan. Results are cached until you change the partner.",
            use_container_width=True,
        )
    with _info_col:
        if plan is None:
            st.info("💡 Click **Generate Recommendation Plan** to run AI analysis for this partner.")
        else:
            st.success(f"✅ Showing cached plan for **{selected_partner}**. Re-click to refresh.")

    if _gen_plan:
        with st.spinner("Generating recommendation plan..."):
            plan = ai.get_partner_recommendation_plan(
                partner_name=selected_partner,
                top_n=int(top_n),
                use_genai=True,
                api_key=key if key else None,
                model=model_name,
            )
        st.session_state[_plan_cache_key] = plan
        st.rerun()

    if plan is None:
        return

    # --- Export Buttons ---
    rex1, rex2, rex3 = st.columns([1, 1, 4])
    with rex1:
        reco_pdf = export_recommendation_plan_pdf(selected_partner, plan)
        st.download_button(
            "\u2B07 Download PDF",
            data=reco_pdf,
            file_name=f"Reco_Plan_{selected_partner.replace(' ', '_')}.pdf",
            mime="application/pdf",
            key="reco_pdf",
        )
    with rex2:
        reco_xls = export_recommendation_plan_excel(selected_partner, plan)
        st.download_button(
            "\u2B07 Download Excel",
            data=reco_xls,
            file_name=f"Reco_Plan_{selected_partner.replace(' ', '_')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="reco_xlsx",
        )

    st.markdown("---")
    c1, c2 = st.columns(2)
    with c1:
        st.metric("Partner", str(plan.get("partner_name", selected_partner)))
    with c2:
        st.metric(
            "Segment",
            f"{plan.get('cluster_label', 'Unknown')} ({plan.get('cluster_type', 'Unknown')})",
        )
    st.info(f"Suggested Sequence: {plan.get('sequence_summary', 'N/A')}")

    actions = plan.get("actions", []) or []
    bundles = ai.get_partner_bundle_recommendations(partner_name=selected_partner, top_n=5)


    explanation = plan.get("plain_language_explanation", {}) or {}

    # ======================================================================
    # Enhanced Recommendations (Bandits + Collaborative + Learned Scoring)
    # ======================================================================
    st.markdown("---")
    if explanation and isinstance(explanation, dict):
        st.subheader("Recommendation Explanation (Plain Language)")
        summary = str(explanation.get("summary", "")).strip()
        if summary:
            st.info(summary)
        reasons = explanation.get("reasons", []) or []
        if isinstance(reasons, list):
            for idx, reason in enumerate(reasons, start=1):
                st.write(f"{idx}. {reason}")

        signals = explanation.get("model_signals", {}) or {}
        if isinstance(signals, dict) and signals:
            s1, s2, s3 = st.columns(3)
            with s1:
                st.metric(
                    "Peer Gap (Top Category)",
                    f"{float(signals.get('peer_gap_delta_pct', 0.0)):.1f}%",
                )
            with s2:
                st.metric(
                    "Churn Probability",
                    f"{float(signals.get('churn_probability', 0.0)) * 100:.1f}%",
                )
            with s3:
                st.metric(
                    "Credit Risk",
                    f"{float(signals.get('credit_risk_score', 0.0)) * 100:.1f}%",
                )
    elif explanation and isinstance(explanation, str):
        st.subheader("Recommendation Explanation")
        st.info(explanation)

    st.markdown("---")
    st.subheader("📨 Personalized Pitch Scripts")
    st.caption("Built from your inventory, partner purchase history, and affinity signals — no generic discounts.")

    if not actions:
        st.info("Generate recommendations first to create pitch scripts.")
    else:
        seq_options = [int(a.get("sequence", i + 1)) for i, a in enumerate(actions)]
        selected_seq = st.selectbox("Pick Recommendation", seq_options, index=0, key="rh_seq_sel")

        sel_action  = next((a for a in actions if int(a.get("sequence", 0)) == selected_seq), actions[0])
        rec_product = str(sel_action.get("recommended_offer", "") or "")

        # Affinity triggers from bundle recs
        trigger_prods = [str(r.trigger_product) for r in bundles.itertuples()] if not bundles.empty else []

        # Partner context
        _engine = getattr(ai, "engine", None)
        partner_ctx = _fetch_partner_context(_engine, selected_partner) if _engine else {}

        scripts = _build_personalized_scripts(
            partner_name     = selected_partner,
            rec_product      = rec_product,
            trigger_products = trigger_prods,
            partner_ctx      = partner_ctx,
            cluster_label    = str(plan.get("cluster_label", "")),
            health_segment   = str(plan.get("health_segment", "")),
        )

        wa_col, em_col = st.columns(2)
        with wa_col:
            st.markdown(
                "<div style='background:#0f172a;border:1px solid #25d366;border-radius:10px;"
                "padding:10px 14px;margin-bottom:8px;font-size:12px;font-weight:700;color:#25d366;'>"
                "💬 WhatsApp Message</div>", unsafe_allow_html=True,
            )
            st.text_area("WhatsApp", value=scripts["whatsapp"], height=190, key="rh_wa",
                         label_visibility="collapsed")
        with em_col:
            st.markdown(
                "<div style='background:#0f172a;border:1px solid #3b82f6;border-radius:10px;"
                "padding:10px 14px;margin-bottom:8px;font-size:12px;font-weight:700;color:#3b82f6;'>"
                "📧 Email</div>", unsafe_allow_html=True,
            )
            st.text_input("Subject", value=scripts["email_subject"], key="rh_subj")
            st.text_area("Email Body", value=scripts["email_body"], height=150, key="rh_email",
                         label_visibility="collapsed")





