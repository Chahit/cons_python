import pandas as pd
import streamlit as st

import sys, os, re
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from ml_engine.services.export_service import (
    export_recommendation_plan_pdf,
    export_recommendation_plan_excel,
)
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from styles import apply_global_styles, section_header, page_caption, banner, page_header, skeleton_loader


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
    tab_rec, tab_nl, tab_adv = st.tabs(["📋 Recommendations", "🔍 NL Query", "⚙️ Advanced"])

    # ── Tab 2: NL Query ───────────────────────────────────────────────────────
    with tab_nl:
        section_header("Natural Language Query over Recommendations")
        st.caption("Example: Show high-margin recommendations for low-credit-risk VIPs in Delhi.")
        nq1, nq2 = st.columns([2, 1])
        with nq1:
            nl_query = st.text_input(
                "Ask in plain language",
                value="",
                placeholder="Show high-margin recommendations for low-credit-risk VIPs in Delhi",
                key="nl_query_input",
            )
        with nq2:
            nl_scope = st.selectbox(
                "Search Scope",
                ["Selected State", "All States"],
                index=0,
                key="nl_scope",
            )
        nq3, nq4, nq5 = st.columns(3)
        with nq3:
            nl_top_n = st.slider("NL Query Top N", 5, 100, 20, 5)
        with nq4:
            st.markdown("<br>", unsafe_allow_html=True)
            advanced_filters = st.checkbox("Show Advanced Filters")
        with nq5:
            st.write("")
            st.write("")
            nl_run = st.button("Run NL Query", use_container_width=True, key="nl_run_btn")
            if nl_run:
                st.session_state["_nl_run_triggered"] = True
            
        if advanced_filters:
            af1, af2 = st.columns(2)
            with af1:
                min_conf = st.slider("Min Confidence Threshold", 0.0, 1.0, 0.15, 0.05)
            with af2:
                min_lift = st.slider("Min Lift Threshold", 1.0, 5.0, 1.0, 0.5)
    # ── Tab 3: Advanced ───────────────────────────────────────────────────────
    with tab_adv:
        model_name_adv = str(getattr(ai, "gemini_model", "gemini-1.5-flash"))
        key_adv = str(getattr(ai, "gemini_api_key", "")).strip()
        if key_adv:
            st.caption(f"Gemini Model: {model_name_adv} (enabled via environment)")
        else:
            st.info("GEMINI_API_KEY not configured. Enhanced AI narrative unavailable, but all deterministic logic still runs.")

    # ── Tab 1: Recommendations ────────────────────────────────────────────────
    with tab_rec:
        model_name = str(getattr(ai, "gemini_model", "gemini-1.5-flash"))
        model_fallbacks = str(getattr(ai, "gemini_model_fallbacks", "") or "").strip()
        key = str(getattr(ai, "gemini_api_key", "")).strip()
        nl_query = st.session_state.get("nl_query_input", "")
        # Critical fix: read nl_run from session_state (set by NL tab button).
        # Setting nl_run = False here was overwriting the True value from the button click.
        nl_run = st.session_state.pop("_nl_run_triggered", False)


    if nl_run and str(nl_query).strip():
        nl_result = ai.query_recommendations_nl(
            query=nl_query,
            state_scope=selected_state if nl_scope == "Selected State" else None,
            top_n=int(nl_top_n),
            use_genai=True,
            api_key=key if key else None,
            model=model_name,
        )
        if not nl_result or nl_result.get("status") != "ok":
            st.error(
                nl_result.get("reason", "Query execution failed.")
                if isinstance(nl_result, dict)
                else "Query execution failed."
            )
        else:
            parser = nl_result.get("parser", {}) or {}
            filters = nl_result.get("filters", {}) or {}
            st.info(
                f"Matched {int(nl_result.get('total_matches', 0))} recommendation rows "
                f"(showing top {int(filters.get('top_n', nl_top_n))}); "
                f"scanned {int(nl_result.get('scanned_partners', 0))} of "
                f"{int(nl_result.get('candidate_partners', 0))} candidate partners. "
                f"Parser: {parser.get('mode', 'heuristic')}."
            )
            if parser.get("genai_error"):
                st.warning(parser.get("genai_error"))
            with st.expander("Structured Filters Used", expanded=False):
                st.json(filters)

            nl_df = nl_result.get("results", pd.DataFrame())
            if isinstance(nl_df, pd.DataFrame) and not nl_df.empty:
                cols = [
                    "partner_name",
                    "state",
                    "cluster_label",
                    "cluster_type",
                    "health_segment",
                    "action_type",
                    "recommended_offer",
                    "priority_score",
                    "margin_rate",
                    "safe_discount_pct",
                    "churn_probability",
                    "credit_risk_score",
                ]
                show = [c for c in cols if c in nl_df.columns]
                st.dataframe(
                    nl_df[show],
                    column_config={
                        "priority_score": st.column_config.NumberColumn("Priority", format="%.2f"),
                        "margin_rate": st.column_config.NumberColumn("Margin Rate", format="%.2f"),
                        "safe_discount_pct": st.column_config.NumberColumn("Safe Discount %", format="%.1f"),
                        "churn_probability": st.column_config.NumberColumn("Churn", format="%.3f"),
                        "credit_risk_score": st.column_config.NumberColumn("Credit Risk", format="%.3f"),
                    },
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.warning("No recommendations matched the requested filters.")

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
    st.subheader("Top Recommended Actions")
    if not actions:
        st.warning("No recommendations generated.")
    else:
        df = pd.DataFrame(actions)
        
        # Category / Action Type Filter
        available_types = sorted([str(x) for x in df["action_type"].unique() if pd.notna(x)])
        selected_types = st.multiselect("Filter by Category / Action", available_types, default=available_types)
        
        if selected_types:
            df = df[df["action_type"].isin(selected_types)]
            
        if df.empty:
            st.info("No recommendations match the selected filters.")
        else:
            # Polished Native Table View
            def clean_html(text):
                if not text: return ""
                return re.sub('<[^<]+?>', '', str(text)).strip()

            df_display = df.copy()
            
            # Map icons for a premium look
            icon_map = {
                "up-sell": "📈", "cross-sell": "🛒", "rescue": "🚨", "retention": "🔄", "affinity": "📦"
            }
            
            df_display["Type"] = df_display["action_type"].apply(lambda x: f"{icon_map.get(next((k for k in icon_map if k in str(x).lower()), ''), '📦')} {str(x).upper()}")
            df_display["Recommendation"] = df_display["recommended_offer"]
            df_display["Logic"] = df_display["why_relevant"].apply(clean_html)
            df_display["Execution"] = df_display["suggested_sequence"].apply(clean_html)
            df_display["Priority"] = df_display["priority_score"]
            
            # Show the table
            st.dataframe(
                df_display[["Priority", "Type", "Recommendation", "Logic", "Execution"]].sort_values("Priority", ascending=False),
                column_config={
                    "Priority": st.column_config.ProgressColumn("Confidence", min_value=0, max_value=100, format="%.0f"),
                    "Type": st.column_config.TextColumn("Category", width="small"),
                    "Recommendation": st.column_config.TextColumn("Offer", width="medium"),
                    "Logic": st.column_config.TextColumn("Why This?", width="large"),
                    "Execution": st.column_config.TextColumn("Next Step", width="medium"),
                },
                use_container_width=True,
                hide_index=True,
            )
            st.markdown("---")

    # ======================================================================
    # FP-Growth Predictive Bundles
    # ======================================================================
    st.subheader("Predictive Bundles (FP-Growth)")
    bundles = ai.get_partner_bundle_recommendations(partner_name=selected_partner, top_n=5)
    if not bundles.empty:
        st.caption("Frequently bought together by similar buyers:")
        b_cols = st.columns(len(bundles))
        for idx, row in enumerate(bundles.itertuples()):
            if idx < len(b_cols):
                with b_cols[idx]:
                    st.info(f"**{row.trigger_product}** \n\n ➕ {row.recommended_product}\n\n*Confidence: {row.confidence:.0%}*")
    else:
        st.info("No strong predictive bundles found for this partner's purchase history.")


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
    st.subheader("Auto-generated Pitch Scripts")
    if not actions:
        st.info("Generate recommendations first to create pitch drafts.")
    else:
        seq_options = [int(a.get("sequence", i + 1)) for i, a in enumerate(actions)]
        selected_seq = st.selectbox("Pick Recommendation Sequence", seq_options, index=0)
        tone = st.selectbox("Tone", ["formal", "friendly", "urgent"], index=0)

        script_pack = ai.get_partner_pitch_scripts(
            partner_name=selected_partner,
            action_sequence=int(selected_seq),
            tone=tone,
            use_genai=True,
            api_key=key if key else None,
            model=model_name,
        )
        if not script_pack or script_pack.get("status") != "ok":
            st.warning(
                script_pack.get("reason", "Pitch script generation unavailable.")
                if isinstance(script_pack, dict)
                else "Pitch script generation unavailable."
            )
        else:
            pricing = script_pack.get("pricing", {}) or {}
            p1, p2, p3 = st.columns(3)
            with p1:
                st.metric("Offer", str(pricing.get("offer_name", "Recommended Offer")))
            with p2:
                unit_price = pricing.get("unit_price", None)
                if unit_price is not None and pd.notna(unit_price):
                    st.metric("Indicative Price", f"Rs {int(float(unit_price)):,}")
                else:
                    st.metric("Indicative Price", "Rate Card")
            with p3:
                st.metric(
                    "Margin-safe Offer",
                    f"{float(pricing.get('safe_discount_pct', 0.0)):.0f}% off",
                )

            scripts = script_pack.get("scripts", {}) or {}
            st.text_area(
                "WhatsApp Draft",
                value=str(scripts.get("whatsapp", "")),
                height=170,
            )
            st.text_input(
                "Email Subject",
                value=str(scripts.get("email_subject", "")),
            )
            st.text_area(
                "Email Body",
                value=str(scripts.get("email_body", "")),
                height=230,
            )


        st.markdown("---")
        st.subheader("Follow-up Message Generator")
        st.caption(
            "If no conversion in X days, generate revised follow-up with alternate bundle or smaller trial quantity."
        )
        c1, c2, c3 = st.columns(3)
        with c1:
            no_conversion_days = st.number_input(
                "No Conversion Days",
                min_value=1,
                max_value=90,
                value=7,
                step=1,
            )
        with c2:
            trial_qty = st.number_input(
                "Trial Quantity",
                min_value=1,
                max_value=500,
                value=5,
                step=1,
            )
        with c3:
            followup_tone = st.selectbox("Follow-up Tone", ["formal", "friendly", "urgent"], index=0)

        followup_pack = ai.get_partner_followup_scripts(
            partner_name=selected_partner,
            action_sequence=int(selected_seq),
            tone=followup_tone,
            no_conversion_days=int(no_conversion_days),
            trial_qty=int(trial_qty),
            use_genai=True,
            api_key=key if key else None,
            model=model_name,
        )

        if not followup_pack or followup_pack.get("status") != "ok":
            st.warning(
                followup_pack.get("reason", "Follow-up generation unavailable.")
                if isinstance(followup_pack, dict)
                else "Follow-up generation unavailable."
            )
        else:
            f1, f2, f3 = st.columns(3)
            with f1:
                st.metric("No Conversion Window", f"{int(no_conversion_days)} day(s)")
            with f2:
                st.metric("Trial Quantity", str(int(trial_qty)))
            with f3:
                alt_offer = str(followup_pack.get("alternate_offer", "") or "").strip()
                if alt_offer:
                    st.metric("Alternate Bundle", alt_offer)
                else:
                    st.metric("Alternate Bundle", "Fallback: smaller trial")

            followup = followup_pack.get("followup", {}) or {}
            st.text_area(
                "WhatsApp Follow-up",
                value=str(followup.get("whatsapp_followup", "")),
                height=180,
            )
            st.text_input(
                "Follow-up Email Subject",
                value=str(followup.get("email_subject_followup", "")),
            )
            st.text_area(
                "Follow-up Email Body",
                value=str(followup.get("email_body_followup", "")),
                height=240,
            )



