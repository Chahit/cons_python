import streamlit as st
import pandas as pd
import numpy as np
import sys, os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from styles import page_header, skeleton_loader

# ── Kanban swimlane configuration ──────────────────────────────────────────
LANES = [
    {"key": "champion", "label": "🏆 Champion", "segments": {"Champion"}, "color": "#22c55e"},
    {"key": "healthy",  "label": "✅ Healthy",  "segments": {"Healthy"},  "color": "#3b82f6"},
    {"key": "at_risk",  "label": "⚠️ At Risk",  "segments": {"At Risk"},  "color": "#f59e0b"},
    {"key": "critical", "label": "🔴 Critical", "segments": {"Critical"}, "color": "#ef4444"},
]

def _fmt_inr(val):
    try:
        v = float(val)
    except Exception:
        return "₹0"
    if v >= 1_00_00_000: return f"₹{v / 1_00_00_000:.1f}Cr"
    if v >= 1_00_000:    return f"₹{v / 1_00_000:.1f}L"
    if v >= 1_000:       return f"₹{v / 1_000:.0f}K"
    return f"₹{v:.0f}"

def _days_ago(recency_days):
    """Format recency_days as human-readable last-order string."""
    try:
        d = int(float(recency_days))
        if d == 0:  return "Today"
        if d == 1:  return "1d ago"
        if d < 31:  return f"{d}d ago"
        if d < 365: return f"{d // 30}mo ago"
        return f"{d // 365}y ago"
    except Exception:
        return "—"

def _primary_risk_signal(row):
    """Return (signal_text, color) for the single most urgent risk indicator."""
    try:
        recency   = float(row.get("recency_days") or 0)
        drop      = float(row.get("revenue_drop_pct") or 0)
        recent    = float(row.get("recent_90_revenue") or 0)
        prev      = float(row.get("prev_90_revenue") or 0)
        if recent == 0 and prev > 0:
            return "🔴 Revenue stopped", "#ef4444"
        if recency > 120:
            return f"⏰ {int(recency)}d no purchase", "#ef4444"
        if drop > 50:
            return f"📉 Revenue ↓{drop:.0f}%", "#ef4444"
        if recency > 60:
            return f"⏳ {int(recency)}d quiet", "#f59e0b"
        if drop > 25:
            return f"📉 ↓{drop:.0f}% revenue", "#f59e0b"
    except Exception:
        pass
    return None, None

# ── Cache the heavy data slice so repeated renders are fast ────────────────
@st.cache_data(ttl=300, show_spinner=False)
def _build_kanban_df(_pf_df):
    """Extract and pre-process only the columns needed by the Kanban board."""
    needed = [
        "company_name", "state", "health_segment", "health_status",
        "churn_probability", "credit_risk_band",
        "recent_90_revenue", "prev_90_revenue", "revenue_drop_pct", "revenue_at_risk",
        "cluster_label", "cluster_type", "recency_days",
    ]
    df = _pf_df.reset_index()
    if "company_name" not in df.columns and "index" in df.columns:
        df = df.rename(columns={"index": "company_name"})
    cols_present = [c for c in needed if c in df.columns]
    df = df[cols_present].copy()

    # Fill defaults for optional columns
    for col, default in [
        ("churn_probability", 0.0),
        ("credit_risk_band", "N/A"),
        ("health_segment", "Healthy"),
        ("cluster_label", "—"),
        ("cluster_type", "—"),
        ("recency_days", None),
        ("prev_90_revenue", 0.0),
        ("revenue_drop_pct", None),
        ("revenue_at_risk", None),
    ]:
        if col not in df.columns:
            df[col] = default

    df["churn_probability"] = pd.to_numeric(df["churn_probability"], errors="coerce").fillna(0.0)
    df["recent_90_revenue"] = pd.to_numeric(df.get("recent_90_revenue", 0), errors="coerce").fillna(0.0)

    # Compute revenue_at_risk if not provided: churn probability × 90d revenue
    if "revenue_at_risk" not in df.columns or df["revenue_at_risk"].isna().all():
        df["revenue_at_risk"] = df["churn_probability"] * df["recent_90_revenue"]
    else:
        df["revenue_at_risk"] = pd.to_numeric(df["revenue_at_risk"], errors="coerce").fillna(
            df["churn_probability"] * df["recent_90_revenue"]
        )

    return df


@st.cache_data(ttl=300, show_spinner=False)
def _build_category_performance(_group_spend_df):
    """
    Build a category→partner performance summary.
    Returns a DataFrame: company_name, category (group_name), total_spend
    """
    if _group_spend_df is None or _group_spend_df.empty:
        return pd.DataFrame(columns=["company_name", "category", "total_spend"])
    df = _group_spend_df.copy()
    if "group_name" in df.columns:
        df = df.rename(columns={"group_name": "category"})
    needed = [c for c in ["company_name", "category", "total_spend"] if c in df.columns]
    return df[needed].copy()


def _render_filter_bar(df, cat_perf_df):
    """Render the inline main-page filter bar above the kanban board."""
    st.markdown("""
    <style>
    .filter-bar {
        background: #12141c;
        border: 1px solid #1e2235;
        border-radius: 12px;
        padding: 16px 20px;
        margin-bottom: 18px;
    }
    .filter-bar-title {
        font-size: 11px;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.12em;
        color: #4b5563;
        margin-bottom: 12px;
    }
    </style>
    <div class="filter-bar">
      <div class="filter-bar-title">🔍 Pipeline Filters</div>
    </div>
    """, unsafe_allow_html=True)

    # ── Row 1: State/Area + Category ──────────────────────────────────────
    c1, c2, c3, c4 = st.columns([2, 2, 1.5, 1])

    with c1:
        all_states = sorted(df["state"].dropna().unique().tolist()) if "state" in df.columns else []
        sel_states = st.multiselect(
            "📍 Filter by Area / State",
            all_states,
            default=[],
            key="kb_states",
            help="Show only partners from selected states. Leave empty to show all.",
        )

    with c2:
        # Category filter — built from group_name spend data
        all_cats = []
        if not cat_perf_df.empty and "category" in cat_perf_df.columns:
            all_cats = sorted(cat_perf_df["category"].dropna().unique().tolist())
        sel_cats = st.multiselect(
            "🏷️ Filter by Product Category",
            all_cats,
            default=[],
            key="kb_cats",
            help="Show only partners who have purchased in the selected categories.",
        )

    with c3:
        credit_opts = ["All", "Low", "Medium", "High", "Critical"]
        sel_credit  = st.selectbox("💳 Credit Risk", credit_opts, key="kb_credit")

    with c4:
        sort_by = st.selectbox(
            "↕️ Sort by",
            ["Revenue (High→Low)", "Churn Risk (High→Low)", "At Risk (High→Low)", "Name (A→Z)"],
            key="kb_sort",
        )

    # ── Row 2: Revenue floor + Name search ────────────────────────────────
    c5, c6, c7 = st.columns([1.5, 2, 0.5])
    with c5:
        min_rev = st.number_input("Min 90d Revenue (₹)", value=0, step=10000, key="kb_minrev")
    with c6:
        search_query = st.text_input(
            "🔍 Search partner by name",
            placeholder="Type a company name...",
            key="kb_search",
        )
    with c7:
        st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        show_cat_insight = st.toggle("Category View", key="kb_cat_view", value=False)

    return sel_states, sel_cats, sel_credit, sort_by, min_rev, search_query, show_cat_insight


def _render_category_insight(cat_perf_df, kanban_df):
    """
    Renders a category performance breakdown table:
    For each category → best performing distributor and worst performing distributor.
    """
    if cat_perf_df.empty or "category" not in cat_perf_df.columns:
        st.info("No category spend data available.")
        return

    st.markdown("""
    <div style='background:#12141c;border:1px solid #1e2235;border-radius:12px;
         padding:14px 20px;margin-bottom:18px;'>
      <div style='font-size:13px;font-weight:700;color:#6366f1;margin-bottom:4px;'>
        📊 Category Performance — Distributor Breakdown
      </div>
      <div style='font-size:12px;color:#64748b;'>
        Which distributors are performing best and worst in each product category
      </div>
    </div>
    """, unsafe_allow_html=True)

    # Merge health segment info
    seg_map = {}
    if not kanban_df.empty and "health_segment" in kanban_df.columns:
        seg_map = kanban_df.set_index("company_name")["health_segment"].to_dict()

    # Aggregate: sum spend per company per category
    cat_agg = (
        cat_perf_df.groupby(["category", "company_name"])["total_spend"]
        .sum()
        .reset_index()
    )
    cat_agg["health"] = cat_agg["company_name"].map(seg_map).fillna("—")

    categories = sorted(cat_agg["category"].unique().tolist())

    for cat in categories:
        cat_slice = cat_agg[cat_agg["category"] == cat].sort_values("total_spend", ascending=False)
        if cat_slice.empty:
            continue

        best  = cat_slice.head(3)
        worst = cat_slice.tail(3).sort_values("total_spend")

        with st.expander(f"🏷️ {cat}  •  {len(cat_slice)} distributors  •  Total: {_fmt_inr(cat_slice['total_spend'].sum())}"):
            col_b, col_w = st.columns(2)

            with col_b:
                st.markdown("<div style='color:#22c55e;font-weight:700;font-size:12px;margin-bottom:6px;'>🥇 Top Performers</div>", unsafe_allow_html=True)
                for _, r in best.iterrows():
                    seg = r["health"]
                    seg_color = {"Champion": "#22c55e", "Healthy": "#3b82f6",
                                 "At Risk": "#f59e0b", "Critical": "#ef4444"}.get(seg, "#aaa")
                    st.markdown(
                        f"<div style='background:#0d1f0d;border-left:3px solid #22c55e;"
                        f"border-radius:6px;padding:8px 12px;margin-bottom:5px;'>"
                        f"<span style='font-weight:600;color:#e2e8f0;font-size:13px;'>{r['company_name']}</span>"
                        f"<span style='float:right;color:#22c55e;font-weight:700;'>{_fmt_inr(r['total_spend'])}</span><br/>"
                        f"<span style='font-size:11px;color:{seg_color};'>● {seg}</span>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )

            with col_w:
                st.markdown("<div style='color:#ef4444;font-weight:700;font-size:12px;margin-bottom:6px;'>⚠️ Lowest Performers</div>", unsafe_allow_html=True)
                for _, r in worst.iterrows():
                    seg = r["health"]
                    seg_color = {"Champion": "#22c55e", "Healthy": "#3b82f6",
                                 "At Risk": "#f59e0b", "Critical": "#ef4444"}.get(seg, "#aaa")
                    st.markdown(
                        f"<div style='background:#1f0d0d;border-left:3px solid #ef4444;"
                        f"border-radius:6px;padding:8px 12px;margin-bottom:5px;'>"
                        f"<span style='font-weight:600;color:#e2e8f0;font-size:13px;'>{r['company_name']}</span>"
                        f"<span style='float:right;color:#ef4444;font-weight:700;'>{_fmt_inr(r['total_spend'])}</span><br/>"
                        f"<span style='font-size:11px;color:{seg_color};'>● {seg}</span>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )


def render(ai):
    page_header(
        title="Revenue Pipeline Tracker",
        subtitle="Monitor partner health across every stage — Champion, Healthy, At Risk, and Critical.",
        icon="📊",
        accent_color="#6366f1",
    )
    skel = st.empty()
    with skel.container():
        skeleton_loader(n_metric_cards=5, n_rows=2, label="Loading pipeline data...")

    # Load clustering (fast, cached) and optionally churn/credit
    ai.ensure_clustering()
    if getattr(ai, "enable_realtime_partner_scoring", False):
        try:
            ai.ensure_churn_forecast()
            ai.ensure_credit_risk()
        except Exception:
            pass

    skel.empty()

    pf = getattr(ai, "df_partner_features", None)
    if pf is None or pf.empty:
        st.warning("Partner features not available. Run the clustering engine first.")
        return

    # Use cached, lightweight slice
    df = _build_kanban_df(pf)

    # Category performance data from df_recent_group_spend
    group_spend = getattr(ai, "df_recent_group_spend", None)
    cat_perf_df = _build_category_performance(group_spend)

    # ── Main-page filter bar (replaces sidebar filters) ──────────────────
    st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)
    sel_states, sel_cats, sel_credit, sort_by, min_rev, search_query, show_cat_insight = (
        _render_filter_bar(df, cat_perf_df)
    )

    # ── Apply state filter ────────────────────────────────────────────────
    if sel_states:
        df = df[df["state"].isin(sel_states)]

    # ── Apply category filter ─────────────────────────────────────────────
    if sel_cats and not cat_perf_df.empty and "category" in cat_perf_df.columns:
        # Get set of company names that have purchased in selected categories
        cat_companies = set(
            cat_perf_df[cat_perf_df["category"].isin(sel_cats)]["company_name"].unique()
        )
        df = df[df["company_name"].isin(cat_companies)]

    # ── Apply credit risk filter ──────────────────────────────────────────
    if sel_credit != "All" and "credit_risk_band" in df.columns:
        df = df[df["credit_risk_band"] == sel_credit]

    # ── Apply revenue floor ───────────────────────────────────────────────
    if min_rev > 0:
        df = df[df["recent_90_revenue"] >= min_rev]

    # ── Apply name search ─────────────────────────────────────────────────
    if search_query.strip():
        df = df[df["company_name"].str.contains(search_query.strip(), case=False, na=False)]

    # ── Sort ──────────────────────────────────────────────────────────────
    if sort_by == "Revenue (High→Low)":
        df = df.sort_values("recent_90_revenue", ascending=False)
    elif sort_by == "Churn Risk (High→Low)":
        df = df.sort_values("churn_probability", ascending=False)
    elif sort_by == "At Risk (High→Low)":
        df = df.sort_values("revenue_at_risk", ascending=False)
    else:
        df = df.sort_values("company_name")

    st.markdown("---")

    # ── Category insight view (toggle) ────────────────────────────────────
    if show_cat_insight:
        _render_category_insight(cat_perf_df, df)
        st.markdown("---")

    # ── Summary bar — 5 metrics ───────────────────────────────────────────
    total_partners  = len(df)
    high_churn      = int((df["churn_probability"] >= 0.65).sum())
    critical_cnt    = int((df.get("health_segment", pd.Series(dtype=str)) == "Critical").sum())
    total_revenue   = float(df["recent_90_revenue"].sum())
    total_at_risk   = float(df["revenue_at_risk"].sum())

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Partners in Pipeline", total_partners)
    m2.metric("High Churn Risk", high_churn,
              delta=f"⚠️ {high_churn/max(total_partners,1)*100:.0f}% of Pipeline",
              delta_color="inverse")
    m3.metric("Critical Accounts", critical_cnt, delta_color="inverse")
    m4.metric("90d Pipeline Value", _fmt_inr(total_revenue))
    m5.metric("Revenue at Risk ⓘ", _fmt_inr(total_at_risk),
              delta="⚠️ AI Risk + Critical", delta_color="inverse")

    # Active filter info chips
    active_filters = []
    if sel_states:
        active_filters.append(f"📍 {', '.join(sel_states)}")
    if sel_cats:
        active_filters.append(f"🏷️ {', '.join(sel_cats)}")
    if sel_credit != "All":
        active_filters.append(f"💳 {sel_credit} Credit")
    if min_rev > 0:
        active_filters.append(f"₹ ≥ {_fmt_inr(min_rev)}")
    if search_query.strip():
        active_filters.append(f"🔍 \"{search_query.strip()}\"")

    if active_filters:
        chips_html = "".join(
            f"<span style='background:#1e2235;border:1px solid #374151;color:#93c5fd;"
            f"border-radius:20px;padding:3px 10px;font-size:11px;margin-right:6px;'>{f}</span>"
            for f in active_filters
        )
        st.markdown(
            f"<div style='margin-top:6px;margin-bottom:2px;'>"
            f"<span style='color:#64748b;font-size:11px;margin-right:8px;'>Active filters:</span>"
            f"{chips_html}</div>",
            unsafe_allow_html=True,
        )

    st.markdown("---")

    # ── Kanban Board ──────────────────────────────────────────────────────
    cols = st.columns(len(LANES))

    for idx, lane in enumerate(LANES):
        col = cols[idx]
        mask = (
            df["health_segment"].isin(lane["segments"])
            if "health_segment" in df.columns
            else pd.Series(False, index=df.index)
        )
        lane_df = df[mask]
        lane_count = len(lane_df)
        lane_rev   = float(lane_df["recent_90_revenue"].sum())
        lane_risk  = float(lane_df["revenue_at_risk"].sum())

        with col:
            # Lane header
            st.markdown(
                f"""<div style="background:#1a1c23;padding:12px;border-top:4px solid {lane['color']};border-radius:8px;margin-bottom:12px;">
                    <h4 style="margin:0;font-size:15px;color:{lane['color']};">
                        {lane['label']} <span style="font-size:12px;color:#aaa;float:right;">({lane_count})</span>
                    </h4>
                    <div style="font-size:12px;color:#aaa;margin-top:4px;">
                        Value: <b>{_fmt_inr(lane_rev)}</b>
                        &nbsp;|&nbsp; <span style="color:#f59e0b;">⚠ At Risk: {_fmt_inr(lane_risk)}</span>
                    </div>
                </div>""",
                unsafe_allow_html=True,
            )

            if lane_count == 0:
                st.info("Empty")
                continue

            # ── Cards: only render top 50 per lane for speed ──────────────
            shown = lane_df.head(50)
            for _, row in shown.iterrows():
                name       = str(row.get("company_name", "Unknown"))
                rev        = _fmt_inr(row.get("recent_90_revenue", 0))
                churn_raw  = row.get("churn_probability", 0)
                churn_pct  = f"{float(churn_raw)*100:.0f}%" if pd.notnull(churn_raw) else "—"
                credit     = str(row.get("credit_risk_band", "—"))
                state      = str(row.get("state", "—"))
                cluster    = str(row.get("cluster_label", "—"))
                at_risk    = row.get("revenue_at_risk", None)
                drop_pct   = row.get("revenue_drop_pct", None)
                recency    = row.get("recency_days", None)

                # ── Color-code churn severity ──────────────────────────────
                if pd.notnull(churn_raw) and float(churn_raw) >= 0.7:
                    churn_color = "#ef4444"
                elif pd.notnull(churn_raw) and float(churn_raw) >= 0.5:
                    churn_color = "#f59e0b"
                else:
                    churn_color = "#22c55e"

                # ── Revenue trend display ──────────────────────────────────
                if drop_pct is not None and pd.notnull(drop_pct):
                    dp = float(drop_pct)
                    if dp > 0:
                        rev_trend_html = f"<span style='color:#ef4444;font-weight:600'>↓ {dp:.0f}%</span>"
                    elif dp < 0:
                        # Negative drop = growth
                        rev_trend_html = f"<span style='color:#22c55e;font-weight:600'>↑ {abs(dp):.0f}%</span>"
                    else:
                        rev_trend_html = "<span style='color:#aaa'>→ 0%</span>"
                else:
                    rev_trend_html = "<span style='color:#aaa'>—</span>"

                # ── Last order recency ─────────────────────────────────────
                last_order_str = _days_ago(recency) if recency is not None and pd.notnull(recency) else "—"

                # ── At Risk amount display ─────────────────────────────────
                at_risk_str = _fmt_inr(float(at_risk)) if at_risk is not None and pd.notnull(at_risk) and float(at_risk) > 0 else "—"

                # ── State + cluster badge ──────────────────────────────────
                cluster_color = "#22c55e" if "VIP" in cluster else "#6366f1" if "Growth" in cluster else "#aaa"
                badge_html = ""
                if state and state != "—":
                    badge_html += f"<span style='background:#23283a;padding:2px 6px;border-radius:4px;font-size:11px;margin-right:4px;'>📍 {state}</span>"
                if cluster and cluster not in ("—", "nan", "Uncategorized"):
                    badge_html += f"<span style='background:{cluster_color}22;color:{cluster_color};padding:2px 6px;border-radius:4px;font-size:11px;border:1px solid {cluster_color}44;'>🏷 {cluster}</span>"

                # ── Category top spend (from cat_perf_df) ─────────────────
                top_cat_html = ""
                if not cat_perf_df.empty and "category" in cat_perf_df.columns:
                    partner_cats = cat_perf_df[cat_perf_df["company_name"] == name]
                    if not partner_cats.empty:
                        top_cat = partner_cats.loc[partner_cats["total_spend"].idxmax(), "category"]
                        top_cat_spend = partner_cats["total_spend"].max()
                        top_cat_html = (
                            f"<span style='background:#1e1b4b;color:#a5b4fc;padding:2px 6px;"
                            f"border-radius:4px;font-size:11px;margin-left:4px;'>"
                            f"📦 {top_cat} ({_fmt_inr(top_cat_spend)})</span>"
                        )

                with st.expander(f"{name} — {rev}"):
                    if badge_html or top_cat_html:
                        st.markdown(badge_html + top_cat_html, unsafe_allow_html=True)
                    st.markdown(
                        f"**Rev Trend:** {rev_trend_html} &nbsp;|&nbsp; **Last Order:** {last_order_str}  \n"
                        f"**Churn:** <span style='color:{churn_color};font-weight:600'>{churn_pct}</span>"
                        f" &nbsp;|&nbsp; **Credit:** {credit}  \n"
                        f"**At Risk:** {at_risk_str} &nbsp;|&nbsp; **Cluster:** {cluster}",
                        unsafe_allow_html=True,
                    )
                    # ── Primary risk signal (At Risk / Critical only) ──────────
                    if lane["key"] in ("at_risk", "critical"):
                        sig_text, sig_color = _primary_risk_signal(row)
                        if sig_text:
                            st.markdown(
                                f"<div style='margin-top:8px;padding:6px 10px;"
                                f"background:{sig_color}18;border-radius:6px;"
                                f"border-left:3px solid {sig_color};"
                                f"font-size:12px;color:{sig_color};font-weight:600;'>"
                                f"⚡ {sig_text}"
                                f"</div>",
                                unsafe_allow_html=True,
                            )

            if lane_count > 50:
                st.caption(f"Showing top 50 of {lane_count}. Use filters to narrow down.")
