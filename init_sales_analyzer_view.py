"""
Run this script ONCE to create the view_sales_analyzer_partner_summary
materialized view in the database.

Usage:
    python init_sales_analyzer_view.py
"""
import os, sys
import sqlalchemy
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))
sys.path.insert(0, os.path.dirname(__file__))

from ml_engine.sales_model import SalesIntelligenceEngine

SQL = open(
    os.path.join(os.path.dirname(__file__), "db", "sales_analyzer_view.sql"),
    encoding="utf-8",
).read()

print("Connecting to database…")
ai = SalesIntelligenceEngine()
engine = ai.engine

with engine.begin() as conn:
    for stmt in SQL.split(";"):
        # strip and skip blank / comment-only chunks
        lines = [l for l in stmt.strip().splitlines() if not l.strip().startswith("--")]
        clean = "\n".join(lines).strip()
        if clean:
            conn.execute(sqlalchemy.text(clean))
    print("SUCCESS: view_sales_analyzer_partner_summary created/refreshed.")
