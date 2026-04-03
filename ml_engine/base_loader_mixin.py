import time
import numpy as np
import pandas as pd
from .schemas import DataQualityReport

class BaseLoaderMixin:
    # ── Date-filtered accessors ────────────────────────────────────────────────
    # All mixins and tabs should prefer these over self.df_fact / self.df_ml.
    # Both fall back to the full frame when no date range is set.

    @property
    def df_fact_filtered(self):
        """Return df_fact sliced to the sidebar date window (or full df_fact)."""
        return self.get_date_filtered_fact() if self.df_fact is not None else None

    @property
    def df_ml_filtered(self):
        """Return df_ml sliced to the sidebar date window (or full df_ml)."""
        return self.get_date_filtered_ml() if self.df_ml is not None else None

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
                lambda: self.df_ml[
                    [c for c in ["company_name", "state", "group_name", "total_spend"]
                     if c in self.df_ml.columns]
                ].copy() if self.df_ml is not None and not self.df_ml.empty
                else pd.DataFrame(columns=["company_name", "state", "group_name", "total_spend"]),
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
        # Inject auto-named cluster labels into df_partner_features so every tab
        # (Kanban, Partner 360, Chatbot, Monitoring) sees meaningful labels
        # like "VIP — High-Value · Diversified" instead of "VIP-0".
        self._merge_cluster_labels_to_features()
        self._clustering_ready = True
        self._clustering_loaded_at = time.time()

    def _merge_cluster_labels_to_features(self):
        if self.matrix is None or self.matrix.empty:
            return
        if self.df_partner_features is None or self.df_partner_features.empty:
            return

        # ── Deduplicate both indices before reindex to prevent ValueError ──
        if self.matrix.index.duplicated().any():
            self.matrix = self.matrix[~self.matrix.index.duplicated(keep="last")]
        if self.df_partner_features.index.duplicated().any():
            self.df_partner_features = self.df_partner_features[
                ~self.df_partner_features.index.duplicated(keep="last")
            ]

        cluster_cols = ["cluster_label", "cluster_type", "cluster", "strategic_tag"]
        for col in cluster_cols:
            if col in self.matrix.columns:
                self.df_partner_features[col] = (
                    self.matrix[col].reindex(self.df_partner_features.index)
                )

        if "cluster_label" in self.df_partner_features.columns:
            self.df_partner_features["cluster_label"] = (
                self.df_partner_features["cluster_label"].fillna("Uncategorized")
            )
        if "cluster_type" in self.df_partner_features.columns:
            self.df_partner_features["cluster_type"] = (
                self.df_partner_features["cluster_type"].fillna("Growth")
            )


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

    def _build_recent_matrix(self):
        if self.df_recent_group_spend is None or self.df_recent_group_spend.empty:
            return pd.DataFrame()
        if "group_name" not in self.df_recent_group_spend.columns:
            return pd.DataFrame()

        _val_col = next(
            (c for c in ["total_spend", "total_revenue"] if c in self.df_recent_group_spend.columns),
            None,
        )
        if _val_col is None:
            return pd.DataFrame()

        matrix_recent = self.df_recent_group_spend.pivot_table(
            index="company_name",
            columns="group_name",
            values=_val_col,
            aggfunc="sum",
            fill_value=0,
        )
        # Deduplicate index (safety guard)
        matrix_recent = matrix_recent[~matrix_recent.index.duplicated(keep="last")]

        if "state" in self.df_recent_group_spend.columns:
            matrix_recent["state"] = (
                self.df_recent_group_spend[["company_name", "state"]]
                .drop_duplicates("company_name")
                .set_index("company_name")["state"]
                .reindex(matrix_recent.index)
                .fillna("Unknown")
            )
        else:
            matrix_recent["state"] = "Unknown"
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
        """Build partner-level features from view_ml_input (df_ml).
        df_fact is product-level and has no company_name — df_ml is the correct source.
        """
        if self.df_ml is None or self.df_ml.empty:
            return pd.DataFrame()

        # df_ml may have multiple rows per partner (one per group_name).
        # Aggregate to one row per company.
        agg_cols = {c: "first" for c in ["state", "party_id"] if c in self.df_ml.columns}
        agg_cols.update({
            c: "sum" for c in ["total_revenue", "total_spend", "order_count", "product_diversity"]
            if c in self.df_ml.columns
        })
        agg_cols.update({
            c: "mean" for c in ["avg_order_value", "avg_payment_days"]
            if c in self.df_ml.columns
        })
        if "last_order_date" in self.df_ml.columns:
            # Force datetime — psycopg2 may return date objects as object dtype
            try:
                self.df_ml["last_order_date"] = pd.to_datetime(
                    self.df_ml["last_order_date"], errors="coerce"
                )
                agg_cols["last_order_date"] = "max"
            except Exception:
                pass  # skip if not coercible
        if "recency_days" in self.df_ml.columns:
            # Force numeric — PostgreSQL interval may come in as object/timedelta
            try:
                col = self.df_ml["recency_days"]
                if col.dtype == object or str(col.dtype).startswith("timedelta"):
                    self.df_ml["recency_days"] = pd.to_numeric(
                        col.apply(lambda x: x.days if hasattr(x, "days") else x),
                        errors="coerce",
                    )
                agg_cols["recency_days"] = "min"  # min = most recently active
            except Exception:
                pass  # skip if not coercible

        features = self.df_ml.groupby("company_name", as_index=False).agg(agg_cols)
        features["state"] = features["state"].fillna("Unknown") if "state" in features.columns else "Unknown"

        # Derive revenue proxy columns expected by downstream components
        rev_col = "total_revenue" if "total_revenue" in features.columns else "total_spend"
        features["recent_90_revenue"] = features.get(rev_col, pd.Series(0.0, index=features.index))
        # In the fallback path we don't have the 90-180 day split.
        # Use flat assumption (prev = recent) — neutral and honest.
        # The old `* 0.9` implied all partners dropped 11% which was wrong:
        # it inflated churn scores uniformly and made revenue_drop_pct misleading.
        features["prev_90_revenue"] = features["recent_90_revenue"].copy()
        features["revenue_drop_pct"] = 0.0
        features["growth_rate_90d"] = 0.0

        n = len(features)
        idx = features.index
        features["health_score"] = pd.Series(0.65, index=idx, dtype=float)
        features["health_segment"] = pd.Series(["Healthy"] * n, index=idx)
        features["health_status"] = pd.Series(["Stable"] * n, index=idx)
        features["estimated_monthly_loss"] = pd.Series(0.0, index=idx, dtype=float)
        features["degrowth_threshold_pct"] = pd.Series(20.0, index=idx, dtype=float)
        features["degrowth_flag"] = pd.Series([False] * n, index=idx)
        features["churn_probability"] = pd.Series(0.0, index=idx, dtype=float)
        features["churn_risk_band"] = pd.Series(["Unknown"] * n, index=idx)
        features["expected_revenue_at_risk_90d"] = pd.Series(0.0, index=idx, dtype=float)
        features["expected_revenue_at_risk_monthly"] = pd.Series(0.0, index=idx, dtype=float)
        features["forecast_next_30d"] = pd.Series(0.0, index=idx, dtype=float)
        features["forecast_trend_pct"] = pd.Series(0.0, index=idx, dtype=float)
        features["forecast_confidence"] = pd.Series(0.0, index=idx, dtype=float)
        features["credit_risk_score"] = pd.Series(0.0, index=idx, dtype=float)
        features["credit_risk_band"] = pd.Series(["Unknown"] * n, index=idx)
        features["credit_utilization"] = pd.Series(0.0, index=idx, dtype=float)
        features["overdue_ratio"] = pd.Series(0.0, index=idx, dtype=float)
        features["outstanding_amount"] = pd.Series(0.0, index=idx, dtype=float)
        features["credit_adjusted_risk_value"] = pd.Series(0.0, index=idx, dtype=float)
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
        revenue_strength = self._normalize(np.log1p(features["recent_90_revenue"]))
        growth_trend = self._normalize(features["growth_rate_90d"].clip(-1.0, 1.5))
        # LOG-TRANSFORM recency before normalizing into the health score.
        # WHY: Linear normalization treats absence of 10d vs 40d identically to 100d vs 200d.
        # np.log1p compresses short absences — a partner gone 10 days is barely penalized,
        # while one gone 200+ days is heavily penalized. This matches real sales urgency.
        recency_activity = 1.0 - self._normalize(np.log1p(features["recency_days"].clip(lower=0)))
        stability = 1.0 - self._normalize(np.log1p(features["revenue_volatility"]))

        features["health_score"] = (
            0.35 * revenue_strength
            + 0.30 * growth_trend
            + 0.20 * recency_activity
            + 0.15 * stability
        ).clip(0.0, 1.0)

        state_threshold = (
            features.assign(pos_drop=features["revenue_drop_pct"].where(features["revenue_drop_pct"] > 0))
            .groupby("state")["pos_drop"]
            .transform(lambda s: float(s.quantile(0.70)) if s.notna().any() else 20.0)
            .clip(lower=10.0, upper=40.0)
        )
        features["degrowth_threshold_pct"] = state_threshold.fillna(20.0)
        features["degrowth_flag"] = (
            features["revenue_drop_pct"] >= features["degrowth_threshold_pct"]
        )
        features["estimated_monthly_loss"] = (
            (features["prev_90_revenue"] - features["recent_90_revenue"]).clip(lower=0) / 3.0
        )

        # Revenue at risk — trend-based baseline.
        # Formula: absolute revenue lost over the past 90 days (prev - recent, floor 0).
        # This gives a meaningful non-zero value immediately from health scoring,
        # even before churn scoring runs. When _score_partner_churn_risk() runs,
        # it overwrites this with the more accurate formula:
        #   expected_revenue_at_risk_90d = churn_probability × recent_90_revenue
        # which is better because it accounts for partners who are declining slowly
        # (still positive revenue, but high churn probability).
        features["expected_revenue_at_risk_90d"] = (
            (features["prev_90_revenue"] - features["recent_90_revenue"]).clip(lower=0)
        )
        features["expected_revenue_at_risk_monthly"] = features["estimated_monthly_loss"].copy()

        segments = []
        statuses = []
        for row in features.itertuples():
            if row.recent_90_revenue <= 0 and row.prev_90_revenue > 0:
                segments.append("Critical")
                statuses.append("Churned (Risk)")
            elif row.health_score >= 0.8 and row.revenue_drop_pct < 10:
                segments.append("Champion")
                statuses.append("Healthy (Growing)")
            elif row.health_score >= 0.6 and row.revenue_drop_pct < row.degrowth_threshold_pct:
                segments.append("Healthy")
                statuses.append("Stable")
            elif row.health_score >= 0.4:
                segments.append("At Risk")
                statuses.append("At Risk (Degrowth)")
            else:
                segments.append("Critical")
                statuses.append("Critical (Immediate Action)")

        features["health_segment"] = segments
        features["health_status"] = statuses
        return features

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
