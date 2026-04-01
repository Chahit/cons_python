import streamlit as st
import pandas as pd
import plotly.express as px
import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from styles import apply_global_styles, section_header, page_caption, page_header, skeleton_loader


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

    f1, f2, f3, f4, f5 = st.columns([2, 1, 1, 1, 1])
    with f1:
        search_term = st.text_input("Search Product", "")
    with f2:
        min_conf = st.slider(
            "Min Confidence (i)",
            0.0,
            1.0,
            0.15,
            0.01,
            help="Confidence = P(Buy B | Buy A). Higher means stronger cross-sell reliability.",
        )
    with f3:
        min_lift = st.slider(
            "Min Lift (i)",
            0.0,
            5.0,
            1.0,
            0.1,
            help="Lift compares association against random chance. >1 means meaningful affinity.",
        )
    with f4:
        min_support = st.slider(
            "Min Support (i)",
            1,
            50,
            5,
            1,
            help="Support is basket count evidence. Higher support means more stable rules.",
        )
    with f5:
        include_low_support = st.checkbox("Include Low Support", value=False)

    df_assoc = ai.get_associations(
        search_term=search_term,
        min_confidence=min_conf,
        min_lift=min_lift,
        min_support=min_support,
        include_low_support=include_low_support,
        limit=300,
    )

    st.markdown("---")
    st.subheader("🛠️ Bundle Builder Simulator")
    st.caption("Select a base product to instantly see the best items to bundle with it.")
    
    # ── Immediate nuclear sanitisation of all numeric columns ─────────────
    # Must happen BEFORE any widget accesses df_assoc, including the Bundle Builder.
    # PostgreSQL NUMERIC/Decimal types in Arrow cause React #185 if any column
    # is passed to Streamlit widgets (including st.success, itertuples, etc.)
    if not df_assoc.empty:
        for _sc in df_assoc.columns:
            if df_assoc[_sc].dtype == object:
                df_assoc[_sc] = df_assoc[_sc].fillna("").astype(str)
            else:
                # Convert ALL numeric to Python float first — eliminates Decimal
                try:
                    df_assoc[_sc] = df_assoc[_sc].astype(float)
                except Exception:
                    df_assoc[_sc] = df_assoc[_sc].fillna("").astype(str)

    unique_products = sorted(list(set(df_assoc["product_a"].dropna().unique()) | set(df_assoc["product_b"].dropna().unique()))) if not df_assoc.empty else []
    
    base_product = st.selectbox("Select Base Product", [""] + unique_products)
    if base_product:
        bundle_options = df_assoc[df_assoc["product_a"] == base_product].sort_values("confidence_a_to_b", ascending=False).head(5)
        if not bundle_options.empty:
            b_cols = st.columns(len(bundle_options))
            for idx, row in enumerate(bundle_options.itertuples()):
                with b_cols[idx]:
                    st.success(f"**➕ {row.product_b}**\n\n*Conf: {row.confidence_a_to_b:.0%} | Lift: {row.lift_a_to_b:.1f}x*")
        else:
            st.info("No strong bundle partners found for this product.")


    st.markdown("---")




    left, right = st.columns([2, 1])
    with left:
        st.subheader(f"Association Rules ({len(df_assoc)} found)")
        with st.expander("Metric Info (i)", expanded=False):
            st.write("Confidence: Probability of B given A.")
            st.write("Lift: Strength of A->B vs random chance.")
            st.write("Support A/B: Number of baskets containing product A/B.")
            st.write("Rule Strength: High/Medium/Low quality tag using confidence + lift thresholds.")
            st.write("Low Support?: Flags rules with support below your min-support threshold.")
            st.write("Expected Gain (Weekly/Monthly/Yearly): Approx split from rule gain estimate.")
            st.write("Expected Margin: Gross profit potential; rules are ranked by margin first.")
        if df_assoc.empty:
            st.warning("No association rules match the current filters.")
        else:
            def _rs(v):
                try: return f"Rs {int(float(v)):,}"
                except Exception: return "—"
            def _pct(v):
                try: return f"{float(v):.0%}"
                except Exception: return "—"
            def _num(v, dec=2):
                try: return f"{float(v):.{dec}f}"
                except Exception: return "—"

            # Only include columns that actually exist in df_assoc
            _wanted_cols = [
                "product_a", "product_b", "times_bought_together",
                "support_a", "support_b", "confidence_a_to_b", "lift_a_to_b",
                "rule_strength", "low_support_flag",
                "expected_gain_weekly", "expected_gain_monthly", "expected_gain_yearly",
                "expected_margin_weekly", "expected_margin_monthly", "expected_margin_yearly",
                "margin_rate", "expected_revenue_gain", "expected_margin_gain",
            ]
            _avail_cols = [c for c in _wanted_cols if c in df_assoc.columns]
            disp_assoc = df_assoc[_avail_cols].copy()

            # ── Nuclear sanitisation: format every column as a plain string ──
            # This completely eliminates React #185 (caused by decimal.Decimal /
            # mixed-type Arrow columns from PostgreSQL NUMERIC fields).
            _money_set = {"expected_gain_weekly","expected_gain_monthly","expected_gain_yearly",
                          "expected_margin_weekly","expected_margin_monthly","expected_margin_yearly",
                          "expected_revenue_gain","expected_margin_gain"}
            _pct_set   = {"confidence_a_to_b", "support_a", "support_b", "margin_rate"}
            _num_set   = {"lift_a_to_b", "times_bought_together"}
            for _c in disp_assoc.columns:
                if _c in _money_set:
                    disp_assoc[_c] = disp_assoc[_c].apply(_rs)
                elif _c in _pct_set:
                    disp_assoc[_c] = disp_assoc[_c].apply(_pct)
                elif _c in _num_set:
                    disp_assoc[_c] = disp_assoc[_c].apply(lambda v: _num(v, 0))
                else:
                    disp_assoc[_c] = disp_assoc[_c].fillna("").astype(str).replace("nan","").replace("None","")

            # Rename for display
            _rename = {
                "product_a":"If they buy...", "product_b":"...pitch this",
                "times_bought_together":"Frequency",
                "support_a":"Support A", "support_b":"Support B",
                "confidence_a_to_b":"Confidence", "lift_a_to_b":"Lift",
                "rule_strength":"Rule Strength", "low_support_flag":"Low Support?",
                "expected_gain_weekly":"Gain Weekly","expected_gain_monthly":"Gain Monthly",
                "expected_gain_yearly":"Gain Yearly",
                "expected_margin_weekly":"Margin Weekly","expected_margin_monthly":"Margin Monthly",
                "expected_margin_yearly":"Margin Yearly",
                "margin_rate":"Margin Rate",
                "expected_revenue_gain":"Gain Base","expected_margin_gain":"Margin Base",
            }
            disp_assoc = disp_assoc.rename(columns={k:v for k,v in _rename.items() if k in disp_assoc.columns})

            # Render — no column_config, all columns are already plain strings
            st.dataframe(disp_assoc, use_container_width=True, hide_index=True)

    with right:
        st.markdown("**📞 Sales Script**")
        if not df_assoc.empty:
            # Use the top rule for the script
            top_row = df_assoc.iloc[0]
            prod_a = str(top_row.get("product_a", "Product A"))
            prod_b = str(top_row.get("product_b", "Product B"))
            conf = float(top_row.get("confidence_a_to_b", 0))
            lift = float(top_row.get("lift_a_to_b", 0))
            # Safe extraction: gain_m might be a pre-formatted string like "Rs 1,234"
            _raw_gain = top_row.get("expected_gain_monthly", 0)
            try:
                gain_m = float(str(_raw_gain).replace("Rs", "").replace(",", "").strip())
            except Exception:
                gain_m = 0

            # Confidence indicator
            if conf >= 0.6:
                conf_label, conf_hex = "High Confidence", "34d96f"
            elif conf >= 0.3:
                conf_label, conf_hex = "Medium Confidence", "f5c842"
            else:
                conf_label, conf_hex = "Low Confidence", "888888"
            st.markdown(
                f"<span style='font-size:11px;color:#{conf_hex};'>"
                f"● {conf_label} — {conf:.0%} confidence, {lift:.1f}x lift</span>",
                unsafe_allow_html=True,
            )

            st.markdown("---")
            st.markdown("**Opening:**")
            st.info(
                f"\"We noticed you regularly order **{prod_a}**. "
                f"Most of our partners who buy this also pick up **{prod_b}** at the same time — "
                f"shall I add it to today's order?\""
            )
            st.markdown("**Follow-up (if hesitant):**")
            st.info(
                f"\"It's a popular combination — about {conf:.0%} of "
                f"{prod_a} buyers also take {prod_b}. "
                f"We have stock ready and can deliver together.\""
            )
            st.markdown("**Value pitch:**")
            st.info(
                f"\"Bundling both saves a delivery, and cross-selling this pair typically "
                f"adds Rs {int(gain_m):,}/month in business value.\""
            )

            if gain_m:
                st.caption(f"Est. monthly gain from this rule: Rs {int(gain_m):,}")
        else:
            st.info("Select a rule from the table to generate a sales script.")



    st.subheader("Partner-Specific Recommendations")

    if ai.strict_view_only:
        st.info(
            "STRICT_VIEW_ONLY is ON. Partner-specific recommendations use view-backed history."
        )

    if ai.matrix is not None and not ai.matrix.empty:
        partner_names = sorted(ai.matrix.index.tolist())
    elif ai.df_ml is not None and not ai.df_ml.empty and "company_name" in ai.df_ml.columns:
        partner_names = sorted(ai.df_ml["company_name"].dropna().astype(str).unique().tolist())
    else:
        partner_names = []
    if not partner_names:
        st.warning("No partner list available. Refresh data.")
        return

    selected_partner = st.selectbox("Select Partner", partner_names)
    top_n = st.slider("Recommendations to Show", 3, 20, 10, 1)

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
        def _rs2(v):
            try: return f"Rs {int(float(v)):,}"
            except Exception: return "—"
        def _pct2(v):
            try: return f"{float(v):.0%}"
            except Exception: return "—"
        def _num2(v, dec=2):
            try: return f"{float(v):.{dec}f}"
            except Exception: return "—"

        pr_disp = partner_recos.copy()
        # Nuclear sanitisation: format every column to plain string
        _money_set2 = {"expected_gain_weekly","expected_gain_monthly","expected_gain_yearly",
                       "expected_margin_weekly","expected_margin_monthly","expected_margin_yearly",
                       "expected_revenue_gain","expected_margin_gain"}
        _pct_set2   = {"confidence", "support_a", "support_b", "margin_rate"}
        _num_set2   = {"lift", "frequency"}
        for _c2 in pr_disp.columns:
            if _c2 in _money_set2:
                pr_disp[_c2] = pr_disp[_c2].apply(_rs2)
            elif _c2 in _pct_set2:
                pr_disp[_c2] = pr_disp[_c2].apply(_pct2)
            elif _c2 in _num_set2:
                pr_disp[_c2] = pr_disp[_c2].apply(lambda v: _num2(v, 1))
            else:
                pr_disp[_c2] = pr_disp[_c2].fillna("").astype(str).replace("nan","").replace("None","")

        _rename2 = {
            "trigger_product":"Bought Product","recommended_product":"Recommended Product",
            "confidence":"Confidence","lift":"Lift","frequency":"Frequency",
            "rule_strength":"Rule Strength","low_support_flag":"Low Support?",
            "expected_gain_weekly":"Gain Weekly","expected_gain_monthly":"Gain Monthly",
            "expected_gain_yearly":"Gain Yearly",
            "expected_margin_weekly":"Margin Weekly","expected_margin_monthly":"Margin Monthly",
            "expected_margin_yearly":"Margin Yearly",
            "margin_rate":"Margin Rate","expected_revenue_gain":"Gain Base","expected_margin_gain":"Margin Base",
        }
        pr_disp = pr_disp.rename(columns={k:v for k,v in _rename2.items() if k in pr_disp.columns})
        st.dataframe(pr_disp, use_container_width=True, hide_index=True)

    # ======================================================================
    # Enhanced Association Mining (FP-Growth, Sequential, Cross-Category)
    # ======================================================================
    st.markdown("---")
    st.subheader("Advanced Association Mining")

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
                            seq_disp = seq_df[show_cols].copy()
                            for _sc in ["sequence_count", "support_a"]:
                                if _sc in seq_disp.columns:
                                    seq_disp[_sc] = seq_disp[_sc].apply(lambda v: str(int(float(v))) if v==v else "0")
                            if "confidence_a_then_b" in seq_disp.columns:
                                seq_disp["confidence_a_then_b"] = seq_disp["confidence_a_then_b"].apply(lambda v: f"{float(v):.2f}" if v==v else "—")
                            if "lift" in seq_disp.columns:
                                seq_disp["lift"] = seq_disp["lift"].apply(lambda v: f"{float(v):.2f}" if v==v else "—")
                            for _sc2 in seq_disp.select_dtypes(include=["object"]).columns:
                                seq_disp[_sc2] = seq_disp[_sc2].fillna("").astype(str)
                            seq_disp = seq_disp.rename(columns={"pattern":"Pattern","sequence_count":"Count","support_a":"Support A","confidence_a_then_b":"Confidence","lift":"Lift"})
                            st.dataframe(seq_disp, use_container_width=True, hide_index=True)
                            # Show partner names for a selected pattern
                            if "partner_names" in seq_df.columns:
                                st.markdown("---")
                                st.markdown("**🏢 See which partners follow a pattern:**")
                                chosen = st.selectbox(
                                    "Select a pattern",
                                    seq_df["pattern"].tolist(),
                                    key="seq_pattern_picker"
                                )
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
                            cc_disp = cc_df[show_cols].copy()
                            for _cc in ["upgrade_count", "partners_in_x"]:
                                if _cc in cc_disp.columns:
                                    cc_disp[_cc] = cc_disp[_cc].apply(lambda v: str(int(float(v))) if v==v else "0")
                            if "confidence" in cc_disp.columns:
                                cc_disp["confidence"] = cc_disp["confidence"].apply(lambda v: f"{float(v):.2f}" if v==v else "—")
                            if "lift" in cc_disp.columns:
                                cc_disp["lift"] = cc_disp["lift"].apply(lambda v: f"{float(v):.2f}" if v==v else "—")
                            for _cc2 in cc_disp.select_dtypes(include=["object"]).columns:
                                cc_disp[_cc2] = cc_disp[_cc2].fillna("").astype(str)
                            cc_disp = cc_disp.rename(columns={"pattern":"Upgrade Pattern","upgrade_count":"Count","partners_in_x":"Partners in X","confidence":"Confidence","lift":"Lift"})
                            st.dataframe(cc_disp, use_container_width=True, hide_index=True)
                            # Show partner names for a selected cross-category pattern
                            if "partner_names" in cc_df.columns:
                                st.markdown("---")
                                st.markdown("**🏢 See which partners follow a pattern:**")
                                chosen_cc = st.selectbox(
                                    "Select a pattern",
                                    cc_df["pattern"].tolist(),
                                    key="cc_pattern_picker"
                                )
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
