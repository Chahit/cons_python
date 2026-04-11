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
        return df

    def fetch_table_data(self, table_name):
        """Generic table fetcher for raw data modeling"""
        try:
            return pd.read_sql(f"SELECT * FROM {table_name}", self.engine)
        except Exception as e:
            print(f"Error fetching {table_name}: {e}")
            return pd.DataFrame()
