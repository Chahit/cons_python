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

