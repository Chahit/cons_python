"""Patch partner_360.py: replace old flat churn block (lines 168-205, 1-indexed) with rich v2 UI."""

NEW_BLOCK = '''    # ── Churn Risk Intelligence v2 ──────────────────────────────────────────
    churn_data = report.get("churn_reasons", {})
    if isinstance(churn_data, list):
        churn_signals = churn_data
        composite_score = 0; risk_level = "Unknown"; risk_label = ""
        score_breakdown = {}; top_signal = churn_signals[0] if churn_signals else None
        outreach_script = ""; peer_ctx = {}; rec_label = "Rs0"
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
        _rl_color = (
            "#ef4444" if risk_level == "Critical" else
            "#f59e0b" if risk_level == "High" else
            "#6366f1" if risk_level == "Medium" else "#22c55e"
        )
        _pct = max(0, min(100, composite_score))
        _bar = (
            f"<div style=\\'background:#1e2433;border-radius:6px;height:10px;"
            f"margin:8px 0 4px;overflow:hidden;\\'>"
            f"<div style=\\'width:{_pct}%;height:100%;border-radius:6px;"
            f"background:linear-gradient(90deg,{_rl_color}88,{_rl_color});\\'></div></div>"
        )
        _sub = ""
        for _cn, _cv in score_breakdown.items():
            _sp = int(min(100, _cv / 0.3))
            _sub += (
                f"<div style=\\'display:flex;align-items:center;gap:6px;margin-bottom:3px;\\'>"
                f"<div style=\\'width:85px;font-size:11px;color:#94a3b8;text-align:right;\\'>{_cn}</div>"
                f"<div style=\\'flex:1;background:#1e2433;border-radius:4px;height:6px;\\'>"
                f"<div style=\\'width:{_sp}%;background:{_rl_color};border-radius:4px;height:6px;\\'></div></div>"
                f"<div style=\\'font-size:11px;color:{_rl_color};width:22px;\\'>{int(_cv)}</div></div>"
            )
        st.markdown(
            f"<div style=\\'background:#0f1420;border:1px solid {_rl_color}55;"
            f"border-radius:12px;padding:20px;margin-bottom:18px;\\'>"
            f"<div style=\\'display:flex;align-items:flex-start;justify-content:space-between;"
            f"flex-wrap:wrap;gap:12px;margin-bottom:14px;\\'>"
            f"<div><div style=\\'font-size:16px;font-weight:700;color:{_rl_color};\\'>"
            f"&#9888; Churn Risk Intelligence</div>"
            f"<div style=\\'font-size:12px;color:#64748b;margin-top:2px;\\'>"
            f"Why this partner is at risk with peer context and actionable steps</div></div>"
            f"<div style=\\'text-align:center;background:{_rl_color}18;border:1px solid {_rl_color}44;"
            f"border-radius:10px;padding:10px 18px;min-width:110px;\\'>"
            f"<div style=\\'font-size:28px;font-weight:800;color:{_rl_color};line-height:1;\\'>{composite_score}</div>"
            f"<div style=\\'font-size:10px;color:#94a3b8;font-weight:600;text-transform:uppercase;"
            f"letter-spacing:0.5px;margin-top:3px;\\'>/ 100 Risk</div>"
            f"<div style=\\'font-size:11px;color:{_rl_color};margin-top:4px;font-weight:600;\\'>{risk_level}</div>"
            f"</div></div>{_bar}"
            f"<div style=\\'font-size:11px;color:#64748b;margin-bottom:12px;\\'>{risk_label}</div>"
            f"<div style=\\'background:#161b2a;border-radius:8px;padding:12px;\\'>"
            f"<div style=\\'font-size:11px;color:#94a3b8;font-weight:600;margin-bottom:8px;"
            f"text-transform:uppercase;letter-spacing:0.5px;\\'>Score Breakdown</div>"
            f"{_sub}</div></div>",
            unsafe_allow_html=True,
        )

        if top_signal:
            _tc = _sev_c.get(top_signal.get("severity", "high"), "#f59e0b")
            st.markdown(
                f"<div style=\\'background:{_tc}12;border:1px solid {_tc}55;"
                f"border-left:5px solid {_tc};border-radius:10px;padding:16px;margin-bottom:14px;\\'>"
                f"<div style=\\'display:flex;align-items:center;gap:8px;margin-bottom:6px;\\'>"
                f"<span style=\\'font-size:15px;font-weight:800;color:{_tc};\\'>"
                f"&#127919; #1 Priority - {top_signal.get(\\'signal\\', \\'\\')}</span>"
                f"<span style=\\'font-size:10px;padding:2px 8px;border-radius:12px;"
                f"background:{_tc}22;color:{_tc};font-weight:700;text-transform:uppercase;\\'>"
                f"{top_signal.get(\\'severity\\', \\'high\\').upper()}</span></div>"
                f"<div style=\\'font-size:13px;color:#cbd5e1;margin-bottom:10px;\\'>"
                f"{top_signal.get(\\'detail\\', \\'\\')}</div>"
                f"<div style=\\'background:#ffffff0a;border-radius:6px;padding:10px 12px;\\'>"
                f"<span style=\\'color:#22c55e;font-weight:700;font-size:12px;\\'>&#9654; RECOMMENDED ACTION:</span>"
                f"<div style=\\'color:#e2e8f0;font-size:13px;margin-top:4px;\\'>"
                f"{top_signal.get(\\'action\\', \\'\\')}</div></div></div>",
                unsafe_allow_html=True,
            )

        _others = [s for s in churn_signals if s is not top_signal]
        if _others:
            _chips = "".join([
                f"<span style=\\'display:inline-block;padding:4px 10px;border-radius:20px;"
                f"background:{_sev_c.get(s.get(\\'severity\\',\\'medium\\'),\\'#6366f1\\')}18;"
                f"color:{_sev_c.get(s.get(\\'severity\\',\\'medium\\'),\\'#6366f1\\')};"
                f"border:1px solid {_sev_c.get(s.get(\\'severity\\',\\'medium\\'),\\'#6366f1\\')}44;"
                f"font-size:12px;font-weight:600;margin:3px;\\'>{s.get(\\'signal\\',\\'\\')}</span>"
                for s in _others
            ])
            st.markdown(
                f"<div style=\\'margin-bottom:14px;\\'>"
                f"<div style=\\'font-size:11px;color:#64748b;font-weight:600;"
                f"text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px;\\'>"
                f"Other Contributing Signals</div>{_chips}</div>",
                unsafe_allow_html=True,
            )
            with st.expander("View all signal details and actions"):
                for _s in _others:
                    st.markdown(
                        f"**{_s.get(\\'signal\\', \\'\\'')}** ({_s.get(\\'severity\\', \\'\\').upper()})  \\n"
                        f"{_s.get(\\'detail\\', \\'\\'')}  \\n"
                        f"Action: {_s.get(\\'action\\', \\'\\'')}",
                    )
                    st.divider()

        if peer_ctx:
            _pd = peer_ctx.get("pct_vs_peer", 0)
            _pc = "#ef4444" if _pd < -20 else "#f59e0b" if _pd < 0 else "#22c55e"
            _cd = peer_ctx.get("this_cats", 0) - peer_ctx.get("peer_avg_cats", 0)
            _cc = "#ef4444" if _cd < -1 else "#f59e0b" if _cd < 0 else "#22c55e"
            st.markdown(
                f"<div style=\\'background:#161b2a;border-radius:8px;padding:14px 16px;"
                f"margin-bottom:14px;display:flex;flex-wrap:wrap;gap:16px;align-items:center;\\'>"
                f"<div style=\\'font-size:11px;color:#94a3b8;font-weight:600;"
                f"text-transform:uppercase;letter-spacing:0.5px;width:100%;margin-bottom:4px;\\'>"
                f"Peer Benchmark - {peer_ctx.get(\\'cluster_label\\',\\'Cluster\\')} "
                f"({peer_ctx.get(\\'peer_count\\',0)} peers)</div>"
                f"<div style=\\'text-align:center;\\'>"
                f"<div style=\\'font-size:20px;font-weight:700;color:#e2e8f0;\\'>"
                f"{peer_ctx.get(\\'this_rev_fmt\\',\\'Rs0\\')}</div>"
                f"<div style=\\'font-size:11px;color:#64748b;\\'>This partner (90d)</div></div>"
                f"<div style=\\'font-size:20px;color:#334155;\\'>vs</div>"
                f"<div style=\\'text-align:center;\\'>"
                f"<div style=\\'font-size:20px;font-weight:700;color:#94a3b8;\\'>"
                f"{peer_ctx.get(\\'peer_avg_rev_fmt\\',\\'Rs0\\')}</div>"
                f"<div style=\\'font-size:11px;color:#64748b;\\'>Cluster avg (90d)</div></div>"
                f"<div style=\\'background:{_pc}18;padding:6px 14px;border-radius:20px;"
                f"font-weight:700;font-size:13px;color:{_pc};border:1px solid {_pc}44;\\'>"
                f"{_pd:+.0f}% vs peers</div>"
                f"<div style=\\'margin-left:auto;font-size:12px;color:#64748b;\\'>"
                f"Categories: <span style=\\'color:{_cc};font-weight:700;\\'>"
                f"{peer_ctx.get(\\'this_cats\\',0)} vs {peer_ctx.get(\\'peer_avg_cats\\',0):.0f} avg</span><br/>"
                f"Peer avg last purchase: {peer_ctx.get(\\'peer_avg_recency\\',0):.0f}d</div></div>",
                unsafe_allow_html=True,
            )

        _r1, _r2 = st.columns([1, 2])
        with _r1:
            st.markdown(
                f"<div style=\\'background:#22c55e12;border:1px solid #22c55e44;"
                f"border-radius:10px;padding:16px;text-align:center;\\'>"
                f"<div style=\\'font-size:11px;color:#22c55e;font-weight:700;"
                f"text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px;\\'>"
                f"Recovery Potential</div>"
                f"<div style=\\'font-size:28px;font-weight:800;color:#22c55e;line-height:1;\\'>"
                f"{rec_label}</div>"
                f"<div style=\\'font-size:11px;color:#64748b;margin-top:6px;\\'>Estimated Yearly</div>"
                f"<div style=\\'font-size:11px;color:#64748b;margin-top:2px;\\'>"
                f"Based on historical avg revenue</div></div>",
                unsafe_allow_html=True,
            )
        with _r2:
            if outreach_script:
                with st.expander("Outreach Script - click to expand and copy"):
                    st.code(outreach_script, language=None)
                    st.caption("Customise: replace [Contact Name], [Day], [Time] before sending.")

'''

with open('frontend/tabs/partner_360.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

print(f'File has {len(lines)} lines')
# Old block: lines 168-205 (1-indexed), 0-indexed: 167 to 204 inclusive
# Keep: 0..166 + NEW_BLOCK + 205..end
before = lines[:167]
after  = lines[205:]
new_content = before + [NEW_BLOCK] + after
with open('frontend/tabs/partner_360.py', 'w', encoding='utf-8') as f:
    f.writelines(new_content)
print(f'Done. File now has {len(new_content)} lines')
