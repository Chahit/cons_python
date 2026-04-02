import pandas as pd


class DataRepository:
    """DB access layer for read-heavy dashboard workloads."""

    def __init__(self, engine):
        self.engine = engine

    def fetch_view_ml_input(self):
        query = """
        SELECT
            v.*,
            COALESCE(ms.state_name, 'Unknown') AS state
        FROM view_ml_input v
        LEFT JOIN master_party mp ON mp.company_name = v.company_name
        LEFT JOIN master_state  ms ON ms.id = mp.state_id
        """
        try:
            return pd.read_sql(query, self.engine)
        except Exception:
            # Fallback: return without state if join fails
            return pd.read_sql("SELECT * FROM view_ml_input", self.engine)


    def fetch_fact_sales_intelligence(self):
        return pd.read_sql("SELECT * FROM fact_sales_intelligence", self.engine).set_index(
            "product_name"
        )

    def fetch_view_ageing_stock(self):
        return pd.read_sql(
            "SELECT product_name, total_stock_qty, max_age_days FROM view_ageing_stock",
            self.engine,
        )

    def fetch_view_product_associations(self, limit=2000):
        return pd.read_sql(
            f"""SELECT item_1 AS product_a, item_2 AS product_b,
                       times_bought_together, unique_buyers_together
                FROM view_product_associations
                ORDER BY times_bought_together DESC
                LIMIT {int(limit)}""",
            self.engine,
        )

    def fetch_view_stock_liquidation_leads(self):
        """
        Reads the liquidation leads materialized view.
        Falls back to a live query against the raw tables if the view
        hasn't been created yet (UndefinedTable / ProgrammingError).
        """
        try:
            df = pd.read_sql("SELECT * FROM view_stock_liquidation_leads", self.engine)
            rename_map = {"historical_qty_bought": "buyer_past_purchase_qty"}
            return df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})
        except Exception as primary_err:
            err_str = str(primary_err).lower()
            # Only fall back for "view doesn't exist" errors, re-raise anything else
            if "does not exist" not in err_str and "undefined" not in err_str:
                raise
            import warnings
            warnings.warn(
                "view_stock_liquidation_leads not found — running live fallback query. "
                "Run the supreme_schema.sql to create the materialized view for better performance.",
                RuntimeWarning,
            )

        # ── Fallback: replicate the view logic inline ──────────────────
        FALLBACK_SQL = """
            SELECT
                vas.product_name            AS dead_stock_item,
                vas.total_stock_qty         AS qty_in_stock,
                vas.max_age_days,
                mp.company_name             AS potential_buyer,
                mp.mobile_no                AS mobile_no,
                mp.id                       AS party_id,
                MAX(t.date)                 AS last_purchase_date,
                SUM(tp.qty)                 AS buyer_past_purchase_qty,
                SUM(tp.net_amt)             AS historical_revenue
            FROM view_ageing_stock vas
            JOIN master_products p             ON p.product_name = vas.product_name
            JOIN transactions_dsr_products tp  ON tp.product_id  = p.id
            JOIN transactions_dsr t            ON t.id = tp.dsr_id
                                              AND LOWER(CAST(t.is_approved AS TEXT)) = 'true'
            JOIN master_party mp               ON mp.id = t.party_id
            GROUP BY vas.product_name, vas.total_stock_qty, vas.max_age_days,
                     mp.company_name, mp.mobile_no, mp.id
            ORDER BY vas.max_age_days DESC, historical_revenue DESC
        """
        try:
            return pd.read_sql(FALLBACK_SQL, self.engine)
        except Exception as fallback_err:
            # view_ageing_stock also missing — try fully raw fallback
            err_str2 = str(fallback_err).lower()
            if "does not exist" not in err_str2 and "undefined" not in err_str2:
                raise
            warnings.warn(
                "view_ageing_stock also not found — running fully raw fallback query.",
                RuntimeWarning,
            )

        # ── Deep fallback: derive ageing stock inline too ──────────────
        DEEP_FALLBACK_SQL = """
            WITH product_stock AS (
                SELECT
                    p.id          AS product_id,
                    p.product_name,
                    (s.days_0_to_15_qty + s.days_16_to_30_qty +
                     s.days_31_to_60_qty + s.days_61_to_90_qty + s.days_above_90_qty)
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
            ),
            ageing AS (
                SELECT
                    ls.product_id,
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
            )
            SELECT
                ag.product_name             AS dead_stock_item,
                ag.total_stock_qty          AS qty_in_stock,
                ag.max_age_days,
                mp.company_name             AS potential_buyer,
                mp.mobile_no                AS mobile_no,
                mp.id                       AS party_id,
                MAX(t.date)                 AS last_purchase_date,
                SUM(tp.qty)                 AS buyer_past_purchase_qty,
                SUM(tp.net_amt)             AS historical_revenue
            FROM ageing ag
            JOIN master_products p             ON p.product_name = ag.product_name
            JOIN transactions_dsr_products tp  ON tp.product_id  = p.id
            JOIN transactions_dsr t            ON t.id = tp.dsr_id
                                              AND LOWER(CAST(t.is_approved AS TEXT)) = 'true'
            JOIN master_party mp               ON mp.id = t.party_id
            GROUP BY ag.product_name, ag.total_stock_qty, ag.max_age_days,
                     mp.company_name, mp.mobile_no, mp.id
            ORDER BY ag.max_age_days DESC, historical_revenue DESC
        """
        return pd.read_sql(DEEP_FALLBACK_SQL, self.engine)

    def fetch_table_data(self, table_name):
        """Generic table fetcher for raw data modeling"""
        try:
            return pd.read_sql(f"SELECT * FROM {table_name}", self.engine)
        except Exception as e:
            print(f"Error fetching {table_name}: {e}")
            return pd.DataFrame()
