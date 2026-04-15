import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from sklearn.decomposition import PCA

import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from ml_engine.services.export_service import (
    export_cluster_summary_pdf,
    export_cluster_summary_excel,
)
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from styles import apply_global_styles, section_header, page_caption, banner, page_header, skeleton_loader


# ── Helper: format rupees ───────────────────────────────────────────────────
def _fmt_inr(val):
    try:
        v = float(val)
        if v >= 1_00_00_000:
            return f"₹{v/1_00_00_000:.1f} Cr"
        if v >= 1_00_000:
            return f"₹{v/1_00_000:.1f} L"
        if v >= 1_000:
            return f"₹{v/1_000:.1f} K"
        return f"₹{v:,.0f}"
    except Exception:
        return "—"


def _pct_badge(val):
    """Return a colored HTML badge for a growth % value."""
    try:
        v = float(val) * 100
        color = "#10b981" if v >= 0 else "#ef4444"
        arrow = "▲" if v >= 0 else "▼"
        return f"<span style='color:{color};font-weight:700'>{arrow} {abs(v):.1f}%</span>"
    except Exception:
        return "—"


def _cluster_narrative(cluster_df, pf_df, mix_cols):
    """
    Build a plain-English explanation of what makes this cluster distinct.
    Uses the product-spend mix columns and key financial signals.
    """
    lines = []

    # Top product groups
    if mix_cols:
        group_spend = cluster_df[mix_cols].mean().sort_values(ascending=False)
        top_groups = group_spend[group_spend > 0.05].head(4).index.tolist()
        top_groups_clean = [g.replace("mix::rw::", "").replace("_", " ").title() for g in top_groups]
        if top_groups_clean:
            lines.append(f"**🛒 Product Focus:** Partners in this cluster predominantly buy **{', '.join(top_groups_clean)}**.")

    # Revenue signal from partner features
    if pf_df is not None and not pf_df.empty:
        rev_col = next((c for c in ["recent_90_revenue", "total_revenue"] if c in pf_df.columns), None)
        if rev_col:
            avg_rev = float(pf_df[rev_col].mean())
            lines.append(f"**💰 Revenue:** Average quarterly revenue is **{_fmt_inr(avg_rev)}** across this cluster.")

        # Growth signal
        if "growth_rate_90d" in pf_df.columns:
            avg_growth = float(pf_df["growth_rate_90d"].fillna(0).mean())
            direction = "growing" if avg_growth > 0 else "declining"
            lines.append(f"**📈 Trend:** Business is {direction} at **{abs(avg_growth*100):.1f}% QoQ** on average.")

        # Recency signal
        if "recency_days" in pf_df.columns:
            avg_rec = float(pf_df["recency_days"].fillna(999).mean())
            if avg_rec < 30:
                rec_label = "very recently (< 30 days)"
            elif avg_rec < 60:
                rec_label = "within the last 60 days"
            elif avg_rec < 90:
                rec_label = "within the last quarter"
            else:
                rec_label = f"{int(avg_rec)} days ago on average"
            lines.append(f"**🕐 Recency:** Last purchase was **{rec_label}**.")

        # Churn signal
        if "churn_probability" in pf_df.columns:
            avg_churn = float(pf_df["churn_probability"].fillna(0).mean())
            churn_risk = "High" if avg_churn > 0.6 else "Medium" if avg_churn > 0.35 else "Low"
            churn_color = "#ef4444" if churn_risk == "High" else "#f59e0b" if churn_risk == "Medium" else "#10b981"
            lines.append(f"**⚠️ Churn Risk:** Average churn probability is <span style='color:{churn_color};font-weight:700'>{churn_risk} ({avg_churn*100:.0f}%)</span>.")

        # State concentration
        if "state" in cluster_df.columns:
            top_states = cluster_df["state"].value_counts().head(3).index.tolist()
            if top_states:
                lines.append(f"**📍 Geography:** Mostly concentrated in **{', '.join(top_states)}**.")

    return lines


def render(ai):
    apply_global_styles()
    page_header(
        title="Cluster Intelligence",
        subtitle="AI-generated partner segments based on buying behaviour, RFM signals, and category mix.",
        icon="🧠",
        accent_color="#8b5cf6",
        badge_text="HDBSCAN + GMM",
    )
    skel = st.empty()
    with skel.container():
        skeleton_loader(n_metric_cards=4, n_rows=3, label="Running clustering engine...")
    ai.ensure_clustering()
    skel.empty()

    matrix = ai.matrix.copy()
    if matrix is None or matrix.empty:
        st.warning("Cluster matrix is empty. Refresh data and try again.")
        return

    if "cluster_label" not in matrix.columns:
        matrix["cluster_label"] = matrix["cluster"].astype(str)
    if "cluster_type" not in matrix.columns:
        matrix["cluster_type"] = "Growth"
    if "strategic_tag" not in matrix.columns:
        matrix["strategic_tag"] = "N/A"
    if "state" not in matrix.columns:
        matrix["state"] = "Unknown"

    # ── Summary KPI strip ────────────────────────────────────────────────────
    is_outlier = matrix["cluster_label"].astype(str).str.contains("Outlier|Uncategorized", case=False, na=False)
    n_clusters = matrix.loc[~is_outlier, "cluster_label"].nunique()
    n_outliers = int(is_outlier.sum())
    n_vip      = int((matrix["cluster_type"] == "VIP").sum())

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Total Clusters Formed", int(n_clusters))
    with c2:
        st.metric("Outlier Partners", n_outliers)
    with c3:
        st.metric("VIP Partners", n_vip)
    with c4:
        label_method = "—"
        if hasattr(ai, "cluster_label_report") and isinstance(ai.cluster_label_report, dict):
            method_raw = ai.cluster_label_report.get("method", "")
            label_method = {
                "gemini_llm": "🧠 LLM (Gemini)",
                "heuristic":  "📊 Heuristic",
            }.get(str(method_raw).lower(), str(method_raw) or "—")
        st.metric("Label Method", label_method)

    # ── Export Buttons ────────────────────────────────────────────────────────
    cex1, cex2, cex3 = st.columns([1, 1, 4])
    with cex1:
        cluster_pdf = export_cluster_summary_pdf(
            matrix,
            quality_report=ai.get_cluster_quality_report() if hasattr(ai, "get_cluster_quality_report") else None,
            business_report=ai.get_cluster_business_validation_report() if hasattr(ai, "get_cluster_business_validation_report") else None,
        )
        st.download_button(
            "⬇ Download PDF",
            data=cluster_pdf,
            file_name="Cluster_Summary.pdf",
            mime="application/pdf",
            key="cluster_pdf",
        )
    with cex2:
        cluster_xls = export_cluster_summary_excel(
            matrix,
            quality_report=ai.get_cluster_quality_report() if hasattr(ai, "get_cluster_quality_report") else None,
            business_report=ai.get_cluster_business_validation_report() if hasattr(ai, "get_cluster_business_validation_report") else None,
        )
        st.download_button(
            "⬇ Download Excel",
            data=cluster_xls,
            file_name="Cluster_Summary.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="cluster_xlsx",
        )

    st.markdown("---")

    # ── Cluster Summary Table ─────────────────────────────────────────────────
    section_header("Cluster Summary")
    cluster_summary = (
        matrix[~is_outlier]
        .groupby(["cluster_label", "cluster_type"])
        .agg(Partners=("cluster_label", "count"))
        .reset_index()
        .sort_values("Partners", ascending=False)
    )
    rev_col = next((c for c in ["total_revenue", "revenue", "Total Revenue"] if c in matrix.columns), None)
    if rev_col:
        rev_agg = matrix[~is_outlier].groupby("cluster_label")[rev_col].mean().rename("Avg Revenue (Rs)")
        cluster_summary = cluster_summary.merge(rev_agg, on="cluster_label", how="left")
        st.dataframe(
            cluster_summary,
            column_config={
                "cluster_label": st.column_config.TextColumn("Cluster"),
                "cluster_type": "Type",
                "Partners": st.column_config.NumberColumn("Partners", format="%d"),
                "Avg Revenue (Rs)": st.column_config.NumberColumn("Avg Revenue", format="Rs %.0f"),
            },
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.dataframe(
            cluster_summary,
            column_config={
                "cluster_label": st.column_config.TextColumn("Cluster"),
                "cluster_type": "Type",
                "Partners": st.column_config.NumberColumn("Partners", format="%d"),
            },
            use_container_width=True,
            hide_index=True,
        )

    # ── 3D DNA Map ────────────────────────────────────────────────────────────
    section_header("Partner DNA Map (3D)")

    f1, f2 = st.columns([1, 2])
    with f1:
        type_options  = ["All"] + sorted(matrix["cluster_type"].dropna().unique().tolist())
        selected_type = st.selectbox("Cluster Type", type_options)
    with f2:
        if selected_type != "All":
            label_pool = matrix[matrix["cluster_type"] == selected_type]["cluster_label"].dropna().unique().tolist()
        else:
            label_pool = matrix["cluster_label"].dropna().unique().tolist()
        label_options  = ["All"] + sorted(label_pool)
        selected_label = st.selectbox("Cluster Label", label_options)

    filtered = matrix.copy()
    if selected_type != "All":
        filtered = filtered[filtered["cluster_type"] == selected_type]
    if selected_label != "All":
        filtered = filtered[filtered["cluster_label"] == selected_label]

    if filtered.empty:
        st.warning("No partners match the selected filters.")
        return

    # PCA for the 3D scatter
    feature_df = filtered.select_dtypes(include=[np.number]).drop(
        columns=["cluster"], errors="ignore"
    ).fillna(0)

    if feature_df.shape[1] >= 2:
        n_components = min(3, feature_df.shape[0], feature_df.shape[1])
        if n_components >= 2:
            log_features = np.log1p(feature_df)
            pca = PCA(n_components=n_components, random_state=42)
            components = pca.fit_transform(log_features)

            plot_df = pd.DataFrame(index=filtered.index)
            plot_df["x"] = components[:, 0]
            plot_df["y"] = components[:, 1]
            plot_df["z"] = components[:, 2] if n_components >= 3 else 0.0
            plot_df["Partner"]       = filtered.index
            plot_df["Cluster"]       = filtered["cluster_label"].astype(str)
            plot_df["Cluster Type"]  = filtered["cluster_type"].astype(str)
            plot_df["Strategic Tag"] = filtered["strategic_tag"].astype(str)
            plot_df["State"]         = filtered["state"].astype(str)

            col_map, col_comp = st.columns([2, 1])
            with col_map:
                fig = px.scatter_3d(
                    plot_df, x="x", y="y", z="z",
                    color="Cluster",
                    symbol="Cluster Type",
                    hover_name="Partner",
                    hover_data=["State", "Strategic Tag"],
                    title="Partner DNA Map",
                    color_discrete_sequence=px.colors.qualitative.Bold,
                )
                fig.update_traces(marker=dict(size=7, opacity=0.85))
                fig.update_layout(height=450, margin=dict(l=0, r=0, b=0, t=30))
                st.plotly_chart(fig, use_container_width=True)
            with col_comp:
                comp_df = plot_df.groupby(["Cluster", "Cluster Type"]).size().reset_index(name="Count")
                fig_comp = px.bar(
                    comp_df, x="Cluster", y="Count", color="Cluster Type",
                    title="Composition Breakdown",
                    barmode="stack",
                    color_discrete_sequence=px.colors.qualitative.Pastel,
                )
                fig_comp.update_layout(height=450, margin=dict(l=0, r=0, b=0, t=40))
                st.plotly_chart(fig_comp, use_container_width=True)

    st.markdown("---")

    # ════════════════════════════════════════════════════════════════════════
    # CLUSTER DEEP-DIVE — shown only when a specific cluster label is chosen
    # ════════════════════════════════════════════════════════════════════════
    if selected_label == "All":
        st.info("👆 Select a specific **Cluster Label** above to see the deep-dive partner analysis.")
        return

    section_header(f"🔍 Cluster Deep-Dive — {selected_label}")

    # ── Pull partner features for this cluster ────────────────────────────────
    pf_raw = getattr(ai, "df_partner_features", None)
    pf_cluster = None
    if pf_raw is not None and not pf_raw.empty:
        pf_reset = pf_raw.reset_index()
        if "company_name" not in pf_reset.columns:
            pf_reset = pf_reset.rename(columns={"index": "company_name"})
        pf_reset = pf_reset.set_index("company_name")
        common_idx = filtered.index.intersection(pf_reset.index)
        if len(common_idx) > 0:
            pf_cluster = pf_reset.loc[common_idx]

    # ── Mix cols for the selected cluster ────────────────────────────────────
    mix_cols = [c for c in filtered.columns if c.startswith("mix::rw::") or
                (c not in ["cluster", "cluster_type", "cluster_label", "strategic_tag", "state"]
                 and filtered[c].dtype in [np.float64, np.int64, float, int])]

    # ── Cluster narrative (Why are they here?) ───────────────────────────────
    narrative_lines = _cluster_narrative(filtered, pf_cluster, mix_cols)
    if narrative_lines:
        st.markdown(
            """
            <div style="
                background: rgba(139,92,246,0.08);
                border-left: 4px solid #8b5cf6;
                border-radius: 8px;
                padding: 16px 20px;
                margin-bottom: 18px;
            ">
            <p style="font-size:1rem;font-weight:700;color:#8b5cf6;margin-bottom:8px;">
                💡 Why are these partners grouped together?
            </p>
            """
            + "".join(f"<p style='margin:4px 0;font-size:0.9rem;line-height:1.6;'>{l}</p>" for l in narrative_lines)
            + "</div>",
            unsafe_allow_html=True,
        )

    # ── Revenue KPIs for the cluster ──────────────────────────────────────────
    if pf_cluster is not None:
        rev_90_col  = next((c for c in ["recent_90_revenue", "total_revenue"] if c in pf_cluster.columns), None)
        prev_90_col = "prev_90_revenue" if "prev_90_revenue" in pf_cluster.columns else None
        life_col    = "lifetime_revenue" if "lifetime_revenue" in pf_cluster.columns else None

        if rev_90_col:
            total_q  = float(pf_cluster[rev_90_col].sum())
            avg_q    = float(pf_cluster[rev_90_col].mean())
            avg_mo   = avg_q / 3.0
            avg_yr   = avg_q * 4.0
            total_yr = total_q * 4.0

            # QoQ growth
            qoq_delta = None
            if prev_90_col:
                prev_avg = float(pf_cluster[prev_90_col].mean())
                if prev_avg > 0:
                    qoq_delta = (avg_q - prev_avg) / prev_avg * 100

            k1, k2, k3, k4 = st.columns(4)
            k1.metric(
                "Avg Monthly Rev",
                _fmt_inr(avg_mo),
                delta=f"{qoq_delta:+.1f}% QoQ" if qoq_delta is not None else None,
                delta_color="normal",
            )
            k2.metric("Avg Quarterly Rev", _fmt_inr(avg_q))
            k3.metric("Avg Annual Rev (est.)", _fmt_inr(avg_yr))
            k4.metric("Total Cluster Rev (Qtr)", _fmt_inr(total_q))

    # ── Revenue comparison bar (cluster vs overall) ───────────────────────────
    if pf_cluster is not None and rev_90_col:
        all_labels = matrix["cluster_label"].dropna().unique()
        rev_by_cluster = []
        for lbl in all_labels:
            idx_lbl = matrix[matrix["cluster_label"] == lbl].index
            if pf_raw is not None:
                pf_all = pf_raw.reset_index()
                if "company_name" not in pf_all.columns:
                    pf_all = pf_all.rename(columns={"index": "company_name"})
                pf_all = pf_all.set_index("company_name")
                common = idx_lbl.intersection(pf_all.index)
                if len(common) > 0 and rev_90_col in pf_all.columns:
                    avg = float(pf_all.loc[common, rev_90_col].mean())
                    rev_by_cluster.append({"Cluster": lbl, "Avg Quarterly Rev": avg})

        if rev_by_cluster:
            rev_bar_df = pd.DataFrame(rev_by_cluster).sort_values("Avg Quarterly Rev", ascending=False)
            rev_bar_df["highlight"] = rev_bar_df["Cluster"] == selected_label
            fig_rev = px.bar(
                rev_bar_df, x="Cluster", y="Avg Quarterly Rev",
                color="highlight",
                color_discrete_map={True: "#8b5cf6", False: "#334155"},
                title="Avg Quarterly Revenue — All Clusters",
                text="Avg Quarterly Rev",
            )
            fig_rev.update_traces(
                texttemplate=[_fmt_inr(v) for v in rev_bar_df["Avg Quarterly Rev"]],
                textposition="outside",
            )
            fig_rev.update_layout(
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                showlegend=False,
                height=320,
                xaxis_title="Cluster",
                yaxis_title="Avg Quarterly Revenue (₹)",
            )
            st.plotly_chart(fig_rev, use_container_width=True)

    st.markdown("---")

    # ── Partner roster with state + revenue ──────────────────────────────────
    section_header(f"👥 Partners in this Cluster ({len(filtered)})")

    # Build display dataframe
    roster_rows = []
    for partner in filtered.index:
        state = str(filtered.at[partner, "state"]) if "state" in filtered.columns else "Unknown"
        strat = str(filtered.at[partner, "strategic_tag"]) if "strategic_tag" in filtered.columns else "—"

        row = {
            "Partner Name": partner,
            "State":        state,
            "Strategic Tag": strat,
        }

        # Pull revenue from partner features
        if pf_cluster is not None and partner in pf_cluster.index:
            _raw = pf_cluster.loc[partner]
            # .loc can return a Series (single-partner) OR a DataFrame (dup index).
            # Normalise to a plain dict so scalar access is safe everywhere.
            if isinstance(_raw, pd.DataFrame):
                pf_row = _raw.iloc[0].to_dict()
            else:
                pf_row = _raw.to_dict()

            def _scalar(key, default=0):
                v = pf_row.get(key, default)
                if isinstance(v, (pd.Series, pd.DataFrame)):
                    v = v.iloc[0] if len(v) else default
                try:
                    return v if v is not None else default
                except Exception:
                    return default

            q_rev   = float(_scalar(rev_90_col, 0)) if rev_90_col else 0.0
            mo_rev  = q_rev / 3.0
            yr_rev  = q_rev * 4.0
            lt_rev  = float(_scalar(life_col, 0)) if life_col else 0.0
            growth  = float(_scalar("growth_rate_90d", 0))
            recency = int(float(_scalar("recency_days", 999)))
            health  = str(_scalar("health_segment", "—") or "—")
            churn_p = float(_scalar("churn_probability", 0))

            row["Monthly Rev (est.)"]   = mo_rev
            row["Quarterly Rev"]        = q_rev
            row["Annual Rev (est.)"]    = yr_rev
            row["Lifetime Revenue"]     = lt_rev
            row["QoQ Growth %"]         = growth * 100
            row["Recency (days)"]       = recency
            row["Health Segment"]       = health
            row["Churn Risk %"]         = churn_p * 100
        else:
            # Fallback from matrix spend
            spend_cols = [c for c in filtered.columns if c not in
                          ["cluster", "cluster_type", "cluster_label", "strategic_tag", "state"]
                          and filtered[c].dtype in [np.float64, np.int64, float, int]]
            total_spend = float(filtered.loc[partner, spend_cols].sum()) if spend_cols else 0.0
            row["Monthly Rev (est.)"]  = total_spend / 3.0
            row["Quarterly Rev"]       = total_spend
            row["Annual Rev (est.)"]   = total_spend * 4.0
            row["Lifetime Revenue"]    = total_spend
            row["QoQ Growth %"]        = 0.0
            row["Recency (days)"]      = 999
            row["Health Segment"]      = "—"
            row["Churn Risk %"]        = 0.0

        roster_rows.append(row)

    roster_df = pd.DataFrame(roster_rows).sort_values("Quarterly Rev", ascending=False)

    # Color map for health segment
    health_color_map = {
        "Champion": "🏆",
        "Emerging": "🚀",
        "Healthy":  "✅",
        "At Risk":  "⚠️",
        "Critical": "🔴",
    }
    if "Health Segment" in roster_df.columns:
        roster_df["🏥 Health"] = roster_df["Health Segment"].map(
            lambda x: f"{health_color_map.get(x, '❓')} {x}"
        )

    # Display columns
    display_cols = ["Partner Name", "State", "🏥 Health", "Monthly Rev (est.)",
                    "Quarterly Rev", "Annual Rev (est.)", "Lifetime Revenue",
                    "QoQ Growth %", "Recency (days)", "Churn Risk %", "Strategic Tag"]
    display_cols = [c for c in display_cols if c in roster_df.columns]

    st.dataframe(
        roster_df[display_cols],
        column_config={
            "Partner Name":         st.column_config.TextColumn("Partner"),
            "State":                st.column_config.TextColumn("Area (State)"),
            "🏥 Health":            st.column_config.TextColumn("Health"),
            "Monthly Rev (est.)":   st.column_config.NumberColumn("Monthly Rev", format="₹%.0f"),
            "Quarterly Rev":        st.column_config.NumberColumn("Quarterly Rev", format="₹%.0f"),
            "Annual Rev (est.)":    st.column_config.NumberColumn("Annual Rev", format="₹%.0f"),
            "Lifetime Revenue":     st.column_config.NumberColumn("Lifetime Rev", format="₹%.0f"),
            "QoQ Growth %":         st.column_config.NumberColumn("QoQ Growth", format="%.1f%%"),
            "Recency (days)":       st.column_config.NumberColumn("Last Purchase", format="%d days"),
            "Churn Risk %":         st.column_config.ProgressColumn("Churn Risk", format="%.0f%%", min_value=0, max_value=100),
            "Strategic Tag":        st.column_config.TextColumn("Strategy"),
        },
        use_container_width=True,
        hide_index=True,
    )

    # ── CSV Export ────────────────────────────────────────────────────────────
    safe_label = selected_label.replace(" ", "_").replace("/", "-")
    st.download_button(
        "⬇️ Export Partner Roster",
        data=roster_df[display_cols].to_csv(index=False),
        file_name=f"cluster_{safe_label}_partners.csv",
        mime="text/csv",
        use_container_width=False,
    )

    st.markdown("---")

    # ── Similarity spider / radar chart ──────────────────────────────────────
    section_header("🕸️ Cluster Similarity Profile")

    st.markdown(
        """<p style='color:#94a3b8;font-size:0.88rem;margin-bottom:12px;'>
        The radar below shows how this cluster scores on key signals vs the overall average.
        A wider shape = stronger differentiation from the rest.
        </p>""",
        unsafe_allow_html=True,
    )

    # Build normalized radar from key metrics
    radar_metrics = {}

    if pf_cluster is not None and not pf_cluster.empty:
        pf_all_reset = pf_raw.reset_index() if pf_raw is not None else None
        if pf_all_reset is not None and "company_name" not in pf_all_reset.columns:
            pf_all_reset = pf_all_reset.rename(columns={"index": "company_name"})
        pf_all_full = pf_all_reset.set_index("company_name") if pf_all_reset is not None else pf_cluster

        def _norm_metric(col, higher_is_better=True):
            """Return (cluster_val, overall_val) both in 0–1 range."""
            if col not in pf_cluster.columns or col not in pf_all_full.columns:
                return None, None
            c_val  = float(pf_cluster[col].mean())
            a_val  = float(pf_all_full[col].replace([np.inf, -np.inf], np.nan).mean())
            lo     = float(pf_all_full[col].replace([np.inf, -np.inf], np.nan).min())
            hi     = float(pf_all_full[col].replace([np.inf, -np.inf], np.nan).max())
            rng    = hi - lo if (hi - lo) > 0 else 1.0
            c_norm = (c_val - lo) / rng
            a_norm = (a_val - lo) / rng
            if not higher_is_better:
                c_norm = 1 - c_norm
                a_norm = 1 - a_norm
            return round(float(np.clip(c_norm, 0, 1)), 3), round(float(np.clip(a_norm, 0, 1)), 3)

        metric_defs = [
            ("Revenue",  "recent_90_revenue",   True),
            ("Growth",   "growth_rate_90d",      True),
            ("Loyalty",  "recency_days",         False),   # lower recency = more loyal
            ("Safety",   "churn_probability",    False),   # lower churn = safer
            ("Stability","revenue_volatility",   False),   # lower volatility = stable
            ("Breadth",  "category_count",       True),
        ]

        cluster_vals = []
        overall_vals = []
        labels       = []
        for label, col, hib in metric_defs:
            cv, av = _norm_metric(col, hib)
            if cv is not None:
                cluster_vals.append(cv)
                overall_vals.append(av)
                labels.append(label)

        if len(labels) >= 3:
            fig_radar = go.Figure()
            fig_radar.add_trace(go.Scatterpolar(
                r=cluster_vals + [cluster_vals[0]],
                theta=labels + [labels[0]],
                fill="toself",
                name=selected_label[:30],
                line=dict(color="#8b5cf6", width=2),
                fillcolor="rgba(139,92,246,0.25)",
            ))
            fig_radar.add_trace(go.Scatterpolar(
                r=overall_vals + [overall_vals[0]],
                theta=labels + [labels[0]],
                fill="toself",
                name="Overall Average",
                line=dict(color="#64748b", width=1.5, dash="dot"),
                fillcolor="rgba(100,116,139,0.12)",
            ))
            fig_radar.update_layout(
                polar=dict(
                    radialaxis=dict(visible=True, range=[0, 1], tickfont=dict(size=9)),
                    angularaxis=dict(tickfont=dict(size=12)),
                ),
                showlegend=True,
                height=400,
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                title=f"Signal Profile — {selected_label[:35]}",
            )
            st.plotly_chart(fig_radar, use_container_width=True)

    # ── State distribution bar ────────────────────────────────────────────────
    if "state" in filtered.columns:
        _vc = filtered["state"].fillna("Unknown").value_counts().reset_index()
        # pandas ≥2.0 value_counts reset_index gives columns ['state','count']
        # older pandas gives columns ['index','state']
        if "state" in _vc.columns and "count" in _vc.columns:
            state_counts = _vc.rename(columns={"state": "State", "count": "Partners"})
        elif "index" in _vc.columns:
            state_counts = _vc.rename(columns={"index": "State", "state": "Partners"})
        else:
            state_counts = _vc.copy()
            state_counts.columns = ["State", "Partners"]

        if len(state_counts) > 1:
            section_header("📍 Geographic Spread")
            fig_state = px.bar(
                state_counts.head(12), x="State", y="Partners",
                title="Partner Distribution by State",
                color="Partners",
                color_continuous_scale="Purples",
                text="Partners",
            )
            fig_state.update_traces(textposition="outside")
            fig_state.update_layout(
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                xaxis_title="State",
                yaxis_title="No. of Partners",
                coloraxis_showscale=False,
                height=300,
            )
            st.plotly_chart(fig_state, use_container_width=True)

    # ── Top product categories for this cluster ────────────────────────────────
    raw_mix = [c for c in filtered.columns if c.startswith("mix::rw::")]
    if not raw_mix:
        raw_mix = [c for c in filtered.columns if c not in
                   ["cluster", "cluster_type", "cluster_label", "strategic_tag", "state"]
                   and filtered[c].dtype in [np.float64, np.int64, float, int]]

    if raw_mix:
        section_header("🛒 Product Category Affinity")
        cat_avg = filtered[raw_mix].mean().sort_values(ascending=False).head(10)
        cat_df  = pd.DataFrame({
            "Category": [c.replace("mix::rw::", "").replace("_", " ").title() for c in cat_avg.index],
            "Avg Spend Share": cat_avg.values,
        })
        fig_cat = px.bar(
            cat_df, x="Avg Spend Share", y="Category",
            orientation="h",
            title="Top Product Categories (by avg spend share)",
            color="Avg Spend Share",
            color_continuous_scale="Purpor",
            text="Avg Spend Share",
        )
        fig_cat.update_traces(texttemplate="%{text:.1%}", textposition="outside")
        fig_cat.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            xaxis_tickformat=".0%",
            xaxis_title="Avg Spend Share",
            yaxis_title="",
            coloraxis_showscale=False,
            height=max(280, len(cat_df) * 32),
        )
        st.plotly_chart(fig_cat, use_container_width=True)
