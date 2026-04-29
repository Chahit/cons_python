-- ==============================================================
--  Sales Analyzer — Partner Summary Materialized View
--  Pre-aggregates per-partner geography (state, city) and
--  all-time sales metrics so that cascading dropdowns are instant.
--
--  Detailed product breakdown & date-filtered charts always query
--  the raw transaction tables directly (they use existing indexes
--  idx_dsr_date_approved and idx_dsr_party_date_approved).
--
--  Run order: execute after master_state / master_city / master_party
--  tables exist (they are part of the base app schema).
-- ==============================================================

DROP MATERIALIZED VIEW IF EXISTS view_sales_analyzer_partner_summary;

CREATE MATERIALIZED VIEW view_sales_analyzer_partner_summary AS
SELECT
    mp.id                                           AS party_id,
    mp.company_name,
    mp.mobile_no,
    COALESCE(ms.state_name, 'Unknown')              AS state_name,
    COALESCE(mc.name, 'Unknown')                    AS city_name,
    COUNT(DISTINCT t.id)                            AS total_orders,
    COALESCE(SUM(tp.net_amt), 0)                    AS total_revenue,
    MAX(t.date)                                     AS last_order_date,
    MIN(t.date)                                     AS first_order_date,
    COUNT(DISTINCT tp.product_id)                   AS unique_products
FROM master_party mp
LEFT JOIN master_state ms   ON ms.id  = mp.state_id
LEFT JOIN master_city mc    ON mc.id  = mp.city_id
LEFT JOIN transactions_dsr t
       ON t.party_id = mp.id
      AND LOWER(CAST(t.is_approved AS TEXT)) = 'true'
LEFT JOIN transactions_dsr_products tp ON tp.dsr_id = t.id
GROUP BY mp.id, mp.company_name, mp.mobile_no, ms.state_name, mc.name;

-- Indexes for fast cascade filter lookups
CREATE INDEX IF NOT EXISTS idx_sa_summary_state
    ON view_sales_analyzer_partner_summary (state_name);

CREATE INDEX IF NOT EXISTS idx_sa_summary_city
    ON view_sales_analyzer_partner_summary (city_name);

CREATE INDEX IF NOT EXISTS idx_sa_summary_party
    ON view_sales_analyzer_partner_summary (party_id);

CREATE INDEX IF NOT EXISTS idx_sa_summary_state_city
    ON view_sales_analyzer_partner_summary (state_name, city_name);

-- Refresh command (run from a cron / after bulk data import):
-- REFRESH MATERIALIZED VIEW CONCURRENTLY view_sales_analyzer_partner_summary;
