"""
Sales Analyzer Tab
Cascading geo-drill: State → City → Partner
Calendar date-range picker + KPI summary + product breakdown
"""

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import sys, os
from datetime import date, timedelta

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from styles import apply_global_styles, page_header
from tabs.sales_analyzer_extras import (
    fetch_yoy_kpis, predict_next_order, fetch_repeat_new,
    fetch_multi_partner_kpis, fetch_multi_monthly,
    export_excel, export_pdf,
)

# ── Approved condition ────────────────────────────────────────────────────────
_APPROVED = "LOWER(CAST(t.is_approved AS TEXT)) = 'true'"

# ── Preset chips ──────────────────────────────────────────────────────────────
_SA_PRESETS = [
    {"label": "15 Days", "days": 15},
    {"label": "1 Month", "days": 30},
    {"label": "2 Months", "days": 60},
    {"label": "3 Months", "days": 90},
    {"label": "6 Months", "days": 180},
    {"label": "1 Year",   "days": 365},
]


# ── Helpers ───────────────────────────────────────────────────────────────────

@st.cache_data(ttl=600, show_spinner=False)
def _load_geo_summary(_engine):
    """Load the materialized view (state / city / partner lookup)."""
    try:
        return pd.read_sql(
            "SELECT party_id, company_name, mobile_no, state_name, city_name, "
            "total_orders, total_revenue, last_order_date, first_order_date, unique_products "
            "FROM view_sales_analyzer_partner_summary "
            "WHERE total_orders > 0 ORDER BY company_name",
            _engine,
        )
    except Exception:
        # Fallback: build from raw tables if the view hasn't been created yet
        try:
            return pd.read_sql(
                """
                SELECT mp.id AS party_id, mp.company_name, mp.mobile_no,
                       COALESCE(ms.state_name,'Unknown') AS state_name,
                       COALESCE(mc.name,'Unknown')       AS city_name,
                       COUNT(DISTINCT t.id)              AS total_orders,
                       COALESCE(SUM(tp.net_amt),0)       AS total_revenue,
                       MAX(t.date)  AS last_order_date,
                       MIN(t.date)  AS first_order_date,
                       COUNT(DISTINCT tp.product_id) AS unique_products
                FROM master_party mp
                LEFT JOIN master_state ms ON ms.id = mp.state_id
                LEFT JOIN master_city  mc ON mc.id = mp.city_id
                LEFT JOIN transactions_dsr t
                       ON t.party_id = mp.id
                      AND LOWER(CAST(t.is_approved AS TEXT)) = 'true'
                LEFT JOIN transactions_dsr_products tp ON tp.dsr_id = t.id
                GROUP BY mp.id, mp.company_name, mp.mobile_no, ms.state_name, mc.name
                HAVING COUNT(DISTINCT t.id) > 0
                ORDER BY mp.company_name
                """,
                _engine,
            )
        except Exception:
            return pd.DataFrame()


@st.cache_data(ttl=120, show_spinner=False)
def _fetch_partner_kpis(_engine, party_id: int, start: date, end: date) -> dict:
    """Revenue KPIs for a partner within the date window."""
    try:
        df = pd.read_sql(
            """
            SELECT
                COUNT(DISTINCT t.id)           AS orders,
                COALESCE(SUM(tp.net_amt), 0)   AS revenue,
                COALESCE(SUM(tp.qty), 0)       AS total_qty,
                COUNT(DISTINCT tp.product_id)  AS unique_products,
                MAX(t.date)                    AS last_order
            FROM transactions_dsr t
            JOIN transactions_dsr_products tp ON tp.dsr_id = t.id
            WHERE LOWER(CAST(t.is_approved AS TEXT)) = 'true'
              AND t.party_id = %(pid)s
              AND t.date BETWEEN %(s)s AND %(e)s
            """,
            _engine,
            params={"pid": party_id, "s": start, "e": end},
        )
        if df.empty:
            return {}
        r = df.iloc[0]
        return {
            "orders":          int(r["orders"]),
            "revenue":         float(r["revenue"]),
            "total_qty":       float(r["total_qty"]),
            "unique_products": int(r["unique_products"]),
            "last_order":      str(r["last_order"]) if r["last_order"] else "—",
        }
    except Exception:
        return {}


@st.cache_data(ttl=120, show_spinner=False)
def _fetch_product_breakdown(_engine, party_id: int, start: date, end: date) -> pd.DataFrame:
    """Product-level detail: qty, rate, net_amt, category, last purchase."""
    try:
        return pd.read_sql(
            """
            SELECT
                p.product_name,
                COALESCE(mg.group_name, 'General')      AS product_group,
                COALESCE(mpc.category_name, 'General')  AS category,
                SUM(tp.qty)                             AS total_qty,
                ROUND(AVG(tp.net_amt / NULLIF(tp.qty, 0))::NUMERIC, 2) AS avg_rate,
                ROUND(SUM(tp.net_amt)::NUMERIC, 2)      AS total_amount,
                COUNT(DISTINCT t.id)                    AS txn_count,
                MAX(t.date)                             AS last_purchased
            FROM transactions_dsr t
            JOIN transactions_dsr_products tp  ON tp.dsr_id = t.id
            JOIN master_products p             ON p.id = tp.product_id
            LEFT JOIN master_group mg          ON mg.id = p.group_id
            LEFT JOIN master_product_category mpc ON mpc.id = mg.category_id_id
            WHERE LOWER(CAST(t.is_approved AS TEXT)) = 'true'
              AND t.party_id = %(pid)s
              AND t.date BETWEEN %(s)s AND %(e)s
            GROUP BY p.product_name, mg.group_name, mpc.category_name
            ORDER BY total_amount DESC
            """,
            _engine,
            params={"pid": party_id, "s": start, "e": end},
        )
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=120, show_spinner=False)
def _fetch_monthly_revenue(_engine, party_id: int, start: date, end: date) -> pd.DataFrame:
    """Month-by-month revenue for the bar chart."""
    try:
        return pd.read_sql(
            """
            SELECT
                DATE_TRUNC('month', t.date)::date AS month,
                ROUND(SUM(tp.net_amt)::NUMERIC, 2) AS revenue,
                COUNT(DISTINCT t.id)               AS orders
            FROM transactions_dsr t
            JOIN transactions_dsr_products tp ON tp.dsr_id = t.id
            WHERE LOWER(CAST(t.is_approved AS TEXT)) = 'true'
              AND t.party_id = %(pid)s
              AND t.date BETWEEN %(s)s AND %(e)s
            GROUP BY DATE_TRUNC('month', t.date)
            ORDER BY month
            """,
            _engine,
            params={"pid": party_id, "s": start, "e": end},
        )
    except Exception:
        return pd.DataFrame()




@st.cache_data(ttl=300, show_spinner=False)
def _fetch_alltime_history(_engine, party_id: int):
    """All-time product purchase history for a partner (no date filter)."""
    try:
        return pd.read_sql(
            """
            SELECT
                p.product_name,
                COALESCE(mg.group_name, 'General')      AS product_group,
                COALESCE(mpc.category_name, 'General')  AS category,
                SUM(tp.qty)                             AS total_qty,
                ROUND(AVG(tp.net_amt / NULLIF(tp.qty, 0))::NUMERIC, 2)         AS avg_rate,
                ROUND(SUM(tp.net_amt)::NUMERIC, 2)      AS total_amount,
                COUNT(DISTINCT t.id)                    AS txn_count,
                MIN(t.date)                             AS first_purchased,
                MAX(t.date)                             AS last_purchased
            FROM transactions_dsr t
            JOIN transactions_dsr_products tp  ON tp.dsr_id = t.id
            JOIN master_products p             ON p.id = tp.product_id
            LEFT JOIN master_group mg          ON mg.id = p.group_id
            LEFT JOIN master_product_category mpc ON mpc.id = mg.category_id_id
            WHERE LOWER(CAST(t.is_approved AS TEXT)) = 'true'
              AND t.party_id = %(pid)s
            GROUP BY p.product_name, mg.group_name, mpc.category_name
            ORDER BY total_amount DESC
            """,
            _engine,
            params={"pid": party_id},
        )
    except Exception:
        return pd.DataFrame()

def _fmt_inr(val: float) -> str:
    if val >= 1_00_00_000:
        return f"₹{val/1_00_00_000:.2f} Cr"
    if val >= 1_00_000:
        return f"₹{val/1_00_000:.2f} L"
    return f"₹{val:,.0f}"


@st.cache_data(ttl=120, show_spinner=False)
def _fetch_overview_stats(_engine, party_ids: tuple, start: date, end: date) -> pd.DataFrame:
    """Live aggregate revenue/orders for selected partners within the date window."""
    if not party_ids:
        return pd.DataFrame()
    try:
        ids_str = ",".join(str(i) for i in party_ids)
        return pd.read_sql(
            f"""SELECT mp.company_name,
                       COALESCE(SUM(tp.net_amt),0) AS period_revenue,
                       COUNT(DISTINCT t.id)         AS period_orders
                FROM transactions_dsr t
                JOIN transactions_dsr_products tp ON tp.dsr_id = t.id
                JOIN master_party mp ON mp.id = t.party_id
                WHERE LOWER(CAST(t.is_approved AS TEXT)) = 'true'
                  AND t.party_id IN ({ids_str})
                  AND t.date BETWEEN %(s)s AND %(e)s
                GROUP BY mp.company_name""",
            _engine, params={"s": start, "e": end},
        )
    except Exception:
        return pd.DataFrame()


# ── Date picker ───────────────────────────────────────────────────────────────

def _render_date_picker() -> tuple:
    st.markdown("""
    <style>
    div[data-testid="column"] .stButton>button{
        border-radius:20px!important;font-size:12px!important;
        padding:4px 14px!important;border:1px solid #374151!important;
        background:#1e2235!important;color:#34d399!important;
        transition:all 0.18s ease!important;
    }
    div[data-testid="column"] .stButton>button:hover{
        background:#059669!important;border-color:#059669!important;color:#fff!important;
    }
    </style>""", unsafe_allow_html=True)

    today = date.today()
    if "sa_date_start" not in st.session_state:
        st.session_state["sa_date_start"] = today - timedelta(days=5 * 365)  # 5-year default
    if "sa_date_end" not in st.session_state:
        st.session_state["sa_date_end"] = today



    # Manual range
    st.markdown("<div style='font-size:11px;color:#64748b;margin-top:10px;margin-bottom:4px;'>🗓️ Custom Range</div>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1.5, 1.5, 1])
    with c1:
        new_start = st.date_input("Start Date", value=st.session_state["sa_date_start"],
                                  max_value=today, key="sa_cal_start")
    with c2:
        new_end = st.date_input("End Date", value=st.session_state["sa_date_end"],
                                min_value=new_start, max_value=today, key="sa_cal_end")
    with c3:
        st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        if st.button("✅ Apply", key="sa_apply", use_container_width=True):
            st.session_state["sa_date_start"] = new_start
            st.session_state["sa_date_end"]   = new_end

    sel_start = st.session_state["sa_date_start"]
    sel_end   = st.session_state["sa_date_end"]
    if sel_end < sel_start:
        sel_end = sel_start
    span = max((sel_end - sel_start).days, 1)
    label = f"{sel_start.strftime('%d %b %Y')} → {sel_end.strftime('%d %b %Y')}  ({span}d)"

    st.markdown(f"""
    <div style='background:rgba(15,26,43,0.9);border:1px solid #1e3a5f;border-radius:8px;
         padding:8px 16px;margin-top:8px;display:flex;align-items:center;gap:10px;'>
      <span style='font-size:15px;'>📅</span>
      <span style='color:#6ee7b7;font-size:13px;font-weight:600;'>Active Window</span>
      <span style='color:#475569;'>–</span>
      <span style='color:#64748b;font-size:12px;'>
        <b style='color:#7eb8f0;'>{sel_start.strftime('%d %b %Y')}</b>
        &nbsp;→&nbsp;
        <b style='color:#7eb8f0;'>{sel_end.strftime('%d %b %Y')}</b>
      </span>
      <span style='margin-left:auto;font-size:11px;color:#4b5563;'>{span} day window</span>
    </div>""", unsafe_allow_html=True)

    return sel_start, sel_end, label, span


# ── Main render ───────────────────────────────────────────────────────────────

def render(ai):
    page_header(
        "📈 Sales Analyzer",
        "Drill down by State → City → Partner and explore purchase history over any date window",
    )

    engine = getattr(ai, "engine", None)
    if engine is None:
        st.error("Database engine not available.")
        return

    # ── Handle quick-jump from Kanban ─────────────────────────────────────────
    if "sa_preselect_partner" in st.session_state and st.session_state["sa_preselect_partner"]:
        _pname = st.session_state.pop("sa_preselect_partner")
        st.session_state["sa_partner"] = _pname

    # ── Load geo summary ──────────────────────────────────────────────────────
    with st.spinner("Loading partner geography…"):
        geo = _load_geo_summary(engine)

    if geo.empty:
        st.warning("No partner data found. Ensure the view_sales_analyzer_partner_summary "
                   "materialized view has been created and data exists.")
        with st.expander("📋 View SQL to create the materialized view"):
            st.code(open(os.path.join(os.path.dirname(__file__), "..", "..",
                         "db", "sales_analyzer_view.sql")).read(), language="sql")
        return

    # ── Date picker ───────────────────────────────────────────────────────────
    sel_start, sel_end, date_label, span_days = _render_date_picker()
    st.markdown("---")

    # ── Cascading Geo Filters ─────────────────────────────────────────────────


    f1, f2, f3 = st.columns([1, 1, 2])

    with f1:
        states = sorted(geo["state_name"].dropna().unique().tolist())
        sel_state = st.selectbox("State", ["— All States —"] + states, key="sa_state")

    with f2:
        if sel_state and sel_state != "— All States —":
            cities = sorted(geo[geo["state_name"] == sel_state]["city_name"].dropna().unique().tolist())
        else:
            cities = sorted(geo["city_name"].dropna().unique().tolist())
        sel_city = st.selectbox("City / Area", ["— All Cities —"] + cities, key="sa_city")

    with f3:
        mask = pd.Series([True] * len(geo))
        if sel_state and sel_state != "— All States —":
            mask &= geo["state_name"] == sel_state
        if sel_city and sel_city != "— All Cities —":
            mask &= geo["city_name"] == sel_city
        partner_df = geo[mask].copy()
        partner_options = partner_df["company_name"].dropna().unique().tolist()
        partner_options = sorted(partner_options)
        sel_partner = st.selectbox("Partner / Company", ["— Select a Partner —"] + partner_options,
                                   key="sa_partner")

    st.markdown("</div>", unsafe_allow_html=True)

    # ── Summary cards (no partner needed — show state/city totals) ────────────
    if sel_partner == "— Select a Partner —":
        # Show aggregate stats for current filter using LIVE date-range query
        st.markdown("#### 📊 Overview — Filtered Partners")
        agg = partner_df

        # Live period stats (respects date picker)
        _pid_tuple = tuple(int(i) for i in agg["party_id"].tolist())
        with st.spinner("Loading period stats…"):
            period_stats = _fetch_overview_stats(engine, _pid_tuple, sel_start, sel_end)
        period_rev = float(period_stats["period_revenue"].sum()) if not period_stats.empty else 0.0
        period_ord = int(period_stats["period_orders"].sum())   if not period_stats.empty else 0
        alltime_rev = float(agg["total_revenue"].sum())

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Partners", f"{len(agg):,}")
        c2.metric(f"💰 Revenue ({date_label})", _fmt_inr(period_rev))
        c3.metric(f"📦 Orders ({date_label})", f"{period_ord:,}")
        c4.metric("⏳ All-Time Revenue", _fmt_inr(alltime_rev))

        if not agg.empty:
            st.markdown("#### 🏆 Top Partners by Revenue (Selected Period)")
            # Merge period stats into the top-partners table
            if not period_stats.empty:
                top_merged = agg.merge(period_stats, on="company_name", how="left")
                top_merged["period_revenue"] = top_merged["period_revenue"].fillna(0)
                top = top_merged.nlargest(20, "period_revenue")[
                    ["company_name", "state_name", "city_name",
                     "period_orders", "period_revenue", "total_orders",
                     "total_revenue", "last_order_date"]
                ].copy()
                top["period_revenue"] = top["period_revenue"].apply(_fmt_inr)
                top["total_revenue"]  = top["total_revenue"].apply(_fmt_inr)
                top["period_orders"]  = top["period_orders"].fillna(0).astype(int)
                top.columns = ["Partner", "State", "City",
                               "Orders (Period)", "Revenue (Period)",
                               "Orders (All-Time)", "Revenue (All-Time)", "Last Order"]
            else:
                top = agg.nlargest(20, "total_revenue")[
                    ["company_name", "state_name", "city_name",
                     "total_orders", "total_revenue",
                     "unique_products", "last_order_date"]
                ].copy()
                top["total_revenue"] = top["total_revenue"].apply(_fmt_inr)
                top.columns = ["Partner", "State", "City", "Orders", "Revenue", "Products", "Last Order"]
            st.dataframe(top, use_container_width=True, hide_index=True)
        return

    # ── Partner selected — fetch detailed data ────────────────────────────────
    partner_row = partner_df[partner_df["company_name"] == sel_partner]
    if partner_row.empty:
        st.warning("Partner not found in filtered results.")
        return
    party_id = int(partner_row.iloc[0]["party_id"])

    # Partner info strip
    pr = partner_row.iloc[0]
    st.markdown(f"""
    <div style='background:linear-gradient(135deg,rgba(52,211,153,0.08),rgba(16,185,129,0.04));
         border:1px solid rgba(52,211,153,0.3);border-radius:12px;
         padding:14px 20px;margin-bottom:20px;display:flex;gap:32px;align-items:center;'>
      <div>
        <div style='font-size:18px;font-weight:700;color:#ecfdf5;'>{pr['company_name']}</div>
        <div style='font-size:12px;color:#64748b;margin-top:2px;'>
          📍 {pr['city_name']}, {pr['state_name']}
          {f"&nbsp;&nbsp;📞 {pr['mobile_no']}" if pr.get('mobile_no') else ""}
        </div>
      </div>
      <div style='margin-left:auto;text-align:right;'>
        <div style='font-size:11px;color:#64748b;'>All-Time Revenue</div>
        <div style='font-size:20px;font-weight:700;color:#34d399;'>{_fmt_inr(float(pr['total_revenue']))}</div>
        <div style='font-size:11px;color:#475569;'>{int(pr['total_orders'])} orders · {int(pr['unique_products'])} products</div>
      </div>
    </div>""", unsafe_allow_html=True)

    # ── Fetch data for selected window ────────────────────────────────────────
    with st.spinner("Loading analytics…"):
        kpis     = _fetch_partner_kpis(engine, party_id, sel_start, sel_end)
        prod_df  = _fetch_product_breakdown(engine, party_id, sel_start, sel_end)
        month_df = _fetch_monthly_revenue(engine, party_id, sel_start, sel_end)
        yoy      = fetch_yoy_kpis(engine, party_id, sel_start, sel_end)
        pred     = predict_next_order(engine, party_id)

    st.caption(f"Showing data for: **{date_label}**")

    # ── Mode tabs ─────────────────────────────────────────────────────────────
    tab1, tab2 = st.tabs(["📊 Single Partner", "🔀 Compare Partners"])

    with tab1:
        # Next-order prediction banner
        if pred:
            da   = pred["days_away"]
            conf = pred["confidence"]
            trend_emoji = pred.get("trend_emoji", "➡️")
            trend_label = pred.get("trend_label", "")
            total_ord   = pred.get("total_orders", "")
            cv          = pred.get("cv", "")
            clr  = {"High": "#34d399", "Medium": "#f59e0b"}.get(conf, "#ef4444")
            conf_bg = {"High": "rgba(52,211,153,0.15)", "Medium": "rgba(245,158,11,0.15)"}.get(conf, "rgba(239,68,68,0.15)")
            sign = "in" if da >= 0 else "overdue by"
            pred_date_str = pred["predicted_date"].strftime("%d %b %Y")
            st.markdown(f"""
<div style='background:rgba(15,23,42,0.9);border:1px solid {clr}55;
     border-radius:12px;padding:14px 20px;margin-bottom:16px;'>
  <div style='display:flex;align-items:center;gap:12px;'>
    <span style='font-size:28px;'>🔮</span>
    <div style='flex:1;'>
      <div style='color:{clr};font-weight:700;font-size:14px;margin-bottom:4px;'>
        Next Order Prediction
        <span style='background:{conf_bg};color:{clr};font-size:11px;
          padding:2px 10px;border-radius:10px;margin-left:8px;font-weight:600;border:1px solid {clr}44;'>
          {conf} Confidence
        </span>
      </div>
      <div style='color:#e2e8f0;font-size:13px;'>
        Expected <b style='color:#7eb8f0;'>{pred_date_str}</b>
        &nbsp;···&nbsp;
        <b style='color:#f1f5f9;'>{sign} <span style='color:{clr};'>{abs(da)}</span> days</b>
      </div>
      <div style='display:flex;gap:18px;margin-top:8px;flex-wrap:wrap;'>
        <span style='font-size:11px;color:#64748b;'>
          ⏱️ Avg gap: <b style='color:#94a3b8;'>{pred["avg_gap"]}d</b>
        </span>
        <span style='font-size:11px;color:#64748b;'>
          {trend_emoji} <b style='color:#94a3b8;'>{trend_label}</b>
        </span>
        <span style='font-size:11px;color:#64748b;'>
          📅 Based on <b style='color:#94a3b8;'>{total_ord} orders</b>
        </span>
        <span style='font-size:11px;color:#64748b;'>
          📊 Consistency: <b style='color:#94a3b8;'>CV={cv}</b>
        </span>
      </div>
    </div>
  </div>
</div>""", unsafe_allow_html=True)

        # KPI metrics with YoY deltas
        if not kpis:
            st.info(f"No approved transactions found for **{sel_partner}** in the selected date range.")
        else:
            k1, k2, k3, k4, k5 = st.columns(5)
            yoy_rev = yoy.get("revenue", 0) if yoy else 0
            yoy_ord = yoy.get("orders",  0) if yoy else 0
            rev_delta = ((kpis["revenue"] - yoy_rev) / yoy_rev * 100) if yoy_rev else None
            ord_delta = ((kpis["orders"]  - yoy_ord) / yoy_ord * 100) if yoy_ord else None
            k1.metric("💰 Revenue", _fmt_inr(kpis["revenue"]),
                      delta=f"{rev_delta:+.1f}% YoY" if rev_delta is not None else None)
            k2.metric("📦 Orders", f"{kpis['orders']:,}",
                      delta=f"{ord_delta:+.1f}% YoY" if ord_delta is not None else None)
            k3.metric("🛒 Total Qty", f"{kpis['total_qty']:,.0f}")
            k4.metric("🔢 Products Bought", str(kpis["unique_products"]))
            k5.metric("📅 Last Order", kpis["last_order"])
            if yoy:
                st.caption(f"YoY comparison: {yoy.get('label','')} — "
                           f"Revenue {_fmt_inr(yoy_rev)} · Orders {yoy_ord}")

        # Export buttons
        ex1, ex2, _ = st.columns([1, 1, 3])
        with ex1:
            if kpis:
                xlsx = export_excel(sel_partner, kpis, yoy, prod_df, month_df, sel_start, sel_end)
                st.download_button("📥 Export Excel", data=xlsx,
                    file_name=f"{sel_partner[:20].replace(' ','_')}_{sel_end}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="sa_excel")
        with ex2:
            if kpis:
                pdf_b = export_pdf(sel_partner, str(pr.get("city_name", "")),
                    str(pr.get("state_name", "")), kpis, yoy, prod_df, sel_start, sel_end)
                st.download_button("📄 Export PDF", data=pdf_b,
                    file_name=f"{sel_partner[:20].replace(' ','_')}_{sel_end}.pdf",
                    mime="application/pdf", key="sa_pdf")

        st.markdown("---")



    # ── Compare Tab ───────────────────────────────────────────────────────────

        # ---- All-Time Purchase History ----
        st.markdown('---')
        st.markdown(
            "<div style='display:flex;align-items:center;gap:10px;margin-bottom:8px;'>"
            "<span style='font-size:20px;'>&#128110;</span>"
            "<span style='font-size:16px;font-weight:700;color:#ecfdf5;'>"
            "All-Time Purchase History</span>"
            "<span style='font-size:12px;color:#64748b;margin-left:8px;'>"
            "Every product &amp; category this partner has ever purchased"
            "</span></div>",
            unsafe_allow_html=True,
        )
        with st.spinner('Loading all-time purchase history...'):
            hist_df = _fetch_alltime_history(engine, party_id)

        if hist_df.empty:
            st.info('No historical purchase data found for this partner.')
        else:
            h1, h2, h3, h4 = st.columns(4)
            h1.metric('Total Products (All-Time)', str(len(hist_df)))
            h2.metric('Total Qty (All-Time)', f"{float(hist_df['total_qty'].sum()):,.0f}")
            h3.metric('Total Revenue (All-Time)', _fmt_inr(float(hist_df['total_amount'].sum())))
            h4.metric('Categories Bought', str(hist_df['category'].nunique()))

            hf1, hf2 = st.columns([1, 2])
            with hf1:
                hist_cats = ['All'] + sorted(hist_df['category'].dropna().unique().tolist())
                sel_hist_cat = st.selectbox('Filter by Category', hist_cats, key='sa_hist_cat')
            with hf2:
                hist_search = st.text_input('Search Product', '', key='sa_hist_search',
                                            placeholder='Type product name...')

            hist_show = hist_df.copy()
            if sel_hist_cat != 'All':
                hist_show = hist_show[hist_show['category'] == sel_hist_cat]
            if hist_search:
                hist_show = hist_show[
                    hist_show['product_name'].str.contains(hist_search, case=False, na=False)
                ]

            hist_display = hist_show[[
                'product_name', 'category', 'product_group',
                'total_qty', 'avg_rate', 'total_amount',
                'txn_count', 'first_purchased', 'last_purchased'
            ]].copy()
            hist_display.columns = [
                'Product', 'Category', 'Group',
                'Total Qty', 'Avg Rate (Rs)', 'Total Amount (Rs)',
                '# Invoices', 'First Purchase', 'Last Purchase'
            ]
            hist_display['Avg Rate (Rs)'] = hist_display['Avg Rate (Rs)'].apply(
                lambda x: 'Rs {:,.2f}'.format(float(x or 0)))
            hist_display['Total Amount (Rs)'] = hist_display['Total Amount (Rs)'].apply(
                lambda x: 'Rs {:,.2f}'.format(float(x or 0)))
            st.dataframe(hist_display, use_container_width=True, hide_index=True)

            csv_hist = hist_show.to_csv(index=False).encode('utf-8')
            st.download_button(
                'Download All-Time History (CSV)',
                data=csv_hist,
                file_name=sel_partner.replace(' ', '_') + '_alltime_history.csv',
                mime='text/csv',
                key='sa_download_hist_csv',
            )

    with tab2:
        st.markdown("#### Select up to 3 partners to compare")
        all_partners = sorted(geo["company_name"].dropna().unique().tolist())
        compare_sel  = st.multiselect("Pick partners", all_partners,
                                      default=[sel_partner] if sel_partner != "— Select a Partner —" else [],
                                      max_selections=3, key="sa_compare_sel")
        if len(compare_sel) < 2:
            st.info("Select at least 2 partners to compare.")
        else:
            pid_map = geo[geo["company_name"].isin(compare_sel)].set_index("company_name")["party_id"].to_dict()
            with st.spinner("Loading comparison data…"):
                cmp_kpis = fetch_multi_partner_kpis(
                    engine, list(pid_map.values()), sel_start, sel_end)

            if not cmp_kpis.empty:
                # Side-by-side KPI cards
                cols = st.columns(len(cmp_kpis))
                for ci, (_, row) in enumerate(cmp_kpis.iterrows()):
                    with cols[ci]:
                        st.markdown(f"**{row['company_name']}**")
                        st.metric("Revenue", _fmt_inr(float(row["revenue"])))
                        st.metric("Orders",  int(row["orders"]))
                        st.metric("Products", int(row["unique_products"]))

                st.markdown("---")

                # Overlaid monthly revenue chart
                all_monthly = []
                for name, pid in pid_map.items():
                    mdf = fetch_multi_monthly(engine, pid, name, sel_start, sel_end)
                    if not mdf.empty:
                        all_monthly.append(mdf)
                if all_monthly:
                    combined = pd.concat(all_monthly)
                    combined["month"] = pd.to_datetime(combined["month"])
                    fig_cmp = px.line(combined, x="month", y="revenue", color="partner",
                                      markers=True, title="Monthly Revenue Comparison",
                                      color_discrete_sequence=["#34d399","#6366f1","#f59e0b"])
                    fig_cmp.update_layout(
                        height=350, plot_bgcolor="rgba(0,0,0,0)",
                        paper_bgcolor="rgba(0,0,0,0)",
                        font=dict(color="#94a3b8"),
                        xaxis=dict(gridcolor="#1e293b"),
                        yaxis=dict(gridcolor="#1e293b", tickprefix="₹"),
                        legend=dict(orientation="h", yanchor="bottom", y=1.02),
                        margin=dict(l=10,r=10,t=40,b=10),
                    )
                    st.plotly_chart(fig_cmp, use_container_width=True)

                # Product category comparison bar
                cat_rows = []
                for name, pid in pid_map.items():
                    pdf = _fetch_product_breakdown(engine, pid, sel_start, sel_end)
                    if not pdf.empty:
                        for _, r in pdf.groupby("category")["total_amount"].sum().reset_index().iterrows():
                            cat_rows.append({"partner": name, "category": r["category"],
                                             "revenue": float(r["total_amount"])})
                if cat_rows:
                    cat_cmp = pd.DataFrame(cat_rows)
                    fig_cat = px.bar(cat_cmp, x="category", y="revenue", color="partner",
                                     barmode="group", title="Category Revenue Comparison",
                                     color_discrete_sequence=["#34d399","#6366f1","#f59e0b"])
                    fig_cat.update_layout(
                        height=350, plot_bgcolor="rgba(0,0,0,0)",
                        paper_bgcolor="rgba(0,0,0,0)",
                        font=dict(color="#94a3b8"),
                        xaxis=dict(gridcolor="#1e293b"),
                        yaxis=dict(gridcolor="#1e293b", tickprefix="₹"),
                        margin=dict(l=10,r=10,t=40,b=10),
                    )
                    st.plotly_chart(fig_cat, use_container_width=True)
