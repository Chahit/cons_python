"""
Product Lifecycle Intelligence mixin for the SalesIntelligenceEngine.
Provides growth velocity scoring, cannibalization detection, end-of-life prediction,
and Prophet-powered time-series forecasting with seasonality.
"""

import logging
import time
import warnings
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class ProductLifecycleMixin:
    """Product-level trend analysis: velocity, cannibalization, EOL prediction."""

    _lifecycle_ready = False
    _lifecycle_loaded_at = None

    # -----------------------------------------------------------------------
    # Lifecycle orchestration
    # -----------------------------------------------------------------------

    def ensure_product_lifecycle(self):
        """Load and compute all product lifecycle data."""
        if self._lifecycle_ready and not self._is_stale(
            self._lifecycle_loaded_at, getattr(self, "core_cache_ttl_sec", 900)
        ):
            return
        self.ensure_core_loaded()
        self.ensure_associations()

        self.df_product_monthly = self._timed_step(
            "lifecycle.monthly_product_revenue",
            self._load_product_monthly_revenue,
        )
        self.df_product_velocity = self._timed_step(
            "lifecycle.growth_velocity",
            self._compute_growth_velocity,
        )
        self.df_product_cannibalization = self._timed_step(
            "lifecycle.cannibalization",
            self._detect_cannibalization,
        )
        self.df_product_eol = self._timed_step(
            "lifecycle.eol_prediction",
            self._predict_end_of_life,
        )
        self._lifecycle_ready = True
        self._lifecycle_loaded_at = time.time()

    # -----------------------------------------------------------------------
    # 1. Monthly product-level revenue loading
    # -----------------------------------------------------------------------

    def _load_product_monthly_revenue(self) -> pd.DataFrame:
        """
        Load monthly revenue aggregated by product group.
        Uses the same base tables as _load_monthly_revenue_history but groups by product.
        """
        query = """
        WITH max_date_cte AS (
            SELECT MAX(date)::date AS last_recorded_date
            FROM transactions_dsr t
            WHERE {approved}
        )
        SELECT
            mg.group_name AS product_name,
            DATE_TRUNC('month', t.date)::date AS sale_month,
            SUM(tp.net_amt) AS monthly_revenue,
            COUNT(DISTINCT t.id) AS monthly_txn_count,
            COUNT(DISTINCT t.party_id) AS monthly_buyer_count
        FROM transactions_dsr t
        JOIN transactions_dsr_products tp ON t.id = tp.dsr_id
        JOIN master_products p ON tp.product_id = p.id
        JOIN master_group mg ON p.group_id = mg.id
        CROSS JOIN max_date_cte md
        WHERE {approved}
          AND t.date >= md.last_recorded_date - INTERVAL '18 months'
        GROUP BY mg.group_name, DATE_TRUNC('month', t.date)
        ORDER BY mg.group_name, DATE_TRUNC('month', t.date)
        """.format(approved=self._approved_condition("t"))
        try:
            df = pd.read_sql(query, self.engine)
            if not df.empty:
                df["sale_month"] = pd.to_datetime(df["sale_month"], errors="coerce")
            return df
        except Exception:
            return pd.DataFrame(
                columns=["product_name", "sale_month", "monthly_revenue",
                         "monthly_txn_count", "monthly_buyer_count"]
            )

    # -----------------------------------------------------------------------
    # 2. Growth velocity scoring
    # -----------------------------------------------------------------------

    def _compute_growth_velocity(self) -> pd.DataFrame:
        """
        Score each product's growth velocity using:
        - Revenue trend slope (linear regression over months)
        - 3-month vs 3-month-prior growth rate
        - Buyer count trend
        - Transaction intensity trend
        Then classify into lifecycle stage.
        """
        df = self.df_product_monthly
        if df is None or df.empty:
            return pd.DataFrame()

        products = df["product_name"].unique()
        records = []

        for prod in products:
            sub = df[df["product_name"] == prod].sort_values("sale_month")
            if len(sub) < 3:
                continue

            # Overall stats
            total_revenue = float(sub["monthly_revenue"].sum())
            total_months = len(sub)
            avg_monthly = float(sub["monthly_revenue"].mean())
            latest_month = sub["sale_month"].max()

            # Revenue trend slope (linear regression: month_index -> revenue)
            sub = sub.copy()
            sub["month_idx"] = np.arange(len(sub))
            try:
                coeffs = np.polyfit(sub["month_idx"].values, sub["monthly_revenue"].values, 1)
                slope = float(coeffs[0])  # Revenue change per month
                slope_pct = (slope / avg_monthly * 100) if avg_monthly > 0 else 0.0
            except Exception:
                slope = 0.0
                slope_pct = 0.0

            # Recent 3 months vs prior 3 months growth
            recent_3 = sub.tail(3)["monthly_revenue"].sum()
            if len(sub) >= 6:
                prior_3 = sub.iloc[-6:-3]["monthly_revenue"].sum()
            else:
                prior_3 = sub.head(len(sub) - 3)["monthly_revenue"].sum() if len(sub) > 3 else recent_3
            growth_3m = ((recent_3 - prior_3) / prior_3 * 100) if prior_3 > 0 else 0.0

            # Peak revenue & distance from peak
            peak_revenue = float(sub["monthly_revenue"].max())
            current_revenue = float(sub.iloc[-1]["monthly_revenue"])
            peak_distance_pct = ((peak_revenue - current_revenue) / peak_revenue * 100) if peak_revenue > 0 else 0.0

            # Buyer trend
            try:
                buyer_coeffs = np.polyfit(sub["month_idx"].values, sub["monthly_buyer_count"].values, 1)
                buyer_trend = float(buyer_coeffs[0])
            except Exception:
                buyer_trend = 0.0

            # Transaction intensity trend
            try:
                txn_coeffs = np.polyfit(sub["month_idx"].values, sub["monthly_txn_count"].values, 1)
                txn_trend = float(txn_coeffs[0])
            except Exception:
                txn_trend = 0.0

            # Revenue volatility (coefficient of variation)
            rev_std = float(sub["monthly_revenue"].std())
            cv = (rev_std / avg_monthly) if avg_monthly > 0 else 0.0

            # Months since peak
            peak_month = sub.loc[sub["monthly_revenue"].idxmax(), "sale_month"]
            months_since_peak = max(0, (latest_month.year - peak_month.year) * 12 + (latest_month.month - peak_month.month))

            # Composite velocity score: weighted signal combining slope, growth, buyer trend
            velocity_score = (
                0.35 * np.clip(slope_pct / 10, -1, 1)   # Normalized slope
                + 0.30 * np.clip(growth_3m / 50, -1, 1)  # 3m growth
                + 0.20 * np.clip(buyer_trend / 2, -1, 1)  # Buyer trend
                + 0.15 * np.clip(txn_trend / 5, -1, 1)    # Txn trend
            )

            # Lifecycle stage classification
            if velocity_score >= 0.3 and growth_3m > 15:
                stage = "Growing"
            elif velocity_score >= 0.05 and growth_3m > -5:
                stage = "Mature"
            elif velocity_score >= -0.15 and peak_distance_pct < 30:
                stage = "Plateauing"
            elif velocity_score >= -0.4 or peak_distance_pct >= 30:
                stage = "Declining"
            else:
                stage = "End-of-Life"

            records.append({
                "product_name": prod,
                "total_revenue": round(total_revenue, 2),
                "avg_monthly_revenue": round(avg_monthly, 2),
                "total_months_active": total_months,
                "slope_per_month": round(slope, 2),
                "slope_pct": round(slope_pct, 2),
                "growth_3m_pct": round(growth_3m, 2),
                "peak_revenue": round(peak_revenue, 2),
                "current_revenue": round(current_revenue, 2),
                "peak_distance_pct": round(peak_distance_pct, 2),
                "months_since_peak": months_since_peak,
                "buyer_trend": round(buyer_trend, 3),
                "txn_trend": round(txn_trend, 3),
                "revenue_cv": round(cv, 3),
                "velocity_score": round(velocity_score, 4),
                "lifecycle_stage": stage,
                "latest_month": latest_month,
            })

        result = pd.DataFrame(records)
        if not result.empty:
            result = result.sort_values("velocity_score", ascending=False).reset_index(drop=True)
        return result

    # -----------------------------------------------------------------------
    # 3. Cannibalization detection
    # -----------------------------------------------------------------------

    def _detect_cannibalization(self) -> pd.DataFrame:
        """
        Detect product cannibalization from association rules.
        Cannibalization = Product A is growing while a closely associated Product B is declining.
        This suggests A may be replacing B.

        Uses MBA association rules + growth velocity data.
        """
        velocity = self.df_product_velocity
        assoc = getattr(self, "df_assoc_rules", None)

        if velocity is None or velocity.empty:
            return pd.DataFrame()
        if assoc is None or assoc.empty:
            return pd.DataFrame()

        # Get growing and declining products
        growing = set(velocity[velocity["lifecycle_stage"] == "Growing"]["product_name"].values)
        declining = set(velocity[velocity["lifecycle_stage"].isin(["Declining", "End-of-Life"])]["product_name"].values)

        if not growing or not declining:
            return pd.DataFrame()

        # Find association pairs where one is growing, the other is declining
        cannibalization_pairs = []

        for _, rule in assoc.iterrows():
            prod_a = str(rule.get("product_a", ""))
            prod_b = str(rule.get("product_b", ""))
            confidence = float(rule.get("confidence_a_to_b", 0))
            lift = float(rule.get("lift_a_to_b", 0))

            # Look for the pattern: growing product cannibalizing declining product
            if prod_a in growing and prod_b in declining:
                cannibal, victim = prod_a, prod_b
            elif prod_b in growing and prod_a in declining:
                cannibal, victim = prod_b, prod_a
            else:
                continue

            # Only flag high-confidence associations as cannibalization
            if confidence < 0.15 or lift < 1.0:
                continue

            c_data = velocity[velocity["product_name"] == cannibal].iloc[0]
            v_data = velocity[velocity["product_name"] == victim].iloc[0]

            cannibalization_pairs.append({
                "cannibal_product": cannibal,
                "cannibal_growth_3m_pct": float(c_data["growth_3m_pct"]),
                "cannibal_velocity": float(c_data["velocity_score"]),
                "victim_product": victim,
                "victim_growth_3m_pct": float(v_data["growth_3m_pct"]),
                "victim_velocity": float(v_data["velocity_score"]),
                "association_confidence": round(confidence, 3),
                "association_lift": round(lift, 2),
                "cannibalization_score": round(
                    float(c_data["velocity_score"]) - float(v_data["velocity_score"]), 3
                ),
                "estimated_revenue_shift": round(
                    abs(float(v_data["slope_per_month"])) * 3, 2
                ),
            })

        result = pd.DataFrame(cannibalization_pairs)
        if not result.empty:
            result = result.sort_values("cannibalization_score", ascending=False).reset_index(drop=True)
        return result

    # -----------------------------------------------------------------------
    # 4. End-of-life prediction
    # -----------------------------------------------------------------------

    def _predict_end_of_life(self) -> pd.DataFrame:
        """
        Predict end-of-life timeline for slow-moving products.
        Uses:
        - Current revenue trajectory (slope)
        - Stock age from view_ageing_stock
        - Buyer attrition (declining buyer count)
        - Peak distance (how far below peak)

        Returns products at risk with estimated months until EOL.
        """
        velocity = self.df_product_velocity
        if velocity is None or velocity.empty:
            return pd.DataFrame()

        # Focus on declining / plateauing products
        at_risk = velocity[velocity["lifecycle_stage"].isin(
            ["Declining", "End-of-Life", "Plateauing"]
        )].copy()

        if at_risk.empty:
            return pd.DataFrame()

        # Merge stock age info if available
        stock_info = getattr(self, "df_stock_stats", None)
        if stock_info is not None and not stock_info.empty:
            stock_agg = stock_info.groupby("product_name").agg(
                total_stock=("total_stock_qty", "sum"),
                max_age_days=("max_age_days", "max"),
            ).reset_index()
            at_risk = at_risk.merge(stock_agg, on="product_name", how="left")
        else:
            at_risk["total_stock"] = np.nan
            at_risk["max_age_days"] = np.nan

        # Estimate months until revenue reaches zero (from linear extrapolation)
        eol_records = []
        for _, row in at_risk.iterrows():
            slope = float(row["slope_per_month"])
            current = float(row["current_revenue"])
            peak_dist = float(row["peak_distance_pct"])
            buyer_trend = float(row["buyer_trend"])

            # Months until zero revenue (if slope is negative)
            if slope < 0 and current > 0:
                months_to_zero = current / abs(slope)
            else:
                months_to_zero = float("inf")

            # Cap at 36 months
            months_to_zero = min(months_to_zero, 36.0)

            # EOL risk score (0-1, higher = more at risk)
            score_components = []
            # 1. Revenue decline speed
            if slope < 0:
                score_components.append(min(abs(slope) / max(current, 1) * 10, 1.0))
            else:
                score_components.append(0.0)
            # 2. Distance from peak
            score_components.append(min(peak_dist / 100, 1.0))
            # 3. Buyer attrition
            if buyer_trend < 0:
                score_components.append(min(abs(buyer_trend) / 3, 1.0))
            else:
                score_components.append(0.0)
            # 4. Stock age risk (older stock = higher risk)
            stock_age = float(row.get("max_age_days", 0) or 0)
            score_components.append(min(stock_age / 180, 1.0))

            eol_risk = (
                0.30 * score_components[0]
                + 0.25 * score_components[1]
                + 0.25 * score_components[2]
                + 0.20 * score_components[3]
            )

            # Urgency classification
            if eol_risk >= 0.7 or months_to_zero <= 3:
                urgency = "Critical"
            elif eol_risk >= 0.45 or months_to_zero <= 6:
                urgency = "High"
            elif eol_risk >= 0.25 or months_to_zero <= 12:
                urgency = "Medium"
            else:
                urgency = "Low"

            # Suggested action
            if urgency == "Critical":
                action = "Liquidate stock immediately; stop procurement; run clearance sale"
            elif urgency == "High":
                action = "Reduce reorder quantity; bundle with fast-movers; discount 15-25%"
            elif urgency == "Medium":
                action = "Monitor closely; create promotional bundles; limit new purchases"
            else:
                action = "Continue monitoring; review in 3 months"

            eol_records.append({
                "product_name": row["product_name"],
                "lifecycle_stage": row["lifecycle_stage"],
                "current_revenue": round(current, 2),
                "slope_per_month": round(slope, 2),
                "growth_3m_pct": round(float(row["growth_3m_pct"]), 2),
                "peak_distance_pct": round(peak_dist, 1),
                "months_since_peak": int(row["months_since_peak"]),
                "buyer_trend": round(buyer_trend, 3),
                "total_stock": row.get("total_stock", None),
                "max_age_days": row.get("max_age_days", None),
                "est_months_to_zero": round(months_to_zero, 1),
                "eol_risk_score": round(eol_risk, 3),
                "urgency": urgency,
                "suggested_action": action,
            })

        result = pd.DataFrame(eol_records)
        if not result.empty:
            result = result.sort_values("eol_risk_score", ascending=False).reset_index(drop=True)
        return result

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def get_product_velocity_summary(self) -> dict:
        """Return a summary of product lifecycle stages."""
        self.ensure_product_lifecycle()
        v = self.df_product_velocity
        if v is None or v.empty:
            return {"status": "no_data", "total_products": 0}

        stages = v["lifecycle_stage"].value_counts().to_dict()
        return {
            "status": "ok",
            "total_products": len(v),
            "growing": int(stages.get("Growing", 0)),
            "mature": int(stages.get("Mature", 0)),
            "plateauing": int(stages.get("Plateauing", 0)),
            "declining": int(stages.get("Declining", 0)),
            "end_of_life": int(stages.get("End-of-Life", 0)),
            "avg_velocity": round(float(v["velocity_score"].mean()), 4),
            "top_grower": str(v.iloc[0]["product_name"]) if len(v) > 0 else "N/A",
            "fastest_declining": str(v.iloc[-1]["product_name"]) if len(v) > 0 else "N/A",
        }

    def get_velocity_data(self, stage_filter: str | None = None) -> pd.DataFrame:
        """Get product velocity data, optionally filtered by lifecycle stage."""
        self.ensure_product_lifecycle()
        v = self.df_product_velocity
        if v is None or v.empty:
            return pd.DataFrame()
        if stage_filter and stage_filter != "All":
            v = v[v["lifecycle_stage"] == stage_filter]
        return v

    def get_cannibalization_data(self) -> pd.DataFrame:
        """Get cannibalization detection results."""
        self.ensure_product_lifecycle()
        return self.df_product_cannibalization if self.df_product_cannibalization is not None else pd.DataFrame()

    def get_eol_predictions(self, urgency_filter: str | None = None) -> pd.DataFrame:
        """Get end-of-life predictions, optionally filtered by urgency."""
        self.ensure_product_lifecycle()
        eol = self.df_product_eol
        if eol is None or eol.empty:
            return pd.DataFrame()
        if urgency_filter and urgency_filter != "All":
            eol = eol[eol["urgency"] == urgency_filter]
        return eol

    def get_product_trend(self, product_name: str) -> pd.DataFrame:
        """Get monthly revenue trend for a specific product."""
        self.ensure_product_lifecycle()
        df = self.df_product_monthly
        if df is None or df.empty:
            return pd.DataFrame()
        return df[df["product_name"] == product_name].sort_values("sale_month")

    # -----------------------------------------------------------------------
    # Prophet Forecasting
    # -----------------------------------------------------------------------

    def _prophet_forecast_product(
        self,
        product_name: str,
        periods: int = 6,
    ) -> pd.DataFrame:
        """
        Fit a Prophet model on a product's monthly revenue and return a forecast.

        Returns a DataFrame with columns:
            ds, yhat, yhat_lower, yhat_upper, type ('actual' | 'forecast')

        Falls back to linear extrapolation if Prophet is unavailable or
        there are fewer than 6 months of data.
        """
        self.ensure_product_lifecycle()
        df = self.df_product_monthly
        if df is None or df.empty:
            return pd.DataFrame()

        sub = (
            df[df["product_name"] == product_name]
            .sort_values("sale_month")
            .dropna(subset=["sale_month", "monthly_revenue"])
            .copy()
        )
        if sub.empty:
            return pd.DataFrame()

        # Build actual rows for the result
        actual = sub[["sale_month", "monthly_revenue"]].copy()
        actual.columns = ["ds", "yhat"]
        actual["yhat_lower"] = actual["yhat"]
        actual["yhat_upper"] = actual["yhat"]
        actual["type"] = "actual"
        actual["ds"] = pd.to_datetime(actual["ds"])

        # ── Attempt Prophet ──────────────────────────────────────────────────
        MIN_MONTHS = 6
        if len(sub) >= MIN_MONTHS:
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    from prophet import Prophet  # type: ignore

                prophet_df = pd.DataFrame({
                    "ds": pd.to_datetime(sub["sale_month"]),
                    "y":  sub["monthly_revenue"].astype(float).clip(lower=0),
                })

                m = Prophet(
                    yearly_seasonality=True,
                    weekly_seasonality=False,
                    daily_seasonality=False,
                    seasonality_mode="multiplicative",
                    changepoint_prior_scale=0.1,
                    interval_width=0.80,
                    stan_backend="CMDSTANPY" if False else None,  # use default
                )
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    m.fit(prophet_df)

                future = m.make_future_dataframe(periods=periods, freq="MS")
                forecast = m.predict(future)

                # Keep only future rows (beyond last actual month)
                last_actual = prophet_df["ds"].max()
                future_fc = forecast[forecast["ds"] > last_actual][
                    ["ds", "yhat", "yhat_lower", "yhat_upper"]
                ].copy()
                future_fc["yhat"]       = future_fc["yhat"].clip(lower=0).round(2)
                future_fc["yhat_lower"] = future_fc["yhat_lower"].clip(lower=0).round(2)
                future_fc["yhat_upper"] = future_fc["yhat_upper"].clip(lower=0).round(2)
                future_fc["type"]       = "forecast"

                return pd.concat([actual, future_fc], ignore_index=True)

            except Exception as exc:
                logger.debug("Prophet failed for %s, using linear: %s", product_name, exc)

        # ── Fallback: linear extrapolation ───────────────────────────────────
        sub2 = sub.copy()
        sub2["month_idx"] = np.arange(len(sub2))
        try:
            coeffs = np.polyfit(sub2["month_idx"].values,
                                sub2["monthly_revenue"].astype(float).values, 1)
            slope, intercept = coeffs[0], coeffs[1]
        except Exception:
            slope, intercept = 0.0, float(sub["monthly_revenue"].mean())

        last_date = pd.to_datetime(sub["sale_month"].max())
        forecast_rows = []
        for i in range(1, periods + 1):
            next_ds = last_date + pd.DateOffset(months=i)
            pred = max(0.0, slope * (len(sub2) + i - 1) + intercept)
            forecast_rows.append({
                "ds": next_ds, "yhat": round(pred, 2),
                "yhat_lower": round(pred * 0.85, 2),
                "yhat_upper": round(pred * 1.15, 2),
                "type": "forecast",
            })

        return pd.concat([actual, pd.DataFrame(forecast_rows)], ignore_index=True)

    def get_product_prophet_forecast(self, product_name: str, periods: int = 6) -> dict:
        """
        Public API: return Prophet (or linear) forecast for a product.

        Returns a dict with:
            product_name, method, periods, data (list of dicts)
        """
        fc = self._prophet_forecast_product(product_name, periods=periods)
        if fc.empty:
            return {"product_name": product_name, "method": "none", "periods": 0, "data": []}

        # Detect which method was used
        try:
            from prophet import Prophet  # noqa: F401
            method = "prophet" if len(self.df_product_monthly[
                self.df_product_monthly["product_name"] == product_name
            ]) >= 6 else "linear"
        except ImportError:
            method = "linear"

        fc["ds"] = fc["ds"].astype(str)
        return {
            "product_name": product_name,
            "method": method,
            "periods": int((fc["type"] == "forecast").sum()),
            "data": fc.to_dict(orient="records"),
        }
