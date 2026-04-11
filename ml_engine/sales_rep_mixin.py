import pandas as pd
import numpy as np

class SalesRepMixin:
    """Methods for computing Sales Representative Performance."""

    def ensure_sales_rep_data(self):
        """Loads and processes all sales rep data into a single leaderboard dataframe."""
        if getattr(self, "df_sales_rep", None) is not None:
            return

        db = self.repo
        
        # 1. Fetch tables
        users = db.fetch_table_data("auth_user")
        tx = db.fetch_table_data("transactions_dsr")
        tx_prod = db.fetch_table_data("transactions_dsr_products")
        tours = db.fetch_table_data("apps_tour_tourplan")
        expenses = db.fetch_table_data("apps_tours_expense")
        calls = db.fetch_table_data("primary_dashboard_call_log")
        issues = db.fetch_table_data("primary_dashboard_issue")
        
        if users.empty or tx.empty:
            self.df_sales_rep = pd.DataFrame()
            self._tx_merged = pd.DataFrame()
            return
            
        # Ensure ID columns are numeric
        users["id"] = pd.to_numeric(users["id"], errors="coerce")
        tx["user_id"] = pd.to_numeric(tx["user_id"], errors="coerce")
        tx["id"] = pd.to_numeric(tx["id"], errors="coerce")
        tx["date"] = pd.to_datetime(tx["date"], errors="coerce")
        
        # ── Filter ONLY active users (still in the organisation) ──────────────
        if "is_active" in users.columns:
            users["is_active"] = users["is_active"].astype(str).str.lower()
            users = users[users["is_active"].isin(["true", "1", "yes"])].copy()
        
        # 2. Revenue by sales rep (join products to get actual net_amt)
        if not tx_prod.empty:
            tx_prod["dsr_id"] = pd.to_numeric(tx_prod["dsr_id"], errors="coerce")
            tx_prod["net_amt"] = pd.to_numeric(tx_prod["net_amt"], errors="coerce").fillna(0)
            
            # Merge products → transactions (captures revenue per line item)
            tx_merged = tx.merge(tx_prod, left_on="id", right_on="dsr_id", how="left")
        else:
            tx_merged = tx.copy()
            tx_merged["net_amt"] = 0

        # Cache for drilldown queries
        self._tx_merged = tx_merged

        rep_sales = tx_merged.groupby("user_id").agg(
            total_orders=("id_x" if "id_x" in tx_merged.columns else "id", "nunique"),
            total_revenue=("net_amt", "sum"),
            unique_customers=("party_id", "nunique")
        ).reset_index()
        
        # 3. Tours
        if not tours.empty:
            tours["created_by_id"] = pd.to_numeric(tours["created_by_id"], errors="coerce")
            rep_tours = tours.groupby("created_by_id").agg(
                total_tours=("id", "count")
            ).reset_index().rename(columns={"created_by_id": "user_id"})
        else:
            rep_tours = pd.DataFrame({"user_id": [], "total_tours": []})
            
        # 4. Expenses
        if not expenses.empty:
            expenses["created_by_id"] = pd.to_numeric(expenses["created_by_id"], errors="coerce")
            expenses["amount"] = pd.to_numeric(expenses["amount"], errors="coerce").fillna(0)
            rep_exp = expenses.groupby("created_by_id").agg(
                total_expenses=("amount", "sum")
            ).reset_index().rename(columns={"created_by_id": "user_id"})
        else:
            rep_exp = pd.DataFrame({"user_id": [], "total_expenses": []})
            
        # 5. Issues Raised
        if not issues.empty:
            issues["created_by_id"] = pd.to_numeric(issues["created_by_id"], errors="coerce")
            rep_issues = issues.groupby("created_by_id").agg(
                issues_logged=("id", "count")
            ).reset_index().rename(columns={"created_by_id": "user_id"})
        else:
            rep_issues = pd.DataFrame({"user_id": [], "issues_logged": []})

        # Merge everything (only for active users)
        df = users[["id", "first_name", "last_name", "username", "email", "is_active", "last_login"]].copy()
        df.rename(columns={"id": "user_id"}, inplace=True)
        
        # Create full name
        df["first_name"] = df["first_name"].fillna("")
        df["last_name"] = df["last_name"].fillna("")
        df["sales_rep_name"] = (df["first_name"] + " " + df["last_name"]).str.strip()
        df["sales_rep_name"] = np.where(df["sales_rep_name"] == "", df["username"], df["sales_rep_name"])
        
        # Merge metrics
        df = df.merge(rep_sales, on="user_id", how="left")
        df = df.merge(rep_tours, on="user_id", how="left")
        df = df.merge(rep_exp, on="user_id", how="left")
        df = df.merge(rep_issues, on="user_id", how="left")
        
        # Fill NA
        for col in ["total_orders", "total_revenue", "unique_customers", "total_tours", "total_expenses", "issues_logged"]:
            if col in df.columns:
                df[col] = df[col].fillna(0)
                
        # Filter only reps who have actually done something
        df = df[
            (df["total_orders"] > 0) | 
            (df["total_tours"] > 0) | 
            (df["total_expenses"] > 0)
        ].copy()
        
        # Calculate True ROI: Revenue / Expense multiplier
        df["revenue_roi"] = np.where(
            df["total_expenses"] > 0,
            df["total_revenue"] / df["total_expenses"],
            np.where(df["total_revenue"] > 0, 9999.0, 0.0)
        )
        df["expense_per_order"] = 0  # Deprecated

        # Sort by best true performer (Revenue)
        df = df.sort_values("total_revenue", ascending=False)
        self.df_sales_rep = df

    def get_sales_rep_leaderboard(self):
        self.ensure_sales_rep_data()
        if getattr(self, "df_sales_rep", None) is None:
            return pd.DataFrame()
        return self.df_sales_rep.copy()

    def get_sales_rep_monthly_revenue(self, user_id: int, forecast_months: int = 3) -> pd.DataFrame:
        """Returns a dataframe with monthly revenue for a specific rep plus a linear forecast.
        
        Returns columns: ['month', 'revenue', 'type'] where type is 'Actual' or 'Forecast'.
        """
        self.ensure_sales_rep_data()
        
        tx_merged = getattr(self, "_tx_merged", pd.DataFrame())
        if tx_merged.empty:
            return pd.DataFrame(columns=["month", "revenue", "type"])

        # ── Filter to this rep ────────────────────────────────────────────────
        rep_tx = tx_merged[tx_merged["user_id"] == user_id].copy()
        if rep_tx.empty:
            return pd.DataFrame(columns=["month", "revenue", "type"])
        
        date_col = "date" if "date" in rep_tx.columns else None
        if date_col is None:
            return pd.DataFrame(columns=["month", "revenue", "type"])

        rep_tx["date"] = pd.to_datetime(rep_tx[date_col], errors="coerce")
        rep_tx = rep_tx.dropna(subset=["date"])
        rep_tx["month"] = rep_tx["date"].dt.to_period("M")
        rep_tx["net_amt"] = pd.to_numeric(rep_tx["net_amt"], errors="coerce").fillna(0)

        # Monthly aggregation
        monthly = (
            rep_tx.groupby("month")["net_amt"]
            .sum()
            .reset_index()
            .rename(columns={"net_amt": "revenue"})
            .sort_values("month")
        )
        monthly["month"] = monthly["month"].astype(str)
        monthly["type"] = "Actual"

        # ── Linear Regression Forecast ────────────────────────────────────────
        if len(monthly) >= 3 and forecast_months > 0:
            try:
                x = np.arange(len(monthly)).reshape(-1, 1)
                y = monthly["revenue"].values

                # numpy polyfit (degree 1 = linear) - no sklearn dependency needed
                coeffs = np.polyfit(x.flatten(), y, deg=1)
                slope, intercept = coeffs[0], coeffs[1]

                last_month = pd.Period(monthly["month"].iloc[-1], freq="M")
                forecast_rows = []
                for i in range(1, forecast_months + 1):
                    next_period = last_month + i
                    pred_revenue = max(0, slope * (len(monthly) + i - 1) + intercept)
                    forecast_rows.append({
                        "month": str(next_period),
                        "revenue": round(pred_revenue, 2),
                        "type": "Forecast"
                    })
                
                monthly = pd.concat([monthly, pd.DataFrame(forecast_rows)], ignore_index=True)
            except Exception:
                pass  # If forecast fails, just return actual data

        return monthly
