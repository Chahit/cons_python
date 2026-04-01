-- SQL Performance Governance Baseline
-- Purpose: keep dashboard latency stable as data grows.

-- 1) Recommended partial indexes for hot paths
-- Note: run after validation on staging.
CREATE INDEX IF NOT EXISTS idx_dsr_party_date_approved
ON transactions_dsr (party_id, date)
WHERE LOWER(CAST(is_approved AS TEXT)) = 'true';

CREATE INDEX IF NOT EXISTS idx_dsr_date_approved
ON transactions_dsr (date)
WHERE LOWER(CAST(is_approved AS TEXT)) = 'true';

CREATE INDEX IF NOT EXISTS idx_dsr_products_dsr
ON transactions_dsr_products (dsr_id);

CREATE INDEX IF NOT EXISTS idx_dsr_products_product
ON transactions_dsr_products (product_id);

-- 2) Materialized view refresh order
-- Keep dependencies refreshed in this sequence.
REFRESH MATERIALIZED VIEW view_ml_input;
REFRESH MATERIALIZED VIEW view_ageing_stock;
REFRESH MATERIALIZED VIEW view_stock_liquidation_leads;
REFRESH MATERIALIZED VIEW view_product_associations;
REFRESH MATERIALIZED VIEW fact_sales_intelligence;

-- 3) EXPLAIN ANALYZE templates
-- Run and store outputs weekly to detect regressions.
EXPLAIN (ANALYZE, BUFFERS, VERBOSE)
SELECT * FROM view_ml_input;

EXPLAIN (ANALYZE, BUFFERS, VERBOSE)
SELECT * FROM fact_sales_intelligence;

EXPLAIN (ANALYZE, BUFFERS, VERBOSE)
SELECT * FROM view_product_associations ORDER BY times_bought_together DESC LIMIT 2000;

-- 4) Statistics maintenance
ANALYZE transactions_dsr;
ANALYZE transactions_dsr_products;
ANALYZE master_products;
ANALYZE master_party;
