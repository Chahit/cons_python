import numpy as np
import pandas as pd
import plotly.express as px
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

    # Stats — detect outliers by either legacy "Outlier" label or renamed "Uncategorized"
    is_outlier = matrix["cluster_label"].astype(str).str.contains("Outlier|Uncategorized", case=False, na=False)
    n_clusters = matrix.loc[~is_outlier, "cluster_label"].nunique()
    n_outliers = is_outlier.sum()
    n_vip = (matrix["cluster_type"] == "VIP").sum()

    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("Total Clusters Formed", int(n_clusters))
    with c2:
        st.metric("Outlier Partners", int(n_outliers))
    with c3:
        st.metric("VIP Partners", int(n_vip))

    # --- Export Buttons ---
    cex1, cex2, cex3 = st.columns([1, 1, 4])
    with cex1:
        cluster_pdf = export_cluster_summary_pdf(
            matrix,
            quality_report=ai.get_cluster_quality_report() if hasattr(ai, "get_cluster_quality_report") else None,
            business_report=ai.get_cluster_business_validation_report() if hasattr(ai, "get_cluster_business_validation_report") else None,
        )
        st.download_button(
            "\u2B07 Download PDF",
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
            "\u2B07 Download Excel",
            data=cluster_xls,
            file_name="Cluster_Summary.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="cluster_xlsx",
        )

    st.markdown("---")

    # ── Cluster Summary Table ────────────────────────────────────────────────
    section_header("Cluster Summary")
    cluster_summary = (
        matrix[~is_outlier]
        .groupby(["cluster_label", "cluster_type"])
        .agg(
            Partners=("cluster_label", "count"),
        )
        .reset_index()
        .sort_values("Partners", ascending=False)
    )
    # Add avg revenue column if available
    rev_col = next((c for c in ["total_revenue", "revenue", "Total Revenue"] if c in matrix.columns), None)
    if rev_col:
        rev_agg = matrix[~is_outlier].groupby("cluster_label")[rev_col].mean().rename("Avg Revenue (Rs)")
        cluster_summary = cluster_summary.merge(rev_agg, on="cluster_label", how="left")
    cs_disp = cluster_summary.copy()
    if "Partners" in cs_disp.columns:
        cs_disp["Partners"] = cs_disp["Partners"].apply(lambda v: str(int(float(v))) if v==v else "0")
    if "Avg Revenue (Rs)" in cs_disp.columns:
        cs_disp["Avg Revenue (Rs)"] = cs_disp["Avg Revenue (Rs)"].apply(
            lambda v: f"Rs {int(float(v)):,}" if v==v else "—"
        )
    for _oc in cs_disp.select_dtypes(include=["object"]).columns:
        cs_disp[_oc] = cs_disp[_oc].fillna("").astype(str)
    cs_disp = cs_disp.rename(columns={"cluster_label":"Cluster","cluster_type":"Type","Avg Revenue (Rs)":"Avg Revenue"})
    st.dataframe(cs_disp, use_container_width=True, hide_index=True)

    # Cluster Profile Cards (roadmap 3.2)
    def _cluster_recommended_action(label, cluster_type):
        label_l = label.lower()
        if "strategic accounts" in label_l: return "Expand to new categories with a curated premium bundle."
        if "category champions" in label_l:  return "Deepen share in dominant category; offer exclusive deals."
        if "core revenue drivers" in label_l: return "Protect with quarterly commitment scheme + loyalty incentive."
        if "anchor specialists" in label_l:  return "Broaden mix with 1 adjacent category recommendation."
        if "emerging power" in label_l or "rising" in label_l: return "Fast-track relationship with senior sales rep ownership."
        if "steady contributors" in label_l: return "Expand wallet share with cross-sell in under-penetrated category."
        if "win-back" in label_l:            return "Run recovery call + 14-day exclusive offer window."
        if "high-growth" in label_l:         return "Accelerate with priority fulfilment + advance order incentive."
        if "niche power" in label_l:         return "Offer category exclusivity deal to lock in spend."
        if "high-volume" in label_l:         return "Drive margin with premium-tier product recommendation."
        if "balanced growth" in label_l:     return "Increase visit frequency; position as full-range supplier."
        if "category growth specialist" in label_l: return "Cross-sell 1 complementary category to reduce concentration."
        if "mid-tier growing" in label_l:    return "Qualify for VIP threshold with a volume-based milestone reward."
        if cluster_type == "VIP":            return "Maintain relationship with quarterly strategic review."
        return "Regular follow-up and portfolio review."

    section_header("Cluster Profile Cards")

    rev_col       = next((c for c in ["total_revenue", "recent_90_revenue", "revenue"] if c in matrix.columns), None)
    order_gap_col = next((c for c in ["avg_order_gap_days", "order_gap_days", "recency_days"] if c in matrix.columns), None)
    product_col   = next((c for c in ["top_category", "top_affinity_pitch"] if c in matrix.columns), None)

    CLUSTER_ICONS = {
        "strategic accounts": "💎", "category champions": "🏆",
        "core revenue drivers": "💰", "win-back": "🔄",
        "high-growth": "🚀", "anchor": "⚓",
    }

    cluster_groups = list(matrix[~is_outlier].groupby(["cluster_label", "cluster_type"]))
    cards_per_row = 2
    for i in range(0, len(cluster_groups), cards_per_row):
        cols = st.columns(cards_per_row)
        for j, (key, grp) in enumerate(cluster_groups[i: i + cards_per_row]):
            label, ctype = key
            n_partners = len(grp)
            avg_rev    = float(grp[rev_col].mean()) if rev_col and rev_col in grp.columns else 0.0
            avg_gap    = float(grp[order_gap_col].mean()) if order_gap_col and order_gap_col in grp.columns else None
            if product_col and product_col in grp.columns:
                prods = grp[product_col].dropna().astype(str)
                prods = prods[prods.str.lower() != "n/a"]
                top_prods = ", ".join(prods.value_counts().head(2).index.tolist()) or "N/A"
            else:
                top_prods = "N/A"
            icon = next((v for k, v in CLUSTER_ICONS.items() if k in label.lower()),
                        "📋" if ctype == "VIP" else "📊")
            action  = _cluster_recommended_action(label, ctype)
            gap_txt = f"{avg_gap:.0f} days" if avg_gap is not None else "N/A"
            rev_fmt = f"Rs {int(avg_rev / 100_000):.0f}L" if avg_rev >= 100_000 else f"Rs {int(avg_rev):,}"
            with cols[j]:
                st.markdown(
                    f'<div style="background:linear-gradient(135deg,#1e1e2e,#2a2a3e);border:1px solid #3f3f5f;'
                    f'border-radius:12px;padding:18px 20px;margin-bottom:14px;">'
                    f'<div style="font-size:1.3em;margin-bottom:6px;">{icon} '
                    f'<strong style="color:#c4b5fd;">{label}</strong> '
                    f'<span style="font-size:0.75em;color:#6b7280;margin-left:6px;">{ctype}</span></div>'
                    f'<div style="display:flex;gap:20px;flex-wrap:wrap;margin:8px 0 10px;">'
                    f'<div><span style="color:#9ca3af;font-size:0.78em;">PARTNERS</span><br/>'
                    f'<strong style="color:#f9fafb;">{n_partners}</strong></div>'
                    f'<div><span style="color:#9ca3af;font-size:0.78em;">AVG 90D REVENUE</span><br/>'
                    f'<strong style="color:#34d399;">{rev_fmt}</strong></div>'
                    f'<div><span style="color:#9ca3af;font-size:0.78em;">AVG ORDER GAP</span><br/>'
                    f'<strong style="color:#f9fafb;">{gap_txt}</strong></div></div>'
                    f'<div style="font-size:0.81em;color:#d1d5db;margin-bottom:8px;">'
                    f'<span style="color:#9ca3af;">Typical products:</span> {top_prods}</div>'
                    f'<div style="background:#312e81;border-radius:8px;padding:8px 12px;'
                    f'font-size:0.81em;color:#e0e7ff;">'
                    f'🎯 <strong>Recommended action:</strong> {action}</div></div>',
                    unsafe_allow_html=True,
                )

    # ── 3D DNA Map ───────────────────────────────────────────────────────────
    section_header("Partner DNA Map (3D)")

    # Filters
    f1, f2 = st.columns([1, 2])
    with f1:
        type_options = ["All"] + sorted(matrix["cluster_type"].dropna().unique().tolist())
        selected_type = st.selectbox("Cluster Type", type_options)
    with f2:
        label_options = ["All"] + sorted(matrix["cluster_label"].dropna().unique().tolist())
        selected_label = st.selectbox("Cluster Label", label_options)

    filtered = matrix.copy()
    if selected_type != "All":
        filtered = filtered[filtered["cluster_type"] == selected_type]
    if selected_label != "All":
        filtered = filtered[filtered["cluster_label"] == selected_label]

    if filtered.empty:
        st.warning("No partners match the selected filters.")
        return

    # Build PCA input from numeric spend columns only.
    feature_df = filtered.select_dtypes(include=[np.number]).drop(
        columns=["cluster"], errors="ignore"
    )
    feature_df = feature_df.fillna(0)

    if feature_df.shape[1] == 0:
        st.warning("No numeric features available for PCA visualization.")
        return

    # PCA supports up to available dimensions. Keep 3D output shape stable.
    n_components = min(3, feature_df.shape[0], feature_df.shape[1])
    if n_components < 2:
        st.warning("Not enough data points to render cluster map.")
        return

    log_features = np.log1p(feature_df)
    pca = PCA(n_components=n_components, random_state=42)
    components = pca.fit_transform(log_features)

    plot_df = pd.DataFrame(index=filtered.index)
    plot_df["x"] = components[:, 0]
    plot_df["y"] = components[:, 1]
    plot_df["z"] = components[:, 2] if n_components >= 3 else 0.0
    plot_df["Partner"] = filtered.index
    plot_df["Cluster"] = filtered["cluster_label"].astype(str)
    plot_df["Cluster Type"] = filtered["cluster_type"].astype(str)
    plot_df["Strategic Tag"] = filtered["strategic_tag"].astype(str)
    plot_df["State"] = filtered["state"].astype(str) if "state" in filtered.columns else "Unknown"

    col_map, col_comp = st.columns([2, 1])

    with col_map:
        fig = px.scatter_3d(
            plot_df,
            x="x",
            y="y",
            z="z",
            color="Cluster",
            symbol="Cluster Type",
            hover_name="Partner",
            hover_data=["State", "Strategic Tag"],
            title="Partner DNA Map",
            color_discrete_sequence=px.colors.qualitative.Bold,
        )
        fig.update_layout(height=450, margin=dict(l=0, r=0, b=0, t=30))
        st.plotly_chart(fig, use_container_width=True)
    
    with col_comp:
        comp_df = plot_df.groupby(["Cluster", "Cluster Type"]).size().reset_index(name="Count")
        fig_comp = px.bar(
            comp_df, x="Cluster", y="Count", color="Cluster Type",
            title="Composition Breakdown",
            barmode="stack",
            color_discrete_sequence=px.colors.qualitative.Pastel
        )
        fig_comp.update_layout(height=450, margin=dict(l=0, r=0, b=0, t=40))
        st.plotly_chart(fig_comp, use_container_width=True)



