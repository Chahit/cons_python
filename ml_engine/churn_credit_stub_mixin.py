"""
Churn & Credit lightweight implementation.

This replaces the removed ChurnCreditMixin with a self-contained, fast
implementation that does not require any new DB tables.

Churn is computed using rule-based scoring from revenue/recency/volatility
signals already in df_partner_features (loaded by BaseLoaderMixin).

Credit risk is computed using a simple overdue-ratio / transaction pattern
proxy — no additional tables required.
"""
import numpy as np
import pandas as pd


class ChurnCreditStubMixin:
    """
    Lightweight churn + credit scoring.
    All logic derives from columns already present in df_partner_features,
    so no extra DB calls are needed.
    """

    # ── Churn ────────────────────────────────────────────────────────────────

    def _build_churn_training_data(self) -> pd.DataFrame:
        """Return partner features ready for churn scoring (no ML model needed)."""
        pf = getattr(self, "df_partner_features", None)
        if pf is None or pf.empty:
            return pd.DataFrame()
        return pf.copy()

    def _train_churn_model(self):
        """No model to train — we use rule-based scoring."""
        self.churn_model = None
        self.churn_model_report = {
            "method": "rule_based",
            "features": ["revenue_drop_pct", "recency_days", "revenue_volatility",
                         "growth_rate_90d", "recent_txns"],
        }

    def _score_partner_churn_risk(self):
        """
        Assign churn probability and risk band to every partner using
        behavioural signals.  Score range: [0, 1].
        """
        pf = getattr(self, "df_partner_features", None)
        if pf is None or pf.empty:
            return

        df = pf.copy()

        # ── normalised signal sub-scores (each 0‒1, higher = more churn risk)
        # 1. Revenue drop magnitude
        rev_drop = df.get("revenue_drop_pct", pd.Series(0.0, index=df.index)).fillna(0).clip(0, 100) / 100.0

        # 2. Recency (days since last order) — 365 days = 1.0
        recency = df.get("recency_days", pd.Series(0.0, index=df.index)).fillna(0).clip(0, 365) / 365.0

        # 3. Revenue volatility (normalised by mean revenue to get CoV)
        revenue = df.get("recent_90_revenue", pd.Series(1.0, index=df.index)).replace(0, 1)
        vol = df.get("revenue_volatility", pd.Series(0.0, index=df.index)).fillna(0)
        cov = (vol / revenue).clip(0, 2) / 2.0

        # 4. Negative growth trend
        growth = df.get("growth_rate_90d", pd.Series(0.0, index=df.index)).fillna(0).clip(-1, 1)
        growth_risk = ((-growth + 1) / 2.0).clip(0, 1)   # 0 growth → 0.5, -1 → 1.0, +1 → 0.0

        # 5. Transaction frequency drop
        recent_txns = df.get("recent_txns", pd.Series(0.0, index=df.index)).fillna(0)
        prev_txns   = df.get("prev_txns",   pd.Series(0.0, index=df.index)).fillna(0)
        txn_drop = np.where(
            prev_txns > 0,
            ((prev_txns - recent_txns) / prev_txns).clip(0, 1),
            np.where(recent_txns == 0, 0.5, 0.0)
        )

        # Weighted composite
        churn_prob = (
            0.30 * rev_drop
            + 0.25 * recency
            + 0.15 * cov
            + 0.20 * growth_risk
            + 0.10 * txn_drop
        ).clip(0.0, 1.0)

        # Partners with zero recent revenue are high churn
        churned_mask = df.get("recent_90_revenue", pd.Series(0.0, index=df.index)).fillna(0) <= 0
        churn_prob = churn_prob.where(~churned_mask, other=0.85)

        pf["churn_probability"] = churn_prob.values

        # Risk band
        def _band(p):
            if p >= 0.70: return "High"
            if p >= 0.45: return "Medium"
            return "Low"

        pf["churn_risk_band"] = [_band(p) for p in pf["churn_probability"]]

        # Revenue at risk
        rev_90 = pf.get("recent_90_revenue", pd.Series(0.0, index=pf.index)).fillna(0)
        pf["expected_revenue_at_risk_90d"]      = (pf["churn_probability"] * rev_90).round(2)
        pf["expected_revenue_at_risk_monthly"]  = (pf["churn_probability"] * rev_90 / 3).round(2)

        self.df_partner_features = pf

    def _build_partner_forecast(self):
        """
        Simple linear-trend forecast using 90-day growth rate to project
        the next 30-day revenue.
        """
        pf = getattr(self, "df_partner_features", None)
        if pf is None or pf.empty:
            return

        rev_90  = pf.get("recent_90_revenue", pd.Series(0.0, index=pf.index)).fillna(0)
        growth  = pf.get("growth_rate_90d",   pd.Series(0.0, index=pf.index)).fillna(0).clip(-0.5, 1.0)

        # Monthly base × (1 + monthly_growth)
        monthly_base    = rev_90 / 3.0
        monthly_growth  = growth / 3.0          # quarterly growth → monthly equivalent
        forecast_30d    = (monthly_base * (1 + monthly_growth)).clip(lower=0)

        pf["forecast_next_30d"]     = forecast_30d.round(2)
        pf["forecast_trend_pct"]    = (monthly_growth * 100).round(2)
        pf["forecast_confidence"]   = np.where(
            pf.get("active_months", pd.Series(0, index=pf.index)).fillna(0) >= 6, 0.75, 0.45
        )
        self.df_partner_features = pf

    # ── Credit Risk ─────────────────────────────────────────────────────────

    def _load_credit_risk_features(self) -> pd.DataFrame:
        """
        Build credit-risk proxy features from transaction patterns.
        Uses recency/frequency/drop signals as proxies for payment risk.
        """
        pf = getattr(self, "df_partner_features", None)
        if pf is None or pf.empty:
            return pd.DataFrame()

        df = pf.copy().reset_index()
        if "company_name" not in df.columns and "index" in df.columns:
            df = df.rename(columns={"index": "company_name"})

        # Proxy signals
        rev_drop  = df.get("revenue_drop_pct",      pd.Series(0.0)).fillna(0).clip(0, 100) / 100.0
        recency   = df.get("recency_days",            pd.Series(0.0)).fillna(0).clip(0, 365) / 365.0
        vol       = df.get("revenue_volatility",      pd.Series(0.0)).fillna(0)
        revenue   = df.get("recent_90_revenue",       pd.Series(1.0)).replace(0, 1)
        cov       = (vol / revenue).clip(0, 2) / 2.0

        # Overdue proxy: high recency + high drop = likely payment issues
        overdue_proxy = ((recency + rev_drop) / 2).clip(0, 1)

        df["credit_risk_score"]      = (0.40 * rev_drop + 0.35 * recency + 0.25 * cov).clip(0, 1).round(4)
        df["overdue_ratio"]          = overdue_proxy.round(4)
        df["credit_utilization"]     = rev_drop.round(4)   # proxy: more drop = less utilisation
        df["outstanding_amount"]     = (
            df.get("recent_90_revenue", pd.Series(0.0)).fillna(0) * overdue_proxy
        ).round(2)
        df["credit_adjusted_risk_value"] = (
            df["credit_risk_score"] * df.get("recent_90_revenue", pd.Series(0.0)).fillna(0)
        ).round(2)

        return df

    def _score_credit_risk(self):
        """Apply credit risk scores back into df_partner_features."""
        credit_df = self._load_credit_risk_features()
        if credit_df.empty:
            return

        pf = getattr(self, "df_partner_features", None)
        if pf is None:
            return

        for col in ["credit_risk_score", "overdue_ratio", "credit_utilization",
                    "outstanding_amount", "credit_adjusted_risk_value"]:
            if col in credit_df.columns:
                # align by company_name index
                pf[col] = credit_df.set_index("company_name")[col].reindex(pf.index).values

        # Risk band
        def _band(s):
            if s >= 0.65: return "Critical"
            if s >= 0.45: return "High"
            if s >= 0.25: return "Medium"
            return "Low"

        pf["credit_risk_band"] = [_band(s) for s in pf["credit_risk_score"].fillna(0)]
        self.df_partner_features = pf
        self.credit_risk_report = {"method": "rule_based_proxy"}

    # ── SHAP Explainability (rule-based replacement) ──────────────────────────

    def explain_partner_churn(self, partner_name: str) -> dict:
        """
        Return churn feature importances for a single partner.
        Uses rule-based signal decomposition instead of SHAP trees
        (the ML churn model tab was removed).
        """
        pf = getattr(self, "df_partner_features", None)
        if pf is None or pf.empty:
            return {"status": "unavailable", "reason": "Partner features not loaded yet."}

        # Try to locate this partner
        idx = None
        pf_reset = pf.reset_index()
        name_col = "company_name" if "company_name" in pf_reset.columns else pf_reset.columns[0]
        matches = pf_reset[pf_reset[name_col].astype(str).str.lower() == partner_name.lower()]
        if matches.empty:
            # fuzzy fallback — starts-with
            matches = pf_reset[pf_reset[name_col].astype(str).str.lower().str.startswith(partner_name.lower()[:5])]
        if matches.empty:
            return {"status": "unavailable", "reason": f"No data found for '{partner_name}'."}

        row = matches.iloc[0]

        # Compute individual sub-scores (mirror _score_partner_churn_risk weights)
        rev_drop    = float(pd.to_numeric(row.get("revenue_drop_pct", 0), errors="coerce") or 0)
        recency     = float(pd.to_numeric(row.get("recency_days", 0), errors="coerce") or 0)
        volatility  = float(pd.to_numeric(row.get("revenue_volatility", 0), errors="coerce") or 0)
        revenue     = max(float(pd.to_numeric(row.get("recent_90_revenue", 1), errors="coerce") or 1), 1)
        growth      = float(pd.to_numeric(row.get("growth_rate_90d", 0), errors="coerce") or 0)
        recent_txns = float(pd.to_numeric(row.get("recent_txns", 0), errors="coerce") or 0)
        prev_txns   = float(pd.to_numeric(row.get("prev_txns", 0), errors="coerce") or 0)

        # Normalised contributions (matching the weighted formula)
        s_revenue_drop  = 0.30 * min(rev_drop / 100.0, 1.0)
        s_recency       = 0.25 * min(recency / 365.0, 1.0)
        s_volatility    = 0.15 * min((volatility / revenue) / 2.0, 1.0)
        s_growth        = 0.20 * max(0.0, (-growth + 1) / 2.0)
        s_txn_drop      = 0.10 * (max(0, (prev_txns - recent_txns) / max(prev_txns, 1)) if prev_txns > 0 else 0.5)

        churn_prob = float(row.get("churn_probability", s_revenue_drop + s_recency + s_volatility + s_growth + s_txn_drop))

        shap_values = {
            "Revenue Drop %":        round(s_revenue_drop, 4),
            "Days Since Last Order":  round(s_recency, 4),
            "Revenue Volatility":    round(s_volatility, 4),
            "Negative Growth Rate":  round(s_growth, 4),
            "Transaction Frequency": round(s_txn_drop, 4),
        }

        return {
            "status": "ok",
            "method": "rule_based",
            "partner_name": partner_name,
            "churn_probability": round(churn_prob, 4),
            "churn_risk_band": row.get("churn_risk_band", "Unknown"),
            "shap_values": shap_values,
            "feature_names": list(shap_values.keys()),
            "shap_array": list(shap_values.values()),
            "base_value": 0.0,
        }

    def predict_partner_survival(self, partner_name: str) -> dict:
        """
        Return a simplified survival probability curve for a partner.
        Based on churn probability — a partner with P(churn)=0.4 has a
        ~60% survival rate at 90 days, ~36% at 180 days (geometric decay).
        """
        pf = getattr(self, "df_partner_features", None)
        if pf is None or pf.empty:
            return {"status": "unavailable", "reason": "Partner features not loaded yet."}

        pf_reset = pf.reset_index()
        name_col = "company_name" if "company_name" in pf_reset.columns else pf_reset.columns[0]
        matches = pf_reset[pf_reset[name_col].astype(str).str.lower() == partner_name.lower()]
        if matches.empty:
            return {"status": "unavailable", "reason": f"No data found for '{partner_name}'."}

        row = matches.iloc[0]
        churn_p = float(pd.to_numeric(row.get("churn_probability", 0.3), errors="coerce") or 0.3)
        monthly_survival = 1.0 - (churn_p / 3.0)   # annualised quarter → monthly
        monthly_survival = max(0.05, min(monthly_survival, 0.999))

        times = list(range(0, 25))   # months 0-24
        survival_probs = [round(monthly_survival ** t, 4) for t in times]

        return {
            "status": "ok",
            "method": "geometric_decay",
            "partner_name": partner_name,
            "churn_probability": round(churn_p, 4),
            "median_survival_months": next(
                (t for t, s in zip(times, survival_probs) if s <= 0.5), 24
            ),
            "times": times,
            "survival_probs": survival_probs,
        }

    # ───────────────────────────────────────────────────────────────────────
    # Isotonic Score Calibration  (PAVA — numpy only, no labels required)
    # ───────────────────────────────────────────────────────────────────────

    @staticmethod
    def _isotonic_calibrate(scores):
        """
        Pool Adjacent Violators Algorithm (PAVA) applied to a score Series.

        Since no ground-truth churn labels exist, the empirical rank-sorted
        distribution is used as the training signal.  The output:
          1. Preserves rank order (monotone)
          2. Smooths histogram clustering / removes score pile-ups
          3. Clips output to [0, 1]
        """
        import numpy as np
        import pandas as pd

        s = scores.copy().fillna(0.0).astype(float)
        if s.empty or s.std() < 1e-9:
            return s.clip(0.0, 1.0)

        values = s.values
        order = np.argsort(values)
        sorted_vals = values[order].copy().astype(float)

        n = len(sorted_vals)
        blocks = []  # each entry: [start, end, mean]
        for i in range(n):
            blocks.append([i, i, float(sorted_vals[i])])
            while len(blocks) >= 2:
                s1, s2 = blocks[-2], blocks[-1]
                if s1[2] <= s2[2]:
                    break
                w1 = float(s1[1] - s1[0] + 1)
                w2 = float(s2[1] - s2[0] + 1)
                merged = (s1[2] * w1 + s2[2] * w2) / (w1 + w2)
                blocks.pop(); blocks.pop()
                blocks.append([s1[0], s2[1], merged])

        calibrated = np.empty(n)
        for blk in blocks:
            calibrated[blk[0]: blk[1] + 1] = blk[2]

        result = np.empty(n)
        result[order] = calibrated
        return pd.Series(np.clip(result, 0.0, 1.0), index=s.index)

    def calibrate_churn_scores(self):
        """Calibrate churn_probability; backs up raw to churn_probability_raw."""
        pf = getattr(self, "df_partner_features", None)
        if pf is None or pf.empty or "churn_probability" not in pf.columns:
            return {"status": "skipped", "reason": "df_partner_features not ready."}
        raw = pf["churn_probability"].copy()
        pf["churn_probability_raw"] = raw
        pf["churn_probability"] = self._isotonic_calibrate(raw)
        self.df_partner_features = pf
        return {
            "status": "ok", "method": "isotonic_pava",
            "n_partners": int(len(pf)),
            "mean_before": round(float(raw.mean()), 4),
            "mean_after":  round(float(pf["churn_probability"].mean()), 4),
            "std_before":  round(float(raw.std()), 4),
            "std_after":   round(float(pf["churn_probability"].std()), 4),
        }

    def calibrate_credit_scores(self):
        """Calibrate credit_risk_score; backs up raw to credit_risk_score_raw."""
        pf = getattr(self, "df_partner_features", None)
        if pf is None or pf.empty or "credit_risk_score" not in pf.columns:
            return {"status": "skipped", "reason": "df_partner_features not ready."}
        raw = pf["credit_risk_score"].copy()
        pf["credit_risk_score_raw"] = raw
        pf["credit_risk_score"] = self._isotonic_calibrate(raw)
        self.df_partner_features = pf
        return {
            "status": "ok", "method": "isotonic_pava",
            "n_partners": int(len(pf)),
            "mean_before": round(float(raw.mean()), 4),
            "mean_after":  round(float(pf["credit_risk_score"].mean()), 4),
            "std_before":  round(float(raw.std()), 4),
            "std_after":   round(float(pf["credit_risk_score"].std()), 4),
        }

    def calibrate_all_scores(self):
        """Calibrate both churn and credit scores; return combined report."""
        return {
            "churn":  self.calibrate_churn_scores(),
            "credit": self.calibrate_credit_scores(),
        }
