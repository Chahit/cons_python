import time
import numpy as np
import pandas as pd
from .schemas import DataQualityReport

class BaseLoaderMixin:
    @staticmethod
    def _approved_condition(alias="t"):
        # Works whether source column is text ('True') or boolean.
        return f"LOWER(CAST({alias}.is_approved AS TEXT)) = 'true'"

    @staticmethod
    def _is_stale(loaded_at, ttl_seconds):
        if loaded_at is None:
            return True
        return (time.time() - float(loaded_at)) > float(ttl_seconds)

    def _timed_step(self, label, fn):
        started = time.perf_counter()
        result = fn()
        elapsed = time.perf_counter() - started
        self.step_timings[label] = round(float(elapsed), 3)
        print(f"[timing] {label}: {elapsed:.2f}s")
        return result

    def ensure_core_loaded(self):
        if self._core_loaded and not self._is_stale(
            self._core_loaded_at, self.core_cache_ttl_sec
        ):
            return
        self._clustering_ready = False
        self._churn_ready = False
        self._credit_ready = False
        self._associations_ready = False

        self.df_ml = self._timed_step(
            "load.view_ml_input",
            self.repo.fetch_view_ml_input,
        )
        self.data_quality_report = self._run_data_quality_checks(self.df_ml)
        self.df_fact = self._timed_step(
            "load.fact_sales_intelligence",
            self.repo.fetch_fact_sales_intelligence,
        )
        try:
            self.df_stock_stats = self._timed_step(
                "load.view_ageing_stock",
                self.repo.fetch_view_ageing_stock,
            )
        except Exception:
            # Fallback if view fails or is empty
            self.df_stock_stats = pd.DataFrame(
                columns=["product_name", "total_stock_qty", "max_age_days"]
            )

        if self.strict_view_only:
            self.df_partner_features = self._timed_step(
                "features.partner_view_only",
                self._build_partner_features_from_views,
            )
            self.df_recent_group_spend = self._timed_step(
                "features.recent_group_spend_view_only",
                self._build_group_spend_from_ml_view,
            )
        else:
            self.df_partner_features = self._timed_step(
                "features.partner",
                self._load_partner_features,
            )
            self.df_recent_group_spend = self._timed_step(
                "features.recent_group_spend",
                lambda: self._load_recent_group_spend(self.gap_lookback_days),
            )
        self.matrix_recent = self._timed_step(
            "features.recent_matrix",
            self._build_recent_matrix,
        )
        self.df_live_scores = self._timed_step("load.live_scores", self._load_live_scores)
        self._apply_live_scores()
        self._core_loaded = True
        self._core_loaded_at = time.time()

    def ensure_clustering(self):
        if self._clustering_ready and not self._is_stale(
            self._clustering_loaded_at, self.cluster_cache_ttl_sec
        ):
            return
        self.ensure_core_loaded()
        self._timed_step("model.clustering", self.run_clustering)
        self._clustering_ready = True
        self._clustering_loaded_at = time.time()

    def ensure_churn_forecast(self):
        if self._churn_ready and not self._is_stale(
            self._churn_loaded_at, self.churn_cache_ttl_sec
        ):
            return
        if self.strict_view_only or (self.fast_mode and not self.enable_realtime_partner_scoring):
            self._churn_ready = True
            self._churn_loaded_at = time.time()
            return
        self.ensure_core_loaded()
        self.df_monthly_revenue = self._timed_step(
            "load.monthly_revenue_history",
            self._load_monthly_revenue_history,
        )
        self.df_churn_training = self._timed_step(
            "build.churn_training",
            self._build_churn_training_data,
        )
        self._timed_step("train.churn_model", self._train_churn_model)
        self._timed_step("score.churn_risk", self._score_partner_churn_risk)
        self._timed_step("build.forecast", self._build_partner_forecast)
        self._churn_ready = True
        self._churn_loaded_at = time.time()

    def ensure_credit_risk(self):
        if self._credit_ready and not self._is_stale(
            self._credit_loaded_at, self.credit_cache_ttl_sec
        ):
            return
        if self.strict_view_only or (self.fast_mode and not self.enable_realtime_partner_scoring):
            self._credit_ready = True
            self._credit_loaded_at = time.time()
            return
        self.ensure_core_loaded()
        self.df_credit_risk = self._timed_step(
            "load.credit_risk",
            self._load_credit_risk_features,
        )
        self._timed_step("score.credit_risk", self._score_credit_risk)
        self._credit_ready = True
        self._credit_loaded_at = time.time()

    def ensure_associations(self):
        if self._associations_ready and not self._is_stale(
            self._associations_loaded_at, self.assoc_cache_ttl_sec
        ):
            return
        self.ensure_core_loaded()
        self.df_assoc_rules = self._timed_step(
            "load.associations",
            self._load_associations_with_metrics,
        )
        self._associations_ready = True
        self._associations_loaded_at = time.time()

    def load_data(self, lightweight=True):
        """Load data in phases. Lightweight mode keeps app startup responsive."""
        self.ensure_core_loaded()
        if not lightweight:
            self.ensure_churn_forecast()
            self.ensure_credit_risk()
            self.ensure_associations()

    def _load_recent_group_spend(self, lookback_days):
        """
        Load partner-group spend over a fixed recent horizon for gap analysis.
        This keeps monthly/weekly/yearly projections unit-consistent.
        """
        query = """
        WITH max_date_cte AS (
            SELECT MAX(date)::date AS last_recorded_date
            FROM transactions_dsr t
            WHERE {approved}
        )
        SELECT
            mp.company_name,
            COALESCE(ms.state_name, 'Unknown') AS state,
            mg.group_name,
            SUM(tp.net_amt) AS total_spend
        FROM transactions_dsr t
        JOIN transactions_dsr_products tp ON t.id = tp.dsr_id
        JOIN master_products p ON tp.product_id = p.id
        JOIN master_group mg ON p.group_id = mg.id
        JOIN master_party mp ON t.party_id = mp.id
        LEFT JOIN master_state ms ON mp.state_id = ms.id
        CROSS JOIN max_date_cte md
        WHERE {approved}
          AND t.date >= md.last_recorded_date - INTERVAL '{lookback_days} days'
        GROUP BY mp.company_name, ms.state_name, mg.group_name
        """.format(
            approved=self._approved_condition("t"),
            lookback_days=int(lookback_days),
        )
        try:
            return pd.read_sql(query, self.engine)
        except Exception:
            return pd.DataFrame(columns=["company_name", "state", "group_name", "total_spend"])

    def _build_group_spend_from_ml_view(self):
        """
        Safely slice df_ml into the group-spend DataFrame.
        Fills missing columns (state, group_name, total_spend) with defaults
        instead of crashing when the host DB view differs from the expected schema.
        """
        if self.df_ml is None or self.df_ml.empty:
            return pd.DataFrame(
                columns=["company_name", "state", "group_name", "total_spend"]
            )
        df = self.df_ml.copy()
        # Ensure all required columns exist — fill with safe defaults if absent
        if "state" not in df.columns:
            df["state"] = "Unknown"
        if "group_name" not in df.columns:
            df["group_name"] = "General"
        if "total_spend" not in df.columns:
            df["total_spend"] = 0.0
        if "company_name" not in df.columns:
            return pd.DataFrame(
                columns=["company_name", "state", "group_name", "total_spend"]
            )
        return df[["company_name", "state", "group_name", "total_spend"]].copy()

    def _build_recent_matrix(self):
        if self.df_recent_group_spend is None or self.df_recent_group_spend.empty:
            return pd.DataFrame()

        # Ensure state column exists before pivot
        if "state" not in self.df_recent_group_spend.columns:
            self.df_recent_group_spend["state"] = "Unknown"

        matrix_recent = self.df_recent_group_spend.pivot_table(
            index="company_name",
            columns="group_name",
            values="total_spend",
            fill_value=0,
        )
        matrix_recent["state"] = (
            self.df_recent_group_spend[["company_name", "state"]]
            .drop_duplicates("company_name")
            .set_index("company_name")["state"]
        )
        return matrix_recent

    def _run_data_quality_checks(self, df_ml):
        report = DataQualityReport(rows=int(len(df_ml)) if df_ml is not None else 0)
        if df_ml is None or df_ml.empty:
            report.status = "error"
            report.errors.append("view_ml_input is empty.")
            return report.to_dict()

        required_cols = {"company_name", "group_name", "total_spend", "state"}
        missing = sorted(list(required_cols - set(df_ml.columns)))
        if missing:
            report.status = "error"
            report.errors.append(f"Missing required columns: {', '.join(missing)}")
            return report.to_dict()

        null_company = float(df_ml["company_name"].isna().mean())
        null_group = float(df_ml["group_name"].isna().mean())
        if null_company > 0:
            report.warnings.append(f"Null company_name ratio: {null_company:.2%}")
        if null_group > 0:
            report.warnings.append(f"Null group_name ratio: {null_group:.2%}")

        negatives = int((df_ml["total_spend"] < 0).sum())
        if negatives > 0:
            report.warnings.append(f"Negative total_spend rows: {negatives}")

        dupes = int(
            df_ml.duplicated(subset=["company_name", "group_name"], keep=False).sum()
        )
        if dupes > 0:
            report.warnings.append(f"Duplicate partner-group rows: {dupes}")

        if report.warnings:
            report.status = "warn"
        return report.to_dict()

    def _build_partner_features_from_views(self):
        if self.df_fact is None or self.df_fact.empty:
            return pd.DataFrame()
        features = self.df_fact.copy().reset_index()
        states = (
            self.df_ml[["company_name", "state"]]
            .drop_duplicates("company_name")
            if self.df_ml is not None and not self.df_ml.empty
            else pd.DataFrame(columns=["company_name", "state"])
        )
        features = features.merge(states, on="company_name", how="left")
        features["state"] = features["state"].fillna("Unknown")
        features["health_segment"] = np.where(
            features["health_status"].astype(str).str.contains("Champion", case=False, na=False),
            "Champion",
            np.where(
                features["health_status"].astype(str).str.contains("Emerging|Rising", case=False, na=False),
                "Emerging",
                np.where(
                    features["health_status"].astype(str).str.contains("Healthy|Stable", case=False, na=False),
                    "Healthy",
                    np.where(
                        features["health_status"].astype(str).str.contains("Risk", case=False, na=False),
                        "At Risk",
                        "Critical",
                    ),
                ),
            ),
        )
        features["health_score"] = np.where(
            features["health_segment"] == "Champion", 0.82,
            np.where(features["health_segment"] == "Emerging", 0.62,
            np.where(features["health_segment"] == "Healthy",  0.58,
            np.where(features["health_segment"] == "At Risk",  0.38,
            0.18))))
        features["estimated_monthly_loss"] = 0.0
        features["recency_days"] = 0
        features["degrowth_threshold_pct"] = 20.0
        features["degrowth_flag"] = features["revenue_drop_pct"].fillna(0).astype(float) >= 20.0
        features["churn_probability"] = 0.0
        features["churn_risk_band"] = "Unknown"
        features["expected_revenue_at_risk_90d"] = 0.0
        features["expected_revenue_at_risk_monthly"] = 0.0
        features["forecast_next_30d"] = 0.0
        features["forecast_trend_pct"] = 0.0
        features["forecast_confidence"] = 0.0
        features["credit_risk_score"] = 0.0
        features["credit_risk_band"] = "Unknown"
        features["credit_utilization"] = 0.0
        features["overdue_ratio"] = 0.0
        features["outstanding_amount"] = 0.0
        features["credit_adjusted_risk_value"] = 0.0
        return features.set_index("company_name")

    def _load_partner_features(self):
        """
        Build partner features for health scoring and degrowth detection.
        Falls back gracefully if base transaction tables are unavailable.
        """
        query = """
        WITH max_date_cte AS (
            SELECT MAX(date)::date AS last_recorded_date
            FROM transactions_dsr t
            WHERE {approved}
        ),
        monthly_party AS (
            SELECT
                t.party_id,
                DATE_TRUNC('month', t.date)::date AS sale_month,
                SUM(tp.net_amt) AS monthly_revenue
            FROM transactions_dsr t
            JOIN transactions_dsr_products tp ON t.id = tp.dsr_id
            WHERE {approved}
            GROUP BY t.party_id, DATE_TRUNC('month', t.date)
        ),
        sales_stats AS (
            SELECT
                t.party_id,
                SUM(tp.net_amt) AS lifetime_revenue,
                COUNT(DISTINCT DATE_TRUNC('month', t.date)) AS active_months,
                COUNT(DISTINCT t.id) FILTER (
                    WHERE t.date >= (SELECT last_recorded_date FROM max_date_cte) - INTERVAL '90 days'
                ) AS recent_txns,
                COUNT(DISTINCT t.id) FILTER (
                    WHERE t.date >= (SELECT last_recorded_date FROM max_date_cte) - INTERVAL '180 days'
                      AND t.date < (SELECT last_recorded_date FROM max_date_cte) - INTERVAL '90 days'
                ) AS prev_txns,
                COALESCE(SUM(tp.net_amt) FILTER (
                    WHERE t.date >= (SELECT last_recorded_date FROM max_date_cte) - INTERVAL '90 days'
                ), 0) AS recent_90_revenue,
                COALESCE(SUM(tp.net_amt) FILTER (
                    WHERE t.date >= (SELECT last_recorded_date FROM max_date_cte) - INTERVAL '180 days'
                      AND t.date < (SELECT last_recorded_date FROM max_date_cte) - INTERVAL '90 days'
                ), 0) AS prev_90_revenue,
                COUNT(DISTINCT p.group_id) FILTER (
                    WHERE t.date >= (SELECT last_recorded_date FROM max_date_cte) - INTERVAL '90 days'
                ) AS category_count,
                COUNT(DISTINCT p.group_id) FILTER (
                    WHERE t.date >= (SELECT last_recorded_date FROM max_date_cte) - INTERVAL '180 days'
                      AND t.date < (SELECT last_recorded_date FROM max_date_cte) - INTERVAL '90 days'
                ) AS category_count_prev,
                MAX(t.date)::date AS last_purchase_date
            FROM transactions_dsr t
            JOIN transactions_dsr_products tp ON t.id = tp.dsr_id
            LEFT JOIN master_products p ON tp.product_id = p.id
            WHERE {approved}
            GROUP BY t.party_id
        ),
        volatility AS (
            SELECT
                party_id,
                COALESCE(STDDEV_SAMP(monthly_revenue), 0) AS revenue_volatility
            FROM monthly_party
            GROUP BY party_id
        )
        SELECT
            mp.company_name,
            COALESCE(ms.state_name, 'Unknown') AS state,
            COALESCE(ss.lifetime_revenue, 0) AS lifetime_revenue,
            COALESCE(ss.active_months, 0) AS active_months,
            COALESCE(ss.recent_txns, 0) AS recent_txns,
            COALESCE(ss.prev_txns, 0) AS prev_txns,
            COALESCE(ss.recent_90_revenue, 0) AS recent_90_revenue,
            COALESCE(ss.prev_90_revenue, 0) AS prev_90_revenue,
            COALESCE(ss.category_count, 0) AS category_count,
            COALESCE(ss.category_count_prev, 0) AS category_count_prev,
            ss.last_purchase_date,
            (SELECT last_recorded_date FROM max_date_cte) AS data_last_date,
            COALESCE(v.revenue_volatility, 0) AS revenue_volatility
        FROM master_party mp
        LEFT JOIN master_state ms ON mp.state_id = ms.id
        LEFT JOIN sales_stats ss ON mp.id = ss.party_id
        LEFT JOIN volatility v ON mp.id = v.party_id
        """.format(approved=self._approved_condition("t"))
        try:
            features = pd.read_sql(query, self.engine)
        except Exception:
            return pd.DataFrame()

        if features.empty:
            return features

        features["last_purchase_date"] = pd.to_datetime(
            features["last_purchase_date"], errors="coerce"
        )
        features["data_last_date"] = pd.to_datetime(
            features["data_last_date"], errors="coerce"
        )
        features["recency_days"] = (
            features["data_last_date"] - features["last_purchase_date"]
        ).dt.days.fillna(9999)

        prev = features["prev_90_revenue"].replace(0, np.nan)
        features["growth_rate_90d"] = (
            (features["recent_90_revenue"] - features["prev_90_revenue"]) / prev
        ).fillna(0.0)
        features["revenue_drop_pct"] = np.where(
            (features["prev_90_revenue"] > 0)
            & (features["recent_90_revenue"] < features["prev_90_revenue"]),
            ((features["prev_90_revenue"] - features["recent_90_revenue"]) / features["prev_90_revenue"]) * 100,
            0.0,
        )
        # Churn-model behavioral features used at score time.
        features["avg_order_value"] = np.where(
            features["recent_txns"] > 0,
            features["recent_90_revenue"] / features["recent_txns"],
            0.0,
        )
        features["avg_order_value_prev"] = np.where(
            features["prev_txns"] > 0,
            features["prev_90_revenue"] / features["prev_txns"],
            0.0,
        )
        prev_aov = features["avg_order_value_prev"].replace(0, np.nan)
        features["aov_trend"] = (
            (features["avg_order_value"] - features["avg_order_value_prev"]) / prev_aov
        ).fillna(0.0).clip(-5.0, 5.0)
        features["category_diversity_change"] = (
            features["category_count"].astype(float) - features["category_count_prev"].astype(float)
        )
        prev_txns_safe = features["prev_txns"].replace(0, np.nan)
        features["engagement_velocity"] = (
            features["recent_txns"] / prev_txns_safe
        ).fillna(0.0).clip(0.0, 10.0)

        features = self._add_health_scores(features)
        return features.set_index("company_name")

    @staticmethod
    def _normalize(series):
        series = series.fillna(0.0).astype(float)
        lo, hi = series.min(), series.max()
        if np.isclose(lo, hi):
            return pd.Series(0.5, index=series.index, dtype=float)
        return (series - lo) / (hi - lo)

    def _add_health_scores(self, features):
        """
        Enterprise Health Scoring Engine v3  (Precision Tier Update)
        ================================================================
        Five segments: Champion | Emerging | Healthy | At Risk | Critical

        Key improvements over v2:
        ─────────────────────────
        1. Revenue-adaptive composite weights:
           Top-20% revenue partners (stable, mature accounts) receive a higher
           revenue weight (40%) and a lower growth weight (15%) so that a flat-
           but-massive partner is not unfairly penalised for not posting fast QoQ
           growth. Smaller partners retain the original 30/25 split.

        2. Lifetime Revenue Champion Shield:
           Partners in the top-10% by LIFETIME revenue who are still actively
           buying (recent_90_revenue > 0), with churn < 0.50 and revenue drop
           < 30%, are unconditionally classified as Champion. This captures elite
           stable accounts like Tanishk (₹67Cr) who may show near-zero QoQ growth
           because they are at saturation — not because they are at risk.

        3. State-adaptive degrowth threshold (unchanged from v2).
        4. Emerging detection on smaller base (unchanged from v2).
        5. Hard Critical override for churned partners (unchanged from v2).
        """
        f = features  # alias for brevity
        _zero = pd.Series(0.0, index=f.index)
        _ones = pd.Series(1.0, index=f.index)

        # ── Dimension 1: Revenue Magnitude (log-percentile rank) ───────────
        rev_rank = np.log1p(f["recent_90_revenue"]).rank(pct=True)

        # ── Dimension 2: Growth Momentum (signed QoQ trajectory) ───────────
        growth_clipped = f["growth_rate_90d"].clip(-1.0, 2.0)
        growth_rank = growth_clipped.rank(pct=True)

        # ── Dimension 3: Churn Safety (ML probability, first-class signal) ─
        churn_p = pd.to_numeric(
            f["churn_probability"] if "churn_probability" in f.columns else _zero,
            errors="coerce",
        ).fillna(0.0).clip(0.0, 1.0)
        churn_safety = 1.0 - churn_p

        # ── Dimension 4: Engagement Quality ────────────────────────────────
        eng_vel = pd.to_numeric(
            f["engagement_velocity"] if "engagement_velocity" in f.columns else _ones,
            errors="coerce",
        ).fillna(1.0).clip(0.0, 5.0)
        aov_t = pd.to_numeric(
            f["aov_trend"] if "aov_trend" in f.columns else _zero,
            errors="coerce",
        ).fillna(0.0).clip(-1.0, 1.0)
        engagement_raw = eng_vel * (1.0 + aov_t.clip(-0.5, 0.5))
        engagement_rank = engagement_raw.rank(pct=True)

        # ── Dimension 5: Revenue Stability ─────────────────────────────────
        rev_vol = pd.to_numeric(
            f["revenue_volatility"] if "revenue_volatility" in f.columns else _zero,
            errors="coerce",
        ).fillna(0.0)
        stability_rank = 1.0 - np.log1p(rev_vol).rank(pct=True)

        # ── Revenue-tier flag: top-20% by recent revenue ────────────────────
        # Mature, high-volume partners should be evaluated more on MAGNITUDE
        # and STABILITY than on raw QoQ growth, which is naturally compressed
        # at scale (a ₹67Cr partner can't grow 50% YoY indefinitely).
        rev_p80 = float(f["recent_90_revenue"].quantile(0.80)) if len(f) > 0 else 0.0
        top20_mask = f["recent_90_revenue"] >= max(rev_p80, 1.0)

        # ── Composite health score — revenue-tier-adaptive weights ──────────
        #
        # Standard partners (bottom 80% by rev):
        #   Revenue magnitude  30% | Growth momentum 25% |
        #   Churn safety       25% | Engagement      12% | Stability 8%
        #
        # Top-20% revenue partners:
        #   Revenue magnitude  40% | Growth momentum 15% |
        #   Churn safety       25% | Engagement      12% | Stability 8%
        #   (Growth weight cut to 15% — stability matters more at scale)
        #
        score_base = (
            0.30 * rev_rank
            + 0.25 * growth_rank
            + 0.25 * churn_safety
            + 0.12 * engagement_rank
            + 0.08 * stability_rank
        )
        score_top20 = (
            0.40 * rev_rank
            + 0.15 * growth_rank
            + 0.25 * churn_safety
            + 0.12 * engagement_rank
            + 0.08 * stability_rank
        )
        f["health_score"] = np.where(top20_mask, score_top20, score_base).clip(0.0, 1.0)

        # ── State-adaptive degrowth threshold (v2 logic, unchanged) ────────
        if "state" in f.columns and f["state"].nunique() > 1:
            state_threshold = (
                f.assign(pos_drop=f["revenue_drop_pct"].where(f["revenue_drop_pct"] > 0))
                .groupby("state")["pos_drop"]
                .transform(lambda s: float(s.quantile(0.70)) if s.notna().any() else 20.0)
                .clip(lower=10.0, upper=40.0)
            )
            f["degrowth_threshold_pct"] = state_threshold.fillna(20.0)
        else:
            f["degrowth_threshold_pct"] = 20.0

        f["degrowth_flag"] = f["revenue_drop_pct"] >= f["degrowth_threshold_pct"]
        f["estimated_monthly_loss"] = (
            (f["prev_90_revenue"] - f["recent_90_revenue"]).clip(lower=0) / 3.0
        )

        # ── Lifetime Revenue Champion Shield ────────────────────────────────
        # Strategy: partners in the top-10% by LIFETIME revenue who are still
        # actively purchasing, not massively churning, and not in freefall are
        # definitively Champion accounts regardless of their composite score.
        # This prevents stable, mature accounts at revenue saturation from
        # being mis-classified as At Risk due to near-zero QoQ growth.
        _lifetime_rev = pd.to_numeric(
            f["lifetime_revenue"] if "lifetime_revenue" in f.columns else _zero,
            errors="coerce",
        ).fillna(0.0)
        ltv_p90 = float(_lifetime_rev.quantile(0.90)) if len(_lifetime_rev) > 0 else 0.0
        _lrev_rank = _lifetime_rev.rank(pct=True)      # also used in labels below

        # ── Emerging signal: acceleration on a smaller base (unchanged) ─────
        rev_p65 = f["recent_90_revenue"].quantile(0.65)
        cat_div = pd.to_numeric(
            f["category_diversity_change"] if "category_diversity_change" in f.columns else _zero,
            errors="coerce",
        ).fillna(0.0)
        _recent_txns_s = pd.to_numeric(
            f["recent_txns"] if "recent_txns" in f.columns else _zero,
            errors="coerce",
        ).fillna(0.0)
        f["_emerging_flag"] = (
            (f["recent_90_revenue"] > 0)
            & (f["growth_rate_90d"] >= -0.05)
            & (
                (f["growth_rate_90d"] >= 0.05)
                | (eng_vel >= 1.1)
                | (_recent_txns_s >= 2)
            )
            & (cat_div >= -1)
            & (churn_p < 0.55)
            & (f["recent_90_revenue"] <= rev_p65)
        )

        # ── Five-segment classification (evaluation order is critical) ──────
        segments = []
        statuses  = []
        for row in f.itertuples():
            cp      = float(churn_p.get(row.Index, 0) or 0)
            ltv     = float(_lifetime_rev.get(row.Index, 0) or 0)
            lrev_r  = float(_lrev_rank.get(row.Index, 0) or 0)
            is_top10_ltv = ltv >= ltv_p90 and ltv_p90 > 0

            # ① Hard override: revenue stopped after buying previously
            if row.recent_90_revenue <= 0 and row.prev_90_revenue > 0:
                segments.append("Critical")
                statuses.append("Churned (Revenue Stopped)")

            # ② Lifetime Revenue Champion Shield:
            #    Top-10% lifetime value + still active + not severely churning
            #    + no revenue freefall → unconditionally Champion.
            #    These accounts define the business; they cannot be At Risk
            #    solely because their YoY growth rate plateaued at scale.
            elif (
                is_top10_ltv
                and row.recent_90_revenue > 0
                and cp < 0.50
                and row.revenue_drop_pct < 30.0
            ):
                segments.append("Champion")
                statuses.append("Champion (Elite Account — Top-10% LTV)")

            # ③ Champion: score path — high composite + growing + low churn
            elif row.health_score >= 0.72 and row.revenue_drop_pct < 10 and cp < 0.35:
                segments.append("Champion")
                statuses.append("Champion (High Performer)")

            # ④ Champion: revenue-tier path — top-20% recent rev + not truly churning
            elif (
                row.recent_90_revenue >= max(rev_p80, 1.0)
                and cp < 0.45
                and row.revenue_drop_pct < 25.0
                and row.health_score >= 0.40
            ):
                segments.append("Champion")
                statuses.append("Champion (Volume Leader)")

            # ⑤ Emerging: acceleration signals on a smaller base
            elif f.at[row.Index, "_emerging_flag"]:
                segments.append("Emerging")
                statuses.append("Emerging (Rising Star)")

            # ⑥ Healthy: solid mid-tier, no significant decline
            elif row.health_score >= 0.50 and row.revenue_drop_pct < row.degrowth_threshold_pct:
                segments.append("Healthy")
                statuses.append("Healthy (Stable)")

            # ⑦ At Risk: score deteriorating but not yet critical
            elif row.health_score >= 0.30:
                segments.append("At Risk")
                statuses.append("At Risk (Degrowth)")

            # ⑧ Critical: weak score + churn signals
            else:
                segments.append("Critical")
                statuses.append("Critical (Immediate Action)")

        f["health_segment"] = segments
        f["health_status"]  = statuses
        f.drop(columns=["_emerging_flag"], inplace=True)
        return f

    def _load_monthly_revenue_history(self):
        query = """
        WITH max_date_cte AS (
            SELECT MAX(date)::date AS last_recorded_date
            FROM transactions_dsr t
            WHERE {approved}
        )
        SELECT
            mp.company_name,
            DATE_TRUNC('month', t.date)::date AS sale_month,
            SUM(tp.net_amt) AS monthly_revenue,
            COUNT(DISTINCT t.id) AS monthly_txns
        FROM transactions_dsr t
        JOIN transactions_dsr_products tp ON t.id = tp.dsr_id
        JOIN master_party mp ON t.party_id = mp.id
        CROSS JOIN max_date_cte md
        WHERE {approved}
          AND t.date >= md.last_recorded_date - INTERVAL '{months} months'
        GROUP BY mp.company_name, DATE_TRUNC('month', t.date)
        """.format(
            approved=self._approved_condition("t"),
            months=int(self.churn_history_months + self.forecast_history_months + 3),
        )
        try:
            df = pd.read_sql(query, self.engine)
            if df.empty:
                return df
            df["sale_month"] = pd.to_datetime(df["sale_month"], errors="coerce")
            return df
        except Exception:
            return pd.DataFrame(
                columns=["company_name", "sale_month", "monthly_revenue", "monthly_txns"]
            )
