"""
Universal AI Chatbot Mixin — powered by OpenAI gpt-4o.

DATA STRATEGY:
  On the FIRST chat, _ensure_all_modules() is called ONCE to pre-load all 8 modules:
    Partner 360   → ensure_churn_forecast() + ensure_credit_risk()
    Clusters      → ensure_clustering()
    MBA           → ensure_associations()
    Product Life  → ensure_product_lifecycle()
    Inventory     → df_stock_stats (already in core)
    Competitors   → get_competitor_summary()
    Monitoring    → get_cluster_quality_report()
    Sales Rep     → ensure_sales_rep_data()

  Subsequent calls are instant — data is already in memory.
  All module data is woven into the context based on the user's question keywords.
"""

import os


class ChatbotMixin:

    _chatbot_all_loaded: bool = False

    # ── Helpers ────────────────────────────────────────────────────────
    def _sf(self, v, default=0.0):
        try:
            return float(v)
        except Exception:
            return default

    # ── One-time pre-load ALL module data ─────────────────────────────
    def _ensure_all_modules(self):
        """Load every module's computed data once so the chatbot always has full context."""
        if self._chatbot_all_loaded:
            return
        try:
            self.ensure_core_loaded()
        except Exception:
            pass
        for fn in [
            "ensure_churn_forecast",
            "ensure_credit_risk",
            "ensure_clustering",
            "ensure_associations",
            "ensure_product_lifecycle",
            "ensure_sales_rep_data",
        ]:
            try:
                getattr(self, fn, lambda: None)()
            except Exception:
                pass
        self._chatbot_all_loaded = True

    # ── Partner name fuzzy finder ──────────────────────────────────────
    def _find_partners(self, q: str) -> list:
        sources = []
        if self.df_partner_features is not None and not self.df_partner_features.empty:
            sources = list(self.df_partner_features.index.unique())
        elif self.df_ml is not None and not self.df_ml.empty and "company_name" in self.df_ml.columns:
            sources = list(self.df_ml["company_name"].unique())
        q_low = q.lower()
        exact = [p for p in sources if p.lower() in q_low]
        if exact:
            return exact[:3]
        words = [w.strip("'\".,!?") for w in q_low.split() if len(w) >= 4]
        scored = sorted([(sum(1 for w in words if w in p.lower()), p) for p in sources], key=lambda x: -x[0])
        return [p for score, p in scored if score > 0][:3]

    # ── Full partner profile (same data path as Partner 360 page) ─────
    def _get_full_partner_context(self, partner: str) -> str:
        lines = [f"PARTNER PROFILE — {partner}:"]
        report = None
        try:
            report = self.get_partner_intelligence(partner)
        except Exception:
            pass

        ALL_FIELDS = [
            ("state",                          "State",                      "text"),
            ("health_status",                  "Health Status",              "text"),
            ("health_segment",                 "Segment",                    "text"),
            ("health_score",                   "Health Score",               "score"),
            ("cluster_label",                  "Cluster",                    "text"),
            ("cluster_type",                   "Cluster Type",               "text"),
            ("lifetime_revenue",               "Lifetime Revenue",           "money"),
            ("recent_90_revenue",              "Revenue (Last 90d)",         "money"),
            ("prev_90_revenue",                "Revenue (Prev 90d)",         "money"),
            ("revenue_drop_pct",               "Revenue Drop %",             "pct"),
            ("estimated_monthly_loss",         "Est. Monthly Loss",          "money"),
            ("recency_days",                   "Days Since Last Order",      "int"),
            ("avg_order_value",                "Avg Order Value",            "money"),
            ("category_count",                 "Active Product Categories",  "int"),
            ("churn_probability",              "Churn Probability",          "pct100"),
            ("churn_risk_band",                "Churn Risk Band",            "text"),
            ("expected_revenue_at_risk_90d",   "Revenue At Risk (90d)",      "money"),
            ("expected_revenue_at_risk_monthly","Revenue At Risk / month",   "money"),
            ("forecast_next_30d",              "PROJECTED REVENUE (Next 30d)","money"),
            ("forecast_trend_pct",             "Forecast Trend %",           "pct"),
            ("forecast_confidence",            "Forecast Confidence",        "score"),
            ("credit_risk_score",              "Credit Risk Score",          "score"),
            ("credit_risk_band",               "Credit Risk Band",           "text"),
            ("credit_utilization",             "Credit Utilization",         "pct100"),
            ("overdue_ratio",                  "Overdue Ratio",              "pct100"),
            ("outstanding_amount",             "Outstanding Amount",         "money"),
            ("credit_adjusted_risk_value",     "Credit Adj. Risk Value",     "money"),
            ("top_affinity_pitch",             "Best Product to Cross-sell", "text"),
            ("pitch_confidence",               "Pitch Confidence",           "pct100"),
            ("pitch_lift",                     "Pitch Lift",                 "float2"),
        ]

        data_source = report if report else {}
        # Also merge df_partner_features if report missing fields
        try:
            pf = self.df_partner_features
            if pf is not None and not pf.empty and partner in pf.index:
                row = pf.loc[partner]
                if hasattr(row, "iloc"):
                    row = row.iloc[0]
                pf_dict = row.to_dict() if hasattr(row, "to_dict") else {}
                merged = {**pf_dict, **data_source}  # report wins on conflicts
            else:
                merged = data_source
        except Exception:
            merged = data_source

        if not merged:
            lines.append(f"  [Partner '{partner}' not found — check exact spelling]")
        else:
            for col, label, fmt in ALL_FIELDS:
                v = merged.get(col)
                if v is None:
                    continue
                try:
                    sv = str(v)
                    if sv in ("nan", "None", "", "N/A"):
                        continue
                    if fmt == "money":
                        lines.append(f"  {label}: Rs {self._sf(v):,.0f}")
                    elif fmt == "pct100":
                        lines.append(f"  {label}: {self._sf(v)*100:.1f}%")
                    elif fmt == "pct":
                        lines.append(f"  {label}: {self._sf(v):.1f}%")
                    elif fmt == "int":
                        lines.append(f"  {label}: {int(self._sf(v))}")
                    elif fmt == "score":
                        lines.append(f"  {label}: {self._sf(v):.3f}")
                    elif fmt == "float2":
                        lines.append(f"  {label}: {self._sf(v):.2f}")
                    else:
                        lines.append(f"  {label}: {v}")
                except Exception:
                    pass

        # Monthly revenue history
        try:
            mr = self.df_monthly_revenue
            if mr is not None and not mr.empty and "company_name" in mr.columns:
                import pandas as pd
                pmr = mr[mr["company_name"] == partner].copy()
                if not pmr.empty:
                    total = pmr["monthly_revenue"].sum()
                    lines.append(f"  Total Revenue (all months): Rs {total:,.0f}")
                    if "sale_month" in pmr.columns:
                        pmr["sale_month"] = pd.to_datetime(pmr["sale_month"], errors="coerce")
                        for _, mrow in pmr.sort_values("sale_month").tail(4).iterrows():
                            m = str(mrow["sale_month"])[:7]
                            lines.append(f"  Revenue {m}: Rs {mrow['monthly_revenue']:,.0f}")
        except Exception:
            pass

        # Product groups
        try:
            rgs = self.df_recent_group_spend
            if rgs is not None and not rgs.empty and "company_name" in rgs.columns:
                prgs = rgs[rgs["company_name"] == partner]
                if not prgs.empty and "group_name" in prgs.columns:
                    lines.append("  Top product groups purchased:")
                    for _, row in prgs.sort_values("total_spend", ascending=False).head(8).iterrows():
                        lines.append(f"    - {row['group_name']}: Rs {row['total_spend']:,.0f}")
        except Exception:
            pass

        return "\n".join(lines)

    # ── Main context builder ───────────────────────────────────────────
    def _build_chat_context(self, question: str) -> str:
        q = question.lower()
        sections = []

        # ── Business snapshot ──────────────────────────────────────────
        try:
            snap = []
            pf = self.df_partner_features
            mr = self.df_monthly_revenue
            if pf is not None and not pf.empty:
                snap.append(f"Total partners: {len(pf)}")
                if "churn_probability" in pf.columns:
                    snap.append(f"High churn risk partners (>65%): {int((pf['churn_probability'] > 0.65).sum())}")
                if "health_segment" in pf.columns:
                    seg = pf["health_segment"].value_counts()
                    snap.append("Health breakdown: " + ", ".join(f"{k}:{v}" for k, v in seg.items()))
                if "forecast_next_30d" in pf.columns:
                    total_fc = pf["forecast_next_30d"].sum()
                    snap.append(f"Total forecasted revenue (all partners, next 30d): Rs {total_fc:,.0f}")
            if mr is not None and not mr.empty and "monthly_revenue" in mr.columns:
                snap.append(f"Total all-time revenue: Rs {mr['monthly_revenue'].sum():,.0f}")
                if "sale_month" in mr.columns:
                    import pandas as pd
                    mr2 = mr.copy()
                    mr2["sale_month"] = pd.to_datetime(mr2["sale_month"], errors="coerce")
                    cutoff = mr2["sale_month"].max() - pd.DateOffset(months=12)
                    snap.append(f"Revenue last 12 months: Rs {mr2[mr2['sale_month'] >= cutoff]['monthly_revenue'].sum():,.0f}")
            if snap:
                sections.append("BUSINESS SNAPSHOT:\n" + "\n".join(f"  - {l}" for l in snap))
        except Exception:
            pass

        # ── MODULE 1: Partner 360 — Specific partner query ─────────────
        mentioned = self._find_partners(q)
        if mentioned:
            for partner in mentioned:
                sections.append(self._get_full_partner_context(partner))

        # ── MODULE 1+3: Partner list / top partners ────────────────────
        if any(w in q for w in ["partner", "customer", "company", "account", "dealer", "top", "list", "all"]):
            try:
                mr = self.df_monthly_revenue
                pf = self.df_partner_features
                if mr is not None and not mr.empty and "company_name" in mr.columns:
                    top = mr.groupby("company_name")["monthly_revenue"].sum().sort_values(ascending=False).head(20)
                    lines = [f"  {i+1}. {n}: Rs {r:,.0f}" for i, (n, r) in enumerate(top.items())]
                    sections.append("TOP 20 PARTNERS BY TOTAL REVENUE:\n" + "\n".join(lines))
                if pf is not None and not pf.empty and "state" in pf.columns:
                    by_state = pf.groupby("state").size().sort_values(ascending=False)
                    sections.append("PARTNERS BY STATE:\n" + "\n".join(f"  {s}: {c}" for s, c in by_state.items()))
            except Exception:
                pass

        # ── MODULE 1: Churn risk ───────────────────────────────────────
        if any(w in q for w in ["churn", "at risk", "losing", "retention", "leaving", "risk"]):
            try:
                pf = self.df_partner_features
                if pf is not None and not pf.empty and "churn_probability" in pf.columns:
                    top_churn = pf["churn_probability"].sort_values(ascending=False).head(25)
                    lines = [f"  {i+1}. {n}: {v*100:.1f}%" for i, (n, v) in enumerate(top_churn.items())]
                    sections.append("TOP 25 HIGH CHURN RISK PARTNERS:\n" + "\n".join(lines))
                    if "estimated_monthly_loss" in pf.columns:
                        sections.append(f"TOTAL EST. MONTHLY REVENUE AT RISK:\n  Rs {pf['estimated_monthly_loss'].sum():,.0f}/month")
                    if "expected_revenue_at_risk_90d" in pf.columns:
                        top_rar = pf["expected_revenue_at_risk_90d"].sort_values(ascending=False).head(10)
                        lines2 = [f"  {i+1}. {n}: Rs {r:,.0f}" for i, (n, r) in enumerate(top_rar.items())]
                        sections.append("TOP 10 BY REVENUE AT RISK (90D):\n" + "\n".join(lines2))
            except Exception:
                pass

        # ── MODULE 1: Revenue & Forecast ──────────────────────────────
        if any(w in q for w in ["revenue", "sales", "monthly", "trend", "annual", "year", "growth", "forecast", "project", "predict"]):
            try:
                import pandas as pd
                mr = self.df_monthly_revenue
                if mr is not None and not mr.empty and "sale_month" in mr.columns:
                    mr2 = mr.copy()
                    mr2["sale_month"] = pd.to_datetime(mr2["sale_month"], errors="coerce")
                    monthly = mr2.groupby("sale_month")["monthly_revenue"].sum().sort_index().tail(18)
                    lines = [f"  {str(m)[:7]}: Rs {r:,.0f}" for m, r in monthly.items()]
                    sections.append("MONTHLY TOTAL REVENUE (LAST 18 MONTHS):\n" + "\n".join(lines))
                    recent_cut = mr2["sale_month"].max() - pd.DateOffset(months=3)
                    rec = mr2[mr2["sale_month"] >= recent_cut]
                    if not rec.empty:
                        top_r = rec.groupby("company_name")["monthly_revenue"].sum().sort_values(ascending=False).head(10)
                        sections.append("TOP 10 PARTNERS LAST 3 MONTHS:\n" + "\n".join(
                            f"  {i+1}. {n}: Rs {r:,.0f}" for i, (n, r) in enumerate(top_r.items())))
            except Exception:
                pass
            try:
                pf = self.df_partner_features
                if pf is not None and not pf.empty and "forecast_next_30d" in pf.columns:
                    top_fc = pf["forecast_next_30d"].sort_values(ascending=False).head(15)
                    lines = [f"  {i+1}. {n}: Rs {r:,.0f}" for i, (n, r) in enumerate(top_fc.items())]
                    sections.append("PROJECTED REVENUE — TOP 15 PARTNERS (NEXT 30 DAYS):\n" + "\n".join(lines))
                    sections.append(f"TOTAL PROJECTED REVENUE ALL PARTNERS (NEXT 30D): Rs {pf['forecast_next_30d'].sum():,.0f}")
            except Exception:
                pass

        # ── MODULE 1: Credit risk ─────────────────────────────────────
        if any(w in q for w in ["credit", "payment", "overdue", "outstanding", "due", "debt"]):
            try:
                pf = self.df_partner_features
                if pf is not None and not pf.empty and "credit_risk_band" in pf.columns:
                    high = pf[pf["credit_risk_band"] == "High"]
                    if not high.empty:
                        lines = []
                        for i, (name, row) in enumerate(high.head(15).iterrows()):
                            amt = self._sf(row.get("outstanding_amount", 0))
                            lines.append(f"  {i+1}. {name}: Outstanding Rs {amt:,.0f}, Overdue {self._sf(row.get('overdue_ratio',0))*100:.0f}%")
                        sections.append(f"HIGH CREDIT RISK PARTNERS ({len(high)} total):\n" + "\n".join(lines))
            except Exception:
                pass

        # ── MODULE 1: Health / degrowth ────────────────────────────────
        if any(w in q for w in ["degrowth", "declining", "health", "unhealthy", "critical", "stable", "champion", "vip"]):
            try:
                pf = self.df_partner_features
                if pf is not None and not pf.empty and "health_segment" in pf.columns:
                    for seg in ["Critical", "At Risk", "Healthy", "Champion"]:
                        grp = pf[pf["health_segment"] == seg]
                        if grp.empty:
                            continue
                        rev_c = next((c for c in ["lifetime_revenue", "recent_90_revenue"] if c in grp.columns), None)
                        lines = []
                        for i, n in enumerate(list(grp.index[:15])):
                            line = f"  {i+1}. {n}"
                            if rev_c:
                                try:
                                    line += f": Rs {grp.loc[n, rev_c]:,.0f}"
                                except Exception:
                                    pass
                            lines.append(line)
                        sections.append(f"{seg.upper()} PARTNERS ({len(grp)} total):\n" + "\n".join(lines))
            except Exception:
                pass

        # ── MODULE 2: Market Basket / Product Bundles ─────────────────
        if any(w in q for w in ["bundle", "associat", "cross", "pitch", "together", "basket", "often", "combo"]):
            try:
                rules = self.get_associations(limit=20)
                if rules is not None and not rules.empty:
                    lines = []
                    for _, row in rules.head(15).iterrows():
                        a = row.get("product_a", "?")
                        b = row.get("product_b", "?")
                        lift = row.get("lift_a_to_b", row.get("lift", 0))
                        conf = row.get("confidence_a_to_b", row.get("confidence", 0))
                        times = row.get("times_bought_together", "")
                        lines.append(f"  - {a} → {b} | lift:{lift:.2f}, conf:{conf:.0%}" +
                                     (f", bought {int(times)}x" if times else ""))
                    sections.append("TOP PRODUCT BUNDLE RULES:\n" + "\n".join(lines))
            except Exception:
                pass

        # ── MODULE 3: Cluster Intelligence ────────────────────────────
        if any(w in q for w in ["cluster", "segment", "tier", "group of partner", "cluster partner"]):
            try:
                matrix = getattr(self, "matrix", None)
                if matrix is not None and not matrix.empty and "cluster_label" in matrix.columns:
                    summary = matrix.groupby(["cluster_label", "cluster_type"] if "cluster_type" in matrix.columns else ["cluster_label"]).size()
                    lines = [f"  {'/'.join(str(x) for x in (label if isinstance(label, tuple) else [label]))}: {cnt} partners"
                             for label, cnt in summary.sort_values(ascending=False).items()]
                    sections.append("CLUSTER SUMMARY (ALL CLUSTERS):\n" + "\n".join(lines))
                    if "cluster_type" in matrix.columns:
                        n_vip = (matrix["cluster_type"] == "VIP").sum()
                        sections.append(f"  VIP partners count: {int(n_vip)}")
                    quality = None
                    try:
                        quality = self.get_cluster_quality_report()
                    except Exception:
                        pass
                    if quality and isinstance(quality, dict):
                        sil = quality.get("silhouette_score", quality.get("silhouette", None))
                        if sil is not None:
                            sections.append(f"  Cluster quality silhouette score: {sil:.3f}")
            except Exception:
                pass

        # ── MODULE 4: Inventory / Dead Stock ──────────────────────────
        if any(w in q for w in ["inventory", "stock", "dead", "liquid", "ageing", "old", "slow", "unsold"]):
            try:
                ds = self.df_stock_stats
                if ds is not None and not ds.empty:
                    block = f"INVENTORY / DEAD STOCK:\n  Total SKUs tracked: {len(ds)}"
                    if "max_age_days" in ds.columns and "product_name" in ds.columns:
                        oldest = ds.nlargest(20, "max_age_days")
                        qty_c = "total_stock_qty" if "total_stock_qty" in ds.columns else None
                        lines = []
                        for _, row in oldest.iterrows():
                            line = f"  - {row['product_name']}: {int(row['max_age_days'])} days old"
                            if qty_c:
                                line += f", qty: {int(row[qty_c])}"
                            lines.append(line)
                        block += "\nOLDEST / DEAD STOCK:\n" + "\n".join(lines)
                    sections.append(block)
            except Exception:
                pass
            try:
                dead = self.get_dead_stock()
                if dead is not None and not dead.empty and "dead_stock_item" in dead.columns:
                    items = dead["dead_stock_item"].unique()
                    sections.append(f"DEAD STOCK ITEMS ({len(items)} unique): " + ", ".join(list(items)[:10]))
            except Exception:
                pass

        # ── MODULE 5: Product Lifecycle ───────────────────────────────
        if any(w in q for w in ["lifecycle", "product lifecycle", "growing product", "declining product",
                                  "end of life", "eol", "cannibal", "velocity", "product growth", "product trend"]):
            try:
                vel = self.get_velocity_data()
                if vel is not None and not vel.empty:
                    if "lifecycle_stage" in vel.columns and "product_name" in vel.columns:
                        stars = vel[vel["lifecycle_stage"] == "Star"].head(10)
                        decline = vel[vel["lifecycle_stage"] == "Declining"].head(10)
                        if not stars.empty:
                            lines = [f"  - {row['product_name']}: score {self._sf(row.get('velocity_score',0)):.2f}"
                                     for _, row in stars.iterrows()]
                            sections.append("FAST-GROWING PRODUCTS (STAR STAGE):\n" + "\n".join(lines))
                        if not decline.empty:
                            lines = [f"  - {row['product_name']}: score {self._sf(row.get('velocity_score',0)):.2f}"
                                     for _, row in decline.iterrows()]
                            sections.append("DECLINING PRODUCTS:\n" + "\n".join(lines))
            except Exception:
                pass
            try:
                eol = self.get_eol_predictions()
                if eol is not None and not eol.empty:
                    lines = []
                    for _, row in eol.head(10).iterrows():
                        pn = row.get("product_name", "?")
                        m = row.get("eol_months", "?")
                        urg = row.get("urgency", "")
                        lines.append(f"  - {pn}: ~{m} months to EOL [{urg}]")
                    sections.append("PRODUCTS APPROACHING END OF LIFE:\n" + "\n".join(lines))
            except Exception:
                pass
            try:
                cannibal = self.get_cannibalization_data()
                if cannibal is not None and not cannibal.empty:
                    lines = []
                    for _, row in cannibal.head(8).iterrows():
                        gp = row.get("growing_product", "?")
                        dp = row.get("declining_product", "?")
                        lines.append(f"  - {gp} is replacing {dp}")
                    sections.append("PRODUCT CANNIBALIZATION DETECTED:\n" + "\n".join(lines))
            except Exception:
                pass

        # ── MODULE 6: Recommendations ─────────────────────────────────
        if any(w in q for w in ["recommend", "action", "next best", "what should", "pitch", "suggest"]):
            try:
                pf = self.df_partner_features
                if pf is not None and not pf.empty and "top_affinity_pitch" in pf.columns:
                    pitches = pf[pf["top_affinity_pitch"].notna() & (pf["top_affinity_pitch"] != "N/A")]
                    if not pitches.empty:
                        lines = [f"  - {name}: pitch '{row.get('top_affinity_pitch','?')}' (conf: {self._sf(row.get('pitch_confidence',0))*100:.0f}%)"
                                 for name, row in pitches.head(10).iterrows()]
                        sections.append("TOP CROSS-SELL PITCHES (from MBA):\n" + "\n".join(lines))
            except Exception:
                pass

        # Competitor intelligence removed

        # ── MODULE 8: Model Monitoring ─────────────────────────────────
        if any(w in q for w in ["model", "accuracy", "auc", "monitor", "drift", "quality", "train", "performance"]):
            try:
                report = self.get_churn_model_report() if hasattr(self, "get_churn_model_report") else None
                if report and isinstance(report, dict):
                    auc = report.get("roc_auc", report.get("auc", None))
                    pr_auc = report.get("pr_auc", report.get("avg_precision", None))
                    lines = []
                    if auc:
                        lines.append(f"  Churn Model ROC-AUC: {self._sf(auc):.3f}")
                    if pr_auc:
                        lines.append(f"  Churn Model PR-AUC: {self._sf(pr_auc):.3f}")
                    n_feats = report.get("n_features", None)
                    if n_feats:
                        lines.append(f"  Features used: {n_feats}")
                    if lines:
                        sections.append("MODEL MONITORING:\n" + "\n".join(lines))
            except Exception:
                pass

        # ── MODULE 9: Sales Rep Performance ────────────────────────────
        if any(w in q for w in ["rep", "salesman", "sales person", "performance", "tour", "expense", "issue", "leaderboard", "roi", "cost per order"]):
            try:
                df_rep = getattr(self, "df_sales_rep", None)
                if df_rep is not None and not df_rep.empty:
                    lines = []
                    for _, row in df_rep.head(15).iterrows():
                        name = row.get("sales_rep_name", "?")
                        orders = row.get("total_orders", 0)
                        exp = row.get("total_expenses", 0)
                        issues = row.get("issues_logged", 0)
                        cost = row.get("expense_per_order", 0)
                        lines.append(f"  - {name}: {int(orders)} orders, Rs {self._sf(exp):,.0f} expenses, Cost/Order: Rs {self._sf(cost):,.0f}, {int(issues)} issues logged")
                    sections.append("SALES REP LEADERBOARD (Top by Orders):\n" + "\n".join(lines))
            except Exception:
                pass

        # ── Product group revenue (for product-level questions) ────────
        if any(w in q for w in ["product", "group", "categor", "item", "what do we sell"]):
            try:
                rgs = self.df_recent_group_spend
                if rgs is not None and not rgs.empty and "group_name" in rgs.columns:
                    top_groups = rgs.groupby("group_name")["total_spend"].sum().sort_values(ascending=False)
                    lines = [f"  {i+1}. {n}: Rs {r:,.0f}" for i, (n, r) in enumerate(top_groups.items())]
                    sections.append("PRODUCT GROUPS BY TOTAL REVENUE:\n" + "\n".join(lines))

                    q_words = [w.strip("'\".,!?") for w in q.split() if len(w) >= 3]
                    matched = [g for g in top_groups.index if any(w in g.lower() for w in q_words)][:2]
                    for mg in matched:
                        buyers = rgs[rgs["group_name"] == mg].sort_values("total_spend", ascending=False).head(15)
                        if not buyers.empty:
                            blines = [f"  {i+1}. {row['company_name']}: Rs {row['total_spend']:,.0f}"
                                      for i, (_, row) in enumerate(buyers.iterrows())]
                            sections.append(f"TOP BUYERS OF '{mg}':\n" + "\n".join(blines))
            except Exception:
                pass

        # ── Fallback: top partners if context is thin ──────────────────
        if len(sections) <= 1 and not mentioned:
            try:
                mr = self.df_monthly_revenue
                pf = self.df_partner_features
                if mr is not None and not mr.empty and "company_name" in mr.columns:
                    top = mr.groupby("company_name")["monthly_revenue"].sum().sort_values(ascending=False).head(10)
                    sections.append("TOP 10 PARTNERS BY REVENUE:\n" +
                                    "\n".join(f"  {i+1}. {n}: Rs {r:,.0f}" for i, (n, r) in enumerate(top.items())))
                elif pf is not None and not pf.empty and "lifetime_revenue" in pf.columns:
                    top = pf["lifetime_revenue"].sort_values(ascending=False).head(10)
                    sections.append("TOP 10 PARTNERS BY LIFETIME REVENUE:\n" +
                                    "\n".join(f"  {i+1}. {n}: Rs {r:,.0f}" for i, (n, r) in enumerate(top.items())))
            except Exception:
                pass

        if not sections:
            return "Data is loading. Please try again in a moment."
        return "\n\n".join(sections)

    # ── OpenAI gpt-4o call ─────────────────────────────────────────────
    def chat_with_ai(self, question: str, history: list | None = None) -> str:
        # Pre-load all modules on first call
        self._ensure_all_modules()

        api_key = getattr(self, "openai_api_key", None) or os.getenv("OPENAI_API_KEY", "")
        if not api_key:
            return "⚠️ No OpenAI API key. Add `OPENAI_API_KEY=sk-...` to your `.env` file and restart."
        try:
            from openai import OpenAI
        except ImportError:
            return "⚠️ `openai` package not installed. Run: `pip install openai`"

        model = getattr(self, "openai_model", None) or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        context = self._build_chat_context(question)

        system_prompt = f"""You are a senior business intelligence assistant for CONSISTENT — a B2B distributor of lubricants, paints, greases, construction chemicals, and industrial products across India.

You have DIRECT ACCESS to live production data from all 7 modules of the application, queried moments ago:
  Module 1: Partner 360         — individual partner health, churn, credit, forecasts
  Module 2: Market Basket       — product bundle/cross-sell rules
  Module 3: Clusters            — partner segments (VIP, Growth, Standard, At Risk)
  Module 4: Inventory           — dead stock items and liquidation leads
  Module 5: Product Lifecycle   — product growth velocity, EOL predictions, cannibalization
  Module 6: Recommendations     — best actions and pitches per partner
  Module 7: Sales Rep           — rep performance, tours, expenses, partner issues logged
  Revenue Pipeline Tracker      — partner health segmented across Champion/Healthy/At Risk/Critical

═══ STRICT RULES ═══
1. ONLY use data provided below. NEVER invent names, numbers, or figures.
2. "PROJECTED REVENUE (Next 30d)" in a partner profile = their forecast. Quote it directly.
3. Churn probability is a decimal — multiply by 100 for percentage display.
4. Format currency as Rs X,XX,XXX (Indian number format).
5. If a partner is not found: "I couldn't find [name] — please check exact spelling."
6. Answer directly in simple business language. No "I can see in the data..."
7. Keep responses under 300 words. Lead with the most important number.

═══ LIVE DATA FROM ALL 9 MODULES ═══
{context}
"""

        messages = [{"role": "system", "content": system_prompt}]
        if history:
            messages.extend(history[-8:])
        messages.append({"role": "user", "content": question})

        try:
            client = OpenAI(api_key=api_key)
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.05,
                max_tokens=600,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            return f"❌ OpenAI API error: {e}"

    def get_quick_insights(self) -> list[str]:
        return [
            "What is the projected revenue for our top partners?",
            "Who are the top performing sales reps?",
            "Show me all dead stock items",
            "Which products are growing and which are declining?",
        ]
