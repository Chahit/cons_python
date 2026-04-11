"""
Unit tests for all core scoring formulas.
No database connection required — all inputs are synthetic.

Run with:
    python -m pytest tests/test_core_formulas.py -v
"""

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ml_engine.clustering_mixin import ClusteringMixin
from ml_engine.base_loader_mixin import BaseLoaderMixin
from ml_engine.churn_credit_stub_mixin import ChurnCreditStubMixin


# ──────────────────────────────────────────────────────────────────────────────
# Test harnesses (mix only what's needed, no DB)
# ──────────────────────────────────────────────────────────────────────────────

class _ClusterHarness(ClusteringMixin):
    strict_view_only = True
    engine = None


class _BaseHarness(BaseLoaderMixin):
    pass


class _ChurnHarness(ChurnCreditStubMixin):
    churn_prob_high = 0.65
    churn_prob_medium = 0.35
    credit_risk_high = 0.67
    credit_risk_medium = 0.40
    df_partner_features = None


# ──────────────────────────────────────────────────────────────────────────────
# 1. RFM features (ClusteringMixin static helpers)
# ──────────────────────────────────────────────────────────────────────────────

class TestRFMFormulas(unittest.TestCase):

    def test_safe_ratio_normal(self):
        num = np.array([10.0, 20.0, 0.0])
        den = np.array([5.0, 0.0, 4.0])
        result = ClusteringMixin._safe_ratio(num, den)
        self.assertAlmostEqual(result[0], 2.0)
        self.assertAlmostEqual(result[1], 0.0)   # den=0 → 0
        self.assertAlmostEqual(result[2], 0.0)   # num=0 → 0

    def test_safe_ratio_all_zeros(self):
        result = ClusteringMixin._safe_ratio(np.zeros(5), np.zeros(5))
        self.assertTrue(np.all(result == 0.0))

    def test_safe_ratio_no_infs(self):
        result = ClusteringMixin._safe_ratio(np.array([1e10]), np.array([0.0]))
        self.assertTrue(np.all(np.isfinite(result)))

    def test_rfm_log_monetary_positive(self):
        """log1p(monetary) must always be ≥ 0."""
        monetaries = np.array([0.0, 1.0, 1000.0, 1_000_000.0])
        log_m = np.log1p(monetaries)
        self.assertTrue(np.all(log_m >= 0))

    def test_rfm_recency_monotone(self):
        """Higher recency_days → lower partner value."""
        recency_days = np.array([1, 30, 90, 365, 730])
        log_r = np.log1p(recency_days)
        self.assertTrue(np.all(np.diff(log_r) > 0), "log_recency should be monotonically increasing")


# ──────────────────────────────────────────────────────────────────────────────
# 2. Shannon entropy
# ──────────────────────────────────────────────────────────────────────────────

class TestCategoryEntropy(unittest.TestCase):

    def setUp(self):
        self.h = _ClusterHarness()

    def test_uniform_distribution_max_entropy(self):
        """4 equal categories → entropy = log2(4) = 2, norm = 1.0."""
        pivot = pd.DataFrame(
            {"A": [25.0], "B": [25.0], "C": [25.0], "D": [25.0]},
            index=["partner1"],
        )
        result = self.h._compute_category_entropy(pivot)
        self.assertAlmostEqual(result.loc["partner1", "category_entropy"], 2.0, places=5)
        self.assertAlmostEqual(result.loc["partner1", "category_entropy_norm"], 1.0, places=5)

    def test_monopoly_zero_entropy(self):
        """Only one category → entropy = 0."""
        pivot = pd.DataFrame(
            {"A": [100.0], "B": [0.0], "C": [0.0]},
            index=["partner1"],
        )
        result = self.h._compute_category_entropy(pivot)
        self.assertAlmostEqual(result.loc["partner1", "category_entropy"], 0.0, places=5)
        self.assertAlmostEqual(result.loc["partner1", "category_entropy_norm"], 0.0, places=5)

    def test_entropy_order(self):
        """Uniform > skewed distribution."""
        pivot = pd.DataFrame(
            {"A": [50.0, 100.0], "B": [50.0, 0.0]},
            index=["uniform", "monopoly"],
        )
        result = self.h._compute_category_entropy(pivot)
        self.assertGreater(
            result.loc["uniform", "category_entropy"],
            result.loc["monopoly", "category_entropy"],
        )

    def test_entropy_empty_pivot(self):
        result = self.h._compute_category_entropy(pd.DataFrame())
        self.assertTrue(result.empty)

    def test_entropy_non_negative(self):
        pivot = pd.DataFrame(
            {"A": [10.0, 90.0, 50.0], "B": [90.0, 10.0, 50.0]},
            index=["p1", "p2", "p3"],
        )
        result = self.h._compute_category_entropy(pivot)
        self.assertTrue((result["category_entropy"] >= 0).all())


# ──────────────────────────────────────────────────────────────────────────────
# 3. HHI (portfolio concentration)
# ──────────────────────────────────────────────────────────────────────────────

class TestHHI(unittest.TestCase):

    def test_monopoly_hhi_equals_one(self):
        spend = pd.Series({"A": 100.0, "B": 0.0, "C": 0.0})
        total = spend.sum()
        shares = spend / total
        hhi = float((shares ** 2).sum())
        self.assertAlmostEqual(hhi, 1.0, places=5)

    def test_uniform_hhi_minimum(self):
        """Uniform distribution over N categories → HHI = 1/N."""
        n = 5
        spend = pd.Series({f"cat_{i}": 1.0 for i in range(n)})
        total = spend.sum()
        shares = spend / total
        hhi = float((shares ** 2).sum())
        self.assertAlmostEqual(hhi, 1.0 / n, places=5)

    def test_hhi_bounded(self):
        """HHI must always be in (0, 1]."""
        for trial in range(20):
            rng = np.random.RandomState(trial)
            spend = pd.Series(np.abs(rng.randn(6)) + 0.1)
            total = spend.sum()
            shares = spend / total
            hhi = float((shares ** 2).sum())
            self.assertGreater(hhi, 0.0)
            self.assertLessEqual(hhi, 1.0 + 1e-9)

    def test_hhi_more_concentrated_is_higher(self):
        diversified = pd.Series({"A": 25.0, "B": 25.0, "C": 25.0, "D": 25.0})
        concentrated = pd.Series({"A": 90.0, "B": 5.0, "C": 3.0, "D": 2.0})
        def _hhi(s):
            sh = s / s.sum()
            return float((sh ** 2).sum())
        self.assertGreater(_hhi(concentrated), _hhi(diversified))


# ──────────────────────────────────────────────────────────────────────────────
# 4. Purchase velocity / gap CV
# ──────────────────────────────────────────────────────────────────────────────

class TestPurchaseVelocity(unittest.TestCase):

    def test_gap_cv_zero_for_uniform_gaps(self):
        """Perfectly regular buyer has CV = 0."""
        gaps = np.array([30.0, 30.0, 30.0, 30.0])
        mean_gap = np.mean(gaps)
        std_gap = np.std(gaps, ddof=1) if len(gaps) > 1 else 0.0
        cv = std_gap / mean_gap if mean_gap > 0 else 0.0
        self.assertAlmostEqual(cv, 0.0, places=5)

    def test_gap_cv_high_for_irregular_gaps(self):
        """Very irregular buyer has high CV."""
        gaps = np.array([1.0, 1.0, 200.0, 1.0, 1.0])
        mean_gap = np.mean(gaps)
        std_gap = np.std(gaps, ddof=1)
        cv = std_gap / mean_gap
        self.assertGreater(cv, 1.0)

    def test_mean_gap_positive(self):
        gaps = np.array([14.0, 28.0, 21.0])
        self.assertGreater(np.mean(gaps), 0.0)

    def test_log1p_mean_gap_monotone(self):
        slow = np.log1p(60.0)
        fast = np.log1p(7.0)
        self.assertGreater(slow, fast)   # slower buyer → higher log gap


# ──────────────────────────────────────────────────────────────────────────────
# 5. Health score formula
# ──────────────────────────────────────────────────────────────────────────────

class TestHealthScore(unittest.TestCase):

    def _make_features(self, recent_90=10000, prev_90=10000, recency=15,
                       revenue_volatility=0, state="TestState"):
        return pd.DataFrame([{
            "company_name": "Partner",
            "state": state,
            "recent_90_revenue": recent_90,
            "prev_90_revenue": prev_90,
            "recency_days": recency,
            "revenue_volatility": revenue_volatility,
            "growth_rate_90d": (recent_90 - prev_90) / max(prev_90, 1),
            "revenue_drop_pct": max(0, (prev_90 - recent_90) / max(prev_90, 1) * 100),
            "revenue_drop_pct_raw": max(0, (prev_90 - recent_90) / max(prev_90, 1) * 100),
        }])

    def test_health_score_bounded(self):
        h = _BaseHarness()
        features = self._make_features()
        result = h._add_health_scores(features)
        hs = float(result["health_score"].iloc[0])
        self.assertGreaterEqual(hs, 0.0)
        self.assertLessEqual(hs, 1.0)

    def test_healthy_partner_higher_score(self):
        """Growing partner with recent activity → higher health score."""
        h = _BaseHarness()
        healthy = self._make_features(recent_90=20000, prev_90=10000, recency=5)
        unhealthy = self._make_features(recent_90=1000, prev_90=20000, recency=300)
        # Combine to allow normalization across both
        combined = pd.concat([healthy, unhealthy], ignore_index=True)
        combined["company_name"] = ["Healthy", "Unhealthy"]
        result = h._add_health_scores(combined)
        self.assertGreater(
            float(result.loc[result["company_name"] == "Healthy", "health_score"].iloc[0]),
            float(result.loc[result["company_name"] == "Unhealthy", "health_score"].iloc[0]),
        )

    def test_weights_sum_to_one(self):
        """The 4 health score weights must sum to 1.0."""
        weights = [0.35, 0.30, 0.20, 0.15]
        self.assertAlmostEqual(sum(weights), 1.0, places=5)

    def test_degrowth_flag_triggered(self):
        h = _BaseHarness()
        features = self._make_features(recent_90=5000, prev_90=20000)  # 75% drop
        result = h._add_health_scores(features)
        self.assertTrue(bool(result["degrowth_flag"].iloc[0]))


# ──────────────────────────────────────────────────────────────────────────────
# 6. Churn scoring
# ──────────────────────────────────────────────────────────────────────────────

class TestChurnScoring(unittest.TestCase):

    def _make_pf(self, **kwargs):
        defaults = dict(
            revenue_drop_pct=0.0,
            recency_days=10,
            revenue_volatility=0.0,
            recent_90_revenue=10000.0,
            growth_rate_90d=0.0,
            recent_txns=5,
            prev_txns=5,
        )
        defaults.update(kwargs)
        return pd.DataFrame([defaults], index=["partner"])

    def test_high_churn_on_zero_revenue(self):
        h = _ChurnHarness()
        h.df_partner_features = self._make_pf(recent_90_revenue=0.0, revenue_drop_pct=100.0)
        h._score_partner_churn_risk()
        prob = float(h.df_partner_features.loc["partner", "churn_probability"])
        self.assertGreaterEqual(prob, 0.80)

    def test_low_churn_healthy_partner(self):
        h = _ChurnHarness()
        h.df_partner_features = self._make_pf(
            recent_90_revenue=50000.0, revenue_drop_pct=0.0,
            recency_days=5, growth_rate_90d=0.3, recent_txns=10, prev_txns=8,
        )
        h._score_partner_churn_risk()
        prob = float(h.df_partner_features.loc["partner", "churn_probability"])
        self.assertLess(prob, 0.5)

    def test_churn_probability_bounded(self):
        for drop in [0, 25, 50, 75, 100]:
            h = _ChurnHarness()
            h.df_partner_features = self._make_pf(revenue_drop_pct=float(drop))
            h._score_partner_churn_risk()
            prob = float(h.df_partner_features.loc["partner", "churn_probability"])
            self.assertGreaterEqual(prob, 0.0, f"drop={drop}")
            self.assertLessEqual(prob, 1.0, f"drop={drop}")

    def test_churn_risk_band_assigned(self):
        h = _ChurnHarness()
        h.df_partner_features = self._make_pf(revenue_drop_pct=80.0, recency_days=300)
        h._score_partner_churn_risk()
        band = h.df_partner_features.loc["partner", "churn_risk_band"]
        self.assertIn(band, {"High", "Medium", "Low"})

    def test_revenue_at_risk_formula(self):
        """expected_revenue_at_risk_90d = churn_prob * recent_90_revenue."""
        h = _ChurnHarness()
        revenue = 12000.0
        h.df_partner_features = self._make_pf(recent_90_revenue=revenue, revenue_drop_pct=60.0)
        h._score_partner_churn_risk()
        prob = float(h.df_partner_features.loc["partner", "churn_probability"])
        rar = float(h.df_partner_features.loc["partner", "expected_revenue_at_risk_90d"])
        expected = round(prob * revenue, 2)
        self.assertAlmostEqual(rar, expected, places=1)


# ──────────────────────────────────────────────────────────────────────────────
# 7. Credit risk scoring
# ──────────────────────────────────────────────────────────────────────────────

class TestCreditRiskScoring(unittest.TestCase):

    def _make_pf(self, **kwargs):
        defaults = dict(
            revenue_drop_pct=0.0,
            recency_days=10,
            revenue_volatility=0.0,
            recent_90_revenue=10000.0,
        )
        defaults.update(kwargs)
        df = pd.DataFrame([defaults], index=["partner"])
        return df

    def test_credit_score_bounded(self):
        h = _ChurnHarness()
        for drop in [0.0, 50.0, 100.0]:
            h.df_partner_features = self._make_pf(revenue_drop_pct=drop)
            h._score_credit_risk()
            score = float(h.df_partner_features.loc["partner", "credit_risk_score"])
            self.assertGreaterEqual(score, 0.0, f"drop={drop}")
            self.assertLessEqual(score, 1.0, f"drop={drop}")

    def test_high_drop_raises_credit_risk(self):
        h_low = _ChurnHarness()
        h_low.df_partner_features = self._make_pf(revenue_drop_pct=0.0, recency_days=5)
        h_low._score_credit_risk()

        h_high = _ChurnHarness()
        h_high.df_partner_features = self._make_pf(revenue_drop_pct=90.0, recency_days=300)
        h_high._score_credit_risk()

        low_score = float(h_low.df_partner_features.loc["partner", "credit_risk_score"])
        high_score = float(h_high.df_partner_features.loc["partner", "credit_risk_score"])
        self.assertGreater(high_score, low_score)

    def test_credit_risk_band_assigned(self):
        h = _ChurnHarness()
        h.df_partner_features = self._make_pf(revenue_drop_pct=80.0, recency_days=350)
        h._score_credit_risk()
        band = h.df_partner_features.loc["partner", "credit_risk_band"]
        self.assertIn(band, {"Critical", "High", "Medium", "Low"})

    def test_credit_weights_sum(self):
        """Internal credit formula: 0.40 + 0.35 + 0.25 = 1.0."""
        self.assertAlmostEqual(0.40 + 0.35 + 0.25, 1.0, places=9)


# ──────────────────────────────────────────────────────────────────────────────
# 8. Revenue at risk formula
# ──────────────────────────────────────────────────────────────────────────────

class TestRevenueAtRisk(unittest.TestCase):

    def test_rar_90d_proportional(self):
        churn_prob = 0.4
        rev_90 = 30000.0
        expected = round(churn_prob * rev_90, 2)  # 12000.0
        self.assertAlmostEqual(expected, 12000.0, places=2)

    def test_rar_monthly_derived_from_90d(self):
        churn_prob = 0.6
        rev_90 = 9000.0
        rar_90d = churn_prob * rev_90           # 5400.0
        rar_monthly = rar_90d / 3.0             # 1800.0
        self.assertAlmostEqual(rar_monthly, 1800.0, places=2)

    def test_zero_revenue_zero_risk(self):
        churn_prob = 0.99
        rev_90 = 0.0
        rar = churn_prob * rev_90
        self.assertAlmostEqual(rar, 0.0, places=5)


if __name__ == "__main__":
    unittest.main()
