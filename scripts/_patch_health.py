"""
Patch: Rewrites the _add_health_scores method in base_loader_mixin.py
with a fixed Emerging segment detection and clean degrowth logic.
"""

with open(r'ml_engine/base_loader_mixin.py', 'r', encoding='utf-8') as f:
    content = f.read()

start_marker = '    def _add_health_scores(self, features):'
end_marker   = '    def _load_monthly_revenue_history(self):'

idx_start = content.find(start_marker)
idx_end   = content.find(end_marker)

if idx_start == -1 or idx_end == -1:
    print("ERROR: markers not found"); exit(1)

NEW_METHOD = '''    def _add_health_scores(self, features):
        """
        Enterprise Health Scoring Engine v2
        ====================================
        Five segments: Champion | Emerging | Healthy | At Risk | Critical

        Architecture:
        1. Percentile-rank scoring on five signal dimensions (0-1 each).
        2. Weighted composite health_score.
        3. Emerging detection: growth/engagement acceleration on a smaller base.
        4. State-adaptive degrowth threshold.
        5. Hard override rules first (churned = Critical).
        """
        f = features  # alias for brevity

        # Dimension 1: Revenue Magnitude (percentile rank)
        rev_rank = np.log1p(f["recent_90_revenue"]).rank(pct=True)

        # Dimension 2: Growth Momentum (signed QoQ trajectory)
        growth_clipped = f["growth_rate_90d"].clip(-1.0, 2.0)
        growth_rank = growth_clipped.rank(pct=True)

        # Dimension 3: Churn Safety (ML probability, first-class signal)
        _zero = pd.Series(0.0, index=f.index)
        churn_p = pd.to_numeric(
            f["churn_probability"] if "churn_probability" in f.columns else _zero,
            errors="coerce",
        ).fillna(0.0).clip(0.0, 1.0)
        churn_safety = 1.0 - churn_p

        # Dimension 4: Engagement Quality
        _ones = pd.Series(1.0, index=f.index)
        eng_vel = pd.to_numeric(
            f["engagement_velocity"] if "engagement_velocity" in f.columns else _ones,
            errors="coerce",
        ).fillna(1.0).clip(0.0, 5.0)
        aov_t = pd.to_numeric(
            f["aov_trend"] if "aov_trend" in f.columns else _zero,
            errors="coerce",
        ).fillna(0.0).clip(-1.0, 1.0)
        engagement_raw = eng_vel * (1.0 + aov_t.clip(-0.5, 0.5))
        engagement_rank = engagement_raw.rank(pct=True)

        # Dimension 5: Revenue Stability
        stability_rank = 1.0 - np.log1p(f["revenue_volatility"]).rank(pct=True)

        # Composite health score (calibrated weights)
        #   Revenue magnitude  30%
        #   Growth momentum    25%
        #   Churn safety       25%
        #   Engagement quality 12%
        #   Stability           8%
        f["health_score"] = (
            0.30 * rev_rank
            + 0.25 * growth_rank
            + 0.25 * churn_safety
            + 0.12 * engagement_rank
            + 0.08 * stability_rank
        ).clip(0.0, 1.0)

        # State-adaptive degrowth threshold
        if "state" in f.columns and f["state"].nunique() > 1:
            state_threshold = (
                f.assign(pos_drop=f["revenue_drop_pct"].where(f["revenue_drop_pct"] > 0))
                .groupby("state")["pos_drop"]
                .transform(lambda s: float(s.quantile(0.70)) if s.notna().any() else 20.0)
                .clip(lower=10.0, upper=40.0)
            )
            f["degrowth_threshold_pct"] = state_threshold.fillna(20.0)
        else:
            f["degrowth_threshold_pct"] = 20.0

        f["degrowth_flag"] = f["revenue_drop_pct"] >= f["degrowth_threshold_pct"]
        f["estimated_monthly_loss"] = (
            (f["prev_90_revenue"] - f["recent_90_revenue"]).clip(lower=0) / 3.0
        )

        # Emerging signal: acceleration without scale
        # Criteria:
        #   - Recent revenue is non-zero (actively buying)
        #   - Revenue is NOT materially dropping (growth_rate_90d >= -0.05)
        #   - QoQ growth >= 5% OR engagement velocity >= 1.1
        #     OR recent_txns >= 2 (new partner with no prior 90d window, so eng_vel=0)
        #   - Category diversity is stable or expanding (>= -1 allows slight drop)
        #   - Churn probability < 0.55
        #   - Revenue is below the 65th percentile (not yet Champion/Healthy scale)
        rev_p65 = f["recent_90_revenue"].quantile(0.65)
        cat_div = pd.to_numeric(
            f["category_diversity_change"] if "category_diversity_change" in f.columns else _zero,
            errors="coerce",
        ).fillna(0.0)
        _recent_txns_s = pd.to_numeric(
            f["recent_txns"] if "recent_txns" in f.columns else _zero,
            errors="coerce",
        ).fillna(0.0)
        f["_emerging_flag"] = (
            (f["recent_90_revenue"] > 0)
            & (f["growth_rate_90d"] >= -0.05)
            & (
                (f["growth_rate_90d"] >= 0.05)
                | (eng_vel >= 1.1)
                | (_recent_txns_s >= 2)
            )
            & (cat_div >= -1)
            & (churn_p < 0.55)
            & (f["recent_90_revenue"] <= rev_p65)
        )

        # Five-segment classification (evaluation order matters)
        segments = []
        statuses  = []
        for row in f.itertuples():
            # Hard override: revenue stopped after buying previously
            if row.recent_90_revenue <= 0 and row.prev_90_revenue > 0:
                segments.append("Critical")
                statuses.append("Churned (Revenue Stopped)")

            # Champion: top-quartile score + growing + ML confirms low churn
            elif row.health_score >= 0.72 and row.revenue_drop_pct < 10 and churn_p[row.Index] < 0.35:
                segments.append("Champion")
                statuses.append("Champion (High Performer)")

            # Emerging: acceleration signals on a smaller base
            elif f.at[row.Index, "_emerging_flag"]:
                segments.append("Emerging")
                statuses.append("Emerging (Rising Star)")

            # Healthy: solid mid-tier, no significant decline
            elif row.health_score >= 0.50 and row.revenue_drop_pct < row.degrowth_threshold_pct:
                segments.append("Healthy")
                statuses.append("Healthy (Stable)")

            # At Risk: score deteriorating but not yet critical
            elif row.health_score >= 0.30:
                segments.append("At Risk")
                statuses.append("At Risk (Degrowth)")

            # Critical: weak score + churn signals
            else:
                segments.append("Critical")
                statuses.append("Critical (Immediate Action)")

        f["health_segment"] = segments
        f["health_status"]  = statuses
        f.drop(columns=["_emerging_flag"], inplace=True)
        return f

'''

new_content = content[:idx_start] + NEW_METHOD + content[idx_end:]

with open(r'ml_engine/base_loader_mixin.py', 'w', encoding='utf-8') as f:
    f.write(new_content)

print("SUCCESS: _add_health_scores rewritten cleanly.")
print(f"New file size: {len(new_content)} bytes")
