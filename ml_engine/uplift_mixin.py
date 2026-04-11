"""
ml_engine/uplift_mixin.py
──────────────────────────────────────────────────────────────────────────────
Uplift Modeling — Per-Action Revenue Lift Prediction
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Turns the system from DESCRIPTIVE ("this partner is in Win-Back") to
PRESCRIPTIVE ("call them within 7 days — expected lift: Rs 1.2L").

Two modes:
  ML Mode     — activated when >= 50 outcome records exist in
                recommendation_feedback_events. Trains an XGBoost classifier
                per action_type to predict P(positive outcome | partner features).
  Rule-Based  — always available as fallback. Uses churn probability,
                revenue trend, recency, and credit risk to estimate ROI per action.

Expected revenue lift formula:
  lift = P(positive outcome) × current revenue × action_multiplier

Actions:
  call_visit       — personal outreach / site visit
  bundle_offer     — targeted product bundle discount
  credit_extension — extend credit limit / payment terms
  do_nothing       — expected natural recovery probability

Config:
  ENABLE_UPLIFT_MODEL=true
  UPLIFT_MIN_RECORDS=50   # minimum feedback rows to train ML model
"""

import logging
import numpy as np
import pandas as pd
from sqlalchemy import text

logger = logging.getLogger(__name__)

UPLIFT_ACTIONS = ["call_visit", "bundle_offer", "credit_extension", "do_nothing"]

OUTCOME_POSITIVE = {
    "purchase", "success", "converted", "positive", "yes", "1", "true", "won"
}

ACTION_LABELS = {
    "call_visit":       "📞 Call / Visit",
    "bundle_offer":     "🎁 Bundle Offer",
    "credit_extension": "💳 Credit Extension",
    "do_nothing":       "⏳ Monitor (Natural Recovery)",
}


class UpliftMixin:
    """
    Adds per-partner and per-cluster uplift scoring to the engine.
    Inherit alongside ClusteringMixin.
    """

    _uplift_models: dict = {}
    _uplift_feature_names: list = []
    _uplift_ready: bool = False
    _uplift_record_count: int = 0
    uplift_report: dict = {}

    # ── Public entry point ────────────────────────────────────────────────────
    def ensure_uplift(self) -> None:
        """Train or prepare uplift scoring. Idempotent — safe to call multiple times."""
        if self._uplift_ready:
            return

        feedback_df = self._load_feedback_data()
        self._uplift_record_count = len(feedback_df)
        min_records = int(getattr(self, "uplift_min_records", 50))

        if self._uplift_record_count >= min_records:
            self._train_uplift_model(feedback_df)
            mode = f"ML (XGBoost, {self._uplift_record_count} records)"
        else:
            mode = (
                f"Rule-based (only {self._uplift_record_count} feedback records; "
                f"need ≥{min_records} for ML mode)"
            )

        self._uplift_ready = True
        self.uplift_report = {
            "mode": mode,
            "feedback_records": self._uplift_record_count,
            "trained_actions": list(self._uplift_models.keys()),
            "min_records_for_ml": min_records,
        }
        logger.info(f"[Uplift] Ready. {mode}")

    def get_partner_uplift_scores(self, partner_name: str) -> dict:
        """
        Returns expected Rs revenue lift per action for the given partner.
        Return format: {action_key: expected_rs_lift}
        """
        if not self._uplift_ready:
            self.ensure_uplift()

        facts = {}
        if (
            self.df_partner_features is not None
            and not self.df_partner_features.empty
            and partner_name in self.df_partner_features.index
        ):
            facts = self.df_partner_features.loc[partner_name].to_dict()

        revenue = float(
            facts.get("recent_90_revenue", facts.get("total_revenue", 0)) or 0
        )
        if revenue <= 0:
            revenue = 5_000  # safe floor so scores aren't always zero

        if self._uplift_models:
            return self._ml_uplift(facts, revenue)
        else:
            return self._rule_based_uplift(facts, revenue)

    def get_cluster_best_action(self, cluster_label: str) -> dict:
        """
        Aggregate uplift scores across all partners in a cluster.
        Returns the best action + average expected lift per partner.
        """
        if not self._uplift_ready:
            self.ensure_uplift()

        if self.matrix is None or "cluster_label" not in self.matrix.columns:
            return {"action": "call_visit", "action_label": ACTION_LABELS["call_visit"],
                    "expected_lift": 0.0, "all_actions": {}}

        members = self.matrix[
            self.matrix["cluster_label"] == cluster_label
        ].index.tolist()

        if not members:
            return {"action": "call_visit", "action_label": ACTION_LABELS["call_visit"],
                    "expected_lift": 0.0, "all_actions": {}}

        total_scores = {a: 0.0 for a in UPLIFT_ACTIONS}
        for partner in members:
            ps = self.get_partner_uplift_scores(partner)
            for a in UPLIFT_ACTIONS:
                total_scores[a] += ps.get(a, 0.0)

        best_action = max(total_scores, key=lambda a: total_scores[a])
        n = max(len(members), 1)
        avg_lift = total_scores[best_action] / n

        return {
            "action": best_action,
            "action_label": ACTION_LABELS.get(best_action, best_action),
            "expected_lift": round(avg_lift, 2),
            "all_actions": {
                a: round(total_scores[a] / n, 2) for a in UPLIFT_ACTIONS
            },
        }

    # ── Internal: data loading ────────────────────────────────────────────────
    def _load_feedback_data(self) -> pd.DataFrame:
        query = text(
            """
            SELECT
                action_type,
                outcome,
                COALESCE(churn_probability, 0)                AS churn_probability,
                COALESCE(credit_risk_score, 0)                AS credit_risk_score,
                COALESCE(revenue_drop_pct, 0)                 AS revenue_drop_pct,
                COALESCE(priority_score, 0)                   AS priority_score,
                COALESCE(confidence, 0)                       AS confidence,
                COALESCE(expected_revenue_at_risk_monthly, 0) AS expected_revenue_at_risk_monthly,
                cluster_type
            FROM recommendation_feedback_events
            WHERE created_at >= CURRENT_DATE - INTERVAL '180 days'
            ORDER BY created_at DESC
            """
        )
        try:
            df = pd.read_sql(query, self.engine)
            logger.info(f"[Uplift] Loaded {len(df)} feedback records.")
            return df
        except Exception as exc:
            logger.warning(f"[Uplift] Could not load feedback data: {exc}")
            return pd.DataFrame()

    # ── Internal: ML training ─────────────────────────────────────────────────
    def _train_uplift_model(self, feedback_df: pd.DataFrame) -> None:
        try:
            from xgboost import XGBClassifier
        except ImportError:
            logger.warning("[Uplift] XGBoost not available — using rule-based fallback.")
            return

        FEATURES = [
            "churn_probability",
            "credit_risk_score",
            "revenue_drop_pct",
            "priority_score",
            "confidence",
            "expected_revenue_at_risk_monthly",
        ]

        feedback_df = feedback_df.copy()
        feedback_df["outcome_binary"] = (
            feedback_df["outcome"]
            .astype(str)
            .str.lower()
            .isin(OUTCOME_POSITIVE)
        ).astype(int)

        self._uplift_feature_names = FEATURES
        models = {}

        for action in feedback_df["action_type"].dropna().unique():
            sub = feedback_df[feedback_df["action_type"] == action].copy()
            if len(sub) < 10 or sub["outcome_binary"].nunique() < 2:
                logger.info(f"[Uplift] Skipping '{action}' — insufficient data.")
                continue
            try:
                clf = XGBClassifier(
                    n_estimators=50,
                    max_depth=3,
                    learning_rate=0.1,
                    eval_metric="logloss",
                    verbosity=0,
                    random_state=42,
                )
                clf.fit(sub[FEATURES].fillna(0), sub["outcome_binary"])
                models[action] = clf
                logger.info(
                    f"[Uplift] Trained model for '{action}' "
                    f"({len(sub)} samples, "
                    f"positive rate={sub['outcome_binary'].mean():.1%})."
                )
            except Exception as exc:
                logger.warning(f"[Uplift] Training failed for '{action}': {exc}")

        self._uplift_models = models

    # ── Internal: scoring ─────────────────────────────────────────────────────
    def _ml_uplift(self, facts: dict, revenue: float) -> dict:
        """Predict P(positive) per action using trained models × revenue."""
        FEATURES = self._uplift_feature_names
        X_row = pd.DataFrame([{f: float(facts.get(f, 0) or 0) for f in FEATURES}])
        scores = {}
        for action, model in self._uplift_models.items():
            try:
                prob = float(model.predict_proba(X_row)[0][1])
                # Expected lift = P(conversion) × base revenue × action multiplier
                multipliers = {
                    "call_visit": 0.35,
                    "bundle_offer": 0.25,
                    "credit_extension": 0.20,
                    "do_nothing": 0.10,
                }
                scores[action] = round(prob * revenue * multipliers.get(action, 0.25), 2)
            except Exception:
                scores[action] = 0.0

        # Fill any untrained actions with rule-based estimates
        rule = self._rule_based_uplift(facts, revenue)
        for action in UPLIFT_ACTIONS:
            if action not in scores:
                scores[action] = rule.get(action, 0.0)
        return scores

    def _rule_based_uplift(self, facts: dict, revenue: float) -> dict:
        """
        Calibrated rule-based uplift when ML data is insufficient.
        Based on: churn probability, revenue drop %, recency days, credit risk.
        """
        churn = min(float(facts.get("churn_probability", 0.30) or 0.30), 1.0)
        drop = min(float(facts.get("revenue_drop_pct", 0.0) or 0.0) / 100.0, 1.0)
        recency = float(facts.get("recency_days", 30) or 30)
        credit_risk = min(float(facts.get("credit_risk_score", 0.20) or 0.20), 1.0)

        # Recency factor: 1.0 at 0 days, 0.0 at 180 days
        recency_factor = max(0.0, 1.0 - recency / 180.0)

        # Call/visit: high value when churn is medium-high + still active
        call_lift = revenue * (
            0.45 * churn + 0.30 * drop + 0.25 * recency_factor
        ) * 0.35

        # Bundle offer: best for active partners with category concentration
        bundle_lift = revenue * (
            0.40 * recency_factor + 0.35 * (1.0 - churn) + 0.25 * drop
        ) * 0.25

        # Credit extension: only sensible for low-risk active partners
        if credit_risk < 0.40 and recency_factor > 0.3:
            credit_lift = revenue * (1.0 - credit_risk) * recency_factor * 0.20
        else:
            credit_lift = 0.0

        # Do nothing: natural recovery — works for healthy, low-churn partners
        natural = revenue * max(0.0, (1.0 - churn) * (1.0 - drop) * 0.15)

        return {
            "call_visit":       round(call_lift, 2),
            "bundle_offer":     round(bundle_lift, 2),
            "credit_extension": round(credit_lift, 2),
            "do_nothing":       round(natural, 2),
        }
