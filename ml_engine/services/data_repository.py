import pandas as pd


class DataRepository:
    """DB access layer for read-heavy dashboard workloads."""

    def __init__(self, engine):
        self.engine = engine

    def fetch_view_ml_input(self):
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
        df = pd.read_sql("SELECT * FROM view_stock_liquidation_leads", self.engine)
        # Align view column names to what the frontend expects
        rename_map = {
            "historical_qty_bought": "buyer_past_purchase_qty",
        }
        return df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})

    def fetch_table_data(self, table_name):
        """Generic table fetcher for raw data modeling"""
        try:
            return pd.read_sql(f"SELECT * FROM {table_name}", self.engine)
        except Exception as e:
            print(f"Error fetching {table_name}: {e}")
            return pd.DataFrame()
