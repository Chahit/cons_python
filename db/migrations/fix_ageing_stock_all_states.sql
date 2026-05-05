-- Fix: view_ageing_stock - sum latest snapshot per branch (area_id) across all warehouses
-- Also recreates view_stock_liquidation_leads (dropped by CASCADE)
-- area_id = branch/warehouse identifier in apps.master.stockageing

DROP MATERIALIZED VIEW IF EXISTS view_ageing_stock CASCADE;

CREATE MATERIALIZED VIEW view_ageing_stock AS
WITH latest_per_branch AS (
    -- For each (product, branch), pick the single most recent snapshot row.
    -- This ensures we read current live stock per warehouse, not historical accumulation.
    SELECT DISTINCT ON (s.product_id, s.area_id)
        p.id AS product_id,
        p.product_name,
        (s.days_0_to_15_qty + s.days_16_to_30_qty +
         s.days_31_to_60_qty + s.days_61_to_90_qty + s.days_above_90_qty) AS branch_stock_qty,
        s.to_date AS stock_snapshot_date
    FROM "apps.master.stockageing" s
    JOIN master_products p ON s.product_id = p.id
    WHERE s.disable = false OR s.disable IS NULL
    ORDER BY s.product_id, s.area_id, s.to_date DESC
),
-- Sum the latest stock qty across all branches for a true national total
aggregated AS (
    SELECT
        product_id,
        product_name,
        SUM(branch_stock_qty)  AS total_stock_qty,
        MAX(stock_snapshot_date) AS stock_snapshot_date
    FROM latest_per_branch
    GROUP BY product_id, product_name
),
-- Last approved sale date per product (for demand-recency age calculation)
last_sold AS (
    SELECT tp.product_id, MAX(t.date) AS last_sold_date
    FROM transactions_dsr_products tp
    JOIN transactions_dsr t ON tp.dsr_id = t.id
    WHERE LOWER(CAST(t.is_approved AS TEXT)) = 'true'
    GROUP BY tp.product_id
)
SELECT
    a.product_name,
    a.total_stock_qty,
    CASE
        WHEN s.last_sold_date IS NULL
            THEN GREATEST((CURRENT_DATE - a.stock_snapshot_date), 0)
        ELSE
            GREATEST((CURRENT_DATE - s.last_sold_date), 0)
    END AS max_age_days
FROM aggregated a
LEFT JOIN last_sold s ON a.product_id = s.product_id
WHERE a.total_stock_qty > 10
  AND (s.last_sold_date IS NULL OR (CURRENT_DATE - s.last_sold_date) > 60)
ORDER BY max_age_days DESC;

CREATE UNIQUE INDEX IF NOT EXISTS idx_ageing_stock_product
    ON view_ageing_stock (product_name);

-- Recreate liquidation leads view (dropped by CASCADE above)
CREATE MATERIALIZED VIEW view_stock_liquidation_leads AS
SELECT
    vas.product_name                        AS dead_stock_item,
    vas.total_stock_qty                     AS qty_in_stock,
    vas.max_age_days,
    mp.company_name                         AS potential_buyer,
    mp.mobile_no                            AS mobile_no,
    mp.id                                   AS party_id,
    COALESCE(ms.state_name, 'Unknown')      AS state_name,
    COALESCE(mg.group_name, 'General')      AS product_group,
    COALESCE(mpc.category_name, 'General')  AS product_category,
    MAX(t.date)                             AS last_purchase_date,
    SUM(tp.qty)                             AS historical_qty_bought,
    COUNT(DISTINCT t.id)                    AS purchase_txn_count,
    SUM(tp.net_amt)                         AS historical_revenue
FROM view_ageing_stock vas
JOIN master_products p              ON p.product_name = vas.product_name
LEFT JOIN master_group mg           ON p.group_id = mg.id
LEFT JOIN master_product_category mpc ON mg.category_id_id = mpc.id
JOIN transactions_dsr_products tp   ON tp.product_id = p.id
JOIN transactions_dsr t             ON t.id = tp.dsr_id
                                   AND LOWER(CAST(t.is_approved AS TEXT)) = 'true'
JOIN master_party mp                ON mp.id = t.party_id
LEFT JOIN master_state ms           ON mp.state_id = ms.id
GROUP BY
    vas.product_name, vas.total_stock_qty, vas.max_age_days,
    mp.company_name, mp.mobile_no, mp.id,
    ms.state_name, mg.group_name, mpc.category_name
ORDER BY vas.max_age_days DESC, historical_revenue DESC;

-- Verify: should show realistic national totals per product
SELECT COUNT(*) AS total_products,
       SUM(total_stock_qty) AS national_total_stock,
       MAX(max_age_days) AS oldest_stock_days
FROM view_ageing_stock;
