import streamlit as st
import pandas as pd
import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from styles import apply_global_styles, section_header, page_caption, page_header, skeleton_loader


# ─────────────────────────────────────────────────────────────────────────────
# Helper: format INR
# ─────────────────────────────────────────────────────────────────────────────
def _inr(val):
    try:
        v = float(val)
    except Exception:
        return "₹0"
    if v >= 1_00_00_000:
        return f"₹{v/1_00_00_000:.1f}Cr"
    if v >= 1_00_000:
        return f"₹{v/1_00_000:.1f}L"
    if v >= 1_000:
        return f"₹{v/1_000:.0f}K"
    return f"₹{v:.0f}"


@st.cache_data(ttl=600, show_spinner=False)
def _fetch_category_map(_engine):
    """product_name → category_name from master tables."""
    try:
        import pandas as pd
        df = pd.read_sql(
            """SELECT mp.product_name,
                      COALESCE(mpc.category_name, mg.group_name, 'General') AS category
               FROM master_products mp
               LEFT JOIN master_group mg ON mg.id = mp.group_id
               LEFT JOIN master_product_category mpc ON mpc.id = mg.category_id_id""",
            _engine,
        )
        return df.drop_duplicates("product_name").set_index("product_name")["category"].to_dict()
    except Exception:
        return {}


@st.cache_data(ttl=120, show_spinner=False)
def _fetch_partner_recent_products(_engine, partner_name: str, n: int = 15):
    """Last N distinct products ordered by this partner (by most recent date)."""
    try:
        import pandas as pd
        return pd.read_sql(
            """SELECT mp.product_name,
                      COALESCE(mpc.category_name, mg.group_name, 'General') AS category,
                      MAX(t.date)         AS last_date,
                      SUM(tp.qty)         AS total_qty,
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
               LIMIT %(n)s""",
            _engine, params={"name": partner_name, "n": n},
        )
    except Exception:
        import pandas as pd
        return pd.DataFrame()


@st.cache_data(ttl=900, show_spinner=False)
def _fetch_bundle_monthly_trends(_engine, top_pairs: list):
    """
    Monthly co-purchase counts for a given list of (product_a, product_b) pairs.
    Queries raw transactions for the last 12 months.
    top_pairs: list of [product_a, product_b] strings (already the top bundles).
    """
    try:
        import pandas as pd
        if not top_pairs:
            return pd.DataFrame()
        # Build pair filter — LEAST/GREATEST normalise ordering
        pair_filters = " OR ".join(
            f"(LEAST(mp1.product_name, mp2.product_name) = %s "
            f"AND GREATEST(mp1.product_name, mp2.product_name) = %s)"
            for _ in top_pairs
        )
        params = []
        for a, b in top_pairs:
            params += [min(a, b), max(a, b)]

        sql = f"""
            SELECT
                TO_CHAR(t.date, 'YYYY-MM') AS month,
                LEAST(mp1.product_name, mp2.product_name)    AS product_a,
                GREATEST(mp1.product_name, mp2.product_name) AS product_b,
                COUNT(DISTINCT t.id) AS monthly_count
            FROM transactions_dsr t
            JOIN transactions_dsr_products tp1 ON tp1.dsr_id = t.id
            JOIN transactions_dsr_products tp2 ON tp2.dsr_id = t.id
                                               AND tp2.product_id > tp1.product_id
            JOIN master_products mp1 ON mp1.id = tp1.product_id
            JOIN master_products mp2 ON mp2.id = tp2.product_id
            WHERE LOWER(CAST(t.is_approved AS TEXT)) = 'true'
              AND t.date >= CURRENT_DATE - INTERVAL '12 months'
              AND ({pair_filters})
            GROUP BY month, product_a, product_b
            ORDER BY month, monthly_count DESC
        """
        with _engine.connect() as conn:
            df = pd.read_sql(sql, conn, params=params)
        return df
    except Exception:
        import pandas as pd
        return pd.DataFrame()


def _generate_human_script(
    partner_name, trigger_product, rec_product,
    trigger_category, rec_category,
    confidence, lift, frequency, gain_monthly,
    days_since_last, partner_order_count,
):
    """Rule-driven, human-sounding sales call script. No AI-buzzwords."""
    import random, hashlib
    seed = int(hashlib.md5(f"{partner_name}{rec_product}".encode()).hexdigest(), 16) % (2**31)
    rng  = random.Random(seed)

    same_cat = (trigger_category == rec_category and trigger_category not in ("General", "Unknown", ""))

    # ── Opening ──────────────────────────────────────────────────────────
    if days_since_last > 60:
        opens = [
            f"I was going through accounts and noticed it's been about {days_since_last} days since your last {trigger_product} order — wanted to reach out before your next cycle.",
            f"It's been a while since your last {trigger_product} shipment and I had a quick thought I wanted to run by you.",
        ]
    elif partner_order_count >= 20:
        opens = [
            f"With all the {trigger_product} you've been moving, I spotted something worth flagging before your next order.",
            f"I know you're on top of your {trigger_product} ordering — this one's quick and relevant.",
        ]
    else:
        opens = [
            f"I was looking at your recent {trigger_product} orders and there's something I wanted to mention.",
            f"Quick call about your {trigger_product} pattern — there's a pairing I think makes sense for your account.",
        ]
    opening = rng.choice(opens)

    # ── Pitch ─────────────────────────────────────────────────────────────
    cat_note = "same category" if same_cat else f"the {rec_category} side"
    if confidence >= 0.65:
        pitches = [
            f"About {confidence:.0%} of partners who regularly order {trigger_product} end up needing {rec_product} — we've tracked this across {frequency} actual orders. It's not a coincidence.",
            f"This is a pattern we see reliably: {trigger_product} goes out, {rec_product} follows. {confidence:.0%} of the time, same ordering cycle. Makes sense to plan for both.",
        ]
    elif confidence >= 0.40:
        pitches = [
            f"We've seen {frequency} cases where {trigger_product} and {rec_product} get ordered together from {cat_note}. Lift is {lift:.1f}x — that's meaningful correlation.",
            f"Not a slam dunk, but {confidence:.0%} of similar accounts are picking up {rec_product} alongside {trigger_product}. Worth a conversation.",
        ]
    else:
        pitches = [
            f"It's a lower-frequency pairing but {rec_product} keeps showing up alongside {trigger_product} orders — {frequency} times. Might be worth keeping in mind.",
            f"I wouldn't push hard on this one, but {rec_product} from {cat_note} has come up alongside {trigger_product} {frequency} times. Just flagging it.",
        ]
    pitch = rng.choice(pitches)

    # ── Value anchor ──────────────────────────────────────────────────────
    if gain_monthly >= 100000:
        value = f"Partners making this combination are adding roughly {_inr(gain_monthly)}/month in incremental revenue. At your volume, that compounds fast."
    elif gain_monthly >= 10000:
        value = f"Incremental gain on the pairing is about {_inr(gain_monthly)}/month — not massive, but it adds up and there's no extra effort on the logistics side."
    else:
        value = f"It's not a big revenue mover on its own, but it consolidates a delivery and removes a separate reorder step for you."

    # ── Objection handler ─────────────────────────────────────────────────
    if lift >= 3.0:
        objection = f"I'd push back on any hesitation here — {lift:.1f}x lift across {frequency} transactions isn't soft data. The demand is real."
    elif lift >= 1.5:
        objection = f"Even if you want to trial it — the {lift:.1f}x lift tells me it's not random. Start small and we'll track it from there."
    else:
        objection = f"Totally fair if it's not the right time. Just keep {rec_product} in mind — it's shown up {frequency} times alongside {trigger_product} and that number grows each quarter."

    # ── Close ─────────────────────────────────────────────────────────────
    closes = [
        f"Want me to add a trial qty of {rec_product} to your next {trigger_product} order? I can set it up now.",
        f"Should I put a combined quote together? Takes two minutes and you can decide from there.",
        f"I can note it on your account and raise it again at your next order — or we move on it now if the timing works.",
    ]
    close = rng.choice(closes)

    return {"opening": opening, "pitch": pitch, "value": value, "objection": objection, "close": close}


def render(ai):

    apply_global_styles()
    page_header(
        title="Market Basket Analysis",
        subtitle="Discover product bundle rules and partner-specific cross-sell opportunities from sales data.",
        icon="🛒",
        accent_color="#0891b2",
        badge_text="FP-Growth",
    )
    skel = st.empty()
    with skel.container():
        skeleton_loader(n_metric_cards=3, n_rows=3, label="Mining association rules...")
    ai.ensure_associations()
    ai.ensure_clustering()
    skel.empty()

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 1 — Bundle Builder Simulator (TOP OF PAGE)
    # ─────────────────────────────────────────────────────────────────────────
    section_header("🛠️ Bundle Builder Simulator")
    st.caption("Select a base product to instantly see the best items to bundle with it.")

    # Load ALL rules with very permissive thresholds for the bundle builder
    @st.cache_data(show_spinner=False, ttl=300)
    def _all_assoc(_ai_hash):
        return _ai_hash.get_associations(
            search_term="",
            min_confidence=0.0,
            min_lift=0.0,
            min_support=1,
            include_low_support=True,
            limit=5000,
        )

    # Use ai object id as cache key proxy
    _df_all = _all_assoc(ai)

    @st.cache_data(show_spinner=False)
    def _get_unique_products(df):
        if df.empty:
            return []
        return sorted(list(
            set(df["product_a"].dropna().unique()) |
            set(df["product_b"].dropna().unique())
        ))

    unique_products = _get_unique_products(_df_all) if not _df_all.empty else []
    base_product = st.selectbox("Select Base Product", [""] + unique_products, key="bundle_base")

    if base_product:
        bundle_options = (
            _df_all[_df_all["product_a"] == base_product]
            .sort_values("confidence_a_to_b", ascending=False)
            .head(5)
        )
        if not bundle_options.empty:
            b_cols = st.columns(min(len(bundle_options), 5))
            for idx, row in enumerate(bundle_options.itertuples()):
                conf_v = float(getattr(row, "confidence_a_to_b", 0))
                lift_v = float(getattr(row, "lift_a_to_b", 0))
                gain_m = float(getattr(row, "expected_gain_monthly", 0) or 0)
                with b_cols[idx]:
                    st.markdown(
                        f"""<div style="background:linear-gradient(135deg,#0c1a2e,#0f2642);
                            border:1px solid #1e3f6b;border-radius:12px;padding:14px 16px;
                            text-align:center;height:100%;">
                          <div style="font-size:13px;font-weight:700;color:#e2e8f0;
                                      margin-bottom:6px;line-height:1.4;">{row.product_b}</div>
                          <div style="font-size:11px;color:#38bdf8;margin-bottom:4px;">
                            Conf: {conf_v:.0%} &nbsp;|&nbsp; Lift: {lift_v:.1f}x
                          </div>
                          <div style="font-size:11px;color:#22c55e;font-weight:600;">
                            +{_inr(gain_m)}/mo
                          </div>
                        </div>""",
                        unsafe_allow_html=True,
                    )
        else:
            st.info("No bundle partners found for this product. Try a different selection.")

    st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)
    st.markdown("---")

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 2 — Association Rules Filters (just above the table)
    #   Defaults: confidence=0, lift=1, support=1 so ALL rules show on open
    # ─────────────────────────────────────────────────────────────────────────
    section_header("🔍 Filter Association Rules")

    f1, f2, f3, f4, f5 = st.columns([2, 1, 1, 1, 1])
    with f1:
        search_term = st.text_input("Search Product", "", placeholder="e.g. HDD, Camera, Cable…")
    with f2:
        min_conf = st.slider(
            "Min Confidence ⓘ",
            0.0, 1.0, 0.0, 0.01,
            help="Confidence = P(Buy B | Buy A). Higher = stronger cross-sell reliability.",
        )
    with f3:
        min_lift = st.slider(
            "Min Lift ⓘ",
            0.0, 5.0, 1.0, 0.1,
            help="Lift > 1 means meaningful affinity above random chance.",
        )
    with f4:
        min_support = st.slider(
            "Min Support ⓘ",
            1, 50, 1, 1,
            help="Support = basket count evidence. Higher = more stable rules.",
        )
    with f5:
        include_low_support = st.checkbox("Include Low Support", value=True)

    df_assoc = ai.get_associations(
        search_term=search_term,
        min_confidence=min_conf,
        min_lift=min_lift,
        min_support=min_support,
        include_low_support=include_low_support,
        limit=300,
    )

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 3 — Bundle Tables: Same-Category & Cross-Category
    # ─────────────────────────────────────────────────────────────────────────
    import pandas as pd
    engine = getattr(ai, "engine", None)
    cat_map = _fetch_category_map(engine) if engine else {}

    if not df_assoc.empty and cat_map:
        df_assoc = df_assoc.copy()
        df_assoc["cat_a"] = df_assoc["product_a"].map(cat_map).fillna("General")
        df_assoc["cat_b"] = df_assoc["product_b"].map(cat_map).fillna("General")
        df_assoc["bundle_type"] = df_assoc.apply(
            lambda r: "Same Category" if r["cat_a"] == r["cat_b"] else "Cross Category", axis=1
        )
        df_same  = df_assoc[df_assoc["bundle_type"] == "Same Category"]
        df_cross = df_assoc[df_assoc["bundle_type"] == "Cross Category"]
    else:
        df_same  = df_assoc.copy() if not df_assoc.empty else pd.DataFrame()
        df_cross = pd.DataFrame()

    _display_cols = [
        "product_a", "product_b", "times_bought_together",
        "confidence_a_to_b", "lift_a_to_b", "rule_strength",
        "expected_gain_monthly", "expected_margin_monthly",
    ]
    _col_cfg = {
        "product_a": "If they buy…", "product_b": "…pitch this",
        "times_bought_together": st.column_config.NumberColumn("Frequency"),
        "confidence_a_to_b":    st.column_config.NumberColumn("Confidence", format="%.2f"),
        "lift_a_to_b":          st.column_config.NumberColumn("Lift", format="%.2f"),
        "rule_strength":        "Rule Strength",
        "expected_gain_monthly": st.column_config.NumberColumn("₹ Gain/Month", format="₹%d"),
        "expected_margin_monthly": st.column_config.NumberColumn("₹ Margin/Month", format="₹%d"),
    }

    left = st.container()

    with left:
        section_header(f"Product Bundle Rules ({len(df_assoc)} found)")
        with st.expander("ℹ️ Metric Glossary", expanded=False):
            st.markdown(
                "- **Confidence**: P(B | A)\n- **Lift**: >1 = meaningful affinity\n"
                "- **Same Category**: both products in same category (e.g. HDD → HDD)\n"
                "- **Cross Category**: different categories (e.g. HDD → Cables)"
            )

        same_tab, cross_tab = st.tabs([
            f"🔁 Same-Category Bundles ({len(df_same)})",
            f"🔀 Cross-Category Bundles ({len(df_cross)})",
        ])

        with same_tab:
            st.caption("Depth-selling within a product family — same category on both sides.")
            if df_same.empty:
                st.info("No same-category rules with current filters.")
            else:
                st.dataframe(df_same[[c for c in _display_cols if c in df_same.columns]],
                             column_config=_col_cfg, use_container_width=True, hide_index=True)

        with cross_tab:
            st.caption("Category expansion — partner buys A, pitch them B from a different category.")
            if df_cross.empty:
                st.info("No cross-category rules with current filters.")
            else:
                st.dataframe(df_cross[[c for c in _display_cols if c in df_cross.columns]],
                             column_config=_col_cfg, use_container_width=True, hide_index=True)
    st.markdown("---")




    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 4 — Partner-First Recommendations
    # ─────────────────────────────────────────────────────────────────────────
    st.markdown("---")
    section_header("🎯 Partner Pitch Engine")
    st.caption("Select a partner to see which products the algorithm recommends pitching based on their purchase history.")


    if ai.matrix is not None and not ai.matrix.empty:
        partner_names = sorted(ai.matrix.index.tolist())
    elif ai.df_ml is not None and not ai.df_ml.empty and "company_name" in ai.df_ml.columns:
        partner_names = sorted(ai.df_ml["company_name"].dropna().astype(str).unique().tolist())
    else:
        partner_names = []

    if not partner_names:
        st.warning("No partner list available. Refresh data.")
    else:
        ph_col, top_col = st.columns([3, 1])
        with ph_col:
            selected_partner = st.selectbox("🏢 Select Partner", partner_names, key="partner_pitch_sel")
        with top_col:
            top_n = st.slider("Top Pitches", 3, 15, 8, 1, key="partner_top_n")

        # Fetch partner's actual recent products
        if engine:
            with st.spinner("Loading partner history…"):
                recent_df = _fetch_partner_recent_products(engine, selected_partner, n=20)
        else:
            import pandas as pd
            recent_df = pd.DataFrame()

        # Get algorithm recommendations
        partner_recos = ai.get_partner_bundle_recommendations(
            selected_partner,
            min_confidence=min_conf,
            min_lift=min_lift,
            min_support=min_support,
            include_low_support=include_low_support,
            top_n=top_n,
        )

        # ── Partner context strip ────────────────────────────────────────────
        if not recent_df.empty:
            last_product  = str(recent_df.iloc[0]["product_name"])
            last_date     = recent_df.iloc[0]["last_date"]
            import datetime
            days_since = (datetime.date.today() - pd.to_datetime(last_date).date()).days
            total_orders  = int(recent_df["order_count"].sum())
            top_cats      = recent_df["category"].value_counts().head(2).index.tolist()
            st.markdown(
                f"<div style='background:#0f172a;border:1px solid #1e293b;border-radius:10px;"
                f"padding:12px 18px;margin-bottom:16px;display:flex;gap:32px;align-items:center;'>"
                f"<div><div style='font-size:11px;color:#64748b;'>Last Product Ordered</div>"
                f"<div style='color:#e2e8f0;font-weight:600;'>{last_product}</div></div>"
                f"<div><div style='font-size:11px;color:#64748b;'>Days Since Last Order</div>"
                f"<div style='color:#f59e0b;font-weight:600;'>{days_since}d ago</div></div>"
                f"<div><div style='font-size:11px;color:#64748b;'>Total Lines (Last 20 Products)</div>"
                f"<div style='color:#e2e8f0;font-weight:600;'>{total_orders}</div></div>"
                f"<div><div style='font-size:11px;color:#64748b;'>Top Categories</div>"
                f"<div style='color:#38bdf8;font-weight:600;'>{' · '.join(top_cats) if top_cats else '—'}</div></div>"
                f"</div>",
                unsafe_allow_html=True,
            )
        else:
            days_since   = 30
            total_orders = 0
            last_product = ""

        if partner_recos.empty:
            st.warning("No cross-sell opportunities found for this partner with current filters.")
        else:
            # Enrich recs with category info
            if cat_map:
                partner_recos = partner_recos.copy()
                partner_recos["trigger_cat"] = partner_recos["trigger_product"].map(cat_map).fillna("General")
                partner_recos["rec_cat"]     = partner_recos["recommended_product"].map(cat_map).fillna("General")
                partner_recos["bundle_type"] = partner_recos.apply(
                    lambda r: "🔁 Same-Cat" if r["trigger_cat"] == r["rec_cat"] else "🔀 Cross-Cat", axis=1
                )

            _preco_cols = [
                "trigger_product", "recommended_product",
                "confidence", "lift", "frequency", "rule_strength",
                "expected_gain_monthly",
            ]
            if "bundle_type" in partner_recos.columns:
                _preco_cols = ["bundle_type"] + _preco_cols
            _preco_cfg = {
                "bundle_type":          "Type",
                "trigger_product":      "Bought Product",
                "recommended_product":  "Pitch This",
                "confidence":           st.column_config.NumberColumn("Conf.", format="%.2f"),
                "lift":                 st.column_config.NumberColumn("Lift", format="%.2f"),
                "frequency":            st.column_config.NumberColumn("Freq."),
                "rule_strength":        "Strength",
                "expected_gain_monthly": st.column_config.NumberColumn("₹ Gain/Mo", format="₹%d"),
            }
            st.dataframe(
                partner_recos[[c for c in _preco_cols if c in partner_recos.columns]],
                column_config=_preco_cfg,
                use_container_width=True, hide_index=True,
            )



    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 5 — Advanced Association Mining
    # ─────────────────────────────────────────────────────────────────────────
    st.markdown("---")
    section_header("Advanced Association Mining")

    if ai.strict_view_only:
        st.info("Advanced mining is disabled in STRICT_VIEW_ONLY mode.")
    else:
        adv_tab1, adv_tab2, adv_tab3 = st.tabs([
            "Enhanced Rules (FP-Growth)",
            "Sequential Patterns",
            "Cross-Category Upgrades",
        ])

        with adv_tab1:
            st.caption("FP-Growth + temporal decay mining discovers rules missed by SQL co-occurrence.")
            if st.button("Run Enhanced Mining", key="btn_enhanced"):
                with st.spinner("Mining FP-Growth + temporal decay rules..."):
                    try:
                        result = ai.get_enhanced_associations(
                            min_support=0.02,
                            min_confidence=min_conf,
                            min_lift=min_lift,
                            include_sequential=False,
                            include_cross_category=False,
                            include_temporal_decay=True,
                            top_n=50,
                        )
                        reports = result.get("reports", {})
                        total = result.get("all_rules_count", 0)
                        st.success(f"Found {total} enhanced rules.")
                        for method, rpt in reports.items():
                            status = rpt.get("status", "unknown")
                            if status == "ok":
                                st.caption(f"{method}: {rpt.get('total_rules', rpt.get('fp_rules', '?'))} rules")
                            else:
                                st.caption(f"{method}: {status} — {rpt.get('reason', '')}")
                        precs = result.get("partner_recommendations")
                        if precs is not None and not precs.empty:
                            st.write("Partner-specific enhanced recommendations:")
                            st.dataframe(precs, use_container_width=True, hide_index=True)
                    except Exception as e:
                        st.error(f"Enhanced mining error: {e}")

        with adv_tab2:
            st.caption("Finds patterns like 'Partners who buy A then buy B within N days'.")
            gap_days = st.slider("Max Gap (days)", 7, 90, 30, 7, key="seq_gap")
            seq_min_conf = st.slider("Min Confidence", 0.05, 0.50, 0.10, 0.05, key="seq_conf")
            if st.button("Mine Sequential Patterns", key="btn_seq"):
                with st.spinner("Mining sequential purchase patterns..."):
                    try:
                        seq_df, seq_report = ai.mine_sequential_patterns(
                            max_gap_days=gap_days,
                            min_confidence=seq_min_conf,
                        )
                        rpt_status = seq_report.get("status", "unknown")
                        if rpt_status == "ok" and not seq_df.empty:
                            st.success(
                                f"Found {len(seq_df)} sequential patterns "
                                f"across {seq_report.get('total_partners', '?')} partners."
                            )
                            show_cols = [c for c in [
                                "pattern", "sequence_count", "support_a",
                                "confidence_a_then_b", "lift",
                            ] if c in seq_df.columns]
                            st.dataframe(
                                seq_df[show_cols],
                                column_config={
                                    "pattern": "Pattern",
                                    "sequence_count": st.column_config.NumberColumn("Count"),
                                    "support_a": st.column_config.NumberColumn("Support A"),
                                    "confidence_a_then_b": st.column_config.NumberColumn("Confidence", format="%.2f"),
                                    "lift": st.column_config.NumberColumn("Lift", format="%.2f"),
                                },
                                use_container_width=True,
                                hide_index=True,
                            )
                            if "partner_names" in seq_df.columns:
                                st.markdown("---")
                                st.markdown("**🏢 See which partners follow a pattern:**")
                                chosen = st.selectbox("Select a pattern", seq_df["pattern"].tolist(), key="seq_pattern_picker")
                                row = seq_df[seq_df["pattern"] == chosen].iloc[0]
                                partners = [p.strip() for p in str(row.get("partner_names", "")).split(",") if p.strip()]
                                if partners:
                                    st.success(f"**{len(partners)} partner(s)** followed this sequence:")
                                    for p in partners:
                                        st.markdown(f"• {p}")
                                else:
                                    st.info("No partner names available for this pattern.")
                        else:
                            st.warning(f"No patterns found: {seq_report.get('reason', 'try lower thresholds')}")
                    except Exception as e:
                        st.error(f"Sequential mining error: {e}")

        with adv_tab3:
            st.caption("Finds patterns like 'Premium buyers in Category X expand to Category Y'.")
            cc_gap = st.slider("Category Gap (days)", 14, 120, 60, 14, key="cc_gap")
            cc_min_conf = st.slider("Min Confidence", 0.05, 0.50, 0.10, 0.05, key="cc_conf")
            if st.button("Mine Cross-Category Upgrades", key="btn_cc"):
                with st.spinner("Mining cross-category upgrade patterns..."):
                    try:
                        cc_df, cc_report = ai.mine_cross_category_upgrades(
                            gap_days=cc_gap,
                            min_confidence=cc_min_conf,
                        )
                        rpt_status = cc_report.get("status", "unknown")
                        if rpt_status == "ok" and not cc_df.empty:
                            st.success(
                                f"Found {len(cc_df)} cross-category patterns "
                                f"across {cc_report.get('total_partners', '?')} partners."
                            )
                            show_cols = [c for c in [
                                "pattern", "upgrade_count", "partners_in_x",
                                "confidence", "lift",
                            ] if c in cc_df.columns]
                            st.dataframe(
                                cc_df[show_cols],
                                column_config={
                                    "pattern": "Upgrade Pattern",
                                    "upgrade_count": st.column_config.NumberColumn("Count"),
                                    "partners_in_x": st.column_config.NumberColumn("Partners in X"),
                                    "confidence": st.column_config.NumberColumn("Confidence", format="%.2f"),
                                    "lift": st.column_config.NumberColumn("Lift", format="%.2f"),
                                },
                                use_container_width=True,
                                hide_index=True,
                            )
                            if "partner_names" in cc_df.columns:
                                st.markdown("---")
                                st.markdown("**🏢 See which partners follow a pattern:**")
                                chosen_cc = st.selectbox("Select a pattern", cc_df["pattern"].tolist(), key="cc_pattern_picker")
                                cc_row = cc_df[cc_df["pattern"] == chosen_cc].iloc[0]
                                partners_cc = [p.strip() for p in str(cc_row.get("partner_names", "")).split(",") if p.strip()]
                                if partners_cc:
                                    st.success(f"**{len(partners_cc)} partner(s)** showed this upgrade pattern:")
                                    for p in partners_cc:
                                        st.markdown(f"• {p}")
                                else:
                                    st.info("No partner names available for this pattern.")
                        else:
                            st.warning(f"No patterns found: {cc_report.get('reason', 'try lower thresholds')}")
                    except Exception as e:
                        st.error(f"Cross-category mining error: {e}")
