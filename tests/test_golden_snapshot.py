"""
Snapshot / regression tests against the golden dataset.

Runs the deterministic feature engineering pipeline (health scoring,
churn scoring, credit scoring) on tests/golden/golden_dataset.csv
and asserts outputs match the expected_output.json contract.

No DB connection required.

Run:
    python -m pytest tests/test_golden_snapshot.py -v

To regenerate expected_output.json after intentional changes:
    python tests/test_golden_snapshot.py --generate
"""

import json
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
GOLDEN_DIR = ROOT / "tests" / "golden"
DATASET_PATH = GOLDEN_DIR / "golden_dataset.csv"
EXPECTED_PATH = GOLDEN_DIR / "expected_output.json"

sys.path.insert(0, str(ROOT))

from ml_engine.base_loader_mixin import BaseLoaderMixin
from ml_engine.churn_credit_stub_mixin import ChurnCreditStubMixin


# ──────────────────────────────────────────────────────────────────────────────
# Harness
# ──────────────────────────────────────────────────────────────────────────────

class _Harness(BaseLoaderMixin, ChurnCreditStubMixin):
    churn_prob_high = 0.65
    churn_prob_medium = 0.35
    credit_risk_high = 0.67
    credit_risk_medium = 0.40
    df_partner_features = None


def _build_features_from_csv(path: Path) -> pd.DataFrame:
    """Load golden dataset and build partner features as the real pipeline does."""
    raw = pd.read_csv(path)

    # Aggregate to one row per partner (unique business entity)
    partners = (
        raw.groupby("company_name")
        .agg(
            state=("state", "first"),
            recent_90_revenue=("recent_90_revenue", "first"),
            prev_90_revenue=("prev_90_revenue", "first"),
            recency_days=("recency_days", "first"),
            revenue_drop_pct=("revenue_drop_pct", "first"),
            growth_rate_90d=("growth_rate_90d", "first"),
            revenue_volatility=("revenue_volatility", "first"),
            recent_txns=("recent_txns", "first"),
            prev_txns=("prev_txns", "first"),
            active_months=("active_months", "first"),
        )
        .reset_index()
    )

    h = _Harness()
    features = h._add_health_scores(partners.copy())

    # Score churn
    h.df_partner_features = features.set_index("company_name")
    h._score_partner_churn_risk()
    # Score credit
    h._score_credit_risk()
    return h.df_partner_features


# ──────────────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────────────

class TestGoldenSnapshot(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not DATASET_PATH.exists():
            raise FileNotFoundError(f"Golden dataset not found: {DATASET_PATH}")
        if not EXPECTED_PATH.exists():
            raise FileNotFoundError(f"Expected output not found: {EXPECTED_PATH}")

        cls.features = _build_features_from_csv(DATASET_PATH)
        with open(EXPECTED_PATH, "r", encoding="utf-8") as f:
            cls.expected = json.load(f)

    # ── Global bounds ────────────────────────────────────────────────────────

    def test_churn_probability_all_bounded(self):
        """All churn probabilities must be in [0, 1]."""
        col = self.features["churn_probability"]
        self.assertTrue((col >= 0.0).all(), "Some churn_probability < 0")
        self.assertTrue((col <= 1.0).all(), "Some churn_probability > 1")

    def test_credit_score_all_bounded(self):
        col = self.features["credit_risk_score"]
        self.assertTrue((col >= 0.0).all(), "credit_risk_score < 0")
        self.assertTrue((col <= 1.0).all(), "credit_risk_score > 1")

    def test_health_score_all_bounded(self):
        col = self.features["health_score"]
        self.assertTrue((col >= 0.0).all(), "health_score < 0")
        self.assertTrue((col <= 1.0).all(), "health_score > 1")

    # ── Per-partner contract assertions ─────────────────────────────────────

    def _get(self, partner, field):
        if partner not in self.features.index:
            self.skipTest(f"Partner '{partner}' not in golden features")
        return self.features.loc[partner, field]

    def test_alpha_health_segment(self):
        seg = self._get("Alpha Distributors", "health_segment")
        expected = self.expected["partners"]["Alpha Distributors"]
        allowed = expected.get("health_segment_options",
                               [expected.get("health_segment", seg)])
        self.assertIn(seg, allowed, f"Alpha Distributors health_segment={seg}")

    def test_alpha_no_degrowth(self):
        flag = bool(self._get("Alpha Distributors", "degrowth_flag"))
        self.assertFalse(flag, "Alpha Distributors should not be in degrowth")

    def test_beta_degrowth_triggered(self):
        flag = bool(self._get("Beta Traders", "degrowth_flag"))
        self.assertTrue(flag, "Beta Traders revenue dropped 67% — degrowth must fire")

    def test_beta_churn_elevated(self):
        prob = float(self._get("Beta Traders", "churn_probability"))
        min_expected = self.expected["partners"]["Beta Traders"]["churn_probability_min"]
        self.assertGreaterEqual(prob, min_expected,
                                f"Beta Traders churn_prob={prob:.3f} < {min_expected}")

    def test_epsilon_churned_state(self):
        prob = float(self._get("Epsilon Stores", "churn_probability"))
        min_expected = self.expected["partners"]["Epsilon Stores"]["churn_probability_min"]
        self.assertGreaterEqual(prob, min_expected,
                                f"Epsilon Stores (zero revenue partner) churn_prob={prob:.3f}")

    def test_epsilon_zero_revenue(self):
        rev = float(self._get("Epsilon Stores", "recent_90_revenue"))
        max_expected = self.expected["partners"]["Epsilon Stores"]["recent_90_revenue_max"]
        self.assertLessEqual(rev, max_expected)

    def test_theta_vip_low_churn(self):
        prob = float(self._get("Theta Partners", "churn_probability"))
        max_expected = self.expected["partners"]["Theta Partners"]["churn_probability_max"]
        self.assertLessEqual(prob, max_expected,
                             f"Theta Partners (high revenue, fresh) churn_prob={prob:.3f}")

    def test_iota_degrowth_flagged(self):
        flag = bool(self._get("Iota Wholesale", "degrowth_flag"))
        self.assertTrue(flag, "Iota Wholesale had 25% revenue drop — degrowth must fire")

    # ── No missing fields ────────────────────────────────────────────────────

    def test_all_required_columns_present(self):
        required = [
            "health_score", "health_segment", "health_status",
            "churn_probability", "churn_risk_band",
            "credit_risk_score", "credit_risk_band",
            "degrowth_flag", "estimated_monthly_loss",
        ]
        missing = [c for c in required if c not in self.features.columns]
        self.assertEqual(missing, [], f"Missing columns: {missing}")

    def test_no_nan_in_core_scores(self):
        for col in ("health_score", "churn_probability", "credit_risk_score"):
            n_nan = int(self.features[col].isna().sum())
            self.assertEqual(n_nan, 0, f"Column '{col}' has {n_nan} NaN values")


# ──────────────────────────────────────────────────────────────────────────────
# CLI: --generate flag to write/refresh expected_output.json
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if "--generate" in sys.argv:
        print(f"Generating expected outputs from {DATASET_PATH}...")
        features = _build_features_from_csv(DATASET_PATH)
        snapshot = {
            "description": "Golden snapshot — regenerated",
            "partners": {},
            "aggregate": {
                "all_churn_probabilities_bounded": True,
                "all_credit_scores_bounded": True,
                "all_health_scores_bounded": True,
            },
        }
        for partner in features.index:
            row = features.loc[partner]
            snapshot["partners"][partner] = {
                "health_segment": str(row["health_segment"]),
                "degrowth_flag": bool(row["degrowth_flag"]),
                "churn_probability": round(float(row["churn_probability"]), 4),
                "credit_risk_score": round(float(row["credit_risk_score"]), 4),
                "health_score": round(float(row["health_score"]), 4),
            }
        EXPECTED_PATH.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
        print(f"Saved to {EXPECTED_PATH}")
    else:
        unittest.main()
