import streamlit as st
import pandas as pd
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
    selected_state = st.selectbox("Step 1: Select State/Region", all_states)

    filtered_partners = sorted(
        ai.matrix[ai.matrix["state"] == selected_state].index.unique()
    )

    if not filtered_partners:
        st.warning("No partners found in this state with recent activity.")
        return

    selected_partner = st.selectbox("Step 2: Select Partner", filtered_partners)
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

    # ── Status Banner (with confidence + freshness badges) ───────────────────
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

    # -- Churn Risk Intelligence v2 ---------------------------------------------
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
                with st.expander("Outreach Script - click to expand and copy"):
                    st.code(outreach_script, language=None)
                    st.caption(
                        "Customise: replace [Contact Name], [Day], [Time] before sending."
                    )


    st.markdown(
        f"<div class='ui-section'>",
        unsafe_allow_html=True,
    )
    section_header("Revenue Health")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Revenue Drop", f"{drop:.1f}%", delta=f"-{drop:.1f}%", delta_color="inverse")
    with c2:
        st.metric("Unlocked Potential (Yearly)", _fmt(total_pot_yearly),
                  delta=f"Monthly {_fmt(total_pot_monthly)}", delta_color="off")
    with c3:
        st.metric("Health Score", f"{health_score:.2f}")
    with c4:
        st.metric("Est. Monthly Loss", _fmt(est_monthly_loss))
    st.markdown("</div>", unsafe_allow_html=True)

    # ── Section 2: Churn & Forecast ──────────────────────────────────────────
    st.markdown(
        f"<div class='ui-section'>",
        unsafe_allow_html=True,
    )
    section_header("Churn & Forecast")
    c5, c6, c7, c8 = st.columns(4)
    with c5:
        st.metric("Churn Probability", f"{churn_prob * 100:.1f}%")
        st.caption(f"Risk Band: {churn_band}")
    with c6:
        st.metric("Revenue At Risk (90d)", _fmt(risk_90d),
                  delta=f"Monthly {_fmt(risk_monthly)}", delta_color="off")
    with c7:
        st.metric("Forecast Next 30d", _fmt(fc_next_30d),
                  delta=f"Trend {fc_trend_pct:+.1f}%", delta_color="normal")
        st.caption(f"Confidence: {fc_conf:.2f}")
    with c8:
        st.metric("Last Activity", f"{recency_days}d ago")
    st.markdown("</div>", unsafe_allow_html=True)

    # ── Section 3: Credit Risk ───────────────────────────────────────────────
    st.markdown(
        f"<div class='ui-section'>",
        unsafe_allow_html=True,
    )
    section_header("Credit Risk")
    cr1, cr2, cr3, cr4 = st.columns(4)
    with cr1:
        st.metric("Credit Risk Score", f"{credit_score * 100:.1f}%",
                  delta=f"Band: {credit_band}", delta_color="off")
        st.caption(f"Utilization: {credit_util * 100:.1f}% | Overdue: {overdue_ratio * 100:.1f}%")
    with cr2:
        st.metric("Outstanding + Adj Risk",
            _fmt(outstanding_amt),
            delta=f"Adj Risk {_fmt(credit_adjusted_risk)}",
            delta_color="off",
        )
    st.markdown("</div>", unsafe_allow_html=True)


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

    # ── SPIN Selling Script ──────────────────────────────────────────────────
    section_header("SPIN Selling Script")

    _state_str = str(facts.get("state", "your region") or "your region")
    missing_cat = str(gaps.iloc[0]["Product"]) if not gaps.empty else "a key product category"
    top_gap_monthly = _fmt(total_pot_monthly) if total_pot_monthly > 0 else None

    recency_txt = (
        f"their last order was {recency_days} days ago"
        if recency_days > 30
        else "they've been ordering regularly"
    )
    spin_s = (
        f"When you speak with them, open with what you already know — {recency_txt}, "
        f"they're classified as a <b>{cluster_type}</b> account, and they've been buying "
        f"mostly in the <b>{cluster_name}</b> segment. "
        f"Ask something like: <i>\"You've been with us for a while now — how's business been "
        f"holding up in {_state_str} this quarter? Any pressure from your customers on pricing or availability?\"</i>"
    )

    if drop > 5:
        spin_p = (
            f"Their orders have dropped <b>{drop:.1f}%</b> in the last 90 days. "
            f"Don't call it out bluntly — instead ask: <i>\"We noticed a bit of a shift in your "
            f"order pattern over the past few months. Have you been adjusting inventory levels, "
            f"or is there something happening on the demand side with your end customers?\"</i>"
        )
    elif not gaps.empty:
        spin_p = (
            f"Similar partners in the same cluster regularly stock <b>{missing_cat}</b>, "
            f"but this partner hasn't picked it up. Try: <i>\"Your peers in the same region have "
            f"been doing well with {missing_cat} — have you had a chance to test that with your "
            f"customers, or is there a reason it hasn't fit your range yet?\"</i>"
        )
    else:
        spin_p = (
            f"Things look stable, but probe for hidden friction: "
            f"<i>\"Most distributors we speak with right now are managing tighter credit cycles and "
            f"slower-moving stock. Is that something affecting your cash flow or ordering decisions at the moment?\"</i>"
        )

    if top_gap_monthly and total_pot_yearly > 10000:
        spin_i = (
            f"This isn't abstract — the numbers show a potential <b>{_fmt(total_pot_yearly)}/year</b> "
            f"left on the table. Land it like this: <i>\"If partners similar to you are generating "
            f"an extra {top_gap_monthly} a month from {missing_cat}, and you're not in that space yet — "
            f"over a year that's a real gap. What does that kind of revenue mean for your business?\"</i>"
        )
    elif churn_prob > 0.5:
        spin_i = (
            f"Churn risk is elevated at <b>{churn_prob*100:.0f}%</b>. Make it tangible: "
            f"<i>\"When partners slow down this much, we often see them consolidate suppliers — "
            f"and the first ones cut are usually the ones they've had the least recent contact with. "
            f"Is that a concern on your side, or am I reading it wrong?\"</i>"
        )
    else:
        spin_i = (
            f"Keep it forward-looking: <i>\"Right now your numbers are solid, but the "
            f"distributors who build the most resilience are the ones who diversify their "
            f"product basket early — before demand forces them to. What categories are you "
            f"looking to grow in the next two quarters?\"</i>"
        )

    credit_txt = (
        f" We can also look at adjusting credit terms to free up working capital."
        if credit_score > 0.3
        else ""
    )
    spin_n = (
        f"Close on a concrete action, not a vague offer: "
        f"<i>\"Let's set you up with a trial allocation of {missing_cat} for next month — "
        f"no minimum commitment. If it moves, we lock in a priority schedule so you're "
        f"never out of stock when your customers ask for it.{credit_txt} Does that work for you?\"</i>"
    )

    for icon, label, color, body in [
        ("S", "Situation",   "#3b82f6", spin_s),
        ("P", "Problem",     "#ef4444", spin_p),
        ("I", "Implication", "#f59e0b", spin_i),
        ("N", "Need-Payoff", "#10b981", spin_n),
    ]:
        st.markdown(
            f"""
            <div style="display:flex;gap:14px;align-items:flex-start;
                        margin-bottom:20px;padding:16px 20px;
                        background:rgba(255,255,255,0.02);
                        border:1px solid rgba(255,255,255,0.06);
                        border-radius:10px;">
                <div style="flex-shrink:0;width:32px;height:32px;
                            background:{color};border-radius:50%;
                            display:flex;align-items:center;justify-content:center;
                            font-weight:700;font-size:14px;color:#fff;">{icon}</div>
                <div>
                    <div style="font-weight:600;font-size:13px;color:{color};
                                text-transform:uppercase;letter-spacing:0.06em;
                                margin-bottom:6px;">{label}</div>
                    <div style="font-size:14px;line-height:1.7;color:#d1d5db;">{body}</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown("<div style='height: 24px;'></div>", unsafe_allow_html=True)

    # ── Similar Partners (SVD Graph Embeddings) ──────────────────────────────
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
