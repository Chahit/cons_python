import os, sys; sys.path.insert(0,'.')
from dotenv import load_dotenv; load_dotenv()
from ml_engine.sales_model import SalesIntelligenceEngine
import pandas as pd
ai = SalesIntelligenceEngine()
df = pd.read_sql("SELECT COUNT(1) AS rows, COUNT(DISTINCT state_name) AS states, COUNT(DISTINCT city_name) AS cities FROM view_sales_analyzer_partner_summary", ai.engine)
print(df.to_string())
