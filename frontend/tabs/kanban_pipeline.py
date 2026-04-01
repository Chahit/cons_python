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

# Cluster label → emoji badge
CLUSTER_BADGES = {
    "vip":       "👑 VIP",
    "champion":  "🏆 Champion",
    "growth":    "📈 Growth",
    "emerging":  "🌱 Emerging",
    "dormant":   "💤 Dormant",
    "at-risk":   "⚠️ At-Risk",
    "niche":     "🎯 Niche",
    "outlier":   "🔍 Outlier",
}

def _cluster_badge(label: str) -> str:
    if not label or label in ("Unknown", "—", ""):
        return ""
    lower = str(label).lower()
    for key, badge in CLUSTER_BADGES.items():
        if key in lower:
            return badge
    return f"🔷 {label}"

def _fmt_inr(val):
    try:
        v = float(val)
    except Exception:
        return "₹0"
    if v >= 1_00_00_000: return f"₹{v / 1_00_00_000:.1f}Cr"
    if v >= 1_00_000:    return f"₹{v / 1_00_000:.1f}L"
    if v >= 1_000:       return f"₹{v / 1_000:.0f}K"
    return f"₹{v:.0f}"

def _trend_arrow(drop_pct):
    """Return colored arrow + pct string based on revenue_drop_pct."""
    try:
        d = float(drop_pct)
    except Exception:
        return ""
    if d >= 30:
        return f"<span style='color:#ef4444;font-weight:700'>▼ {d:.0f}%</span>"
    if d >= 10:
        return f"<span style='color:#f59e0b;font-weight:700'>▼ {d:.0f}%</span>"
    if d <= -10:   # negative drop = growth
        return f"<span style='color:#22c55e;font-weight:700'>▲ {abs(d):.0f}%</span>"
    return f"<span style='color:#94a3b8'>→ {abs(d):.0f}%</span>"

def _churn_border_color(churn_raw):
    try:
        c = float(churn_raw)
    except Exception:
        return "#334155"
    if c >= 0.70: return "#ef4444"
    if c >= 0.50: return "#f59e0b"
    if c >= 0.30: return "#3b82f6"
    return "#22c55e"

def _last_seen(recency_days):
    try:
        d = int(float(recency_days))
    except Exception:
        return "—"
    if d == 0:   return "Today"
    if d == 1:   return "Yesterday"
    if d <= 7:   return f"{d}d ago"
    if d <= 30:  return f"{d // 7}w ago"
    if d <= 365: return f"{d // 30}mo ago"
    return f"{d // 365}y ago"

# ── Cache the heavy data slice ──────────────────────────────────────────────
@st.cache_data(ttl=300, show_spinner=False)
def _build_kanban_df(_pf_df):
    """Extract and pre-process only the columns needed by the Kanban board."""
    needed = [
        "company_name", "state", "health_segment", "health_status",
        "churn_probability", "credit_risk_band",
        "recent_90_revenue", "revenue_drop_pct",
        "recency_days", "cluster_label", "cluster_type",
        "expected_revenue_at_risk_90d",
    ]
    df = _pf_df.reset_index()
    if "company_name" not in df.columns and "index" in df.columns:
        df = df.rename(columns={"index": "company_name"})
    cols_present = [c for c in needed if c in df.columns]
    df = df[cols_present].copy()

    # Fill defaults for optional columns
    for col, default in [
        ("churn_probability", 0.0),
        ("revenue_drop_pct", 0.0),
        ("recency_days", 0.0),
        ("expected_revenue_at_risk_90d", 0.0),
        ("credit_risk_band", "N/A"),
        ("health_segment", "Healthy"),
        ("cluster_label", ""),
        ("cluster_type", ""),
    ]:
        if col not in df.columns:
            df[col] = default

    for col in ["churn_probability", "recent_90_revenue", "revenue_drop_pct",
                "recency_days", "expected_revenue_at_risk_90d"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    # Fallback: if churn scoring was skipped (fast_mode=True) the
    # expected_revenue_at_risk_90d column may be 0 even though churn_probability
    # is non-zero. In that case compute it inline so the Kanban always shows
    # meaningful risk values.
    # Formula: churn_probability × recent_90_revenue (probability-weighted loss).
    # WHY: This is the same formula used in churn_credit_stub_mixin when full
    # scoring runs — applying it here as a fallback ensures consistency.
    zero_risk_mask = df["expected_revenue_at_risk_90d"] == 0.0
    has_churn_prob = df["churn_probability"] > 0.0
    fallback_mask = zero_risk_mask & has_churn_prob
    if fallback_mask.any():
        df.loc[fallback_mask, "expected_revenue_at_risk_90d"] = (
            df.loc[fallback_mask, "churn_probability"]
            * df.loc[fallback_mask, "recent_90_revenue"]
        ).round(2)

    return df


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

    df = _build_kanban_df(pf)

    # ── Sidebar filters ─────────────────────────────────────────────────────
    st.sidebar.markdown("---")
    st.sidebar.markdown("**🔍 Pipeline Filters**")

    all_states = sorted(df["state"].dropna().unique().tolist()) if "state" in df.columns else []
    sel_states = st.sidebar.multiselect("Filter by State", all_states, default=[], key="kb_states")
    if sel_states:
        df = df[df["state"].isin(sel_states)]

    credit_opts = ["All", "Low", "Medium", "High", "Critical"]
    sel_credit  = st.sidebar.selectbox("Filter by Credit Risk", credit_opts, key="kb_credit")
    if sel_credit != "All" and "credit_risk_band" in df.columns:
        df = df[df["credit_risk_band"] == sel_credit]

    sort_by = st.sidebar.selectbox(
        "Sort cards by",
        ["Revenue (High→Low)", "Churn Risk (High→Low)", "Revenue Drop (High→Low)", "Name (A→Z)"],
        key="kb_sort",
    )

    min_rev = st.sidebar.number_input("Min 90d Revenue (₹)", value=0, step=10000, key="kb_minrev")
    if min_rev > 0:
        df = df[df["recent_90_revenue"] >= min_rev]

    search_query = st.text_input("🔍 Search partner by name", placeholder="Type a company name...", key="kb_search")
    if search_query.strip():
        df = df[df["company_name"].str.contains(search_query.strip(), case=False, na=False)]

    # ── Sort ────────────────────────────────────────────────────────────────
    if sort_by == "Revenue (High→Low)":
        df = df.sort_values("recent_90_revenue", ascending=False)
    elif sort_by == "Churn Risk (High→Low)":
        df = df.sort_values("churn_probability", ascending=False)
    elif sort_by == "Revenue Drop (High→Low)":
        df = df.sort_values("revenue_drop_pct", ascending=False)
    else:
        df = df.sort_values("company_name")

    st.markdown("---")

    # ── Summary bar — 5 metrics ──────────────────────────────────────────────
    total_partners = len(df)
    high_churn     = int((df["churn_probability"] >= 0.65).sum())
    critical_cnt   = int((df.get("health_segment", pd.Series(dtype=str)) == "Critical").sum())
    total_revenue  = float(df["recent_90_revenue"].sum())

    # Revenue at risk = expected_revenue_at_risk_90d for At Risk + Critical lanes
    at_risk_mask = df["health_segment"].isin({"At Risk", "Critical"}) if "health_segment" in df.columns else pd.Series(False, index=df.index)
    revenue_at_risk = float(df.loc[at_risk_mask, "expected_revenue_at_risk_90d"].sum())

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Partners in Pipeline", total_partners)
    m2.metric("High Churn Risk", high_churn,
              delta=f"{high_churn/max(total_partners,1)*100:.0f}% of Pipeline",
              delta_color="inverse")
    m3.metric("Critical Accounts", critical_cnt, delta_color="inverse")
    m4.metric("90d Pipeline Value", _fmt_inr(total_revenue))
    m5.metric(
        "⚠️ Revenue at Risk",
        _fmt_inr(revenue_at_risk),
        delta="At Risk + Critical",
        delta_color="inverse",
        help="Sum of expected_revenue_at_risk_90d for all At Risk and Critical partners",
    )

    st.markdown("---")

    # ── Kanban Board ─────────────────────────────────────────────────────────
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
        lane_at_risk_rev = float(lane_df["expected_revenue_at_risk_90d"].sum())

        with col:
            # Lane header
            at_risk_row = (
                f"<div style='font-size:11px;color:#f87171;margin-top:2px;'>⚠️ At Risk: <b>{_fmt_inr(lane_at_risk_rev)}</b></div>"
                if lane_at_risk_rev > 0 else ""
            )
            st.markdown(
                f"""<div style="background:#1a1c23;padding:12px;border-top:4px solid {lane['color']};border-radius:8px;margin-bottom:12px;">
                    <h4 style="margin:0;font-size:15px;color:{lane['color']};">
                        {lane['label']} <span style="font-size:12px;color:#aaa;float:right;">({lane_count})</span>
                    </h4>
                    <div style="font-size:12px;color:#aaa;margin-top:4px;">Value: <b>{_fmt_inr(lane_rev)}</b></div>
                    {at_risk_row}
                </div>""",
                unsafe_allow_html=True,
            )

            if lane_count == 0:
                st.info("Empty")
                continue

            # ── Cards: top 50 per lane ────────────────────────────────────
            shown = lane_df.head(50)
            for _, row in shown.iterrows():
                name        = str(row.get("company_name", "Unknown"))
                rev         = _fmt_inr(row.get("recent_90_revenue", 0))
                churn_raw   = row.get("churn_probability", 0)
                churn_pct   = f"{float(churn_raw)*100:.0f}%" if pd.notnull(churn_raw) else "—"
                credit      = str(row.get("credit_risk_band", "—"))
                state       = str(row.get("state", "—"))
                drop_pct    = row.get("revenue_drop_pct", 0)
                recency     = row.get("recency_days", 0)
                at_risk_rev = row.get("expected_revenue_at_risk_90d", 0)
                clabel      = str(row.get("cluster_label", ""))
                ctype       = str(row.get("cluster_type", ""))

                churn_color  = _churn_border_color(churn_raw)
                trend_html   = _trend_arrow(drop_pct)
                last_seen    = _last_seen(recency)
                badge        = _cluster_badge(clabel)
                at_risk_str  = _fmt_inr(at_risk_rev) if at_risk_rev > 0 else "—"

                # Credit badge color
                credit_colors = {"Low": "#22c55e", "Medium": "#f59e0b",
                                 "High": "#ef4444", "Critical": "#dc2626"}
                credit_color = credit_colors.get(credit, "#94a3b8")

                with st.expander(f"{name} — {rev}"):
                    # Row 1: State + cluster badge
                    badge_str = f"&nbsp;&nbsp;•&nbsp;&nbsp;{badge}" if badge else ""
                    st.markdown(
                        f"<span style='color:#94a3b8;font-size:12px;'>📍 {state}{badge_str}</span>",
                        unsafe_allow_html=True,
                    )

                    # Row 2: Revenue trend + Last order
                    c1, c2 = st.columns(2)
                    with c1:
                        st.markdown(
                            f"**Rev Trend:** {trend_html}",
                            unsafe_allow_html=True,
                        )
                    with c2:
                        st.markdown(
                            f"**Last Order:** <span style='color:#94a3b8'>{last_seen}</span>",
                            unsafe_allow_html=True,
                        )

                    # Row 3: Churn + Credit
                    c3, c4 = st.columns(2)
                    with c3:
                        st.markdown(
                            f"**Churn:** <span style='color:{churn_color};font-weight:600'>{churn_pct}</span>",
                            unsafe_allow_html=True,
                        )
                    with c4:
                        st.markdown(
                            f"**Credit:** <span style='color:{credit_color};font-weight:600'>{credit}</span>",
                            unsafe_allow_html=True,
                        )

                    # Row 4: Revenue at Risk + Cluster type
                    c5, c6 = st.columns(2)
                    with c5:
                        st.markdown(
                            f"**At Risk:** <span style='color:#f87171'>{at_risk_str}</span>",
                            unsafe_allow_html=True,
                        )
                    with c6:
                        label_val = (ctype or clabel or "").strip()
                        if label_val and label_val not in ("Unknown", "—", ""):
                            st.markdown(
                                f"**Cluster:** <span style='color:#a5b4fc'>{label_val}</span>",
                                unsafe_allow_html=True,
                            )


            if lane_count > 50:
                st.caption(f"Showing top 50 of {lane_count}. Use filters to narrow down.")
