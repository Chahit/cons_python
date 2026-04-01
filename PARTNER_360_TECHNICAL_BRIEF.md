

## What is Partner 360?

Partner 360 is a single screen inside the Sales Intelligence Dashboard that gives a complete, real-time view of any distributor/partner in the network. You pick a state, pick a partner, and you get:

- How healthy is this partner right now (revenue health score)?
- Are they about to leave us (churn probability)?
- How much revenue could we be missing from them (peer gap)?
- What's their credit risk looking like?
- What should the sales rep actually say to them (SPIN script)?

Every metric on that screen is computed by the ML engine. None of it is manually maintained or hardcoded. The engine reads from the live database, runs the models, and produces the numbers fresh every session.

---

## The Architecture — How It All Fits Together

The core engine is a class called `SalesIntelligenceEngine`. It's built using Python mixins — essentially, different files that each handle one part of the problem (health scoring, churn, credit risk, clustering, etc.) and are combined into a single class when the app starts.

Here's how data flows from database to dashboard:

```
PostgreSQL Database
        |
        v
  BaseLoaderMixin  →  Partner Features (revenue, recency, volatility, growth)
        |
        v
  ChurnCreditMixin →  Churn Probability  +  Credit Risk Score
  ClusteringMixin  →  Partner Segments (which "type" of buyer are they?)
  AssociationsMixin → Product Affinities (what should we cross-sell?)
  LifecycleMixin   →  Product Stage (is this product growing or dying?)
        |
        v
  RecommendationMixin  →  Ranked Actions  +  Confidence Scores
        |
        v
  Partner 360 UI  →  Sales Rep sees it all in one screen
```

---

## Section 1 — Health Score

**File:** `ml_engine/base_loader_mixin.py` → `_add_health_scores()`

### What it measures

The health score is a single number between 0 and 1 that summarises how well a partner is doing right now. It feeds the traffic-light segmentation: Champion (≥ 0.8), Healthy (≥ 0.6), At Risk (≥ 0.4), Critical (< 0.4).

### The formula

```
Health Score = 0.35 × revenue_strength
             + 0.30 × growth_trend
             + 0.20 × recency_activity
             + 0.15 × stability
```

Each component is normalised to 0–1 before being combined.

**Revenue Strength** = min-max normalise `log(1 + 90-day revenue)`
**Growth Trend** = min-max normalise `90-day growth rate` (clipped to -100% / +150%)
**Recency Activity** = `1 − normalise(log(1 + recency_days))`
**Stability** = `1 − normalise(log(1 + revenue_volatility))`

### Why log-transform recency?

This was a big fix we made. The old version used raw `recency_days / 365`, which treated a partner absent for 10 days almost the same as one absent for 40 days — but a sales rep would care a lot more about a partner missing for 200 days than 50 days. 

Log transformation compresses short absences and stretches long ones, which matches how urgency actually works in a sales context:

```
raw recency:   10d → 0.027    100d → 0.274    300d → 0.822
log recency:   10d → 0.194    100d → 0.393    300d → 0.517
```

The log version makes a 300-day absence almost twice as urgent as a 100-day absence, which is what the sales team actually needs.

### Why these weights (0.35, 0.30, 0.20, 0.15)?

Revenue strength gets the highest weight because in B2B distribution, revenue volume is the primary signal of account health. Growth comes second because a growing account — even if small today — is the most important to protect. Recency and stability are supporting signals rather than primary drivers.

### What could we use instead?

- **Logistic Regression or XGBoost on health labels**: We'd need sales managers to manually label accounts ("this one is healthy, this one is at risk") to train it. We tried an XGBoost variant but the auto-generated "churn = 0 revenue" labels produced scores of ~1% for everyone, which is useless. The weighted formula gives real differentiation.
- **RFM Score (Recency, Frequency, Monetary)**: Classic in retail. Less reliable in B2B because a distributor might order monthly in large batches — low frequency doesn't mean they're at risk.

### Is this the best approach?

It's the right approach for our data maturity level. In a mature state with 2+ years of labelled data and a dedicated data scientist, we'd train a supervised model. Right now, the weighted formula + log transform gives meaningful, trustworthy differentiation across the partner base.

### Degrowth threshold — why is it state-level?

```
degrowth_threshold = 70th percentile of revenue drop % within the state
(clamped between 10% and 40%)
```

A 30% revenue drop in Maharashtra is different from a 30% drop in a smaller state where market fluctuations are naturally larger. By computing the threshold at state level from actual data, a partner in a high-volatility region isn't penalised for normal seasonal swings.

---

## Section 2 — Churn Probability

**File:** `ml_engine/churn_credit_stub_mixin.py` → `_score_churn_rule_based()`

### What it measures

The probability (0 to 1) that a partner will stop ordering in the next 90 days. Three bands: Low (< 45%), Medium (45–70%), High (> 70%).

### The formula

```
Churn Score = w₁ × rev_drop
            + w₂ × log_recency
            + w₃ × CoV (volatility ratio)
            + w₄ × growth_risk
            + w₅ × txn_drop
```

Where:
- `rev_drop` = revenue drop % ÷ 100, clipped 0–1
- `log_recency` = log(1 + recency_days) ÷ log(1 + 730), clipped 0–1
- `CoV` = revenue_volatility ÷ recent_90d_revenue, normalised to 0–1
- `growth_risk` = (1 − growth_rate_90d) ÷ 2
- `txn_drop` = (prev_txns − recent_txns) ÷ prev_txns, clipped 0–1

### How weights are computed (the calibration step)

The weights (w₁ through w₅) are NOT hardcoded guesses anymore. We compute them fresh each session using **point-biserial correlation**:

1. Pull 12–15 months of monthly revenue history per partner
2. For any partner who was active in month M but had zero revenue in month M+3, label them `churn = 1`, else `churn = 0`
3. Compute the correlation between each feature and the churn label
4. Normalise the absolute correlation values so they sum to 1.0

```
w_feature = |corr(feature, churn_label)| / Σ|corr(all features, churn_label)|
```

If there aren't enough churn samples (< 20 total, or < 5 churned), we fall back to sensible defaults:
`{rev_drop: 0.30, recency: 0.25, growth: 0.20, volatility: 0.15, txn_drop: 0.10}`

### Why do we have XGBoost code but not use it?

We trained an XGBoost model on historical data, but when scoring current (active) partners, it predicted ~1% churn probability for almost everyone. That's because it was trained on "zero revenue = churned", and all active partners have some revenue. Gradient boosted trees are excellent but they need a clean, well-defined label, and "this partner is going to churn in the next quarter" is hard to define precisely without historical churn events. The rule-based scoring, calibrated with real correlations, gives far more useful differentiation for actual sales decisions.

### Revenue at risk formula

```
Revenue at risk (90d) = churn_probability × recent_90d_revenue
Revenue at risk (monthly) = churn_probability × recent_90d_revenue ÷ 3
```

This is intentionally simple and easy to explain: if there's a 60% chance a partner generating Rs 5L in revenue stops ordering, Rs 3L of that revenue is at risk. A sales rep can understand and trust that number.

### What could we use instead?

- **Survival Analysis (Kaplan-Meier / Cox)**: Great for "time to churn" estimates. We have the infrastructure in place (`survival_model` in the engine config) but haven't trained it yet because we'd need clean event data (first order date, last order date, confirmed churned Y/N per partner).
- **Deep learning (LSTM on order sequences)**: Works well when orders are frequent and the sequence matters. Our B2B partners place orders monthly or quarterly — too sparse for sequence models to be meaningful.
- **Current approach**: Best available given our data. The calibrated correlation weights distinguish it from a naive rule.

---

## Section 3 — 30-Day Revenue Forecast

**File:** `ml_engine/churn_credit_stub_mixin.py` → `_build_partner_forecast()`

### The formula

```
Forecast_30d = (recent_90d_revenue ÷ 3) × (1 + growth_rate_90d ÷ 3)
Confidence   = 0.75 if partner has ≥ 6 months history, else 0.45
```

This is a linear trend projection. It takes the monthly revenue rate and applies the 90-day growth trend proportionally. It's deliberately simple and honest about its uncertainty.

### Why not a proper time-series model like ARIMA or Prophet?

We actually do load monthly revenue history (`_load_monthly_revenue_history`), so the data exists for a more sophisticated model. The reason we use linear projection here is reliability. Monthly B2B order data is lumpy — a distributor might place one big order in January and nothing until March. ARIMA would try to fit a pattern that doesn't exist. Prophet handles seasonality well but needs 2+ years of clean data with minimal gaps to be trustworthy. Until we build proper model validation pipelines, the linear projection is honest and explainable. When wrong, it's wrong in an obvious way.

### Improvement: this should be next on the roadmap

Once we have 2+ full years of monthly history for most partners, we should implement Prophet-based forecasting with:
- Yearly seasonality (festival buying patterns, harvest seasons etc.)
- Per-partner trend components
- Holiday/event calendars for Indian distribution markets

The database query for this already exists. It's an execution priority, not a technical blocker.

---

## Section 4 — Partner Clustering (Segmentation)

**File:** `ml_engine/clustering_mixin.py`

### What it does

Groups all partners into segments based on their purchasing behaviour. This drives the "Peer Gap Analysis" — we can only compare a partner to similar partners if we first know which group they belong to.

### The pipeline: PCA → UMAP → HDBSCAN/GMM

**Step 1: Feature groups**

Partners are described by spend across several category groups (spend_telecom, spend_handsets, spend_accessories, etc.) plus RFM signals. These features are organised into weighted groups:

```
Category spend features  → PCA (reduces from 20+ columns to ~5 dimensions)
                         → Weighted by 1.0 (equal importance)
RFM features (recency, frequency, monetary) → PCA → Weighted by 0.8
```

**Step 2: PCA (Principal Component Analysis)**

Within each feature group, we compress correlated features into fewer dimensions. For example, if a partner buys heavily in Mobiles, they probably also buy accessories — PCA captures this correlation and reduces it to one "mobile buyer" axis.

```
n_components = min(available_features, n_partners ÷ 6, 8)
```

**Step 3: UMAP (Uniform Manifold Approximation and Projection)**

UMAP is a non-linear dimensionality reduction — it can find curved shapes in data that PCA can't. Think of PCA as flattening a 3D shape onto 2D, and UMAP as being able to "unfold" that shape first before flattening.

Key parameter decisions:

```
n_neighbors = max(5, min(30, √n_partners))
  → √n gives statistically sound local-global balance
  → e.g., for 100 partners: n_neighbors = 10
  → for 400 partners: n_neighbors = 20

min_dist:
  < 50 partners  → 0.10  (spread out, avoid compression in small datasets)
  50–200         → 0.05  (balanced)
  200+           → 0.01  (tighter clusters, more separation)
```

The old version hardcoded `n_neighbors=15, min_dist=0.10`, which worked fine at 100 partners but produced overlapping clusters at 300+ partners. The square-root formula is a standard recommendation from the UMAP authors.

**Step 4: HDBSCAN + GMM**

Two algorithms are run and compared:
- **HDBSCAN** (density-based): finds clusters of arbitrary shapes. Good for finding outliers ("unusual" partners who don't fit any pattern).
- **GMM** (Gaussian Mixture Model): assumes partners can be partially in multiple clusters. Good for smooth distributions.

The better result (by Silhouette Score) wins. This is called "algorithm competition" and ensures we're not locked into one method's assumptions.

**Step 5: VIP vs Growth classification**

After clustering, each partner is assigned a tier:

```
VIP   = top 80th percentile of revenue AND cluster contributes 20–45% of total revenue
Growth = everyone else
```

This ensures our "VIP" label actually means something commercially — it's not just the biggest cluster, it's the partners who drive most of the business.

### Business cluster labels

Old labels looked like: `VIP-0`, `Growth-2` — useless to a sales manager.

New labels use business archetypes matched against centroid profiles:

| Cluster Profile | Label |
|---|---|
| VIP + High spend + Diversified purchase mix | Strategic Accounts |
| VIP + High spend + Concentrated in one category | Category Champions |
| VIP + Medium spend + Diversified | Emerging Power Buyers |
| Growth + Low spend, inactive recently | Win-Back Targets |
| Growth + High spend + Single category focus | Niche Power Players |

The matching logic reads the centroid profile description (text generated from the cluster's average feature values) and finds the closest archetype. If an OpenAI API key is configured, a language model can generate even richer descriptions. If not, the heuristic match works reliably.

### What could we use instead?

- **K-Means**: Simple, fast, but assumes circular clusters and requires you to specify the number of clusters upfront. Our B2B data has natural outliers (unusual partners) and the number of natural segments changes as the partner base grows — K-Means doesn't handle this well.
- **Hierarchical clustering**: Good for seeing how clusters nest inside each other. Computationally expensive at scale. Better for offline analysis than real-time dashboards.
- **Current HDBSCAN + GMM competition**: Recommended approach for mixed B2B data. The quality scores (Silhouette, Calinski-Harabasz) tell us objectively which model performs better.

### Cluster quality validation

Every time clustering runs, it computes and logs:
- **Silhouette Score**: Are clusters well-separated? (range: -1 to 1, higher is better, > 0.4 is good)
- **Calinski-Harabasz Index**: Ratio of between-cluster to within-cluster variance (higher is better)
- **Stability (ARI)**: Run 80% bootstrap samples 5 times and compare results. If clusters are stable, ARI ≈ 1. Unstable clusters are flagged.

---

## Section 5 — Peer Gap Analysis (Cross-Sell Identification)

**File:** `ml_engine/base_loader_mixin.py` + the gap computation in `ClusteringMixin`

### What it does

Compares this partner's spend in each product category against the average of their cluster peers. If peers spend 18% of revenue on Category X but this partner only spends 5%, there's a 13% gap — a cross-sell opportunity.

### The formula

```
Gap % = Others_Do_Pct − You_Do_Pct    (floored at 0 — can't have negative gap)

Potential Revenue (monthly) = Gap % × Peer_Avg_Monthly_Spend_In_Category

Potential Revenue (yearly) = Potential Revenue (monthly) × 12
```

**Peer_Avg_Spend** is computed from partners in the same cluster with a minimum basket size — we exclude micro-buyers who would pull the peer average down unrealistically.

### Why compare only within the cluster?

A small regional distributor should not be benchmarked against a national key account. Clustering ensures the comparison is always like-for-like. If a partner's cluster peers average Rs 50K/month on smartphones and this partner spends Rs 10K, the Rs 40K gap is realistic because the peers are genuinely similar in size and buying profile.

### High/Medium/Low priority tiering

```
High Priority   = monthly gap > Rs 50,000
Medium Priority = monthly gap Rs 10,000 – 50,000
Low Priority    = monthly gap < Rs 10,000 (shown in collapsible section)
```

These thresholds are business-defined and reflect what's worth a sales call vs a passing mention. They should be reviewed periodically.

---

## Section 6 — Market Basket Analysis / Product Affinity (FP-Growth)

**File:** `ml_engine/associations_mixin.py`

### What it does

Finds products that are frequently bought together. If 70% of partners who buy Product A also buy Product B in the same month, we should be pitching Product B to any partner who buys Product A but hasn't tried Product B yet.

### The algorithm: FP-Growth

FP-Growth (Frequent Pattern Growth) is the industry standard for association rule mining. It's faster than the older Apriori algorithm because it represents the transaction database as a compressed tree rather than scanning it repeatedly.

**Key output metrics:**
- **Support**: How often does this product pair appear? (% of all baskets)
- **Confidence**: Of all baskets containing Product A, what % also contain Product B?
- **Lift**: How much more likely are A and B to co-occur compared to random chance?

```
Lift = P(A and B) / (P(A) × P(B))

Lift > 1 = positive association (they tend to go together)
Lift = 1 = no relationship
Lift < 1 = negative association (buying A makes B less likely)
```

We use `Lift > 1.1` and `Confidence > 15%` as minimum thresholds.

### The adaptive support problem — why we fixed it

The original code used a static `min_support = 2%`, meaning a product pair had to appear in at least 2% of all monthly baskets to be considered. In a B2B dataset with 200 partners and 50 products, each partner buys maybe 3–5 products per month. The data is sparse by design.

With 200 baskets and 50 products, a static 2% threshold means a pair needs to appear in at least 4 baskets — which sounds low, but because of sparsity it eliminates many real signals.

**New adaptive formula:**

```
sparsity = actual_pair_co-occurrences / max_possible_pair_co-occurrences

if sparsity < 0.10:  min_support = max(0.005, 2 / n_baskets)   # at least 2 occurrences
if sparsity 0.10–0.30: min_support = 0.01
if sparsity > 0.30:  min_support = 0.02   (standard)
```

This means in a sparse dataset (most B2B data is), the threshold automatically relaxes to ensure we don't miss patterns. The support floor of `2/n_baskets` guarantees we always require at least 2 real co-occurrences — we never report a "rule" based on a single coincidence.

### What could we use instead?

- **Collaborative filtering**: Instead of "products that go together", it asks "partners who are similar also buy X". This is what Netflix-style recommendation engines use. Better for large, dense datasets; our sparse data makes matrix factorisation noisy.
- **Apriori**: The older version of FP-Growth. Slower (especially for large datasets) but identical results. We try FP-Growth first and fall back to Apriori if it's not installed.

---

## Section 7 — Credit Risk Scoring

**File:** `ml_engine/churn_credit_stub_mixin.py` → `_load_credit_risk_features()` + `_load_due_payment_signals()`

### What it measures

The probability that a partner becomes a credit risk (fails to pay on time, or has large outstanding amounts). Range: 0 to 1, three bands — Low (< 40%), Medium (40–67%), High (> 67%).

### Three-tier logic

**Tier 1 (Best): Real AR data from `view_partner_credit_risk_score`**

If the database view is available and has real overdue data (max score > 0.05), we use it directly. This view already computes overdue ratios, aging buckets (0–30d, 31–60d, 61–90d, 91–120d, 120d+), credit utilisation, and payment trend direction. This is ground truth.

```sql
credit_risk_score = (already computed in the view from actual collections data)
```

**Tier 2 (Enhanced proxy): `due_payment` table signals**

When the view shows all zeros (no old/overdue data yet), we compute from the `due_payment` table directly:

```
Credit Risk = 0.35 × payment_delay_ratio
            + 0.25 × overdue_outstanding_norm
            + 0.20 × revenue_concentration_risk
            + 0.20 × revenue_drop_pct (lagging signal)
```

Where:
```
payment_delay_ratio = (avg_payment_days - assigned_credit_days) / assigned_credit_days
                      clipped to [0, 1]

overdue_outstanding_norm = outstanding_unpaid_amount / recent_90d_revenue

revenue_concentration_risk = 1 / category_count   (single category = fragile)
```

**Why payment_delay_ratio gets the highest weight (35%)**

Revenue drop is a lagging signal — by the time revenue drops, the credit event has often already happened. Payment age is a leading signal: a partner who consistently pays 15 days after their 30-day credit window is already showing stress. We want to catch it before it becomes a bad debt.

**Tier 3 (Last resort): Pure revenue-based proxy**

If even the due_payment table isn't accessible:
```
Credit Risk = 0.40 × rev_drop + 0.35 × recency + 0.25 × CoV
```

This is the weakest version because it uses no payment data at all. It can still differentiate partners who have stopped ordering (high credit risk in distribution businesses, because it often precedes payment disputes) but it can't detect partners who are still ordering but paying late.

### Credit Adjusted Risk Value

```
Credit Adjusted Risk Value = credit_risk_score × recent_90d_revenue
```

This is the money-weighted risk number. A partner with 80% credit risk and Rs 50K revenue has a credit adjusted risk of Rs 40K — the actual amount at risk. Much more useful for collections prioritisation than the score alone.

### What could we use instead?

- **Altman Z-Score**: Classic corporate credit scoring formula using financial ratios. Requires balance sheet data we don't have (assets, liabilities).
- **Machine learning on payment history**: With enough overdue events labelled in the payment history, we could train a logistic regression or gradient boosted model. Strong candidate once we have 12+ months of `due_payment` data with sufficient overdue events.
- **Current approach**: The due_payment enhanced proxy is meaningfully better than the revenue proxy and is already a production improvement.

---

## Section 8 — Product Lifecycle Staging

**File:** `ml_engine/product_lifecycle_mixin.py`

### What it does

Classifies every product the company sells into a lifecycle stage: **Growing, Mature, Plateauing, Declining, End-of-Life**. Sales reps should pitch Growing products aggressively, defend Mature ones, and phase out End-of-Life items.

### The velocity score formula

```
Velocity Score = 0.35 × (slope_per_month_pct / 10)    # Monthly revenue slope
               + 0.30 × (growth_3m_pct / 50)            # Recent 3-month growth %
               + 0.20 × (buyer_trend / 2)                # Trend in number of buyers
               + 0.15 × (txn_trend / 5)                  # Trend in transaction count
```

Each component is normalised (clipped to [-1, 1]) before combining.

`slope_per_month` comes from a linear regression (`np.polyfit`) over the product's monthly revenue history. It's the best-fit line through all historical monthly revenue points — the slope tells you whether revenue is genuinely trending up or down over time.

### Data-driven stage boundaries (the key calibration)

Old system used fixed thresholds: `velocity >= 0.3 → Growing`. The problem: if all products in a category are declining (e.g., feature phones post-smartphone), every product gets classified as "Declining" or "End-of-Life" even though some are doing relatively well. Fixed thresholds have no context.

New system computes boundaries from the actual distribution of velocity scores:

```
v_p80 = 80th percentile of velocity scores in this dataset  →  Growing floor
v_p50 = median                                               →  Mature floor
v_p25 = 25th percentile                                     →  Declining start
v_p10 = 10th percentile                                     →  End-of-Life ceiling

(v_p80 is clamped ≥ 0.05 — "Growing" must have genuinely positive momentum)
(v_p10 is clamped ≤ -0.05 — "End-of-Life" must be genuinely negative)
```

### Slope + Acceleration signals

We also compute an acceleration signal:

```
acceleration = growth_3m_pct − growth_rate_90d × 100

positive acceleration = product is speeding up (3m better than 6m)
negative acceleration = product is decelerating (3m worse than 6m)
```

Classification rules:
| Condition | Stage |
|---|---|
| v < v_p10 AND recency > 180 days | End-of-Life |
| v ≥ v_p80 AND growth ≥ g_p70 AND accel ≥ 0 | Growing |
| v ≥ v_p50 AND growth ≥ g_p30 AND peak_dist < 20% | Mature |
| v ≥ v_p25 AND peak_dist < 30% AND accel < 0 | Plateauing |
| v ≥ v_p10 OR growth < g_p30 | Declining |
| otherwise | End-of-Life |

---

## Section 9 — Recommendations & Confidence Scores

**File:** `ml_engine/recommendation_mixin.py`

### How a recommendation is built

For each partner, the engine checks five signal types and generates a recommended action for each:

| Signal | Action Type | Priority Score |
|---|---|---|
| High peer gap product found | Cross-sell Upsell | 55 + gap_size × 0.00025 |
| Strong FP-Growth affinity (confidence ≥ 0.10 or lift ≥ 1.1) | Affinity Bundle | 58 + conf × 30 + lift bonus |
| Health segment At Risk or Churn > 45% | Retention Intervention | 70 + monthly_loss / 100K |
| Credit risk > 55% | Credit-safe Action | 65 + credit_score × 40 |
| VIP partner with Champion/Healthy segment | Strategic Expansion | 52–60 |
| Any active alert | Alert-led Escalation | 75 + severity |

Actions are deduplicated (highest score per type wins) and ranked descending by priority score.

### Confidence, Similar Partners, and Expected Uplift

As of the current build, every recommendation carries three additional business-facing signals:

**Confidence %:**
```
confidence_pct = 50 + (priority_score / 100) × 47
```
Maps the priority score (0–100) to an interpretable confidence range (50–97%). A recommendation with priority_score = 80 has 87.6% confidence.

**Similar Partners (N peers):**
```
n_similar = count of partners in same cluster with same cluster_label

For retention/credit actions: effective = n_similar × 0.40
  (roughly 40% of cluster is at-risk at any given time)

For cross-sell/affinity: effective = n_similar × 0.75
  (gap exists for most healthy cluster peers too)
```

**Expected Uplift/Month:**
First tries to extract a monetary figure from the recommendation text (e.g., "estimated monthly upside Rs 1,20,000"). Falls back to:
```
uplift = (recent_90d_revenue ÷ 3) × (priority_score ÷ 100) × 0.15
```
i.e., 15% of monthly revenue × confidence. This is conservative and intended to be a floor estimate, not a projection.

### The SPIN selling script

SPIN (Situation, Problem, Implication, Need-Payoff) is a structured sales methodology. The dashboard auto-generates a SPIN script personalised to each partner using their actual data:

- **Situation**: Opens with what we know — recency, cluster type, state
- **Problem**: If revenue dropped > 5%, addresses the drop directly. If gap exists, mentions the missing category. If neither, probes for hidden friction.
- **Implication**: Quantifies what the gap or churn risk means in money terms
- **Need-Payoff**: Closes with a specific trial offer, no minimum commitment

The script is generated in Python, not by an AI model, so it's instant, deterministic, and doesn't cost API tokens. It's designed to sound like a prepared sales rep, not a robotic script.

---

## Section 10 — Natural Language Query

**File:** `ml_engine/recommendation_mixin.py` → `query_recommendations_nl()`

### What it does

The sales manager can type a query like "show me top 20 VIP partners with high churn risk in Maharashtra" and the system returns a ranked list of partners matching those criteria, with recommended actions.

### How it works

Two-stage parsing:

1. **Heuristic parser**: Regex and keyword matching. Picks up state names, cluster types, churn/credit thresholds, health segments, and limit numbers from the query text.

2. **OpenAI fallback**: If an API key is configured, sends the query to GPT to convert it to a structured JSON filter. The result is merged on top of the heuristic output (GPT is used to patch, not replace, the heuristic).

The heuristic parser works well for common query patterns and has no running cost. GPT handles edge cases and complex queries.

---

## Section 11 — Alerts

The engine monitors six trigger conditions per partner and fires alerts:

| Alert | Trigger |
|---|---|
| Sharp revenue drop | Revenue drop % ≥ configured threshold (default 35%) |
| High churn | Churn probability ≥ 45% |
| Churn jump | Churn probability increased by ≥ 15% vs previous snapshot |
| High credit risk | Credit score ≥ 55% |
| Credit jump | Credit score increased by ≥ 15% vs previous snapshot |
| Zero revenue after active history | recent_90d = 0, prev_90d > 0 |

Alerts are stored per partner and surfaced in the Partner 360 view. They also influence recommendation priority — an alert-triggered recommendation automatically gets priority ≥ 75.

---

## What We Should Improve Next

This section is honest about where we are and where the model needs to go.

### 1. Revenue Forecast → Prophet Time-Series Model
**Current state:** Linear projection from 90-day growth rate.
**Why it's limited:** Can't capture seasonality (festival buying, harvest cycles). Gives the same forecast gradient regardless of months of data available.
**What to do:** Implement Facebook Prophet on the monthly revenue history already loaded by `_load_monthly_revenue_history()`. Requires 2+ years of history for most partners.
**Expected impact:** More accurate 30/60/90 day forecasts. Better revenue planning conversations with partners.

### 2. Churn Model → Supervised Learning (once we have labelled events)
**Current state:** Calibrated rule-based with correlation-derived weights.
**Why it's limited:** Cannot learn interaction effects between signals (e.g., "low recency + high credit risk together are more dangerous than either alone").
**What to do:** Export the auto-generated churn labels, clean them manually for the top 200 partners, and train an XGBoost or LightGBM classifier with SHAP explanations.
**Expected impact:** Better prediction accuracy. SHAP values would let us tell a sales rep exactly WHY a partner is flagged (e.g., "primary driver is 200-day absence, secondary driver is 40% revenue drop").

### 3. Credit Risk → Proper AR Aging Validation
**Current state:** Falls back to payment-delay proxy when the AR view returns all zeros.
**What to do:** Work with the collections team to validate that `due_payment` contains complete overdue history. Once confirmed, the Tier 1 view becomes the primary scorer for everyone.
**Expected impact:** Credit scores become forensically accurate — backed by actual receivables data, not proxies.

### 4. Recommendation Engine → Reinforcement Learning (Bandit)
**Current state:** Rule-based priority scores. No feedback loop — we don't know if reps acted on recommendations or if they resulted in sales.
**What to do:** Log recommendation events (which partner, which action, which rep) and outcomes (did revenue increase next month?). Use a multi-armed bandit (e.g., Thompson Sampling) to gradually shift weight toward recommendations that actually convert.
**Expected impact:** Recommendations improve over time with actual sales data rather than staying static.

### 5. Partner Similarity → Embedding Store
**Current state:** Peer comparison is cluster-based only.
**What to do:** Compute a learned embedding (similar to word2vec but for partners) and store in a vector database. Enable "find the 10 most similar partners to X" without clustering boundaries.
**Expected impact:** More precise peer gap analysis, especially for outlier partners who don't cleanly fit any cluster.

---

## Configuration Reference

All key thresholds are configurable via environment variables — nothing is buried in code.

| Parameter | Default | What it controls |
|---|---|---|
| `CHURN_PROB_HIGH` | 0.65 | Threshold for "High" churn band |
| `CHURN_PROB_MEDIUM` | 0.35 | Threshold for "Medium" churn band |
| `CREDIT_RISK_HIGH` | 0.67 | Threshold for "High" credit band |
| `CREDIT_RISK_MEDIUM` | 0.40 | Threshold for "Medium" credit band |
| `ALERT_REVENUE_DROP_SHARP_PCT` | 35.0 | Revenue drop % that triggers an alert |
| `ALERT_CHURN_HIGH_LEVEL` | 0.45 | Churn threshold for risk warning |
| `ALERT_CREDIT_HIGH_LEVEL` | 0.55 | Credit threshold for risk warning |
| `GAP_LOOKBACK_DAYS` | 365 | Window for peer gap computation |
| `MBA_LOOKBACK_MONTHS` | 12 | Window for FP-Growth basket analysis |
| `CHURN_HISTORY_MONTHS` | 15 | History depth for churn label generation |
| `CLUSTER_VIP_PERCENTILE` | 0.80 | Revenue percentile to qualify for VIP |
| `FAST_MODE` | true | Skip full churn scoring for dashboard speed |

---

## Database Dependencies

| Table / View | Used For |
|---|---|
| `transactions_dsr` | All revenue and order history |
| `transactions_dsr_products` | Product-level revenue and category data |
| `master_party` | Partner master (company_name, state_id) |
| `master_products` | Product groupings (group_id = category) |
| `master_state` | State names |
| `due_payment` | Credit risk — payment age, overdue amounts |
| `view_ml_input` | Pre-aggregated ML feature input (optional) |
| `view_partner_credit_risk_score` | Credit risk — real AR data (optional) |

---

## Business Impact Summary

The metrics on the Partner 360 screen translate directly to decisions a sales rep makes every day:

**Revenue protection:** The churn probability × revenue at risk number tells the rep which accounts to call first. A partner with 70% churn risk and Rs 10L/quarter in revenue = Rs 7L at risk. That's a next-morning call, not a next-week call.

**Revenue growth:** The peer gap analysis tells the rep what to pitch. Instead of "we have a new product, want to try it?", the rep can say: "Your peers in the same cluster average Rs 80K/month on Category X, you're at Rs 15K — here's what you're leaving on the table."

**Credit management:** The credit scores give collections a prioritised list instead of a flat spreadsheet. A partner appearing both on the high-churn list AND the high-credit-risk list is a collections priority, not just a sales priority.

**Sales efficiency:** The SPIN script means a rep spending 5 minutes on the dashboard before a call has a better opening 3 minutes than one who spent 30 minutes pulling spreadsheets. Scalable, consistent, data-backed talking points across a field force.

---

*Document prepared: April 2026 | Version 2.4 — Week 2 ML Calibration Complete*
*Covers: base_loader_mixin.py, churn_credit_stub_mixin.py, clustering_mixin.py, associations_mixin.py, product_lifecycle_mixin.py, recommendation_mixin.py, partner_360.py, kanban_pipeline.py, sales_model.py*
