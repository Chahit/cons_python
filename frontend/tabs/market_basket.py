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
    # SECTION 3 — Association Rules Table + Dynamic Sales Script (side-by-side)
    # ─────────────────────────────────────────────────────────────────────────
    left, right = st.columns([2, 1])

    with left:
        section_header(f"Association Rules ({len(df_assoc)} found)")

        with st.expander("ℹ️ Metric Glossary", expanded=False):
            st.markdown(
                "- **Confidence**: P(B | A) — how reliably B is bought when A is bought\n"
                "- **Lift**: strength of A→B vs random chance (>1 = meaningful)\n"
                "- **Frequency**: number of baskets containing both A and B\n"
                "- **Rule Strength**: High / Medium / Low quality tag\n"
                "- **₹ Gain/Month**: estimated monthly revenue lift from this rule"
            )

        if df_assoc.empty:
            st.warning("No association rules match the current filters. Try lowering the thresholds.")
        else:
            _display_cols = [
                "product_a", "product_b", "times_bought_together",
                "confidence_a_to_b", "lift_a_to_b", "rule_strength",
                "expected_gain_monthly", "expected_margin_monthly",
            ]
            _col_cfg = {
                "product_a": "If they buy…",
                "product_b": "…pitch this",
                "times_bought_together": st.column_config.NumberColumn("Frequency"),
                "confidence_a_to_b": st.column_config.NumberColumn("Confidence", format="%.2f"),
                "lift_a_to_b": st.column_config.NumberColumn("Lift", format="%.2f"),
                "rule_strength": "Rule Strength",
                "expected_gain_monthly": st.column_config.NumberColumn("₹ Gain/Month", format="₹%d"),
                "expected_margin_monthly": st.column_config.NumberColumn("₹ Margin/Month", format="₹%d"),
            }
            st.dataframe(
                df_assoc[[c for c in _display_cols if c in df_assoc.columns]],
                column_config=_col_cfg,
                use_container_width=True,
                hide_index=True,
            )

    # ─────────────────────────────────────────────────────────────────────────
    # Dynamic Sales Script — right panel
    # ─────────────────────────────────────────────────────────────────────────
    with right:
        st.markdown(
            "<div style='background:#0f172a;border:1px solid #1e293b;border-radius:14px;padding:14px 16px;'>"
            "<span style='font-size:14px;font-weight:800;color:#f0f4ff;'>\U0001f4de Sales Script</span>"
            "</div>",
            unsafe_allow_html=True,
        )

        if not df_assoc.empty:
            # ── Rule selector: build label list from the filtered table
            rule_labels = [
                f"{r['product_a']}  →  {r['product_b']}"
                for _, r in df_assoc.iterrows()
            ]
            selected_label = st.selectbox(
                "Select rule to script",
                options=rule_labels,
                index=0,
                key="sales_script_rule_selector",
                help="Choose any association rule from the table — the script updates instantly.",
            )
            selected_idx = rule_labels.index(selected_label)
            top = df_assoc.iloc[selected_idx]

            prod_a  = str(top.get("product_a", "Product A"))
            prod_b  = str(top.get("product_b", "Product B"))
            conf    = float(top.get("confidence_a_to_b", 0) or 0)
            lift    = float(top.get("lift_a_to_b", 0) or 0)
            supp_a  = int(top.get("support_a", 0) or 0)
            supp_b  = int(top.get("support_b", 0) or 0)
            freq    = int(top.get("times_bought_together", 0) or 0)
            gain_m  = float(top.get("expected_gain_monthly", 0) or 0)
            gain_y  = float(top.get("expected_gain_yearly", 0) or 0)
            margin_m = float(top.get("expected_margin_monthly", 0) or 0)
            strength = str(top.get("rule_strength", "Medium") or "Medium")

            # ── Confidence badge
            if conf >= 0.6:
                badge_color, badge_label = "#10b981", "🟢 High Confidence"
            elif conf >= 0.3:
                badge_color, badge_label = "#f59e0b", "🟡 Medium Confidence"
            else:
                badge_color, badge_label = "#64748b", "⚪ Low Confidence"

            st.markdown(
                f"<div style='font-size:11px;color:{badge_color};font-weight:600;"
                f"margin-bottom:10px;'>{badge_label} — {conf:.0%} conf · {lift:.1f}x lift · "
                f"{strength}</div>",
                unsafe_allow_html=True,
            )

            # ── Dynamic Opening Line
            if conf >= 0.7:
                opening = (
                    f"\"Every time we see a partner ordering {prod_a}, they almost always "
                    f"need {prod_b} within the same cycle. I'd like to add it to today's order for you — "
                    f"shall I confirm both?\""
                )
                followup = (
                    f"\"This isn't a guess — {conf:.0%} of partners who buy {prod_a} take "
                    f"{prod_b}. That's {freq} transactions in our data backing this up.\""
                )
            elif conf >= 0.4:
                opening = (
                    f"\"We've noticed that many partners who stock {prod_a} also pick up "
                    f"{prod_b} at the same time. It's a combination that moves well together — "
                    f"have you considered adding it to this order?\""
                )
                followup = (
                    f"\"About {conf:.0%} of {prod_a} buyers also take {prod_b}. "
                    f"We've seen this pattern {freq} times across our partner network.\""
                )
            else:
                opening = (
                    f"\"While you're placing an order for {prod_a}, I wanted to flag that "
                    f"{prod_b} is often complementary — some of our partners find it useful "
                    f"to bundle both in a single delivery.\""
                )
                followup = (
                    f"\"It reduces your logistics overhead and we've seen this combination "
                    f"work well across {freq} orders in our network.\""
                )

            # ── Dynamic Value Pitch
            if gain_m >= 1_00_000:
                value_pitch = (
                    f"\"Bundling this pair adds roughly {_inr(gain_m)} per month in revenue — "
                    f"that's {_inr(gain_y)} annually. The margin contribution is {_inr(margin_m)}/month. "
                    f"It's one of the cleanest cross-sell wins in your category right now.\""
                )
            elif gain_m >= 10_000:
                value_pitch = (
                    f"\"Cross-selling {prod_b} alongside {prod_a} typically generates an extra "
                    f"{_inr(gain_m)}/month. Over a year that's {_inr(gain_y)} in incremental revenue "
                    f"with {_inr(margin_m)}/month in margin.\""
                )
            else:
                value_pitch = (
                    f"\"Even a small uplift from bundling {prod_b} with {prod_a} can add "
                    f"{_inr(gain_m)}/month incrementally — it consolidates a delivery and gives "
                    f"your customer a more complete solution.\""
                )

            # ── Objection handler
            if lift >= 3.0:
                objection = (
                    f"\"The data is actually quite clear — partners who buy {prod_a} are "
                    f"{lift:.1f}x more likely than average to also need {prod_b}. "
                    f"This isn't a speculative pitch, it's a pattern we see reliably.\""
                )
            elif lift >= 1.5:
                objection = (
                    f"\"The affinity between these two products is {lift:.1f}x above baseline — "
                    f"meaning this is a real buying signal, not just random co-purchase.\""
                )
            else:
                objection = (
                    f"\"Even at a {lift:.1f}x lift, this pairing has appeared {freq} times in "
                    f"real orders. It's worth trialling — we can always adjust next cycle.\""
                )

            # ── Render script blocks
            blocks = [
                ("Opening:", opening),
                ("Follow-up (if hesitant):", followup),
                ("Value Pitch:", value_pitch),
                ("Handle Objection:", objection),
            ]

            for label, text in blocks:
                st.markdown(
                    f"<div style='font-size:11px;font-weight:700;color:#94a3b8;"
                    f"text-transform:uppercase;letter-spacing:0.07em;margin-top:12px;'>"
                    f"{label}</div>",
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f"<div style='background:#1e293b;border-left:3px solid #3b82f6;"
                    f"border-radius:0 8px 8px 0;padding:10px 14px;font-size:13px;"
                    f"color:#e2e8f0;line-height:1.7;margin-top:4px;font-style:italic;'>"
                    f"{text}</div>",
                    unsafe_allow_html=True,
                )

            # ── Stats summary row (st.columns avoids unclosed-div React #185 crash)
            st.markdown("<hr style='border-color:#1e293b;margin:14px 0 8px 0;'>", unsafe_allow_html=True)
            s1, s2, s3, s4 = st.columns(4)
            s1.metric("Frequency", str(freq))
            s2.metric("Support A", str(supp_a))
            s3.metric("Support B", str(supp_b))
            s4.metric("Gain/yr", _inr(gain_y))


            # ── Copy button — builds a plain-text version of the script
            full_script = (
                f"CROSS-SELL SCRIPT: {prod_a} → {prod_b}\n"
                f"{'='*55}\n"
                f"Rule: {prod_a} → {prod_b}\n"
                f"Confidence: {conf:.0%} | Lift: {lift:.1f}x | Frequency: {freq} | Strength: {strength}\n"
                f"Est. Monthly Gain: {_inr(gain_m)} | Annual: {_inr(gain_y)} | Margin/mo: {_inr(margin_m)}\n"
                f"\n--- OPENING ---\n{opening}\n"
                f"\n--- FOLLOW-UP ---\n{followup}\n"
                f"\n--- VALUE PITCH ---\n{value_pitch}\n"
                f"\n--- OBJECTION HANDLER ---\n{objection}\n"
            )
            st.markdown("<div style='margin-top:14px;'></div>", unsafe_allow_html=True)
            with st.expander("📋 Copy Full Script"):
                st.code(full_script, language=None)
                st.caption("Click the copy icon (top-right of the code block) to copy.")

        else:
            st.info("Sales script will appear here once association rules are loaded.")

    st.markdown("---")

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 4 — Partner-Specific Recommendations
    # ─────────────────────────────────────────────────────────────────────────
    section_header("Partner-Specific Recommendations")

    if ai.strict_view_only:
        st.info("STRICT_VIEW_ONLY is ON. Partner-specific recommendations use view-backed history.")

    if ai.matrix is not None and not ai.matrix.empty:
        partner_names = sorted(ai.matrix.index.tolist())
    elif ai.df_ml is not None and not ai.df_ml.empty and "company_name" in ai.df_ml.columns:
        partner_names = sorted(ai.df_ml["company_name"].dropna().astype(str).unique().tolist())
    else:
        partner_names = []

    if not partner_names:
        st.warning("No partner list available. Refresh data.")
        return

    pc1, pc2 = st.columns([3, 1])
    with pc1:
        selected_partner = st.selectbox("Select Partner", partner_names)
    with pc2:
        top_n = st.slider("Recommendations", 3, 20, 10, 1)

    partner_recos = ai.get_partner_bundle_recommendations(
        selected_partner,
        min_confidence=min_conf,
        min_lift=min_lift,
        min_support=min_support,
        include_low_support=include_low_support,
        top_n=top_n,
    )

    if partner_recos.empty:
        st.warning("No cross-sell opportunities found for this partner with current filters.")
    else:
        _preco_cols = [
            "trigger_product", "recommended_product",
            "confidence", "lift", "frequency", "rule_strength",
            "expected_gain_monthly", "expected_margin_monthly",
        ]
        _preco_cfg = {
            "trigger_product":        "Bought Product",
            "recommended_product":    "Recommended Product",
            "confidence":             st.column_config.NumberColumn("Confidence", format="%.2f"),
            "lift":                   st.column_config.NumberColumn("Lift", format="%.2f"),
            "frequency":              st.column_config.NumberColumn("Frequency"),
            "rule_strength":          "Rule Strength",
            "expected_gain_monthly":  st.column_config.NumberColumn("₹ Gain/Mo", format="₹%d"),
            "expected_margin_monthly":st.column_config.NumberColumn("₹ Margin/Mo", format="₹%d"),
        }
        st.dataframe(
            partner_recos[[c for c in _preco_cols if c in partner_recos.columns]],
            column_config=_preco_cfg,
            use_container_width=True,
            hide_index=True,
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
