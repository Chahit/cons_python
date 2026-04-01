import numpy as np
import pandas as pd
from .schemas import MonitoringSnapshot

class MonitoringMixin:
    @staticmethod
    def _to_float(value, default=0.0):
        try:
            return float(value)
        except Exception:
            return float(default)

    @staticmethod
    def _bucket_priority(exposure_score):
        score = float(exposure_score)
        if score >= 80.0:
            return "Critical", "Immediate Action"
        if score >= 60.0:
            return "High", "Plan Sales"
        if score >= 35.0:
            return "Medium", "Monitor Weekly"
        return "Low", "Monitor Monthly"

    def run_degrowth_backtest(self, months=9, min_drop_pct=None):
        """
        Evaluate degrowth rule against next-window realized decline.
        Returns precision/recall-style diagnostics.
        """
        if min_drop_pct is None:
            min_drop_pct = 20.0

        query = """
        SELECT
            t.party_id,
            t.date::date AS tx_date,
            SUM(tp.net_amt) AS revenue
        FROM transactions_dsr t
        JOIN transactions_dsr_products tp ON t.id = tp.dsr_id
        WHERE {approved}
        GROUP BY t.party_id, t.date::date
        """.format(approved=self._approved_condition("t"))
        try:
            tx = pd.read_sql(query, self.engine)
        except Exception:
            self.last_backtest = {"status": "failed", "reason": "Unable to load transaction history."}
            return self.last_backtest

        if tx.empty:
            self.last_backtest = {"status": "failed", "reason": "No transaction data."}
            return self.last_backtest

        tx["tx_date"] = pd.to_datetime(tx["tx_date"])
        anchors = pd.date_range(
            tx["tx_date"].max() - pd.DateOffset(months=months),
            tx["tx_date"].max() - pd.DateOffset(months=1),
            freq="MS",
        )
        rows = []
        for anchor in anchors:
            prev_start = anchor - pd.Timedelta(days=180)
            prev_end = anchor - pd.Timedelta(days=90)
            curr_start = anchor - pd.Timedelta(days=90)
            curr_end = anchor
            next_end = anchor + pd.Timedelta(days=90)

            prev = tx[(tx["tx_date"] >= prev_start) & (tx["tx_date"] < prev_end)].groupby("party_id")["revenue"].sum()
            curr = tx[(tx["tx_date"] >= curr_start) & (tx["tx_date"] < curr_end)].groupby("party_id")["revenue"].sum()
            nxt = tx[(tx["tx_date"] >= curr_end) & (tx["tx_date"] < next_end)].groupby("party_id")["revenue"].sum()

            joined = pd.DataFrame({"prev": prev, "curr": curr, "next": nxt}).fillna(0.0)
            if joined.empty:
                continue
            joined["drop_pct"] = np.where(
                joined["prev"] > 0,
                (joined["prev"] - joined["curr"]).clip(lower=0) / joined["prev"] * 100.0,
                0.0,
            )
            joined["pred_flag"] = joined["drop_pct"] >= float(min_drop_pct)
            joined["actual_flag"] = joined["next"] < joined["curr"]
            rows.append(joined[["pred_flag", "actual_flag"]])

        if not rows:
            self.last_backtest = {"status": "failed", "reason": "Insufficient windows for backtest."}
            return self.last_backtest

        eval_df = pd.concat(rows, axis=0)
        tp = int(((eval_df["pred_flag"]) & (eval_df["actual_flag"])).sum())
        fp = int(((eval_df["pred_flag"]) & (~eval_df["actual_flag"])).sum())
        fn = int(((~eval_df["pred_flag"]) & (eval_df["actual_flag"])).sum())
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0

        self.last_backtest = {
            "status": "ok",
            "threshold_drop_pct": float(min_drop_pct),
            "samples": int(len(eval_df)),
            "precision": round(float(precision), 4),
            "recall": round(float(recall), 4),
            "tp": tp,
            "fp": fp,
            "fn": fn,
        }
        return self.last_backtest

    def get_data_quality_report(self):
        return dict(self.data_quality_report) if self.data_quality_report else {}

    def get_backtest_report(self):
        return dict(self.last_backtest) if self.last_backtest else {}

    def get_churn_model_report(self):
        return dict(self.churn_model_report) if self.churn_model_report else {}

    def get_credit_risk_report(self):
        return dict(self.credit_risk_report) if self.credit_risk_report else {}

    def get_monitoring_snapshot(self):
        self.ensure_clustering()
        if self.enable_realtime_partner_scoring:
            self.ensure_churn_forecast()
            self.ensure_credit_risk()
        snapshot = MonitoringSnapshot(
            data_quality_status=self.data_quality_report.get("status", "unknown")
        )
        if self.matrix is not None and not self.matrix.empty:
            snapshot.partner_count = int(len(self.matrix))
            if "cluster_label" in self.matrix.columns:
                snapshot.cluster_count = int(
                    self.matrix["cluster_label"]
                    .astype(str)
                    .loc[~self.matrix["cluster_label"].astype(str).str.contains("Outlier", case=False, na=False)]
                    .nunique()
                )
                snapshot.outlier_count = int(
                    self.matrix["cluster_label"]
                    .astype(str)
                    .str.contains("Outlier", case=False, na=False)
                    .sum()
                )
        if self.df_partner_features is not None and not self.df_partner_features.empty:
            snapshot.avg_health_score = round(
                float(self.df_partner_features["health_score"].mean()), 4
            )
            if "churn_probability" in self.df_partner_features.columns:
                snapshot.avg_churn_probability = round(
                    float(self.df_partner_features["churn_probability"].mean()), 4
                )
            if "credit_risk_score" in self.df_partner_features.columns:
                snapshot.avg_credit_risk_score = round(
                    float(self.df_partner_features["credit_risk_score"].mean()), 4
                )
            if "credit_risk_band" in self.df_partner_features.columns:
                snapshot.high_credit_risk_partners = int(
                    (self.df_partner_features["credit_risk_band"] == "High").sum()
                )
        return snapshot.to_dict()

    def get_alert_snapshot(self, limit=100):
        self.ensure_clustering()
        if self.enable_realtime_partner_scoring:
            self.ensure_churn_forecast()
            self.ensure_credit_risk()

        if self.df_partner_features is None or self.df_partner_features.empty:
            return {"status": "failed", "reason": "Partner features unavailable."}

        df = self.df_partner_features.copy()
        if "company_name" not in df.columns:
            df = df.reset_index().rename(columns={"index": "company_name"})
        if "company_name" not in df.columns:
            return {"status": "failed", "reason": "Missing company_name in partner features."}

        for col, default in [
            ("revenue_drop_pct", 0.0),
            ("degrowth_threshold_pct", 20.0),
            ("churn_probability", 0.0),
            ("credit_risk_score", 0.0),
        ]:
            if col not in df.columns:
                df[col] = default
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(default)

        live_cols = pd.DataFrame(columns=["company_name", "live_churn_probability", "live_credit_risk_score"])
        if self.df_live_scores is not None and not self.df_live_scores.empty:
            live_cols = (
                self.df_live_scores.reset_index()
                .rename(
                    columns={
                        "partner_name": "company_name",
                        "churn_probability": "live_churn_probability",
                        "credit_risk_score": "live_credit_risk_score",
                    }
                )[
                    [
                        "company_name",
                        "live_churn_probability",
                        "live_credit_risk_score",
                    ]
                ]
            )
        df = df.merge(live_cols, on="company_name", how="left")
        df["live_churn_probability"] = pd.to_numeric(
            df.get("live_churn_probability", np.nan), errors="coerce"
        )
        df["live_credit_risk_score"] = pd.to_numeric(
            df.get("live_credit_risk_score", np.nan), errors="coerce"
        )

        sharp_drop = float(getattr(self, "alert_revenue_drop_sharp_pct", 35.0))
        churn_jump = float(getattr(self, "alert_churn_jump_delta", 0.15))
        churn_high = float(getattr(self, "alert_churn_high_level", 0.45))
        credit_jump = float(getattr(self, "alert_credit_jump_delta", 0.15))
        credit_high = float(getattr(self, "alert_credit_high_level", 0.55))

        rev_threshold = np.maximum(df["degrowth_threshold_pct"].values, sharp_drop)
        df["alert_sharp_revenue_drop"] = df["revenue_drop_pct"].values >= rev_threshold
        df["churn_delta"] = df["churn_probability"] - df["live_churn_probability"]
        df["alert_high_churn_jump"] = (
            df["live_churn_probability"].notna()
            & (df["churn_delta"] >= churn_jump)
            & (df["churn_probability"] >= churn_high)
        )
        df["credit_delta"] = df["credit_risk_score"] - df["live_credit_risk_score"]
        df["alert_high_credit_risk_jump"] = (
            df["live_credit_risk_score"].notna()
            & (df["credit_delta"] >= credit_jump)
            & (df["credit_risk_score"] >= credit_high)
        )

        df["active_alerts"] = (
            df["alert_sharp_revenue_drop"].astype(int)
            + df["alert_high_churn_jump"].astype(int)
            + df["alert_high_credit_risk_jump"].astype(int)
        )
        df["alert_severity_score"] = (
            3 * df["alert_sharp_revenue_drop"].astype(int)
            + 2 * df["alert_high_churn_jump"].astype(int)
            + 2 * df["alert_high_credit_risk_jump"].astype(int)
        )

        flagged = df[df["active_alerts"] > 0].copy()
        if flagged.empty:
            return {
                "status": "ok",
                "summary": {
                    "partners_with_alerts": 0,
                    "sharp_revenue_drop_count": 0,
                    "high_churn_jump_count": 0,
                    "high_credit_risk_jump_count": 0,
                },
                "rows": [],
            }

        def _rule_text(r):
            rules = []
            if bool(r["alert_sharp_revenue_drop"]):
                rules.append("Sharp Revenue Drop")
            if bool(r["alert_high_churn_jump"]):
                rules.append("High Churn Jump")
            if bool(r["alert_high_credit_risk_jump"]):
                rules.append("High Credit Risk Jump")
            return " | ".join(rules)

        flagged["triggered_rules"] = flagged.apply(_rule_text, axis=1)
        flagged = flagged.sort_values(
            by=["alert_severity_score", "active_alerts", "revenue_drop_pct", "churn_probability"],
            ascending=[False, False, False, False],
        )
        cols = [
            "company_name",
            "triggered_rules",
            "revenue_drop_pct",
            "churn_probability",
            "churn_delta",
            "credit_risk_score",
            "credit_delta",
            "active_alerts",
        ]
        for c in cols:
            if c not in flagged.columns:
                flagged[c] = np.nan

        out = flagged[cols].head(max(1, int(limit))).copy()
        return {
            "status": "ok",
            "summary": {
                "partners_with_alerts": int(len(flagged)),
                "sharp_revenue_drop_count": int(df["alert_sharp_revenue_drop"].sum()),
                "high_churn_jump_count": int(df["alert_high_churn_jump"].sum()),
                "high_credit_risk_jump_count": int(df["alert_high_credit_risk_jump"].sum()),
            },
            "rows": out.to_dict(orient="records"),
        }

    def get_dead_stock(self):
        if self.df_dead_stock is None:
            self.df_dead_stock = self.repo.fetch_view_stock_liquidation_leads()
        return self.df_dead_stock.copy()

    def get_stock_details(self, product_name):
        if self.df_stock_stats is None or self.df_stock_stats.empty:
            return None
        row = self.df_stock_stats[self.df_stock_stats["product_name"] == product_name]
        if row.empty:
            return None

        selected = row.iloc[0]
        max_age_days = max(0.0, self._to_float(selected.get("max_age_days", 0.0), 0.0))
        total_stock_qty = max(0.0, self._to_float(selected.get("total_stock_qty", 0.0), 0.0))

        age_series = pd.to_numeric(
            self.df_stock_stats.get("max_age_days", pd.Series(dtype=float)),
            errors="coerce",
        ).dropna()
        if age_series.empty:
            age_percentile = 50.0
        else:
            age_percentile = float((age_series <= max_age_days).mean() * 100.0)

        demand_recency_days = np.nan
        if self.df_dead_stock is not None and not self.df_dead_stock.empty:
            if {"dead_stock_item", "last_purchase_date"}.issubset(self.df_dead_stock.columns):
                leads = self.df_dead_stock[
                    self.df_dead_stock["dead_stock_item"].astype(str) == str(product_name)
                ]
                if not leads.empty:
                    last_dates = pd.to_datetime(leads["last_purchase_date"], errors="coerce").dropna()
                    if not last_dates.empty:
                        anchor = pd.Timestamp.now().normalize()
                        demand_recency_days = float(max(0, (anchor - last_dates.max().normalize()).days))

        # Composite stock-age pressure score:
        # - absolute max age
        # - relative position in portfolio
        # - inventory volume pressure
        # - buyer inactivity recency when available
        age_component = min(max_age_days / 180.0, 1.0) * 55.0
        percentile_component = min(max(age_percentile, 0.0), 100.0) / 100.0 * 20.0
        qty_component = min(total_stock_qty / 100.0, 1.0) * 15.0
        recency_component = (
            min(demand_recency_days / 180.0, 1.0) * 10.0
            if pd.notna(demand_recency_days)
            else 0.0
        )
        stock_exposure_score = float(age_component + percentile_component + qty_component + recency_component)
        priority, priority_delta = self._bucket_priority(stock_exposure_score)

        effective_age_days = max_age_days
        if pd.notna(demand_recency_days):
            effective_age_days = max(max_age_days, demand_recency_days)

        return {
            "product_name": selected.get("product_name", product_name),
            "total_stock_qty": int(round(total_stock_qty)),
            "max_age_days": int(round(max_age_days)),
            "effective_age_days": int(round(effective_age_days)),
            "age_percentile": round(float(age_percentile), 1),
            "demand_recency_days": (
                int(round(float(demand_recency_days)))
                if pd.notna(demand_recency_days)
                else None
            ),
            "stock_exposure_score": round(float(stock_exposure_score), 1),
            "priority": priority,
            "priority_delta": priority_delta,
        }
