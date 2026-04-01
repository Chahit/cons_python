-- ==============================================================
--  CONSISTENT AI — COMPLETE DATABASE SQL
--  Sales Intelligence Suite | Consistent Infosystems Pvt. Ltd.
--
--  This file contains ALL SQL used across the project:
--    1. Core Materialized Views (business intelligence views)
--    2. Application Tables (new tables created for this project)
--    3. Indexes (performance)
--    4. Queries used by the ML Engine (read queries)
--    5. Refresh & Governance Scripts
--
--  Database: PostgreSQL 14+
--  Run order: Section 2 → 3 → 1 → 4 → 5
-- ==============================================================


-- ==============================================================
--  SECTION 1: CORE MATERIALIZED VIEWS
--  These views pre-aggregate data for fast dashboard reads.
-- ==============================================================

-- --------------------------------------------------------------
-- 1A. view_ml_input
--     Per-partner feature matrix used by churn, credit, and
--     clustering models. Aggregates the last 90 days of approved
--     transactions into one row per partner.
-- --------------------------------------------------------------
CREATE MATERIALIZED VIEW IF NOT EXISTS view_ml_input AS
SELECT
    mp.company_name,
    mp.id                                           AS party_id,

    -- Revenue metrics
    COALESCE(SUM(tp.net_amt), 0)                    AS total_revenue,
    COALESCE(COUNT(DISTINCT t.id), 0)               AS order_count,
    COALESCE(AVG(tp.net_amt), 0)                    AS avg_order_value,

    -- Recency
    MAX(t.date)                                     AS last_order_date,
    CURRENT_DATE - MAX(t.date)                      AS recency_days,

    -- Product diversity (number of unique product groups purchased)
    COUNT(DISTINCT p.product_name)                  AS product_diversity,

    -- Credit proxy: average days column on the transaction
    AVG(NULLIF(CAST(t.days AS INTEGER), 0))         AS avg_payment_days

FROM master_party mp
LEFT JOIN transactions_dsr t
       ON t.party_id = mp.id
      AND LOWER(CAST(t.is_approved AS TEXT)) = 'true'
      AND t.date >= CURRENT_DATE - INTERVAL '90 days'
LEFT JOIN transactions_dsr_products tp
       ON tp.dsr_id = t.id
LEFT JOIN master_products p
       ON p.id = tp.product_id
GROUP BY mp.id, mp.company_name;


-- --------------------------------------------------------------
-- 1B. fact_sales_intelligence
--     Product-group level aggregates used by the Product
--     Lifecycle, Market Basket, and Inventory modules.
-- --------------------------------------------------------------
CREATE MATERIALIZED VIEW IF NOT EXISTS fact_sales_intelligence AS
SELECT
    p.product_name,
    SUM(tp.net_amt)                                 AS total_revenue,
    SUM(tp.qty)                                     AS total_qty_sold,
    COUNT(DISTINCT t.id)                            AS order_count,
    COUNT(DISTINCT t.party_id)                      AS unique_buyers,
    MAX(t.date)                                     AS last_sold_date,
    MIN(t.date)                                     AS first_sold_date,
    AVG(tp.net_amt)                                 AS avg_order_value,

    -- Recent 90-day window revenue (for lifecycle velocity)
    SUM(CASE
        WHEN t.date >= CURRENT_DATE - INTERVAL '90 days'
        THEN tp.net_amt ELSE 0
    END)                                            AS revenue_last_90d,

    -- Prior 90-day window revenue
    SUM(CASE
        WHEN t.date >= CURRENT_DATE - INTERVAL '180 days'
         AND t.date <  CURRENT_DATE - INTERVAL '90 days'
        THEN tp.net_amt ELSE 0
    END)                                            AS revenue_prev_90d

FROM transactions_dsr t
JOIN transactions_dsr_products tp ON tp.dsr_id = t.id
JOIN master_products p             ON p.id = tp.product_id
WHERE LOWER(CAST(t.is_approved AS TEXT)) = 'true'
GROUP BY p.product_name;


-- --------------------------------------------------------------
-- 1C. view_ageing_stock  (FIXED — real date-based calculation)
--     Dead stock detection: identifies products with stock
--     remaining and NO sale in the last 60+ days.
--     max_age_days = CURRENT_DATE - last transaction date for
--     each product (using approved transactions).
-- --------------------------------------------------------------
DROP MATERIALIZED VIEW IF EXISTS view_ageing_stock;
CREATE MATERIALIZED VIEW view_ageing_stock AS
WITH product_stock AS (
    -- Get current physical stock quantities per product (latest snapshot)
    SELECT
        p.id          AS product_id,
        p.product_name,
        (
            s.days_0_to_15_qty  + s.days_16_to_30_qty +
            s.days_31_to_60_qty + s.days_61_to_90_qty  + s.days_above_90_qty
        )             AS total_stock_qty,
        s.to_date     AS stock_snapshot_date
    FROM "apps.master.stockageing" s
    JOIN master_products p ON s.product_id = p.id
    WHERE s.disable = false OR s.disable IS NULL
),
latest_stock AS (
    -- Keep only the most recent snapshot per product
    SELECT DISTINCT ON (product_id)
        product_id,
        product_name,
        total_stock_qty,
        stock_snapshot_date
    FROM product_stock
    ORDER BY product_id, stock_snapshot_date DESC
),
last_sold AS (
    -- Most recent approved sale date per product
    SELECT
        tp.product_id,
        MAX(t.date)   AS last_sold_date
    FROM transactions_dsr_products tp
    JOIN transactions_dsr t ON tp.dsr_id = t.id
    WHERE LOWER(CAST(t.is_approved AS TEXT)) = 'true'
    GROUP BY tp.product_id
)
SELECT
    ls.product_name,
    ls.total_stock_qty,
    CASE
        WHEN s.last_sold_date IS NULL THEN
            -- Product was never sold: age from stock snapshot date
            GREATEST((CURRENT_DATE - ls.stock_snapshot_date), 0)
        ELSE
            -- Days since it was last sold (demand recency)
            GREATEST((CURRENT_DATE - s.last_sold_date), 0)
    END               AS max_age_days
FROM latest_stock ls
LEFT JOIN last_sold s ON ls.product_id = s.product_id
WHERE
    ls.total_stock_qty > 10
    AND (
        s.last_sold_date IS NULL                          -- never sold
        OR (CURRENT_DATE - s.last_sold_date) > 60        -- stale > 60 days
    )
ORDER BY max_age_days DESC;


-- --------------------------------------------------------------
-- 1D. view_stock_liquidation_leads
--     Joins dead stock items with partners who have historically
--     bought them, ranking potential liquidation buyers.
-- --------------------------------------------------------------
CREATE MATERIALIZED VIEW IF NOT EXISTS view_stock_liquidation_leads AS
SELECT
    vas.product_name            AS dead_stock_item,
    vas.total_stock_qty         AS qty_in_stock,
    vas.max_age_days,
    mp.company_name             AS potential_buyer,
    mp.id                       AS party_id,
    MAX(t.date)                 AS last_purchase_date,
    SUM(tp.qty)                 AS historical_qty_bought,
    SUM(tp.net_amt)             AS historical_revenue
FROM view_ageing_stock vas
JOIN master_products p   ON p.product_name = vas.product_name
JOIN transactions_dsr_products tp ON tp.product_id = p.id
JOIN transactions_dsr t  ON t.id = tp.dsr_id
                        AND LOWER(CAST(t.is_approved AS TEXT)) = 'true'
JOIN master_party mp     ON mp.id = t.party_id
GROUP BY
    vas.product_name, vas.total_stock_qty, vas.max_age_days,
    mp.company_name, mp.id
ORDER BY vas.max_age_days DESC, historical_revenue DESC;


-- --------------------------------------------------------------
-- 1E. view_product_associations
--     Pre-computed product co-purchase frequencies for the
--     Market Basket (MBA) module.
-- --------------------------------------------------------------
CREATE MATERIALIZED VIEW IF NOT EXISTS view_product_associations AS
SELECT
    p1.product_name             AS item_1,
    p2.product_name             AS item_2,
    COUNT(DISTINCT t.id)        AS times_bought_together,
    COUNT(DISTINCT t.party_id)  AS unique_buyers_together
FROM transactions_dsr t
JOIN transactions_dsr_products tp1 ON tp1.dsr_id  = t.id
JOIN transactions_dsr_products tp2 ON tp2.dsr_id  = t.id
                                   AND tp2.product_id > tp1.product_id   -- avoid duplicates
JOIN master_products p1             ON p1.id = tp1.product_id
JOIN master_products p2             ON p2.id = tp2.product_id
WHERE LOWER(CAST(t.is_approved AS TEXT)) = 'true'
GROUP BY p1.product_name, p2.product_name
HAVING COUNT(DISTINCT t.id) >= 2     -- minimum support threshold
ORDER BY times_bought_together DESC;


-- ==============================================================
--  SECTION 2: APPLICATION TABLES
--  New tables created for the Consistent AI project features.
-- ==============================================================

-- --------------------------------------------------------------
-- 2A. Cluster Governance
--     Tracks each ML clustering run, its parameters, quality
--     scores, and approval status.
-- --------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cluster_model_runs (
    id                      BIGSERIAL PRIMARY KEY,
    run_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status                  TEXT NOT NULL DEFAULT 'ok',
    approved                BOOLEAN NOT NULL DEFAULT FALSE,
    reject_reason           TEXT NULL,

    -- VIP cluster parameters and quality metrics
    vip_method              TEXT NULL,
    vip_chosen_k            INT NULL,
    vip_silhouette          DOUBLE PRECISION NULL,
    vip_calinski_harabasz   DOUBLE PRECISION NULL,
    vip_stability_ari       DOUBLE PRECISION NULL,

    -- Growth cluster parameters and quality metrics
    growth_method           TEXT NULL,
    growth_min_cluster_size INT NULL,
    growth_min_samples      INT NULL,
    growth_outlier_ratio    DOUBLE PRECISION NULL,
    growth_silhouette       DOUBLE PRECISION NULL,
    growth_calinski_harabasz DOUBLE PRECISION NULL,
    growth_stability_ari    DOUBLE PRECISION NULL,

    -- Global metrics
    global_outlier_ratio    DOUBLE PRECISION NULL,
    global_cluster_count    INT NULL
);

CREATE TABLE IF NOT EXISTS cluster_assignments (
    run_id          BIGINT NOT NULL REFERENCES cluster_model_runs(id) ON DELETE CASCADE,
    company_name    TEXT NOT NULL,
    cluster         INT NOT NULL,
    cluster_type    TEXT NOT NULL,           -- 'vip' | 'growth'
    cluster_label   TEXT NOT NULL,           -- 'VIP', 'At Risk', etc.
    strategic_tag   TEXT NOT NULL,
    PRIMARY KEY (run_id, company_name)
);


-- --------------------------------------------------------------
-- 2B. Competitor Intelligence
--     Stores competitor product pricing and auto-generated
--     price undercut alerts.
-- --------------------------------------------------------------
CREATE TABLE IF NOT EXISTS competitor_products (
    id              BIGSERIAL PRIMARY KEY,
    competitor_name TEXT NOT NULL,
    product_name    TEXT NOT NULL,
    product_group   TEXT NULL,
    unit_price      DOUBLE PRECISION NOT NULL DEFAULT 0,
    currency        TEXT NOT NULL DEFAULT 'INR',
    source          TEXT NULL,
    scraped_at      TIMESTAMPTZ NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (competitor_name, product_name)
);

CREATE TABLE IF NOT EXISTS our_product_pricing (
    id              BIGSERIAL PRIMARY KEY,
    product_name    TEXT NOT NULL UNIQUE,
    product_group   TEXT NULL,
    unit_price      DOUBLE PRECISION NOT NULL DEFAULT 0,
    cost_price      DOUBLE PRECISION NULL,
    margin_pct      DOUBLE PRECISION NULL,
    currency        TEXT NOT NULL DEFAULT 'INR',
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS competitor_price_alerts (
    id                  BIGSERIAL PRIMARY KEY,
    product_name        TEXT NOT NULL,
    competitor_name     TEXT NOT NULL,
    our_price           DOUBLE PRECISION NOT NULL,
    competitor_price    DOUBLE PRECISION NOT NULL,
    price_diff_pct      DOUBLE PRECISION NOT NULL,
    alert_type          TEXT NOT NULL DEFAULT 'undercut',
    severity            TEXT NOT NULL DEFAULT 'medium',
    is_resolved         BOOLEAN NOT NULL DEFAULT FALSE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at         TIMESTAMPTZ NULL
);


-- --------------------------------------------------------------
-- 2C. Real-time Scoring
--     Caches live partner churn / credit / forecast scores
--     computed by the background ML worker.
-- --------------------------------------------------------------
CREATE TABLE IF NOT EXISTS score_recompute_jobs (
    id              BIGSERIAL PRIMARY KEY,
    partner_name    TEXT NULL,
    reason          TEXT NOT NULL DEFAULT 'manual',
    status          TEXT NOT NULL DEFAULT 'pending',
    attempts        INT NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at      TIMESTAMPTZ NULL,
    finished_at     TIMESTAMPTZ NULL,
    error_message   TEXT NULL
);

CREATE TABLE IF NOT EXISTS partner_live_scores (
    partner_name                    TEXT PRIMARY KEY,
    churn_probability               DOUBLE PRECISION NOT NULL DEFAULT 0,
    churn_risk_band                 TEXT NOT NULL DEFAULT 'Unknown',
    expected_revenue_at_risk_90d    DOUBLE PRECISION NOT NULL DEFAULT 0,
    expected_revenue_at_risk_monthly DOUBLE PRECISION NOT NULL DEFAULT 0,
    forecast_next_30d               DOUBLE PRECISION NOT NULL DEFAULT 0,
    forecast_trend_pct              DOUBLE PRECISION NOT NULL DEFAULT 0,
    forecast_confidence             DOUBLE PRECISION NOT NULL DEFAULT 0,
    credit_risk_score               DOUBLE PRECISION NOT NULL DEFAULT 0,
    credit_risk_band                TEXT NOT NULL DEFAULT 'Unknown',
    credit_utilization              DOUBLE PRECISION NOT NULL DEFAULT 0,
    overdue_ratio                   DOUBLE PRECISION NOT NULL DEFAULT 0,
    outstanding_amount              DOUBLE PRECISION NOT NULL DEFAULT 0,
    credit_adjusted_risk_value      DOUBLE PRECISION NOT NULL DEFAULT 0,
    updated_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS recommendation_feedback_events (
    id                              BIGSERIAL PRIMARY KEY,
    partner_name                    TEXT NOT NULL,
    cluster_label                   TEXT NULL,
    cluster_type                    TEXT NULL,
    action_type                     TEXT NOT NULL,
    recommended_offer               TEXT NULL,
    action_sequence                 INT NULL,
    stage                           TEXT NOT NULL DEFAULT 'initial_pitch',
    channel                         TEXT NOT NULL DEFAULT 'whatsapp',
    tone                            TEXT NOT NULL DEFAULT 'formal',
    outcome                         TEXT NOT NULL,
    notes                           TEXT NULL,
    priority_score                  DOUBLE PRECISION NULL,
    confidence                      DOUBLE PRECISION NULL,
    lift                            DOUBLE PRECISION NULL,
    churn_probability               DOUBLE PRECISION NULL,
    credit_risk_score               DOUBLE PRECISION NULL,
    revenue_drop_pct                DOUBLE PRECISION NULL,
    expected_revenue_at_risk_monthly DOUBLE PRECISION NULL,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- ==============================================================
--  SECTION 3: INDEXES
--  Performance indexes for hot query paths.
-- ==============================================================

-- Transactions (most queried table)
CREATE INDEX IF NOT EXISTS idx_dsr_party_date_approved
ON transactions_dsr (party_id, date)
WHERE LOWER(CAST(is_approved AS TEXT)) = 'true';

CREATE INDEX IF NOT EXISTS idx_dsr_date_approved
ON transactions_dsr (date)
WHERE LOWER(CAST(is_approved AS TEXT)) = 'true';

CREATE INDEX IF NOT EXISTS idx_dsr_user_date
ON transactions_dsr (user_id, date);

-- Transaction line items
CREATE INDEX IF NOT EXISTS idx_dsr_products_dsr
ON transactions_dsr_products (dsr_id);

CREATE INDEX IF NOT EXISTS idx_dsr_products_product
ON transactions_dsr_products (product_id);

-- Cluster governance
CREATE INDEX IF NOT EXISTS idx_cluster_model_runs_run_at
ON cluster_model_runs (run_at DESC);

CREATE INDEX IF NOT EXISTS idx_cluster_model_runs_approved
ON cluster_model_runs (approved, run_at DESC);

CREATE INDEX IF NOT EXISTS idx_cluster_assignments_company
ON cluster_assignments (company_name);

-- Competitor intelligence
CREATE INDEX IF NOT EXISTS idx_competitor_products_product
ON competitor_products (product_name);

CREATE INDEX IF NOT EXISTS idx_competitor_products_competitor
ON competitor_products (competitor_name);

CREATE INDEX IF NOT EXISTS idx_competitor_products_group
ON competitor_products (product_group);

CREATE INDEX IF NOT EXISTS idx_our_product_pricing_group
ON our_product_pricing (product_group);

CREATE INDEX IF NOT EXISTS idx_price_alerts_unresolved
ON competitor_price_alerts (is_resolved, created_at DESC);

-- Real-time scoring
CREATE INDEX IF NOT EXISTS idx_score_recompute_jobs_status_created
ON score_recompute_jobs (status, created_at);

CREATE INDEX IF NOT EXISTS idx_partner_live_scores_updated_at
ON partner_live_scores (updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_reco_feedback_created_at
ON recommendation_feedback_events (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_reco_feedback_outcome_created
ON recommendation_feedback_events (outcome, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_reco_feedback_action_tone
ON recommendation_feedback_events (action_type, tone);


-- ==============================================================
--  SECTION 4: ML ENGINE READ QUERIES
--  Key SELECT queries run by the Python ML Engine at runtime.
--  (These are embedded in the Python mixins — listed here for
--   documentation and DBA reference.)
-- ==============================================================

-- ── 4A. Churn / Credit feature extraction ────────────────────
-- Used by churn_credit_mixin.py to get per-partner metrics
-- for the churn probability model.
SELECT
    t.party_id,
    mp.company_name,
    COALESCE(SUM(tp.net_amt), 0)                        AS total_revenue,
    COUNT(DISTINCT t.id)                                AS order_count,
    MAX(t.date)                                         AS last_order_date,
    CURRENT_DATE - MAX(t.date)                          AS recency_days,

    -- Revenue split: current vs prior 90-day window
    SUM(CASE WHEN t.date >= CURRENT_DATE - INTERVAL '90 days'
             THEN tp.net_amt ELSE 0 END)                AS revenue_curr,
    SUM(CASE WHEN t.date >= CURRENT_DATE - INTERVAL '180 days'
              AND t.date  < CURRENT_DATE - INTERVAL '90 days'
             THEN tp.net_amt ELSE 0 END)                AS revenue_prev,

    -- Revenue drop % (positive = declining)
    CASE
        WHEN SUM(CASE WHEN t.date >= CURRENT_DATE - INTERVAL '180 days'
                       AND t.date  < CURRENT_DATE - INTERVAL '90 days'
                      THEN tp.net_amt ELSE 0 END) > 0
        THEN (
            SUM(CASE WHEN t.date >= CURRENT_DATE - INTERVAL '180 days'
                      AND t.date  < CURRENT_DATE - INTERVAL '90 days'
                     THEN tp.net_amt ELSE 0 END)
            - SUM(CASE WHEN t.date >= CURRENT_DATE - INTERVAL '90 days'
                       THEN tp.net_amt ELSE 0 END)
        ) / SUM(CASE WHEN t.date >= CURRENT_DATE - INTERVAL '180 days'
                      AND t.date  < CURRENT_DATE - INTERVAL '90 days'
                     THEN tp.net_amt ELSE 0 END) * 100.0
        ELSE 0
    END                                                 AS revenue_drop_pct

FROM transactions_dsr t
JOIN transactions_dsr_products tp ON tp.dsr_id  = t.id
JOIN master_party mp               ON mp.id = t.party_id
WHERE LOWER(CAST(t.is_approved AS TEXT)) = 'true'
  AND t.date >= CURRENT_DATE - INTERVAL '180 days'
GROUP BY t.party_id, mp.company_name;


-- ── 4B. Market Basket transaction matrix ─────────────────────
-- Fetches all approved orders with their product groups for
-- MBA / Apriori analysis.
SELECT
    t.id            AS order_id,
    t.party_id,
    p.product_name  AS product_group
FROM transactions_dsr t
JOIN transactions_dsr_products tp ON tp.dsr_id = t.id
JOIN master_products p             ON p.id = tp.product_id
WHERE LOWER(CAST(t.is_approved AS TEXT)) = 'true'
ORDER BY t.id;


-- ── 4C. Partner-specific purchase history ────────────────────
-- Used by Recommendation Hub to get all products a specific
-- partner has bought for personalised pitch generation.
SELECT
    p.product_name,
    SUM(tp.qty)     AS qty_bought,
    SUM(tp.net_amt) AS revenue,
    MAX(t.date)     AS last_purchased
FROM transactions_dsr t
JOIN transactions_dsr_products tp ON tp.dsr_id  = t.id
JOIN master_products p             ON p.id = tp.product_id
JOIN master_party mp               ON mp.id = t.party_id
WHERE LOWER(CAST(t.is_approved AS TEXT)) = 'true'
  AND mp.company_name = :partner_name       -- parameterised
GROUP BY p.product_name
ORDER BY revenue DESC;


-- ── 4D. Product lifecycle revenue velocity ───────────────────
-- Computes month-by-month revenue per product for lifecycle
-- stage classification (Rising / Stable / Declining / At Risk).
SELECT
    p.product_name,
    DATE_TRUNC('month', t.date)     AS month,
    SUM(tp.net_amt)                 AS monthly_revenue,
    SUM(tp.qty)                     AS monthly_qty
FROM transactions_dsr t
JOIN transactions_dsr_products tp ON tp.dsr_id = t.id
JOIN master_products p             ON p.id = tp.product_id
WHERE LOWER(CAST(t.is_approved AS TEXT)) = 'true'
  AND t.date >= CURRENT_DATE - INTERVAL '12 months'
GROUP BY p.product_name, DATE_TRUNC('month', t.date)
ORDER BY p.product_name, month;


-- ── 4E. Degrowth backtest (Model Monitoring) ─────────────────
-- Evaluates churn/degrowth classifier quality against
-- historical data by comparing predicted vs realised decline.
SELECT
    t.party_id,
    t.date::date    AS tx_date,
    SUM(tp.net_amt) AS revenue
FROM transactions_dsr t
JOIN transactions_dsr_products tp ON t.id = tp.dsr_id
WHERE LOWER(CAST(t.is_approved AS TEXT)) = 'true'
GROUP BY t.party_id, t.date::date;


-- ── 4F. Sales Representative performance ─────────────────────
-- Used by Sales Rep Performance Tracker module to compute
-- orders, customers, and last order date per sales rep.
SELECT
    t.user_id,
    COUNT(t.id)             AS total_orders,
    COUNT(DISTINCT t.party_id) AS unique_customers,
    MAX(t.date)             AS last_order_date
FROM transactions_dsr t
WHERE LOWER(CAST(t.is_approved AS TEXT)) = 'true'
GROUP BY t.user_id;

-- Sales rep tour count
SELECT
    created_by_id           AS user_id,
    COUNT(id)               AS total_tours
FROM apps_tour_tourplan
GROUP BY created_by_id;

-- Sales rep expenses
SELECT
    created_by_id           AS user_id,
    SUM(amount)             AS total_expenses
FROM apps_tours_expense
GROUP BY created_by_id;

-- Issues logged per rep
SELECT
    created_by_id           AS user_id,
    COUNT(id)               AS issues_logged
FROM primary_dashboard_issue
GROUP BY created_by_id;


-- ── 4G. Competitor price gap analysis ────────────────────────
-- Computes price gap between competitor and Consistent pricing
-- for every matched product (negative = competitor is cheaper).
SELECT
    cp.product_name,
    cp.competitor_name,
    opp.unit_price          AS our_price,
    cp.unit_price           AS competitor_price,
    ROUND(
        ((cp.unit_price - opp.unit_price) / NULLIF(opp.unit_price, 0)) * 100.0,
        2
    )                       AS price_diff_pct,
    cp.scraped_at
FROM competitor_products cp
JOIN our_product_pricing opp ON LOWER(opp.product_name) = LOWER(cp.product_name)
ORDER BY price_diff_pct ASC;


-- ── 4H. Live score retrieval (chatbot / Partner 360) ─────────
-- Merges batch scores with live re-scored values for the most
-- up-to-date partner risk profile.
SELECT * FROM partner_live_scores
ORDER BY churn_probability DESC;

-- Pending recompute jobs queue
SELECT *
FROM score_recompute_jobs
WHERE status = 'pending'
ORDER BY created_at ASC
LIMIT 50;


-- ── 4I. Recommendation feedback loop ─────────────────────────
-- Reads past sales interaction outcomes for A/B analysis of
-- pitch effectiveness by tone, channel, and cluster type.
SELECT
    action_type,
    tone,
    channel,
    cluster_label,
    outcome,
    COUNT(*)                AS count,
    AVG(confidence)         AS avg_confidence
FROM recommendation_feedback_events
WHERE created_at >= NOW() - (:lookback_days * INTERVAL '1 day')
GROUP BY action_type, tone, channel, cluster_label, outcome
ORDER BY count DESC;


-- ==============================================================
--  SECTION 5: MATERIALIZED VIEW REFRESH SCHEDULE
--  Run these in order after any major data load / ETL cycle.
--  Recommended: schedule as a nightly cron job at 02:00 IST.
-- ==============================================================

-- Step 1 — refresh base views first (dependencies)
REFRESH MATERIALIZED VIEW view_ml_input;
REFRESH MATERIALIZED VIEW fact_sales_intelligence;

-- Step 2 — refresh views that depend on base views
REFRESH MATERIALIZED VIEW view_ageing_stock;
REFRESH MATERIALIZED VIEW view_stock_liquidation_leads;
REFRESH MATERIALIZED VIEW view_product_associations;

-- Step 3 — update statistics for query planner
ANALYZE transactions_dsr;
ANALYZE transactions_dsr_products;
ANALYZE master_products;
ANALYZE master_party;


-- ==============================================================
--  SECTION 6: USEFUL DIAGNOSTIC QUERIES
--  Run these to validate data health and debug issues.
-- ==============================================================

-- How many approved transactions do we have per month?
SELECT
    DATE_TRUNC('month', date) AS month,
    COUNT(*)                  AS order_count,
    COUNT(DISTINCT party_id)  AS active_partners,
    COUNT(DISTINCT user_id)   AS active_reps
FROM transactions_dsr
WHERE LOWER(CAST(is_approved AS TEXT)) = 'true'
GROUP BY DATE_TRUNC('month', date)
ORDER BY month DESC;

-- Top 10 dead stock items by age
SELECT product_name, total_stock_qty, max_age_days
FROM view_ageing_stock
ORDER BY max_age_days DESC
LIMIT 10;

-- Top 10 partners by churn risk
SELECT partner_name, churn_probability, churn_risk_band, forecast_next_30d
FROM partner_live_scores
ORDER BY churn_probability DESC
LIMIT 10;

-- Products that have never been sold
SELECT p.product_name, p.id
FROM master_products p
LEFT JOIN transactions_dsr_products tp ON tp.product_id = p.id
WHERE tp.id IS NULL;

-- Sales rep leaderboard (orders + expense efficiency)
SELECT
    au.first_name || ' ' || au.last_name    AS rep_name,
    COUNT(t.id)                             AS total_orders,
    COUNT(DISTINCT t.party_id)              AS unique_partners,
    COALESCE(SUM(e.amount), 0)              AS total_expenses,
    CASE WHEN COUNT(t.id) > 0
         THEN ROUND(COALESCE(SUM(e.amount), 0) / COUNT(t.id), 2)
         ELSE 0
    END                                     AS cost_per_order
FROM auth_user au
LEFT JOIN transactions_dsr t  ON t.user_id = au.id
                              AND LOWER(CAST(t.is_approved AS TEXT)) = 'true'
LEFT JOIN apps_tours_expense e ON e.created_by_id = au.id
GROUP BY au.id, au.first_name, au.last_name
ORDER BY total_orders DESC;

-- ==============================================================
--  END OF FILE
-- ==============================================================
