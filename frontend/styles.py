"""
Shared UI utilities for the Consistent AI Dashboard.
Import and call apply_global_styles() at the top of each tab's render().
"""

import streamlit as st


# ── Global stylesheet ────────────────────────────────────────────────────────
GLOBAL_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

/* ── Typography ─────────────────────────────────────────────────────────── */
html, body, [class*="css"], .stMarkdown, .stText, .stCaption,
[data-testid="stSidebar"], [data-testid="stMainBlockContainer"] {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
}

/* ── Page & sidebar ─────────────────────────────── */
[data-testid="stSidebar"] { min-width: 290px; }

/* ══════════════════════════════════════════════════
   MICRO-ANIMATIONS
   ══════════════════════════════════════════════════ */

/* ── Page fade-in on load ────────────────────────── */
@keyframes fadeInUp {
  from { opacity: 0; transform: translateY(14px); }
  to   { opacity: 1; transform: translateY(0); }
}
.block-container,
[data-testid="stMainBlockContainer"],
section.main .block-container {
  animation: fadeInUp 0.38s cubic-bezier(0.22,1,0.36,1) both;
}

/* ── Metric card hover glow + lift ───────────────── */
[data-testid="stMetric"] {
  border-radius: 10px !important;
  padding: 14px 16px !important;
  background: #0f1117 !important;
  border: 1px solid #1e2433 !important;
  transition: box-shadow 0.22s ease, transform 0.22s ease, border-color 0.22s ease !important;
}
[data-testid="stMetric"]:hover {
  box-shadow: 0 0 0 1px rgba(99,102,241,0.35), 0 6px 24px rgba(99,102,241,0.15) !important;
  border-color: rgba(99,102,241,0.4) !important;
  transform: translateY(-2px) !important;
}
[data-testid="stMetricLabel"] > div {
  font-size: 11px !important;
  font-weight: 600 !important;
  text-transform: uppercase !important;
  letter-spacing: 0.07em !important;
  color: #64748b !important;
}
[data-testid="stMetricValue"] > div {
  font-size: 26px !important;
  font-weight: 700 !important;
  color: #f0f4ff !important;
}

/* ── Badge pulse ─────────────────────────────────── */
@keyframes badgePulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(239,68,68,0.45); }
  60%       { box-shadow: 0 0 0 5px rgba(239,68,68,0); }
}
@keyframes badgePulseAmber {
  0%, 100% { box-shadow: 0 0 0 0 rgba(245,158,11,0.4); }
  60%       { box-shadow: 0 0 0 5px rgba(245,158,11,0); }
}
.badge-red   { animation: badgePulse 2.2s ease-in-out infinite; }
.badge-amber { animation: badgePulseAmber 2.8s ease-in-out infinite; }

/* ── Animated gradient on page-hero accent bar ───── */
@keyframes gradientShift {
  0%   { background-position: 0% 50%; }
  50%  { background-position: 100% 50%; }
  100% { background-position: 0% 50%; }
}
.page-hero::before {
  background: linear-gradient(90deg,#2563eb,#7c3aed,#06b6d4,#2563eb) !important;
  background-size: 300% 100% !important;
  animation: gradientShift 5s ease infinite !important;
}

/* ── Page hero hover ─────────────────────────────── */
.page-hero {
  transition: box-shadow 0.25s ease, border-color 0.25s ease !important;
}
.page-hero:hover {
  box-shadow: 0 4px 32px rgba(37,99,235,0.12) !important;
  border-color: rgba(37,99,235,0.25) !important;
}

/* ── Section card hover ──────────────────────────── */
.ui-section {
  transition: border-color 0.2s ease, box-shadow 0.2s ease !important;
}
.ui-section:hover {
  border-color: #2a2a3a !important;
  box-shadow: 0 2px 16px rgba(0,0,0,0.3) !important;
}

/* ── Tab styling ─────────────────────────────────── */
[data-testid="stTabs"] [data-baseweb="tab-list"] {
  gap: 4px !important;
  border-bottom: 1px solid #1e2433 !important;
  padding-bottom: 0 !important;
}
[data-testid="stTabs"] [data-baseweb="tab"] {
  border-radius: 6px 6px 0 0 !important;
  padding: 8px 18px !important;
  font-size: 13px !important;
  font-weight: 600 !important;
  color: #64748b !important;
  transition: color 0.18s ease, background 0.18s ease !important;
  background: transparent !important;
  border: none !important;
}
[data-testid="stTabs"] [data-baseweb="tab"]:hover {
  color: #e2e8f0 !important;
  background: rgba(99,102,241,0.08) !important;
}
[data-testid="stTabs"] [aria-selected="true"] {
  color: #818cf8 !important;
  background: rgba(99,102,241,0.12) !important;
  border-bottom: 2px solid #6366f1 !important;
}
[data-testid="stTabs"] [data-baseweb="tab-highlight"] {
  display: none !important;
}

/* ── Expander hover ──────────────────────────────── */
[data-testid="stExpander"] {
  border: 1px solid #1e2433 !important;
  border-radius: 8px !important;
  transition: border-color 0.2s ease !important;
}
[data-testid="stExpander"]:hover {
  border-color: #2a3450 !important;
}

/* ── Button micro-interactions ───────────────────── */
[data-testid="stButton"] > button {
  transition: all 0.18s ease !important;
}
[data-testid="stButton"] > button:hover {
  transform: translateY(-1px) !important;
  box-shadow: 0 4px 14px rgba(37,99,235,0.22) !important;
}
[data-testid="stButton"] > button:active {
  transform: translateY(0) scale(0.98) !important;
}
[data-testid="stDownloadButton"] > button {
  transition: all 0.18s ease !important;
}
[data-testid="stDownloadButton"] > button:hover {
  transform: translateY(-1px) !important;
  box-shadow: 0 4px 12px rgba(16,185,129,0.2) !important;
}

/* ── Dataframe animation ─────────────────────────── */
[data-testid="stDataFrame"] {
  animation: fadeInUp 0.4s ease-out both !important;
  border: 1px solid #1e2433 !important;
  border-radius: 8px !important;
  overflow: hidden !important;
}

/* ══════════════════════════════════════════════════
   GLOBAL SEARCH BAR
   ══════════════════════════════════════════════════ */
#_gsearch_trigger {
  position: fixed;
  top: 10px;
  right: 90px;
  z-index: 2147483641;
  background: rgba(18,20,28,0.92);
  border: 1px solid #2a3450;
  border-radius: 8px;
  padding: 5px 13px;
  font-size: 12px;
  color: #64748b;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 6px;
  backdrop-filter: blur(10px);
  transition: all 0.18s ease;
  user-select: none;
}
#_gsearch_trigger:hover {
  border-color: #6366f1;
  color: #a5b4fc;
  background: rgba(99,102,241,0.1);
}
#_gsearch_overlay {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.6);
  z-index: 2147483638;
  display: none;
  backdrop-filter: blur(2px);
}
#_gsearch_overlay.open { display: block; }
#_gsearch_modal {
  position: fixed;
  top: 80px;
  left: 50%;
  transform: translateX(-50%) translateY(-10px);
  width: 600px;
  max-width: 90vw;
  background: #12141c;
  border: 1px solid #2a3450;
  border-radius: 14px;
  box-shadow: 0 24px 64px rgba(0,0,0,0.8);
  z-index: 2147483639;
  display: none;
  flex-direction: column;
  overflow: hidden;
  transition: transform 0.22s cubic-bezier(0.34,1.56,0.64,1), opacity 0.18s ease;
  opacity: 0;
}
#_gsearch_modal.open {
  display: flex;
  transform: translateX(-50%) translateY(0);
  opacity: 1;
}
#_gsearch_header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 16px;
  border-bottom: 1px solid #1e2433;
}
#_gsearch_icon { font-size: 16px; color: #6366f1; flex-shrink: 0; }
#_gsearch_input {
  flex: 1;
  background: transparent;
  border: none;
  outline: none;
  font-size: 15px;
  color: #e2e8f0;
  font-family: inherit;
}
#_gsearch_input::placeholder { color: #475569; }
#_gsearch_kbd {
  font-size: 11px;
  color: #475569;
  background: #1e2433;
  border: 1px solid #2a3450;
  border-radius: 4px;
  padding: 2px 6px;
  flex-shrink: 0;
}
#_gsearch_results {
  max-height: 340px;
  overflow-y: auto;
  padding: 8px 0;
}
#_gsearch_empty {
  padding: 20px 16px;
  text-align: center;
  color: #475569;
  font-size: 13px;
  display: none;
}
.gsr-group-label {
  padding: 6px 16px 4px;
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: #374151;
}
.gsr-item {
  padding: 8px 16px;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13px;
  color: #e2e8f0;
  transition: background 0.12s ease;
}
.gsr-item:hover { background: rgba(99,102,241,0.12); }
.gsr-item-icon { font-size: 15px; flex-shrink: 0; width: 22px; text-align: center; }
.gsr-item-label { flex: 1; font-weight: 500; }
.gsr-item-meta { font-size: 11px; color: #64748b; }
.gsr-item-state { font-size: 10px; background: #1e2433; color: #94a3b8; padding: 1px 6px; border-radius: 4px; }

/* ══════════════════════════════════════════════════
   ORIGINAL STYLES (preserved)
   ══════════════════════════════════════════════════ */

/* ── Section card ───────────────────────────────── */
.ui-section {
    border: 1px solid #2a2a2a;
    border-radius: 8px;
    padding: 16px 20px 10px 20px;
    margin-bottom: 18px;
    background: #111111;
}
.ui-section-title {
    font-size: 13px;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: #888;
    margin-bottom: 12px;
}

/* ── Status badges ───────────────────────────────── */
.badge {
    display: inline-block;
    padding: 3px 10px;
    border-radius: 12px;
    font-size: 13px;
    font-weight: 600;
    letter-spacing: 0.03em;
}
.badge-green  { background: #0d2b1a; color: #34d96f; border: 1px solid #1a5c35; }
.badge-amber  { background: #2b2200; color: #f5c842; border: 1px solid #5a4700; }
.badge-red    { background: #2b0a0a; color: #f55c5c; border: 1px solid #5c1a1a; }
.badge-blue   { background: #0a1a2b; color: #5cbcf5; border: 1px solid #1a3d5c; }
.badge-grey   { background: #1e1e1e; color: #aaa;    border: 1px solid #333; }

/* ── Page header ─────────────────────────────────── */
.page-header-cap {
    color: #888;
    font-size: 14px;
    margin-top: -10px;
    margin-bottom: 18px;
}

/* ── Divider label ───────────────────────────────── */
.divider-label {
    display: flex;
    align-items: center;
    gap: 10px;
    margin: 22px 0 14px 0;
    color: #666;
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.07em;
    text-transform: uppercase;
}

/* ── Info banner ─────────────────────────────────── */
.info-banner {
    padding: 10px 16px;
    border-radius: 6px;
    margin-bottom: 14px;
    font-size: 14px;
    font-weight: 500;
}
.info-banner-green { background: #0d2b1a; border-left: 4px solid #34d96f; color: #d4f5e0; }
.info-banner-amber { background: #2b2200; border-left: 4px solid #f5c842; color: #f5e8a0; }
.info-banner-red   { background: #2b0a0a; border-left: 4px solid #f55c5c; color: #f5c0c0; }
.info-banner-blue  { background: #0a1a2b; border-left: 4px solid #5cbcf5; color: #b8ddf7; }

/* ── Chat bubbles (sidebar) ──────────────────────── */
.chat-message-user {
    background: #1e3a5f;
    color: #e8f4fd;
    padding: 10px 14px;
    border-radius: 12px 12px 2px 12px;
    margin: 6px 0;
    font-size: 13px;
}
.chat-message-ai {
    background: #1a2a1a;
    color: #d4f0d4;
    padding: 10px 14px;
    border-radius: 12px 12px 12px 2px;
    margin: 6px 0;
    border-left: 3px solid #2ecc71;
    font-size: 13px;
}

/* ── Compact dataframe ───────────────────────────── */
[data-testid="stDataFrame"] { border-radius: 6px; overflow: hidden; }

/* ── Skeleton shimmer ────────────────────────────── */
@keyframes shimmer {
  0%   { background-position: -800px 0; }
  100% { background-position:  800px 0; }
}
.skeleton {
  display: inline-block;
  width: 100%;
  border-radius: 6px;
  background: linear-gradient(90deg, #1a1a1a 25%, #252525 50%, #1a1a1a 75%);
  background-size: 800px 100%;
  animation: shimmer 1.4s infinite linear;
}
.sk-row { display:flex; gap:12px; margin-bottom:14px; }
.sk-card {
  border-radius: 10px;
  background: #111;
  border: 1px solid #222;
  padding: 18px 16px;
  flex: 1;
}

/* ── Page hero header ─────────────────────────────── */
.page-hero {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 18px 22px;
  margin-bottom: 22px;
  border-radius: 12px;
  border: 1px solid #222;
  background: linear-gradient(135deg, #111 0%, #161616 100%);
  position: relative;
  overflow: hidden;
}
.page-hero::before {
  content: "";
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 3px;
  background: var(--hero-accent, #2563eb);
  border-radius: 12px 12px 0 0;
}
.page-hero-icon {
  font-size: 36px;
  line-height: 1;
  flex-shrink: 0;
}
.page-hero-text { flex: 1; }
.page-hero-title {
  font-size: 22px;
  font-weight: 700;
  color: #f0f0f0;
  margin: 0 0 4px 0;
  letter-spacing: -0.01em;
}
.page-hero-sub {
  font-size: 13px;
  color: #777;
  margin: 0;
  line-height: 1.4;
}
.page-hero-badge {
  font-size: 11px;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: 20px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  flex-shrink: 0;
}
</style>
"""


def apply_global_styles():
    """Inject the global stylesheet. Call once at the top of every tab's render()."""
    st.markdown(GLOBAL_CSS, unsafe_allow_html=True)


# ── Helper: section header (uppercase label + thin line) ─────────────────────
def section_header(label: str):
    st.markdown(
        f'<div class="divider-label">{label}</div>',
        unsafe_allow_html=True,
    )


# ── Helper: status badge ──────────────────────────────────────────────────────
def status_badge(label: str, color: str = "grey") -> str:
    """Return an HTML badge string. color: green | amber | red | blue | grey"""
    return f'<span class="badge badge-{color}">{label}</span>'


# ── Helper: banner (info block with left border) ──────────────────────────────
def banner(message: str, color: str = "blue"):
    """Render a colored info banner. color: green | amber | red | blue"""
    st.markdown(
        f'<div class="info-banner info-banner-{color}">{message}</div>',
        unsafe_allow_html=True,
    )


# ── Helper: page description caption ─────────────────────────────────────────
def page_caption(text: str):
    st.markdown(f'<p class="page-header-cap">{text}</p>', unsafe_allow_html=True)


# ── Helper: skeleton loader ───────────────────────────────────────────────────
def skeleton_loader(n_metric_cards: int = 4, n_rows: int = 2, label: str = "Loading data..."):
    """
    Render a shimmer skeleton screen.
    Shows metric card placeholders + row placeholders during data loading.
    """
    st.markdown(
        f'<p style="color:#555;font-size:13px;margin-bottom:12px">⏳ {label}</p>',
        unsafe_allow_html=True,
    )
    # Metric cards row
    card_html = ""
    for _ in range(n_metric_cards):
        card_html += """
        <div class="sk-card">
          <div class="skeleton" style="height:11px;width:50%;margin-bottom:10px"></div>
          <div class="skeleton" style="height:28px;width:70%;margin-bottom:6px"></div>
          <div class="skeleton" style="height:10px;width:40%"></div>
        </div>"""
    st.markdown(f'<div class="sk-row">{card_html}</div>', unsafe_allow_html=True)
    # Content rows
    for w in (["100%", "85%", "90%", "75%", "95%"])[:n_rows]:
        st.markdown(
            f'<div class="skeleton" style="height:14px;width:{w};margin-bottom:10px"></div>',
            unsafe_allow_html=True,
        )


# ── Helper: unified hero page header ─────────────────────────────────────────
def page_header(
    title: str,
    subtitle: str = "",
    icon: str = "📊",
    accent_color: str = "#2563eb",
    badge_text: str = "",
    badge_color: str = "#1e3a5f",
):
    """
    Render a premium hero header with icon, title, subtitle and optional badge.
    Replaces bare st.title() + page_caption() calls for a consistent look.
    """
    badge_html = (
        f'<span class="page-hero-badge" '
        f'style="background:{badge_color};color:#7eb8f0;border:1px solid #1e3a5f">'
        f'{badge_text}</span>'
        if badge_text else ""
    )
    st.markdown(
        f"""
        <div class="page-hero" style="--hero-accent:{accent_color}">
          <div class="page-hero-icon">{icon}</div>
          <div class="page-hero-text">
            <p class="page-hero-title">{title}</p>
            <p class="page-hero-sub">{subtitle}</p>
          </div>
          {badge_html}
        </div>""",
        unsafe_allow_html=True,
    )


# ── Color helpers used in tables ──────────────────────────────────────────────
def health_color(status: str) -> str:
    s = str(status).lower()
    if "healthy" in s or "green" in s or "low" in s:
        return "green"
    if "watch" in s or "medium" in s or "amber" in s:
        return "amber"
    return "red"


def churn_color(prob: float) -> str:
    if prob < 0.35:
        return "green"
    if prob < 0.65:
        return "amber"
    return "red"


