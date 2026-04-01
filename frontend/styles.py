"""
Shared UI utilities for the Consistent AI Dashboard.
Import and call apply_global_styles() at the top of each tab's render().
"""

import streamlit as st


# ── Global stylesheet ────────────────────────────────────────────────────────
GLOBAL_CSS = """
<style>
/* ── Page & sidebar ─────────────────────────────── */
[data-testid="stSidebar"] { min-width: 290px; }

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


def price_diff_color(diff_pct: float) -> str:
    """Used for competitor price diff: positive = we're more expensive (bad)."""
    if diff_pct <= -5:
        return "green"   # we're cheaper
    if diff_pct >= 5:
        return "red"     # we're more expensive / undercut
    return "grey"
