import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import time
import re

import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from ml_engine.services.export_service import (
    export_partner_360_pdf,
    export_partner_360_excel,
)
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from styles import apply_global_styles, section_header, status_badge, banner, health_color, churn_color, page_caption, page_header, skeleton_loader


def render(ai):
    apply_global_styles()
    page_header(
        title="Partner 360 View",
        subtitle="Deep-dive into any partner — revenue health, churn risk, forecast, and recommendations.",
        icon="🤝",
        accent_color="#2563eb",
    )
    skel = st.empty()
    with skel.container():
        skeleton_loader(n_metric_cards=4, n_rows=3, label="Loading partner intelligence...")
    ai.ensure_clustering()
    skel.empty()

    all_states = sorted(ai.matrix["state"].dropna().unique())

    # ── Pre-select from session state (deep-link from Kanban / Global Search) ──
    _preselect_state   = st.session_state.pop("preselect_state", None)
    _preselect_partner = st.session_state.pop("preselect_partner", None)

    _state_idx = 0
    if _preselect_state and _preselect_state in list(all_states):
        _state_idx = list(all_states).index(_preselect_state)
    selected_state = st.selectbox("Step 1: Select State/Region", all_states, index=_state_idx)

    filtered_partners = sorted(
        ai.matrix[ai.matrix["state"] == selected_state].index.unique()
    )

    if not filtered_partners:
        st.warning("No partners found in this state with recent activity.")
        return

    _partner_idx = 0
    if _preselect_partner and _preselect_partner in list(filtered_partners):
        _partner_idx = list(filtered_partners).index(_preselect_partner)
    selected_partner = st.selectbox("Step 2: Select Partner", filtered_partners, index=_partner_idx)

    report = ai.get_partner_intelligence(selected_partner)
    if not report:
        st.warning("No report available for the selected partner.")
        return

    # --- Export Buttons ---
    ex1, ex2, ex3 = st.columns([1, 1, 4])
    with ex1:
        pdf_bytes = export_partner_360_pdf(selected_partner, report)
        st.download_button(
            "\u2B07 Download PDF",
            data=pdf_bytes,
            file_name=f"Partner_360_{selected_partner.replace(' ', '_')}.pdf",
            mime="application/pdf",
            key="p360_pdf",
        )
    with ex2:
        xls_bytes = export_partner_360_excel(selected_partner, report)
        st.download_button(
            "\u2B07 Download Excel",
            data=xls_bytes,
            file_name=f"Partner_360_{selected_partner.replace(' ', '_')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="p360_xlsx",
        )

    facts = report["facts"]
    gaps = report["gaps"]
    cluster_name = report["cluster_label"]
    cluster_type = report.get("cluster_type", "Unknown")
    cluster_info = report.get("cluster_info", "")
    playbook = report.get("playbook", {}) or {}
    alerts = report.get("alerts", []) or []

    status = facts.get("health_status", "Unknown")
    drop = float(facts.get("revenue_drop_pct", 0))
    total_pot_yearly = (
        float(gaps["Potential_Revenue_Yearly"].sum())
        if not gaps.empty and "Potential_Revenue_Yearly" in gaps.columns
        else (float(gaps["Potential_Revenue"].sum()) if not gaps.empty else 0.0)
    )
    total_pot_monthly = (
        float(gaps["Potential_Revenue_Monthly"].sum())
        if not gaps.empty and "Potential_Revenue_Monthly" in gaps.columns
        else total_pot_yearly / 12.0
    )
    total_pot_weekly = (
        float(gaps["Potential_Revenue_Weekly"].sum())
        if not gaps.empty and "Potential_Revenue_Weekly" in gaps.columns
        else total_pot_yearly / 52.0
    )
    health_segment = facts.get("health_segment", "Unknown")
    health_score = float(facts.get("health_score", 0))
    est_monthly_loss = float(facts.get("estimated_monthly_loss", 0))
    recency_days = int(facts.get("recency_days", 0))
    degrowth_flag = bool(facts.get("degrowth_flag", False))
    degrowth_threshold = float(facts.get("degrowth_threshold_pct", 20))
    churn_prob = float(facts.get("churn_probability", 0))
    churn_band = str(facts.get("churn_risk_band", "Unknown"))
    risk_90d = float(facts.get("expected_revenue_at_risk_90d", 0))
    risk_monthly = float(facts.get("expected_revenue_at_risk_monthly", 0))
    fc_next_30d = float(facts.get("forecast_next_30d", 0))
    fc_trend_pct = float(facts.get("forecast_trend_pct", 0))
    fc_conf = float(facts.get("forecast_confidence", 0))
    credit_score = float(facts.get("credit_risk_score", 0))
    credit_band = str(facts.get("credit_risk_band", "Unknown"))
    credit_util = float(facts.get("credit_utilization", 0))
    overdue_ratio = float(facts.get("overdue_ratio", 0))
    outstanding_amt = float(facts.get("outstanding_amount", 0))
    credit_adjusted_risk = float(facts.get("credit_adjusted_risk_value", 0))

    # ── ₹ formatter ──────────────────────────────────────────────────────────
    def _fmt(v):
        try: v = float(v)
        except Exception: return "₹0"
        if v >= 1_00_00_000: return f"₹{v/1_00_00_000:.1f}Cr"
        if v >= 1_00_000:    return f"₹{v/1_00_000:.1f}L"
        if v >= 1_000:       return f"₹{v/1_000:.0f}K"
        return f"₹{v:.0f}"

    # ── Confidence label + freshness badge ───────────────────────────────────
    def _confidence_label(active_mo, rec_days, rec_txns):
        """Return (label, hex_color) for data confidence tier."""
        if active_mo >= 6 and rec_txns >= 3 and rec_days <= 60:
            return "Verified",  "#10b981"
        if active_mo >= 2 and rec_txns >= 1 and rec_days <= 120:
            return "Derived",   "#3b82f6"
        if rec_txns >= 1:
            return "Proxy",     "#f59e0b"
        return "Estimated",     "#ef4444"

    def _freshness_badge(rec_days):
        if rec_days <= 30:  return "🟢", "Fresh",      "#10b981"
        if rec_days <= 90:  return "🟡", "Stale",      "#f59e0b"
        return               "🔴", "Very Stale", "#ef4444"

    _active_mo   = int(facts.get("active_months", 0) or 0)
    _rec_txns    = int(facts.get("recent_txns",   0) or 0)
    conf_label, conf_color = _confidence_label(_active_mo, recency_days, _rec_txns)
    fresh_emoji, fresh_label, fresh_color = _freshness_badge(recency_days)
    _data_dt      = facts.get("data_last_date", None)
    data_date_str = str(_data_dt)[:10] if _data_dt else "live"

    # ── Status Banner ────────────────────────────────────────────────────────
    color = health_color(status)
    churn_c = churn_color(churn_prob)
    st.markdown(
        f"<div style='display:flex;gap:10px;align-items:center;"
        f"flex-wrap:wrap;margin-bottom:18px;'>"
        f"{status_badge(f'Status: {status}', color)}"
        f"{status_badge(f'Churn: {churn_prob*100:.0f}%', churn_c)}"
        f"{status_badge(f'Segment: {cluster_type}', 'blue')}"
        f"{status_badge(cluster_name, 'grey')}"
        f"<span style='margin-left:auto;display:flex;gap:8px;align-items:center;'>"
        f"<span title='Data confidence tier' style='font-size:11px;padding:3px 9px;"
        f"border-radius:20px;background:rgba(255,255,255,0.06);"
        f"color:{conf_color};border:1px solid {conf_color}55;font-weight:600;'>"
        f"● {conf_label}</span>"
        f"<span title='Last purchase recency' style='font-size:11px;padding:3px 9px;"
        f"border-radius:20px;background:rgba(255,255,255,0.06);"
        f"color:{fresh_color};border:1px solid {fresh_color}55;'>"
        f"{fresh_emoji} {fresh_label} · Data as of {data_date_str}</span>"
        f"</span></div>",
        unsafe_allow_html=True,
    )

    # ── Traffic Light Health alert box ──
    badge_emoji = "🟢"
    badge_title = "Active & Growing"
    badge_desc = "Account is in excellent health with consistent transaction volumes and low churn risk."
    badge_bg = "rgba(16, 185, 129, 0.08)"
    badge_bdr = "#10b981"
    
    if health_segment in ("At Risk", "Critical") or churn_prob >= 0.6:
        badge_emoji = "🔴"
        badge_title = "Action Needed (High Risk)"
        badge_desc = "Account is experiencing purchase drops or elevated churn signals. Direct outreach is highly recommended."
        badge_bg = "rgba(239, 68, 68, 0.08)"
        badge_bdr = "#ef4444"
    elif health_segment in ("Emerging", "Mature") or churn_prob >= 0.3:
        badge_emoji = "🟡"
        badge_title = "Needs Monitoring"
        badge_desc = "Account spend profile is stable but shows minor recency or category gaps. Monitor upcoming orders closely."
        badge_bg = "rgba(245, 158, 11, 0.08)"
        badge_bdr = "#f59e0b"
        
    st.markdown(
        f"<div style='background:{badge_bg};border-left:5px solid {badge_bdr};"
        f"border-radius:10px;padding:16px 20px;margin-bottom:20px;'>"
        f"<div style='font-size:16px;font-weight:700;color:{badge_bdr};display:flex;align-items:center;gap:8px;'>"
        f"<span>{badge_emoji}</span><span>{badge_title}</span>"
        f"</div>"
        f"<div style='font-size:13px;color:#e2e8f0;margin-top:6px;'>{badge_desc}</div>"
        f"</div>",
        unsafe_allow_html=True
    )

    # ══════════════════════════════════════════════════════════════════════════
    # 5-TAB LAYOUT
    # ══════════════════════════════════════════════════════════════════════════
    _tab_rev, _tab_churn, _tab_cross, _tab_spin, _tab_sim = st.tabs([
        "📈  Revenue & Health",
        "⚠️  Churn Intelligence",
        "🛒  Cross-sell & Retention",
        "🎙️  SPIN Script",
        "👥  Similar Partners",
    ])

    # ─────────────────────────────────────────────────────────────────────────
    # TAB 2 — Churn Intelligence
    # ─────────────────────────────────────────────────────────────────────────
    with _tab_churn:
        churn_data = report.get("churn_reasons", {})
        if isinstance(churn_data, list):
            churn_signals   = churn_data
            composite_score = 0
            risk_level      = "Unknown"
            risk_label      = ""
            score_breakdown = {}
            top_signal      = churn_signals[0] if churn_signals else None
            outreach_script = ""
            peer_ctx        = {}
            rec_label       = "Rs0"
        else:
            churn_signals   = churn_data.get("signals", [])
            composite_score = int(churn_data.get("composite_score", 0))
            risk_level      = churn_data.get("risk_level", "Low")
            risk_label      = churn_data.get("risk_label", "")
            score_breakdown = churn_data.get("score_breakdown", {})
            top_signal      = churn_data.get("top_signal")
            outreach_script = churn_data.get("outreach_script", "")
            peer_ctx        = churn_data.get("peer_context", {}) or {}
            rec_label       = churn_data.get("recovery_label", "Rs0")

        _seg = str(facts.get("health_segment", "Healthy"))
        if churn_signals and _seg in ("At Risk", "Critical"):
            _sev_c = {"critical": "#ef4444", "high": "#f59e0b", "medium": "#6366f1"}
            if risk_level == "Critical":
                _rl = "#ef4444"
            elif risk_level == "High":
                _rl = "#f59e0b"
            elif risk_level == "Medium":
                _rl = "#6366f1"
            else:
                _rl = "#22c55e"

            # Score gauge bar
            _pct = max(0, min(100, composite_score))
            _bar_html = (
                "<div style='background:#1e2433;border-radius:6px;height:10px;"
                "margin:8px 0 4px;overflow:hidden;'>"
                "<div style='width:" + str(_pct) + "%;height:100%;border-radius:6px;"
                "background:linear-gradient(90deg," + _rl + "88," + _rl + ");'></div></div>"
            )

            # Score breakdown bars
            _sub_html = ""
            for _cn, _cv in score_breakdown.items():
                _sp = int(min(100, _cv / 0.3))
                _sub_html += (
                    "<div style='display:flex;align-items:center;gap:6px;margin-bottom:3px;'>"
                    "<div style='width:85px;font-size:11px;color:#94a3b8;text-align:right;'>"
                    + str(_cn)
                    + "</div><div style='flex:1;background:#1e2433;border-radius:4px;height:6px;'>"
                    "<div style='width:" + str(_sp) + "%;background:" + _rl
                    + ";border-radius:4px;height:6px;'></div></div>"
                    "<div style='font-size:11px;color:" + _rl + ";width:22px;'>"
                    + str(int(_cv)) + "</div></div>"
                )

            st.markdown(
                "<div style='background:#0f1420;border:1px solid " + _rl + "55;"
                "border-radius:12px;padding:20px;margin-bottom:18px;'>"
                "<div style='display:flex;align-items:flex-start;"
                "justify-content:space-between;flex-wrap:wrap;gap:12px;margin-bottom:14px;'>"
                "<div><div style='font-size:16px;font-weight:700;color:" + _rl + ";'>"
                "&#9888; Churn Risk Intelligence</div>"
                "<div style='font-size:12px;color:#64748b;margin-top:2px;'>"
                "Why this partner is at risk &mdash; peer context &amp; next steps"
                "</div></div>"
                "<div style='text-align:center;background:" + _rl + "18;"
                "border:1px solid " + _rl + "44;border-radius:10px;padding:10px 18px;"
                "min-width:110px;'>"
                "<div style='font-size:28px;font-weight:800;color:" + _rl + ";line-height:1;'>"
                + str(composite_score)
                + "</div><div style='font-size:10px;color:#94a3b8;font-weight:600;"
                "text-transform:uppercase;letter-spacing:0.5px;margin-top:3px;'>/ 100 Risk</div>"
                "<div style='font-size:11px;color:" + _rl + ";margin-top:4px;font-weight:600;'>"
                + risk_level + "</div></div></div>"
                + _bar_html
                + "<div style='font-size:11px;color:#64748b;margin-bottom:12px;'>"
                + risk_label + "</div>"
                "<div style='background:#161b2a;border-radius:8px;padding:12px;'>"
                "<div style='font-size:11px;color:#94a3b8;font-weight:600;"
                "margin-bottom:8px;text-transform:uppercase;letter-spacing:0.5px;'>"
                "Score Breakdown</div>"
                + _sub_html + "</div></div>",
                unsafe_allow_html=True,
            )

            # Priority #1 action card
            if top_signal:
                _ts_sev    = top_signal.get("severity", "high")
                _ts_title  = top_signal.get("signal", "")
                _ts_detail = top_signal.get("detail", "")
                _ts_action = top_signal.get("action", "")
                _tc = _sev_c.get(_ts_sev, "#f59e0b")
                st.markdown(
                    "<div style='background:" + _tc + "12;border:1px solid " + _tc + "55;"
                    "border-left:5px solid " + _tc + ";border-radius:10px;"
                    "padding:16px;margin-bottom:14px;'>"
                    "<div style='display:flex;align-items:center;gap:8px;margin-bottom:6px;'>"
                    "<span style='font-size:15px;font-weight:800;color:" + _tc + ";'>"
                    "&#127919; #1 Priority &mdash; " + _ts_title + "</span>"
                    "<span style='font-size:10px;padding:2px 8px;border-radius:12px;"
                    "background:" + _tc + "22;color:" + _tc + ";font-weight:700;"
                    "text-transform:uppercase;'>" + _ts_sev.upper() + "</span></div>"
                    "<div style='font-size:13px;color:#cbd5e1;margin-bottom:10px;'>"
                    + _ts_detail
                    + "</div><div style='background:#ffffff0a;border-radius:6px;"
                    "padding:10px 12px;'>"
                    "<span style='color:#22c55e;font-weight:700;font-size:12px;'>"
                    "&#9654; RECOMMENDED ACTION:</span>"
                    "<div style='color:#e2e8f0;font-size:13px;margin-top:4px;'>"
                    + _ts_action + "</div></div></div>",
                    unsafe_allow_html=True,
                )

            # Other signals as chips
            _others = [s for s in churn_signals if s is not top_signal]
            if _others:
                _chips_html = ""
                for s in _others:
                    _sc = _sev_c.get(s.get("severity", "medium"), "#6366f1")
                    _sig_name = s.get("signal", "")
                    _chips_html += (
                        "<span style='display:inline-block;padding:4px 10px;"
                        "border-radius:20px;background:" + _sc + "18;color:" + _sc + ";"
                        "border:1px solid " + _sc + "44;"
                        "font-size:12px;font-weight:600;margin:3px;'>"
                        + _sig_name + "</span>"
                    )
                st.markdown(
                    "<div style='margin-bottom:14px;'>"
                    "<div style='font-size:11px;color:#64748b;font-weight:600;"
                    "text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px;'>"
                    "Other Contributing Signals</div>" + _chips_html + "</div>",
                    unsafe_allow_html=True,
                )
                with st.expander("View all signal details and actions"):
                    for _s in _others:
                        _s_sig    = _s.get("signal", "")
                        _s_sev    = _s.get("severity", "").upper()
                        _s_detail = _s.get("detail", "")
                        _s_action = _s.get("action", "")
                        st.markdown(
                            "**" + _s_sig + "** (" + _s_sev + ")\n\n"
                            + _s_detail + "\n\n"
                            "Action: " + _s_action,
                        )
                        st.divider()

            # Peer benchmark row
            if peer_ctx:
                _pd   = peer_ctx.get("pct_vs_peer", 0)
                _pc   = "#ef4444" if _pd < -20 else "#f59e0b" if _pd < 0 else "#22c55e"
                _cd   = peer_ctx.get("this_cats", 0) - peer_ctx.get("peer_avg_cats", 0)
                _cc   = "#ef4444" if _cd < -1 else "#f59e0b" if _cd < 0 else "#22c55e"
                _cl   = str(peer_ctx.get("cluster_label", "Cluster"))
                _pcnt = str(peer_ctx.get("peer_count", 0))
                _tr   = str(peer_ctx.get("this_rev_fmt", "Rs0"))
                _pr   = str(peer_ctx.get("peer_avg_rev_fmt", "Rs0"))
                _tc2  = str(int(peer_ctx.get("this_cats", 0)))
                _pc2  = "{:.0f}".format(peer_ctx.get("peer_avg_cats", 0))
                _rec  = "{:.0f}".format(peer_ctx.get("peer_avg_recency", 0))
                _pdstr = "{:+.0f}".format(_pd)
                st.markdown(
                    "<div style='background:#161b2a;border-radius:8px;padding:14px 16px;"
                    "margin-bottom:14px;display:flex;flex-wrap:wrap;gap:16px;align-items:center;'>"
                    "<div style='font-size:11px;color:#94a3b8;font-weight:600;"
                    "text-transform:uppercase;letter-spacing:0.5px;width:100%;margin-bottom:4px;'>"
                    "Peer Benchmark &mdash; " + _cl + " (" + _pcnt + " peers)</div>"
                    "<div style='text-align:center;'>"
                    "<div style='font-size:20px;font-weight:700;color:#e2e8f0;'>" + _tr + "</div>"
                    "<div style='font-size:11px;color:#64748b;'>This partner (90d)</div></div>"
                    "<div style='font-size:20px;color:#334155;'>vs</div>"
                    "<div style='text-align:center;'>"
                    "<div style='font-size:20px;font-weight:700;color:#94a3b8;'>" + _pr + "</div>"
                    "<div style='font-size:11px;color:#64748b;'>Cluster avg (90d)</div></div>"
                    "<div style='background:" + _pc + "18;padding:6px 14px;border-radius:20px;"
                    "font-weight:700;font-size:13px;color:" + _pc + ";border:1px solid " + _pc + "44;'>"
                    + _pdstr + "% vs peers</div>"
                    "<div style='margin-left:auto;font-size:12px;color:#64748b;'>"
                    "Categories: <span style='color:" + _cc + ";font-weight:700;'>"
                    + _tc2 + " vs " + _pc2 + " avg</span><br/>"
                    "Peer avg last purchase: " + _rec + "d</div></div>",
                    unsafe_allow_html=True,
                )

            # Recovery potential + outreach script
            _r1, _r2 = st.columns([1, 2])
            with _r1:
                st.markdown(
                    "<div style='background:#22c55e12;border:1px solid #22c55e44;"
                    "border-radius:10px;padding:16px;text-align:center;'>"
                    "<div style='font-size:11px;color:#22c55e;font-weight:700;"
                    "text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px;'>"
                    "Recovery Potential</div>"
                    "<div style='font-size:28px;font-weight:800;color:#22c55e;line-height:1;'>"
                    + str(rec_label)
                    + "</div>"
                    "<div style='font-size:11px;color:#64748b;margin-top:6px;'>"
                    "Estimated Yearly</div>"
                    "<div style='font-size:11px;color:#64748b;margin-top:2px;'>"
                    "Based on historical avg revenue</div></div>",
                    unsafe_allow_html=True,
                )
            with _r2:
                if outreach_script:
                    st.markdown(
                        f"<div style='background:rgba(37,99,235,0.08);border-radius:10px;padding:12px;border:1px solid rgba(37,99,235,0.2);'>"
                        f"<div style='font-size:12px;font-weight:700;color:#3b82f6;margin-bottom:6px;'>📞 PERSONALIZED OUTREACH SCRIPT</div>"
                        f"</div>",
                        unsafe_allow_html=True
                    )
                    st.code(outreach_script, language=None)
                    st.caption("👉 Hover over the box above and click the copy icon on the right to copy to clipboard in one click!")
                    st.caption(
                        "Customise: replace [Contact Name], [Day], [Time] before sending."
                    )
        else:
            # No churn signals or not at risk
            _churn_col = churn_color(churn_prob)
            st.markdown(
                f"<div style='background:#0f1420;border:1px solid #1e2433;border-radius:12px;"
                f"padding:24px;text-align:center;'>"
                f"<div style='font-size:36px;margin-bottom:10px;'>✅</div>"
                f"<div style='font-size:16px;font-weight:700;color:#22c55e;margin-bottom:6px;'>"
                f"No Active Churn Signals</div>"
                f"<div style='font-size:13px;color:#64748b;'>"
                f"Churn probability: <b style='color:#e2e8f0;'>{churn_prob*100:.1f}%</b> · "
                f"Health segment: <b style='color:#e2e8f0;'>{_seg}</b></div>"
                f"</div>",
                unsafe_allow_html=True,
            )

        # ── Pitfall A & Wow Factor 1: Machine Learning Explainer & Survival Projections ──
        st.markdown("<div style='margin-top: 24px;'></div>", unsafe_allow_html=True)
        st.markdown(f"<div class='ui-section'>", unsafe_allow_html=True)
        section_header("🔮 Machine Learning Explainer & Survival Projections")
        
        m_col1, m_col2 = st.columns(2)
        with m_col1:
            st.markdown("#### Attribution of Churn Risk (SHAP Explainer)")
            explain_data = ai.explain_partner_churn(selected_partner)
            if explain_data.get("status") == "ok":
                shap_vals = explain_data["shap_values"]
                
                # Diverging colors: red for risk contribution (>0), teal/green for safety (<0 or tiny)
                # But since all signals in our rule-based mixin are positive risk contributions, 
                # let's color them by magnitude (red for high, green/indigo for tiny)
                colors = []
                for val in shap_vals.values():
                    if val > 0.15:
                        colors.append("#ef4444")  # Red (High Risk)
                    elif val > 0.08:
                        colors.append("#f59e0b")  # Orange (Medium Risk)
                    else:
                        colors.append("#10b981")  # Green (Low/Mitigated)
                
                fig_shap = go.Figure(go.Bar(
                    x=list(shap_vals.values()),
                    y=list(shap_vals.keys()),
                    orientation='h',
                    marker=dict(
                        color=colors,
                        line=dict(width=1, color='rgba(255,255,255,0.08)')
                    )
                ))
                fig_shap.update_layout(
                    paper_bgcolor='rgba(0,0,0,0)',
                    plot_bgcolor='rgba(0,0,0,0)',
                    xaxis=dict(gridcolor='#1e2433', showgrid=True, title="Relative Risk Weight"),
                    yaxis=dict(autorange="reversed"),
                    font={'color': "#94a3b8", 'family': "Inter, sans-serif"},
                    height=280,
                    margin=dict(l=10, r=10, t=10, b=10)
                )
                st.plotly_chart(fig_shap, use_container_width=True)
                st.markdown(
                    "<div style='font-size:12px;color:#94a3b8;margin-top:6px;line-height:1.5;padding:8px 12px;background:rgba(255,255,255,0.02);border-radius:6px;border-left:3px solid #ef4444;'>"
                    "📊 <b>Plain-English Summary:</b> This chart shows which specific business behaviors are driving the churn risk. "
                    "Longer bars on top represent the biggest issues (e.g. late payments or purchase gaps) that you need to resolve with the partner."
                    "</div>",
                    unsafe_allow_html=True
                )
            else:
                st.info("Attribution data loading or unavailable.")
                
        with m_col2:
            st.markdown("#### 24-Month Account Survival Probability")
            survival_data = ai.predict_partner_survival(selected_partner)
            if survival_data.get("status") == "ok":
                times = survival_data["times"]
                probs = [p * 100 for p in survival_data["survival_probs"]]
                med_months = survival_data["median_survival_months"]
                
                fig_surv = go.Figure()
                fig_surv.add_trace(go.Scatter(
                    x=times, y=probs,
                    mode='lines',
                    line=dict(color='#3b82f6', width=3),
                    fill='tozeroy',
                    fillcolor='rgba(59, 130, 246, 0.06)',
                    name='Survival Probability'
                ))
                
                # 50% Median Line
                fig_surv.add_shape(
                    type="line", x0=0, y0=50, x1=24, y1=50,
                    line=dict(color="#ef4444", width=1.5, dash="dash")
                )
                fig_surv.add_annotation(
                    x=med_months, y=50,
                    text=f"Median Survival: {med_months} Mo",
                    showarrow=True,
                    arrowhead=2,
                    ax=0, ay=-30,
                    font=dict(color="#ef4444", size=10)
                )
                
                fig_surv.update_layout(
                    paper_bgcolor='rgba(0,0,0,0)',
                    plot_bgcolor='rgba(0,0,0,0)',
                    font={'color': "#94a3b8", 'family': "Inter, sans-serif"},
                    xaxis=dict(gridcolor='#1e2433', showgrid=True, title="Months Elapsed"),
                    yaxis=dict(gridcolor='#1e2433', showgrid=True, title="Survival Probability (%)", range=[0, 105]),
                    height=280,
                    margin=dict(l=10, r=10, t=10, b=10)
                )
                st.plotly_chart(fig_surv, use_container_width=True)
                st.markdown(
                    f"<div style='font-size:12px;color:#94a3b8;margin-top:6px;line-height:1.5;padding:8px 12px;background:rgba(255,255,255,0.02);border-radius:6px;border-left:3px solid #3b82f6;'>"
                    f"📊 <b>Plain-English Summary:</b> This curve shows the likelihood of this partner continuing to do business with us over the next 24 months. "
                    f"A steep drop indicates high risk. The red line highlights the estimated point of a 50% drop (median survival of <b>{med_months} months</b>)."
                    f"</div>",
                    unsafe_allow_html=True
                )
            else:
                st.info("Survival projection data loading or unavailable.")
        st.markdown("</div>", unsafe_allow_html=True)

    # ─────────────────────────────────────────────────────────────────────────
    # TAB 1 — Revenue & Health
    # ─────────────────────────────────────────────────────────────────────────
    with _tab_rev:
        st.markdown(f"<div class='ui-section'>", unsafe_allow_html=True)
        section_header("Revenue Health & Status")
        
        rh1, rh2 = st.columns([1, 1.5])
        with rh1:
            # ── Wow Factor 2: Dynamic Health Score Plotly Gauge Dial ──
            g_color = "#10b981"
            if health_segment == "Champion":
                g_color = "#10b981"
            elif health_segment in ("Healthy", "Emerging"):
                g_color = "#3b82f6"
            elif health_segment == "At Risk":
                g_color = "#f59e0b"
            else:
                g_color = "#ef4444"

            fig_gauge = go.Figure(go.Indicator(
                mode = "gauge+number",
                value = health_score * 100,
                domain = {'x': [0, 1], 'y': [0, 1]},
                title = {'text': f"<b>{health_segment}</b>", 'font': {'size': 15, 'color': '#f8fafc'}},
                gauge = {
                    'axis': {'range': [0, 100], 'tickwidth': 1, 'tickcolor': "#475569"},
                    'bar': {'color': g_color},
                    'bgcolor': "rgba(0,0,0,0)",
                    'borderwidth': 1.5,
                    'bordercolor': "#1e2433",
                    'steps': [
                        {'range': [0, 40], 'color': 'rgba(239, 68, 68, 0.15)'},
                        {'range': [40, 70], 'color': 'rgba(245, 158, 11, 0.15)'},
                        {'range': [70, 100], 'color': 'rgba(16, 185, 129, 0.15)'}
                    ],
                }
            ))
            fig_gauge.update_layout(
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                font={'color': "#f8fafc", 'family': "Inter, sans-serif"},
                height=180,
                margin=dict(l=10, r=10, t=30, b=10)
            )
            st.plotly_chart(fig_gauge, use_container_width=True)
            
        with rh2:
            st.markdown("<div style='padding-top: 15px;'></div>", unsafe_allow_html=True)
            m_col1, m_col2 = st.columns(2)
            with m_col1:
                st.metric("Revenue Drop", f"{drop:.1f}%", delta=f"-{drop:.1f}%", delta_color="inverse")
                st.metric("Est. Monthly Loss", _fmt(est_monthly_loss))
            with m_col2:
                st.metric("Unlocked Potential (Yearly)", _fmt(total_pot_yearly),
                          delta=f"Monthly {_fmt(total_pot_monthly)}", delta_color="off")
        st.markdown("</div>", unsafe_allow_html=True)

        # ── Section 2: Churn & Forecast with Cash-Flow Micro-Chart ──
        st.markdown(f"<div class='ui-section'>", unsafe_allow_html=True)
        section_header("Churn Risk & Forecast Trajectory")
        
        cf1, cf2 = st.columns([1, 1.5])
        with cf1:
            st.markdown("<div style='padding-top: 10px;'></div>", unsafe_allow_html=True)
            st.metric("Churn Probability", f"{churn_prob * 100:.1f}%", delta=f"Risk Band: {churn_band}", delta_color="off")
            st.metric("Revenue At Risk (90d)", _fmt(risk_90d),
                      delta=f"Monthly {_fmt(risk_monthly)}", delta_color="off")
            st.metric("Last Order Recency", f"{recency_days} Days Ago")
            
        with cf2:
            # ── Wow Factor 3: Cash-Flow Trajectory Micro-Chart ──
            hist_df = pd.DataFrame()
            if hasattr(ai, "df_monthly_revenue") and ai.df_monthly_revenue is not None and not ai.df_monthly_revenue.empty:
                hist_df = ai.df_monthly_revenue[ai.df_monthly_revenue["company_name"] == selected_partner].copy()
            
            if hist_df.empty:
                recent_90 = float(facts.get("recent_90_revenue", 0.0))
                prev_90 = float(facts.get("prev_90_revenue", 0.0))
                dates = pd.date_range(end=pd.Timestamp.now(), periods=6, freq="MS")
                vals = [prev_90 / 3.0] * 3 + [recent_90 / 3.0] * 3
                hist_df = pd.DataFrame({
                    "sale_month": dates,
                    "monthly_revenue": vals
                })
                
            hist_sorted = hist_df.sort_values("sale_month")
            months = hist_sorted["sale_month"].dt.strftime("%b %y").tolist()
            revenues = hist_sorted["monthly_revenue"].tolist()
            
            forecast_month = (hist_sorted["sale_month"].iloc[-1] + pd.DateOffset(months=1)).strftime("%b %y")
            
            fig_trend = go.Figure()
            # Historical Area
            fig_trend.add_trace(go.Scatter(
                x=months, y=revenues,
                mode='lines+markers',
                line=dict(color='#3b82f6', width=3),
                fill='tozeroy',
                fillcolor='rgba(59, 130, 246, 0.06)',
                name='Historical'
            ))
            # Forecast Dotted Area
            fig_trend.add_trace(go.Scatter(
                x=[months[-1], forecast_month],
                y=[revenues[-1], fc_next_30d],
                mode='lines+markers',
                line=dict(color='#10b981' if fc_trend_pct >= 0 else '#ef4444', width=3, dash='dash'),
                fill='tozeroy',
                fillcolor='rgba(16, 185, 129, 0.06)' if fc_trend_pct >= 0 else 'rgba(239, 68, 68, 0.06)',
                name='30-Day Forecast'
            ))
            fig_trend.update_layout(
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                font={'color': "#94a3b8", 'family': "Inter, sans-serif"},
                xaxis=dict(gridcolor='#1e2433', showgrid=True),
                yaxis=dict(gridcolor='#1e2433', showgrid=True),
                height=180,
                margin=dict(l=10, r=10, t=10, b=10),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
            )
            st.plotly_chart(fig_trend, use_container_width=True)
            # Dynamic forecast caption
            trend_direction = "upward 📈" if fc_trend_pct >= 0 else "downward 📉"
            trend_color = "#22c55e" if fc_trend_pct >= 0 else "#ef4444"
            action_advice = (
                "The partner is in a healthy growing phase. Continue standard relationship management."
                if fc_trend_pct >= 0
                else "Action Recommended: Reach out immediately to understand the drop and stabilize future orders."
            )
            st.markdown(
                f"<div style='font-size:12px;color:#94a3b8;padding:8px 12px;background:rgba(255,255,255,0.03);"
                f"border-radius:6px;border-left:3px solid {trend_color};margin-top:6px;'>"
                f"💡 <b>Plain-English Summary:</b> This chart shows a <b>{trend_direction}</b> revenue projection of "
                f"<span style='color:{trend_color};font-weight:700;'>{abs(fc_trend_pct):.1f}%</span> for the next 30 days. "
                f"Estimated next month revenue: <b style='color:#f8fafc;'>{_fmt(fc_next_30d)}</b>. {action_advice}"
                f"</div>",
                unsafe_allow_html=True
            )
        st.markdown("</div>", unsafe_allow_html=True)

        # ── Section 3: Credit Risk ───────────────────────────────────────────
        st.markdown(f"<div class='ui-section'>", unsafe_allow_html=True)
        section_header("Credit Risk Profile")
        cr1, cr2 = st.columns([1, 1.5])
        with cr1:
            st.metric("Credit Risk Score", f"{credit_score * 100:.1f}%",
                      delta=f"Band: {credit_band}", delta_color="off")
            st.caption(f"Utilization: {credit_util * 100:.1f}% | Overdue: {overdue_ratio * 100:.1f}%")
        with cr2:
            st.metric("Outstanding + Adjusted Risk Value",
                _fmt(outstanding_amt),
                delta=f"Adjusted Risk Value: {_fmt(credit_adjusted_risk)}",
                delta_color="off",
            )
            st.caption("Adjusted risk value balances outstanding balances against the actual credit probability.")
        st.markdown("</div>", unsafe_allow_html=True)

    # ─────────────────────────────────────────────────────────────────────────
    # TAB 3 — Cross-sell & Retention
    # ─────────────────────────────────────────────────────────────────────────
    with _tab_cross:
        left, right = st.columns([1, 1.5])

        with left:
            st.subheader("Retention Strategy")
            pitch = facts.get("top_affinity_pitch", None)
            pitch_conf = facts.get("pitch_confidence", None)
            pitch_lift = facts.get("pitch_lift", None)
            pitch_gain = facts.get("pitch_expected_gain", None)
            pitch_margin = facts.get("pitch_expected_margin", None)
            if pitch and pitch not in ("None", "N/A"):
                st.info(f"**Pitch This:** {pitch}")
                st.caption("Reason: Frequent buyer of associated items.")

                metric_line = []
                if pitch_conf is not None and not pd.isna(pitch_conf):
                    metric_line.append(f"Confidence: {float(pitch_conf):.2f}")
                if pitch_lift is not None and not pd.isna(pitch_lift):
                    metric_line.append(f"Lift: {float(pitch_lift):.2f}")
                if pitch_gain is not None and not pd.isna(pitch_gain):
                    metric_line.append(f"Expected Gain: Rs {int(float(pitch_gain)):,}")
                if pitch_margin is not None and not pd.isna(pitch_margin):
                    metric_line.append(f"Expected Margin: Rs {int(float(pitch_margin)):,}")
                if metric_line:
                    st.caption(" | ".join(metric_line))
            else:
                st.success("No immediate missed attachments.")

            st.caption(f"Recency: {recency_days} days since last purchase")
            st.caption(f"Degrowth threshold: {degrowth_threshold:.1f}% revenue drop")

            if degrowth_flag:
                st.warning("Degrowth detected in recent 90-day window.")

            if "Healthy" not in status:
                st.error(f"Action: {status}")

        with right:
            st.subheader("Peer Gap Analysis (Cross-Sell)")
            if not gaps.empty:
                st.write(f"Comparisons against **{cluster_name}** peers:")

                def _gap_fmt(v):
                    try: v = float(v)
                    except Exception: return "₹0"
                    if v >= 1_00_00_000: return f"₹{v/1_00_00_000:.1f}Cr"
                    if v >= 1_00_000:    return f"₹{v/1_00_000:.1f}L"
                    if v >= 1_000:       return f"₹{v/1_000:.0f}K"
                    return f"₹{v:.0f}"

                disp = gaps.copy()
                disp["Gap_Val_Monthly"] = disp["Potential_Revenue_Monthly"].fillna(0).astype(float)
                disp["Gap (Monthly)"]  = disp["Potential_Revenue_Monthly"].apply(_gap_fmt)
                disp["Gap (Yearly)"]   = disp["Potential_Revenue_Yearly"].apply(_gap_fmt)
                disp["Peer Avg Spend"] = disp["Peer_Avg_Spend"].apply(_gap_fmt)
                disp["You Do"]         = disp["You_Do_Pct"].apply(lambda x: f"{float(x):.1f}%" if pd.notna(x) else "0%")
                disp["Peers Do"]       = disp["Others_Do_Pct"].apply(lambda x: f"{float(x):.1f}%" if pd.notna(x) else "0%")

                show = disp[["Product", "Gap_Val_Monthly", "Gap (Monthly)", "Gap (Yearly)", "You Do", "Peers Do", "Peer Avg Spend"]].sort_values("Gap_Val_Monthly", ascending=False)

                high_gaps = show[show["Gap_Val_Monthly"] >= 50000].drop(columns=["Gap_Val_Monthly"])
                med_gaps = show[(show["Gap_Val_Monthly"] >= 10000) & (show["Gap_Val_Monthly"] < 50000)].drop(columns=["Gap_Val_Monthly"])
                low_gaps = show[show["Gap_Val_Monthly"] < 10000].drop(columns=["Gap_Val_Monthly"])

                if not high_gaps.empty:
                    st.markdown("#### 🔥 High Priority (>&nbsp;₹50K/mo)")
                    st.dataframe(high_gaps, use_container_width=True, hide_index=True)
                if not med_gaps.empty:
                    st.markdown("#### ⚡ Medium Priority (>&nbsp;₹10K/mo)")
                    st.dataframe(med_gaps, use_container_width=True, hide_index=True)
                if not low_gaps.empty:
                    with st.expander("Explore Low Priority Gaps (<&nbsp;₹10K/mo)"):
                        st.dataframe(low_gaps, use_container_width=True, hide_index=True)
            else:
                if any(tag in str(cluster_name) for tag in ("Outlier", "Uncategorized")):
                    st.warning("Partner is uncategorized (unique buying pattern).")
                else:
                    st.success("Perfect account. Matches peer average.")

    # ─────────────────────────────────────────────────────────────────────────
    # TAB 4 — SPIN Selling Script
    # ─────────────────────────────────────────────────────────────────────────
    with _tab_spin:
        # ── Data prep ────────────────────────────────────────────────────────
        _state_str   = str(facts.get("state", "your region") or "your region")
        missing_cat  = str(gaps.iloc[0]["Product"]) if not gaps.empty else "a key product category"
        top_gap_monthly   = _fmt(total_pot_monthly) if total_pot_monthly > 0 else None
        pitch         = str(facts.get("top_affinity_pitch", "") or "")
        pitch_conf    = float(facts.get("pitch_confidence",  0) or 0)
        pitch_lift    = float(facts.get("pitch_lift",        0) or 0)
        active_months = int(facts.get("active_months",       0) or 0)
        recent_txns   = int(facts.get("recent_txns",         0) or 0)

        # ── Call-Readiness Score ──────────────────────────────────────────────
        cr_score = 0
        cr_reasons = []
        if recency_days < 90:
            cr_score += 20
            cr_reasons.append(("\u2705", f"Recent purchase data ({recency_days}d ago)"))
        else:
            cr_reasons.append(("\u26a0\ufe0f", f"Last order was {recency_days}d ago — stale data"))

        if not gaps.empty:
            cr_score += 20
            cr_reasons.append(("\u2705", f"{len(gaps)} cross-sell gap(s) identified"))
        else:
            cr_reasons.append(("\u26a0\ufe0f", "No peer-gap data — using general signals"))

        if pitch and pitch not in ("None", "N/A", ""):
            cr_score += 20
            cr_reasons.append(("\u2705", f"Affinity pitch ready: {pitch}"))

        if active_months >= 3:
            cr_score += 20
            cr_reasons.append(("\u2705", f"{active_months} months of purchase history"))
        else:
            cr_reasons.append(("\u26a0\ufe0f", "Limited purchase history"))

        if churn_prob < 0.6:
            cr_score += 10
            cr_reasons.append(("\u2705", "Not in high churn zone"))
        else:
            cr_reasons.append(("\U0001F534", f"High churn ({churn_prob*100:.0f}%) — handle carefully"))

        if credit_score < 0.5:
            cr_score += 10
            cr_reasons.append(("\u2705", "Credit risk acceptable"))
        else:
            cr_reasons.append(("\U0001F534", f"Elevated credit risk ({credit_score*100:.0f}%)"))

        cr_color = "#10b981" if cr_score >= 70 else "#f59e0b" if cr_score >= 40 else "#ef4444"
        cr_label = "Excellent" if cr_score >= 70 else "Good" if cr_score >= 40 else "Low"

        # ── Pre-Call Intelligence Brief ───────────────────────────────────────
        chips_html = "".join(
            f'<div style="display:flex;align-items:center;gap:6px;background:rgba(255,255,255,0.04);'
            f'border-radius:20px;padding:4px 12px;font-size:11px;color:#cbd5e1;">'
            f'<span>{em}</span><span>{msg}</span></div>'
            for em, msg in cr_reasons
        )
        churn_hi_color = "#ef4444" if churn_prob > 0.4 else "#f0f4ff"
        st.markdown(
            f"""
            <div style="background:linear-gradient(135deg,#0f172a,#1e293b);
                        border:1px solid #334155;border-radius:16px;padding:24px;
                        margin-bottom:24px;position:relative;overflow:hidden;">
              <div style="position:absolute;top:0;left:0;right:0;height:3px;
                          background:linear-gradient(90deg,#3b82f6,#8b5cf6,#06b6d4);"></div>
              <div style="display:flex;justify-content:space-between;align-items:flex-start;
                          flex-wrap:wrap;gap:16px;">
                <div>
                  <div style="font-size:10px;color:#64748b;font-weight:700;
                              text-transform:uppercase;letter-spacing:0.12em;margin-bottom:6px;">
                    &#x1F4CB; Pre-Call Intelligence Brief
                  </div>
                  <div style="font-size:20px;font-weight:800;color:#f0f4ff;line-height:1.2;">
                    {selected_partner}
                  </div>
                  <div style="font-size:12px;color:#64748b;margin-top:4px;">
                    {cluster_type} account &nbsp;&middot;&nbsp; {cluster_name} &nbsp;&middot;&nbsp; {_state_str}
                  </div>
                </div>
                <div style="text-align:center;background:{cr_color}18;
                            border:1px solid {cr_color}44;border-radius:12px;
                            padding:14px 22px;min-width:130px;">
                  <div style="font-size:32px;font-weight:900;color:{cr_color};line-height:1;">{cr_score}</div>
                  <div style="font-size:10px;color:#94a3b8;font-weight:700;text-transform:uppercase;
                              letter-spacing:0.08em;margin-top:2px;">/ 100 Readiness</div>
                  <div style="font-size:12px;color:{cr_color};font-weight:600;margin-top:4px;">{cr_label}</div>
                </div>
              </div>
              <div style="height:6px;background:#1e293b;border-radius:999px;margin:18px 0 6px;">
                <div style="width:{cr_score}%;height:100%;border-radius:999px;
                            background:linear-gradient(90deg,{cr_color}88,{cr_color});"></div>
              </div>
              <div style="display:flex;flex-wrap:wrap;gap:8px;margin-top:14px;">{chips_html}</div>
              <div style="display:flex;flex-wrap:wrap;gap:24px;margin-top:20px;
                          padding-top:16px;border-top:1px solid #1e293b;">
                <div style="text-align:center;">
                  <div style="font-size:18px;font-weight:700;color:#f0f4ff;">{recency_days}d</div>
                  <div style="font-size:10px;color:#64748b;">Last Order</div>
                </div>
                <div style="text-align:center;">
                  <div style="font-size:18px;font-weight:700;color:#f0f4ff;">{_fmt(total_pot_yearly)}</div>
                  <div style="font-size:10px;color:#64748b;">Potential/yr</div>
                </div>
                <div style="text-align:center;">
                  <div style="font-size:18px;font-weight:700;color:{churn_hi_color};">{churn_prob*100:.0f}%</div>
                  <div style="font-size:10px;color:#64748b;">Churn Risk</div>
                </div>
                <div style="text-align:center;">
                  <div style="font-size:18px;font-weight:700;color:#f0f4ff;">{health_segment}</div>
                  <div style="font-size:10px;color:#64748b;">Health</div>
                </div>
                <div style="text-align:center;">
                  <div style="font-size:18px;font-weight:700;color:#f0f4ff;">{recent_txns}</div>
                  <div style="font-size:10px;color:#64748b;">Recent Txns</div>
                </div>
                <div style="text-align:center;">
                  <div style="font-size:18px;font-weight:700;color:#f0f4ff;">{_fmt(fc_next_30d)}</div>
                  <div style="font-size:10px;color:#64748b;">Forecast 30d</div>
                </div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # ── Build SPIN content ────────────────────────────────────────────────
        recency_txt = (
            f"their last order was <b>{recency_days} days ago</b>"
            if recency_days > 30
            else "they've been ordering regularly"
        )

        # ── SITUATION ─────────────────────────────────────────────────────────
        spin_s_main = (
            f"Open by demonstrating you know this account. {recency_txt}. "
            f"They're a <b>{cluster_type}</b> account in the <b>{cluster_name}</b> cluster, "
            f"operating in <b>{_state_str}</b>."
            f"<br><br><span style='color:#93c5fd;font-style:italic;'>"
            f"&ldquo;We've been tracking your account closely &mdash; you've been a "
            f"consistent {cluster_type.lower()} buyer in {_state_str}. "
            f"Before I get into what I've prepared for you, I want to understand &mdash; "
            f"how's business holding up this quarter? "
            f"Any shifts in what your end customers are asking for?&rdquo;</span>"
        )
        spin_s_alt = [
            (f"&ldquo;We work with a lot of distributors in {_state_str} &mdash; you're one of "
             f"our more established ones. How has demand been trending for you in the last 60 days?&rdquo;"),
            (f"&ldquo;I looked at your history before this call &mdash; {active_months} months of "
             f"business with us. What's changed most in how you're sourcing inventory lately?&rdquo;"),
        ]
        spin_s_expected = "Partner shares business context, order volumes, customer demand trends."
        spin_s_coach = "Don't start with a pitch. Don't reference internal system names or ML scores."

        # ── PROBLEM ───────────────────────────────────────────────────────────
        if drop > 5:
            spin_p_main = (
                f"Their orders dropped <b>{drop:.1f}%</b> over the last 90 days. "
                f"<b>Don't call it out bluntly</b> &mdash; frame it as curiosity, not accusation."
                f"<br><br><span style='color:#fca5a5;font-style:italic;'>"
                f"&ldquo;We noticed a pattern in your order flow &mdash; it's been lighter than usual "
                f"over the past few months. Is that a planned inventory adjustment, or is there something "
                f"on the demand side we should understand &mdash; like your customers pulling back?&rdquo;</span>"
            )
            spin_p_objections = [
                ("We're fine, just managing stock",
                 "Great &mdash; smart move. What's driving that? Cash flow, demand uncertainty, or supplier diversification?"),
                ("We have another supplier now",
                 "That's fair. What are they doing differently? I want to make sure we're matching or beating what you're getting elsewhere."),
            ]
        elif not gaps.empty:
            spin_p_main = (
                f"Similar <b>{cluster_name}</b> peers regularly stock <b>{missing_cat}</b>, "
                f"but this partner hasn't picked it up yet &mdash; a clear gap."
                f"<br><br><span style='color:#fca5a5;font-style:italic;'>"
                f"&ldquo;Your peers in the same market have been doing really well with {missing_cat}. "
                f"Have you had a chance to test that category, or has something made it tricky "
                f"to add to your range?&rdquo;</span>"
            )
            spin_p_objections = [
                ("We don't have demand for it",
                 f"Interesting &mdash; your peers are generating consistent demand for it. Could the gap be in awareness with your end customers?"),
                (f"{missing_cat} has low margins",
                 f"Good point. Let me show you the actual margin picture for {missing_cat} in your cluster &mdash; it might surprise you."),
            ]
        else:
            spin_p_main = (
                f"Use exploratory probing to surface hidden friction that data can't fully capture."
                f"<br><br><span style='color:#fca5a5;font-style:italic;'>"
                f"&ldquo;Most distributors right now are dealing with two or three pain points: "
                f"tighter credit cycles, slower-moving SKUs, or customer consolidation. "
                f"Which of those &mdash; if any &mdash; are you experiencing?&rdquo;</span>"
            )
            spin_p_objections = [
                ("Things are good",
                 "Good to hear. But most healthy distributors still have one or two categories not quite where they want them. What's yours?"),
                ("Credit is tight",
                 "Understood. That's actually something we can work on together &mdash; there are ways to structure orders that free up working capital."),
            ]
        spin_p_alt = [
            ("&ldquo;What's the single biggest friction in your supply chain right now? "
             "Not about us &mdash; just in general.&rdquo;"),
            (f"&ldquo;If you could change one thing about how you're sourcing {missing_cat}, "
             f"what would it be?&rdquo;"),
        ]
        spin_p_expected = "Partner reveals a blocker, pain point, or gap they hadn't fully articulated."
        spin_p_coach = "Never say 'your numbers are down' or 'you're underperforming'. Frame as observation + curiosity."

        # ── IMPLICATION ───────────────────────────────────────────────────────
        if top_gap_monthly and total_pot_yearly > 10000:
            spin_i_main = (
                f"Make the cost of inaction concrete &mdash; <b>{_fmt(total_pot_yearly)}/year</b> "
                f"is left on the table."
                f"<br><br><span style='color:#fcd34d;font-style:italic;'>"
                f"&ldquo;Here's what the data shows: partners just like you &mdash; same market, "
                f"same buying profile &mdash; are generating an extra {top_gap_monthly} every month "
                f"from {missing_cat} alone. Over a year, that's {_fmt(total_pot_yearly)} in revenue "
                f"you're not capturing. What would even half of that number mean for your business?&rdquo;</span>"
            )
        elif churn_prob > 0.5:
            spin_i_main = (
                f"The churn signal is elevated at <b>{churn_prob*100:.0f}%</b>. "
                f"Make the stakes tangible without being alarmist."
                f"<br><br><span style='color:#fcd34d;font-style:italic;'>"
                f"&ldquo;When we see partners slow down the way yours has, the pattern we usually "
                f"see next is supplier consolidation &mdash; businesses cut to two or three core "
                f"suppliers. The ones who stay on the list are the ones who showed up with something "
                f"concrete. I don't want you to cut us &mdash; and I don't think you want to. "
                f"So let's talk about what it would take to lock in that relationship.&rdquo;</span>"
            )
        else:
            spin_i_main = (
                f"The account is stable &mdash; use forward-looking implication to create "
                f"urgency around opportunity cost."
                f"<br><br><span style='color:#fcd34d;font-style:italic;'>"
                f"&ldquo;Right now, everything looks solid &mdash; which is exactly the right "
                f"time to expand. The distributors who grow the most are the ones who diversified "
                f"their product mix early. If you wait until demand forces your hand, the margins "
                f"shrink and competition is already there. What categories are you thinking about "
                f"for the next two quarters?&rdquo;</span>"
            )
        spin_i_alt = [
            ("&ldquo;If nothing changes over the next six months, what does your business look like? "
             "Is that okay with you?&rdquo;"),
            (f"&ldquo;What happens to your customer relationships if a competitor starts stocking "
             f"{missing_cat} in your area before you do?&rdquo;"),
        ]
        spin_i_expected = "Partner feels urgency, starts thinking about cost of inaction, asks 'what do you recommend?'"
        spin_i_coach = "Never use fear as the primary lever. Frame as opportunity cost, not threat. Avoid the word 'churn'."

        # ── NEED-PAYOFF ───────────────────────────────────────────────────────
        _credit_suffix = (
            " We can also restructure your credit terms to free up working capital."
            if credit_score > 0.3 else ""
        )
        pitch_txt = pitch if pitch and pitch not in ("None", "N/A", "") else missing_cat
        _conf_txt = f" &mdash; our data shows a {pitch_conf*100:.0f}% likelihood you'd move it" if pitch_conf > 0.1 else ""
        _lift_txt = f" with {pitch_lift:.1f}x lift over base rate" if pitch_lift > 1.1 else ""
        spin_n_main = (
            f"Close on a concrete, low-risk action that eliminates second-guessing."
            f"<br><br><span style='color:#6ee7b7;font-style:italic;'>"
            f"&ldquo;Here's what I want to do: let's set you up with a trial allocation of "
            f"<b>{pitch_txt}</b>{_conf_txt}{_lift_txt}. "
            f"No minimum commitment &mdash; just a pilot. "
            f"If it moves with your customers in the first 30 days, we lock you in with priority "
            f"stock so you're never caught out. If it doesn't move, we pull it back &mdash; "
            f"no pressure.{_credit_suffix} "
            f"Can we confirm the first order before the end of the week?&rdquo;</span>"
        )
        spin_n_alt = [
            "&ldquo;What would make this an easy yes for you today? I want to make sure the terms work.&rdquo;",
            (f"&ldquo;If margins or credit were not a concern, would you move on this? "
             f"Let's talk about how to make those not a concern.&rdquo;"),
        ]
        spin_n_expected = "Partner agrees to trial, asks about process, or requests a proposal."
        spin_n_coach = "Never say 'if you're interested'. Assume interest. Ask for a specific commitment with a deadline."

        # ── Assembble SPIN block definitions ──────────────────────────────────
        spin_blocks = [
            {
                "icon": "S", "label": "Situation",
                "sublabel": "Establish context. Show you know them.",
                "color": "#3b82f6", "bg": "#1e3a5f22", "border": "#3b82f644",
                "main": spin_s_main, "alts": spin_s_alt,
                "expected": spin_s_expected, "coach": spin_s_coach,
                "goal": "Build rapport. Get them talking. Uncover current state.",
                "timing": "2\u20133 min", "objections": [],
            },
            {
                "icon": "P", "label": "Problem",
                "sublabel": "Surface the real pain \u2014 don\u2019t assume.",
                "color": "#ef4444", "bg": "#2b0a0a22", "border": "#ef444444",
                "main": spin_p_main, "alts": spin_p_alt,
                "expected": spin_p_expected, "coach": spin_p_coach,
                "goal": "Identify a specific pain point or gap they acknowledge.",
                "timing": "3\u20135 min", "objections": spin_p_objections,
            },
            {
                "icon": "I", "label": "Implication",
                "sublabel": "Make the cost of inaction real and personal.",
                "color": "#f59e0b", "bg": "#2b220022", "border": "#f59e0b44",
                "main": spin_i_main, "alts": spin_i_alt,
                "expected": spin_i_expected, "coach": spin_i_coach,
                "goal": "Partner feels urgency. They start asking what to do.",
                "timing": "3\u20134 min", "objections": [],
            },
            {
                "icon": "N", "label": "Need-Payoff",
                "sublabel": "Confirm the solution. Get a concrete next step.",
                "color": "#10b981", "bg": "#0d2b1a22", "border": "#10b98144",
                "main": spin_n_main, "alts": spin_n_alt,
                "expected": spin_n_expected, "coach": spin_n_coach,
                "goal": "Specific commitment: trial order, proposal, or callback.",
                "timing": "2\u20133 min", "objections": [],
            },
        ]

        section_header("SPIN Selling Script")

        for blk in spin_blocks:
            c = blk["color"]
            # Header
            st.markdown(
                f'<div style="display:flex;align-items:flex-start;gap:16px;padding:20px 22px;'
                f'margin-bottom:0;background:linear-gradient(135deg,{blk["bg"]},rgba(0,0,0,0));'
                f'border:1px solid {blk["border"]};border-bottom:none;border-radius:12px 12px 0 0;">'
                f'<div style="flex-shrink:0;width:40px;height:40px;background:{c};border-radius:50%;'
                f'display:flex;align-items:center;justify-content:center;font-weight:900;font-size:18px;'
                f'color:#fff;box-shadow:0 0 18px {c}55;line-height:1;">{blk["icon"]}</div>'
                f'<div style="flex:1;">'
                f'<div style="font-size:16px;font-weight:800;color:{c};letter-spacing:0.04em;">{blk["label"]}</div>'
                f'<div style="font-size:12px;color:#94a3b8;margin-top:2px;">{blk["sublabel"]}</div>'
                f'</div>'
                f'<div style="display:flex;flex-direction:column;align-items:flex-end;gap:4px;">'
                f'<div style="font-size:10px;color:{c};background:{c}18;border:1px solid {c}33;'
                f'border-radius:20px;padding:2px 10px;font-weight:700;text-transform:uppercase;'
                f'letter-spacing:0.06em;">&#x23F1; {blk["timing"]}</div>'
                f'<div style="font-size:10px;color:#475569;">Goal: {blk["goal"]}</div>'
                f'</div></div>',
                unsafe_allow_html=True,
            )
            # Script body
            st.markdown(
                f'<div style="padding:18px 22px 20px;background:rgba(15,20,40,0.6);'
                f'border:1px solid {blk["border"]};border-top:1px dashed {c}33;border-bottom:none;">'
                f'<div style="font-size:12px;font-weight:700;color:#475569;text-transform:uppercase;'
                f'letter-spacing:0.08em;margin-bottom:8px;">&#x1F4DD; Script</div>'
                f'<div style="font-size:14px;line-height:1.85;color:#e2e8f0;">{blk["main"]}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
            # Expected response row
            st.markdown(
                f'<div style="padding:12px 22px;background:rgba(255,255,255,0.02);'
                f'border:1px solid {blk["border"]};border-top:none;border-bottom:none;">'
                f'<span style="font-size:11px;font-weight:700;color:#10b981;text-transform:uppercase;'
                f'letter-spacing:0.07em;">&#x1F4AC; Expected Response: </span>'
                f'<span style="font-size:12px;color:#94a3b8;">{blk["expected"]}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )
            # Voice coach warning
            st.markdown(
                f'<div style="padding:10px 22px;background:#1a0a0018;'
                f'border:1px solid #ef444422;border-top:none;border-bottom:none;">'
                f'<span style="font-size:11px;font-weight:700;color:#ef4444;text-transform:uppercase;'
                f'letter-spacing:0.07em;">&#x1F6AB; Voice Coach: </span>'
                f'<span style="font-size:12px;color:#94a3b8;">{blk["coach"]}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )
            # Alt phrases + objection handlers expander
            alts_html = "".join(
                f'<div style="font-size:12px;color:#93c5fd;font-style:italic;'
                f'border-left:3px solid #3b82f633;padding:6px 10px;margin-bottom:6px;">{a}</div>'
                for a in blk["alts"]
            )
            obj_html = ""
            if blk["objections"]:
                obj_html = (
                    '<div style="margin-top:12px;">'
                    '<div style="font-size:11px;font-weight:700;color:#f59e0b;'
                    'text-transform:uppercase;letter-spacing:0.07em;margin-bottom:8px;">'
                    '&#x1F6E1; Objection Handlers</div>'
                )
                for obj, resp in blk["objections"]:
                    obj_html += (
                        f'<div style="margin-bottom:10px;">'
                        f'<div style="font-size:12px;font-weight:600;color:#fcd34d;">&ldquo; {obj}</div>'
                        f'<div style="font-size:12px;color:#94a3b8;padding-left:14px;margin-top:3px;">'
                        f'&#x21B3; {resp}</div>'
                        f'</div>'
                    )
                obj_html += "</div>"

            with st.expander("&#x1F501; Alt Phrases & Objection Handlers"):
                st.markdown(
                    f'<div style="padding:14px 0;">'
                    f'<div style="font-size:11px;font-weight:700;color:#64748b;text-transform:uppercase;'
                    f'letter-spacing:0.07em;margin-bottom:8px;">Alternative Phrasings</div>'
                    f'{alts_html}{obj_html}'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            # Bottom accent bar
            st.markdown(
                f'<div style="height:4px;background:linear-gradient(90deg,{c}88,transparent);'
                f'border:1px solid {blk["border"]};border-top:none;'
                f'border-radius:0 0 12px 12px;margin-bottom:22px;"></div>',
                unsafe_allow_html=True,
            )

        # ── Follow-Up Action Plan ─────────────────────────────────────────────
        st.markdown("<div style='margin-top:10px;'></div>", unsafe_allow_html=True)
        section_header("Post-Call Action Plan")

        if health_segment in ("Critical", "At Risk") or churn_prob > 0.6:
            urgency_color = "#ef4444"
            urgency_label = "URGENT \u2014 Act within 24 hours"
            followup_steps = [
                ("1h",  "&#x1F4DE;", f"Send WhatsApp/SMS confirming discussion \u2014 personalised, not templated"),
                ("24h", "&#x1F4E7;", f"Email 1-page proposal: trial of {pitch_txt}, pricing and terms"),
                ("48h", "&#x1F4CA;", "Check if order was placed. If not, escalate to account manager"),
                ("7d",  "&#x1F501;", "Review new order data. Check if churn indicators improved"),
                ("30d", "&#x1F4C8;", "Re-run partner report. Update SPIN script for next cycle"),
            ]
        elif not gaps.empty:
            urgency_color = "#f59e0b"
            urgency_label = "MONITOR \u2014 Follow up within 48 hours"
            followup_steps = [
                ("2h",  "&#x1F4AC;", f"Send a quick note referencing the {missing_cat} gap discussion"),
                ("48h", "&#x1F4E7;", f"Share 1-pager on {missing_cat} \u2014 margin data, peer benchmark, trial terms"),
                ("5d",  "&#x1F4DE;", "Call to confirm receipt and answer any product/credit questions"),
                ("14d", "&#x1F501;", "Check if first trial order was placed. Offer to facilitate logistics"),
                ("30d", "&#x1F4CA;", "Review order data \u2014 did the trial convert? Expand or pivot"),
            ]
        else:
            urgency_color = "#10b981"
            urgency_label = "STABLE \u2014 Standard follow-up cadence"
            followup_steps = [
                ("24h", "&#x1F4AC;", "Reconnect message: summarise the conversation, express appreciation"),
                ("7d",  "&#x1F4E7;", "Share one relevant insight: new product, market trend, or peer benchmark"),
                ("14d", "&#x1F4CA;", "Check system for any new order signals or health changes"),
                ("30d", "&#x1F501;", "Run a fresh SPIN session \u2014 update script based on new data"),
            ]

        followup_html = "".join(
            f'<div style="display:flex;align-items:flex-start;gap:14px;margin-bottom:12px;">'
            f'<div style="flex-shrink:0;background:{urgency_color}22;border:1px solid {urgency_color}44;'
            f'border-radius:8px;padding:4px 10px;min-width:42px;text-align:center;'
            f'font-size:11px;font-weight:700;color:{urgency_color};">{timing}</div>'
            f'<div style="font-size:20px;flex-shrink:0;">{emoji}</div>'
            f'<div style="font-size:13px;color:#cbd5e1;line-height:1.6;">{desc}</div>'
            f'</div>'
            for timing, emoji, desc in followup_steps
        )
        st.markdown(
            f'<div style="background:#0f1420;border:1px solid {urgency_color}33;'
            f'border-radius:12px;padding:20px 22px;margin-bottom:24px;">'
            f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:16px;">'
            f'<div style="width:10px;height:10px;border-radius:50%;background:{urgency_color};'
            f'box-shadow:0 0 8px {urgency_color};"></div>'
            f'<div style="font-size:12px;font-weight:700;color:{urgency_color};'
            f'text-transform:uppercase;letter-spacing:0.08em;">{urgency_label}</div>'
            f'</div>{followup_html}</div>',
            unsafe_allow_html=True,
        )

        # ── Full Copyable Script ───────────────────────────────────────────────
        section_header("Full Call Script \u2014 Copy & Customise")

        def _spin_strip(s):
            import re as _re
            for tag in ["<b>", "</b>", "<i>", "</i>", "<br>", "<br/>"]:
                s = s.replace(tag, "")
            s = _re.sub(r"<span[^>]*>|</span>", "", s)
            for e, r in [
                ("&ldquo;", '"'), ("&rdquo;", '"'), ("&mdash;", "\u2014"),
                ("&middot;", "\u00b7"), ("&nbsp;", " "),
            ]:
                s = s.replace(e, r)
            return _re.sub(r"<[^>]+>", "", s).strip()

        full_script = "\n".join([
            f"SPIN SELLING SCRIPT \u2014 {selected_partner}",
            "=" * 60,
            f"Account : {selected_partner}",
            f"Type    : {cluster_type}  |  Cluster: {cluster_name}  |  Region: {_state_str}",
            f"Health  : {health_segment}  |  Churn Risk: {churn_prob*100:.0f}%  |  Last Order: {recency_days}d ago",
            f"Potential: {_fmt(total_pot_yearly)}/year  |  Forecast 30d: {_fmt(fc_next_30d)}",
            "",
            "-" * 60,
            "[S] SITUATION",
            "-" * 60,
            _spin_strip(spin_s_main),
            "",
            "Alt 1: " + _spin_strip(spin_s_alt[0]),
            "Alt 2: " + _spin_strip(spin_s_alt[1]),
            "Expected: " + spin_s_expected,
            "\u26a0 Coach: " + spin_s_coach,
            "",
            "-" * 60,
            "[P] PROBLEM",
            "-" * 60,
            _spin_strip(spin_p_main),
            "",
            "Alt 1: " + _spin_strip(spin_p_alt[0]),
            "Alt 2: " + _spin_strip(spin_p_alt[1]),
            "Expected: " + spin_p_expected,
            "\u26a0 Coach: " + spin_p_coach,
            "",
            "-" * 60,
            "[I] IMPLICATION",
            "-" * 60,
            _spin_strip(spin_i_main),
            "",
            "Alt 1: " + _spin_strip(spin_i_alt[0]),
            "Alt 2: " + _spin_strip(spin_i_alt[1]),
            "Expected: " + spin_i_expected,
            "\u26a0 Coach: " + spin_i_coach,
            "",
            "-" * 60,
            "[N] NEED-PAYOFF",
            "-" * 60,
            _spin_strip(spin_n_main),
            "",
            "Alt 1: " + _spin_strip(spin_n_alt[0]),
            "Alt 2: " + _spin_strip(spin_n_alt[1]),
            "Expected: " + spin_n_expected,
            "\u26a0 Coach: " + spin_n_coach,
            "",
            "=" * 60,
            "POST-CALL: " + urgency_label,
            "-" * 60,
        ] + [f"[{t}] {_spin_strip(d)}" for t, _, d in followup_steps])

        with st.expander("&#x1F4C4; View & Copy Full Script", expanded=False):
            st.code(full_script, language=None)
            st.caption(
                "&#x1F4A1; Click the copy icon (top-right) to copy the full script. "
                "Replace [Contact Name] and [Day/Time] before sending."
            )

        # ── Call Readiness Tips ───────────────────────────────────────────────
        if cr_score < 70:
            with st.expander("&#x1F4A1; How to improve your Call Readiness Score"):
                if recency_days >= 90:
                    st.markdown("&#x1F535; **Verify recent data:** Check if this partner has placed "
                                "any orders not yet captured in the system.")
                if gaps.empty:
                    st.markdown("&#x1F535; **Run peer-gap analysis:** Ensure the clustering model "
                                "has run for this partner's segment.")
                if not (pitch and pitch not in ("None", "N/A", "")):
                    st.markdown("&#x1F535; **Enable association rules:** The affinity pitch requires "
                                "association mining to be completed.")
                if active_months < 3:
                    st.markdown("&#x1F535; **More history needed:** Limited purchase history — "
                                "supplement the script with CRM notes.")

    # ─────────────────────────────────────────────────────────────────────────
    # TAB 5 — Similar Partners
    # ─────────────────────────────────────────────────────────────────────────
    with _tab_sim:
        if hasattr(ai, "get_similar_partners"):
            try:
                similar = ai.get_similar_partners(selected_partner, top_k=5)
            except Exception:
                similar = []
            if similar:
                section_header("Similar Partners (SVD Similarity)")
                sim_df = pd.DataFrame(similar)
                st.caption(
                    f"Partners with the most similar buying patterns to **{selected_partner}**, "
                    "ranked by cosine similarity in product-group embedding space."
                )
                st.dataframe(
                    sim_df.rename(columns={
                        "partner": "Partner",
                        "similarity": "Similarity",
                        "cluster_label": "Cluster",
                        "cluster_type": "Type",
                    }),
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.info("No similar partners data available. Ensure graph embeddings are enabled.")
        else:
            st.info("SVD similarity model not loaded.")
