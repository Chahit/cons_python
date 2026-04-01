import numpy as np


class RealtimeMixin:
    def _load_live_scores(self):
        try:
            return self.realtime_repo.fetch_live_scores()
        except Exception:
            return None

    def _apply_live_scores(self):
        if (
            self.df_partner_features is None
            or self.df_partner_features.empty
            or self.df_live_scores is None
            or self.df_live_scores.empty
        ):
            return
        cols = [
            "churn_probability",
            "churn_risk_band",
            "expected_revenue_at_risk_90d",
            "expected_revenue_at_risk_monthly",
            "forecast_next_30d",
            "forecast_trend_pct",
            "forecast_confidence",
            "credit_risk_score",
            "credit_risk_band",
            "credit_utilization",
            "overdue_ratio",
            "outstanding_amount",
            "credit_adjusted_risk_value",
        ]
        existing = [c for c in cols if c in self.df_live_scores.columns]
        if not existing:
            return
        self.df_partner_features = self.df_partner_features.join(
            self.df_live_scores[existing], how="left", rsuffix="_live"
        )
        for c in existing:
            lc = f"{c}_live"
            if lc in self.df_partner_features.columns:
                self.df_partner_features[c] = self.df_partner_features[lc].where(
                    self.df_partner_features[lc].notna(), self.df_partner_features.get(c, np.nan)
                )
                self.df_partner_features = self.df_partner_features.drop(columns=[lc])

    def queue_recompute_job(self, partner_name=None, reason="manual"):
        try:
            return self.realtime_repo.queue_job(partner_name=partner_name, reason=reason)
        except Exception:
            return None

    def queue_recompute_all(self, reason="manual_full"):
        self.ensure_clustering()
        names = self.matrix.index.tolist() if self.matrix is not None else []
        try:
            return self.realtime_repo.queue_all_missing(names, reason=reason)
        except Exception:
            return 0

    def get_realtime_status(self):
        try:
            return self.realtime_repo.get_queue_status()
        except Exception:
            return {
                "pending_jobs": 0,
                "running_jobs": 0,
                "failed_jobs": 0,
                "last_live_update": None,
                "scored_partners": 0,
            }
    def get_job_status(self, job_id):
        try:
            return self.realtime_repo.get_job_status(job_id)
        except Exception:
            return None
