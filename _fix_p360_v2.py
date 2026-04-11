"""
Fix partner_360.py by replacing broken churn block (lines 168-332 inclusive, 1-indexed)
with clean Python that has no backslash escapes inside f-strings.
"""

CLEAN_BLOCK = """    # -- Churn Risk Intelligence v2 ---------------------------------------------
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
                        "**" + _s_sig + "** (" + _s_sev + ")\\n\\n"
                        + _s_detail + "\\n\\n"
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

"""

TARGET = "frontend/tabs/partner_360.py"

with open(TARGET, "r", encoding="utf-8") as f:
    lines = f.readlines()

print(f"Total lines: {len(lines)}")

# Hardcoded: old block = 0-indexed lines 167..331 (lines 168..332 in 1-indexed)
START = 167   # inclusive
END   = 332   # exclusive (keep from here onward)

new_lines = lines[:START] + [CLEAN_BLOCK + "\n"] + lines[END:]

with open(TARGET, "w", encoding="utf-8") as f:
    f.writelines(new_lines)

print(f"Done. File now has {len(new_lines)} lines.")

# Verify syntax
import py_compile, sys
try:
    py_compile.compile(TARGET, doraise=True)
    print("Syntax OK!")
except py_compile.PyCompileError as e:
    print(f"SYNTAX ERROR: {e}")
    sys.exit(1)
