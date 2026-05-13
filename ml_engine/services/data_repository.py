import pandas as pd


class DataRepository:
    """DB access layer for read-heavy dashboard workloads."""

    def __init__(self, engine):
        self.engine = engine

    def fetch_view_ml_input(self):
        return pd.read_sql("SELECT * FROM view_ml_input", self.engine)

    def fetch_fact_sales_intelligence(self):
        df = pd.read_sql("SELECT * FROM fact_sales_intelligence", self.engine)
        if "company_name" in df.columns:
            return df.set_index("company_name")
        return df   # view schema lacks company_name — return as-is, callers handle gracefully

    def fetch_view_ageing_stock(self):
        """
        Fetch dead/stale stock using ageing bucket columns directly.

        CRITICAL FIX (max_age_days):
          Previously used (snap_date - last_sold_date) which gives 'days since
          last sale' — NOT how long the stock has been in the warehouse.
          e.g. CPU COOLER with 15,940 units ALL in days_above_90_qty was
          showing max_age_days=1 because 1 unit was sold the day before the snap.

          Now max_age_days is derived from the oldest bucket that has stale stock:
            days_above_90_qty > 0  →  91 days (confirmed 90+ day stock)
            days_61_to_90_qty > 0  →  75 days (midpoint 61-90)

        CRITICAL FIX (area exclusion):
          area_id=8 is Delhi — the MAIN DISTRIBUTION WAREHOUSE with 215M+ units
          of opening stock. Products there are in the distribution pipeline, NOT
          dead stock. Including Delhi inflated stale qty by 362,791 units (78%!).
          e.g. SMPS 0602 showed 7,095 stale units (all from Delhi area_id=8) but
          actual branch-level dead stock is 0 — confirmed by the company.

          Fix: exclude area_id=8 from stale stock aggregation. Only count
          stale stock at regional BRANCH level (areas 1,2,3,4,5,6,7,... except 8).

        stale_stock_qty = days_61_to_90_qty + days_above_90_qty (branch-only, summed).
        minimum threshold: > 5 units to filter single-unit noise.
        """
        try:
            return pd.read_sql(
                """
                WITH snap AS (
                    SELECT MAX(to_date) AS snap_date
                    FROM "apps.master.stockageing"
                    WHERE (disable = false OR disable IS NULL)
                ),
                branch_stock AS (
                    SELECT DISTINCT ON (s.product_id, s.area_id)
                        p.id           AS product_id,
                        p.product_name,
                        s.area_id,
                        -- Full stock at this branch (all buckets)
                        COALESCE(s.days_0_to_15_qty,  0)
                      + COALESCE(s.days_16_to_30_qty, 0)
                      + COALESCE(s.days_31_to_60_qty, 0)
                      + COALESCE(s.days_61_to_90_qty, 0)
                      + COALESCE(s.days_above_90_qty, 0) AS total_branch_qty,
                        -- Stale buckets only (61+ days)
                        COALESCE(s.days_61_to_90_qty, 0) AS stale_61_90,
                        COALESCE(s.days_above_90_qty, 0) AS stale_above_90,
                        -- Fresh buckets (for ageing distribution chart)
                        COALESCE(s.days_0_to_15_qty,  0)
                      + COALESCE(s.days_16_to_30_qty, 0) AS fresh_0_30,
                        COALESCE(s.days_31_to_60_qty, 0) AS fresh_31_60,
                        s.to_date AS stock_snapshot_date
                    FROM "apps.master.stockageing" s
                    CROSS JOIN snap
                    JOIN master_products p ON s.product_id = p.id
                    WHERE (s.disable = false OR s.disable IS NULL)
                      AND s.to_date = snap.snap_date
                      -- Exclude main distribution warehouse (Delhi, area_id=8).
                      -- Central warehouse stock is in the distribution pipeline,
                      -- NOT dead stock. Including it inflates stale qty by ~362k units.
                      AND s.area_id != 8
                    ORDER BY s.product_id, s.area_id, s.to_date DESC
                ),
                aggregated AS (
                    SELECT
                        product_id,
                        product_name,
                        SUM(total_branch_qty)            AS total_stock_qty,
                        SUM(stale_61_90)                 AS stale_qty_61_90,
                        SUM(stale_above_90)              AS stale_qty_above_90,
                        SUM(fresh_0_30)                  AS age_0_30,
                        SUM(fresh_31_60)                 AS age_31_60,
                        SUM(stale_61_90)                 AS age_61_90,
                        SUM(stale_above_90)              AS age_90_plus,
                        MAX(stock_snapshot_date)         AS stock_snapshot_date
                    FROM branch_stock
                    GROUP BY product_id, product_name
                )
                SELECT
                    a.product_name,
                    (a.stale_qty_61_90 + a.stale_qty_above_90)  AS total_stock_qty,
                    -- max_age_days from BUCKET DATA (correct warehouse age)
                    -- NOT from last_sold_date which gives 'days since last sale'
                    CASE
                        WHEN a.stale_qty_above_90 > 0 THEN 91
                        WHEN a.stale_qty_61_90    > 0 THEN 75
                        ELSE 0
                    END                                          AS max_age_days,
                    a.age_0_30,
                    a.age_31_60,
                    a.age_61_90,
                    a.age_90_plus,
                    a.stock_snapshot_date                        AS snap_date
                FROM aggregated a
                -- minimum 5 units to filter single-unit noise
                WHERE (a.stale_qty_61_90 + a.stale_qty_above_90) > 5
                ORDER BY max_age_days DESC, total_stock_qty DESC
                """,
                self.engine,
            )
        except Exception as e:
            print(f"[fetch_view_ageing_stock] failed: {e}, falling back to materialized view")
            return pd.read_sql(
                "SELECT product_name, total_stock_qty, max_age_days FROM view_ageing_stock",
                self.engine,
            )

    def fetch_available_snapshot_dates(self):
        """
        Returns all distinct snapshot dates available in apps.master.stockageing.
        Each date represents a weekly Monday upload.
        Returns a list of date objects sorted newest-first.
        """
        try:
            df = pd.read_sql(
                """
                SELECT DISTINCT to_date
                FROM "apps.master.stockageing"
                WHERE (disable = false OR disable IS NULL)
                ORDER BY to_date DESC
                """,
                self.engine,
            )
            if df.empty or "to_date" not in df.columns:
                return []
            return pd.to_datetime(df["to_date"]).dt.date.tolist()
        except Exception as e:
            print(f"[snapshot_dates] {e}")
            return []

    def fetch_ageing_stock_snapshot(self, snapshot_date):
        """
        Returns the dead-stock picture AS OF a specific snapshot_date (a past Monday).

        Key differences from fetch_view_ageing_stock:
          - Queries only rows where to_date = snapshot_date (that week's upload)
          - Calculates max_age_days as (snapshot_date - last_sold_date), NOT CURRENT_DATE
          - Only considers sales that occurred on or before snapshot_date
        This gives a true time-travel view of what was dead stock on that Monday.
        """
        try:
            return pd.read_sql(
                """
                WITH snapshot_per_branch AS (
                    SELECT DISTINCT ON (s.product_id, s.area_id)
                        p.id          AS product_id,
                        p.product_name,
                        (s.days_0_to_15_qty + s.days_16_to_30_qty +
                         s.days_31_to_60_qty + s.days_61_to_90_qty +
                         s.days_above_90_qty) AS branch_stock_qty,
                        s.to_date     AS stock_snapshot_date
                    FROM "apps.master.stockageing" s
                    JOIN master_products p ON s.product_id = p.id
                    WHERE (s.disable = false OR s.disable IS NULL)
                      AND s.to_date = %(snap)s
                    ORDER BY s.product_id, s.area_id, s.to_date DESC
                ),
                aggregated AS (
                    SELECT
                        product_id,
                        product_name,
                        SUM(branch_stock_qty)    AS total_stock_qty,
                        MAX(stock_snapshot_date) AS stock_snapshot_date
                    FROM snapshot_per_branch
                    GROUP BY product_id, product_name
                ),
                last_sold AS (
                    SELECT tp.product_id, MAX(t.date) AS last_sold_date
                    FROM transactions_dsr_products tp
                    JOIN transactions_dsr t ON tp.dsr_id = t.id
                    WHERE LOWER(CAST(t.is_approved AS TEXT)) = 'true'
                      AND t.date <= %(snap)s
                    GROUP BY tp.product_id
                )
                SELECT
                    a.product_name,
                    a.total_stock_qty,
                    CASE
                        WHEN s.last_sold_date IS NULL
                            THEN GREATEST((%(snap)s::date - a.stock_snapshot_date), 0)
                        ELSE
                            GREATEST((%(snap)s::date - s.last_sold_date), 0)
                    END AS max_age_days
                FROM aggregated a
                LEFT JOIN last_sold s ON a.product_id = s.product_id
                WHERE a.total_stock_qty > 10
                  AND (
                        s.last_sold_date IS NULL
                        OR (%(snap)s::date - s.last_sold_date) > 60
                  )
                ORDER BY max_age_days DESC
                """,
                self.engine,
                params={"snap": str(snapshot_date)},
            )
        except Exception as e:
            print(f"[fetch_ageing_stock_snapshot] {e}")
            return pd.DataFrame(columns=["product_name", "total_stock_qty", "max_age_days"])

    def fetch_view_product_associations(self, limit=2000):
        df = pd.read_sql(
            f"SELECT * FROM view_product_associations ORDER BY times_bought_together DESC LIMIT {int(limit)}",
            self.engine,
        )
        # Normalize view column names: DB view uses item_1/item_2, all downstream code
        # (associations_mixin, chatbot, frontend) expects product_a / product_b.
        rename_map = {}
        if "item_1" in df.columns and "product_a" not in df.columns:
            rename_map["item_1"] = "product_a"
        if "item_2" in df.columns and "product_b" not in df.columns:
            rename_map["item_2"] = "product_b"
        if rename_map:
            df = df.rename(columns=rename_map)
        return df

    def fetch_view_stock_liquidation_leads(self):
        """
        Fetch stale dead stock + buyer leads using bucket-based stale detection.

        Uses days_61_to_90_qty + days_above_90_qty directly as the stale
        quantity signal. This matches the stockageing table's design intent
        and does NOT drop products that had any recent sale.
        """
        try:
            df = pd.read_sql(
                """
                WITH snap AS (
                    SELECT MAX(to_date) AS snap_date
                    FROM "apps.master.stockageing"
                    WHERE (disable = false OR disable IS NULL)
                ),
                branch_stock AS (
                    SELECT DISTINCT ON (s.product_id, s.area_id)
                        p.id           AS product_id,
                        p.product_name,
                        COALESCE(s.days_0_to_15_qty,  0)
                      + COALESCE(s.days_16_to_30_qty, 0)
                      + COALESCE(s.days_31_to_60_qty, 0)
                      + COALESCE(s.days_61_to_90_qty, 0)
                      + COALESCE(s.days_above_90_qty, 0) AS total_branch_qty,
                        COALESCE(s.days_61_to_90_qty, 0)
                      + COALESCE(s.days_above_90_qty, 0) AS stale_branch_qty,
                        s.to_date AS stock_snapshot_date
                    FROM "apps.master.stockageing" s
                    CROSS JOIN snap
                    JOIN master_products p ON s.product_id = p.id
                    WHERE (s.disable = false OR s.disable IS NULL)
                      AND s.to_date = snap.snap_date
                    ORDER BY s.product_id, s.area_id, s.to_date DESC
                ),
                aggregated AS (
                    SELECT
                        product_id,
                        product_name,
                        SUM(total_branch_qty) AS total_stock_qty,
                        SUM(stale_branch_qty) AS stale_stock_qty,
                        MAX(stock_snapshot_date) AS stock_snapshot_date
                    FROM branch_stock
                    GROUP BY product_id, product_name
                ),
                last_sold AS (
                    SELECT tp.product_id, MAX(t.date) AS last_sold_date
                    FROM transactions_dsr_products tp
                    JOIN transactions_dsr t ON tp.dsr_id = t.id
                    WHERE LOWER(CAST(t.is_approved AS TEXT)) = 'true'
                      AND t.date <= (SELECT snap_date FROM snap)
                    GROUP BY tp.product_id
                ),
                dead_stock AS (
                    SELECT
                        a.product_id,
                        a.product_name   AS dead_stock_item,
                        a.stale_stock_qty AS qty_in_stock,
                        CASE
                            WHEN ls.last_sold_date IS NULL
                                THEN GREATEST(((SELECT snap_date FROM snap)::date - a.stock_snapshot_date), 0)
                            ELSE
                                GREATEST(((SELECT snap_date FROM snap)::date - ls.last_sold_date), 0)
                        END AS max_age_days
                    FROM aggregated a
                    LEFT JOIN last_sold ls ON a.product_id = ls.product_id
                    WHERE a.stale_stock_qty > 0
                )
                SELECT
                    ds.dead_stock_item,
                    ds.qty_in_stock,
                    ds.max_age_days,
                    mp.company_name                          AS potential_buyer,
                    mp.mobile_no                             AS mobile_no,
                    mp.id                                    AS party_id,
                    COALESCE(ms.state_name,    'Unknown')   AS state_name,
                    COALESCE(mg.group_name,    'General')   AS product_group,
                    COALESCE(mpc.category_name,'General')   AS product_category,
                    MAX(t.date)                              AS last_purchase_date,
                    SUM(tp.qty)                              AS buyer_past_purchase_qty,
                    COUNT(DISTINCT t.id)                     AS purchase_txn_count,
                    SUM(tp.net_amt)                          AS historical_revenue
                FROM dead_stock ds
                JOIN master_products p                ON p.id = ds.product_id
                LEFT JOIN master_group mg             ON p.group_id = mg.id
                LEFT JOIN master_product_category mpc ON mg.category_id_id = mpc.id
                JOIN transactions_dsr_products tp     ON tp.product_id = p.id
                JOIN transactions_dsr t               ON t.id = tp.dsr_id
                                                     AND LOWER(CAST(t.is_approved AS TEXT)) = 'true'
                JOIN master_party mp                  ON mp.id = t.party_id
                LEFT JOIN master_state ms             ON mp.state_id = ms.id
                GROUP BY
                    ds.dead_stock_item, ds.qty_in_stock, ds.max_age_days,
                    mp.company_name, mp.mobile_no, mp.id,
                    ms.state_name, mg.group_name, mpc.category_name
                ORDER BY ds.max_age_days DESC, historical_revenue DESC
                """,
                self.engine,
            )
        except Exception as e:
            print(f"[fetch_stock_leads] query failed ({e}), falling back to materialized view")
            df = pd.read_sql("SELECT * FROM view_stock_liquidation_leads", self.engine)
            if "historical_qty_bought" in df.columns and "buyer_past_purchase_qty" not in df.columns:
                df = df.rename(columns={"historical_qty_bought": "buyer_past_purchase_qty"})

        for col, default in [
            ("purchase_txn_count",      1),
            ("state_name",              "Unknown"),
            ("product_category",        "General"),
            ("product_group",           "General"),
            ("buyer_past_purchase_qty", 0),
        ]:
            if col not in df.columns:
                df[col] = default
        return df

    def fetch_dead_stock_trend(self, months: int = 12):
        """
        Returns total & stale (60+ day) stock units per weekly snapshot date
        over the last `months` months. Used for the historical trend chart.
        Stale = days_61_to_90_qty + days_above_90_qty already aged on that date.
        """
        try:
            return pd.read_sql(
                f"""
                SELECT
                    to_date                                     AS snapshot_date,
                    COUNT(DISTINCT product_id)                  AS total_products,
                    SUM(days_61_to_90_qty + days_above_90_qty)  AS stale_stock_units,
                    SUM(days_0_to_15_qty + days_16_to_30_qty
                        + days_31_to_60_qty + days_61_to_90_qty
                        + days_above_90_qty)                    AS total_stock_units
                FROM "apps.master.stockageing"
                WHERE (disable = false OR disable IS NULL)
                  AND to_date >= CURRENT_DATE - INTERVAL '{int(months)} months'
                GROUP BY to_date
                ORDER BY to_date
                """,
                self.engine,
            )
        except Exception as e:
            print(f"[fetch_dead_stock_trend] {e}")
            return pd.DataFrame(columns=[
                "snapshot_date", "total_products",
                "stale_stock_units", "total_stock_units",
            ])

    def fetch_table_data(self, table_name):
        """Generic table fetcher for raw data modeling"""
        try:
            return pd.read_sql(f"SELECT * FROM {table_name}", self.engine)
        except Exception as e:
            print(f"Error fetching {table_name}: {e}")
            return pd.DataFrame()
