"""
Market Intelligence Tab
-----------------------
4 sub-tabs:
  1. 📰 News Briefing  — RSS + GPT-4o; cached 4 hours        (#6 category filter, #11 archive, #15 article links)
  2. 📊 Price Tracker  — SerpAPI Google Shopping + SQLite     (#9 compare categories, #12 loading feedback, #17 competitor tracker)
  3. ⚡ Partner Alerts  — price signals × your partner DB     (#14 pagination, all 5 bug fixes)
  4. 🗺️ Heat Map        — Partner × Category spend matrix     (#20)
"""

import os
import json
import sqlite3
import datetime
import time
import sys

import numpy as np
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from styles import apply_global_styles, page_header, section_header, banner

# ── Constants ────────────────────────────────────────────────────────────────
_DB_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "market_prices.db")
)
_NEWS_CACHE_SECONDS = 4 * 3600
_PRICE_CACHE_HOURS  = 6

_RSS_FEEDS = [
    ("Tom's Hardware",  "https://www.tomshardware.com/feeds/all"),
    ("The Register",    "https://www.theregister.com/headlines.atom"),
    ("Ars Technica",    "https://feeds.arstechnica.com/arstechnica/technology-lab"),
    ("Economic Times",  "https://economictimes.indiatimes.com/tech/rssfeeds/13357270.cms"),
    ("SlashDot",        "https://rss.slashdot.org/Slashdot/slashDot"),
]


# ═════════════════════════════════════════════════════════════════════════════
# SQLite helpers
# ═════════════════════════════════════════════════════════════════════════════
def _init_db():
    conn = sqlite3.connect(_DB_PATH)
    # Price history (existing)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS price_history (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            product_query    TEXT NOT NULL,
            product_category TEXT NOT NULL,
            search_date      TEXT NOT NULL,
            avg_price        REAL,
            min_price        REAL,
            max_price        REAL,
            results_json     TEXT,
            gpt_summary      TEXT,
            created_at       TEXT DEFAULT (datetime('now'))
        )
    """)
    # #11 – News briefing archive
    conn.execute("""
        CREATE TABLE IF NOT EXISTS news_briefing_archive (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at    TEXT NOT NULL,
            mood          TEXT,
            mood_reason   TEXT,
            briefing_json TEXT NOT NULL
        )
    """)
    # #17 – Competitor watch list
    conn.execute("""
        CREATE TABLE IF NOT EXISTS competitor_watch (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            product_query    TEXT NOT NULL,
            product_category TEXT NOT NULL,
            added_at         TEXT DEFAULT (datetime('now')),
            UNIQUE(product_query, product_category)
        )
    """)
    conn.commit()
    conn.close()


def _save_price_result(query, category, avg_p, min_p, max_p, results_json, gpt_summary):
    conn = sqlite3.connect(_DB_PATH)
    conn.execute(
        """INSERT INTO price_history
           (product_query, product_category, search_date, avg_price,
            min_price, max_price, results_json, gpt_summary)
           VALUES (?,?,?,?,?,?,?,?)""",
        (query, category, datetime.date.today().isoformat(),
         avg_p, min_p, max_p, results_json, gpt_summary),
    )
    conn.commit()
    conn.close()


def _get_cached_result(query, hours=_PRICE_CACHE_HOURS):
    conn = sqlite3.connect(_DB_PATH)
    cutoff = (datetime.datetime.utcnow() - datetime.timedelta(hours=hours)).isoformat()
    row = conn.execute(
        """SELECT avg_price, min_price, max_price, results_json, gpt_summary, created_at
           FROM price_history
           WHERE LOWER(product_query)=LOWER(?)
             AND created_at >= ?
           ORDER BY created_at DESC LIMIT 1""",
        (query, cutoff),
    ).fetchone()
    conn.close()
    return row


def _get_price_history(query, days=30):
    conn = sqlite3.connect(_DB_PATH)
    cutoff = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    rows = conn.execute(
        """SELECT search_date, avg_price, min_price, max_price
           FROM price_history
           WHERE LOWER(product_query)=LOWER(?)
             AND search_date >= ?
           ORDER BY search_date ASC""",
        (query, cutoff),
    ).fetchall()
    conn.close()
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows, columns=["Date", "Avg Price", "Min Price", "Max Price"])


def _get_all_searches(days=30):
    conn = sqlite3.connect(_DB_PATH)
    cutoff = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    rows = conn.execute(
        """SELECT product_query, product_category, search_date, avg_price
           FROM price_history
           WHERE search_date >= ?
           ORDER BY created_at DESC""",
        (cutoff,),
    ).fetchall()
    conn.close()
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows, columns=["Query", "Category", "Date", "Avg Price (₹)"])


# ── #11: Briefing archive ─────────────────────────────────────────────────────
def _save_briefing(briefing: dict):
    try:
        conn = sqlite3.connect(_DB_PATH)
        conn.execute(
            """INSERT INTO news_briefing_archive (created_at, mood, mood_reason, briefing_json)
               VALUES (?, ?, ?, ?)""",
            (
                datetime.datetime.utcnow().isoformat(),
                briefing.get("overall_market_mood", ""),
                briefing.get("mood_reason", ""),
                json.dumps(briefing),
            ),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass  # never crash on archive failure


def _get_past_briefings(days=14):
    try:
        conn = sqlite3.connect(_DB_PATH)
        cutoff = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
        rows = conn.execute(
            """SELECT id, created_at, mood, mood_reason, briefing_json
               FROM news_briefing_archive
               WHERE created_at >= ?
               ORDER BY created_at DESC
               LIMIT 20""",
            (cutoff,),
        ).fetchall()
        conn.close()
        return rows
    except Exception:
        return []


def _get_briefing_by_id(bid: int) -> dict:
    try:
        conn = sqlite3.connect(_DB_PATH)
        row = conn.execute(
            "SELECT briefing_json FROM news_briefing_archive WHERE id=?", (bid,)
        ).fetchone()
        conn.close()
        return json.loads(row[0]) if row else {}
    except Exception:
        return {}


# ── #17: Competitor watch helpers ─────────────────────────────────────────────
def _get_competitor_watches():
    try:
        conn = sqlite3.connect(_DB_PATH)
        rows = conn.execute(
            "SELECT id, product_query, product_category, added_at FROM competitor_watch ORDER BY added_at DESC"
        ).fetchall()
        conn.close()
        return rows
    except Exception:
        return []


def _add_competitor_watch(query: str, category: str) -> bool:
    try:
        conn = sqlite3.connect(_DB_PATH)
        conn.execute(
            "INSERT OR IGNORE INTO competitor_watch (product_query, product_category) VALUES (?, ?)",
            (query, category),
        )
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


def _remove_competitor_watch(watch_id: int):
    try:
        conn = sqlite3.connect(_DB_PATH)
        conn.execute("DELETE FROM competitor_watch WHERE id=?", (watch_id,))
        conn.commit()
        conn.close()
    except Exception:
        pass


# ═════════════════════════════════════════════════════════════════════════════
# GPT-4o helper
# ═════════════════════════════════════════════════════════════════════════════
def _gpt(system: str, user: str, model: str = "gpt-4o", max_tokens: int = 1000) -> str:
    try:
        from openai import OpenAI
        client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            max_tokens=max_tokens,
            temperature=0.3,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        return f"[GPT error: {e}]"


# ═════════════════════════════════════════════════════════════════════════════
# SerpAPI price fetch
# ═════════════════════════════════════════════════════════════════════════════
def _fetch_prices(query: str, serpapi_key: str) -> tuple:
    """Returns (items: list, error: str | None)."""
    try:
        from serpapi import GoogleSearch
    except ImportError:
        return [], "❌ `google-search-results` package is not installed on this server. Run: `pip install google-search-results`"

    try:
        params = {
            "engine":  "google_shopping",
            "q":        query,
            "api_key":  serpapi_key,
            "gl":       "in",
            "hl":       "en",
            "num":      10,
        }
        results = GoogleSearch(params).get_dict()

        # SerpAPI returns an 'error' key when the key is invalid / quota exceeded
        if "error" in results:
            return [], f"❌ SerpAPI error: {results['error']}"

        items = []
        for r in results.get("shopping_results", [])[:15]:
            price_str = str(r.get("price", "0")).replace("₹", "").replace(",", "").strip()
            try:
                price_val = float(price_str.split()[0])
            except Exception:
                price_val = 0.0
            if price_val <= 0:
                continue
            items.append({
                "title":  r.get("title", ""),
                "price":  price_val,
                "source": r.get("source", ""),
                "link":   r.get("link", ""),
                "rating": r.get("rating", ""),
            })
        if not items:
            return [], f"⚠️ SerpAPI returned 0 shopping results for '{query}'. Try a broader query."
        return items, None
    except Exception as exc:
        return [], f"❌ Exception during SerpAPI call: {type(exc).__name__}: {exc}"


# ═════════════════════════════════════════════════════════════════════════════
# RSS + GPT news briefing
# ═════════════════════════════════════════════════════════════════════════════
def _fetch_rss_headlines(max_per_feed: int = 5) -> list:
    try:
        import feedparser
    except ImportError:
        return []
    headlines = []
    for source_name, url in _RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:max_per_feed]:
                headlines.append({
                    "source":  source_name,
                    "title":   entry.get("title", ""),
                    "summary": entry.get("summary", "")[:300],
                    "link":    entry.get("link", ""),
                })
        except Exception:
            continue
    return headlines


def _build_news_briefing(headlines: list, categories: list) -> dict:
    cats_str = ", ".join(categories[:20]) if categories else "IT hardware products"
    headlines_txt = "\n".join(
        [f"- [{h['source']}] {h['title']}" for h in headlines[:25]]
    )
    system = (
        "You are a senior B2B sales intelligence analyst for an Indian IT hardware distributor. "
        "Analyse tech supply-chain news and translate it into actionable briefings for the sales team."
    )
    user = f"""Our product categories: {cats_str}

Today's headlines:
{headlines_txt}

Produce a JSON object with this exact structure:
{{
  "top_stories": [
    {{
      "headline": "short version of story",
      "source": "source name exactly as given",
      "impact_category": "one of our categories or 'General'",
      "impact_level": "High | Medium | Low",
      "impact_summary": "1-2 sentences on how this affects our business",
      "recommended_action": "specific action for our sales team"
    }}
  ],
  "overall_market_mood": "Bullish | Bearish | Neutral",
  "mood_reason": "one line explanation",
  "supply_chain_alert": "any supply shortage or price pressure alert, or null"
}}
Include only the 5 most impactful stories. Output ONLY valid JSON, no markdown fences.
"""
    raw = _gpt(system, user, max_tokens=1500)
    try:
        return json.loads(raw)
    except Exception:
        try:
            start = raw.index("{")
            end   = raw.rindex("}") + 1
            return json.loads(raw[start:end])
        except Exception:
            return {"error": raw}


# ── #15: Match GPT stories back to original RSS links ────────────────────────
def _attach_links_to_stories(stories: list, headlines: list) -> list:
    """Best-effort: match top_stories back to original RSS entries to attach article URLs."""
    hl_by_source: dict = {}
    for h in headlines:
        hl_by_source.setdefault(h.get("source", ""), []).append(h)

    for story in stories:
        story["link"] = ""
        src  = story.get("source", "")
        head = story.get("headline", "")
        candidates = hl_by_source.get(src, [])
        head_words = {w.lower() for w in head.split() if len(w) > 4}
        best_score, best_link = 0, ""
        for h in candidates:
            hl_words = {w.lower() for w in h["title"].split() if len(w) > 4}
            score = len(head_words & hl_words)
            if score > best_score:
                best_score = score
                best_link  = h.get("link", "")
        if best_score >= 1:
            story["link"] = best_link
    return stories


# ═════════════════════════════════════════════════════════════════════════════
# MAIN RENDER
# ═════════════════════════════════════════════════════════════════════════════
def render(ai):
    apply_global_styles()
    _init_db()

    page_header(
        title="Market Intelligence",
        subtitle="Live price tracking, news impact analysis, and partner alerts — all in one place.",
        icon="🌐",
        accent_color="#6366f1",
    )

    # ── Config ───────────────────────────────────────────────────────────────
    openai_key  = os.environ.get("OPENAI_API_KEY", "")
    serpapi_key = os.environ.get("SERPAPI_KEY", "").strip()
    has_openai  = bool(openai_key and not openai_key.endswith("="))
    has_serpapi = bool(serpapi_key)

    # ── Product categories ───────────────────────────────────────────────────
    categories: list = []
    try:
        ai.ensure_product_lifecycle()
        vel = getattr(ai, "df_product_velocity", None)
        if vel is not None and not vel.empty and "product_name" in vel.columns:
            categories = sorted(vel["product_name"].dropna().unique().tolist())
    except Exception:
        pass
    if not categories:
        categories = ["IT Hardware", "Networking", "Storage", "RAM", "Printers", "UPS"]

    # ── Status bar ───────────────────────────────────────────────────────────
    k1, k2, k3 = st.columns(3)
    def _status_card(icon, label, detail):
        return (
            f"<div style='background:#161b2a;border-radius:8px;padding:10px 14px;"
            f"border:1px solid #1e2433;display:flex;align-items:center;gap:8px;'>"
            f"<span style='font-size:18px;'>{icon}</span>"
            f"<div><div style='font-size:12px;font-weight:700;color:#e2e8f0;'>{label}</div>"
            f"<div style='font-size:11px;color:#64748b;'>{detail}</div></div></div>"
        )
    with k1:
        st.markdown(_status_card("✅" if has_openai else "❌", "OpenAI GPT-4o",
                                 "Connected" if has_openai else "Key missing in .env"),
                    unsafe_allow_html=True)
    with k2:
        st.markdown(_status_card("✅" if has_serpapi else "⚠️", "SerpAPI",
                                 "Connected" if has_serpapi else "Add SERPAPI_KEY to .env"),
                    unsafe_allow_html=True)
    with k3:
        st.markdown(_status_card("📦", "Product Categories",
                                 f"{len(categories)} categories loaded from DB"),
                    unsafe_allow_html=True)

    st.markdown("<div style='margin-top:20px;'></div>", unsafe_allow_html=True)

    # ── Tabs ─────────────────────────────────────────────────────────────────
    tab_news, tab_price, tab_alerts, tab_heatmap = st.tabs([
        "📰  News Briefing",
        "📊  Price Tracker",
        "⚡  Partner Alerts",
        "🗺️  Heat Map",
    ])

    # ═════════════════════════════════════════════════════════════════════════
    # TAB 1 — News Briefing
    # ═════════════════════════════════════════════════════════════════════════
    with tab_news:
        st.markdown(
            "<div style='font-size:13px;color:#64748b;margin-bottom:16px;'>"
            "Headlines from 5 tech/supply-chain feeds, analysed by GPT-4o against your product categories. "
            "Refreshes every 4 hours — no API cost on repeat views.</div>",
            unsafe_allow_html=True,
        )

        _now      = time.time()
        _cache    = st.session_state.get("_news_cache")
        _cache_ts = st.session_state.get("_news_cache_ts", 0)
        _cache_valid = bool(_cache and (_now - _cache_ts) < _NEWS_CACHE_SECONDS)

        col_btn, col_info = st.columns([1, 4])
        with col_btn:
            force_refresh = st.button("🔄 Refresh Briefing", key="news_refresh")
        with col_info:
            if _cache_valid:
                age_min = int((_now - _cache_ts) / 60)
                st.caption(f"Cached briefing · {age_min} min ago")

        if force_refresh or not _cache_valid:
            if not has_openai:
                st.error("OpenAI key is required for News Briefing. Add `OPENAI_API_KEY` to `.env`.")
            else:
                with st.spinner("Fetching headlines from 5 RSS sources…"):
                    headlines = _fetch_rss_headlines()
                with st.spinner(
                    f"GPT-4o analysing {len(headlines)} headlines against "
                    f"{len(categories)} product categories…"
                ):
                    briefing = _build_news_briefing(headlines, categories)

                # #15: Attach article links
                if "top_stories" in briefing:
                    briefing["top_stories"] = _attach_links_to_stories(
                        briefing["top_stories"], headlines
                    )

                st.session_state["_news_cache"]     = briefing
                st.session_state["_news_cache_ts"]  = time.time()
                st.session_state["_news_headlines"] = headlines

                # #11: Save to archive
                if "error" not in briefing:
                    _save_briefing(briefing)

                _cache       = briefing
                _cache_valid = True

        if _cache_valid and _cache and "error" not in _cache:
            briefing = _cache

            # ── Market mood banner ────────────────────────────────────────
            mood         = briefing.get("overall_market_mood", "Neutral")
            mood_color   = {"Bullish": "#22c55e", "Bearish": "#ef4444"}.get(mood, "#f59e0b")
            mood_reason  = briefing.get("mood_reason", "")
            supply_alert = briefing.get("supply_chain_alert")

            supply_html = (
                f"<div style='background:#ef444418;border:1px solid #ef444444;"
                f"border-left:4px solid #ef4444;border-radius:10px;padding:12px 16px;flex:2;'>"
                f"<div style='font-size:11px;color:#ef4444;font-weight:700;"
                f"text-transform:uppercase;letter-spacing:0.5px;'>⚠️ Supply Chain Alert</div>"
                f"<div style='font-size:13px;color:#fca5a5;margin-top:4px;'>{supply_alert}</div>"
                f"</div>"
            ) if supply_alert else ""

            st.markdown(
                f"<div style='display:flex;gap:12px;flex-wrap:wrap;margin-bottom:18px;'>"
                f"<div style='background:{mood_color}18;border:1px solid {mood_color}44;"
                f"border-radius:10px;padding:12px 20px;flex:1;min-width:180px;'>"
                f"<div style='font-size:11px;color:#64748b;font-weight:600;"
                f"text-transform:uppercase;letter-spacing:0.5px;'>Market Mood</div>"
                f"<div style='font-size:22px;font-weight:800;color:{mood_color};margin-top:2px;'>"
                f"{mood}</div>"
                f"<div style='font-size:12px;color:#94a3b8;margin-top:4px;'>{mood_reason}</div>"
                f"</div>{supply_html}</div>",
                unsafe_allow_html=True,
            )

            stories = briefing.get("top_stories", [])

            # ── #6: Category + Level filter ───────────────────────────────
            if stories:
                unique_cats = sorted({s.get("impact_category", "General") for s in stories})
                _fc1, _fc2 = st.columns([3, 2])
                with _fc1:
                    news_cat_filter = st.multiselect(
                        "Filter by product category",
                        options=unique_cats,
                        default=[],
                        placeholder="All categories…",
                        key="news_cat_filter",
                        label_visibility="collapsed",
                    )
                with _fc2:
                    news_lvl_filter = st.multiselect(
                        "Filter by impact level",
                        options=["High", "Medium", "Low"],
                        default=[],
                        placeholder="All impact levels…",
                        key="news_lvl_filter",
                        label_visibility="collapsed",
                    )

                filtered = list(stories)
                if news_cat_filter:
                    filtered = [s for s in filtered if s.get("impact_category") in news_cat_filter]
                if news_lvl_filter:
                    filtered = [s for s in filtered if s.get("impact_level") in news_lvl_filter]

                if news_cat_filter or news_lvl_filter:
                    chips = " ".join(
                        f"<span style='background:#6366f120;color:#a5b4fc;border:1px solid #6366f140;"
                        f"border-radius:20px;padding:2px 10px;font-size:11px;font-weight:600;"
                        f"margin-right:4px;'>{c}</span>"
                        for c in (news_cat_filter + news_lvl_filter)
                    )
                    st.markdown(
                        f"<div style='margin-bottom:10px;font-size:12px;color:#64748b;'>"
                        f"Showing {len(filtered)} of {len(stories)} stories &nbsp; {chips}</div>",
                        unsafe_allow_html=True,
                    )

            # ── Story cards ───────────────────────────────────────────────
            impact_colors = {"High": "#ef4444", "Medium": "#f59e0b", "Low": "#22c55e"}
            if stories:
                section_header("Top Stories & Impact Analysis")
                for story in (filtered if stories else []):
                    ic   = impact_colors.get(story.get("impact_level", "Low"), "#6366f1")
                    cat  = story.get("impact_category", "General")
                    lvl  = story.get("impact_level", "Low")
                    src  = story.get("source", "")
                    head = story.get("headline", "")
                    imp  = story.get("impact_summary", "")
                    act  = story.get("recommended_action", "")
                    # #15: Read article link
                    slink = story.get("link", "")
                    link_html = (
                        f"<a href='{slink}' target='_blank' style='font-size:10px;color:#6366f1;"
                        f"text-decoration:none;padding:2px 9px;border:1px solid #6366f140;"
                        f"border-radius:20px;background:#6366f110;margin-left:6px;'>"
                        f"🔗 Read Article</a>"
                    ) if slink else ""

                    st.markdown(
                        f"<div style='background:#0f1420;border:1px solid #1e2433;"
                        f"border-left:4px solid {ic};border-radius:10px;"
                        f"padding:16px;margin-bottom:10px;'>"
                        f"<div style='display:flex;gap:6px;margin-bottom:6px;flex-wrap:wrap;align-items:center;'>"
                        f"<span style='font-size:10px;padding:2px 8px;border-radius:12px;"
                        f"background:{ic}22;color:{ic};font-weight:700;"
                        f"text-transform:uppercase;'>{lvl} IMPACT</span>"
                        f"<span style='font-size:10px;padding:2px 8px;border-radius:12px;"
                        f"background:#1e2433;color:#94a3b8;'>{cat}</span>"
                        f"<span style='font-size:10px;color:#475569;'>{src}</span>"
                        f"{link_html}"
                        f"</div>"
                        f"<div style='font-size:14px;font-weight:700;color:#e2e8f0;margin-bottom:8px;'>{head}</div>"
                        f"<div style='font-size:13px;color:#94a3b8;margin-bottom:10px;'>{imp}</div>"
                        f"<div style='background:#ffffff08;border-radius:6px;padding:8px 12px;'>"
                        f"<span style='color:#22c55e;font-weight:700;font-size:11px;'>▶ ACTION: </span>"
                        f"<span style='color:#d1fae5;font-size:12px;'>{act}</span>"
                        f"</div></div>",
                        unsafe_allow_html=True,
                    )
            else:
                st.info("No stories returned from GPT. Try refreshing.")

            # ── #11: Past Briefings Archive ───────────────────────────────
            past_rows = _get_past_briefings(days=14)
            if past_rows:
                with st.expander(f"📋 Past Briefings Archive ({len(past_rows)} saved, last 14 days)"):
                    st.caption("Briefings are auto-saved on each refresh and kept for 14 days.")
                    for row in past_rows:
                        bid, created_at, mood_a, reason_a, _ = row
                        ts_disp  = created_at[:16].replace("T", " ") + " UTC"
                        mood_c_a = {"Bullish": "#22c55e", "Bearish": "#ef4444"}.get(mood_a, "#f59e0b")
                        col_a, col_b = st.columns([4, 1])
                        with col_a:
                            st.markdown(
                                f"<div style='padding:8px 0;border-bottom:1px solid #1e2535;'>"
                                f"<span style='font-size:12px;color:#e2e8f0;font-weight:600;'>{ts_disp}</span>"
                                f" &nbsp;<span style='background:{mood_c_a}20;color:{mood_c_a};"
                                f"border-radius:20px;padding:2px 8px;font-size:11px;font-weight:700;'>"
                                f"● {mood_a}</span>"
                                f"<div style='font-size:11px;color:#64748b;margin-top:2px;'>{reason_a}</div>"
                                f"</div>",
                                unsafe_allow_html=True,
                            )
                        with col_b:
                            if st.button("View", key=f"arch_{bid}"):
                                st.session_state["_arch_view"] = bid
                                st.rerun()

                    if "_arch_view" in st.session_state:
                        _abid      = st.session_state["_arch_view"]
                        _abriefing = _get_briefing_by_id(_abid)
                        if _abriefing:
                            st.divider()
                            st.markdown("**📂 Archived Briefing Preview:**")
                            for _as in _abriefing.get("top_stories", [])[:3]:
                                _alc = impact_colors.get(_as.get("impact_level", "Low"), "#6366f1")
                                st.markdown(
                                    f"<div style='background:#0d1117;border-left:3px solid {_alc};"
                                    f"border-radius:6px;padding:10px 14px;margin-bottom:8px;'>"
                                    f"<div style='font-size:12px;font-weight:700;color:#e2e8f0;'>"
                                    f"{_as.get('headline','')}</div>"
                                    f"<div style='font-size:11px;color:#64748b;'>"
                                    f"{_as.get('impact_summary','')}</div></div>",
                                    unsafe_allow_html=True,
                                )
                            if st.button("✕ Close archive view", key="close_arch"):
                                del st.session_state["_arch_view"]
                                st.rerun()

        elif not _cache_valid:
            st.info("Click **Refresh Briefing** to fetch today's market news and GPT analysis.")
        elif "error" in (_cache or {}):
            st.error(f"GPT error: {_cache.get('error')}")

    # ═════════════════════════════════════════════════════════════════════════
    # TAB 2 — Price Tracker
    # ═════════════════════════════════════════════════════════════════════════
    with tab_price:
        st.markdown(
            "<div style='font-size:13px;color:#64748b;margin-bottom:20px;'>"
            "Search live prices from Google Shopping via SerpAPI. "
            "Results are cached for 6 hours and stored locally for historical trend charts.</div>",
            unsafe_allow_html=True,
        )

        pc1, pc2 = st.columns([1, 2])
        with pc1:
            selected_cat = st.selectbox(
                "Product Category", ["— Select —"] + categories, key="price_cat"
            )
        with pc2:
            search_query = st.text_input(
                "Search Query",
                placeholder="e.g. Samsung 970 EVO 1TB NVMe",
                key="price_query",
            )

        search_btn = st.button(
            "🔍 Search Prices",
            key="price_search",
            disabled=not (search_query.strip() and has_serpapi),
        )

        if not has_serpapi:
            st.warning(
                "**SerpAPI key required** — add `SERPAPI_KEY=your_key` to `.env` and restart. "
                "Free tier: 100 searches/month at [serpapi.com](https://serpapi.com)."
            )

        # ── Debug panel (always visible so server issues are diagnosable) ──────
        with st.expander("🔧 SerpAPI Debug Info", expanded=not has_serpapi):
            import dotenv as _dotenv_mod
            _dotenv_loaded = "✅ python-dotenv installed"
            _key_val = os.environ.get("SERPAPI_KEY", "")
            _key_display = f"✅ Key loaded — `{_key_val[:6]}...{_key_val[-4:]}` ({len(_key_val)} chars)" if _key_val else "❌ Key is EMPTY — not in environment"
            _env_path_check = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))
            _env_exists = "✅ .env file found" if os.path.exists(_env_path_check) else f"❌ .env NOT found at `{_env_path_check}`"
            st.markdown(f"""
| Check | Status |
|---|---|
| python-dotenv | {_dotenv_loaded} |
| SERPAPI_KEY in env | {_key_display} |
| .env file on disk | {_env_exists} |
| Working directory | `{os.getcwd()}` |
""")
        if search_btn and search_query.strip():
            query = search_query.strip()
            cat   = selected_cat if selected_cat != "— Select —" else "General"

            cached = _get_cached_result(query)
            if cached:
                avg_p, min_p, max_p, results_json_str, gpt_summary, created_at = cached
                # #12: Explicit cache-hit feedback
                st.success(
                    f"✅ Loaded from cache (fetched {created_at[:16]} UTC) — no API call made."
                )
                results = json.loads(results_json_str) if results_json_str else []
            else:
                # #12: Descriptive spinner with timing
                _t0 = time.time()
                with st.spinner(
                    f"🔍 Searching Google Shopping for '{query}'… "
                    f"This usually takes 3–5 seconds."
                ):
                    results, fetch_error = _fetch_prices(query, serpapi_key)
                _elapsed = round(time.time() - _t0, 1)

                if fetch_error:
                    st.error(fetch_error)
                elif not results:
                    st.error(
                        "No results returned. Check your SerpAPI key or try a different query."
                    )
                else:
                    prices  = [r["price"] for r in results if r["price"] > 0]
                    avg_p   = round(sum(prices) / len(prices), 2) if prices else 0
                    min_p   = round(min(prices), 2) if prices else 0
                    max_p   = round(max(prices), 2) if prices else 0

                    results_txt = "\n".join(
                        [f"- {r['title']} | ₹{r['price']:,.0f} | {r['source']}" for r in results[:10]]
                    )
                    with st.spinner("GPT-4o summarising results…"):
                        gpt_summary = _gpt(
                            "You are a procurement analyst for an Indian IT distributor.",
                            f"Product: {query}\nCategory: {cat}\n\n{results_txt}\n\n"
                            "Give a 2-3 sentence summary: price range, competitiveness, one recommendation.",
                            max_tokens=200,
                        )
                    _save_price_result(
                        query, cat, avg_p, min_p, max_p, json.dumps(results), gpt_summary
                    )
                    # #12: Timestamped success banner
                    st.success(
                        f"✅ Found {len(results)} results in {_elapsed}s · "
                        f"Saved to history · {datetime.datetime.utcnow().strftime('%H:%M UTC')}"
                    )

            if results:
                # KPI row
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Avg Price",    f"₹{avg_p:,.0f}")
                m2.metric("Lowest",       f"₹{min_p:,.0f}")
                m3.metric("Highest",      f"₹{max_p:,.0f}")
                spread = round((max_p - min_p) / min_p * 100, 1) if min_p > 0 else 0
                m4.metric("Price Spread", f"{spread}%")

                if gpt_summary and not gpt_summary.startswith("[GPT error"):
                    st.info(f"🤖 **GPT Analysis:** {gpt_summary}")

                df_res = pd.DataFrame(results).rename(columns={
                    "title": "Product", "price": "Price (₹)", "source": "Seller"
                }).sort_values("Price (₹)")
                section_header(f"Price Comparison — {len(df_res)} results")
                st.dataframe(
                    df_res[["Product", "Price (₹)", "Seller"]],
                    column_config={"Price (₹)": st.column_config.NumberColumn(format="₹%,.0f")},
                    use_container_width=True, hide_index=True,
                )

                # History chart
                hist_df = _get_price_history(query, days=30)
                if not hist_df.empty and len(hist_df) > 1:
                    section_header("30-Day Price History")
                    fig_h = go.Figure()
                    fig_h.add_trace(go.Scatter(
                        x=hist_df["Date"], y=hist_df["Avg Price"],
                        mode="lines+markers", name="Avg Price",
                        line=dict(color="#6366f1", width=2), marker=dict(size=7),
                    ))
                    fig_h.add_trace(go.Scatter(
                        x=pd.concat([hist_df["Date"], hist_df["Date"][::-1]]),
                        y=pd.concat([hist_df["Max Price"], hist_df["Min Price"][::-1]]),
                        fill="toself", fillcolor="rgba(99,102,241,0.1)",
                        line=dict(color="rgba(255,255,255,0)"), name="Min–Max Range",
                    ))
                    fig_h.update_layout(
                        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                        height=300,
                        yaxis=dict(tickprefix="₹", gridcolor="#1e2433"),
                        xaxis=dict(gridcolor="#1e2433"),
                        legend=dict(orientation="h", y=1.1),
                    )
                    st.plotly_chart(fig_h, use_container_width=True)
                    st.caption("History builds over time — each new search adds a data point.")
                elif not hist_df.empty:
                    st.caption("📌 Price history chart appears after 2+ searches on the same query.")

        # ── Past searches ─────────────────────────────────────────────────
        all_searches = _get_all_searches(days=30)
        if not all_searches.empty:
            with st.expander("📋 Past Searches (last 30 days)"):
                st.dataframe(
                    all_searches,
                    column_config={"Avg Price (₹)": st.column_config.NumberColumn(format="₹%,.0f")},
                    use_container_width=True, hide_index=True,
                )

        # ── #9: Compare Categories bar chart ──────────────────────────────
        all_7d = _get_all_searches(days=7)
        if not all_7d.empty and "Category" in all_7d.columns:
            all_7d["Avg Price (₹)"] = pd.to_numeric(all_7d["Avg Price (₹)"], errors="coerce")
            cat_summary = (
                all_7d.groupby("Category")["Avg Price (₹)"]
                .mean().dropna().sort_values(ascending=True).reset_index()
            )
            if len(cat_summary) >= 2:
                st.markdown("<div style='margin-top:24px;'></div>", unsafe_allow_html=True)
                section_header("Category Price Comparison (Last 7 Days)")
                st.caption("Average observed price per category across all recent searches.")
                fig_cat = px.bar(
                    cat_summary, x="Avg Price (₹)", y="Category",
                    orientation="h", text="Avg Price (₹)",
                    color="Avg Price (₹)",
                    color_continuous_scale=["#1e3a5f", "#6366f1", "#a78bfa"],
                )
                fig_cat.update_traces(texttemplate="₹%{text:,.0f}", textposition="outside")
                fig_cat.update_layout(
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    height=max(200, len(cat_summary) * 36),
                    showlegend=False, coloraxis_showscale=False,
                    xaxis=dict(tickprefix="₹", gridcolor="#1e2433"),
                    yaxis=dict(gridcolor="#1e2433"),
                    margin=dict(l=0, r=80, t=10, b=10),
                )
                st.plotly_chart(fig_cat, use_container_width=True)

        # ── #17: Competitor Price Tracker ─────────────────────────────────
        st.markdown("<div style='margin-top:20px;'></div>", unsafe_allow_html=True)
        with st.expander("🎯 Competitor Price Tracker — Monitor specific SKUs"):
            st.caption(
                "Save competitor product queries to your watch list. "
                "Hit **Refresh All Prices** to update cached data in one click."
            )
            cw1, cw2, cw3 = st.columns([2, 1, 1])
            with cw1:
                new_cq = st.text_input(
                    "Product to track", placeholder="e.g. TP-Link 8-Port Gigabit Switch",
                    key="comp_q", label_visibility="collapsed",
                )
            with cw2:
                new_cc = st.selectbox(
                    "Category", ["— Select —"] + categories,
                    key="comp_cat", label_visibility="collapsed",
                )
            with cw3:
                if st.button("➕ Add to Watch List", key="add_comp", use_container_width=True):
                    if new_cq.strip() and new_cc != "— Select —":
                        _add_competitor_watch(new_cq.strip(), new_cc)
                        st.success(f"Added: {new_cq.strip()}")
                        st.rerun()
                    else:
                        st.warning("Enter a product name and select a category.")

            watches = _get_competitor_watches()
            if not watches:
                st.info("No competitor products tracked yet. Add one above.")
            else:
                st.caption(f"📌 {len(watches)} product(s) on watch list")
                refresh_all = st.button(
                    "🔄 Refresh All Prices" + ("" if has_serpapi else " (SerpAPI key needed)"),
                    key="refresh_comp_all", disabled=not has_serpapi,
                )
                comp_rows = []
                for wid, wq, wcat, wadded in watches:
                    cached_w = _get_cached_result(wq, hours=_PRICE_CACHE_HOURS)
                    if refresh_all and has_serpapi and not cached_w:
                        with st.spinner(f"Fetching: {wq}…"):
                            items_w = _fetch_prices(wq, serpapi_key)
                        if items_w:
                            px_w  = [r["price"] for r in items_w if r["price"] > 0]
                            avg_w = round(sum(px_w) / len(px_w), 2) if px_w else 0
                            min_w = round(min(px_w), 2) if px_w else 0
                            max_w = round(max(px_w), 2) if px_w else 0
                            _save_price_result(wq, wcat, avg_w, min_w, max_w, json.dumps(items_w), "")
                            cached_w = (avg_w, min_w, max_w, json.dumps(items_w), "",
                                        datetime.datetime.utcnow().isoformat())
                    if cached_w:
                        avg_w, min_w, max_w, _, _, fetched_at = cached_w
                        comp_rows.append({
                            "Product": wq, "Category": wcat,
                            "Avg (₹)": avg_w, "Min (₹)": min_w, "Max (₹)": max_w,
                            "Last Fetched": fetched_at[:16].replace("T", " ") + " UTC",
                            "_wid": wid,
                        })
                    else:
                        comp_rows.append({
                            "Product": wq, "Category": wcat,
                            "Avg (₹)": None, "Min (₹)": None, "Max (₹)": None,
                            "Last Fetched": "Not yet fetched", "_wid": wid,
                        })

                if comp_rows:
                    comp_df = pd.DataFrame(comp_rows)
                    st.dataframe(
                        comp_df.drop(columns=["_wid"]),
                        column_config={
                            "Avg (₹)": st.column_config.NumberColumn(format="₹%,.0f"),
                            "Min (₹)": st.column_config.NumberColumn(format="₹%,.0f"),
                            "Max (₹)": st.column_config.NumberColumn(format="₹%,.0f"),
                        },
                        use_container_width=True, hide_index=True,
                    )
                    rm_opts = {f"{r['Product']}": r["_wid"] for r in comp_rows}
                    rm_sel  = st.selectbox(
                        "Remove from watch list:", ["— Select —"] + list(rm_opts.keys()),
                        key="comp_rm",
                    )
                    if rm_sel != "— Select —":
                        if st.button("🗑️ Remove", key="do_comp_rm"):
                            _remove_competitor_watch(rm_opts[rm_sel])
                            st.success(f"Removed: {rm_sel}")
                            st.rerun()

    # ═════════════════════════════════════════════════════════════════════════
    # TAB 3 — Partner Alerts  (all 5 bug fixes + #14 pagination)
    # ═════════════════════════════════════════════════════════════════════════
    with tab_alerts:
        st.markdown(
            "<div style='font-size:13px;color:#64748b;margin-bottom:20px;'>"
            "Cross-reference price data with your partner database. "
            "Identifies which partners buy a given category and ranks them by urgency.</div>",
            unsafe_allow_html=True,
        )

        alert_cat = st.selectbox(
            "Choose a product category to analyse",
            ["— Select —"] + categories, key="alert_cat",
        )

        if alert_cat == "— Select —":
            st.info("Select a product category above to see which partners to call.")
        else:
            # ── Partner spend data  (Bug #3: exact-first category match) ──
            pf       = getattr(ai, "df_partner_features", None)
            spend_df = getattr(ai, "df_recent_group_spend", None)

            cat_partners = pd.DataFrame()
            if spend_df is not None and not spend_df.empty:
                if "group_name" in spend_df.columns and "company_name" in spend_df.columns:
                    exact = spend_df["group_name"].str.lower() == alert_cat.lower()
                    if exact.any():
                        cat_partners = spend_df[exact].copy()
                    else:
                        sub = spend_df["group_name"].str.lower().str.contains(
                            alert_cat.lower(), na=False
                        )
                        cat_partners = spend_df[sub].copy()

            if cat_partners.empty and pf is not None and not pf.empty:
                pr = pf.reset_index()
                if "company_name" not in pr.columns and "index" in pr.columns:
                    pr = pr.rename(columns={"index": "company_name"})
                cat_partners = pr.copy()
                cat_partners["total_spend"] = pr.get(
                    "recent_90_revenue", pr.get("total_revenue", 0)
                )

            # Bug #2: no st.stop() — use None flag
            if cat_partners.empty:
                st.warning("Could not load partner spend data. Please refresh the engine.")
                cat_partners = None

            # ── Enrich with churn / risk features ─────────────────────────
            if pf is not None and not pf.empty:
                pr = pf.reset_index()
                if "company_name" not in pr.columns and "index" in pr.columns:
                    pr = pr.rename(columns={"index": "company_name"})
                enrich = ["company_name"]
                for c in ["churn_probability", "revenue_drop_pct", "recency_days",
                          "cluster_label", "health_segment"]:
                    if c in pr.columns:
                        enrich.append(c)
                if cat_partners is not None and "company_name" in cat_partners.columns:
                    cat_partners = cat_partners.merge(pr[enrich], on="company_name", how="left")

            # Bug #5: always-defined trend_pct
            trend_pct = 0

            # ── Price context  (Bug #3: exact-first) ──────────────────────
            all_searches = _get_all_searches(days=30)
            cat_searches = pd.DataFrame()
            if not all_searches.empty:
                ex = all_searches["Category"].str.lower() == alert_cat.lower()
                cat_searches = all_searches[ex].copy() if ex.any() else all_searches[
                    all_searches["Category"].str.lower().str.contains(alert_cat.lower(), na=False)
                ].copy()

            # ── Trend banner  (Bug #1: ≥3 searches over ≥3 days) ──────────
            _trend_shown = False
            if not cat_searches.empty:
                _n     = len(cat_searches)
                _dates = pd.to_datetime(cat_searches["Date"], errors="coerce").dropna()
                _span  = (_dates.max() - _dates.min()).days if len(_dates) >= 2 else 0

                if _n >= 3 and _span >= 3:
                    lp = cat_searches.iloc[0]["Avg Price (₹)"]
                    op = cat_searches.iloc[-1]["Avg Price (₹)"]
                    if op and op > 0:
                        trend_pct   = (lp - op) / op * 100
                        tc = "#ef4444" if trend_pct > 5 else "#22c55e" if trend_pct < -5 else "#f59e0b"
                        tl = "Rising ↑"  if trend_pct > 5 else "Falling ↓" if trend_pct < -5 else "Stable →"
                        fd = _dates.min().strftime("%d %b")
                        td = _dates.max().strftime("%d %b")
                        st.markdown(
                            f"<div style='background:#161b2a;border-radius:10px;padding:14px 18px;"
                            f"margin-bottom:18px;display:flex;gap:20px;align-items:center;flex-wrap:wrap;'>"
                            f"<div><div style='font-size:11px;color:#64748b;'>Category</div>"
                            f"<div style='font-size:16px;font-weight:700;color:#e2e8f0;'>{alert_cat}</div></div>"
                            f"<div><div style='font-size:11px;color:#64748b;'>Latest Avg Price</div>"
                            f"<div style='font-size:16px;font-weight:700;color:#e2e8f0;'>₹{lp:,.0f}</div></div>"
                            f"<div style='background:{tc}18;padding:6px 16px;border-radius:20px;"
                            f"font-weight:700;font-size:14px;color:{tc};'>{tl} {abs(trend_pct):.1f}%</div>"
                            f"<div style='font-size:12px;color:#475569;margin-left:auto;'>"
                            f"{_n} searches · {fd}→{td}</div></div>",
                            unsafe_allow_html=True,
                        )
                        _trend_shown = True
                else:
                    lp      = cat_searches.iloc[0]["Avg Price (₹)"]
                    _needed = max(0, 3 - _n)
                    st.markdown(
                        f"<div style='background:#161b2a;border-radius:10px;padding:12px 18px;"
                        f"margin-bottom:18px;display:flex;gap:16px;align-items:center;flex-wrap:wrap;'>"
                        f"<div><div style='font-size:11px;color:#64748b;'>Category</div>"
                        f"<div style='font-size:15px;font-weight:700;color:#e2e8f0;'>{alert_cat}</div></div>"
                        f"<div><div style='font-size:11px;color:#64748b;'>Latest Avg Price</div>"
                        f"<div style='font-size:15px;font-weight:700;color:#e2e8f0;'>₹{lp:,.0f}</div></div>"
                        f"<div style='background:#1e2535;padding:5px 14px;border-radius:20px;"
                        f"font-size:12px;color:#64748b;border:1px dashed #334155;'>"
                        f"📊 Trend needs {_needed} more search{'es' if _needed!=1 else ''} over 3+ days"
                        f"</div></div>",
                        unsafe_allow_html=True,
                    )
            else:
                st.info(
                    f"No price data yet for **{alert_cat}**. "
                    "Go to the **Price Tracker** tab and search for this category first."
                )

            if cat_partners is not None:
                # ── Urgency scoring ────────────────────────────────────────
                section_header(f"Partners Who Buy {alert_cat} — Outreach Priority")

                for col in ["churn_probability", "revenue_drop_pct", "recency_days"]:
                    if col in cat_partners.columns:
                        cat_partners[col] = pd.to_numeric(
                            cat_partners[col], errors="coerce"
                        ).fillna(0)

                spend_col   = pd.to_numeric(cat_partners.get("total_spend", 0), errors="coerce").fillna(0)
                churn_col   = cat_partners.get("churn_probability", pd.Series(0, index=cat_partners.index))
                drop_col    = cat_partners.get("revenue_drop_pct",  pd.Series(0, index=cat_partners.index))
                recency_col = cat_partners.get("recency_days",      pd.Series(30, index=cat_partners.index))

                cat_partners["urgency_score"] = (
                    0.40 * pd.to_numeric(churn_col,    errors="coerce").fillna(0).clip(0, 1)
                    + 0.30 * pd.to_numeric(drop_col,   errors="coerce").fillna(0).clip(0, 100) / 100
                    + 0.20 * pd.to_numeric(recency_col, errors="coerce").fillna(30).clip(0, 90) / 90
                    + 0.10 * (spend_col / (spend_col.max() + 1))
                )
                cat_partners = cat_partners.sort_values("urgency_score", ascending=False)

                def _priority_label(score):
                    if score >= 0.65: return "🔴 CALL TODAY"
                    if score >= 0.40: return "🟡 CALL THIS WEEK"
                    return "🟢 MONITOR"

                cat_partners["Priority"] = cat_partners["urgency_score"].apply(_priority_label)

                optional_map = {
                    "total_spend":      "Category Spend (₹)",
                    "revenue_drop_pct": "Revenue Drop %",
                    "churn_probability":"Churn Risk",
                    "recency_days":     "Days Since Order",
                    "cluster_label":    "Cluster",
                }
                show_cols = ["company_name", "Priority"]
                for k in optional_map:
                    if k in cat_partners.columns:
                        show_cols.append(k)
                show_cols.append("urgency_score")

                total_count = len(cat_partners)

                # ── #14: Pagination slider ─────────────────────────────────
                if total_count > 25:
                    show_n = st.slider(
                        f"Partners to show ({total_count} total)",
                        min_value=10, max_value=min(total_count, 100),
                        value=25, step=5, key="alert_show_n",
                    )
                else:
                    show_n = total_count

                display_df = cat_partners[show_cols].head(show_n).copy().rename(
                    columns={"company_name": "Partner", **optional_map, "urgency_score": "Urgency Score"}
                )

                col_cfg = {"Urgency Score": st.column_config.ProgressColumn(
                    "Urgency Score", min_value=0, max_value=1, format="%.2f"
                )}
                if "Category Spend (₹)" in display_df.columns:
                    col_cfg["Category Spend (₹)"] = st.column_config.NumberColumn(format="₹%,.0f")
                if "Revenue Drop %" in display_df.columns:
                    col_cfg["Revenue Drop %"] = st.column_config.NumberColumn(format="%.1f%%")
                if "Churn Risk" in display_df.columns:
                    col_cfg["Churn Risk"] = st.column_config.ProgressColumn(
                        "Churn Risk", min_value=0, max_value=1, format="%.2f"
                    )

                st.dataframe(
                    display_df, column_config=col_cfg,
                    use_container_width=True, hide_index=True,
                )

                if total_count > show_n:
                    st.caption(
                        f"Showing {show_n} of {total_count} partners. "
                        "Adjust the slider above or export CSV for the full list."
                    )

                # ── GPT talking points  (Bug #4: session_state cache) ──────
                if has_openai and not cat_searches.empty and _trend_shown:
                    top5 = display_df.head(5)["Partner"].tolist() if "Partner" in display_df.columns else []
                    if top5:
                        _ck = f"_tp_{alert_cat}_{','.join(top5)}"
                        with st.expander("🤖 GPT-4o Talking Points for Top 5 Partners"):
                            if _ck not in st.session_state:
                                td = "rising" if trend_pct > 5 else "falling" if trend_pct < -5 else "stable"
                                with st.spinner("Generating talking points…"):
                                    st.session_state[_ck] = _gpt(
                                        "You are a senior sales coach for an Indian IT hardware distributor.",
                                        f"Category: {alert_cat}\n"
                                        f"Market price trend: {td} ({trend_pct:+.1f}% vs 30 days ago)\n"
                                        f"Partners to call: {', '.join(top5)}\n\n"
                                        "Write a concise outreach talking point for each partner:\n"
                                        "**[Partner Name]**: [2 sentences referencing the price trend]\n"
                                        "Be specific, professional, and action-oriented.",
                                        max_tokens=500,
                                    )
                            else:
                                st.caption("📌 Cached — no API call made")
                            st.markdown(st.session_state[_ck])

                # ── CSV export ─────────────────────────────────────────────
                st.download_button(
                    "⬇️ Export Partner Alert List",
                    display_df.to_csv(index=False),
                    f"partner_alerts_{alert_cat.replace(' ','_')}.csv",
                    "text/csv",
                )

    # ═════════════════════════════════════════════════════════════════════════
    # TAB 4 — Heat Map  (#20 Partner × Category)
    # ═════════════════════════════════════════════════════════════════════════
    with tab_heatmap:
        st.markdown(
            "<div style='font-size:13px;color:#64748b;margin-bottom:20px;'>"
            "Partner vs Category spend matrix — green = strong buyer, dark = untapped opportunity. "
            "Hover any cell for exact spend. Use this to find cross-sell gaps at a glance.</div>",
            unsafe_allow_html=True,
        )

        spend_hm = getattr(ai, "df_recent_group_spend", None)

        if spend_hm is None or spend_hm.empty:
            st.warning("No spend data available. Please ensure the engine has loaded data.")
        elif not {"group_name", "company_name"}.issubset(spend_hm.columns):
            st.warning("Spend data missing required columns (company_name, group_name, total_spend).")
        else:
            hc1, hc2, hc3 = st.columns([1, 1, 2])
            with hc1:
                top_n_p = st.slider("Top N Partners (by spend)", 10, 50, 25, 5, key="hm_p")
            with hc2:
                top_n_c = st.slider("Top N Categories",          5, 30, 15, 5, key="hm_c")
            with hc3:
                hm_scale = st.radio(
                    "Colour scale", ["Linear (₹)", "Log scale (better for sparse data)"],
                    horizontal=True, key="hm_scale",
                )

            hm_df = spend_hm.copy()
            hm_df["total_spend"] = pd.to_numeric(
                hm_df.get("total_spend", 0), errors="coerce"
            ).fillna(0)

            top_partners = (
                hm_df.groupby("company_name")["total_spend"].sum()
                .nlargest(top_n_p).index.tolist()
            )
            top_cats = (
                hm_df.groupby("group_name")["total_spend"].sum()
                .nlargest(top_n_c).index.tolist()
            )

            hm_filtered = hm_df[
                hm_df["company_name"].isin(top_partners) &
                hm_df["group_name"].isin(top_cats)
            ]
            pivot = (
                hm_filtered
                .pivot_table(index="company_name", columns="group_name",
                             values="total_spend", aggfunc="sum", fill_value=0)
                .reindex(top_partners).fillna(0)
            )

            if pivot.empty:
                st.info("No data to display with the current filters.")
            else:
                z_raw   = pivot.values
                z_disp  = np.log1p(z_raw) if "Log" in hm_scale else z_raw

                # Human-readable hover text
                hover_text = []
                for row in z_raw:
                    hr = []
                    for v in row:
                        if   v >= 1_00_00_000: hr.append(f"₹{v/1_00_00_000:.1f}Cr")
                        elif v >= 1_00_000:    hr.append(f"₹{v/1_00_000:.1f}L")
                        elif v >= 1_000:       hr.append(f"₹{v/1_000:.0f}K")
                        elif v == 0:           hr.append("—")
                        else:                  hr.append(f"₹{v:.0f}")
                    hover_text.append(hr)

                fig_hm = go.Figure(data=go.Heatmap(
                    z=z_disp,
                    x=pivot.columns.tolist(),
                    y=pivot.index.tolist(),
                    text=hover_text,
                    hovertemplate="<b>%{y}</b><br>%{x}<br>Spend: %{text}<extra></extra>",
                    colorscale=[
                        [0.00, "#0d1117"],
                        [0.05, "#1e293b"],
                        [0.30, "#1d4ed8"],
                        [0.60, "#7c3aed"],
                        [0.85, "#10b981"],
                        [1.00, "#22c55e"],
                    ],
                    showscale=True,
                    colorbar=dict(
                        title=dict(
                            text="Log₁(₹+1)" if "Log" in hm_scale else "₹ Spend",
                            side="right",
                        ),
                        tickfont=dict(color="#94a3b8", size=10),
                        len=0.7,
                    ),
                ))
                fig_hm.update_layout(
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    height=max(420, len(top_partners) * 22),
                    margin=dict(l=200, r=40, t=30, b=120),
                    xaxis=dict(tickfont=dict(size=10, color="#94a3b8"),
                               tickangle=-40, gridcolor="#1e2433"),
                    yaxis=dict(tickfont=dict(size=10, color="#94a3b8"),
                               autorange="reversed", gridcolor="#1e2433"),
                    font=dict(color="#e2e8f0"),
                )
                st.plotly_chart(fig_hm, use_container_width=True)

                # Summary stats
                total_cells  = pivot.shape[0] * pivot.shape[1]
                zero_cells   = int((pivot == 0).values.sum())
                coverage_pct = round((total_cells - zero_cells) / total_cells * 100, 1)

                s1, s2, s3 = st.columns(3)
                s1.metric("Partners Shown",    len(top_partners))
                s2.metric("Categories Shown",  len(top_cats))
                s3.metric("Coverage",          f"{coverage_pct}%",
                          delta=f"{total_cells - zero_cells}/{total_cells} cells active",
                          delta_color="off",
                          help="% of partner-category combinations with ≥₹1 spend")

                st.caption(
                    "🟢 Green = high spend · 🔵 Blue = moderate · ⬛ Dark = zero spend (cross-sell opportunity). "
                    "Switch to Log scale to see low-spend cells more clearly."
                )

                with st.expander("📋 View Raw Pivot Table"):
                    def _fmt(v):
                        if v >= 1_00_000: return f"₹{v/1_00_000:.1f}L"
                        if v >= 1_000:    return f"₹{v/1_000:.0f}K"
                        if v == 0:        return "—"
                        return f"₹{v:.0f}"
                    st.dataframe(
                        pivot.applymap(_fmt),
                        use_container_width=True,
                    )
                    st.download_button(
                        "⬇️ Download Pivot CSV",
                        pivot.to_csv(),
                        "partner_category_heatmap.csv",
                        "text/csv",
                        key="hm_csv",
                    )
