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
        Fetch current live stock aggregated across ALL branch warehouses (area_id).

        Strategy:
          1. DISTINCT ON (product_id, area_id) ORDER BY to_date DESC
             -> picks the single most recent snapshot row per (product, branch)
          2. SUM branch_stock_qty GROUP BY product
             -> correct national total (all 15-16 warehouses, no double-counting)

        Falls back to the materialized view if the raw table is inaccessible.
        """
        try:
            return pd.read_sql(
                """
                WITH latest_per_branch AS (
                    SELECT DISTINCT ON (s.product_id, s.area_id)
                        p.id          AS product_id,
                        p.product_name,
                        (s.days_0_to_15_qty + s.days_16_to_30_qty +
                         s.days_31_to_60_qty + s.days_61_to_90_qty +
                         s.days_above_90_qty) AS branch_stock_qty,
                        s.to_date     AS stock_snapshot_date
                    FROM "apps.master.stockageing" s
                    JOIN master_products p ON s.product_id = p.id
                    WHERE s.disable = false OR s.disable IS NULL
                    ORDER BY s.product_id, s.area_id, s.to_date DESC
                ),
                aggregated AS (
                    SELECT
                        product_id,
                        product_name,
                        SUM(branch_stock_qty)    AS total_stock_qty,
                        MAX(stock_snapshot_date) AS stock_snapshot_date
                    FROM latest_per_branch
                    GROUP BY product_id, product_name
                ),
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
                  AND (s.last_sold_date IS NULL
                       OR (CURRENT_DATE - s.last_sold_date) > 60)
                ORDER BY max_age_days DESC
                """,
                self.engine,
            )
        except Exception:
            return pd.read_sql(
                "SELECT product_name, total_stock_qty, max_age_days FROM view_ageing_stock",
                self.engine,
            )



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
        df = pd.read_sql("SELECT * FROM view_stock_liquidation_leads", self.engine)
        # Normalize: DB view uses historical_qty_bought, frontend expects buyer_past_purchase_qty
        if "historical_qty_bought" in df.columns and "buyer_past_purchase_qty" not in df.columns:
            df = df.rename(columns={"historical_qty_bought": "buyer_past_purchase_qty"})
        # Ensure purchase_txn_count exists (for purchase pattern analysis)
        if "purchase_txn_count" not in df.columns:
            df["purchase_txn_count"] = 1
        # Ensure state_name exists (for Area column)
        if "state_name" not in df.columns:
            df["state_name"] = "Unknown"
        # Ensure product_category exists (for category filter)
        if "product_category" not in df.columns:
            df["product_category"] = "General"
        # Ensure product_group exists
        if "product_group" not in df.columns:
            df["product_group"] = "General"
        return df

    def fetch_table_data(self, table_name):
        """Generic table fetcher for raw data modeling"""
        try:
            return pd.read_sql(f"SELECT * FROM {table_name}", self.engine)
        except Exception as e:
            print(f"Error fetching {table_name}: {e}")
            return pd.DataFrame()
