"""
Product Lifecycle Intelligence mixin for the SalesIntelligenceEngine.
Provides growth velocity scoring, cannibalization detection, and end-of-life prediction.
"""

import time
import numpy as np
import pandas as pd


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
        # Individual-product-level monthly data (with category / group)
        self.df_individual_product_monthly = self._timed_step(
            "lifecycle.individual_monthly_product_revenue",
            self._load_individual_product_monthly_revenue,
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

    def _load_individual_product_monthly_revenue(self) -> pd.DataFrame:
        """
        Load monthly revenue at the individual master_products level (not group-level).
        Also joins master_group and master_product_category for filter support.
        """
        query = """
        WITH max_date_cte AS (
            SELECT MAX(date)::date AS last_recorded_date
            FROM transactions_dsr t
            WHERE {approved}
        )
        SELECT
            p.product_name,
            COALESCE(mg.group_name, 'General')        AS product_group,
            COALESCE(mpc.category_name, 'General')    AS product_category,
            DATE_TRUNC('month', t.date)::date          AS sale_month,
            SUM(tp.net_amt)                            AS monthly_revenue,
            COUNT(DISTINCT t.id)                       AS monthly_txn_count,
            COUNT(DISTINCT t.party_id)                 AS monthly_buyer_count
        FROM transactions_dsr t
        JOIN transactions_dsr_products tp  ON t.id = tp.dsr_id
        JOIN master_products p             ON tp.product_id = p.id
        LEFT JOIN master_group mg          ON p.group_id = mg.id
        LEFT JOIN master_product_category mpc ON mg.category_id_id = mpc.id
        CROSS JOIN max_date_cte md
        WHERE {approved}
          AND t.date >= md.last_recorded_date - INTERVAL '18 months'
        GROUP BY p.product_name, mg.group_name, mpc.category_name,
                 DATE_TRUNC('month', t.date)
        ORDER BY p.product_name, DATE_TRUNC('month', t.date)
        """.format(approved=self._approved_condition("t"))
        try:
            df = pd.read_sql(query, self.engine)
            if not df.empty:
                df["sale_month"] = pd.to_datetime(df["sale_month"], errors="coerce")
            return df
        except Exception:
            return pd.DataFrame(columns=[
                "product_name", "product_group", "product_category",
                "sale_month", "monthly_revenue", "monthly_txn_count", "monthly_buyer_count",
            ])

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

    def get_product_categories(self) -> list:
        """Return sorted list of distinct product categories from individual product data."""
        self.ensure_product_lifecycle()
        df = getattr(self, "df_individual_product_monthly", None)
        if df is None or df.empty or "product_category" not in df.columns:
            return []
        return sorted(df["product_category"].dropna().unique().tolist())

    def get_products_for_category(self, category: str | None = None) -> list:
        """Return sorted list of product names, optionally filtered by category."""
        self.ensure_product_lifecycle()
        df = getattr(self, "df_individual_product_monthly", None)
        if df is None or df.empty or "product_name" not in df.columns:
            return []
        if category and category != "All":
            df = df[df["product_category"] == category]
        return sorted(df["product_name"].dropna().unique().tolist())

    def get_velocity_data(
        self,
        stage_filter: str | None = None,
        period: str | None = None,
        category: str | None = None,
        product: str | None = None,
    ) -> pd.DataFrame:
        """
        Get product velocity data with optional filters:
          - stage_filter: lifecycle stage string
          - period: 'Monthly' | 'Quarterly' | 'Yearly' — restricts the look-back window
            for the monthly dataset before re-computing summary stats
          - category: product_category string from df_individual_product_monthly
          - product: individual product_name from df_individual_product_monthly
        """
        self.ensure_product_lifecycle()

        # If category or product filter is set, operate on individual-product monthly data
        ind_df = getattr(self, "df_individual_product_monthly", None)
        if (category and category != "All") or (product and product != "All"):
            if ind_df is not None and not ind_df.empty:
                filtered_ind = ind_df.copy()
                if category and category != "All":
                    filtered_ind = filtered_ind[filtered_ind["product_category"] == category]
                if product and product != "All":
                    filtered_ind = filtered_ind[filtered_ind["product_name"] == product]

                # Apply period window
                if period:
                    cutoff = self._period_cutoff(filtered_ind, period)
                    if cutoff is not None:
                        filtered_ind = filtered_ind[filtered_ind["sale_month"] >= cutoff]

                if filtered_ind.empty:
                    return pd.DataFrame()

                # Re-compute a lightweight velocity summary for the filtered set
                return self._compute_velocity_for_df(filtered_ind)
        
        # Default: group-level velocity
        v = self.df_product_velocity
        if v is None or v.empty:
            return pd.DataFrame()

        # Apply period filter to group-level monthly data
        if period and period != "All":
            monthly = self.df_product_monthly
            if monthly is not None and not monthly.empty:
                cutoff = self._period_cutoff(monthly, period)
                if cutoff is not None:
                    monthly_filtered = monthly[monthly["sale_month"] >= cutoff]
                    if not monthly_filtered.empty:
                        # Keep only products that have data in the period
                        active_products = monthly_filtered["product_name"].unique()
                        v = v[v["product_name"].isin(active_products)]

        if stage_filter and stage_filter != "All":
            v = v[v["lifecycle_stage"] == stage_filter]
        return v

    @staticmethod
    def _period_cutoff(df: pd.DataFrame, period: str):
        """Return the earliest sale_month to include for the given period string."""
        if "sale_month" not in df.columns:
            return None
        max_month = pd.to_datetime(df["sale_month"]).max()
        if pd.isna(max_month):
            return None
        if period == "Monthly":
            return max_month - pd.DateOffset(months=1)
        if period == "Quarterly":
            return max_month - pd.DateOffset(months=3)
        if period == "Yearly":
            return max_month - pd.DateOffset(months=12)
        return None

    def _compute_velocity_for_df(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Lightweight velocity re-computation on an arbitrary monthly dataframe.
        Used when category/product filters redirect to individual-product data.
        """
        products = df["product_name"].unique()
        records = []

        for prod in products:
            sub = df[df["product_name"] == prod].sort_values("sale_month")
            if len(sub) < 2:
                continue

            avg_monthly = float(sub["monthly_revenue"].mean())
            total_revenue = float(sub["monthly_revenue"].sum())
            current_revenue = float(sub.iloc[-1]["monthly_revenue"])
            peak_revenue = float(sub["monthly_revenue"].max())
            peak_distance_pct = ((peak_revenue - current_revenue) / peak_revenue * 100) if peak_revenue > 0 else 0.0

            sub2 = sub.copy()
            sub2["month_idx"] = np.arange(len(sub2))

            try:
                coeffs = np.polyfit(sub2["month_idx"].values, sub2["monthly_revenue"].values, 1)
                slope = float(coeffs[0])
                slope_pct = (slope / avg_monthly * 100) if avg_monthly > 0 else 0.0
            except Exception:
                slope = 0.0
                slope_pct = 0.0

            recent_3 = sub2.tail(3)["monthly_revenue"].sum()
            prior_3 = sub2.iloc[-6:-3]["monthly_revenue"].sum() if len(sub2) >= 6 else sub2.head(max(1, len(sub2) - 3))["monthly_revenue"].sum()
            growth_3m = ((recent_3 - prior_3) / prior_3 * 100) if prior_3 > 0 else 0.0

            rev_std = float(sub["monthly_revenue"].std())
            cv = (rev_std / avg_monthly) if avg_monthly > 0 else 0.0

            try:
                buyer_coeffs = np.polyfit(sub2["month_idx"].values, sub2["monthly_buyer_count"].fillna(0).values, 1)
                buyer_trend = float(buyer_coeffs[0])
            except Exception:
                buyer_trend = 0.0

            velocity_score = (
                0.35 * np.clip(slope_pct / 10, -1, 1)
                + 0.30 * np.clip(growth_3m / 50, -1, 1)
                + 0.20 * np.clip(buyer_trend / 2, -1, 1)
            )

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

            latest_month = sub["sale_month"].max()
            peak_month = sub.loc[sub["monthly_revenue"].idxmax(), "sale_month"]
            months_since_peak = max(0, int((latest_month.year - peak_month.year) * 12 + (latest_month.month - peak_month.month)))

            row = {
                "product_name": prod,
                "total_revenue": round(total_revenue, 2),
                "avg_monthly_revenue": round(avg_monthly, 2),
                "total_months_active": len(sub),
                "slope_per_month": round(slope, 2),
                "slope_pct": round(slope_pct, 2),
                "growth_3m_pct": round(growth_3m, 2),
                "peak_revenue": round(peak_revenue, 2),
                "current_revenue": round(current_revenue, 2),
                "peak_distance_pct": round(peak_distance_pct, 2),
                "months_since_peak": months_since_peak,
                "buyer_trend": round(buyer_trend, 3),
                "revenue_cv": round(cv, 3),
                "velocity_score": round(velocity_score, 4),
                "lifecycle_stage": stage,
                "latest_month": latest_month,
            }
            # Include category / group if available
            if "product_category" in sub.columns:
                row["product_category"] = sub["product_category"].iloc[0]
            if "product_group" in sub.columns:
                row["product_group"] = sub["product_group"].iloc[0]
            records.append(row)

        result = pd.DataFrame(records)
        if not result.empty:
            result = result.sort_values("velocity_score", ascending=False).reset_index(drop=True)
        return result

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

    def get_product_trend(
        self,
        product_name: str,
        period: str | None = None,
        use_individual: bool = False,
    ) -> pd.DataFrame:
        """
        Get monthly revenue trend for a specific product.
        - use_individual=True → uses df_individual_product_monthly (individual SKU level)
        - period → restricts to Monthly / Quarterly / Yearly window
        """
        self.ensure_product_lifecycle()

        if use_individual:
            df = getattr(self, "df_individual_product_monthly", None)
        else:
            df = self.df_product_monthly

        if df is None or df.empty:
            return pd.DataFrame()

        result = df[df["product_name"] == product_name].sort_values("sale_month").copy()

        if period and period != "All" and not result.empty:
            cutoff = self._period_cutoff(result, period)
            if cutoff is not None:
                result = result[result["sale_month"] >= cutoff]

        return result
