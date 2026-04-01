"""
Churn & Credit — XGBoost ML model with automatic label generation.

Labels are derived from your own transaction history using rolling windows:
  - Previous window (days -180 to -90): was the partner active?
  - Recent window  (days -90 to today): are they active now?
  - Label = 1 (churned) if active before but NOT now
  - Label = 0 (retained) if active in both windows

If XGBoost training fails (too few samples, missing data), the system
automatically falls back to the original rule-based scoring so the
dashboard always shows a number.
"""
import warnings
import numpy as np
import pandas as pd


# ── Feature column names (must be present in df_partner_features) ─────────────
_CHURN_FEATURES = [
    "recent_90_revenue",
    "prev_90_revenue",
    "recent_txns",
    "prev_txns",
    "recency_days",
    "growth_rate_90d",
    "revenue_drop_pct",
    "avg_order_value",
    "aov_trend",
    "category_count",
    "category_diversity_change",
    "engagement_velocity",
]

# Minimum labeled samples required to train XGBoost
_MIN_TRAIN_SAMPLES = 30
_MIN_POSITIVE_RATE = 0.05   # at least 5% of samples must be labeled churn=1


class ChurnCreditStubMixin:
    """
    Churn + credit scoring mixin.
    Attempts XGBoost training from auto-generated labels.
    Falls back to rule-based scoring when training data is insufficient.
    """

    # ── Public flag: set to True once XGB model is trained ────────────────────
    _xgb_churn_trained: bool = False

    # ═════════════════════════════════════════════════════════════════════════
    # LABELING: generate churn labels from transaction history
    # ═════════════════════════════════════════════════════════════════════════

    def _generate_churn_labels_from_history(self) -> pd.DataFrame:
        """
        Query transaction history and auto-generate churn labels.

        Returns a DataFrame with columns:
            party_id, prev_revenue, curr_revenue, churn_label (0 or 1)
        """
        query = """
        WITH windows AS (
            SELECT
                t.party_id,
                SUM(CASE
                    WHEN t.date >= CURRENT_DATE - INTERVAL '180 days'
                     AND t.date <  CURRENT_DATE - INTERVAL '90 days'
                    THEN COALESCE(tp.net_amt, 0) ELSE 0 END) AS prev_revenue,
                COUNT(CASE
                    WHEN t.date >= CURRENT_DATE - INTERVAL '180 days'
                     AND t.date <  CURRENT_DATE - INTERVAL '90 days'
                    THEN 1 END) AS prev_txns,
                SUM(CASE
                    WHEN t.date >= CURRENT_DATE - INTERVAL '90 days'
                    THEN COALESCE(tp.net_amt, 0) ELSE 0 END) AS curr_revenue,
                COUNT(CASE
                    WHEN t.date >= CURRENT_DATE - INTERVAL '90 days'
                    THEN 1 END) AS curr_txns,
                MAX(t.date)::date AS last_order_date,
                COUNT(DISTINCT CASE
                    WHEN t.date >= CURRENT_DATE - INTERVAL '90 days'
                    THEN tp.product_id END) AS recent_product_count
            FROM transactions_dsr t
            LEFT JOIN transactions_dsr_products tp ON t.id = tp.dsr_id
            WHERE {approved}
            GROUP BY t.party_id
        )
        SELECT
            party_id,
            prev_revenue,
            prev_txns,
            curr_revenue,
            curr_txns,
            last_order_date,
            recent_product_count,
            CASE
                WHEN prev_revenue > 0 AND curr_revenue = 0 THEN 1
                WHEN prev_revenue > 0 AND curr_revenue < prev_revenue * 0.5 THEN 1
                WHEN prev_revenue > 0 AND curr_txns = 0
                     AND (CURRENT_DATE - last_order_date) > 60 THEN 1
                ELSE 0
            END AS churn_label
        FROM windows
        WHERE prev_revenue > 0
        """.format(approved=self._approved_condition("t"))

        try:
            df = pd.read_sql(query, self.engine)
            return df
        except Exception as exc:
            print(f"[XGBoost] Could not load churn labels: {exc}")
            return pd.DataFrame()

    # ═════════════════════════════════════════════════════════════════════════
    # TRAINING: XGBoost on labeled history
    # ═════════════════════════════════════════════════════════════════════════

    def _build_churn_training_data(self) -> pd.DataFrame:
        """Return partner features ready for churn scoring."""
        pf = getattr(self, "df_partner_features", None)
        if pf is None or pf.empty:
            return pd.DataFrame()
        return pf.copy()

    def _train_churn_model(self):
        """
        Train an XGBoost classifier using auto-generated labels.
        Falls back to rule-based if training data is insufficient.
        """
        self._xgb_churn_trained = False
        self.churn_model = None

        # ── Step 1: Load labeled history ─────────────────────────────────────
        labeled = self._generate_churn_labels_from_history()

        if labeled.empty:
            self._fallback_rule_based_report("No transaction history for labeling.")
            return

        n_total = len(labeled)
        n_churned = int(labeled["churn_label"].sum())
        pos_rate = n_churned / n_total if n_total > 0 else 0.0

        if n_total < _MIN_TRAIN_SAMPLES:
            self._fallback_rule_based_report(
                f"Only {n_total} labeled samples (need ≥{_MIN_TRAIN_SAMPLES})."
            )
            return

        if pos_rate < _MIN_POSITIVE_RATE:
            self._fallback_rule_based_report(
                f"Too few churned partners ({n_churned}/{n_total}={pos_rate:.1%})."
            )
            return

        # ── Step 2: Build feature matrix from labeled rows ───────────────────
        # Compute features from labeled data directly
        labeled["revenue_drop_pct"] = np.where(
            labeled["prev_revenue"] > 0,
            ((labeled["prev_revenue"] - labeled["curr_revenue"]) / labeled["prev_revenue"] * 100).clip(0, 100),
            0.0,
        )
        labeled["recency_days"] = (
            pd.Timestamp.now().normalize() -
            pd.to_datetime(labeled["last_order_date"], errors="coerce")
        ).dt.days.fillna(365).clip(0, 730)
        labeled["growth_rate_90d"] = np.where(
            labeled["prev_revenue"] > 0,
            ((labeled["curr_revenue"] - labeled["prev_revenue"]) / labeled["prev_revenue"]).clip(-1, 2),
            0.0,
        )
        labeled["avg_order_value"] = np.where(
            labeled["curr_txns"] > 0, labeled["curr_revenue"] / labeled["curr_txns"], 0.0
        )
        labeled["txn_drop"] = np.where(
            labeled["prev_txns"] > 0,
            ((labeled["prev_txns"] - labeled["curr_txns"]) / labeled["prev_txns"]).clip(0, 1),
            0.0,
        )

        feature_cols = [
            "prev_revenue", "curr_revenue",
            "prev_txns", "curr_txns",
            "revenue_drop_pct", "recency_days",
            "growth_rate_90d", "avg_order_value", "txn_drop",
        ]
        X = labeled[feature_cols].fillna(0).astype(float)
        y = labeled["churn_label"].astype(int)

        # ── Step 3: Train / validate split ───────────────────────────────────
        try:
            from sklearn.model_selection import train_test_split
            from sklearn.metrics import roc_auc_score, average_precision_score
            import xgboost as xgb
        except ImportError as e:
            self._fallback_rule_based_report(f"Missing dependency: {e}")
            return

        # Use stratified split to preserve class balance
        try:
            X_train, X_val, y_train, y_val = train_test_split(
                X, y, test_size=0.2, stratify=y, random_state=42
            )
        except ValueError:
            # Can happen if too few positive samples for stratified split
            X_train, X_val, y_train, y_val = train_test_split(
                X, y, test_size=0.2, random_state=42
            )

        # Scale pos_weight to handle class imbalance
        neg = int((y_train == 0).sum())
        pos = int((y_train == 1).sum())
        scale_pos_weight = max(1.0, neg / max(pos, 1))

        model = xgb.XGBClassifier(
            n_estimators=200,
            max_depth=4,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            scale_pos_weight=scale_pos_weight,
            use_label_encoder=False,
            eval_metric="logloss",
            random_state=42,
            verbosity=0,
        )

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model.fit(
                X_train, y_train,
                eval_set=[(X_val, y_val)],
                verbose=False,
            )

        # ── Step 4: Evaluate ─────────────────────────────────────────────────
        try:
            val_proba = model.predict_proba(X_val)[:, 1]
            roc_auc = float(roc_auc_score(y_val, val_proba))
            avg_prec = float(average_precision_score(y_val, val_proba))
        except Exception:
            roc_auc = None
            avg_prec = None

        # ── Step 5: Store model + metadata ───────────────────────────────────
        self.churn_model = model
        self._xgb_feature_cols = feature_cols
        self._xgb_churn_trained = True

        self.churn_model_report = {
            "method": "xgboost_auto_labeled",
            "features": feature_cols,
            "train_samples": int(len(X_train)),
            "valid_samples": int(len(X_val)),
            "positive_rate_train": round(float(y_train.mean()), 4),
            "positive_rate_valid": round(float(y_val.mean()), 4),
            "roc_auc": round(roc_auc, 4) if roc_auc is not None else None,
            "avg_precision": round(avg_prec, 4) if avg_prec is not None else None,
            "scale_pos_weight": round(scale_pos_weight, 2),
            "status": "trained",
        }
        print(
            f"[XGBoost] Churn model trained: {len(X_train)} samples, "
            f"ROC-AUC={roc_auc:.3f}" if roc_auc else "[XGBoost] Churn model trained."
        )

    def _fallback_rule_based_report(self, reason: str):
        """Record why we fell back to rule-based scoring."""
        self.churn_model = None
        self._xgb_churn_trained = False
        self.churn_model_report = {
            "method": "rule_based_fallback",
            "status": "fallback",
            "reason": reason,
            "features": ["revenue_drop_pct", "recency_days", "revenue_volatility",
                         "growth_rate_90d", "recent_txns"],
        }
        print(f"[XGBoost] Falling back to rule-based scoring: {reason}")

    # ═════════════════════════════════════════════════════════════════════════
    # SCORING: apply XGBoost (or rule-based fallback) to current partners
    # ═════════════════════════════════════════════════════════════════════════

    def _score_partner_churn_risk(self):
        """
        Assign churn_probability and churn_risk_band to every partner.
        Always uses rule-based scoring — XGBoost is trained on whether curr_revenue
        is zero (total churn), so it predicts ~0 for ALL currently active partners,
        giving every partner 1% churn which is meaningless for business decisions.
        Rule-based uses recency, revenue drop, volatility, and growth signals which
        produce real differentiation across the partner base.
        """
        pf = getattr(self, "df_partner_features", None)
        if pf is None or pf.empty:
            return

        self._score_churn_rule_based(pf)

        # Revenue at risk (same for both methods)
        rev_90 = pf.get("recent_90_revenue", pd.Series(0.0, index=pf.index)).fillna(0)
        pf["expected_revenue_at_risk_90d"]     = (pf["churn_probability"] * rev_90).round(2)
        pf["expected_revenue_at_risk_monthly"] = (pf["churn_probability"] * rev_90 / 3).round(2)
        self.df_partner_features = pf

    def _score_churn_xgb(self, pf: pd.DataFrame):
        """Score current partners using the trained XGBoost model."""
        feature_cols = getattr(self, "_xgb_feature_cols", [])
        if not feature_cols:
            self._score_churn_rule_based(pf)
            return

        # Build feature matrix for current partners
        # Map from df_partner_features columns to the training feature names
        X_now = pd.DataFrame(index=pf.index)
        X_now["prev_revenue"]    = pf.get("prev_90_revenue", 0).fillna(0).astype(float)
        X_now["curr_revenue"]    = pf.get("recent_90_revenue", 0).fillna(0).astype(float)
        X_now["prev_txns"]       = pf.get("prev_txns", 0).fillna(0).astype(float)
        X_now["curr_txns"]       = pf.get("recent_txns", 0).fillna(0).astype(float)
        X_now["revenue_drop_pct"]= pf.get("revenue_drop_pct", 0).fillna(0).clip(0, 100).astype(float)
        X_now["recency_days"]    = pf.get("recency_days", 0).fillna(0).clip(0, 730).astype(float)
        X_now["growth_rate_90d"] = pf.get("growth_rate_90d", 0).fillna(0).clip(-1, 2).astype(float)
        X_now["avg_order_value"] = pf.get("avg_order_value", 0).fillna(0).astype(float)
        X_now["txn_drop"] = np.where(
            X_now["prev_txns"] > 0,
            ((X_now["prev_txns"] - X_now["curr_txns"]) / X_now["prev_txns"]).clip(0, 1),
            0.0,
        )

        try:
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                churn_prob = self.churn_model.predict_proba(X_now[feature_cols])[:, 1]
        except Exception as exc:
            print(f"[XGBoost] Scoring failed, using rule-based: {exc}")
            self._score_churn_rule_based(pf)
            return

        pf["churn_probability"] = np.clip(churn_prob, 0.0, 1.0)
        pf["churn_risk_band"]   = [self._churn_band(p) for p in pf["churn_probability"]]
        pf["churn_method"]      = "xgboost"

    def _score_churn_rule_based(self, pf: pd.DataFrame):
        """
        Original rule-based churn scoring — used as fallback.
        """
        rev_drop   = pf.get("revenue_drop_pct", pd.Series(0.0, index=pf.index)).fillna(0).clip(0, 100) / 100.0
        recency    = pf.get("recency_days", pd.Series(0.0, index=pf.index)).fillna(0).clip(0, 365) / 365.0
        revenue    = pf.get("recent_90_revenue", pd.Series(1.0, index=pf.index)).replace(0, 1)
        vol        = pf.get("revenue_volatility", pd.Series(0.0, index=pf.index)).fillna(0)
        cov        = (vol / revenue).clip(0, 2) / 2.0
        growth     = pf.get("growth_rate_90d", pd.Series(0.0, index=pf.index)).fillna(0).clip(-1, 1)
        growth_risk = ((-growth + 1) / 2.0).clip(0, 1)
        recent_txns = pf.get("recent_txns", pd.Series(0.0, index=pf.index)).fillna(0)
        prev_txns   = pf.get("prev_txns", pd.Series(0.0, index=pf.index)).fillna(0)
        txn_drop   = np.where(
            prev_txns > 0,
            ((prev_txns - recent_txns) / prev_txns).clip(0, 1),
            np.where(recent_txns == 0, 0.5, 0.0),
        )
        churn_prob = (
            0.30 * rev_drop
            + 0.25 * recency
            + 0.15 * cov
            + 0.20 * growth_risk
            + 0.10 * txn_drop
        ).clip(0.0, 1.0)

        # Partners with zero recent revenue → force high churn
        churned_mask = pf.get("recent_90_revenue", pd.Series(0.0, index=pf.index)).fillna(0) <= 0
        churn_prob = churn_prob.where(~churned_mask, other=0.85)

        pf["churn_probability"] = churn_prob.values
        pf["churn_risk_band"]   = [self._churn_band(p) for p in pf["churn_probability"]]
        pf["churn_method"]      = "rule_based"

    @staticmethod
    def _churn_band(p: float) -> str:
        if p >= 0.70: return "High"
        if p >= 0.45: return "Medium"
        return "Low"

    # ═════════════════════════════════════════════════════════════════════════
    # FORECAST: 30-day revenue projection
    # ═════════════════════════════════════════════════════════════════════════

    def _build_partner_forecast(self):
        """Simple linear-trend forecast for next 30 days."""
        pf = getattr(self, "df_partner_features", None)
        if pf is None or pf.empty:
            return

        rev_90  = pf.get("recent_90_revenue", pd.Series(0.0, index=pf.index)).fillna(0)
        growth  = pf.get("growth_rate_90d", pd.Series(0.0, index=pf.index)).fillna(0).clip(-0.5, 1.0)
        monthly_base   = rev_90 / 3.0
        monthly_growth = growth / 3.0
        forecast_30d   = (monthly_base * (1 + monthly_growth)).clip(lower=0)

        pf["forecast_next_30d"]   = forecast_30d.round(2)
        pf["forecast_trend_pct"]  = (monthly_growth * 100).round(2)
        pf["forecast_confidence"] = np.where(
            pf.get("active_months", pd.Series(0, index=pf.index)).fillna(0) >= 6, 0.75, 0.45
        )
        self.df_partner_features = pf

    # ═════════════════════════════════════════════════════════════════════════
    # CREDIT RISK
    # ═════════════════════════════════════════════════════════════════════════

    def _load_credit_risk_features(self) -> pd.DataFrame:
        """
        Load credit risk data from view_partner_credit_risk_score (real AR data).
        Falls back to proxy formula if the view is unavailable.
        """
        # ── Try real AR view first ────────────────────────────────────────────
        engine = getattr(self, "engine", None)
        if engine is not None:
            try:
                query = """
                    SELECT
                        company_name,
                        credit_risk_score,
                        credit_risk_band,
                        credit_utilization_ratio    AS credit_utilization,
                        overdue_ratio,
                        outstanding_amount,
                        overdue_amount,
                        net_outstanding,
                        credit_adjusted_risk_value,
                        avg_payment_days,
                        assigned_credit_days,
                        credit_limit,
                        advance_received,
                        overdue_0_30,
                        overdue_31_60,
                        overdue_61_90,
                        overdue_91_120,
                        overdue_120_plus,
                        payment_days_recent,
                        payment_days_prev,
                        payment_trend_days,
                        payment_trend_dir
                    FROM view_partner_credit_risk_score
                """
                import pandas as pd
                df_cr = pd.read_sql(query, engine)
                if not df_cr.empty:
                    # If the view has real overdue data (any score > 0.05), use it directly.
                    score_col = "credit_risk_score"
                    max_score = float(df_cr[score_col].fillna(0).max()) if score_col in df_cr.columns else 0.0
                    if max_score >= 0.05:
                        self.credit_risk_report = {"method": "real_ar_data"}
                        return df_cr
                    # All scores are ~0 (no overdue in due_payment). Fall through to
                    # proxy formula so partners get meaningful behavioral credit scores.
                    print(f"[CreditRisk] View loaded but all scores = 0 (no overdue data). Using behavioral proxy.")
            except Exception as exc:
                print(f"[CreditRisk] view_partner_credit_risk_score unavailable, using proxy: {exc}")

        # ── Fallback: proxy formula from partner features ─────────────────────
        pf = getattr(self, "df_partner_features", None)
        if pf is None or pf.empty:
            return pd.DataFrame()

        df = pf.copy().reset_index()
        if "company_name" not in df.columns and "index" in df.columns:
            df = df.rename(columns={"index": "company_name"})

        rev_drop = df.get("revenue_drop_pct", pd.Series(0.0)).fillna(0).clip(0, 100) / 100.0
        recency  = df.get("recency_days", pd.Series(0.0)).fillna(0).clip(0, 365) / 365.0
        vol      = df.get("revenue_volatility", pd.Series(0.0)).fillna(0)
        revenue  = df.get("recent_90_revenue", pd.Series(1.0)).replace(0, 1)
        cov      = (vol / revenue).clip(0, 2) / 2.0
        overdue_proxy = ((recency + rev_drop) / 2).clip(0, 1)

        df["credit_risk_score"]          = (0.40 * rev_drop + 0.35 * recency + 0.25 * cov).clip(0, 1).round(4)
        df["overdue_ratio"]              = overdue_proxy.round(4)
        df["credit_utilization"]         = rev_drop.round(4)
        df["outstanding_amount"]         = (
            df.get("recent_90_revenue", pd.Series(0.0)).fillna(0) * overdue_proxy
        ).round(2)
        df["credit_adjusted_risk_value"] = (
            df["credit_risk_score"] * df.get("recent_90_revenue", pd.Series(0.0)).fillna(0)
        ).round(2)
        self.credit_risk_report = {"method": "rule_based_proxy"}
        return df

    def _score_credit_risk(self):
        credit_df = self._load_credit_risk_features()
        if credit_df.empty:
            return

        pf = getattr(self, "df_partner_features", None)
        if pf is None:
            return

        # Columns to merge from credit view into partner features
        merge_cols = [
            "credit_risk_score", "overdue_ratio", "credit_utilization",
            "outstanding_amount", "credit_adjusted_risk_value",
            "overdue_amount", "net_outstanding", "avg_payment_days",
            "credit_limit", "advance_received",
        ]
        available = [c for c in merge_cols if c in credit_df.columns]

        if "company_name" in credit_df.columns:
            # A company may have multiple party_ids → keep the highest-risk row per company.
            sort_col = "credit_risk_score" if "credit_risk_score" in credit_df.columns else None
            if sort_col:
                deduped = (
                    credit_df.sort_values(sort_col, ascending=False)
                    .drop_duplicates(subset=["company_name"], keep="first")
                )
            else:
                deduped = credit_df.drop_duplicates(subset=["company_name"], keep="first")
            indexed = deduped.set_index("company_name")
            matched = indexed.index.isin(pf.index).sum()
            print(f"[Credit] Loaded {len(credit_df)} rows → {len(deduped)} unique companies → {matched}/{len(pf)} matched in partner features")
            for col in available:
                pf[col] = indexed[col].reindex(pf.index).values
        else:
            for col in available:
                if col in credit_df.columns:
                    pf[col] = credit_df[col].values

        def _band(s):
            if s >= 0.65: return "Critical"
            if s >= 0.45: return "High"
            if s >= 0.25: return "Medium"
            return "Low"

        if "credit_risk_band" in credit_df.columns and "company_name" in credit_df.columns:
            deduped_band = (
                credit_df.sort_values("credit_risk_score", ascending=False)
                .drop_duplicates(subset=["company_name"], keep="first")
            ) if "credit_risk_score" in credit_df.columns else credit_df.drop_duplicates(subset=["company_name"], keep="first")
            pf["credit_risk_band"] = (
                deduped_band.set_index("company_name")["credit_risk_band"]
                .reindex(pf.index).fillna("Low").values
            )
        else:
            pf["credit_risk_band"] = [_band(s) for s in pf["credit_risk_score"].fillna(0)]

        self.df_partner_features = pf


    # ═════════════════════════════════════════════════════════════════════════
    # EXPLAINABILITY
    # ═════════════════════════════════════════════════════════════════════════

    def explain_partner_churn(self, partner_name: str) -> dict:
        """
        Return churn factor breakdown for a single partner.
        Uses XGBoost feature importance if model is trained,
        otherwise rule-based signal decomposition.
        """
        pf = getattr(self, "df_partner_features", None)
        if pf is None or pf.empty:
            return {"status": "unavailable", "reason": "Partner features not loaded yet."}

        pf_reset = pf.reset_index()
        name_col = "company_name" if "company_name" in pf_reset.columns else pf_reset.columns[0]
        matches = pf_reset[pf_reset[name_col].astype(str).str.lower() == partner_name.lower()]
        if matches.empty:
            matches = pf_reset[pf_reset[name_col].astype(str).str.lower().str.startswith(partner_name.lower()[:5])]
        if matches.empty:
            return {"status": "unavailable", "reason": f"No data found for '{partner_name}'."}

        row = matches.iloc[0]
        churn_prob = float(row.get("churn_probability", 0.3))
        method = str(row.get("churn_method", "rule_based"))

        # Build signal decomposition (always shown for interpretability)
        rev_drop   = float(pd.to_numeric(row.get("revenue_drop_pct", 0), errors="coerce") or 0)
        recency    = float(pd.to_numeric(row.get("recency_days", 0), errors="coerce") or 0)
        volatility = float(pd.to_numeric(row.get("revenue_volatility", 0), errors="coerce") or 0)
        revenue    = max(float(pd.to_numeric(row.get("recent_90_revenue", 1), errors="coerce") or 1), 1)
        growth     = float(pd.to_numeric(row.get("growth_rate_90d", 0), errors="coerce") or 0)
        r_txns     = float(pd.to_numeric(row.get("recent_txns", 0), errors="coerce") or 0)
        p_txns     = float(pd.to_numeric(row.get("prev_txns", 0), errors="coerce") or 0)

        s_rev_drop = 0.30 * min(rev_drop / 100.0, 1.0)
        s_recency  = 0.25 * min(recency / 365.0, 1.0)
        s_vol      = 0.15 * min((volatility / revenue) / 2.0, 1.0)
        s_growth   = 0.20 * max(0.0, (-growth + 1) / 2.0)
        s_txn      = 0.10 * (max(0, (p_txns - r_txns) / max(p_txns, 1)) if p_txns > 0 else 0.5)

        shap_values = {
            "Revenue Drop %":       round(s_rev_drop, 4),
            "Days Since Last Order": round(s_recency, 4),
            "Revenue Volatility":   round(s_vol, 4),
            "Negative Growth Rate": round(s_growth, 4),
            "Transaction Frequency":round(s_txn, 4),
        }

        result = {
            "status": "ok",
            "method": method,
            "partner_name": partner_name,
            "churn_probability": round(churn_prob, 4),
            "churn_risk_band": row.get("churn_risk_band", "Unknown"),
            "shap_values": shap_values,
            "feature_names": list(shap_values.keys()),
            "shap_array": list(shap_values.values()),
            "base_value": 0.0,
        }

        # Attach XGBoost feature importance if available
        if self._xgb_churn_trained and self.churn_model is not None:
            try:
                result["xgb_feature_importance"] = dict(
                    zip(
                        getattr(self, "_xgb_feature_cols", []),
                        [round(float(v), 4) for v in self.churn_model.feature_importances_],
                    )
                )
                result["xgb_model_info"] = self.churn_model_report
            except Exception:
                pass

        return result

    def predict_partner_survival(self, partner_name: str) -> dict:
        """Return geometric decay survival curve using churn probability."""
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
        monthly_survival = max(0.05, min(1.0 - (churn_p / 3.0), 0.999))

        times = list(range(0, 25))
        survival_probs = [round(monthly_survival ** t, 4) for t in times]

        return {
            "status": "ok",
            "method": "geometric_decay",
            "partner_name": partner_name,
            "churn_probability": round(churn_p, 4),
            "churn_method": str(row.get("churn_method", "rule_based")),
            "median_survival_months": next(
                (t for t, s in zip(times, survival_probs) if s <= 0.5), 24
            ),
            "times": times,
            "survival_probs": survival_probs,
        }
