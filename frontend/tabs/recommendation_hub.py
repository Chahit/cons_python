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
    # ── Resolve AI keys FIRST (must be outside any tab context) ──────────────
    model_name = str(getattr(ai, "openai_model", "gpt-4o-mini"))
    key = str(getattr(ai, "openai_api_key", "")).strip()

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


    plan = ai.get_partner_recommendation_plan(
        partner_name=selected_partner,
        top_n=int(top_n),
        use_genai=True,
        api_key=key if key else None,
        model=model_name,
    )

    if not plan or plan.get("status") != "ok":
        st.error(plan.get("reason", "Recommendation plan unavailable.") if isinstance(plan, dict) else "Recommendation plan unavailable.")
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

            icon_map = {
                "up-sell": "📈", "cross-sell": "🛒", "rescue": "🚨",
                "retention": "🔄", "affinity": "📦", "strategic": "♟️",
                "alert": "⚠️", "nurture": "🌱", "credit": "🔒",
            }

            df_display["Type"] = df_display["action_type"].apply(
                lambda x: f"{icon_map.get(next((k for k in icon_map if k in str(x).lower()), ''), '📦')} {str(x).upper()}"
            )
            df_display["Offer"]     = df_display["recommended_offer"]
            df_display["Why?"]      = df_display["why_relevant"].apply(clean_html)
            df_display["Next Step"] = df_display["suggested_sequence"].apply(clean_html)

            # Roadmap 4.1 — Confidence + Similar Partners + Expected Uplift
            df_display["Confidence"] = df_display["confidence_pct"].apply(
                lambda v: f"{float(v):.0f}%" if pd.notna(v) else "—"
            ) if "confidence_pct" in df_display.columns else "—"
            df_display["Based On"] = df_display["similar_partners_count"].apply(
                lambda v: f"{int(float(v))} peers" if pd.notna(v) else "—"
            ) if "similar_partners_count" in df_display.columns else "—"
            df_display["Est. Uplift/mo"] = df_display["expected_uplift_monthly"].apply(
                lambda v: f"Rs {int(float(v)):,}" if pd.notna(v) and float(v) > 0 else "—"
            ) if "expected_uplift_monthly" in df_display.columns else "—"

            # Display top action confidence badges prominently
            top_action = df_display.iloc[0] if not df_display.empty else None
            if top_action is not None:
                b1, b2, b3 = st.columns(3)
                with b1:
                    st.markdown(
                        f"<div style='background:#1e3a5f;border-radius:10px;padding:10px 14px;text-align:center;'>"
                        f"<div style='color:#93c5fd;font-size:0.75em;letter-spacing:1px;'>CONFIDENCE</div>"
                        f"<div style='color:#eff6ff;font-size:1.6em;font-weight:700;'>{top_action.get('Confidence','—')}</div>"
                        f"</div>", unsafe_allow_html=True,
                    )
                with b2:
                    st.markdown(
                        f"<div style='background:#1a3a2f;border-radius:10px;padding:10px 14px;text-align:center;'>"
                        f"<div style='color:#6ee7b7;font-size:0.75em;letter-spacing:1px;'>BASED ON</div>"
                        f"<div style='color:#ecfdf5;font-size:1.6em;font-weight:700;'>{top_action.get('Based On','—')}</div>"
                        f"</div>", unsafe_allow_html=True,
                    )
                with b3:
                    st.markdown(
                        f"<div style='background:#3b1f00;border-radius:10px;padding:10px 14px;text-align:center;'>"
                        f"<div style='color:#fcd34d;font-size:0.75em;letter-spacing:1px;'>EXPECTED UPLIFT/MONTH</div>"
                        f"<div style='color:#fffbeb;font-size:1.6em;font-weight:700;'>{top_action.get('Est. Uplift/mo','—')}</div>"
                        f"</div>", unsafe_allow_html=True,
                    )
                st.markdown("<br/>", unsafe_allow_html=True)

            reco_disp = df_display[[
                "Confidence", "Based On", "Est. Uplift/mo",
                "Type", "Offer", "Why?", "Next Step",
            ]].copy()
            for _rc in reco_disp.select_dtypes(include=["object"]).columns:
                reco_disp[_rc] = reco_disp[_rc].fillna("").astype(str)
            st.dataframe(reco_disp, use_container_width=True, hide_index=True)
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
            wa_text = str(scripts.get("whatsapp", ""))
            email_subj = str(scripts.get("email_subject", ""))
            email_body = str(scripts.get("email_body", ""))

            st.text_area("WhatsApp Draft", value=wa_text, height=170)
            st.code(wa_text, language="")

            st.text_input("Email Subject", value=email_subj)

            st.text_area("Email Body", value=email_body, height=230)
            st.code(email_body, language="")


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
            fu_wa = str(followup.get("whatsapp_followup", ""))
            fu_subj = str(followup.get("email_subject_followup", ""))
            fu_body = str(followup.get("email_body_followup", ""))

            st.text_area("WhatsApp Follow-up", value=fu_wa, height=180)
            st.code(fu_wa, language="")

            st.text_input("Follow-up Email Subject", value=fu_subj)

            st.text_area("Follow-up Email Body", value=fu_body, height=240)
            st.code(fu_body, language="")



