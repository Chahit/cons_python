import streamlit as st
import pandas as pd
import numpy as np
import sys, os
import plotly.graph_objects as go
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


@st.cache_data(ttl=600, show_spinner=False)
def _fetch_category_map(_engine):
    """product_name → category_name from master tables."""
    try:
        import pandas as pd
        df = pd.read_sql(
            """SELECT mp.product_name,
                      COALESCE(mpc.category_name, mg.group_name, 'General') AS category
               FROM master_products mp
               LEFT JOIN master_group mg ON mg.id = mp.group_id
               LEFT JOIN master_product_category mpc ON mpc.id = mg.category_id_id""",
            _engine,
        )
        return df.drop_duplicates("product_name").set_index("product_name")["category"].to_dict()
    except Exception:
        return {}


@st.cache_data(ttl=120, show_spinner=False)
def _fetch_partner_recent_products(_engine, partner_name: str, n: int = 15):
    """Last N distinct products ordered by this partner (by most recent date)."""
    try:
        import pandas as pd
        return pd.read_sql(
            """SELECT mp.product_name,
                      COALESCE(mpc.category_name, mg.group_name, 'General') AS category,
                      MAX(t.date)         AS last_date,
                      SUM(tp.qty)         AS total_qty,
                      COUNT(DISTINCT t.id) AS order_count
               FROM transactions_dsr t
               JOIN transactions_dsr_products tp ON tp.dsr_id = t.id
               JOIN master_products mp            ON mp.id = tp.product_id
               JOIN master_party p               ON p.id  = t.party_id
               LEFT JOIN master_group mg          ON mg.id = mp.group_id
               LEFT JOIN master_product_category mpc ON mpc.id = mg.category_id_id
               WHERE LOWER(CAST(t.is_approved AS TEXT)) = 'true'
                 AND p.company_name = %(name)s
               GROUP BY mp.product_name, mpc.category_name, mg.group_name
               ORDER BY last_date DESC
               LIMIT %(n)s""",
            _engine, params={"name": partner_name, "n": n},
        )
    except Exception:
        import pandas as pd
        return pd.DataFrame()


@st.cache_data(ttl=900, show_spinner=False)
def _fetch_bundle_monthly_trends(_engine, top_pairs: list):
    """
    Monthly co-purchase counts for a given list of (product_a, product_b) pairs.
    Queries raw transactions for the last 12 months.
    top_pairs: list of [product_a, product_b] strings (already the top bundles).
    """
    try:
        import pandas as pd
        if not top_pairs:
            return pd.DataFrame()
        # Build pair filter — LEAST/GREATEST normalise ordering
        pair_filters = " OR ".join(
            f"(LEAST(mp1.product_name, mp2.product_name) = %s "
            f"AND GREATEST(mp1.product_name, mp2.product_name) = %s)"
            for _ in top_pairs
        )
        params = []
        for a, b in top_pairs:
            params += [min(a, b), max(a, b)]

        sql = f"""
            SELECT
                TO_CHAR(t.date, 'YYYY-MM') AS month,
                LEAST(mp1.product_name, mp2.product_name)    AS product_a,
                GREATEST(mp1.product_name, mp2.product_name) AS product_b,
                COUNT(DISTINCT t.id) AS monthly_count
            FROM transactions_dsr t
            JOIN transactions_dsr_products tp1 ON tp1.dsr_id = t.id
            JOIN transactions_dsr_products tp2 ON tp2.dsr_id = t.id
                                               AND tp2.product_id > tp1.product_id
            JOIN master_products mp1 ON mp1.id = tp1.product_id
            JOIN master_products mp2 ON mp2.id = tp2.product_id
            WHERE LOWER(CAST(t.is_approved AS TEXT)) = 'true'
              AND t.date >= CURRENT_DATE - INTERVAL '12 months'
              AND ({pair_filters})
            GROUP BY month, product_a, product_b
            ORDER BY month, monthly_count DESC
        """
        with _engine.connect() as conn:
            df = pd.read_sql(sql, conn, params=params)
        return df
    except Exception:
        import pandas as pd
        return pd.DataFrame()


def _generate_human_script(
    partner_name, trigger_product, rec_product,
    trigger_category, rec_category,
    confidence, lift, frequency, gain_monthly,
    days_since_last, partner_order_count,
    tone="Consultative",
):
    """Rule-driven, human-sounding sales call script. No AI-buzzwords. Supports Consultative, Relationship-driven, and Assertive tones."""
    import random, hashlib
    seed = int(hashlib.md5(f"{partner_name}{rec_product}{tone}".encode()).hexdigest(), 16) % (2**31)
    rng  = random.Random(seed)

    same_cat = (trigger_category == rec_category and trigger_category not in ("General", "Unknown", ""))
    cat_note = "same category" if same_cat else f"the {rec_category} side"

    if tone == "Relationship-driven":
        # Opening
        if days_since_last > 60:
            opens = [
                f"Hi! Hope everything is going well over at {partner_name}. I noticed it's been about {days_since_last} days since you last ordered {trigger_product} — just wanted to check in and see how the team is doing.",
                f"Hi there! It's been a while since your last {trigger_product} order and I wanted to touch base, see how things are going, and share a quick operations idea with you."
            ]
        else:
            opens = [
                f"Hi! Always great working with you. I was looking over your recent order of {trigger_product} and had a quick collaborative thought.",
                f"Hope you guys are having a busy week! I was looking at your logistics and wanted to highlight a simple way we can make your life easier on the next shipment."
            ]
        opening = rng.choice(opens)

        # Pitch
        pitches = [
            f"Many of our regular partners who use {trigger_product} also pick up {rec_product} to simplify their deliveries. Since they come from {cat_note}, ordering them together consolidates shipping and saves your receiving team a lot of extra handling.",
            f"I always like to recommend matching {trigger_product} with {rec_product} because it's a natural fit. We've seen {frequency} orders where partners consolidate these two, which really helps streamline operations."
        ]
        pitch = rng.choice(pitches)

        # Value
        value = f"By combining them, you save on freight and consolidate the invoicing. Plus, adding even a small batch of {rec_product} helps build out a complete solution for your customers."

        # Objection
        objections = [
            "Totally understand if you want to start small. We can set up a tiny, no-risk trial batch on the next order just to test it out with your team.",
            "Completely fair! We can easily hold off on a major volume, and just put a small sample of 5 or 10 units in your next regular container at a special trial rate."
        ]
        objection = rng.choice(objections)

        # Close
        closes = [
            f"Would you like me to add a small trial quantity of {rec_product} to your upcoming {trigger_product} shipment?",
            f"Should I put together a quick, consolidated quote for both so you can review it with your team?"
        ]
        close = rng.choice(closes)

    elif tone == "Assertive & Urgent":
        # Opening
        opens = [
            f"Hi! I'm calling because we are preparing our next production schedule for {rec_product} and based on your {trigger_product} consumption, you're currently missing out on a major revenue stream.",
            f"Quick call regarding your {trigger_product} orders — I was looking at the competitive landscape in your region and there is an immediate gap we need to plug."
        ]
        opening = rng.choice(opens)

        # Pitch
        pitches = [
            f"Our market intelligence shows {confidence:.0%} of partners ordering {trigger_product} are experiencing immediate, collateral customer demand for {rec_product}. This is a highly correlated pairing with a {lift:.1f}x affinity lift. Leaving {rec_product} out of your catalog is actively sending buyers to competitors.",
            f"We've tracked {frequency} instances where the market bought these together. With a {lift:.1f}x lift factor, this isn't optional for an account at your scale. You are leaving high-margin money on the table."
        ]
        pitch = rng.choice(pitches)

        # Value
        value = f"At your volume, introducing {rec_product} adds roughly {_inr(gain_monthly)} in incremental monthly margin. This is highly profitable shelf space that is currently underutilized."

        # Objection
        objections = [
            f"I hear your hesitation, but the {lift:.1f}x lift statistical proof is concrete. Every week you delay is incremental margin your competitors are claiming.",
            f"I respect that, but with {confidence:.0%} confidence across {frequency} orders, the market demand is already verified. Waiting only delays your capture of this revenue."
        ]
        objection = rng.choice(objections)

        # Close
        closes = [
            f"Let's add the standard bundle block of {rec_product} to your {trigger_product} order today so we can secure the inventory before the next production cycle closes.",
            f"I will prepare the consolidated booking order now so we can get this shipped and start capturing this monthly revenue."
        ]
        close = rng.choice(closes)

    else:  # Consultative (Default)
        # Original consultative logic
        if days_since_last > 60:
            opens = [
                f"I was going through accounts and noticed it's been about {days_since_last} days since your last {trigger_product} order — wanted to reach out before your next cycle.",
                f"It's been a while since your last {trigger_product} shipment and I had a quick thought I wanted to run by you.",
            ]
        elif partner_order_count >= 20:
            opens = [
                f"With all the {trigger_product} you've been moving, I spotted something worth flagging before your next order.",
                f"I know you're on top of your {trigger_product} ordering — this one's quick and relevant.",
            ]
        else:
            opens = [
                f"I was looking at your recent {trigger_product} orders and there's something I wanted to mention.",
                f"Quick call about your {trigger_product} pattern — there's a pairing I think makes sense for your account.",
            ]
        opening = rng.choice(opens)

        if confidence >= 0.65:
            pitches = [
                f"About {confidence:.0%} of partners who regularly order {trigger_product} end up needing {rec_product} — we've tracked this across {frequency} actual orders. It's not a coincidence.",
                f"This is a pattern we see reliably: {trigger_product} goes out, {rec_product} follows. {confidence:.0%} of the time, same ordering cycle. Makes sense to plan for both.",
            ]
        elif confidence >= 0.40:
            pitches = [
                f"We've seen {frequency} cases where {trigger_product} and {rec_product} get ordered together from {cat_note}. Lift is {lift:.1f}x — that's meaningful correlation.",
                f"Not a slam dunk, but {confidence:.0%} of similar accounts are picking up {rec_product} alongside {trigger_product}. Worth a conversation.",
            ]
        else:
            pitches = [
                f"It's a lower-frequency pairing but {rec_product} keeps showing up alongside {trigger_product} orders — {frequency} times. Might be worth keeping in mind.",
                f"I wouldn't push hard on this one, but {rec_product} from {cat_note} has come up alongside {trigger_product} {frequency} times. Just flagging it.",
            ]
        pitch = rng.choice(pitches)

        if gain_monthly >= 100000:
            value = f"Partners making this combination are adding roughly {_inr(gain_monthly)}/month in incremental revenue. At your volume, that compounds fast."
        elif gain_monthly >= 10000:
            value = f"Incremental gain on the pairing is about {_inr(gain_monthly)}/month — not massive, but it adds up and there's no extra effort on the logistics side."
        else:
            value = f"It's not a big revenue mover on its own, but it consolidates a delivery and removes a separate reorder step for you."

        if lift >= 3.0:
            objection = f"I'd push back on any hesitation here — {lift:.1f}x lift across {frequency} transactions isn't soft data. The demand is real."
        elif lift >= 1.5:
            objection = f"Even if you want to trial it — the {lift:.1f}x lift tells me it's not random. Start small and we'll track it from there."
        else:
            objection = f"Totally fair if it's not the right time. Just keep {rec_product} in mind — it's shown up {frequency} times alongside {trigger_product} and that number grows each quarter."

        closes = [
            f"Want me to add a trial qty of {rec_product} to your next {trigger_product} order? I can set it up now.",
            f"Should I put a combined quote together? Takes two minutes and you can decide from there.",
            f"I can note it on your account and raise it again at your next order — or we move on it now if the timing works.",
        ]
        close = rng.choice(closes)

    return {"opening": opening, "pitch": pitch, "value": value, "objection": objection, "close": close}



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
    # SECTION 1 — Bundle Sandbox & Profit Maximizer (Wow Factor 1)
    # ─────────────────────────────────────────────────────────────────────────
    section_header("🧪 Interactive Sandbox Bundle Simulator & Profit Maximizer")
    st.caption("Design custom multi-product bundles, configure discounts, and instantly simulate demand uplift and net margin growth.")

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

    # Map prices and margin rates — guard against NaN/inf
    import math
    product_prices = {}
    product_margins = {}
    if not _df_all.empty:
        for row in _df_all.itertuples():
            pa = getattr(row, "product_a", None)
            pb = getattr(row, "product_b", None)
            rev  = float(getattr(row, "expected_revenue_gain", 0) or 0)
            freq = float(getattr(row, "times_bought_together", 1) or 1)
            rate = float(getattr(row, "margin_rate", 0.15) or 0.15)
            # Average line revenue — safe division
            avg_rev = rev / freq if freq > 0 else 15000.0
            # Guard: if somehow NaN/inf slipped through, default to 15000
            if not math.isfinite(avg_rev) or avg_rev <= 0:
                avg_rev = 15000.0
            if not math.isfinite(rate) or rate <= 0:
                rate = 0.15
            if pa and pa not in product_prices:
                product_prices[pa] = avg_rev
                product_margins[pa] = rate
            if pb and pb not in product_prices:
                product_prices[pb] = avg_rev
                product_margins[pb] = rate

    # Sandbox input container
    sim_cols = st.columns([3, 1])
    with sim_cols[0]:
        selected_sandbox_products = st.multiselect(
            "Select Products for Custom Bundle Sandbox (Max 4)",
            options=unique_products,
            default=unique_products[:2] if len(unique_products) >= 2 else [],
            max_selections=4,
            key="sandbox_multiselect",
        )
    with sim_cols[1]:
        bundle_discount = st.slider(
            "Bundle Discount %",
            min_value=0,
            max_value=30,
            value=10,
            step=1,
            format="%d%%",
            key="sandbox_discount_slider",
        )

    if len(selected_sandbox_products) >= 2:
        # Calculate simulation
        total_baseline_revenue = 0.0
        total_baseline_margin = 0.0
        total_weighted_lift = 0.0
        pair_counts = 0

        # Sum baseline figures — guard against NaN in all price lookups
        for p in selected_sandbox_products:
            price = float(product_prices.get(p, 15000.0) or 15000.0)
            if not math.isfinite(price) or price <= 0:
                price = 15000.0
            margin_rate = float(product_margins.get(p, 0.15) or 0.15)
            if not math.isfinite(margin_rate) or margin_rate <= 0:
                margin_rate = 0.15
            total_baseline_revenue += price
            total_baseline_margin += price * margin_rate

        # Compute average lift among selected pairs
        for i in range(len(selected_sandbox_products)):
            for j in range(i + 1, len(selected_sandbox_products)):
                p1, p2 = selected_sandbox_products[i], selected_sandbox_products[j]
                # Look up lift
                pair_row = _df_all[
                    ((_df_all["product_a"] == p1) & (_df_all["product_b"] == p2)) |
                    ((_df_all["product_a"] == p2) & (_df_all["product_b"] == p1))
                ]
                if not pair_row.empty:
                    lift_raw = pair_row.iloc[0].get("lift_a_to_b", 1.0)
                    lift_val = float(lift_raw) if lift_raw is not None and math.isfinite(float(lift_raw or 1.0)) else 1.0
                    total_weighted_lift += lift_val
                    pair_counts += 1

        avg_pair_lift = (total_weighted_lift / pair_counts) if pair_counts > 0 else 1.2
        if not math.isfinite(avg_pair_lift):
            avg_pair_lift = 1.2

        # Model demand elastic expansion based on lift and discount
        discount_fraction = float(bundle_discount) / 100.0
        demand_uplift_raw = 1.0 + (discount_fraction * 1.5) * (avg_pair_lift - 0.2)
        demand_uplift = max(1.0, min(float(demand_uplift_raw) if math.isfinite(demand_uplift_raw) else 1.2, 4.0))

        # Bundle pricing & margins — ensure no NaN reaches metrics
        simulated_bundle_revenue = total_baseline_revenue * (1.0 - discount_fraction)
        if not math.isfinite(simulated_bundle_revenue):
            simulated_bundle_revenue = 0.0
        
        # Simulated Margin: sum of (price * margin_rate - price * discount_fraction)
        sim_margin_sum = 0.0
        for p in selected_sandbox_products:
            price = float(product_prices.get(p, 15000.0) or 15000.0)
            if not math.isfinite(price) or price <= 0:
                price = 15000.0
            margin_rate = float(product_margins.get(p, 0.15) or 0.15)
            if not math.isfinite(margin_rate):
                margin_rate = 0.15
            sim_margin_sum += price * (margin_rate - discount_fraction)
        
        simulated_net_margin = max(0.0, sim_margin_sum if math.isfinite(sim_margin_sum) else 0.0) * demand_uplift
        margin_delta = simulated_net_margin - total_baseline_margin
        pct_margin_delta = (margin_delta / total_baseline_margin) if total_baseline_margin > 0 else 0.0

        # Display Plotly Indicators side by side
        fig_sim = go.Figure()
        max_gauge_val = float(max(total_baseline_margin, simulated_net_margin) * 1.4)
        if max_gauge_val == 0:
            max_gauge_val = 50000.0

        fig_sim.add_trace(go.Indicator(
            mode="gauge+number",
            value=total_baseline_margin,
            domain={'x': [0, 0.45], 'y': [0, 1]},
            title={'text': "Baseline Standalone Margin", 'font': {'size': 13, 'color': '#94a3b8'}},
            number={'prefix': "₹", 'font': {'color': '#e2e8f0', 'size': 26}},
            gauge={
                'axis': {'range': [0, max_gauge_val], 'tickwidth': 1, 'tickcolor': "#475569"},
                'bar': {'color': "#475569"},
                'bgcolor': "#0f172a",
                'borderwidth': 1,
                'bordercolor': "#334155",
            }
        ))

        fig_sim.add_trace(go.Indicator(
            mode="gauge+number+delta",
            value=simulated_net_margin,
            delta={'reference': total_baseline_margin, 'relative': False, 'valueformat': '₹.0f',
                   'increasing': {'color': '#22c55e'}, 'decreasing': {'color': '#ef4444'}},
            domain={'x': [0.55, 1], 'y': [0, 1]},
            title={'text': "Projected Bundle Margin", 'font': {'size': 13, 'color': '#94a3b8'}},
            number={'prefix': "₹", 'font': {'color': '#e2e8f0', 'size': 26}},
            gauge={
                'axis': {'range': [0, max_gauge_val], 'tickwidth': 1, 'tickcolor': "#475569"},
                'bar': {'color': "#22c55e" if margin_delta >= 0 else "#ef4444"},
                'bgcolor': "#0f172a",
                'borderwidth': 1,
                'bordercolor': "#334155",
            }
        ))

        fig_sim.update_layout(
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            margin=dict(l=10, r=10, t=30, b=10),
            height=200,
        )

        st.plotly_chart(fig_sim, use_container_width=True)

        # Dynamic metric summaries
        kpi_c1, kpi_c2, kpi_c3, kpi_c4 = st.columns(4)
        with kpi_c1:
            st.metric("Estimated Volume Uplift", f"{demand_uplift:.2f}x", help="Expected multipliers in transaction volume due to discount elasticity.")
        with kpi_c2:
            st.metric("Custom Bundle Price", _inr(simulated_bundle_revenue), f"-{bundle_discount}% off")
        with kpi_c3:
            st.metric("Monthly Margin Delta", f"{'+' if margin_delta >= 0 else ''}{_inr(margin_delta)}", 
                      delta=f"{'+' if margin_delta >= 0 else ''}{pct_margin_delta:.1%}", delta_color="normal")
        with kpi_c4:
            st.metric("Core Bundle Affinity", f"{avg_pair_lift:.2f}x Lift", help="Higher lift means products are exceptionally correlated in actual historic baskets.")
    else:
        st.info("💡 Select 2 or more products above to dynamically run the Bundle Sandbox & Profit Maximizer simulator.")

    st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
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
    # SECTION 3 — Bundle Tables: Same-Category & Cross-Category
    # ─────────────────────────────────────────────────────────────────────────
    import pandas as pd
    engine = getattr(ai, "engine", None)
    cat_map = _fetch_category_map(engine) if engine else {}

    if not df_assoc.empty and cat_map:
        df_assoc = df_assoc.copy()
        df_assoc["cat_a"] = df_assoc["product_a"].map(cat_map).fillna("General")
        df_assoc["cat_b"] = df_assoc["product_b"].map(cat_map).fillna("General")
        df_assoc["bundle_type"] = df_assoc.apply(
            lambda r: "Same Category" if r["cat_a"] == r["cat_b"] else "Cross Category", axis=1
        )
        df_same  = df_assoc[df_assoc["bundle_type"] == "Same Category"]
        df_cross = df_assoc[df_assoc["bundle_type"] == "Cross Category"]
    else:
        df_same  = df_assoc.copy() if not df_assoc.empty else pd.DataFrame()
        df_cross = pd.DataFrame()

    _display_cols = [
        "product_a", "product_b", "times_bought_together",
        "confidence_a_to_b", "lift_a_to_b", "rule_strength",
        "expected_gain_monthly", "expected_margin_monthly",
    ]
    _col_cfg = {
        "product_a": "If they buy…", "product_b": "…pitch this",
        "times_bought_together": st.column_config.NumberColumn("Frequency"),
        "confidence_a_to_b":    st.column_config.NumberColumn("Confidence", format="%.2f"),
        "lift_a_to_b":          st.column_config.NumberColumn("Lift", format="%.2f"),
        "rule_strength":        "Rule Strength",
        "expected_gain_monthly": st.column_config.NumberColumn("₹ Gain/Month", format="₹%d"),
        "expected_margin_monthly": st.column_config.NumberColumn("₹ Margin/Month", format="₹%d"),
    }

    left = st.container()

    with left:
        section_header(f"Product Bundle Rules ({len(df_assoc)} found)")
        with st.expander("ℹ️ Metric Glossary", expanded=False):
            st.markdown(
                "- **Confidence**: P(B | A)\n- **Lift**: >1 = meaningful affinity\n"
                "- **Same Category**: both products in same category (e.g. HDD → HDD)\n"
                "- **Cross Category**: different categories (e.g. HDD → Cables)"
            )

        # Product Affinity Matrix heatmap removed per user request

        same_tab, cross_tab = st.tabs([
            f"🔁 Same-Category Bundles ({len(df_same)})",
            f"🔀 Cross-Category Bundles ({len(df_cross)})",
        ])

        def _safe_df(df, cols):
            """Sanitize dataframe before rendering — prevents React error #185."""
            if df.empty:
                return df
            df = df.copy()
            numeric_cols = ["times_bought_together", "confidence_a_to_b", "lift_a_to_b",
                            "expected_gain_monthly", "expected_margin_monthly",
                            "confidence", "lift", "frequency"]
            for c in numeric_cols:
                if c in df.columns:
                    df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
                    # Replace inf values
                    import numpy as np_local
                    df[c] = df[c].replace([np_local.inf, -np_local.inf], 0.0)
            for c in ["product_a", "product_b", "rule_strength", "trigger_product", "recommended_product", "bundle_type"]:
                if c in df.columns:
                    df[c] = df[c].fillna("").astype(str)
            # Keep only requested cols that exist
            return df[[c for c in cols if c in df.columns]]

        with same_tab:
            st.caption("Depth-selling within a product family — same category on both sides.")
            if df_same.empty:
                st.info("No same-category rules with current filters.")
            else:
                st.dataframe(_safe_df(df_same, _display_cols),
                             column_config=_col_cfg, use_container_width=True, hide_index=True)

        with cross_tab:
            st.caption("Category expansion — partner buys A, pitch them B from a different category.")
            if df_cross.empty:
                st.info("No cross-category rules with current filters.")
            else:
                st.dataframe(_safe_df(df_cross, _display_cols),
                             column_config=_col_cfg, use_container_width=True, hide_index=True)
    st.markdown("---")




    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 4 — Partner-First Recommendations
    # ─────────────────────────────────────────────────────────────────────────
    st.markdown("---")
    section_header("🎯 Partner Pitch Engine")
    st.caption("Select a partner to see which products the algorithm recommends pitching based on their purchase history.")


    if ai.matrix is not None and not ai.matrix.empty:
        partner_names = sorted(ai.matrix.index.tolist())
    elif ai.df_ml is not None and not ai.df_ml.empty and "company_name" in ai.df_ml.columns:
        partner_names = sorted(ai.df_ml["company_name"].dropna().astype(str).unique().tolist())
    else:
        partner_names = []

    if not partner_names:
        st.warning("No partner list available. Refresh data.")
    else:
        ph_col, top_col = st.columns([3, 1])
        with ph_col:
            selected_partner = st.selectbox("🏢 Select Partner", partner_names, key="partner_pitch_sel")
        with top_col:
            top_n = st.slider("Top Pitches", 3, 15, 8, 1, key="partner_top_n")

        # Fetch partner's actual recent products
        if engine:
            with st.spinner("Loading partner history…"):
                recent_df = _fetch_partner_recent_products(engine, selected_partner, n=20)
        else:
            import pandas as pd
            recent_df = pd.DataFrame()

        # Get algorithm recommendations
        partner_recos = ai.get_partner_bundle_recommendations(
            selected_partner,
            min_confidence=min_conf,
            min_lift=min_lift,
            min_support=min_support,
            include_low_support=include_low_support,
            top_n=top_n,
        )

        # ── Partner context strip ────────────────────────────────────────────
        if not recent_df.empty:
            last_product  = str(recent_df.iloc[0]["product_name"])
            last_date     = recent_df.iloc[0]["last_date"]
            import datetime
            days_since = (datetime.date.today() - pd.to_datetime(last_date).date()).days
            total_orders  = int(recent_df["order_count"].sum())
            top_cats      = recent_df["category"].value_counts().head(2).index.tolist()
            st.markdown(
                f"<div style='background:#0f172a;border:1px solid #1e293b;border-radius:10px;"
                f"padding:12px 18px;margin-bottom:16px;display:flex;gap:32px;align-items:center;'>"
                f"<div><div style='font-size:11px;color:#64748b;'>Last Product Ordered</div>"
                f"<div style='color:#e2e8f0;font-weight:600;'>{last_product}</div></div>"
                f"<div><div style='font-size:11px;color:#64748b;'>Days Since Last Order</div>"
                f"<div style='color:#f59e0b;font-weight:600;'>{days_since}d ago</div></div>"
                f"<div><div style='font-size:11px;color:#64748b;'>Total Lines (Last 20 Products)</div>"
                f"<div style='color:#e2e8f0;font-weight:600;'>{total_orders}</div></div>"
                f"<div><div style='font-size:11px;color:#64748b;'>Top Categories</div>"
                f"<div style='color:#38bdf8;font-weight:600;'>{' · '.join(top_cats) if top_cats else '—'}</div></div>"
                f"</div>",
                unsafe_allow_html=True,
            )
        else:
            days_since   = 30
            total_orders = 0
            last_product = ""

        if partner_recos.empty:
            st.warning("No cross-sell opportunities found for this partner with current filters.")
        else:
            # Enrich recs with category info
            if cat_map:
                partner_recos = partner_recos.copy()
                partner_recos["trigger_cat"] = partner_recos["trigger_product"].map(cat_map).fillna("General")
                partner_recos["rec_cat"]     = partner_recos["recommended_product"].map(cat_map).fillna("General")
                partner_recos["bundle_type"] = partner_recos.apply(
                    lambda r: "🔁 Same-Cat" if r["trigger_cat"] == r["rec_cat"] else "🔀 Cross-Cat", axis=1
                )

            _preco_cols = [
                "trigger_product", "recommended_product",
                "confidence", "lift", "frequency", "rule_strength",
                "expected_gain_monthly",
            ]
            if "bundle_type" in partner_recos.columns:
                _preco_cols = ["bundle_type"] + _preco_cols
            _preco_cfg = {
                "bundle_type":          "Type",
                "trigger_product":      "Bought Product",
                "recommended_product":  "Pitch This",
                "confidence":           st.column_config.NumberColumn("Conf.", format="%.2f"),
                "lift":                 st.column_config.NumberColumn("Lift", format="%.2f"),
                "frequency":            st.column_config.NumberColumn("Freq."),
                "rule_strength":        "Strength",
                "expected_gain_monthly": st.column_config.NumberColumn("₹ Gain/Mo", format="₹%d"),
            }
            st.dataframe(
                _safe_df(partner_recos, _preco_cols),
                column_config=_preco_cfg,
                use_container_width=True, hide_index=True,
            )

            # Interactive Sales Call Script Console (Pitfall 1)
            st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
            st.markdown("### 📞 Interactive Sales Pitch Console")
            st.caption("Generate a personalized sales pitch with dynamic objection handling in different tones based on the selected recommendation.")

            pitch_reco_names = partner_recos["recommended_product"].tolist()
            sel_pitch_p = st.selectbox(
                "Select a Recommended Product to Draft Call Script",
                options=[""] + pitch_reco_names,
                format_func=lambda x: f"Select Product..." if x == "" else f"Pitch: {x}",
                key="sandbox_pitch_product_selector"
            )

            if sel_pitch_p:
                row_pitch = partner_recos[partner_recos["recommended_product"] == sel_pitch_p].iloc[0]
                
                # Script tone select
                pitch_tone_focus = st.radio(
                    "Script Tone / Style Focus",
                    options=["Consultative", "Relationship-driven", "Assertive & Urgent"],
                    horizontal=True,
                    key="sandbox_pitch_tone_selector"
                )

                # Fetch parameters
                t_cat = row_pitch.get("trigger_cat", "General")
                r_cat = row_pitch.get("rec_cat", "General")
                conf_val = float(row_pitch.get("confidence", 0.15))
                lift_val = float(row_pitch.get("lift", 1.0))
                freq_val = int(row_pitch.get("frequency", 1))
                gain_mo = float(row_pitch.get("expected_gain_monthly", 0.0) or 0.0)

                # Generate script
                script_out = _generate_human_script(
                    partner_name=selected_partner,
                    trigger_product=row_pitch["trigger_product"],
                    rec_product=sel_pitch_p,
                    trigger_category=t_cat,
                    rec_category=r_cat,
                    confidence=conf_val,
                    lift=lift_val,
                    frequency=freq_val,
                    gain_monthly=gain_mo,
                    days_since_last=days_since,
                    partner_order_count=total_orders,
                    tone=pitch_tone_focus
                )

                # Display premium cards
                st.markdown(
                    f"""<div style="background:#0f172a;border:1px solid #1e293b;border-radius:12px;padding:20px;margin-bottom:16px;">
                      <div style="font-size:12px;text-transform:uppercase;color:#38bdf8;font-weight:700;letter-spacing:1px;margin-bottom:12px;">
                        🎯 Pitch Script: {pitch_tone_focus} Focus
                      </div>
                      <div style="margin-bottom:14px;">
                        <span style="color:#64748b;font-weight:600;font-size:11px;display:block;">1. THE OPENING</span>
                        <span style="color:#e2e8f0;font-size:13.5px;line-height:1.5;">"{script_out['opening']}"</span>
                      </div>
                      <div style="margin-bottom:14px;">
                        <span style="color:#64748b;font-weight:600;font-size:11px;display:block;">2. THE CORE VALUE PITCH</span>
                        <span style="color:#e2e8f0;font-size:13.5px;line-height:1.5;">"{script_out['pitch']}"</span>
                      </div>
                      <div style="margin-bottom:14px;">
                        <span style="color:#64748b;font-weight:600;font-size:11px;display:block;">3. REVENUE / OPERATIONS VALUE PROPOSITION</span>
                        <span style="color:#e2e8f0;font-size:13.5px;line-height:1.5;">"{script_out['value']}"</span>
                      </div>
                      <div style="margin-bottom:14px;">
                        <span style="color:#64748b;font-weight:600;font-size:11px;display:block;">4. OBJECTION HANDLER</span>
                        <span style="color:#e2e8f0;font-size:13.5px;line-height:1.5;">"{script_out['objection']}"</span>
                      </div>
                      <div>
                        <span style="color:#64748b;font-weight:600;font-size:11px;display:block;">5. THE CLOSE</span>
                        <span style="color:#e2e8f0;font-size:13.5px;line-height:1.5;">"{script_out['close']}"</span>
                      </div>
                    </div>""",
                    unsafe_allow_html=True
                )

                # Combined copy textbox
                draft_text = (
                    f"Hi team,\n\n"
                    f"Draft Pitch Script for {selected_partner} ({pitch_tone_focus} Tone):\n\n"
                    f"Opening: {script_out['opening']}\n\n"
                    f"Core Pitch: {script_out['pitch']}\n\n"
                    f"Value: {script_out['value']}\n\n"
                    f"Objection Handling: {script_out['objection']}\n\n"
                    f"Call Close: {script_out['close']}\n\n"
                    f"Best regards,\nSales Representative"
                )
                st.text_area("📋 Copy Pitch Script Draft", value=draft_text, height=180, key="sandbox_pitch_draft_copier")
            else:
                st.info("💡 Select one of the recommended pitch products above to instantly compile a call script.")




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
                            # Render Plotly Sankey Flow Diagram (Wow Factor)
                            try:
                                top_seq = seq_df.head(15)
                                all_items = sorted(list(set(top_seq["product_a"].tolist() + top_seq["product_b"].tolist())))
                                item_indices = {item: idx for idx, item in enumerate(all_items)}
                                sources = [item_indices[row.product_a] for row in top_seq.itertuples()]
                                targets = [item_indices[row.product_b] for row in top_seq.itertuples()]
                                values = [float(row.sequence_count) for row in top_seq.itertuples()]
                                node_colors = ["#0891b2"] * len(all_items)
                                link_colors = ["rgba(8, 145, 178, 0.4)"] * len(top_seq)
                                fig_seq_sankey = go.Figure(data=[go.Sankey(
                                    node=dict(
                                        pad=12, thickness=15,
                                        line=dict(color="#1e293b", width=1),
                                        label=all_items, color=node_colors
                                    ),
                                    link=dict(
                                        source=sources, target=targets, value=values, color=link_colors
                                    )
                                )])
                                fig_seq_sankey.update_layout(
                                    title_text="🌊 Sequential Purchase Flow (Top 15 Transitions)",
                                    font_size=10,
                                    paper_bgcolor='rgba(0,0,0,0)',
                                    plot_bgcolor='rgba(0,0,0,0)',
                                    height=250,
                                    margin=dict(l=10, r=10, t=40, b=10)
                                )
                                st.plotly_chart(fig_seq_sankey, use_container_width=True)
                            except Exception as ex_seq_sankey:
                                st.caption(f"Could not render sequential flow diagram: {ex_seq_sankey}")

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
                            # Render Plotly Sankey Flow Diagram for Cross-Category (Wow Factor)
                            try:
                                top_cc = cc_df.head(15)
                                all_cats = sorted(list(set(top_cc["category_x"].tolist() + top_cc["category_y"].tolist())))
                                cat_indices = {cat: idx for idx, cat in enumerate(all_cats)}
                                sources = [cat_indices[row.category_x] for row in top_cc.itertuples()]
                                targets = [cat_indices[row.category_y] for row in top_cc.itertuples()]
                                values = [float(row.upgrade_count) for row in top_cc.itertuples()]
                                node_colors = ["#f59e0b"] * len(all_cats)
                                link_colors = ["rgba(245, 158, 11, 0.4)"] * len(top_cc)
                                fig_cc_sankey = go.Figure(data=[go.Sankey(
                                    node=dict(
                                        pad=12, thickness=15,
                                        line=dict(color="#1e293b", width=1),
                                        label=all_cats, color=node_colors
                                    ),
                                    link=dict(
                                        source=sources, target=targets, value=values, color=link_colors
                                    )
                                )])
                                fig_cc_sankey.update_layout(
                                    title_text="🔀 Category Cross-Upgrade Sequence Flow (Top 15 Transitions)",
                                    font_size=10,
                                    paper_bgcolor='rgba(0,0,0,0)',
                                    plot_bgcolor='rgba(0,0,0,0)',
                                    height=250,
                                    margin=dict(l=10, r=10, t=40, b=10)
                                )
                                st.plotly_chart(fig_cc_sankey, use_container_width=True)
                            except Exception as ex_cc_sankey:
                                st.caption(f"Could not render category flow diagram: {ex_cc_sankey}")

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
