-- ==============================================================
--  SUPREME SCHEMA — Sales Intelligence Suite
--  Consistent Infosystems Pvt. Ltd.
--
--  This is the SINGLE authoritative SQL file for the entire system.
--  Contains every materialized view, application table, index,
--  and refresh command — in correct dependency order.
--
--  Run order:
--    STEP 1 → Application Tables (new tables for this project)
--    STEP 2 → Core Materialized Views (depend on source tables)
--    STEP 3 → Credit Risk Views (depend on billing tables)
--    STEP 4 → Indexes
--    STEP 5 → Refresh all views in dependency order
--
--  Database: PostgreSQL 14+
--  Source tables (195 total from DSR ERP):
--    transactions_dsr, transactions_dsr_products, master_party,
--    master_products, due_payment, due_payment_amount,
--    master_party_credit_details, due_advance_payment_dueadvancepayment,
--    apps.master.stockageing, apps_tour_tourplan, apps_tours_expense,
--    primary_dashboard_issue, auth_user, etc.
-- ==============================================================


-- ==============================================================
--  STEP 1 — APPLICATION TABLES
--  New tables created for the Sales Intelligence project.
--  These do NOT exist in the source ERP — create them first.
-- ==============================================================

-- ── 1A. Cluster Governance ────────────────────────────────────
-- Tracks each ML clustering run, quality scores, and approval.
CREATE TABLE IF NOT EXISTS cluster_model_runs (
    id                       BIGSERIAL PRIMARY KEY,
    run_at                   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status                   TEXT NOT NULL DEFAULT 'ok',
    approved                 BOOLEAN NOT NULL DEFAULT FALSE,
    reject_reason            TEXT NULL,
    vip_method               TEXT NULL,
    vip_chosen_k             INT NULL,
    vip_silhouette           DOUBLE PRECISION NULL,
    vip_calinski_harabasz    DOUBLE PRECISION NULL,
    vip_stability_ari        DOUBLE PRECISION NULL,
    growth_method            TEXT NULL,
    growth_min_cluster_size  INT NULL,
    growth_min_samples       INT NULL,
    growth_outlier_ratio     DOUBLE PRECISION NULL,
    growth_silhouette        DOUBLE PRECISION NULL,
    growth_calinski_harabasz DOUBLE PRECISION NULL,
    growth_stability_ari     DOUBLE PRECISION NULL,
    global_outlier_ratio     DOUBLE PRECISION NULL,
    global_cluster_count     INT NULL
);

CREATE TABLE IF NOT EXISTS cluster_assignments (
    run_id        BIGINT NOT NULL REFERENCES cluster_model_runs(id) ON DELETE CASCADE,
    company_name  TEXT NOT NULL,
    cluster       INT NOT NULL,
    cluster_type  TEXT NOT NULL,   -- 'vip' | 'growth'
    cluster_label TEXT NOT NULL,   -- 'VIP', 'At Risk', etc.
    strategic_tag TEXT NOT NULL,
    PRIMARY KEY (run_id, company_name)
);


-- ── 1B-2. Cluster Centroid History ─────────────────────────────
-- Stores centroid vectors after each run for drift detection.
CREATE TABLE IF NOT EXISTS cluster_centroids_history (
    id              BIGSERIAL PRIMARY KEY,
    run_id          BIGINT REFERENCES cluster_model_runs(id) ON DELETE CASCADE,
    tier            TEXT NOT NULL,          -- 'VIP' | 'Growth'
    cluster_label   TEXT NOT NULL,
    centroid_json   TEXT NOT NULL,          -- JSON array of float feature values
    feature_names   TEXT NOT NULL,          -- JSON array of feature names (same order)
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_centroids_label_recorded
    ON cluster_centroids_history (cluster_label, recorded_at DESC);


-- ── 1B-3. Cluster Drift Alerts ─────────────────────────────────
-- Records centroid drift alerts raised after comparing runs.
CREATE TABLE IF NOT EXISTS cluster_drift_alerts (
    id                   BIGSERIAL PRIMARY KEY,
    run_id               BIGINT REFERENCES cluster_model_runs(id) ON DELETE CASCADE,
    cluster_label        TEXT NOT NULL,
    drift_score          DOUBLE PRECISION NOT NULL,
    drift_threshold      DOUBLE PRECISION NOT NULL DEFAULT 0.25,
    top_drifted_features TEXT NOT NULL,     -- JSON array of feature names
    severity             TEXT NOT NULL DEFAULT 'medium',  -- 'medium' | 'high'
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_drift_alerts_run_id
    ON cluster_drift_alerts (run_id DESC);

CREATE INDEX IF NOT EXISTS idx_drift_alerts_severity
    ON cluster_drift_alerts (severity, created_at DESC);




-- ── 1B. Competitor Intelligence ───────────────────────────────
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
    id           BIGSERIAL PRIMARY KEY,
    product_name TEXT NOT NULL UNIQUE,
    product_group TEXT NULL,
    unit_price   DOUBLE PRECISION NOT NULL DEFAULT 0,
    cost_price   DOUBLE PRECISION NULL,
    margin_pct   DOUBLE PRECISION NULL,
    currency     TEXT NOT NULL DEFAULT 'INR',
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS competitor_price_alerts (
    id               BIGSERIAL PRIMARY KEY,
    product_name     TEXT NOT NULL,
    competitor_name  TEXT NOT NULL,
    our_price        DOUBLE PRECISION NOT NULL,
    competitor_price DOUBLE PRECISION NOT NULL,
    price_diff_pct   DOUBLE PRECISION NOT NULL,
    alert_type       TEXT NOT NULL DEFAULT 'undercut',
    severity         TEXT NOT NULL DEFAULT 'medium',
    is_resolved      BOOLEAN NOT NULL DEFAULT FALSE,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at      TIMESTAMPTZ NULL
);


-- ── 1C. Real-time Scoring ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS score_recompute_jobs (
    id            BIGSERIAL PRIMARY KEY,
    partner_name  TEXT NULL,
    reason        TEXT NOT NULL DEFAULT 'manual',
    status        TEXT NOT NULL DEFAULT 'pending',
    attempts      INT NOT NULL DEFAULT 0,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at    TIMESTAMPTZ NULL,
    finished_at   TIMESTAMPTZ NULL,
    error_message TEXT NULL
);

CREATE TABLE IF NOT EXISTS partner_live_scores (
    partner_name                     TEXT PRIMARY KEY,
    churn_probability                DOUBLE PRECISION NOT NULL DEFAULT 0,
    churn_risk_band                  TEXT NOT NULL DEFAULT 'Unknown',
    expected_revenue_at_risk_90d     DOUBLE PRECISION NOT NULL DEFAULT 0,
    expected_revenue_at_risk_monthly DOUBLE PRECISION NOT NULL DEFAULT 0,
    forecast_next_30d                DOUBLE PRECISION NOT NULL DEFAULT 0,
    forecast_trend_pct               DOUBLE PRECISION NOT NULL DEFAULT 0,
    forecast_confidence              DOUBLE PRECISION NOT NULL DEFAULT 0,
    credit_risk_score                DOUBLE PRECISION NOT NULL DEFAULT 0,
    credit_risk_band                 TEXT NOT NULL DEFAULT 'Unknown',
    credit_utilization               DOUBLE PRECISION NOT NULL DEFAULT 0,
    overdue_ratio                    DOUBLE PRECISION NOT NULL DEFAULT 0,
    outstanding_amount               DOUBLE PRECISION NOT NULL DEFAULT 0,
    credit_adjusted_risk_value       DOUBLE PRECISION NOT NULL DEFAULT 0,
    updated_at                       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS recommendation_feedback_events (
    id                               BIGSERIAL PRIMARY KEY,
    partner_name                     TEXT NOT NULL,
    cluster_label                    TEXT NULL,
    cluster_type                     TEXT NULL,
    action_type                      TEXT NOT NULL,
    recommended_offer                TEXT NULL,
    action_sequence                  INT NULL,
    stage                            TEXT NOT NULL DEFAULT 'initial_pitch',
    channel                          TEXT NOT NULL DEFAULT 'whatsapp',
    tone                             TEXT NOT NULL DEFAULT 'formal',
    outcome                          TEXT NOT NULL,
    notes                            TEXT NULL,
    priority_score                   DOUBLE PRECISION NULL,
    confidence                       DOUBLE PRECISION NULL,
    lift                             DOUBLE PRECISION NULL,
    churn_probability                DOUBLE PRECISION NULL,
    credit_risk_score                DOUBLE PRECISION NULL,
    revenue_drop_pct                 DOUBLE PRECISION NULL,
    expected_revenue_at_risk_monthly DOUBLE PRECISION NULL,
    created_at                       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- ==============================================================
--  STEP 2 — CORE MATERIALIZED VIEWS
--  Pre-aggregate data for fast dashboard reads.
--  These depend on source ERP tables only.
-- ==============================================================

-- ── 2A. view_ml_input ─────────────────────────────────────────
-- Per-partner feature matrix (last 90 days) used by churn,
-- credit, and clustering models.
DROP MATERIALIZED VIEW IF EXISTS view_ml_input CASCADE;
CREATE MATERIALIZED VIEW view_ml_input AS
SELECT
    mp.company_name,
    mp.id                                           AS party_id,
    COALESCE(SUM(tp.net_amt), 0)                    AS total_revenue,
    COALESCE(COUNT(DISTINCT t.id), 0)               AS order_count,
    COALESCE(AVG(tp.net_amt), 0)                    AS avg_order_value,
    MAX(t.date)                                     AS last_order_date,
    CURRENT_DATE - MAX(t.date)                      AS recency_days,
    COUNT(DISTINCT p.product_name)                  AS product_diversity,
    AVG(CASE WHEN t.days IS NOT NULL AND TRIM(t.days::TEXT) != ''
             THEN CAST(t.days AS INTEGER) ELSE NULL END) AS avg_payment_days
FROM master_party mp
LEFT JOIN transactions_dsr t
       ON t.party_id = mp.id
      AND LOWER(CAST(t.is_approved AS TEXT)) = 'true'
      AND t.date >= CURRENT_DATE - INTERVAL '90 days'
LEFT JOIN transactions_dsr_products tp ON tp.dsr_id = t.id
LEFT JOIN master_products p             ON p.id = tp.product_id
GROUP BY mp.id, mp.company_name;


-- ── 2B. fact_sales_intelligence ───────────────────────────────
-- Product-group level aggregates (current vs prior 90-day window).
DROP MATERIALIZED VIEW IF EXISTS fact_sales_intelligence CASCADE;
CREATE MATERIALIZED VIEW fact_sales_intelligence AS
SELECT
    p.product_name,
    SUM(tp.net_amt)                                 AS total_revenue,
    SUM(tp.qty)                                     AS total_qty_sold,
    COUNT(DISTINCT t.id)                            AS order_count,
    COUNT(DISTINCT t.party_id)                      AS unique_buyers,
    MAX(t.date)                                     AS last_sold_date,
    MIN(t.date)                                     AS first_sold_date,
    AVG(tp.net_amt)                                 AS avg_order_value,
    SUM(CASE WHEN t.date >= CURRENT_DATE - INTERVAL '90 days'
             THEN tp.net_amt ELSE 0 END)            AS revenue_last_90d,
    SUM(CASE WHEN t.date >= CURRENT_DATE - INTERVAL '180 days'
              AND t.date <  CURRENT_DATE - INTERVAL '90 days'
             THEN tp.net_amt ELSE 0 END)            AS revenue_prev_90d
FROM transactions_dsr t
JOIN transactions_dsr_products tp ON tp.dsr_id = t.id
JOIN master_products p             ON p.id = tp.product_id
WHERE LOWER(CAST(t.is_approved AS TEXT)) = 'true'
GROUP BY p.product_name;


-- ── 2C. view_ageing_stock ─────────────────────────────────────
-- Dead stock: products with stock remaining and no sale in 60+ days.
DROP MATERIALIZED VIEW IF EXISTS view_ageing_stock CASCADE;
CREATE MATERIALIZED VIEW view_ageing_stock AS
WITH product_stock AS (
    SELECT
        p.id          AS product_id,
        p.product_name,
        (s.days_0_to_15_qty  + s.days_16_to_30_qty +
         s.days_31_to_60_qty + s.days_61_to_90_qty  + s.days_above_90_qty)
                      AS total_stock_qty,
        s.to_date     AS stock_snapshot_date
    FROM "apps.master.stockageing" s
    JOIN master_products p ON s.product_id = p.id
    WHERE s.disable = false OR s.disable IS NULL
),
latest_stock AS (
    SELECT DISTINCT ON (product_id)
        product_id, product_name, total_stock_qty, stock_snapshot_date
    FROM product_stock
    ORDER BY product_id, stock_snapshot_date DESC
),
last_sold AS (
    SELECT tp.product_id, MAX(t.date) AS last_sold_date
    FROM transactions_dsr_products tp
    JOIN transactions_dsr t ON tp.dsr_id = t.id
    WHERE LOWER(CAST(t.is_approved AS TEXT)) = 'true'
    GROUP BY tp.product_id
)
SELECT
    ls.product_name,
    ls.total_stock_qty,
    CASE
        WHEN s.last_sold_date IS NULL
            THEN GREATEST((CURRENT_DATE - ls.stock_snapshot_date), 0)
        ELSE GREATEST((CURRENT_DATE - s.last_sold_date), 0)
    END AS max_age_days
FROM latest_stock ls
LEFT JOIN last_sold s ON ls.product_id = s.product_id
WHERE ls.total_stock_qty > 10
  AND (s.last_sold_date IS NULL OR (CURRENT_DATE - s.last_sold_date) > 60)
ORDER BY max_age_days DESC;


-- ── 2D. view_stock_liquidation_leads ──────────────────────────
-- Joins dead stock with partners who have historically bought them.
-- Includes state, product group/category, and purchase frequency.
DROP MATERIALIZED VIEW IF EXISTS view_stock_liquidation_leads CASCADE;
CREATE MATERIALIZED VIEW view_stock_liquidation_leads AS
SELECT
    vas.product_name                    AS dead_stock_item,
    vas.total_stock_qty                 AS qty_in_stock,
    vas.max_age_days,
    mp.company_name                     AS potential_buyer,
    mp.mobile_no                        AS mobile_no,
    mp.id                               AS party_id,
    COALESCE(ms.state_name, 'Unknown')  AS state_name,
    COALESCE(mg.group_name, 'General')  AS product_group,
    COALESCE(mpc.category_name, 'General') AS product_category,
    MAX(t.date)                         AS last_purchase_date,
    SUM(tp.qty)                         AS historical_qty_bought,
    COUNT(DISTINCT t.id)                AS purchase_txn_count,
    SUM(tp.net_amt)                     AS historical_revenue
FROM view_ageing_stock vas
JOIN master_products p             ON p.product_name = vas.product_name
LEFT JOIN master_group mg          ON p.group_id = mg.id
LEFT JOIN master_product_category mpc ON mg.category_id_id = mpc.id
JOIN transactions_dsr_products tp  ON tp.product_id  = p.id
JOIN transactions_dsr t            ON t.id = tp.dsr_id
                                  AND LOWER(CAST(t.is_approved AS TEXT)) = 'true'
JOIN master_party mp               ON mp.id = t.party_id
LEFT JOIN master_state ms          ON mp.state_id = ms.id
GROUP BY vas.product_name, vas.total_stock_qty, vas.max_age_days,
         mp.company_name, mp.mobile_no, mp.id,
         ms.state_name, mg.group_name, mpc.category_name
ORDER BY vas.max_age_days DESC, historical_revenue DESC;


-- ── 2E. view_product_associations ────────────────────────────
-- Pre-computed product co-purchase frequencies for Market Basket.
DROP MATERIALIZED VIEW IF EXISTS view_product_associations CASCADE;
CREATE MATERIALIZED VIEW view_product_associations AS
SELECT
    p1.product_name             AS item_1,
    p2.product_name             AS item_2,
    COUNT(DISTINCT t.id)        AS times_bought_together,
    COUNT(DISTINCT t.party_id)  AS unique_buyers_together
FROM transactions_dsr t
JOIN transactions_dsr_products tp1 ON tp1.dsr_id = t.id
JOIN transactions_dsr_products tp2 ON tp2.dsr_id = t.id
                                   AND tp2.product_id > tp1.product_id
JOIN master_products p1            ON p1.id = tp1.product_id
JOIN master_products p2            ON p2.id = tp2.product_id
WHERE LOWER(CAST(t.is_approved AS TEXT)) = 'true'
GROUP BY p1.product_name, p2.product_name
HAVING COUNT(DISTINCT t.id) >= 2
ORDER BY times_bought_together DESC;


-- ==============================================================
--  STEP 3 — CREDIT RISK MATERIALIZED VIEWS
--  These depend on billing tables: due_payment, due_payment_amount,
--  master_party_credit_details, due_advance_payment_dueadvancepayment.
--  Run AFTER Step 2.
-- ==============================================================

-- ── 3A. view_partner_ar_summary ───────────────────────────────
-- Real AR data per partner: outstanding, overdue, aging buckets,
-- payment speed trend. Sourced from actual billing tables.
DROP MATERIALIZED VIEW IF EXISTS view_partner_credit_risk_score CASCADE;
DROP MATERIALIZED VIEW IF EXISTS view_partner_ar_summary CASCADE;

CREATE MATERIALIZED VIEW view_partner_ar_summary AS
SELECT
    mp.company_name,
    t.party_id,
    COUNT(dp.id)                                        AS invoice_count,
    ROUND(COALESCE(SUM(dp.net_amt), 0)::NUMERIC, 2)    AS total_billed,
    ROUND(COALESCE(SUM(dpa.collected), 0)::NUMERIC, 2) AS total_collected,
    ROUND(GREATEST(COALESCE(SUM(dp.net_amt), 0)
                   - COALESCE(SUM(dpa.collected), 0), 0)::NUMERIC, 2)
                                                        AS outstanding_amount,

    -- Total overdue
    ROUND(COALESCE(SUM(
        CASE WHEN (dp.approve IS NULL OR dp.approve = FALSE)
              AND dp.bill_date::date + COALESCE(dp.credit_days, 0) < CURRENT_DATE
             THEN COALESCE(dp.net_amt, 0) ELSE 0 END
    ), 0)::NUMERIC, 2)                                  AS overdue_amount,

    COUNT(CASE
        WHEN (dp.approve IS NULL OR dp.approve = FALSE)
         AND dp.bill_date::date + COALESCE(dp.credit_days, 0) < CURRENT_DATE
        THEN 1 END)                                     AS overdue_invoice_count,

    -- Aging buckets (days overdue bands)
    ROUND(COALESCE(SUM(CASE
        WHEN (dp.approve IS NULL OR dp.approve = FALSE)
         AND (CURRENT_DATE - (dp.bill_date::date + COALESCE(dp.credit_days, 0)))
             BETWEEN 1 AND 30
        THEN COALESCE(dp.net_amt, 0) ELSE 0 END), 0)::NUMERIC, 2) AS overdue_0_30,

    ROUND(COALESCE(SUM(CASE
        WHEN (dp.approve IS NULL OR dp.approve = FALSE)
         AND (CURRENT_DATE - (dp.bill_date::date + COALESCE(dp.credit_days, 0)))
             BETWEEN 31 AND 60
        THEN COALESCE(dp.net_amt, 0) ELSE 0 END), 0)::NUMERIC, 2) AS overdue_31_60,

    ROUND(COALESCE(SUM(CASE
        WHEN (dp.approve IS NULL OR dp.approve = FALSE)
         AND (CURRENT_DATE - (dp.bill_date::date + COALESCE(dp.credit_days, 0)))
             BETWEEN 61 AND 90
        THEN COALESCE(dp.net_amt, 0) ELSE 0 END), 0)::NUMERIC, 2) AS overdue_61_90,

    ROUND(COALESCE(SUM(CASE
        WHEN (dp.approve IS NULL OR dp.approve = FALSE)
         AND (CURRENT_DATE - (dp.bill_date::date + COALESCE(dp.credit_days, 0)))
             BETWEEN 91 AND 120
        THEN COALESCE(dp.net_amt, 0) ELSE 0 END), 0)::NUMERIC, 2) AS overdue_91_120,

    ROUND(COALESCE(SUM(CASE
        WHEN (dp.approve IS NULL OR dp.approve = FALSE)
         AND (CURRENT_DATE - (dp.bill_date::date + COALESCE(dp.credit_days, 0))) > 120
        THEN COALESCE(dp.net_amt, 0) ELSE 0 END), 0)::NUMERIC, 2) AS overdue_120_plus,

    -- Payment speed (all-time)
    ROUND(COALESCE(AVG(
        CASE WHEN dp.approve = TRUE AND dp.payment_date IS NOT NULL
             THEN dp.payment_date::date - dp.bill_date::date END
    ), 0)::NUMERIC, 1)                                  AS avg_payment_days,

    -- Recent 3-month payment speed
    ROUND(COALESCE(AVG(
        CASE
            WHEN dp.approve = TRUE AND dp.payment_date IS NOT NULL
             AND dp.bill_date >= CURRENT_DATE - INTERVAL '90 days'
            THEN dp.payment_date::date - dp.bill_date::date
        END
    ), 0)::NUMERIC, 1)                                  AS payment_days_recent,

    -- Prior 3-month payment speed
    ROUND(COALESCE(AVG(
        CASE
            WHEN dp.approve = TRUE AND dp.payment_date IS NOT NULL
             AND dp.bill_date >= CURRENT_DATE - INTERVAL '180 days'
             AND dp.bill_date <  CURRENT_DATE - INTERVAL '90 days'
            THEN dp.payment_date::date - dp.bill_date::date
        END
    ), 0)::NUMERIC, 1)                                  AS payment_days_prev,

    MAX(dp.bill_date)                                   AS last_invoice_date,
    COALESCE(cl.credit_limit, 0)                        AS credit_limit,
    COALESCE(cl.max_credit_days, 0)                     AS assigned_credit_days,
    COALESCE(adv.total_advance, 0)                      AS advance_received,
    NOW()                                               AS refreshed_at

FROM due_payment dp
JOIN transactions_dsr t  ON t.id  = dp.dsr_id
JOIN master_party mp     ON mp.id = t.party_id

LEFT JOIN (
    SELECT due_payment_id, COALESCE(SUM(amount), 0) AS collected
    FROM due_payment_amount WHERE is_active = TRUE
    GROUP BY due_payment_id
) dpa ON dpa.due_payment_id = dp.id

LEFT JOIN (
    SELECT party_id,
           SUM(credit_limit) AS credit_limit,
           MAX(credit_days)  AS max_credit_days
    FROM master_party_credit_details GROUP BY party_id
) cl ON cl.party_id = t.party_id

LEFT JOIN (
    SELECT party_id,
           COALESCE(SUM(
               CASE WHEN is_active = TRUE AND deleted_at IS NULL
               THEN receive_amount ELSE 0 END
           ), 0) AS total_advance
    FROM due_advance_payment_dueadvancepayment GROUP BY party_id
) adv ON adv.party_id = t.party_id

WHERE dp.is_active = TRUE AND dp.deleted_at IS NULL
GROUP BY mp.company_name, t.party_id, cl.credit_limit,
         cl.max_credit_days, adv.total_advance;


-- ── 3B. view_partner_credit_risk_score ───────────────────────
-- Composite credit risk score (0-1) with aging severity + payment trend.
CREATE MATERIALIZED VIEW view_partner_credit_risk_score AS
WITH scored AS (
    SELECT
        ar.*,
        ROUND((payment_days_recent - payment_days_prev)::NUMERIC, 1) AS payment_trend_days,
        CASE
            WHEN (payment_days_recent - payment_days_prev) > 5  THEN 'Deteriorating'
            WHEN (payment_days_recent - payment_days_prev) < -5 THEN 'Improving'
            ELSE 'Stable'
        END AS payment_trend_dir,
        GREATEST(outstanding_amount - advance_received, 0) AS net_outstanding,
        CASE WHEN total_billed > 0
             THEN LEAST(overdue_amount / total_billed, 1.0) ELSE 0 END AS overdue_ratio,
        CASE WHEN credit_limit > 0
             THEN LEAST(outstanding_amount / credit_limit, 1.0) ELSE 0 END AS credit_utilization_ratio,
        CASE
            WHEN assigned_credit_days > 0 AND payment_days_recent > assigned_credit_days
                THEN LEAST((payment_days_recent - assigned_credit_days)::NUMERIC / assigned_credit_days, 1.0)
            WHEN assigned_credit_days > 0 THEN 0.0
            WHEN payment_days_recent > 60 THEN 0.8
            WHEN payment_days_recent > 30 THEN 0.5
            ELSE 0.1
        END AS speed_score,
        CASE WHEN overdue_amount > 0
             THEN LEAST((0.10*overdue_0_30 + 0.20*overdue_31_60 + 0.30*overdue_61_90
                         + 0.40*overdue_91_120 + 0.60*overdue_120_plus) / overdue_amount, 1.0)
             ELSE 0 END AS aging_severity_score,
        LEAST(overdue_invoice_count / 5.0, 1.0) AS count_score
    FROM view_partner_ar_summary ar
)
SELECT
    company_name, party_id, invoice_count, total_billed, total_collected,
    outstanding_amount, overdue_amount, overdue_invoice_count, net_outstanding,
    overdue_0_30, overdue_31_60, overdue_61_90, overdue_91_120, overdue_120_plus,
    avg_payment_days, assigned_credit_days, payment_days_recent, payment_days_prev,
    payment_trend_days, payment_trend_dir, credit_limit, advance_received,
    ROUND(credit_utilization_ratio::NUMERIC, 4)  AS credit_utilization_ratio,
    ROUND(overdue_ratio::NUMERIC, 4)             AS overdue_ratio,
    ROUND((0.30*overdue_ratio + 0.25*credit_utilization_ratio
           + 0.20*aging_severity_score + 0.15*speed_score
           + 0.10*count_score)::NUMERIC, 4)      AS credit_risk_score,
    CASE
        WHEN (0.30*overdue_ratio+0.25*credit_utilization_ratio+0.20*aging_severity_score+0.15*speed_score+0.10*count_score)>=0.65 THEN 'Critical'
        WHEN (0.30*overdue_ratio+0.25*credit_utilization_ratio+0.20*aging_severity_score+0.15*speed_score+0.10*count_score)>=0.45 THEN 'High'
        WHEN (0.30*overdue_ratio+0.25*credit_utilization_ratio+0.20*aging_severity_score+0.15*speed_score+0.10*count_score)>=0.25 THEN 'Medium'
        ELSE 'Low'
    END AS credit_risk_band,
    ROUND(((0.30*overdue_ratio+0.25*credit_utilization_ratio+0.20*aging_severity_score+0.15*speed_score+0.10*count_score)
           * net_outstanding)::NUMERIC, 2) AS credit_adjusted_risk_value,
    refreshed_at
FROM scored;


-- ==============================================================
--  STEP 4 — INDEXES
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

-- Credit risk views
CREATE INDEX IF NOT EXISTS idx_ar_party_id
    ON view_partner_ar_summary (party_id);

CREATE INDEX IF NOT EXISTS idx_credit_score_desc
    ON view_partner_credit_risk_score (credit_risk_score DESC);

CREATE INDEX IF NOT EXISTS idx_credit_band
    ON view_partner_credit_risk_score (credit_risk_band);

CREATE INDEX IF NOT EXISTS idx_payment_trend
    ON view_partner_credit_risk_score (payment_trend_dir);


-- ==============================================================
--  STEP 5 — REFRESH ALL VIEWS (run nightly at 02:00 IST)
--  Execute in dependency order.
-- ==============================================================

-- Unique indexes required for CONCURRENTLY refresh
CREATE UNIQUE INDEX IF NOT EXISTS idx_view_ml_input_party   ON view_ml_input (party_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_fact_sales_product    ON fact_sales_intelligence (product_name);
CREATE UNIQUE INDEX IF NOT EXISTS idx_ageing_stock_product  ON view_ageing_stock (product_name);
CREATE UNIQUE INDEX IF NOT EXISTS idx_product_assoc_pair    ON view_product_associations (item_1, item_2);
CREATE UNIQUE INDEX IF NOT EXISTS idx_ar_summary_party      ON view_partner_ar_summary (party_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_credit_score_party    ON view_partner_credit_risk_score (party_id);

-- Base views (no dependencies on other views)
REFRESH MATERIALIZED VIEW CONCURRENTLY view_ml_input;
REFRESH MATERIALIZED VIEW CONCURRENTLY fact_sales_intelligence;

-- Views that depend on base views
REFRESH MATERIALIZED VIEW CONCURRENTLY view_ageing_stock;

-- view_stock_liquidation_leads has no unique key → use regular REFRESH
REFRESH MATERIALIZED VIEW view_stock_liquidation_leads;

-- Independent
REFRESH MATERIALIZED VIEW CONCURRENTLY view_product_associations;

-- Credit risk (depends on billing tables, not other views)
REFRESH MATERIALIZED VIEW CONCURRENTLY view_partner_ar_summary;
REFRESH MATERIALIZED VIEW CONCURRENTLY view_partner_credit_risk_score;

-- Update planner statistics
ANALYZE transactions_dsr;
ANALYZE transactions_dsr_products;
ANALYZE master_products;
ANALYZE master_party;
ANALYZE due_payment;


-- ==============================================================
--  FULL MATERIALIZED VIEW INVENTORY
--  ┌─────────────────────────────────────┬──────────────────────────────────────────┐
--  │ View Name                           │ Powers                                   │
--  ├─────────────────────────────────────┼──────────────────────────────────────────┤
--  │ view_ml_input                       │ Churn, Clustering, Credit (proxy)        │
--  │ fact_sales_intelligence             │ Product Lifecycle, Forecast              │
--  │ view_ageing_stock                   │ Dead Stock, Inventory Intelligence       │
--  │ view_stock_liquidation_leads        │ Liquidation Opportunity Matching          │
--  │ view_product_associations           │ Market Basket / Cross-sell               │
--  │ view_partner_ar_summary             │ Real AR: outstanding, overdue, aging     │
--  │ view_partner_credit_risk_score      │ Credit Risk Score + Payment Trend        │
--  └─────────────────────────────────────┴──────────────────────────────────────────┘
--
--  APPLICATION TABLES INVENTORY
--  ┌─────────────────────────────────┬──────────────────────────────────────────────┐
--  │ Table                           │ Purpose                                      │
--  ├─────────────────────────────────┼──────────────────────────────────────────────┤
--  │ cluster_model_runs              │ ML clustering run history + quality scores   │
--  │ cluster_assignments             │ Per-partner cluster assignment per run       │
--  │ competitor_products             │ Competitor pricing data                      │
--  │ our_product_pricing             │ Our pricing + margins                        │
--  │ competitor_price_alerts         │ Auto-generated price undercut alerts         │
--  │ score_recompute_jobs            │ Background ML worker job queue               │
--  │ partner_live_scores             │ Cached real-time partner scores              │
--  │ recommendation_feedback_events  │ Sales pitch outcome feedback loop            │
--  └─────────────────────────────────┴──────────────────────────────────────────────┘
-- ==============================================================
