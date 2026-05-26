"""
Clustering Coverage Audit — uses the correct is_approved condition.
"""
import sys, os
sys.path.insert(0, '.')
from ml_engine.sales_model import SalesIntelligenceEngine
SalesIntelligenceEngine._load_local_env_file()
import sqlalchemy, pandas as pd

db_url = os.getenv("SALES_DB_URL") or (
    f"postgresql://{os.getenv('SALES_DB_USER','')}:{os.getenv('SALES_DB_PASSWORD','')}@"
    f"{os.getenv('SALES_DB_HOST','127.0.0.1')}:{os.getenv('SALES_DB_PORT','5432')}/"
    f"{os.getenv('SALES_DB_NAME','')}"
)
engine = sqlalchemy.create_engine(db_url, connect_args={"connect_timeout": 5})

APPROVED = "LOWER(CAST(t.is_approved AS TEXT)) = 'true'"

print("=" * 60)
print("CLUSTERING COVERAGE AUDIT")
print("=" * 60)

# 1. All companies in master_party
try:
    all_df = pd.read_sql("SELECT company_name FROM master_party WHERE company_name IS NOT NULL", engine)
    n_all = len(all_df)
    all_names = set(all_df["company_name"].dropna().str.strip())
    print(f"\n[master_party] Total companies: {n_all}")
except Exception as e:
    print(f"\n[master_party] FAILED: {e}")
    all_names = set(); n_all = 0

# 2. Companies with recent group-level spend (the clustering data source)
try:
    gs_query = f"""
    SELECT DISTINCT mp.company_name
    FROM transactions_dsr t
    JOIN transactions_dsr_products tp ON t.id = tp.dsr_id
    JOIN master_products p ON tp.product_id = p.id
    JOIN master_group mg ON p.group_id = mg.id
    JOIN master_party mp ON t.party_id = mp.id
    WHERE {APPROVED}
      AND t.date >= CURRENT_DATE - INTERVAL '365 days'
    """
    gs_df = pd.read_sql(gs_query, engine)
    n_gs = len(gs_df)
    gs_names = set(gs_df["company_name"].dropna().str.strip())
    print(f"[group_spend_1yr] Companies with approved transactions: {n_gs} ({n_gs/max(n_all,1)*100:.1f}% of master)")
except Exception as e:
    print(f"[group_spend_1yr] FAILED: {e}")
    gs_names = set(); n_gs = 0

# 3. Companies in view_ml_input
try:
    ml_df = pd.read_sql("SELECT DISTINCT company_name FROM view_ml_input", engine)
    n_ml = len(ml_df)
    ml_names = set(ml_df["company_name"].dropna().str.strip())
    print(f"[view_ml_input]  Companies with ML features: {n_ml} ({n_ml/max(n_all,1)*100:.1f}% of master)")
except Exception as e:
    print(f"[view_ml_input] FAILED: {e}")
    ml_names = set(); n_ml = 0

# 4. Gap analysis
missing = all_names - gs_names
print(f"\n--- RESULTS ---")
print(f"Unclustered companies (in master_party but no recent transactions): {len(missing)} ({len(missing)/max(n_all,1)*100:.1f}%)")
print(f"Clustered companies: {len(gs_names)} ({len(gs_names)/max(n_all,1)*100:.1f}%)")
if missing:
    print(f"\nSample unclustered (first 15):")
    for c in sorted(list(missing))[:15]:
        print(f"  - {c}")

print("\nDone.")
