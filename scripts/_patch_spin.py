#!/usr/bin/env python3
"""
Patch script: replaces TAB 4 (SPIN Selling Script) in partner_360.py
with the world-class elite implementation.
"""
import re

TARGET = r"frontend/tabs/partner_360.py"

NEW_SPIN_TAB = '''    # \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    # TAB 4 \u2014 SPIN Selling Script
    # \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    with _tab_spin:
        # \u2500\u2500 Data prep \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
        _state_str   = str(facts.get("state", "your region") or "your region")
        missing_cat  = str(gaps.iloc[0]["Product"]) if not gaps.empty else "a key product category"
        second_cat   = str(gaps.iloc[1]["Product"]) if len(gaps) > 1 else missing_cat
        top_gap_monthly   = _fmt(total_pot_monthly) if total_pot_monthly > 0 else None
        pitch         = str(facts.get("top_affinity_pitch", "") or "")
        pitch_conf    = float(facts.get("pitch_confidence",  0) or 0)
        pitch_lift    = float(facts.get("pitch_lift",        0) or 0)
        active_months = int(facts.get("active_months",       0) or 0)
        recent_txns   = int(facts.get("recent_txns",         0) or 0)

        # \u2500\u2500 Call-Readiness Score \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
        cr_score = 0
        cr_reasons = []
        if recency_days < 90:
            cr_score += 20; cr_reasons.append(("\u2705", f"Recent purchase data ({recency_days}d ago)"))
        else:
            cr_reasons.append(("\u26a0\ufe0f", f"Last order was {recency_days}d ago \u2014 data may be stale"))

        if not gaps.empty:
            cr_score += 20; cr_reasons.append(("\u2705", f"{len(gaps)} cross-sell gap(s) identified"))
        else:
            cr_reasons.append(("\u26a0\ufe0f", "No peer-gap data \u2014 script relies on general signals"))

        if pitch and pitch not in ("None", "N/A", ""):
            cr_score += 20; cr_reasons.append(("\u2705", f"Affinity pitch ready: {pitch}"))

        if active_months >= 3:
            cr_score += 20; cr_reasons.append(("\u2705", f"{active_months} months of purchase history"))
        else:
            cr_reasons.append(("\u26a0\ufe0f", "Limited purchase history"))

        if churn_prob < 0.6:
            cr_score += 10; cr_reasons.append(("\u2705", "Not in high churn zone"))
        else:
            cr_reasons.append(("\u{1F534}", f"High churn ({churn_prob*100:.0f}%) \u2014 handle carefully"))

        if credit_score < 0.5:
            cr_score += 10; cr_reasons.append(("\u2705", "Credit risk acceptable"))
        else:
            cr_reasons.append(("\u{1F534}", f"Elevated credit risk ({credit_score*100:.0f}%)"))

        cr_color = "#10b981" if cr_score >= 70 else "#f59e0b" if cr_score >= 40 else "#ef4444"
        cr_label = "Excellent" if cr_score >= 70 else "Good" if cr_score >= 40 else "Low"

        # \u2500\u2500 Pre-Call Intelligence Brief \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
        chips_html = "".join(
            f"""<div style="display:flex;align-items:center;gap:6px;
                           background:rgba(255,255,255,0.04);border-radius:20px;
                           padding:4px 12px;font-size:11px;color:#cbd5e1;">
                <span>{em}</span><span>{msg}</span></div>"""
            for em, msg in cr_reasons
        )
        st.markdown(
            f"""
            <div style="background:linear-gradient(135deg,#0f172a,#1e293b);
                        border:1px solid #334155;border-radius:16px;padding:24px;
                        margin-bottom:24px;position:relative;overflow:hidden;">
              <div style="position:absolute;top:0;left:0;right:0;height:3px;
                          background:linear-gradient(90deg,#3b82f6,#8b5cf6,#06b6d4);"></div>
              <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:16px;">
                <div>
                  <div style="font-size:10px;color:#64748b;font-weight:700;text-transform:uppercase;
                              letter-spacing:0.12em;margin-bottom:6px;">
                    \U0001F4CB Pre-Call Intelligence Brief
                  </div>
                  <div style="font-size:20px;font-weight:800;color:#f0f4ff;line-height:1.2;">
                    {selected_partner}
                  </div>
                  <div style="font-size:12px;color:#64748b;margin-top:4px;">
                    {cluster_type} account &nbsp;&middot;&nbsp; {cluster_name} &nbsp;&middot;&nbsp; {_state_str}
                  </div>
                </div>
                <div style="text-align:center;background:{cr_color}18;border:1px solid {cr_color}44;
                            border-radius:12px;padding:14px 22px;min-width:130px;">
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
              <div style="display:flex;flex-wrap:wrap;gap:8px;margin-top:14px;">
                {chips_html}
              </div>
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
                  <div style="font-size:18px;font-weight:700;color:{'#ef4444' if churn_prob>0.4 else '#f0f4ff'};">{churn_prob*100:.0f}%</div>
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

        # \u2500\u2500 Build SPIN content \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
        recency_txt = (
            f"their last order was <b>{recency_days} days ago</b>"
            if recency_days > 30
            else "they\'ve been ordering regularly"
        )

        # \u2500\u2500 SITUATION \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
        spin_s_main = (
            f"Open by demonstrating you know this account. {recency_txt}. "
            f"They\'re a <b>{cluster_type}</b> account in the <b>{cluster_name}</b> cluster, "
            f"operating in <b>{_state_str}</b>."
            f"<br><br><span style=\'color:#93c5fd;font-style:italic;\'>"
            f"&ldquo;We\'ve been tracking your account closely &mdash; you\'ve been a consistent "
            f"{cluster_type.lower()} buyer in {_state_str}. "
            f"Before I get into what I\'ve prepared for you, I want to understand &mdash; "
            f"how\'s business holding up this quarter? "
            f"Any shifts in what your end customers are asking for?&rdquo;</span>"
        )
        spin_s_alt = [
            f"&ldquo;We work with a lot of distributors in {_state_str} &mdash; you\'re one of our more established ones. "
            f"Quick question: how has demand been trending for you in the last 60 days?&rdquo;",
            f"&ldquo;I looked at your history before this call &mdash; {active_months} months of business with us. "
            f"What\'s changed most for you in how you\'re sourcing inventory lately?&rdquo;",
        ]
        spin_s_expected = "Partner shares business context, order volumes, customer demand trends."
        spin_s_coach = "Don\'t start with a pitch. Don\'t reference internal system names or ML scores."

        # \u2500\u2500 PROBLEM \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
        if drop > 5:
            spin_p_main = (
                f"Their orders dropped <b>{drop:.1f}%</b> over the last 90 days. "
                f"<b>Don\'t call it out bluntly</b> &mdash; frame it as curiosity, not accusation."
                f"<br><br><span style=\'color:#fca5a5;font-style:italic;\'>"
                f"&ldquo;We noticed a pattern in your order flow &mdash; it\'s been lighter than usual "
                f"over the past few months. "
                f"Is that a planned inventory adjustment, or is there something on the demand side "
                f"we should understand &mdash; like your customers pulling back?&rdquo;</span>"
            )
            spin_p_objections = [
                ("We\'re fine, just managing stock",
                 "Great &mdash; smart move. What\'s driving that? Cash flow, demand uncertainty, or supplier diversification?"),
                ("We have another supplier now",
                 "That\'s fair. What are they doing differently? I want to make sure we\'re matching or beating what you\'re getting elsewhere."),
            ]
        elif not gaps.empty:
            spin_p_main = (
                f"Similar <b>{cluster_name}</b> peers regularly stock <b>{missing_cat}</b>, "
                f"but this partner hasn\'t picked it up yet &mdash; a clear gap."
                f"<br><br><span style=\'color:#fca5a5;font-style:italic;\'>"
                f"&ldquo;Your peers who are in the same market as you have been doing really well with "
                f"{missing_cat}. Have you had a chance to test that category, "
                f"or has something made it tricky to add to your range?&rdquo;</span>"
            )
            spin_p_objections = [
                ("We don\'t have demand for it",
                 f"Interesting &mdash; your peers are generating consistent demand for it. Could the gap be in awareness with your end customers?"),
                ("That category has low margins",
                 f"Good point. Let me show you what the actual margin picture looks like for {missing_cat} in your cluster &mdash; it might surprise you."),
            ]
        else:
            spin_p_main = (
                f"Use exploratory probing to surface hidden friction that data can\'t fully capture."
                f"<br><br><span style=\'color:#fca5a5;font-style:italic;\'>"
                f"&ldquo;Most distributors right now are dealing with two or three pain points: "
                f"tighter credit cycles, slower-moving SKUs, or customer consolidation. "
                f"Which of those &mdash; if any &mdash; are you experiencing?&rdquo;</span>"
            )
            spin_p_objections = [
                ("Things are good",
                 "Good to hear. But most healthy distributors still have one or two categories not quite where they want them. What\'s yours?"),
                ("Credit is tight",
                 "Understood. That\'s actually something we can work on together &mdash; there are ways to structure orders that free up working capital."),
            ]
        spin_p_alt = [
            f"&ldquo;What\'s the single biggest friction in your supply chain right now? Not about us &mdash; just in general.&rdquo;",
            f"&ldquo;If you could change one thing about how you\'re sourcing {missing_cat}, what would it be?&rdquo;",
        ]
        spin_p_expected = "Partner reveals a blocker, pain point, or gap they hadn\'t fully articulated."
        spin_p_coach = "Never say \'your numbers are down\' or \'you\'re underperforming\'. Always frame as observation + curiosity."

        # \u2500\u2500 IMPLICATION \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
        if top_gap_monthly and total_pot_yearly > 10000:
            spin_i_main = (
                f"Make the cost of inaction concrete &mdash; <b>{_fmt(total_pot_yearly)}/year</b> is left on the table."
                f"<br><br><span style=\'color:#fcd34d;font-style:italic;\'>"
                f"&ldquo;Here\'s what the data shows: partners just like you &mdash; same market, same buying profile &mdash; "
                f"are generating an extra {top_gap_monthly} every month from {missing_cat} alone. "
                f"Over a year, that\'s {_fmt(total_pot_yearly)} in revenue you\'re not capturing. "
                f"What would even half of that number mean for your business?&rdquo;</span>"
            )
        elif churn_prob > 0.5:
            spin_i_main = (
                f"The churn signal is elevated at <b>{churn_prob*100:.0f}%</b>. "
                f"Make the stakes tangible without being alarmist."
                f"<br><br><span style=\'color:#fcd34d;font-style:italic;\'>"
                f"&ldquo;When we see partners slow down the way yours has, the pattern we usually see next is "
                f"supplier consolidation &mdash; businesses cut to two or three core suppliers. "
                f"The ones who stay on the list are the ones who showed up with something concrete. "
                f"I don\'t want you to cut us &mdash; and I don\'t think you want to. "
                f"So let\'s talk about what it would take to lock in that relationship.&rdquo;</span>"
            )
        else:
            spin_i_main = (
                f"The account is stable &mdash; use forward-looking implication to create urgency around opportunity cost."
                f"<br><br><span style=\'color:#fcd34d;font-style:italic;\'>"
                f"&ldquo;Right now, everything looks solid &mdash; which is exactly the right time to expand. "
                f"The distributors who grow the most are the ones who diversified their product mix early. "
                f"If you wait until demand forces your hand, the margins shrink and competition is already there. "
                f"What categories are you thinking about for the next two quarters?&rdquo;</span>"
            )
        spin_i_alt = [
            f"&ldquo;If nothing changes over the next six months, what does your business look like? Is that okay with you?&rdquo;",
            f"&ldquo;What happens to your customer relationships if a competitor starts stocking {missing_cat} in your area before you do?&rdquo;",
        ]
        spin_i_expected = "Partner feels urgency, starts thinking about cost of inaction, asks \'what do you recommend?\'"
        spin_i_coach = "Never use fear as the primary lever. Frame as opportunity cost, not threat. Avoid the word \'churn\' in conversation."

        # \u2500\u2500 NEED-PAYOFF \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
        credit_txt = (
            f" We can also look at restructuring your credit terms to free up working capital."
            if credit_score > 0.3
            else ""
        )
        pitch_txt  = pitch if pitch and pitch not in ("None", "N/A", "") else missing_cat
        conf_txt   = f" &mdash; our data shows a {pitch_conf*100:.0f}% likelihood you\'d move it" if pitch_conf > 0.1 else ""
        lift_txt   = f" with {pitch_lift:.1f}x lift over base rate" if pitch_lift > 1.1 else ""

        spin_n_main = (
            f"Close on a concrete, low-risk action that eliminates second-guessing."
            f"<br><br><span style=\'color:#6ee7b7;font-style:italic;\'>"
            f"&ldquo;Here\'s what I want to do: let\'s set you up with a trial allocation of "
            f"<b>{pitch_txt}</b>{conf_txt}{lift_txt}. "
            f"No minimum commitment &mdash; just a pilot. "
            f"If it moves with your customers in the first 30 days, we lock you in with priority stock "
            f"so you\'re never caught out. If it doesn\'t move, we pull it back &mdash; no pressure.{credit_txt} "
            f"Can we confirm the first order before the end of the week?&rdquo;</span>"
        )
        spin_n_alt = [
            f"&ldquo;What would make this an easy yes for you today? I want to make sure the terms work.&rdquo;",
            f"&ldquo;If margins or credit were not a concern, would you move on this? Let\'s talk about how to make those not a concern.&rdquo;",
        ]
        spin_n_expected = "Partner agrees to a trial, asks about process, or requests a proposal."
        spin_n_coach = "Never say \'if you\'re interested\'. Assume interest. Ask for a specific commitment with a deadline."

        # \u2500\u2500 Render SPIN cards \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
        spin_blocks = [
            {
                "icon":       "S",
                "label":      "Situation",
                "sublabel":   "Establish context. Show you know them.",
                "color":      "#3b82f6",
                "bg":         "#1e3a5f22",
                "border":     "#3b82f644",
                "main":       spin_s_main,
                "alts":       spin_s_alt,
                "expected":   spin_s_expected,
                "coach":      spin_s_coach,
                "goal":       "Build rapport. Get them talking. Uncover current state.",
                "timing":     "2\u20133 min",
                "objections": [],
            },
            {
                "icon":       "P",
                "label":      "Problem",
                "sublabel":   "Surface the real pain \u2014 don\'t assume.",
                "color":      "#ef4444",
                "bg":         "#2b0a0a22",
                "border":     "#ef444444",
                "main":       spin_p_main,
                "alts":       spin_p_alt,
                "expected":   spin_p_expected,
                "coach":      spin_p_coach,
                "goal":       "Identify a specific pain point or gap they acknowledge.",
                "timing":     "3\u20135 min",
                "objections": spin_p_objections,
            },
            {
                "icon":       "I",
                "label":      "Implication",
                "sublabel":   "Make the cost of inaction real and personal.",
                "color":      "#f59e0b",
                "bg":         "#2b220022",
                "border":     "#f59e0b44",
                "main":       spin_i_main,
                "alts":       spin_i_alt,
                "expected":   spin_i_expected,
                "coach":      spin_i_coach,
                "goal":       "Partner feels urgency. They start asking what to do.",
                "timing":     "3\u20134 min",
                "objections": [],
            },
            {
                "icon":       "N",
                "label":      "Need-Payoff",
                "sublabel":   "Confirm the solution. Get a concrete next step.",
                "color":      "#10b981",
                "bg":         "#0d2b1a22",
                "border":     "#10b98144",
                "main":       spin_n_main,
                "alts":       spin_n_alt,
                "expected":   spin_n_expected,
                "coach":      spin_n_coach,
                "goal":       "Specific commitment: trial order, proposal request, or callback.",
                "timing":     "2\u20133 min",
                "objections": [],
            },
        ]

        section_header("SPIN Selling Script")

        for blk in spin_blocks:
            c = blk["color"]
            # \u2500\u2500 Header card \u2500\u2500
            st.markdown(
                f"""<div style="display:flex;align-items:flex-start;gap:16px;
                               padding:20px 22px;margin-bottom:0;
                               background:linear-gradient(135deg,{blk[\'bg\']},rgba(0,0,0,0));
                               border:1px solid {blk[\'border\']};
                               border-bottom:none;border-radius:12px 12px 0 0;">
                  <div style="flex-shrink:0;width:40px;height:40px;background:{c};
                              border-radius:50%;display:flex;align-items:center;
                              justify-content:center;font-weight:900;font-size:18px;
                              color:#fff;box-shadow:0 0 18px {c}55;line-height:1;">{blk[\'icon\']}</div>
                  <div style="flex:1;">
                    <div style="font-size:16px;font-weight:800;color:{c};
                                letter-spacing:0.04em;">{blk[\'label\']}</div>
                    <div style="font-size:12px;color:#94a3b8;margin-top:2px;">{blk[\'sublabel\']}</div>
                  </div>
                  <div style="display:flex;flex-direction:column;align-items:flex-end;gap:4px;">
                    <div style="font-size:10px;color:{c};background:{c}18;
                                border:1px solid {c}33;border-radius:20px;padding:2px 10px;
                                font-weight:700;text-transform:uppercase;letter-spacing:0.06em;">
                      &#x23F1; {blk[\'timing\']}
                    </div>
                    <div style="font-size:10px;color:#475569;">Goal: {blk[\'goal\']}</div>
                  </div>
                </div>""",
                unsafe_allow_html=True,
            )
            # \u2500\u2500 Script body \u2500\u2500
            st.markdown(
                f"""<div style="padding:18px 22px 20px;
                               background:rgba(15,20,40,0.6);
                               border:1px solid {blk[\'border\']};
                               border-top:1px dashed {c}33;
                               border-bottom:none;">
                  <div style="font-size:12px;font-weight:700;color:#475569;
                              text-transform:uppercase;letter-spacing:0.08em;margin-bottom:8px;">
                    &#x1F4DD; Script
                  </div>
                  <div style="font-size:14px;line-height:1.85;color:#e2e8f0;">
                    {blk[\'main\']}
                  </div>
                </div>""",
                unsafe_allow_html=True,
            )
            # \u2500\u2500 Expected response \u2500\u2500
            st.markdown(
                f"""<div style="padding:12px 22px;background:rgba(255,255,255,0.02);
                               border:1px solid {blk[\'border\']};border-top:none;border-bottom:none;">
                  <span style="font-size:11px;font-weight:700;color:#10b981;
                               text-transform:uppercase;letter-spacing:0.07em;">&#x1F4AC; Expected Response: </span>
                  <span style="font-size:12px;color:#94a3b8;">{blk[\'expected\']}</span>
                </div>""",
                unsafe_allow_html=True,
            )
            # \u2500\u2500 Voice coach warning \u2500\u2500
            st.markdown(
                f"""<div style="padding:10px 22px;background:#1a0a0018;
                               border:1px solid #ef444422;border-top:none;border-bottom:none;">
                  <span style="font-size:11px;font-weight:700;color:#ef4444;
                               text-transform:uppercase;letter-spacing:0.07em;">&#x1F6AB; Voice Coach: </span>
                  <span style="font-size:12px;color:#94a3b8;">{blk[\'coach\']}</span>
                </div>""",
                unsafe_allow_html=True,
            )
            # \u2500\u2500 Alternatives + objections \u2500\u2500
            alts_html = "".join(
                f"<div style=\'font-size:12px;color:#93c5fd;font-style:italic;"
                f"border-left:3px solid #3b82f633;padding:6px 10px;margin-bottom:6px;\'>"
                f"{a}</div>"
                for a in blk["alts"]
            )
            obj_html = ""
            if blk["objections"]:
                obj_html = (
                    "<div style=\'margin-top:12px;\'>"
                    "<div style=\'font-size:11px;font-weight:700;color:#f59e0b;"
                    "text-transform:uppercase;letter-spacing:0.07em;margin-bottom:8px;\'>"
                    "&#x1F6E1; Objection Handlers</div>"
                )
                for obj, resp in blk["objections"]:
                    obj_html += (
                        f"<div style=\'margin-bottom:10px;\'>"
                        f"<div style=\'font-size:12px;font-weight:600;color:#fcd34d;\'>&ldquo; {obj}</div>"
                        f"<div style=\'font-size:12px;color:#94a3b8;padding-left:14px;margin-top:3px;\'>&#x21B3; {resp}</div>"
                        f"</div>"
                    )
                obj_html += "</div>"
            with st.expander("&#x1F501; Alt Phrases & Objection Handlers"):
                st.markdown(
                    f"""<div style="padding:14px 0;">
                      <div style="font-size:11px;font-weight:700;color:#64748b;
                                  text-transform:uppercase;letter-spacing:0.07em;margin-bottom:8px;">
                        Alternative Phrasings
                      </div>
                      {alts_html}
                      {obj_html}
                    </div>""",
                    unsafe_allow_html=True,
                )
            # \u2500\u2500 Close card \u2500\u2500
            st.markdown(
                f"""<div style="height:4px;background:linear-gradient(90deg,{c}88,transparent);
                               border:1px solid {blk[\'border\']};border-top:none;
                               border-radius:0 0 12px 12px;margin-bottom:22px;"></div>""",
                unsafe_allow_html=True,
            )

        # \u2500\u2500 Follow-Up Action Plan \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
        st.markdown("<div style=\'margin-top:10px;\'></div>", unsafe_allow_html=True)
        section_header("Post-Call Action Plan")

        if health_segment in ("Critical", "At Risk") or churn_prob > 0.6:
            urgency_color = "#ef4444"
            urgency_label = "URGENT \u2014 Act within 24 hours"
        elif health_segment == "Healthy" and drop < 5:
            urgency_color = "#10b981"
            urgency_label = "STABLE \u2014 Standard follow-up cadence"
        else:
            urgency_color = "#f59e0b"
            urgency_label = "MONITOR \u2014 Follow up within 48 hours"

        if health_segment in ("Critical", "At Risk") or churn_prob > 0.6:
            followup_steps = [
                ("1h",  "&#x1F4DE;", f"Send a WhatsApp/SMS confirming what was discussed \u2014 personalised, not templated"),
                ("24h", "&#x1F4E7;", f"Email a 1-page proposal: trial allocation of {pitch_txt}, pricing, and terms"),
                ("48h", "&#x1F4CA;", "Check if order was placed. If not, escalate to account manager for priority call"),
                ("7d",  "&#x1F501;", "Review new order data. Check if churn indicators improved"),
                ("30d", "&#x1F4C8;", "Re-run partner report. Update health score and SPIN script for next cycle"),
            ]
        elif not gaps.empty:
            followup_steps = [
                ("2h",  "&#x1F4AC;", f"Send a quick note referencing the {missing_cat} gap discussion"),
                ("48h", "&#x1F4E7;", f"Share a 1-pager on {missing_cat} \u2014 margin data, peer benchmark, trial terms"),
                ("5d",  "&#x1F4DE;", "Call to confirm receipt and answer any product/credit questions"),
                ("14d", "&#x1F501;", "Check if first trial order was placed. Offer to facilitate logistics"),
                ("30d", "&#x1F4CA;", "Review order data \u2014 did the trial convert? Expand or pivot accordingly"),
            ]
        else:
            followup_steps = [
                ("24h", "&#x1F4AC;", "Reconnect message: summarise the conversation, express appreciation"),
                ("7d",  "&#x1F4E7;", "Share one relevant insight: new product, market trend, or peer benchmark"),
                ("14d", "&#x1F4CA;", "Check system for any new order signals or health changes"),
                ("30d", "&#x1F501;", "Run a fresh SPIN session \u2014 update script based on new data"),
            ]

        followup_html = "".join(
            f"""<div style="display:flex;align-items:flex-start;gap:14px;margin-bottom:12px;">
              <div style="flex-shrink:0;background:{urgency_color}22;border:1px solid {urgency_color}44;
                          border-radius:8px;padding:4px 10px;min-width:42px;text-align:center;
                          font-size:11px;font-weight:700;color:{urgency_color};">{timing}</div>
              <div style="font-size:20px;flex-shrink:0;">{emoji}</div>
              <div style="font-size:13px;color:#cbd5e1;line-height:1.6;">{desc}</div>
            </div>"""
            for timing, emoji, desc in followup_steps
        )

        st.markdown(
            f"""<div style="background:#0f1420;border:1px solid {urgency_color}33;
                           border-radius:12px;padding:20px 22px;margin-bottom:24px;">
              <div style="display:flex;align-items:center;gap:10px;margin-bottom:16px;">
                <div style="width:10px;height:10px;border-radius:50%;background:{urgency_color};
                            box-shadow:0 0 8px {urgency_color};"></div>
                <div style="font-size:12px;font-weight:700;color:{urgency_color};
                            text-transform:uppercase;letter-spacing:0.08em;">{urgency_label}</div>
              </div>
              {followup_html}
            </div>""",
            unsafe_allow_html=True,
        )

        # \u2500\u2500 Full Script (Copyable) \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
        section_header("Full Call Script \u2014 Copy & Customise")

        def _strip_html_spin(s):
            import re as _re
            s = _re.sub(r"<b>|</b>|<i>|</i>|<br>|<br/>", "", s)
            s = _re.sub(r"<span[^>]*>|</span>", "", s)
            for ent, rep in [
                ("&ldquo;", \'"\'), ("&rdquo;", \'"\'), ("&mdash;", "\u2014"),
                ("&middot;", "\u00b7"), ("&nbsp;", " "),
            ]:
                s = s.replace(ent, rep)
            s = _re.sub(r"<[^>]+>", "", s)
            return s.strip()

        full_script = (
            f"SPIN SELLING SCRIPT \u2014 {selected_partner}\\n"
            + "=" * 60 + "\\n"
            + f"Account: {selected_partner}\\n"
            + f"Type: {cluster_type} | Cluster: {cluster_name} | Region: {_state_str}\\n"
            + f"Health: {health_segment} | Churn Risk: {churn_prob*100:.0f}% | Last Order: {recency_days}d ago\\n"
            + f"Potential: {_fmt(total_pot_yearly)}/year | Forecast 30d: {_fmt(fc_next_30d)}\\n\\n"
            + "-" * 60 + "\\n"
            + "[S] SITUATION\\n"
            + "-" * 60 + "\\n"
            + _strip_html_spin(spin_s_main) + "\\n\\n"
            + "Alt 1: " + _strip_html_spin(spin_s_alt[0]) + "\\n"
            + "Alt 2: " + _strip_html_spin(spin_s_alt[1]) + "\\n"
            + "Expected: " + spin_s_expected + "\\n"
            + "Coach: " + spin_s_coach + "\\n\\n"
            + "-" * 60 + "\\n"
            + "[P] PROBLEM\\n"
            + "-" * 60 + "\\n"
            + _strip_html_spin(spin_p_main) + "\\n\\n"
            + "Alt 1: " + _strip_html_spin(spin_p_alt[0]) + "\\n"
            + "Alt 2: " + _strip_html_spin(spin_p_alt[1]) + "\\n"
            + "Expected: " + spin_p_expected + "\\n"
            + "Coach: " + spin_p_coach + "\\n\\n"
            + "-" * 60 + "\\n"
            + "[I] IMPLICATION\\n"
            + "-" * 60 + "\\n"
            + _strip_html_spin(spin_i_main) + "\\n\\n"
            + "Alt 1: " + _strip_html_spin(spin_i_alt[0]) + "\\n"
            + "Alt 2: " + _strip_html_spin(spin_i_alt[1]) + "\\n"
            + "Expected: " + spin_i_expected + "\\n"
            + "Coach: " + spin_i_coach + "\\n\\n"
            + "-" * 60 + "\\n"
            + "[N] NEED-PAYOFF\\n"
            + "-" * 60 + "\\n"
            + _strip_html_spin(spin_n_main) + "\\n\\n"
            + "Alt 1: " + _strip_html_spin(spin_n_alt[0]) + "\\n"
            + "Alt 2: " + _strip_html_spin(spin_n_alt[1]) + "\\n"
            + "Expected: " + spin_n_expected + "\\n"
            + "Coach: " + spin_n_coach + "\\n\\n"
            + "=" * 60 + "\\n"
            + "POST-CALL: " + urgency_label + "\\n"
            + "-" * 60 + "\\n"
            + "\\n".join(
                f"[{t}] {desc}"
                for t, _, desc in followup_steps
            )
        )

        with st.expander("&#x1F4C4; View & Copy Full Script", expanded=False):
            st.code(full_script, language=None)
            st.caption(
                "&#x1F4A1; Tip: Click the copy icon (top-right of the code block) to copy everything. "
                "Replace [Contact Name] and [Day/Time] before sending."
            )

        # \u2500\u2500 Readiness Tips \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
        if cr_score < 70:
            with st.expander("&#x1F4A1; How to improve your Call Readiness Score"):
                tips = []
                if recency_days >= 90:
                    tips.append(
                        "**Verify recent data:** Check if this partner has placed any orders "
                        "not yet captured in the system."
                    )
                if gaps.empty:
                    tips.append(
                        "**Run peer-gap analysis:** Ensure the clustering model has run "
                        "for this partner\'s segment to generate cross-sell opportunities."
                    )
                if not (pitch and pitch not in ("None", "N/A", "")):
                    tips.append(
                        "**Enable association rules:** The affinity pitch requires association "
                        "mining to be completed for this partner\'s top product categories."
                    )
                if active_months < 3:
                    tips.append(
                        "**More history needed:** This partner has limited purchase history. "
                        "Supplement the script with CRM notes from previous interactions."
                    )
                for tip in tips:
                    st.markdown(f"&#x1F535; {tip}")

'''

with open(TARGET, 'r', encoding='utf-8') as f:
    content = f.read()

# Find boundaries
SPIN_START_MARKER = "    # \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n    # TAB 4 \u2014 SPIN Selling Script"
SPIN_END_MARKER   = "    # \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n    # TAB 5 \u2014 Similar Partners"

idx_start = content.find(SPIN_START_MARKER)
idx_end   = content.find(SPIN_END_MARKER)

if idx_start == -1:
    print("ERROR: Could not find SPIN start marker")
    exit(1)
if idx_end == -1:
    print("ERROR: Could not find SPIN end marker")
    exit(1)

print(f"Found SPIN section: chars {idx_start} to {idx_end}")

new_content = content[:idx_start] + NEW_SPIN_TAB + content[idx_end:]

with open(TARGET, 'w', encoding='utf-8') as f:
    f.write(new_content)

print("SUCCESS: partner_360.py patched with elite SPIN tab.")
print(f"New file size: {len(new_content)} bytes")
