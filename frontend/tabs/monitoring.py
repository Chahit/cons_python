import streamlit as st
import pandas as pd
import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from styles import apply_global_styles, section_header, banner, page_caption, page_header, skeleton_loader


def render(ai):
    apply_global_styles()
    page_header(
        title="AI Churn Engine",
        subtitle="Manage predictions, model performance, and data quality diagnostics.",
        icon="🧠",
        accent_color="#06b6d4",
        badge_text="Live",
        badge_color="#064e3b",
    )
    skel = st.empty()
    with skel.container():
        skeleton_loader(n_metric_cards=4, n_rows=2, label="Loading diagnostics...")
    ai.ensure_clustering()
    if ai.enable_realtime_partner_scoring:
        ai.ensure_churn_forecast()
        ai.ensure_credit_risk()
    ai.ensure_associations()
    skel.empty()

    snapshot = ai.get_monitoring_snapshot()
    dq = ai.get_data_quality_report()

    # ── System Health Banner ────────────────────────────────────────────
    issues = []
    if dq and dq.get("missing_critical_columns"):
        issues.append(f"Missing columns: {dq['missing_critical_columns']}")
    if dq and dq.get("has_nulls_in_critical"):
        issues.append("Nulls detected in critical fields")
    if issues:
        banner("⚠️ System issues detected: " + " | ".join(issues), "amber")
    else:
        banner("✅ All systems operational — no data quality issues detected.", "green")

    section_header("Performance & Cache")
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.metric("Fast Mode", "ON" if ai.fast_mode else "OFF")
    with m2:
        st.metric("Strict View Only", "ON" if ai.strict_view_only else "OFF")
    with m3:
        st.metric("Realtime Scoring", "ON" if ai.enable_realtime_partner_scoring else "OFF")
    with m4:
        st.metric("Core Cache TTL", f"{int(ai.core_cache_ttl_sec)}s")

    timings = dict(ai.step_timings) if ai.step_timings else {}
    if timings:
        tdf = (
            pd.DataFrame(
                [{"Step": k, "Seconds": float(v)} for k, v in timings.items()]
            )
            .sort_values("Seconds", ascending=False)
            .reset_index(drop=True)
        )
        tdf["Seconds"] = tdf["Seconds"].apply(lambda v: f"{float(v):.3f}")
        st.dataframe(tdf.rename(columns={"Seconds":"Latency (s)"}), use_container_width=True, hide_index=True)
    else:
        st.info("No timing data captured yet.")

    section_header("Realtime Queue")
    status = ai.get_realtime_status()
    q1, q2, q3, q4 = st.columns(4)
    with q1:
        st.metric("Pending Jobs", int(status.get("pending_jobs", 0) or 0))
    with q2:
        st.metric("Running Jobs", int(status.get("running_jobs", 0) or 0))
    with q3:
        st.metric("Failed Jobs", int(status.get("failed_jobs", 0) or 0))
    with q4:
        st.metric("Scored Partners", int(status.get("scored_partners", 0) or 0))
    st.caption(f"Last live update: {status.get('last_live_update', 'N/A')}")

    r1, r2 = st.columns(2)
    with r1:
        if st.button("Run All Predictions"):
            n = ai.queue_recompute_all(reason="manual_all_predictions")
            st.success(f"Queued {int(n)} partner predictions.")
    with r2:
        selected_partner = None
        if ai.matrix is not None and not ai.matrix.empty:
            selected_partner = st.selectbox(
                "Queue Single Partner",
                ["(none)"] + sorted(ai.matrix.index.tolist()),
                key="queue_partner_select",
            )
        if st.button("Queue Selected Partner"):
            if selected_partner and selected_partner != "(none)":
                jid = ai.queue_recompute_job(
                    partner_name=selected_partner, reason="manual_single"
                )
                st.success(f"Queued job #{jid} for {selected_partner}.")
            else:
                st.warning("Select a partner first.")

    st.markdown("---")
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    with c1:
        st.metric("Partners", int(snapshot.get("partner_count", 0)))
    with c2:
        st.metric("Clusters", int(snapshot.get("cluster_count", 0)))
    with c3:
        st.metric("Outliers", int(snapshot.get("outlier_count", 0)))
    with c4:
        avg_health = snapshot.get("avg_health_score", None)
        st.metric("Avg Health Score", f"{avg_health:.3f}" if avg_health is not None else "N/A")
    with c5:
        avg_churn = snapshot.get("avg_churn_probability", None)
        st.metric(
            "Avg Churn Probability",
            f"{float(avg_churn) * 100:.1f}%" if avg_churn is not None else "N/A",
        )
    with c6:
        avg_credit = snapshot.get("avg_credit_risk_score", None)
        st.metric(
            "Avg Credit Risk",
            f"{float(avg_credit) * 100:.1f}%" if avg_credit is not None else "N/A",
        )

    st.markdown("---")
    st.subheader("Operational Alerts")
    alert_snapshot = ai.get_alert_snapshot(limit=100)
    if not alert_snapshot or alert_snapshot.get("status") != "ok":
        st.info("Alert snapshot not available.")
    else:
        summary = alert_snapshot.get("summary", {})
        a1, a2, a3, a4 = st.columns(4)
        with a1:
            st.metric("Partners With Alerts", int(summary.get("partners_with_alerts", 0)))
        with a2:
            st.metric("Sharp Revenue Drop", int(summary.get("sharp_revenue_drop_count", 0)))
        with a3:
            st.metric("High Churn Jump", int(summary.get("high_churn_jump_count", 0)))
        with a4:
            st.metric("High Credit Jump", int(summary.get("high_credit_risk_jump_count", 0)))

        rows = alert_snapshot.get("rows", []) or []
        if rows:
            alert_df = pd.DataFrame(rows)
            for _col, _fn in [
                ("revenue_drop_pct",  lambda v: f"{float(v):.1f}"),
                ("churn_probability", lambda v: f"{float(v):.3f}"),
                ("churn_delta",       lambda v: f"{float(v):.3f}"),
                ("credit_risk_score", lambda v: f"{float(v):.3f}"),
                ("credit_delta",      lambda v: f"{float(v):.3f}"),
                ("active_alerts",     lambda v: str(int(float(v)))),
            ]:
                if _col in alert_df.columns:
                    alert_df[_col] = alert_df[_col].apply(lambda v, f=_fn: f(v) if v==v else "—")
            for _oc in alert_df.select_dtypes(include=["object"]).columns:
                alert_df[_oc] = alert_df[_oc].fillna("").astype(str)
            alert_df = alert_df.rename(columns={
                "company_name":"Partner","triggered_rules":"Triggered Rules",
                "revenue_drop_pct":"Revenue Drop %","churn_probability":"Churn",
                "churn_delta":"Churn Delta","credit_risk_score":"Credit Risk",
                "credit_delta":"Credit Delta","active_alerts":"Active Alerts",
            })
            st.dataframe(alert_df, use_container_width=True, hide_index=True)
        else:
            st.success("No alert rules triggered in current snapshot.")

    st.markdown("---")
    st.subheader("Cluster Quality")
    cq = ai.get_cluster_quality_report()
    if not cq or cq.get("status") != "ok":
        st.info("Cluster quality report not available yet.")
    else:
        z1, z2, z3, z4 = st.columns(4)
        with z1:
            st.metric("Outlier Ratio", f"{float(cq.get('outlier_ratio', 0)) * 100:.1f}%")
        with z2:
            ce = cq.get("cluster_entropy", None)
            st.metric("Cluster Entropy", f"{float(ce):.3f}" if ce is not None else "N/A")
        with z3:
            st.metric("Largest Cluster", int(cq.get("largest_cluster_size", 0)))
        with z4:
            st.metric("Smallest Cluster", int(cq.get("smallest_cluster_size", 0)))

        vip = cq.get("vip_summary", {})
        gr = cq.get("growth_summary", {})
        r1, r2 = st.columns(2)
        with r1:
            st.caption("VIP (KMeans)")
            st.write(
                {
                    "n_partners": vip.get("n_partners"),
                    "chosen_k": vip.get("chosen_k"),
                    "silhouette": vip.get("silhouette"),
                    "calinski_harabasz": vip.get("calinski_harabasz"),
                    "stability_ari": vip.get("stability_ari"),
                    "k_candidates": vip.get("k_candidates"),
                }
            )
        with r2:
            st.caption("Growth (HDBSCAN)")
            st.write(
                {
                    "n_partners": gr.get("n_partners"),
                    "min_cluster_size": gr.get("min_cluster_size"),
                    "min_samples": gr.get("min_samples"),
                    "outlier_ratio": gr.get("outlier_ratio"),
                    "silhouette": gr.get("silhouette"),
                    "calinski_harabasz": gr.get("calinski_harabasz"),
                    "stability_ari": gr.get("stability_ari"),
                    "param_candidates": gr.get("param_candidates"),
                }
            )
        tiering = cq.get("tiering", {})
        if tiering:
            st.caption("Tiering Split")
            st.write(tiering)
        gate = cq.get("quality_gate", {})
        st.caption("Quality Gate and Fallback")
        st.write(
            {
                "approved": gate.get("approved"),
                "reason": gate.get("reason"),
                "fallback_applied": cq.get("fallback_applied", False),
                "fallback_reason": cq.get("fallback_reason"),
            }
        )
        fr = cq.get("feature_report", {})
        fq = fr.get("quality", {}) if isinstance(fr, dict) else {}
        fd = fr.get("drift", {}) if isinstance(fr, dict) else {}
        st.caption("Feature Quality and Drift")
        st.write(
            {
                "null_ratio_max": fq.get("null_ratio_max"),
                "zero_var_dropped_count": fq.get("zero_var_dropped_count"),
                "mix_sum_mae": fq.get("mix_sum_mae"),
                "feature_count_after_prune": fq.get("feature_count_after_prune"),
                "drift_status": fd.get("status"),
                "mean_abs_z_shift": fd.get("mean_abs_z_shift"),
            }
        )

    st.markdown("---")
    st.subheader("Cluster Business Validation")
    bv = ai.get_cluster_business_validation_report()
    if not bv or bv.get("status") != "ok":
        st.info("Business validation report not available yet.")
    else:
        comp = bv.get("comparison", {})
        c_guided = comp.get("cluster_guided", {})
        c_rev = comp.get("top_revenue_baseline", {})
        c_rand = comp.get("random_baseline", {})

        y1, y2, y3 = st.columns(3)
        with y1:
            st.caption("Cluster-Guided")
            st.write(c_guided)
        with y2:
            st.caption("Top-Revenue Baseline")
            st.write(c_rev)
        with y3:
            st.caption("Random Baseline")
            st.write(c_rand)

        kpis = bv.get("cluster_kpis", [])
        if kpis:
            _rs = lambda v: f"Rs {int(float(v)):,}" if pd.notnull(v) else "Rs 0"
            kpi_df = pd.DataFrame(kpis)
            for _mc in ["avg_recent_90_revenue", "total_est_monthly_loss"]:
                if _mc in kpi_df.columns:
                    kpi_df[_mc] = kpi_df[_mc].apply(_rs)
            kpi_disp = kpi_df.copy()
            for _col, _fn in [
                ("partners",            lambda v: str(int(float(v)))),
                ("degrowth_rate",       lambda v: f"{float(v):.2f}"),
                ("avg_growth_rate_90d", lambda v: f"{float(v):.3f}"),
                ("avg_churn_probability", lambda v: f"{float(v):.4f}"),
                ("avg_credit_risk_score", lambda v: f"{float(v):.4f}"),
            ]:
                if _col in kpi_disp.columns:
                    kpi_disp[_col] = kpi_disp[_col].apply(lambda v, f=_fn: f(v) if v==v else "—")
            for _oc in kpi_disp.select_dtypes(include=["object"]).columns:
                kpi_disp[_oc] = kpi_disp[_oc].fillna("").astype(str)
            kpi_disp = kpi_disp.rename(columns={
                "cluster_label":"Cluster","partners":"Partners","degrowth_rate":"Degrowth %",
                "avg_recent_90_revenue":"Avg Rev 90d","avg_growth_rate_90d":"Avg Growth 90d",
                "avg_churn_probability":"Avg Churn","avg_credit_risk_score":"Avg Credit",
                "total_est_monthly_loss":"Total Est Monthly Loss",
            })
            st.dataframe(kpi_disp, use_container_width=True, hide_index=True)

    st.markdown("---")
    st.subheader("Data Quality")
    st.write(f"Status: **{dq.get('status', 'unknown').upper()}**")
    st.write(f"Rows: {dq.get('rows', 0):,}")

    warnings = dq.get("warnings", [])
    errors = dq.get("errors", [])
    if errors:
        for err in errors:
            st.error(err)
    if warnings:
        for warn in warnings:
            st.warning(warn)
    if not errors and not warnings:
        st.success("No data quality issues detected in current load.")

    st.markdown("---")
    st.subheader("Churn Model")
    churn = ai.get_churn_model_report()
    if not churn:
        st.info("Churn model report not available.")
    elif churn.get("status") != "ok":
        st.warning(churn.get("reason", "Churn model not trained."))
    else:
        h1, h2, h3, h4 = st.columns(4)
        with h1:
            st.metric("Train Samples", int(churn.get("train_samples", 0)))
        with h2:
            st.metric("Valid Samples", int(churn.get("valid_samples", 0)))
        with h3:
            st.metric("ROC AUC", f"{float(churn.get('roc_auc', 0)):.3f}")
        with h4:
            st.metric("Avg Precision", f"{float(churn.get('avg_precision', 0)):.3f}")

    st.markdown("---")
    st.subheader("Credit Risk Model")
    credit = ai.get_credit_risk_report()
    if not credit:
        st.info("Credit risk report not available.")
    elif credit.get("status") != "ok":
        st.warning(credit.get("reason", "Credit risk model unavailable."))
    else:
        q1, q2, q3 = st.columns(3)
        with q1:
            st.metric("Covered Partners", int(credit.get("covered_partners", 0)))
        with q2:
            st.metric("High Credit Risk", int(credit.get("high_risk_partners", 0)))
        with q3:
            st.metric(
                "Avg Credit Score",
                f"{float(credit.get('avg_credit_risk_score', 0)) * 100:.1f}%",
            )

    st.markdown("---")
    st.subheader("Association Rule Reliability")
    if ai.df_assoc_rules is None or ai.df_assoc_rules.empty:
        st.info("Association rules not loaded.")
    else:
        rules = ai.df_assoc_rules.copy()
        total_rules = len(rules)
        low_support = 0
        if "support_a" in rules.columns and "support_b" in rules.columns:
            low_support = int(((rules["support_a"] < ai.default_min_support) | (rules["support_b"] < ai.default_min_support)).sum())
        high_strength = 0
        if "confidence_a_to_b" in rules.columns and "lift_a_to_b" in rules.columns:
            high_strength = int(((rules["confidence_a_to_b"] >= 0.4) & (rules["lift_a_to_b"] >= 1.5)).sum())

        r1, r2, r3 = st.columns(3)
        with r1:
            st.metric("Total Rules", int(total_rules))
        with r2:
            st.metric("Low Support Rules", int(low_support))
        with r3:
            st.metric("High Strength Rules", int(high_strength))

    st.markdown("---")
    st.subheader("Degrowth Backtest")
    b1, b2 = st.columns([1, 1])
    with b1:
        months = st.slider("History Window (months)", 3, 18, 9, 1)
    with b2:
        threshold = st.slider("Drop Threshold (%)", 5, 50, 20, 1)

    if st.button("Run Backtest"):
        result = ai.run_degrowth_backtest(months=months, min_drop_pct=threshold)
        st.session_state["degrowth_backtest_result"] = result

    result = st.session_state.get("degrowth_backtest_result", ai.get_backtest_report())
    if result:
        if result.get("status") != "ok":
            st.warning(result.get("reason", "Backtest unavailable."))
        else:
            k1, k2, k3, k4 = st.columns(4)
            with k1:
                st.metric("Samples", int(result.get("samples", 0)))
            with k2:
                st.metric("Precision", f"{float(result.get('precision', 0)):.3f}")
            with k3:
                st.metric("Recall", f"{float(result.get('recall', 0)):.3f}")
            with k4:
                st.metric("Threshold", f"{float(result.get('threshold_drop_pct', 0)):.1f}%")

            st.caption(
                f"TP: {result.get('tp', 0)} | FP: {result.get('fp', 0)} | FN: {result.get('fn', 0)}"
            )
