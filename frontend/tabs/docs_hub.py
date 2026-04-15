"""
Documentation Hub Tab
=====================
Renders the full module documentation directly inside the Streamlit dashboard.
Users select a module from the portal card grid and the HTML doc is displayed
inline using st.components.v1.html — no external server required.
"""
import os
import streamlit as st
import streamlit.components.v1 as components
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from styles import page_header

# ── Path resolution ────────────────────────────────────────────────────────
_DOCS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "docs")
)

# ── Module catalogue ───────────────────────────────────────────────────────
MODULES = [
    {
        "id": "partner_360",
        "file": "MODULE_01_PARTNER_360.html",
        "icon": "🤝",
        "num": "MODULE 01",
        "title": "Partner 360 View",
        "desc": "Deep-dive into any partner — revenue health, churn risk intelligence v2, credit exposure, peer gap analysis, SPIN selling scripts, and SVD-based similar partners.",
        "tags": ["Churn Risk", "SPIN Script", "Gap Analysis", "Credit Risk"],
        "accent": "#2563eb",
        "badge": "Solid",
        "badge_color": "#3b82f6",
    },
    {
        "id": "master",
        "file": "MASTER_REVIEW_AND_PRECISION_GUIDE.html",
        "icon": "🎯",
        "num": "MASTER",
        "title": "Master System Review & Precision Audit",
        "desc": "Consolidated audit across all 8 modules — what's correct, what's risky, and the 4-phase fix plan to reach enterprise-grade precision.",
        "tags": ["Audit", "Roadmap", "Best Practices"],
        "accent": "#6366f1",
        "badge": "Recommended First Read",
        "badge_color": "#6366f1",
        "featured": True,
    },
    {
        "id": "cluster",
        "file": "MODULE_02_CLUSTER_INTELLIGENCE.html",
        "icon": "🔬",
        "num": "MODULE 02",
        "title": "Cluster Intelligence",
        "desc": "HDBSCAN + GMM ensemble, purchase2vec embeddings, 2-level hierarchy, uplift modeling, MiniBatch, and drift detection.",
        "tags": ["HDBSCAN", "GMM", "UMAP", "purchase2vec", "Uplift"],
        "accent": "#6366f1",
        "badge": "V2 Live",
        "badge_color": "#22c55e",
    },
    {
        "id": "kanban",
        "file": "MODULE_03_KANBAN_PIPELINE.html",
        "icon": "📊",
        "num": "MODULE 03",
        "title": "Revenue Pipeline Tracker",
        "desc": "Kanban board translating ML scores into visual pipeline stages. Category & area filters, revenue-at-risk calculation, and card rendering.",
        "tags": ["Kanban", "Revenue at Risk", "Category Filter"],
        "accent": "#6366f1",
        "badge": "Solid",
        "badge_color": "#3b82f6",
    },
    {
        "id": "mba",
        "file": "MODULE_04_MARKET_BASKET_ANALYSIS.html",
        "icon": "🛒",
        "num": "MODULE 04",
        "title": "Market Basket Analysis",
        "desc": "Explainable cross-sell recommendations using association rules — support, confidence, and lift on monthly B2B baskets.",
        "tags": ["Apriori", "Support / Lift", "Cross-sell"],
        "accent": "#14b8a6",
        "badge": "Strong",
        "badge_color": "#3b82f6",
    },
    {
        "id": "lifecycle",
        "file": "MODULE_05_PRODUCT_LIFECYCLE.html",
        "icon": "🔄",
        "num": "MODULE 05",
        "title": "Product Lifecycle",
        "desc": "Multi-signal velocity score, Prophet + linear fallback, percentile-based stage gates, and cannibalization signal detection.",
        "tags": ["Velocity Score", "Prophet", "Stage Gate"],
        "accent": "#22c55e",
        "badge": "Strong",
        "badge_color": "#3b82f6",
    },
    {
        "id": "monitoring",
        "file": "MODULE_06_MONITORING.html",
        "icon": "📡",
        "num": "MODULE 06",
        "title": "System Monitoring",
        "desc": "Data quality alerts, degrowth backtest, cluster quality scoring, centroid drift banners, and alert history log.",
        "tags": ["Drift Detection", "Data Quality", "Alerts"],
        "accent": "#f59e0b",
        "badge": "Expanding",
        "badge_color": "#f59e0b",
    },
    {
        "id": "sales_rep",
        "file": "MODULE_07_SALES_REP_PERFORMANCE.html",
        "icon": "💼",
        "num": "MODULE 07",
        "title": "Sales Rep Performance",
        "desc": "Multi-table rep analytics — ROI, call efficiency, territory view, rep-level revenue forecasting, and portfolio health linkage.",
        "tags": ["ROI", "Territory", "Forecast"],
        "accent": "#3b82f6",
        "badge": "Needs Fixes",
        "badge_color": "#f59e0b",
    },
    {
        "id": "chatbot",
        "file": "MODULE_08_AI_CHATBOT.html",
        "icon": "🤖",
        "num": "MODULE 08",
        "title": "AI Sales Chatbot",
        "desc": "Structured BI Q&A chatbot using keyword routing + LLM (Groq). Context builder preloads relevant data slices before answering.",
        "tags": ["Groq / LLM", "BI Q&A", "Context Routing"],
        "accent": "#a78bfa",
        "badge": "Hardening",
        "badge_color": "#f59e0b",
    },
    {
        "id": "inventory",
        "file": "MODULE_09_INVENTORY_LIQUIDATION.html",
        "icon": "📦",
        "num": "MODULE 09",
        "title": "Inventory Liquidation",
        "desc": "Dead/ageing stock → targeted clearance campaigns. Cluster-based lookalike buyer matching, exposure scoring, and discount engine.",
        "tags": ["Stock Ageing", "Lookalike", "Clearance"],
        "accent": "#f97316",
        "badge": "Solid",
        "badge_color": "#3b82f6",
    },
    {
        "id": "market_intelligence",
        "file": "MODULE_10_MARKET_INTELLIGENCE.html",
        "icon": "🌐",
        "num": "MODULE 10",
        "title": "Market Intelligence",
        "desc": "Live market layer — GPT-4o news briefing from 5 RSS feeds, Google Shopping price tracking via SerpAPI, and urgency-ranked partner alerts cross-referenced with your DB.",
        "tags": ["GPT-4o", "SerpAPI", "Price Tracker", "Partner Alerts"],
        "accent": "#6366f1",
        "badge": "Live",
        "badge_color": "#22c55e",
    },
]

# ── Helpers ────────────────────────────────────────────────────────────────
def _read_doc(filename: str) -> str | None:
    path = os.path.join(_DOCS_DIR, filename)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _module_card_html(m: dict) -> str:
    """Build the HTML for a single module selection card."""
    tags_html = "".join(
        f"<span style='background:rgba(255,255,255,0.06);border:1px solid #1e2535;"
        f"color:#64748b;border-radius:20px;padding:3px 9px;font-size:10.5px;"
        f"font-weight:600;margin-right:5px;'>{t}</span>"
        for t in m["tags"]
    )
    badge_html = (
        f"<span style='background:{m['badge_color']}20;color:{m['badge_color']};"
        f"border:1px solid {m['badge_color']}40;border-radius:20px;"
        f"padding:2px 9px;font-size:10px;font-weight:700;"
        f"text-transform:uppercase;letter-spacing:0.8px;'>● {m['badge']}</span>"
    )
    return f"""
    <div style="background:#0d1117;border:1px solid #1e2535;border-radius:12px;
         padding:20px 22px;height:100%;border-top:2px solid {m['accent']};
         transition:all 0.2s ease;">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;">
        <div style="background:{m['accent']}18;border-radius:10px;width:40px;height:40px;
             display:flex;align-items:center;justify-content:center;font-size:20px;">{m['icon']}</div>
        {badge_html}
      </div>
      <div style="font-size:10px;color:#4b5563;font-family:monospace;margin-bottom:5px;">{m['num']}</div>
      <div style="font-size:15px;font-weight:700;color:#e2e8f0;margin-bottom:8px;line-height:1.3;">{m['title']}</div>
      <div style="font-size:12.5px;color:#94a3b8;line-height:1.6;margin-bottom:14px;">{m['desc']}</div>
      <div>{tags_html}</div>
    </div>
    """


# ── Main render function ───────────────────────────────────────────────────
def render(ai=None):
    page_header(
        title="Documentation Hub",
        subtitle="Full technical reference for every platform module. Select a document to view it inline.",
        icon="📚",
        accent_color="#6366f1",
    )

    # ── Session state: which doc is open ──────────────────────────────────
    if "docs_active" not in st.session_state:
        st.session_state.docs_active = None

    # ── If a document is being viewed ─────────────────────────────────────
    if st.session_state.docs_active is not None:
        _render_doc_viewer()
        return

    # ── Portal landing page ────────────────────────────────────────────────
    _render_portal()


def _render_portal():
    """Renders the module selection grid."""

    # Stats bar
    st.markdown("""
    <div style="display:flex;gap:0;border:1px solid #1e2535;border-radius:12px;
         overflow:hidden;background:#0d1117;margin-bottom:28px;max-width:600px;">
      <div style="flex:1;padding:14px 24px;border-right:1px solid #1e2535;text-align:center;">
        <div style="font-size:22px;font-weight:800;color:#6366f1;">11</div>
        <div style="font-size:11px;color:#64748b;font-weight:600;text-transform:uppercase;letter-spacing:0.8px;margin-top:2px;">Modules</div>
      </div>
      <div style="flex:1;padding:14px 24px;border-right:1px solid #1e2535;text-align:center;">
        <div style="font-size:22px;font-weight:800;color:#22c55e;">8+</div>
        <div style="font-size:11px;color:#64748b;font-weight:600;text-transform:uppercase;letter-spacing:0.8px;margin-top:2px;">ML Models</div>
      </div>
      <div style="flex:1;padding:14px 24px;text-align:center;">
        <div style="font-size:22px;font-weight:800;color:#f59e0b;">April 2026</div>
        <div style="font-size:11px;color:#64748b;font-weight:600;text-transform:uppercase;letter-spacing:0.8px;margin-top:2px;">Last Updated</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Featured: Master Review ────────────────────────────────────────────
    master = next(m for m in MODULES if m.get("featured"))
    st.markdown("""
    <div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:1.2px;
         color:#374151;margin-bottom:14px;padding-bottom:8px;border-bottom:1px solid #1e2535;">
      ⭐ Featured Document
    </div>
    """, unsafe_allow_html=True)

    col_m, col_btn = st.columns([5, 1])
    with col_m:
        st.markdown(f"""
        <div style="background:linear-gradient(135deg,rgba(99,102,241,0.1),rgba(79,70,229,0.05));
             border:1px solid rgba(99,102,241,0.3);border-radius:14px;
             padding:24px 28px;display:flex;align-items:center;gap:22px;">
          <div style="background:rgba(99,102,241,0.15);border-radius:12px;width:56px;height:56px;
               display:flex;align-items:center;justify-content:center;font-size:26px;flex-shrink:0;">
            {master['icon']}
          </div>
          <div>
            <div style="background:rgba(99,102,241,0.2);color:#a5b4fc;font-size:10px;font-weight:700;
                 text-transform:uppercase;letter-spacing:1px;padding:2px 10px;border-radius:20px;
                 display:inline-block;margin-bottom:8px;">{master['badge']}</div>
            <div style="font-size:18px;font-weight:800;color:#e2e8f0;margin-bottom:6px;">{master['title']}</div>
            <div style="font-size:13px;color:#94a3b8;line-height:1.6;">{master['desc']}</div>
          </div>
        </div>
        """, unsafe_allow_html=True)

    with col_btn:
        st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        if st.button("📖 Open", key=f"open_{master['id']}", use_container_width=True):
            st.session_state.docs_active = master["id"]
            st.rerun()

    st.markdown("<div style='height:24px'></div>", unsafe_allow_html=True)

    # ── Module grid ────────────────────────────────────────────────────────
    # ── Keyword Search ────────────────────────────────────────────────────────
    _sch1, _sch2 = st.columns([3, 2])
    with _sch1:
        _doc_search = st.text_input(
            "",
            placeholder="🔍 Search documentation by keyword, tag, or module name...",
            key="docs_search",
            label_visibility="collapsed",
        )
    with _sch2:
        _tag_options = sorted(set(t for m in MODULES for t in m["tags"]))
        _tag_filter  = st.multiselect("Filter by tag", _tag_options, key="docs_tag_filter", label_visibility="collapsed", placeholder="Filter by tag...")

    # Apply search + tag filter
    def _matches(m, q, tags):
        if q:
            _q = q.lower()
            if not any(_q in str(v).lower() for v in [m["title"], m["desc"], " ".join(m["tags"])]):
                return False
        if tags:
            if not any(t in m["tags"] for t in tags):
                return False
        return True

    _filtered = [m for m in MODULES if _matches(m, _doc_search, _tag_filter)]

    st.markdown("""
    <div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:1.2px;
         color:#374151;margin-bottom:16px;padding-bottom:8px;border-bottom:1px solid #1e2535;">
      All Module Documentation
    </div>
    """, unsafe_allow_html=True)

    non_featured = [m for m in _filtered if not m.get("featured")]
    if not non_featured:
        _qterm = _doc_search or (', '.join(_tag_filter) if _tag_filter else '')
        st.info(f"No documentation matched **'{_qterm}'**. Try a different keyword or clear the filter.")
        return
    # Render in rows of 3
    for row_start in range(0, len(non_featured), 3):
        row = non_featured[row_start: row_start + 3]
        cols = st.columns(3)
        for i, m in enumerate(row):
            with cols[i]:
                st.markdown(_module_card_html(m), unsafe_allow_html=True)
                st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
                if st.button(f"📖 View Document", key=f"open_{m['id']}", use_container_width=True):
                    st.session_state.docs_active = m["id"]
                    st.rerun()


def _render_doc_viewer():
    """Renders the currently active document inline."""
    active_id = st.session_state.docs_active
    module = next((m for m in MODULES if m["id"] == active_id), None)

    if module is None:
        st.error("Document not found.")
        if st.button("← Back to Documentation Hub"):
            st.session_state.docs_active = None
            st.rerun()
        return

    # ── Top navigation bar ─────────────────────────────────────────────────
    nav_col, meta_col = st.columns([3, 2])
    with nav_col:
        if st.button("← Back to Documentation Hub", key="docs_back"):
            st.session_state.docs_active = None
            st.rerun()
    with meta_col:
        # Quick-jump to another document
        other_titles = {m["id"]: f"{m['icon']} {m['title']}" for m in MODULES}
        jump_choice = st.selectbox(
            "Jump to another module →",
            options=list(other_titles.keys()),
            format_func=lambda x: other_titles[x],
            index=list(other_titles.keys()).index(active_id),
            key="docs_jump",
            label_visibility="collapsed",
        )
        if jump_choice != active_id:
            st.session_state.docs_active = jump_choice
            st.rerun()

    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

    # ── Info strip ─────────────────────────────────────────────────────────
    st.markdown(
        f"<div style='background:#0d1117;border:1px solid #1e2535;border-left:3px solid {module['accent']};"
        f"border-radius:8px;padding:10px 16px;margin-bottom:16px;display:flex;align-items:center;gap:12px;'>"
        f"<span style='font-size:20px;'>{module['icon']}</span>"
        f"<div>"
        f"<div style='font-size:13px;font-weight:700;color:#e2e8f0;'>{module['num']} — {module['title']}</div>"
        f"<div style='font-size:11px;color:#64748b;'>{module['file']}</div>"
        f"</div></div>",
        unsafe_allow_html=True,
    )

    # ── Read & render the HTML file ────────────────────────────────────────
    html_content = _read_doc(module["file"])

    if html_content is None:
        st.error(
            f"Documentation file not found: `{module['file']}`\n\n"
            f"Expected location: `{os.path.join(_DOCS_DIR, module['file'])}`"
        )
        return

    # Inject a small reset to make the doc render nicely inside the iframe
    # (remove fixed heights, ensure scrolling works)
    iframe_wrap = f"""
    <style>
      html, body {{ margin: 0; padding: 0; background: #f9fafb; }}
    </style>
    {html_content}
    """

    components.html(iframe_wrap, height=900, scrolling=True)
