import os
import urllib.parse
from sqlalchemy import create_engine, text

def get_engine():
    env_url = os.getenv("SALES_DB_URL")
    if env_url:
        db_url = env_url
    else:
        user = os.getenv("SALES_DB_USER", "postgres")
        password = urllib.parse.quote_plus(os.getenv("SALES_DB_PASSWORD", "CHAHIT123"))
        host = os.getenv("SALES_DB_HOST", "127.0.0.1")
        port = os.getenv("SALES_DB_PORT", "5432")
        name = os.getenv("SALES_DB_NAME", "dsr_live_local")
        db_url = f"postgresql://{user}:{password}@{host}:{port}/{name}"
    return create_engine(db_url)

def init_mvs():
    engine = get_engine()
    print("Connecting to database to initialize Materialized Views...")
    
    with engine.begin() as conn:
        print("Creating mv_product_elasticity_stats...")
        # Get the actual approved condition from the ML Engine so we don't hardcode wrong columns
        from ml_engine.sales_model import SalesIntelligenceEngine
        ai = SalesIntelligenceEngine()
        approved_cond = ai._approved_condition("t")
        if not approved_cond: approved_cond = "TRUE"
        
        # also for raw table without 't.' prefix
        approved_cond_raw = approved_cond.replace("t.", "")

        # Materialized View for Price Elasticity and Historical Averages
        conn.execute(text(f"""
            CREATE MATERIALIZED VIEW IF NOT EXISTS mv_product_elasticity_stats AS
            WITH max_date_cte AS (
                SELECT MAX(date)::date AS last_recorded_date
                FROM transactions_dsr
                WHERE {approved_cond_raw}
            ),
            partner_stats AS (
                SELECT
                    tp.product_id,
                    t.company_name AS partner_name,
                    AVG(tp.qty) as avg_qty,
                    STDDEV(tp.qty) as std_qty,
                    AVG(tp.net_amt::double precision / NULLIF(tp.qty, 0)) as avg_price,
                    STDDEV(tp.net_amt::double precision / NULLIF(tp.qty, 0)) as std_price
                FROM transactions_dsr t
                JOIN transactions_dsr_products tp ON t.id = tp.dsr_id
                CROSS JOIN max_date_cte md
                WHERE {approved_cond}
                  AND t.date >= md.last_recorded_date - INTERVAL '180 days'
                GROUP BY tp.product_id, t.company_name
            )
            SELECT
                p.product_name,
                ps.partner_name,
                ps.avg_qty,
                ps.std_qty,
                ps.avg_price,
                ps.std_price,
                (ps.std_qty / NULLIF(ps.avg_qty, 0)) as volume_cv,
                (ps.std_price / NULLIF(ps.avg_price, 0)) as price_cv
            FROM partner_stats ps
            JOIN master_products p ON ps.product_id = p.id;
        """))

        print("Creating unique index on mv_product_elasticity_stats...")
        # Add index for concurrent refresh and fast lookups
        conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_elasticity_prod_partner
            ON mv_product_elasticity_stats (product_name, partner_name);
        """))

        print("Refreshing Materialized Views...")
        conn.execute(text("REFRESH MATERIALIZED VIEW mv_product_elasticity_stats;"))
        
    print("Materialized Views successfully initialized!")

if __name__ == "__main__":
    init_mvs()
