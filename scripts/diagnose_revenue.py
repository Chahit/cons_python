# -*- coding: utf-8 -*-
"""
Revenue Diagnostic v2 - tests additional approaches including
'only billed orders' (INNER JOIN due_payment)
"""
import psycopg2
from psycopg2.extras import RealDictCursor
import sys

DB = dict(host="127.0.0.1", port=5432, dbname="dsr_live_local",
          user="postgres", password="CHAHIT123")

PARTNER = "Tanishq Infotech LLP"
PERIODS = [
    ("Jan 2026", "2026-01-01", "2026-01-31", 6.31),
    ("Feb 2026", "2026-02-01", "2026-02-28", 4.20),
    ("Mar 2026", "2026-03-01", "2026-03-31", 2.53),
]

conn = psycopg2.connect(**DB)
cur  = conn.cursor(cursor_factory=RealDictCursor)

cur.execute("SELECT id FROM master_party WHERE company_name = %s LIMIT 1", (PARTNER,))
row = cur.fetchone()
party_id = row["id"]
print("\nParty ID:", party_id)

def cr(v): return f"{v/1e7:.2f}Cr"
def match(v, exp): return " OK" if abs(v/1e7 - exp) < 0.02 else "   "

print(f"\n{'Period':<10} {'A:cur':>9} {'B:+active':>11} {'E:+billed':>11} {'F:billed_net':>13} {'G:bill_date':>12} {'EXPECTED':>10}")
print("-" * 80)

for label, s, e, exp in PERIODS:
    # A: current (is_approved only)
    cur.execute("""
        SELECT COALESCE(SUM(tp.net_amt),0) AS rev
        FROM transactions_dsr t JOIN transactions_dsr_products tp ON tp.dsr_id=t.id
        WHERE LOWER(CAST(t.is_approved AS TEXT))='true'
          AND t.party_id=%s AND t.date BETWEEN %s AND %s
    """, (party_id, s, e))
    rev_a = float(cur.fetchone()["rev"])

    # B: + is_active
    cur.execute("""
        SELECT COALESCE(SUM(tp.net_amt),0) AS rev
        FROM transactions_dsr t JOIN transactions_dsr_products tp ON tp.dsr_id=t.id
        WHERE LOWER(CAST(t.is_approved AS TEXT))='true' AND t.is_active=true
          AND t.party_id=%s AND t.date BETWEEN %s AND %s
    """, (party_id, s, e))
    rev_b = float(cur.fetchone()["rev"])

    # E: only transactions that HAVE a due_payment record (inner join)
    # Uses order date (t.date) for period filter
    cur.execute("""
        SELECT COALESCE(SUM(tp.net_amt),0) AS rev
        FROM transactions_dsr t
        JOIN transactions_dsr_products tp ON tp.dsr_id=t.id
        JOIN due_payment dp ON dp.dsr_id=t.id
             AND dp.is_active=TRUE AND dp.deleted_at IS NULL
        WHERE LOWER(CAST(t.is_approved AS TEXT))='true'
          AND t.party_id=%s AND t.date BETWEEN %s AND %s
    """, (party_id, s, e))
    rev_e = float(cur.fetchone()["rev"])

    # F: sum of due_payment.net_amt where order date in period (billing amount, not order amount)
    cur.execute("""
        SELECT COALESCE(SUM(dp.net_amt),0) AS rev
        FROM transactions_dsr t
        JOIN due_payment dp ON dp.dsr_id=t.id
             AND dp.is_active=TRUE AND dp.deleted_at IS NULL
        WHERE LOWER(CAST(t.is_approved AS TEXT))='true'
          AND t.party_id=%s AND t.date BETWEEN %s AND %s
    """, (party_id, s, e))
    rev_f = float(cur.fetchone()["rev"])

    # G: due_payment.net_amt where BILL DATE in period (billing date view)
    cur.execute("""
        SELECT COALESCE(SUM(dp.net_amt),0) AS rev
        FROM due_payment dp
        JOIN transactions_dsr t ON t.id=dp.dsr_id
        WHERE dp.is_active=TRUE AND dp.deleted_at IS NULL
          AND t.party_id=%s AND dp.bill_date::date BETWEEN %s AND %s
    """, (party_id, s, e))
    rev_g = float(cur.fetchone()["rev"])

    print(f"{label:<10} {cr(rev_a):>8}{match(rev_a,exp)} {cr(rev_b):>10}{match(rev_b,exp)} "
          f"{cr(rev_e):>10}{match(rev_e,exp)} {cr(rev_f):>12}{match(rev_f,exp)} "
          f"{cr(rev_g):>11}{match(rev_g,exp)} {exp:>9.2f}Cr")

# Count billed vs total orders for Feb
print("\n--- Feb 2026: How many DSR orders have/lack due_payment ---")
cur.execute("""
    SELECT
      COUNT(DISTINCT t.id) AS total_orders,
      COUNT(DISTINCT dp.dsr_id) AS billed_orders,
      COUNT(DISTINCT t.id) - COUNT(DISTINCT dp.dsr_id) AS unbilled_orders,
      COALESCE(SUM(CASE WHEN dp.dsr_id IS NULL THEN tp.net_amt ELSE 0 END),0) AS unbilled_revenue
    FROM transactions_dsr t
    JOIN transactions_dsr_products tp ON tp.dsr_id=t.id
    LEFT JOIN due_payment dp ON dp.dsr_id=t.id AND dp.is_active=TRUE AND dp.deleted_at IS NULL
    WHERE LOWER(CAST(t.is_approved AS TEXT))='true'
      AND t.party_id=%s AND t.date BETWEEN '2026-02-01' AND '2026-02-28'
""", (party_id,))
r = cur.fetchone()
print("  Total orders   :", r["total_orders"])
print("  Billed orders  :", r["billed_orders"])
print("  Unbilled orders:", r["unbilled_orders"])
print("  Unbilled rev   :", cr(float(r["unbilled_revenue"])))

# Check dp.approve field
print("\n--- Feb 2026: due_payment approval status ---")
cur.execute("""
    SELECT dp.approve, COUNT(*) AS cnt, COALESCE(SUM(dp.net_amt),0) AS total
    FROM transactions_dsr t
    JOIN due_payment dp ON dp.dsr_id=t.id AND dp.is_active=TRUE AND dp.deleted_at IS NULL
    WHERE LOWER(CAST(t.is_approved AS TEXT))='true'
      AND t.party_id=%s AND t.date BETWEEN '2026-02-01' AND '2026-02-28'
    GROUP BY dp.approve
""", (party_id,))
for r in cur.fetchall():
    print(f"  dp.approve={r['approve']}  count={r['cnt']}  total={cr(float(r['total']))}")

# Try dp.approve=True filter
print("\n--- Approach H: due_payment with dp.approve=TRUE, order date ---")
for label, s, e, exp in PERIODS:
    cur.execute("""
        SELECT COALESCE(SUM(dp.net_amt),0) AS rev
        FROM transactions_dsr t
        JOIN due_payment dp ON dp.dsr_id=t.id
             AND dp.is_active=TRUE AND dp.deleted_at IS NULL AND dp.approve=TRUE
        WHERE LOWER(CAST(t.is_approved AS TEXT))='true'
          AND t.party_id=%s AND t.date BETWEEN %s AND %s
    """, (party_id, s, e))
    rev_h = float(cur.fetchone()["rev"])
    print(f"  {label}: {cr(rev_h)}{match(rev_h,exp)}  (expected {exp:.2f}Cr)")

cur.close()
conn.close()
print("\nDone.")
