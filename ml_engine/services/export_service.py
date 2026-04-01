"""
Export service for generating PDF and Excel reports.
Used by Partner 360, Recommendation Hub, and Clustering tabs.
"""

import io
import re
from datetime import datetime

import math

import pandas as pd


def _safe_float(val, default=0.0):
    """Convert val to float, returning default for None/NaN."""
    try:
        v = float(val)
        return default if math.isnan(v) or math.isinf(v) else v
    except (TypeError, ValueError):
        return default


def _safe_int(val, default=0):
    """Convert val to int, returning default for None/NaN."""
    return int(_safe_float(val, default))
from fpdf import FPDF


def _sanitize(text):
    """Replace Unicode characters unsupported by Helvetica/Latin-1 with ASCII equivalents."""
    s = str(text)
    replacements = {
        "\u2014": "-",    # em dash
        "\u2013": "-",    # en dash
        "\u2018": "'",    # left single quote
        "\u2019": "'",    # right single quote
        "\u201c": '"',    # left double quote
        "\u201d": '"',    # right double quote
        "\u2026": "...",  # ellipsis
        "\u2022": "*",    # bullet
        "\u2192": "->",   # right arrow
        "\u2190": "<-",   # left arrow
        "\u2265": ">=",   # greater than or equal
        "\u2264": "<=",   # less than or equal
        "\u00a0": " ",    # non-breaking space
        "\u2003": " ",    # em space
        "\u2002": " ",    # en space
        "\u200b": "",     # zero-width space
    }
    for char, repl in replacements.items():
        s = s.replace(char, repl)
    # Fallback: encode to latin-1, replacing anything else with '?'
    s = s.encode("latin-1", errors="replace").decode("latin-1")
    return s


# ---------------------------------------------------------------------------
# Internal PDF builder
# ---------------------------------------------------------------------------

class _ReportPDF(FPDF):
    """Custom PDF with header/footer branding."""

    _title_text: str = "Consistent AI Suite"
    _subtitle_text: str = ""

    def header(self):
        self.set_font("Helvetica", "B", 14)
        self.set_text_color(25, 60, 120)
        self.cell(0, 8, self._title_text, new_x="LMARGIN", new_y="NEXT", align="L")
        if self._subtitle_text:
            self.set_font("Helvetica", "", 9)
            self.set_text_color(100, 100, 100)
            self.cell(0, 5, self._subtitle_text, new_x="LMARGIN", new_y="NEXT", align="L")
        self.set_draw_color(25, 60, 120)
        self.line(10, self.get_y() + 1, 200, self.get_y() + 1)
        self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, f"Page {self.page_no()}/{{nb}}  |  Generated {datetime.now():%Y-%m-%d %H:%M}", align="C")


def _add_section(pdf: _ReportPDF, title: str):
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(25, 60, 120)
    pdf.cell(0, 8, _sanitize(title), new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "", 10)


def _add_kv(pdf: _ReportPDF, key: str, value, bold_value: bool = False):
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(60, 6, _sanitize(str(key) + ":"), new_x="RIGHT")
    pdf.set_font("Helvetica", "B" if bold_value else "", 10)
    pdf.cell(0, 6, _sanitize(str(value)), new_x="LMARGIN", new_y="NEXT")


def _add_table(pdf: _ReportPDF, df: pd.DataFrame, max_rows: int = 50):
    """Render a DataFrame as an auto-sized table inside the PDF."""
    if df is None or df.empty:
        pdf.cell(0, 6, "(no data)", new_x="LMARGIN", new_y="NEXT")
        return

    df = df.head(max_rows).reset_index(drop=True)
    cols = list(df.columns)

    # Calculate column widths proportionally based on max content length
    effective_width = pdf.w - pdf.l_margin - pdf.r_margin
    raw_widths = []
    for c in cols:
        max_len = max(len(str(c)), df[c].astype(str).str.len().max() if len(df) > 0 else 5)
        raw_widths.append(min(max_len, 30))
    total = sum(raw_widths) or 1
    col_widths = [w / total * effective_width for w in raw_widths]

    # Header
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_fill_color(230, 235, 245)
    for i, c in enumerate(cols):
        pdf.cell(col_widths[i], 6, _sanitize(str(c)[:28]), border=1, fill=True)
    pdf.ln()

    # Rows
    pdf.set_font("Helvetica", "", 7)
    for _, row in df.iterrows():
        if pdf.get_y() > 260:
            pdf.add_page()
            pdf.set_font("Helvetica", "B", 8)
            pdf.set_fill_color(230, 235, 245)
            for i, c in enumerate(cols):
                pdf.cell(col_widths[i], 6, _sanitize(str(c)[:28]), border=1, fill=True)
            pdf.ln()
            pdf.set_font("Helvetica", "", 7)
        for i, c in enumerate(cols):
            val = str(row[c]) if pd.notna(row[c]) else ""
            pdf.cell(col_widths[i], 5, _sanitize(val[:30]), border=1)
        pdf.ln()


# ---------------------------------------------------------------------------
# Public API — Partner 360 export
# ---------------------------------------------------------------------------

def export_partner_360_pdf(partner_name: str, report: dict) -> bytes:
    """Generate a Partner 360 PDF report and return raw bytes."""
    facts = report.get("facts", {})
    gaps = report.get("gaps", pd.DataFrame())
    cluster_label = report.get("cluster_label", "Unknown")
    cluster_type = report.get("cluster_type", "Unknown")
    alerts = report.get("alerts", []) or []
    playbook = report.get("playbook", {}) or {}

    pdf = _ReportPDF(orientation="P", unit="mm", format="A4")
    pdf._title_text = "Partner 360 Report"
    pdf._subtitle_text = f"Partner: {partner_name}  |  Generated: {datetime.now():%Y-%m-%d %H:%M}"
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    # --- Health Overview ---
    _add_section(pdf, "Health Overview")
    _add_kv(pdf, "Health Status", facts.get("health_status", "Unknown"), bold_value=True)
    _add_kv(pdf, "Health Score", f"{_safe_float(facts.get('health_score', 0)):.2f}")
    _add_kv(pdf, "Health Segment", facts.get("health_segment", "Unknown"))
    _add_kv(pdf, "Revenue Drop", f"{_safe_float(facts.get('revenue_drop_pct', 0)):.1f}%")
    _add_kv(pdf, "Est. Monthly Loss", f"Rs {_safe_int(facts.get('estimated_monthly_loss', 0)):,}")
    _add_kv(pdf, "Recency", f"{_safe_int(facts.get('recency_days', 0))} days")
    _add_kv(pdf, "Degrowth Flag", "Yes" if facts.get("degrowth_flag") else "No")
    pdf.ln(3)

    # --- Cluster Info ---
    _add_section(pdf, "Cluster Intelligence")
    _add_kv(pdf, "Cluster Label", cluster_label)
    _add_kv(pdf, "Cluster Type", cluster_type)
    _add_kv(pdf, "Strategic Tag", report.get("strategic_tag", "N/A"))
    pdf.ln(3)

    # --- Churn & Forecast ---
    _add_section(pdf, "Churn & Revenue Forecast")
    _add_kv(pdf, "Churn Probability", f"{_safe_float(facts.get('churn_probability', 0)) * 100:.1f}%")
    _add_kv(pdf, "Churn Risk Band", facts.get("churn_risk_band", "Unknown"))
    _add_kv(pdf, "Revenue At Risk (90d)", f"Rs {_safe_int(facts.get('expected_revenue_at_risk_90d', 0)):,}")
    _add_kv(pdf, "Revenue At Risk (Monthly)", f"Rs {_safe_int(facts.get('expected_revenue_at_risk_monthly', 0)):,}")
    _add_kv(pdf, "Forecast Next 30d", f"Rs {_safe_int(facts.get('forecast_next_30d', 0)):,}")
    _add_kv(pdf, "Forecast Trend", f"{_safe_float(facts.get('forecast_trend_pct', 0)):+.1f}%")
    _add_kv(pdf, "Forecast Confidence", f"{_safe_float(facts.get('forecast_confidence', 0)):.2f}")
    pdf.ln(3)

    # --- Credit Risk ---
    _add_section(pdf, "Credit Risk Profile")
    _add_kv(pdf, "Credit Risk Score", f"{_safe_float(facts.get('credit_risk_score', 0)) * 100:.1f}%")
    _add_kv(pdf, "Credit Risk Band", facts.get("credit_risk_band", "Unknown"))
    _add_kv(pdf, "Credit Utilization", f"{_safe_float(facts.get('credit_utilization', 0)) * 100:.1f}%")
    _add_kv(pdf, "Overdue Ratio", f"{_safe_float(facts.get('overdue_ratio', 0)) * 100:.1f}%")
    _add_kv(pdf, "Outstanding Amount", f"Rs {_safe_int(facts.get('outstanding_amount', 0)):,}")
    _add_kv(pdf, "Credit Adj. Risk Value", f"Rs {_safe_int(facts.get('credit_adjusted_risk_value', 0)):,}")
    pdf.ln(3)

    # --- Alerts ---
    if alerts:
        _add_section(pdf, "Active Alerts")
        for a in alerts:
            sev = str(a.get("severity", "medium")).upper()
            pdf.set_font("Helvetica", "B", 9)
            pdf.cell(20, 5, f"[{sev}]")
            pdf.set_font("Helvetica", "", 9)
            pdf.cell(0, 5, _sanitize(f"{a.get('title', 'Alert')}: {a.get('message', '')}"), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)

    # --- Playbook ---
    if playbook:
        _add_section(pdf, "Segment Playbook")
        _add_kv(pdf, "Priority", playbook.get("priority", "Normal"))
        _add_kv(pdf, "Next Best Action", playbook.get("next_best_action", "N/A"))
        actions = playbook.get("actions", []) or []
        for idx, act in enumerate(actions, 1):
            pdf.cell(0, 5, _sanitize(f"  {idx}. {act}"), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)

    # --- Peer Gap Analysis ---
    if gaps is not None and not gaps.empty:
        _add_section(pdf, "Peer Gap Analysis")
        gap_cols = ["Product", "Potential_Revenue_Monthly", "Potential_Revenue_Yearly",
                     "You_Do_Pct", "Others_Do_Pct", "Peer_Avg_Spend"]
        show_cols = [c for c in gap_cols if c in gaps.columns]
        _add_table(pdf, gaps[show_cols])

    buf = io.BytesIO()
    pdf.output(buf)
    return buf.getvalue()


def export_partner_360_excel(partner_name: str, report: dict) -> bytes:
    """Generate a Partner 360 Excel workbook and return raw bytes."""
    facts = report.get("facts", {})
    gaps = report.get("gaps", pd.DataFrame())
    alerts = report.get("alerts", []) or []
    playbook = report.get("playbook", {}) or {}

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        # Facts sheet
        facts_df = pd.DataFrame([
            {"Metric": k, "Value": str(v)} for k, v in facts.items()
        ])
        facts_df.to_excel(writer, sheet_name="Partner Facts", index=False)

        # Peer gaps sheet
        if gaps is not None and not gaps.empty:
            gaps.to_excel(writer, sheet_name="Peer Gap Analysis", index=False)

        # Alerts sheet
        if alerts:
            alert_df = pd.DataFrame(alerts)
            alert_df.to_excel(writer, sheet_name="Alerts", index=False)

        # Playbook sheet
        if playbook:
            pb_rows = [{"Key": "Priority", "Value": playbook.get("priority", "")},
                       {"Key": "Next Best Action", "Value": playbook.get("next_best_action", "")}]
            for idx, a in enumerate(playbook.get("actions", []) or [], 1):
                pb_rows.append({"Key": f"Action {idx}", "Value": str(a)})
            pd.DataFrame(pb_rows).to_excel(writer, sheet_name="Playbook", index=False)

    return buf.getvalue()


# ---------------------------------------------------------------------------
# Public API — Recommendation Plan export
# ---------------------------------------------------------------------------

def export_recommendation_plan_pdf(partner_name: str, plan: dict) -> bytes:
    """Generate a Recommendation Plan PDF and return raw bytes."""
    pdf = _ReportPDF(orientation="P", unit="mm", format="A4")
    pdf._title_text = "Recommendation Plan"
    pdf._subtitle_text = f"Partner: {partner_name}  |  Generated: {datetime.now():%Y-%m-%d %H:%M}"
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    _add_section(pdf, "Recommendation Overview")
    _add_kv(pdf, "Partner", plan.get("partner_name", partner_name))
    _add_kv(pdf, "Cluster", f"{plan.get('cluster_label', 'Unknown')} ({plan.get('cluster_type', 'Unknown')})")
    _add_kv(pdf, "Suggested Sequence", plan.get("sequence_summary", "N/A"))
    pdf.ln(3)

    actions = plan.get("actions", []) or []
    if actions:
        _add_section(pdf, "Top Recommended Actions")
        action_df = pd.DataFrame(actions)
        show_cols = [c for c in ["sequence", "action_type", "recommended_offer",
                                  "priority_score", "why_relevant", "suggested_sequence"]
                     if c in action_df.columns]
        if show_cols:
            _add_table(pdf, action_df[show_cols])
        pdf.ln(3)

    explanation = plan.get("plain_language_explanation", {}) or {}
    if explanation:
        _add_section(pdf, "Plain Language Explanation")
        summary = str(explanation.get("summary", "")).strip()
        if summary:
            pdf.set_font("Helvetica", "I", 10)
            pdf.multi_cell(0, 5, _sanitize(summary))
            pdf.set_font("Helvetica", "", 10)
        reasons = explanation.get("reasons", []) or []
        for idx, reason in enumerate(reasons, 1):
            pdf.cell(0, 5, _sanitize(f"  {idx}. {reason}"), new_x="LMARGIN", new_y="NEXT")
        signals = explanation.get("model_signals", {}) or {}
        if signals:
            pdf.ln(2)
            for k, v in signals.items():
                _add_kv(pdf, k, v)

    buf = io.BytesIO()
    pdf.output(buf)
    return buf.getvalue()


def export_recommendation_plan_excel(partner_name: str, plan: dict) -> bytes:
    """Generate a Recommendation Plan Excel workbook and return raw bytes."""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        overview = pd.DataFrame([{
            "Partner": plan.get("partner_name", partner_name),
            "Cluster": plan.get("cluster_label", "Unknown"),
            "Cluster Type": plan.get("cluster_type", "Unknown"),
            "Suggested Sequence": plan.get("sequence_summary", "N/A"),
        }])
        overview.to_excel(writer, sheet_name="Overview", index=False)

        actions = plan.get("actions", []) or []
        if actions:
            pd.DataFrame(actions).to_excel(writer, sheet_name="Actions", index=False)

        explanation = plan.get("plain_language_explanation", {}) or {}
        if explanation:
            rows = []
            if explanation.get("summary"):
                rows.append({"Item": "Summary", "Detail": explanation["summary"]})
            for idx, r in enumerate(explanation.get("reasons", []) or [], 1):
                rows.append({"Item": f"Reason {idx}", "Detail": r})
            for k, v in (explanation.get("model_signals", {}) or {}).items():
                rows.append({"Item": f"Signal: {k}", "Detail": str(v)})
            if rows:
                pd.DataFrame(rows).to_excel(writer, sheet_name="Explanation", index=False)

    return buf.getvalue()


# ---------------------------------------------------------------------------
# Public API — Cluster Summary export
# ---------------------------------------------------------------------------

def export_cluster_summary_pdf(matrix: pd.DataFrame, quality_report: dict | None = None,
                                business_report: dict | None = None) -> bytes:
    """Generate a Cluster Summary PDF and return raw bytes."""
    pdf = _ReportPDF(orientation="L", unit="mm", format="A4")
    pdf._title_text = "Cluster Intelligence Summary"
    pdf._subtitle_text = f"Generated: {datetime.now():%Y-%m-%d %H:%M}"
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    if matrix is not None and not matrix.empty:
        # Cluster distribution
        _add_section(pdf, "Cluster Distribution")
        dist = matrix.groupby(["cluster_type", "cluster_label"]).size().reset_index(name="partner_count")
        dist = dist.sort_values(["cluster_type", "partner_count"], ascending=[True, False])
        _add_table(pdf, dist)
        pdf.ln(5)

        # Strategic tag breakdown
        if "strategic_tag" in matrix.columns:
            _add_section(pdf, "Strategic Tag Breakdown")
            tag_dist = matrix.groupby(["cluster_label", "strategic_tag"]).size().reset_index(name="count")
            _add_table(pdf, tag_dist)
            pdf.ln(5)

    if quality_report and quality_report.get("status") == "ok":
        _add_section(pdf, "Cluster Quality Metrics")
        _add_kv(pdf, "Outlier Ratio", f"{float(quality_report.get('outlier_ratio', 0)) * 100:.1f}%")
        _add_kv(pdf, "Cluster Entropy", f"{float(quality_report.get('cluster_entropy', 0)):.3f}")
        _add_kv(pdf, "Largest Cluster", str(quality_report.get("largest_cluster_size", 0)))
        _add_kv(pdf, "Smallest Cluster", str(quality_report.get("smallest_cluster_size", 0)))
        gate = quality_report.get("quality_gate", {})
        _add_kv(pdf, "Approved", str(gate.get("approved", "N/A")))
        _add_kv(pdf, "Reason", str(gate.get("reason", "N/A")))
        pdf.ln(5)

    if business_report and business_report.get("status") == "ok":
        _add_section(pdf, "Business Validation")
        comp = business_report.get("comparison", {})
        for strat_name in ["cluster_guided", "top_revenue_baseline", "random_baseline"]:
            strat = comp.get(strat_name, {})
            if strat:
                pdf.set_font("Helvetica", "B", 9)
                pdf.cell(0, 6, f"  {strat_name.replace('_', ' ').title()}", new_x="LMARGIN", new_y="NEXT")
                pdf.set_font("Helvetica", "", 9)
                for k, v in strat.items():
                    pdf.cell(0, 5, _sanitize(f"    {k}: {v}"), new_x="LMARGIN", new_y="NEXT")
        kpis = business_report.get("cluster_kpis", [])
        if kpis:
            pdf.ln(3)
            _add_section(pdf, "Cluster KPIs")
            _add_table(pdf, pd.DataFrame(kpis))

    buf = io.BytesIO()
    pdf.output(buf)
    return buf.getvalue()


def export_cluster_summary_excel(matrix: pd.DataFrame, quality_report: dict | None = None,
                                  business_report: dict | None = None) -> bytes:
    """Generate a Cluster Summary Excel workbook and return raw bytes."""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        if matrix is not None and not matrix.empty:
            # Full partner-cluster mapping
            export_cols = ["cluster", "cluster_label", "cluster_type", "strategic_tag"]
            export_cols = [c for c in export_cols if c in matrix.columns]
            if export_cols:
                matrix[export_cols].to_excel(writer, sheet_name="Partner Clusters")

            # Distribution summary
            dist = matrix.groupby(["cluster_type", "cluster_label"]).size().reset_index(name="partner_count")
            dist.to_excel(writer, sheet_name="Distribution", index=False)

        if quality_report and quality_report.get("status") == "ok":
            q_rows = [{"Metric": k, "Value": str(v)} for k, v in quality_report.items()
                       if k not in ("vip_summary", "growth_summary", "feature_report", "tiering")]
            if q_rows:
                pd.DataFrame(q_rows).to_excel(writer, sheet_name="Quality Report", index=False)

        if business_report and business_report.get("status") == "ok":
            kpis = business_report.get("cluster_kpis", [])
            if kpis:
                pd.DataFrame(kpis).to_excel(writer, sheet_name="Business KPIs", index=False)

    return buf.getvalue()
