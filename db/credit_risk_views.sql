-- ============================================================
--  CREDIT RISK VIEWS v4 — with Aging Buckets + Payment Trend
--
--  New columns added to view_partner_ar_summary:
--    overdue_0_30     : overdue 1-30 days (₹)
--    overdue_31_60    : overdue 31-60 days (₹)
--    overdue_61_90    : overdue 61-90 days (₹)
--    overdue_91_120   : overdue 91-120 days (₹)
--    overdue_120_plus : overdue 120+ days (₹) ← most severe
--    payment_days_recent : avg days to pay (last 3 months invoices)
--    payment_days_prev   : avg days to pay (prior 3 months invoices)
--    payment_trend_days  : recent - prev (positive = slower = worse)
--    payment_trend_dir   : 'Improving' | 'Stable' | 'Deteriorating'
--
--  Rebuilt commands (paste both blocks in order):
-- ============================================================


-- ============================================================
--  BLOCK 1 — Rebuild view_partner_ar_summary
-- ============================================================
DROP MATERIALIZED VIEW IF EXISTS view_partner_credit_risk_score CASCADE;
DROP MATERIALIZED VIEW IF EXISTS view_partner_ar_summary CASCADE;

CREATE MATERIALIZED VIEW view_partner_ar_summary AS
SELECT
    mp.company_name,
    t.party_id,
    COUNT(dp.id)                                        AS invoice_count,

    ROUND(COALESCE(SUM(dp.net_amt), 0)::NUMERIC, 2)    AS total_billed,
    ROUND(COALESCE(SUM(dpa.collected), 0)::NUMERIC, 2) AS total_collected,

    ROUND(
        GREATEST(COALESCE(SUM(dp.net_amt), 0)
                 - COALESCE(SUM(dpa.collected), 0), 0)::NUMERIC, 2
    )                                                   AS outstanding_amount,

    -- ── Total overdue ─────────────────────────────────────────────────
    ROUND(COALESCE(SUM(
        CASE WHEN (dp.approve IS NULL OR dp.approve = FALSE)
              AND dp.bill_date::date + COALESCE(dp.credit_days, 0) < CURRENT_DATE
             THEN COALESCE(dp.net_amt, 0) ELSE 0 END
    ), 0)::NUMERIC, 2)                                  AS overdue_amount,

    COUNT(CASE
        WHEN (dp.approve IS NULL OR dp.approve = FALSE)
         AND dp.bill_date::date + COALESCE(dp.credit_days, 0) < CURRENT_DATE
        THEN 1 END)                                     AS overdue_invoice_count,

    -- ── Aging buckets ─────────────────────────────────────────────────
    -- Days overdue = CURRENT_DATE - due_date (for unpaid invoices)
    ROUND(COALESCE(SUM(
        CASE
            WHEN (dp.approve IS NULL OR dp.approve = FALSE)
             AND (CURRENT_DATE - (dp.bill_date::date + COALESCE(dp.credit_days, 0)))
                 BETWEEN 1 AND 30
            THEN COALESCE(dp.net_amt, 0) ELSE 0
        END
    ), 0)::NUMERIC, 2)                                  AS overdue_0_30,

    ROUND(COALESCE(SUM(
        CASE
            WHEN (dp.approve IS NULL OR dp.approve = FALSE)
             AND (CURRENT_DATE - (dp.bill_date::date + COALESCE(dp.credit_days, 0)))
                 BETWEEN 31 AND 60
            THEN COALESCE(dp.net_amt, 0) ELSE 0
        END
    ), 0)::NUMERIC, 2)                                  AS overdue_31_60,

    ROUND(COALESCE(SUM(
        CASE
            WHEN (dp.approve IS NULL OR dp.approve = FALSE)
             AND (CURRENT_DATE - (dp.bill_date::date + COALESCE(dp.credit_days, 0)))
                 BETWEEN 61 AND 90
            THEN COALESCE(dp.net_amt, 0) ELSE 0
        END
    ), 0)::NUMERIC, 2)                                  AS overdue_61_90,

    ROUND(COALESCE(SUM(
        CASE
            WHEN (dp.approve IS NULL OR dp.approve = FALSE)
             AND (CURRENT_DATE - (dp.bill_date::date + COALESCE(dp.credit_days, 0)))
                 BETWEEN 91 AND 120
            THEN COALESCE(dp.net_amt, 0) ELSE 0
        END
    ), 0)::NUMERIC, 2)                                  AS overdue_91_120,

    ROUND(COALESCE(SUM(
        CASE
            WHEN (dp.approve IS NULL OR dp.approve = FALSE)
             AND (CURRENT_DATE - (dp.bill_date::date + COALESCE(dp.credit_days, 0))) > 120
            THEN COALESCE(dp.net_amt, 0) ELSE 0
        END
    ), 0)::NUMERIC, 2)                                  AS overdue_120_plus,

    -- ── Payment speed ─────────────────────────────────────────────────
    ROUND(COALESCE(AVG(
        CASE WHEN dp.approve = TRUE AND dp.payment_date IS NOT NULL
             THEN dp.payment_date::date - dp.bill_date::date END
    ), 0)::NUMERIC, 1)                                  AS avg_payment_days,

    -- Recent 3 months avg payment speed (last 90 days of invoices)
    ROUND(COALESCE(AVG(
        CASE
            WHEN dp.approve = TRUE
             AND dp.payment_date IS NOT NULL
             AND dp.bill_date >= CURRENT_DATE - INTERVAL '90 days'
            THEN dp.payment_date::date - dp.bill_date::date
        END
    ), 0)::NUMERIC, 1)                                  AS payment_days_recent,

    -- Prior 3 months avg payment speed (90-180 days ago)
    ROUND(COALESCE(AVG(
        CASE
            WHEN dp.approve = TRUE
             AND dp.payment_date IS NOT NULL
             AND dp.bill_date >= CURRENT_DATE - INTERVAL '180 days'
             AND dp.bill_date <  CURRENT_DATE - INTERVAL '90 days'
            THEN dp.payment_date::date - dp.bill_date::date
        END
    ), 0)::NUMERIC, 1)                                  AS payment_days_prev,

    MAX(dp.bill_date)                                   AS last_invoice_date,

    -- Credit limits
    COALESCE(cl.credit_limit, 0)                        AS credit_limit,
    COALESCE(cl.max_credit_days, 0)                     AS assigned_credit_days,

    -- Advance buffer
    COALESCE(adv.total_advance, 0)                      AS advance_received,

    NOW()                                               AS refreshed_at

FROM due_payment dp
JOIN transactions_dsr t  ON t.id  = dp.dsr_id
JOIN master_party mp     ON mp.id = t.party_id

LEFT JOIN (
    SELECT due_payment_id, COALESCE(SUM(amount), 0) AS collected
    FROM due_payment_amount
    WHERE is_active = TRUE
    GROUP BY due_payment_id
) dpa ON dpa.due_payment_id = dp.id

LEFT JOIN (
    SELECT party_id,
           SUM(credit_limit)  AS credit_limit,
           MAX(credit_days)   AS max_credit_days
    FROM master_party_credit_details
    GROUP BY party_id
) cl ON cl.party_id = t.party_id

LEFT JOIN (
    SELECT party_id,
           COALESCE(SUM(
               CASE WHEN is_active = TRUE AND deleted_at IS NULL
               THEN receive_amount ELSE 0 END
           ), 0) AS total_advance
    FROM due_advance_payment_dueadvancepayment
    GROUP BY party_id
) adv ON adv.party_id = t.party_id

WHERE dp.is_active = TRUE
  AND dp.deleted_at IS NULL
GROUP BY mp.company_name, t.party_id,
         cl.credit_limit, cl.max_credit_days, adv.total_advance;


-- ============================================================
--  BLOCK 2 — Rebuild view_partner_credit_risk_score
--  (incorporates aging buckets into the risk score)
-- ============================================================
CREATE MATERIALIZED VIEW view_partner_credit_risk_score AS
WITH scored AS (
    SELECT
        ar.*,

        -- Derived: payment trend (positive = getting slower = worse)
        ROUND((payment_days_recent - payment_days_prev)::NUMERIC, 1)
                                                        AS payment_trend_days,

        CASE
            WHEN (payment_days_recent - payment_days_prev) > 5  THEN 'Deteriorating'
            WHEN (payment_days_recent - payment_days_prev) < -5 THEN 'Improving'
            ELSE 'Stable'
        END                                             AS payment_trend_dir,

        -- Net outstanding after advance buffer
        GREATEST(outstanding_amount - advance_received, 0)
                                                        AS net_outstanding,

        -- Overdue ratio
        CASE WHEN total_billed > 0
             THEN LEAST(overdue_amount / total_billed, 1.0) ELSE 0
        END                                             AS overdue_ratio,

        -- Credit utilization
        CASE WHEN credit_limit > 0
             THEN LEAST(outstanding_amount / credit_limit, 1.0) ELSE 0
        END                                             AS credit_utilization_ratio,

        -- Payment speed score
        CASE WHEN assigned_credit_days > 0
             THEN LEAST(
                GREATEST((payment_days_recent - assigned_credit_days)::NUMERIC
                         / assigned_credit_days, 0), 1.0)
             WHEN payment_days_recent > 60 THEN 0.8
             WHEN payment_days_recent > 30 THEN 0.5
             ELSE 0.1
        END                                             AS speed_score,

        -- Aging severity score: heavy weight on 90+ days buckets
        -- (120+ days overdue is worst → weighted higher)
        CASE WHEN overdue_amount > 0
             THEN LEAST((
                 0.10 * overdue_0_30
                 + 0.20 * overdue_31_60
                 + 0.30 * overdue_61_90
                 + 0.40 * overdue_91_120
                 + 0.60 * overdue_120_plus
             ) / overdue_amount, 1.0)
             ELSE 0
        END                                             AS aging_severity_score,

        -- Overdue invoice count score
        LEAST(overdue_invoice_count / 5.0, 1.0)         AS count_score

    FROM view_partner_ar_summary ar
)
SELECT
    company_name,
    party_id,
    invoice_count,
    total_billed,
    total_collected,
    outstanding_amount,
    overdue_amount,
    overdue_invoice_count,
    net_outstanding,

    -- Aging buckets
    overdue_0_30,
    overdue_31_60,
    overdue_61_90,
    overdue_91_120,
    overdue_120_plus,

    -- Payment speed
    avg_payment_days,
    assigned_credit_days,
    payment_days_recent,
    payment_days_prev,
    payment_trend_days,
    payment_trend_dir,

    -- Credit profile
    credit_limit,
    advance_received,
    ROUND(credit_utilization_ratio::NUMERIC, 4)         AS credit_utilization_ratio,
    ROUND(overdue_ratio::NUMERIC, 4)                    AS overdue_ratio,

    -- COMPOSITE CREDIT RISK SCORE (0-1)
    -- Now includes aging severity as a signal
    ROUND((
        0.30 * overdue_ratio
        + 0.25 * credit_utilization_ratio
        + 0.20 * aging_severity_score
        + 0.15 * speed_score
        + 0.10 * count_score
    )::NUMERIC, 4)                                      AS credit_risk_score,

    -- Risk band
    CASE
        WHEN (0.30*overdue_ratio + 0.25*credit_utilization_ratio
              + 0.20*aging_severity_score + 0.15*speed_score
              + 0.10*count_score) >= 0.65 THEN 'Critical'
        WHEN (0.30*overdue_ratio + 0.25*credit_utilization_ratio
              + 0.20*aging_severity_score + 0.15*speed_score
              + 0.10*count_score) >= 0.45 THEN 'High'
        WHEN (0.30*overdue_ratio + 0.25*credit_utilization_ratio
              + 0.20*aging_severity_score + 0.15*speed_score
              + 0.10*count_score) >= 0.25 THEN 'Medium'
        ELSE 'Low'
    END                                                 AS credit_risk_band,

    -- Adjusted risk value (rupee exposure)
    ROUND((
        (0.30*overdue_ratio + 0.25*credit_utilization_ratio
         + 0.20*aging_severity_score + 0.15*speed_score + 0.10*count_score)
        * net_outstanding
    )::NUMERIC, 2)                                      AS credit_adjusted_risk_value,

    refreshed_at
FROM scored;


-- ============================================================
--  BLOCK 3 — Indexes
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_ar_party_id
    ON view_partner_ar_summary (party_id);

CREATE INDEX IF NOT EXISTS idx_credit_score_desc
    ON view_partner_credit_risk_score (credit_risk_score DESC);

CREATE INDEX IF NOT EXISTS idx_credit_band
    ON view_partner_credit_risk_score (credit_risk_band);

CREATE INDEX IF NOT EXISTS idx_payment_trend
    ON view_partner_credit_risk_score (payment_trend_dir);


-- ============================================================
--  BLOCK 4 — Verify
-- ============================================================
SELECT
    company_name,
    overdue_0_30, overdue_31_60, overdue_61_90,
    overdue_91_120, overdue_120_plus,
    payment_trend_dir,
    payment_trend_days,
    credit_risk_band,
    credit_risk_score
FROM view_partner_credit_risk_score
WHERE overdue_amount > 0
ORDER BY overdue_120_plus DESC
LIMIT 10;
