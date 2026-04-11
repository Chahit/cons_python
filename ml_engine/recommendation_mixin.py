import json
import os
import re
from urllib import error, request

import numpy as np
import pandas as pd
from sqlalchemy import text


class RecommendationMixin:
    @staticmethod
    def _fmt_money(value):
        try:
            return f"Rs {int(float(value)):,}"
        except Exception:
            return "Rs 0"

    @staticmethod
    def _fmt_pct(value, digits=1):
        try:
            return f"{float(value):.{int(digits)}f}%"
        except Exception:
            return "0.0%"

    def _gemini_model_candidates(self, primary_model):
        primary = str(
            primary_model or os.getenv("OPENAI_MODEL", "gpt-4o") or ""
        ).strip()
        env_fallbacks = str(getattr(self, "gemini_model_fallbacks", "") or "").strip()
        custom = [m.strip() for m in env_fallbacks.split(",") if m.strip()]
        defaults = [
            "gemini-3-flash",
            "gemini-2.5-flash",
            "gemini-2.5-pro",
            "gemini-2.0-flash",
            "gemini-2.0-flash-lite",
            "gemini-1.5-flash-latest",
            "gemini-1.5-pro-latest",
            "gemini-1.5-flash",
        ]
        ordered = [primary] + custom + defaults
        seen = set()
        out = []
        for m in ordered:
            if not m:
                continue
            k = m.casefold()
            if k in seen:
                continue
            seen.add(k)
            out.append(m)
        return out

    def _build_partner_actions(
        self,
        report,
        partner_name=None,
        include_bundle_actions=False,
    ):
        facts = report.get("facts", pd.Series(dtype=float))
        gaps = report.get("gaps", pd.DataFrame())
        cluster_label = str(report.get("cluster_label", "Unknown"))
        cluster_type = str(report.get("cluster_type", "Unknown"))
        alerts = report.get("alerts", []) or []

        health_segment = str(facts.get("health_segment", "Unknown"))
        health_status = str(facts.get("health_status", "Unknown"))
        drop_pct = float(facts.get("revenue_drop_pct", 0.0) or 0.0)
        churn_prob = float(facts.get("churn_probability", 0.0) or 0.0)
        credit_risk = float(facts.get("credit_risk_score", 0.0) or 0.0)
        est_monthly_loss = float(facts.get("estimated_monthly_loss", 0.0) or 0.0)
        pitch = str(facts.get("top_affinity_pitch", "N/A"))

        actions = []

        if include_bundle_actions and partner_name:
            try:
                bundle = self.get_partner_bundle_recommendations(
                    partner_name=partner_name,
                    min_confidence=self.default_min_confidence,
                    min_lift=self.default_min_lift,
                    min_support=self.default_min_support,
                    include_low_support=self.default_include_low_support,
                    top_n=1,
                )
            except Exception:
                bundle = pd.DataFrame()
            if bundle is not None and not bundle.empty:
                b = bundle.iloc[0]
                rec_product = str(b.get("recommended_product", "")).strip()
                conf = float(b.get("confidence", 0.0) or 0.0)
                lift = float(b.get("lift", 0.0) or 0.0)
                margin_m = float(b.get("expected_margin_monthly", 0.0) or 0.0)
                gain_m = float(b.get("expected_gain_monthly", 0.0) or 0.0)
                if rec_product and (conf >= 0.10 or lift >= 1.1):
                    score = (
                        58.0
                        + min(16.0, conf * 30.0)
                        + min(8.0, max(0.0, lift - 1.0) * 8.0)
                        + min(14.0, max(margin_m, gain_m) / 25000.0)
                    )
                    actions.append(
                        {
                            "action_type": "Affinity Bundle",
                            "recommended_offer": rec_product,
                            "priority_score": round(float(score), 2),
                            "why_relevant": (
                                f"Association signal is strong for {rec_product}: "
                                f"confidence {conf:.2f}, lift {lift:.2f}, "
                                f"expected monthly upside {self._fmt_money(max(gain_m, margin_m))}."
                            ),
                            "suggested_sequence": (
                                "Pitch this affinity bundle first, then follow with peer-gap category expansion."
                            ),
                        }
                    )

        if not gaps.empty:
            gap_col = (
                "Potential_Revenue_Monthly"
                if "Potential_Revenue_Monthly" in gaps.columns
                else ("Potential_Revenue" if "Potential_Revenue" in gaps.columns else None)
            )
            if gap_col is not None:
                gap_sorted = gaps.sort_values(by=gap_col, ascending=False).head(1)
                if not gap_sorted.empty:
                    top_gap = gap_sorted.iloc[0]
                    gap_product = str(top_gap.get("Product", "Gap Category"))
                    gap_monthly = float(top_gap.get(gap_col, 0.0) or 0.0)

                    # ── Lifecycle weighting ──────────────────────────────
                    lifecycle_stage = ""
                    lifecycle_boost = 0.0
                    try:
                        pf_lc = getattr(self, "df_product_lifecycle", None)
                        if pf_lc is not None and not pf_lc.empty:
                            prod_row = pf_lc[
                                pf_lc["product_name"].astype(str).str.lower()
                                == gap_product.lower()
                            ]
                            if not prod_row.empty:
                                lifecycle_stage = str(
                                    prod_row.iloc[0].get("lifecycle_stage", "")
                                )
                                if lifecycle_stage.lower() in {"star", "growth"}:
                                    lifecycle_boost = 0.30  # +30% for star/growth products
                                elif lifecycle_stage.lower() in {"declining", "eol", "end-of-life"}:
                                    lifecycle_boost = -0.20  # -20% for declining/EOL
                    except Exception:
                        pass

                    why = [
                        f"Peer gap exists in {gap_product}.",
                        f"Estimated monthly upside {self._fmt_money(gap_monthly)}.",
                        f"Partner cluster {cluster_label} typically buys this category.",
                    ]
                    if lifecycle_stage:
                        why.append(f"Product lifecycle stage: {lifecycle_stage}.")

                    offer = pitch if pitch not in ("N/A", "None", "") else gap_product
                    base_score = 55.0 + min(25.0, gap_monthly / 100000.0)
                    if cluster_type == "VIP":
                        base_score += 5.0
                    score = base_score * (1.0 + lifecycle_boost)
                    actions.append(
                        {
                            "action_type": "Cross-sell Upsell",
                            "recommended_offer": offer,
                            "priority_score": round(float(score), 2),
                            "lifecycle_stage": lifecycle_stage or "Unknown",
                            "why_relevant": " | ".join(why),
                            "suggested_sequence": (
                                "Start with highest monthly gap category, then add complementary bundle item."
                            ),
                        }
                    )

        risk_signal = (
            health_segment in {"At Risk", "Critical"}
            or "Risk" in health_status
            or drop_pct >= float(getattr(self, "alert_revenue_drop_sharp_pct", 35.0))
            or churn_prob >= float(getattr(self, "alert_churn_high_level", 0.45))
        )
        if risk_signal:
            why = [
                f"Health segment={health_segment}, status={health_status}.",
                f"Revenue drop={drop_pct:.1f}%, churn={churn_prob * 100:.1f}%.",
                f"Estimated monthly leakage {self._fmt_money(est_monthly_loss)}.",
            ]
            score = 70.0 + min(20.0, est_monthly_loss / 100000.0) + (10.0 * churn_prob)
            actions.append(
                {
                    "action_type": "Retention Intervention",
                    "recommended_offer": "Recovery call + focused bundle + 14-day follow-up",
                    "priority_score": round(float(score), 2),
                    "why_relevant": " | ".join(why),
                    "suggested_sequence": (
                        "Do retention first, confirm blocker, then pitch one low-friction bundle."
                    ),
                }
            )

        high_credit = credit_risk >= float(getattr(self, "alert_credit_high_level", 0.55))
        if high_credit:
            why = [
                f"Credit risk is elevated at {credit_risk * 100:.1f}%.",
                "Protect collections and reduce exposure before aggressive growth push.",
                "Use safer terms and fast-moving SKUs.",
            ]
            score = 65.0 + min(25.0, 40.0 * credit_risk)
            actions.append(
                {
                    "action_type": "Credit-safe Action",
                    "recommended_offer": "Low-exposure SKUs + tighter payment terms",
                    "priority_score": round(float(score), 2),
                    "why_relevant": " | ".join(why),
                    "suggested_sequence": (
                        "Stabilize credit terms first, then proceed with high-probability demand items."
                    ),
                }
            )

        if cluster_type == "VIP" and health_segment in {"Champion", "Healthy"}:
            why = [
                "VIP partner with stable/growing health profile.",
                "Suitable for premium mix expansion and margin-focused growth.",
                f"Cluster context: {cluster_label}.",
            ]
            score = 52.0 + (8.0 if health_segment == "Champion" else 4.0)
            actions.append(
                {
                    "action_type": "Strategic Expansion",
                    "recommended_offer": "Premium portfolio expansion plan",
                    "priority_score": round(float(score), 2),
                    "why_relevant": " | ".join(why),
                    "suggested_sequence": (
                        "Pitch premium bundle after confirming quarterly volume commitment."
                    ),
                }
            )

        if alerts:
            severe = alerts[0]
            severity_weight = {"critical": 25.0, "high": 15.0, "medium": 8.0}
            sev = str(severe.get("severity", "medium")).lower()
            score = 75.0 + severity_weight.get(sev, 5.0)
            actions.append(
                {
                    "action_type": "Alert-led Escalation",
                    "recommended_offer": "Immediate manager escalation and recovery plan",
                    "priority_score": round(float(score), 2),
                    "why_relevant": str(severe.get("message", "Alert rule triggered.")),
                    "suggested_sequence": (
                        "Address alert root cause first, then resume growth recommendations."
                    ),
                }
            )

        if not actions:
            actions.append(
                {
                    "action_type": "Account Nurture",
                    "recommended_offer": "Regular follow-up and portfolio review",
                    "priority_score": 35.0,
                    "why_relevant": "No high-risk or high-gap trigger; maintain relationship and monitor movement.",
                    "suggested_sequence": "Run monthly review and refresh recommendations after next cycle.",
                }
            )

        dedup = {}
        for a in actions:
            key = str(a.get("action_type", "")).strip().lower()
            prev = dedup.get(key)
            if prev is None or float(a.get("priority_score", 0.0)) > float(
                prev.get("priority_score", 0.0)
            ):
                dedup[key] = a
        actions = list(dedup.values())
        for a in actions:
            a["priority_score"] = round(
                float(np.clip(float(a.get("priority_score", 0.0)), 0.0, 100.0)),
                2,
            )
        actions = sorted(actions, key=lambda x: float(x.get("priority_score", 0.0)), reverse=True)
        return actions

    def _build_sequence_text(self, actions):
        if not actions:
            return "No recommended sequence available."
        parts = []
        for i, a in enumerate(actions, start=1):
            parts.append(f"{i}) {a.get('action_type', 'Action')}")
        return " -> ".join(parts)

    def _build_plain_language_explanation(self, report, actions):
        facts = report.get("facts", pd.Series(dtype=float))
        gaps = report.get("gaps", pd.DataFrame())
        cluster_label = str(report.get("cluster_label", "peer cluster"))
        alerts = report.get("alerts", []) or []

        reasons = []
        model_signals = {}

        if gaps is not None and not gaps.empty:
            sort_col = (
                "Potential_Revenue_Monthly"
                if "Potential_Revenue_Monthly" in gaps.columns
                else ("Potential_Revenue" if "Potential_Revenue" in gaps.columns else None)
            )
            if sort_col is not None:
                top_gap = gaps.sort_values(by=sort_col, ascending=False).iloc[0]
                product = str(top_gap.get("Product", "target category"))
                monthly_gap = float(top_gap.get(sort_col, 0.0) or 0.0)
                you_do = float(top_gap.get("You_Do_Pct", 0.0) or 0.0)
                others_do = float(top_gap.get("Others_Do_Pct", 0.0) or 0.0)
                less_pct = max(others_do - you_do, 0.0)
                reasons.append(
                    f"This partner buys {self._fmt_pct(less_pct)} less {product} than similar {cluster_label} peers; expected monthly gap is {self._fmt_money(monthly_gap)}."
                )
                model_signals.update(
                    {
                        "top_gap_product": product,
                        "top_gap_monthly": round(monthly_gap, 2),
                        "you_do_pct": round(you_do, 2),
                        "others_do_pct": round(others_do, 2),
                        "peer_gap_delta_pct": round(less_pct, 2),
                    }
                )

        pitch = str(facts.get("top_affinity_pitch", "N/A"))
        pitch_conf = facts.get("pitch_confidence", np.nan)
        pitch_lift = facts.get("pitch_lift", np.nan)
        if pitch not in ("", "N/A", "None") and pd.notna(pitch_conf) and pd.notna(pitch_lift):
            conf = float(pitch_conf)
            lift = float(pitch_lift)
            conf_txt = f"{conf * 100:.1f}%" if conf <= 1.0 else f"{conf:.2f}"
            reasons.append(
                f"Cross-sell signal is strong: for related buyers, likelihood for {pitch} is lift {lift:.2f} with confidence {conf_txt}."
            )
            model_signals.update(
                {
                    "pitch_product": pitch,
                    "pitch_confidence": round(conf, 4),
                    "pitch_lift": round(lift, 4),
                }
            )

        churn = float(facts.get("churn_probability", 0.0) or 0.0)
        churn_band = str(facts.get("churn_risk_band", "Unknown"))
        risk_monthly = float(facts.get("expected_revenue_at_risk_monthly", 0.0) or 0.0)
        reasons.append(
            f"Churn risk is {self._fmt_pct(churn * 100.0)} ({churn_band}); estimated monthly revenue at risk is {self._fmt_money(risk_monthly)}."
        )
        model_signals.update(
            {
                "churn_probability": round(churn, 4),
                "churn_risk_band": churn_band,
                "expected_revenue_at_risk_monthly": round(risk_monthly, 2),
            }
        )

        credit = float(facts.get("credit_risk_score", 0.0) or 0.0)
        credit_band = str(facts.get("credit_risk_band", "Unknown"))
        reasons.append(
            f"Credit risk is {self._fmt_pct(credit * 100.0)} ({credit_band}), so offers should stay margin-safe and payment-safe."
        )
        model_signals.update(
            {
                "credit_risk_score": round(credit, 4),
                "credit_risk_band": credit_band,
            }
        )

        drop = float(facts.get("revenue_drop_pct", 0.0) or 0.0)
        if drop > 0:
            reasons.append(
                f"Revenue dropped by {self._fmt_pct(drop)} vs the prior baseline window, so intervention should be immediate."
            )
            model_signals["revenue_drop_pct"] = round(drop, 2)

        for a in alerts:
            code = str(a.get("code", "")).strip().lower()
            delta = a.get("delta", None)
            if code in {"high_churn_jump", "high_credit_risk_jump"} and delta is not None:
                delta_pct = float(delta) * 100.0
                label = "Churn" if code == "high_churn_jump" else "Credit risk"
                reasons.append(
                    f"{label} increased by {self._fmt_pct(delta_pct)} versus the previous snapshot."
                )
                model_signals[f"{code}_delta"] = round(float(delta), 4)
                break

        primary = actions[0] if actions else {}
        action_type = str(primary.get("action_type", "Account Nurture"))
        offer = str(primary.get("recommended_offer", "portfolio review"))
        score = float(primary.get("priority_score", 0.0) or 0.0)
        summary = (
            f"Top recommendation: {action_type} using '{offer}' (priority score {score:.1f}). "
            f"This is driven by peer-gap, affinity, churn, and risk signals."
        )

        return {
            "summary": summary,
            "reasons": reasons[:6],
            "model_signals": model_signals,
        }

    def _call_gemini_recommendation(self, prompt, api_key, model):
        """
        AI generation call — powered by OpenAI.
        Kept the same (text, error) return signature so all callers work unchanged.
        """
        openai_key = (
            getattr(self, "openai_api_key", None)
            or os.getenv("OPENAI_API_KEY", "")
            or str(api_key or "").strip()
        )
        # Bug fix: use self.openai_model (instance attribute) not raw os.getenv
        openai_model = (
            getattr(self, "openai_model", None)
            or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        )

        if not openai_key:
            return None, "OpenAI API key missing. Add OPENAI_API_KEY to your .env file."

        try:
            from openai import OpenAI
        except ImportError:
            return None, "`openai` package not installed. Run: pip install openai"

        try:
            client = OpenAI(api_key=openai_key)
            response = client.chat.completions.create(
                model=openai_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=700,
            )
            text = response.choices[0].message.content.strip()
            self._last_gemini_model_used = openai_model
            return text, None
        except Exception as e:
            return None, f"OpenAI API error: {str(e)}"


    @staticmethod
    def _normalize_tone(tone):
        t = str(tone or "").strip().lower()
        if t in {"formal", "friendly", "urgent"}:
            return t
        return "formal"

    def _default_nl_query_filters(self, top_n=20):
        return {
            "state": None,
            "cluster_type": None,
            "cluster_label_contains": None,
            "credit_risk_max": None,
            "credit_risk_min": None,
            "churn_probability_max": None,
            "churn_probability_min": None,
            "health_segments": [],
            "margin_rate_min": None,
            "action_type_contains": None,
            "offer_contains": None,
            "top_n": int(max(1, int(top_n))),
        }

    def _merge_nl_filters(self, base_filters, patch_filters):
        merged = dict(base_filters)
        if not isinstance(patch_filters, dict):
            return merged
        for k, v in patch_filters.items():
            if k not in merged:
                continue
            if v is None:
                continue
            if k == "health_segments":
                if isinstance(v, list):
                    merged[k] = [str(x).strip() for x in v if str(x).strip()]
                elif str(v).strip():
                    merged[k] = [str(v).strip()]
            elif k == "top_n":
                try:
                    merged[k] = int(max(1, int(v)))
                except Exception:
                    pass
            elif k in {
                "credit_risk_max",
                "credit_risk_min",
                "churn_probability_max",
                "churn_probability_min",
                "margin_rate_min",
            }:
                try:
                    merged[k] = float(v)
                except Exception:
                    pass
            else:
                s = str(v).strip()
                merged[k] = s if s else None
        return merged

    def _heuristic_parse_nl_query(self, query, top_n=20):
        q = str(query or "").strip().lower()
        filters = self._default_nl_query_filters(top_n=top_n)
        if not q:
            return filters

        if "vip" in q:
            filters["cluster_type"] = "VIP"
        if "outlier" in q:
            filters["cluster_label_contains"] = "Outlier"

        if "low-credit-risk" in q or "low credit risk" in q:
            filters["credit_risk_max"] = float(getattr(self, "credit_risk_medium", 0.40))
        if "high-credit-risk" in q or "high credit risk" in q:
            filters["credit_risk_min"] = float(getattr(self, "credit_risk_high", 0.67))

        if "low churn" in q or "low-churn" in q:
            filters["churn_probability_max"] = float(getattr(self, "churn_prob_medium", 0.35))
        if "high churn" in q or "high-churn" in q:
            filters["churn_probability_min"] = float(getattr(self, "churn_prob_high", 0.65))

        if "high-margin" in q or "high margin" in q:
            filters["margin_rate_min"] = 0.18
        elif "margin-safe" in q or "margin safe" in q:
            filters["margin_rate_min"] = 0.12

        if "cross-sell" in q or "upsell" in q:
            filters["action_type_contains"] = "Cross-sell"
        elif "retention" in q:
            filters["action_type_contains"] = "Retention"
        elif "credit-safe" in q or "credit safe" in q:
            filters["action_type_contains"] = "Credit-safe"

        health_map = {
            "champion": "Champion",
            "healthy": "Healthy",
            "at risk": "At Risk",
            "critical": "Critical",
        }
        hs = []
        for token, label in health_map.items():
            if token in q:
                hs.append(label)
        if hs:
            filters["health_segments"] = hs

        state = None
        try:
            if self.matrix is not None and "state" in self.matrix.columns:
                states = sorted(
                    [str(s).strip() for s in self.matrix["state"].dropna().unique().tolist() if str(s).strip()]
                )
                q_pad = f" {q} "
                for s in states:
                    s_l = s.lower()
                    if f" {s_l} " in q_pad:
                        state = s
                        break
                    if f"in {s_l}" in q_pad or f"for {s_l}" in q_pad:
                        state = s
                        break
        except Exception:
            state = None
        if state:
            filters["state"] = state

        m_top = re.search(r"\btop\s+(\d{1,3})\b", q)
        if m_top:
            filters["top_n"] = int(max(1, min(200, int(m_top.group(1)))))
        else:
            m_limit = re.search(r"\b(?:show|list|give)\s+(\d{1,3})\b", q)
            if m_limit:
                filters["top_n"] = int(max(1, min(200, int(m_limit.group(1)))))
        return filters

    def _parse_nl_query_with_genai(self, query, api_key, model, top_n=20):
        prompt = (
            "Convert a natural-language sales recommendation query into strict JSON filters.\n"
            "Return only one JSON object with keys:\n"
            "state, cluster_type, cluster_label_contains, credit_risk_max, credit_risk_min, "
            "churn_probability_max, churn_probability_min, health_segments, margin_rate_min, "
            "action_type_contains, offer_contains, top_n.\n"
            "Rules:\n"
            "- Use null when not specified.\n"
            "- Keep numeric filters between 0 and 1 where applicable.\n"
            "- health_segments must be an array from: Champion, Healthy, At Risk, Critical.\n"
            "- top_n should be integer.\n\n"
            f"Query: {str(query)}"
        )
        text_out, err = self._call_gemini_recommendation(
            prompt=prompt,
            api_key=str(api_key),
            model=str(model),
        )
        if err or not text_out:
            return None, err or "Empty Gemini response."

        raw = str(text_out).strip()
        start = raw.find("{")
        end = raw.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None, "Gemini did not return JSON object."
        try:
            parsed = json.loads(raw[start : end + 1])
            return parsed, None
        except Exception as e:
            return None, f"Gemini JSON parse failed: {str(e)}"

    def _build_structured_filters_from_nl(
        self,
        query,
        top_n=20,
        use_genai=False,
        api_key=None,
        model=None,
    ):
        base = self._heuristic_parse_nl_query(query=query, top_n=top_n)
        parser_meta = {"mode": "heuristic", "genai_error": None}
        if use_genai:
            key = str(api_key or getattr(self, "openai_api_key", "") or "").strip()
            gm = str(model or os.getenv("OPENAI_MODEL", "gpt-4o")).strip()
            if key:
                parsed, err = self._parse_nl_query_with_genai(
                    query=query,
                    api_key=key,
                    model=gm,
                    top_n=top_n,
                )
                parser_meta["mode"] = "genai+heuristic"
                parser_meta["genai_error"] = err
                if isinstance(parsed, dict):
                    base = self._merge_nl_filters(base, parsed)
            else:
                parser_meta["mode"] = "heuristic"
                parser_meta["genai_error"] = (
                    "Gemini API key missing; fallback parser used."
                )
        return base, parser_meta

    @staticmethod
    def _action_matches_filters(action, filters):
        action_type = str(action.get("action_type", ""))
        offer = str(action.get("recommended_offer", ""))
        atc = filters.get("action_type_contains")
        if atc and atc.lower() not in action_type.lower():
            return False
        oc = filters.get("offer_contains")
        if oc and oc.lower() not in offer.lower():
            return False
        return True

    @staticmethod
    def _partner_matches_filters(report, filters):
        if not isinstance(report, dict):
            return False
        cluster_type = str(report.get("cluster_type", ""))
        cluster_label = str(report.get("cluster_label", ""))
        f_cluster_type = filters.get("cluster_type")
        if f_cluster_type and cluster_type.lower() != str(f_cluster_type).lower():
            return False

        f_cluster_label = filters.get("cluster_label_contains")
        if f_cluster_label and str(f_cluster_label).lower() not in cluster_label.lower():
            return False

        facts = report.get("facts", pd.Series(dtype=float))
        credit = float(facts.get("credit_risk_score", 0.0) or 0.0)
        churn = float(facts.get("churn_probability", 0.0) or 0.0)
        seg = str(facts.get("health_segment", "Unknown"))

        cmax = filters.get("credit_risk_max")
        cmin = filters.get("credit_risk_min")
        if cmax is not None and credit > float(cmax):
            return False
        if cmin is not None and credit < float(cmin):
            return False

        hmax = filters.get("churn_probability_max")
        hmin = filters.get("churn_probability_min")
        if hmax is not None and churn > float(hmax):
            return False
        if hmin is not None and churn < float(hmin):
            return False

        allowed_seg = filters.get("health_segments") or []
        if allowed_seg and seg not in set(allowed_seg):
            return False
        return True

    def query_recommendations_nl(
        self,
        query,
        state_scope=None,
        top_n=20,
        use_genai=False,
        api_key=None,
        model=None,
    ):
        self.ensure_clustering()
        self.ensure_churn_forecast()
        self.ensure_credit_risk()
        self.ensure_associations()

        if self.matrix is None or self.matrix.empty:
            return {
                "status": "failed",
                "reason": "Partner matrix unavailable.",
            }

        filters, parser_meta = self._build_structured_filters_from_nl(
            query=query,
            top_n=top_n,
            use_genai=use_genai,
            api_key=api_key,
            model=model,
        )

        candidates = self.matrix.copy()
        query_state = filters.get("state")
        active_state = query_state if query_state else (str(state_scope).strip() if state_scope else None)
        if active_state and "state" in candidates.columns:
            candidates = candidates[candidates["state"].astype(str) == str(active_state)]

        if filters.get("cluster_type") and "cluster_type" in candidates.columns:
            candidates = candidates[
                candidates["cluster_type"].astype(str).str.lower()
                == str(filters["cluster_type"]).lower()
            ]

        partner_names = candidates.index.tolist()
        max_partners = int(
            max(
                20,
                min(
                    int(getattr(self, "nl_query_partner_scan_limit", 300)),
                    len(partner_names),
                ),
            )
        )
        partner_names = partner_names[:max_partners]

        rows = []
        price_cache = {}
        for partner in partner_names:
            report = self.get_partner_intelligence(partner)
            if not self._partner_matches_filters(report, filters):
                continue

            facts = report.get("facts", pd.Series(dtype=float))
            actions = self._build_partner_actions(report, partner_name=partner, include_bundle_actions=False)
            for action in actions[:3]:
                if not self._action_matches_filters(action, filters):
                    continue
                offer = str(action.get("recommended_offer", "Recommended Offer")).strip()
                key = offer.lower()
                if key not in price_cache:
                    price_cache[key] = self._lookup_offer_pricing(offer)
                pricing = price_cache[key]
                margin_rate = float(pricing.get("margin_rate", 0.0) or 0.0)
                margin_min = filters.get("margin_rate_min")
                if margin_min is not None and margin_rate < float(margin_min):
                    continue

                rows.append(
                    {
                        "partner_name": str(partner),
                        "state": str(self.matrix.loc[partner, "state"])
                        if "state" in self.matrix.columns
                        else "Unknown",
                        "cluster_label": str(report.get("cluster_label", "Unknown")),
                        "cluster_type": str(report.get("cluster_type", "Unknown")),
                        "health_segment": str(facts.get("health_segment", "Unknown")),
                        "churn_probability": float(facts.get("churn_probability", 0.0) or 0.0),
                        "credit_risk_score": float(facts.get("credit_risk_score", 0.0) or 0.0),
                        "action_type": str(action.get("action_type", "Action")),
                        "recommended_offer": offer,
                        "priority_score": float(action.get("priority_score", 0.0) or 0.0),
                        "margin_rate": margin_rate,
                        "safe_discount_pct": float(pricing.get("safe_discount_pct", 0.0) or 0.0),
                        "why_relevant": str(action.get("why_relevant", "")),
                    }
                )

        results = pd.DataFrame(rows)
        if not results.empty:
            q_lower = str(query or "").lower()
            if "margin" in q_lower:
                results = results.sort_values(
                    by=["margin_rate", "priority_score", "churn_probability"],
                    ascending=[False, False, True],
                )
            else:
                results = results.sort_values(
                    by=["priority_score", "margin_rate", "churn_probability"],
                    ascending=[False, False, True],
                )
            results = results.reset_index(drop=True)

        limit_n = int(max(1, min(200, int(filters.get("top_n", top_n)))))
        results_top = results.head(limit_n) if not results.empty else results

        return {
            "status": "ok",
            "query": str(query),
            "parser": parser_meta,
            "filters": filters,
            "results": results_top,
            "total_matches": int(len(results)),
            "scanned_partners": int(len(partner_names)),
            "candidate_partners": int(len(candidates)),
        }

    def _lookup_offer_pricing(self, offer, partner_name=None):
        if not offer or not self.engine:
            return {
                "offer_name": offer or "Unknown",
                "unit_price": np.nan,
                "margin_rate": 0.15,
                "safe_discount_pct": 0.0,
                "offer_price": np.nan,
                "elasticity_signal": "Unknown",
            }

        # Modify SQL to fetch basic price/margin + elasticity metrics via Materialized View
        query = text(
            """
            WITH max_date_cte AS (
                SELECT MAX(date)::date AS last_recorded_date
                FROM transactions_dsr t
                WHERE {approved}
            )
            SELECT
                AVG(
                    CASE
                        WHEN COALESCE(tp.qty, 0) <> 0 THEN (tp.net_amt::double precision / tp.qty::double precision)
                        ELSE NULL
                    END
                ) AS avg_unit_selling_price,
                AVG(
                    CASE
                        WHEN COALESCE(tp.net_amt, 0) > 0 THEN
                            GREATEST(
                                tp.net_amt
                                - (
                                    COALESCE(NULLIF(tp.transfer_price, 0), COALESCE(msp.transfer_price, 0))
                                    * COALESCE(NULLIF(tp.qty, 0), 1)
                                ),
                                0
                            )::double precision / tp.net_amt::double precision
                        ELSE NULL
                    END
                ) AS avg_margin_rate,
                AVG(COALESCE(NULLIF(tp.transfer_price, 0), msp.transfer_price)) AS avg_transfer_price,
                MAX(mv.volume_cv) as volume_cv,
                MAX(mv.price_cv) as price_cv
            FROM transactions_dsr t
            JOIN transactions_dsr_products tp ON t.id = tp.dsr_id
            JOIN master_products p ON tp.product_id = p.id
            LEFT JOIN mv_product_elasticity_stats mv 
                ON mv.product_name = p.product_name 
                AND mv.partner_name = :partner_name
            LEFT JOIN LATERAL (
                SELECT m.transfer_price
                FROM master_product_selling_price m
                WHERE m.product_id = tp.product_id
                ORDER BY m.formation_dt DESC NULLS LAST
                LIMIT 1
            ) msp ON TRUE
            CROSS JOIN max_date_cte md
            WHERE {approved}
              AND p.product_name = :offer_name
              AND t.date >= md.last_recorded_date - INTERVAL '180 days'
            """.format(
                approved=self._approved_condition("t")
            )
        )


        row = {}
        try:
            q = pd.read_sql(query, self.engine, params={"offer_name": offer, "partner_name": partner_name})
            if not q.empty:
                row = q.iloc[0].to_dict()
        except Exception:
            row = {}

        unit_price = float(row.get("avg_unit_selling_price", np.nan) or np.nan)
        if not np.isfinite(unit_price):
            tp = float(row.get("avg_transfer_price", np.nan) or np.nan)
            if np.isfinite(tp) and tp > 0:
                unit_price = tp * 1.18

        margin_rate = float(row.get("avg_margin_rate", np.nan) or np.nan)
        if not np.isfinite(margin_rate):
            margin_rate = 0.15
        margin_rate = float(np.clip(margin_rate, 0.02, 0.60))

        # Dynamic Price Elasticity of Demand (PED) Calculation
        # PED = % Change in Quantity / % Change in Price (approximated here via Coefficients of Variation)
        vol_cv = float(row.get("volume_cv", np.nan) or 0.0)
        price_cv = float(row.get("price_cv", np.nan) or 0.0)
        
        elasticity_score = 1.0 # Neutral assumption
        if pd.notna(vol_cv) and pd.notna(price_cv) and price_cv > 0.01:
            elasticity_score = vol_cv / price_cv

        # Determine strategy based on elasticity and ceiling the discount against absolute margin
        elasticity_signal = "Neutral Demand"
        if elasticity_score > 1.2:
            # Highly elastic: Demand spikes with price drops. Okay to offer higher discount to drive volume.
            elasticity_signal = "Highly Elastic (Maximize Discount)"
            safe_discount = min(15.0, margin_rate * 100 * 0.7) # Give up to 70% of margin
        elif elasticity_score < 0.8 and elasticity_score > 0.1:
            # Inelastic: Partner buys regardless of price. Protect the margin.
            elasticity_signal = "Inelastic (Hold Price)"
            safe_discount = 2.0 # Minimal discount just for relationship
        else:
            # Standard backoff based on margin
            safe_discount = min(8.0, margin_rate * 100 * 0.4)

        safe_discount = float(np.clip(safe_discount, 0.0, 100.0))

        offer_price = unit_price * (1.0 - safe_discount / 100.0) if np.isfinite(unit_price) else np.nan
        return {
            "offer_name": offer,
            "unit_price": float(unit_price) if np.isfinite(unit_price) else np.nan,
            "margin_rate": float(margin_rate),
            "safe_discount_pct": float(safe_discount),
            "offer_price": float(offer_price) if np.isfinite(offer_price) else np.nan,
            "elasticity_signal": elasticity_signal,
        }

    def _build_pitch_templates(self, partner_name, action, tone, pricing):
        tone_norm = self._normalize_tone(tone)
        offer_name = str(pricing.get("offer_name", action.get("recommended_offer", "Recommended Offer")))
        unit_price = pricing.get("unit_price", np.nan)
        offer_price = pricing.get("offer_price", np.nan)
        safe_discount = float(pricing.get("safe_discount_pct", 0.0) or 0.0)
        margin_rate = float(pricing.get("margin_rate", 0.15) or 0.15)
        action_type = str(action.get("action_type", "Recommended Action"))

        price_line = (
            f"Indicative unit price: Rs {int(unit_price):,}"
            if np.isfinite(unit_price)
            else "Indicative unit price: as per latest partner rate card"
        )
        offer_line = (
            f"Margin-safe offer: up to {safe_discount:.0f}% off (effective ~ Rs {int(offer_price):,}/unit)"
            if np.isfinite(offer_price)
            else f"Margin-safe offer: up to {safe_discount:.0f}% off"
        )
        margin_line = f"Protected margin band: ~{margin_rate * 100:.1f}%."

        if tone_norm == "friendly":
            wa_open = f"Hi {partner_name}, quick suggestion for your next order."
            email_open = f"Hi {partner_name},"
            cta = "Reply with quantity and I will block stock today."
        elif tone_norm == "urgent":
            wa_open = f"Hi {partner_name}, urgent opportunity for this cycle."
            email_open = f"Dear {partner_name},"
            cta = "Please confirm today so we can lock this offer and dispatch priority stock."
        else:
            wa_open = f"Dear {partner_name}, recommendation based on your current portfolio."
            email_open = f"Dear {partner_name},"
            cta = "Please confirm your preferred quantity and schedule for dispatch."

        whatsapp = (
            f"{wa_open}\n"
            f"Recommended: {offer_name} ({action_type}).\n"
            f"{price_line}.\n"
            f"{offer_line}.\n"
            f"{margin_line}\n"
            f"{cta}"
        )

        email_subject = f"{offer_name} recommendation for your next cycle"
        email_body = (
            f"{email_open}\n\n"
            f"We recommend {offer_name} as the next best action under '{action_type}'.\n"
            f"{price_line}.\n"
            f"{offer_line}.\n"
            f"{margin_line}\n\n"
            f"Reason: {action.get('why_relevant', 'Based on current buying signals and peer benchmarks.')}\n\n"
            f"Call to action: {cta}\n\n"
            "Regards,\nSales Team"
        )

        return {
            "tone": tone_norm,
            "whatsapp": whatsapp,
            "email_subject": email_subject,
            "email_body": email_body,
        }

    def get_partner_pitch_scripts(
        self,
        partner_name,
        action_sequence=1,
        tone="formal",
        use_genai=False,
        api_key=None,
        model=None,
    ):
        plan = self.get_partner_recommendation_plan(
            partner_name=partner_name,
            top_n=5,
            use_genai=False,
        )
        if not plan or plan.get("status") != "ok":
            return {"status": "failed", "reason": "Unable to build recommendation plan for script generation."}

        actions = plan.get("actions", []) or []
        if not actions:
            return {"status": "failed", "reason": "No recommendation actions available for this partner."}

        seq = max(1, int(action_sequence))
        selected = None
        for a in actions:
            if int(a.get("sequence", 0)) == seq:
                selected = a
                break
        if selected is None:
            selected = actions[0]

        offer_name = str(selected.get("recommended_offer", "Recommended Offer"))
        pricing = self._lookup_offer_pricing(offer_name)
        scripts = self._build_pitch_templates(
            partner_name=partner_name,
            action=selected,
            tone=tone,
            pricing=pricing,
        )

        out = {
            "status": "ok",
            "partner_name": partner_name,
            "selected_action": selected,
            "pricing": pricing,
            "scripts": scripts,
            "genai": None,
            "genai_error": None,
        }

        if use_genai:
            key = str(api_key or getattr(self, "openai_api_key", "") or "").strip()
            gm = str(model or os.getenv("OPENAI_MODEL", "gpt-4o")).strip()
            if not key:
                out["genai_error"] = "OpenAI API key missing. Add OPENAI_API_KEY to your .env file."
                return out

            prompt = (
                "Generate channel-specific B2B pitch drafts.\n"
                "Return exactly three sections:\n"
                "1) WhatsApp Draft\n"
                "2) Email Subject\n"
                "3) Email Body\n"
                "Requirements:\n"
                f"- Tone: {self._normalize_tone(tone)}\n"
                "- Include product/offer, price, margin-safe offer, CTA.\n"
                "- Keep WhatsApp short and practical.\n"
                "- Keep email professional and conversion-focused.\n\n"
                f"Partner: {partner_name}\n"
                f"Action: {json.dumps(selected, ensure_ascii=True)}\n"
                f"Pricing context: {json.dumps(pricing, ensure_ascii=True)}\n"
                f"Deterministic baseline drafts: {json.dumps(scripts, ensure_ascii=True)}\n"
            )
            text_out, err = self._call_gemini_recommendation(
                prompt=prompt,
                api_key=key,
                model=gm,
            )
            out["genai"] = text_out
            out["genai_error"] = err

        return out

    def _pick_alternate_offer(self, partner_name, primary_offer):
        primary = str(primary_offer or "").strip().lower()

        try:
            recos = self.get_partner_bundle_recommendations(
                partner_name=partner_name,
                min_confidence=self.default_min_confidence,
                min_lift=self.default_min_lift,
                min_support=self.default_min_support,
                include_low_support=self.default_include_low_support,
                top_n=10,
            )
        except Exception:
            recos = pd.DataFrame()

        if recos is not None and not recos.empty and "recommended_product" in recos.columns:
            for _, r in recos.iterrows():
                alt = str(r.get("recommended_product", "")).strip()
                if alt and alt.lower() != primary:
                    return {"alternate_offer": alt, "source": "bundle"}

        report = self.get_partner_intelligence(partner_name)
        if report and isinstance(report, dict):
            gaps = report.get("gaps", pd.DataFrame())
            if gaps is not None and not gaps.empty and "Product" in gaps.columns:
                for _, r in gaps.iterrows():
                    alt = str(r.get("Product", "")).strip()
                    if alt and alt.lower() != primary:
                        return {"alternate_offer": alt, "source": "peer_gap"}

        return {"alternate_offer": "", "source": "none"}

    def _build_followup_templates(
        self,
        partner_name,
        action,
        tone,
        pricing,
        no_conversion_days,
        alternate_offer,
        trial_qty,
    ):
        tone_norm = self._normalize_tone(tone)
        offer_name = str(pricing.get("offer_name", action.get("recommended_offer", "Recommended Offer")))
        alt = str(alternate_offer or "").strip()
        trial_qty = max(1, int(trial_qty))
        days = max(1, int(no_conversion_days))

        unit_price = pricing.get("unit_price", np.nan)
        offer_price = pricing.get("offer_price", np.nan)
        safe_discount = float(pricing.get("safe_discount_pct", 0.0) or 0.0)
        margin_rate = float(pricing.get("margin_rate", 0.15) or 0.15)

        if tone_norm == "friendly":
            hook = f"Hi {partner_name}, just checking back after {days} days on the previous suggestion."
            cta = f"If useful, we can start with a small trial of {trial_qty} units this week."
        elif tone_norm == "urgent":
            hook = f"Hi {partner_name}, following up after {days} days because this cycle window is closing."
            cta = f"Please confirm today for a trial order of {trial_qty} units and priority dispatch."
        else:
            hook = (
                f"Dear {partner_name}, this is a follow-up after {days} days regarding the prior recommendation."
            )
            cta = f"Kindly confirm whether we should initiate a trial order of {trial_qty} units."

        revised_hook = "Since there has been no conversion yet, we are proposing a lower-friction option."
        price_line = (
            f"Current offer for {offer_name}: up to {safe_discount:.0f}% off (approx. Rs {int(offer_price):,}/unit)."
            if np.isfinite(offer_price)
            else f"Current offer for {offer_name}: up to {safe_discount:.0f}% off."
        )
        if np.isfinite(unit_price):
            price_line = (
                f"List reference is around Rs {int(unit_price):,}/unit; "
                + price_line
            )
        margin_line = f"Margin-safe band maintained at ~{margin_rate * 100:.1f}%."

        alt_line = (
            f"Alternate bundle option: {alt}."
            if alt
            else "Alternate option: smaller trial quantity on the same recommended item."
        )

        whatsapp = (
            f"{hook}\n"
            f"{revised_hook}\n"
            f"{price_line}\n"
            f"{alt_line}\n"
            f"{margin_line}\n"
            f"{cta}"
        )

        email_subject = f"Follow-up on {offer_name} proposal - alternate option included"
        email_body = (
            f"{hook}\n\n"
            f"{revised_hook}\n"
            f"Primary recommendation: {offer_name}\n"
            f"{price_line}\n"
            f"{alt_line}\n"
            f"{margin_line}\n\n"
            f"Trial option: {trial_qty} units to validate movement before scaling.\n"
            f"Call to action: {cta}\n\n"
            "Regards,\nSales Team"
        )
        return {
            "tone": tone_norm,
            "whatsapp_followup": whatsapp,
            "email_subject_followup": email_subject,
            "email_body_followup": email_body,
        }

    def get_partner_followup_scripts(
        self,
        partner_name,
        action_sequence=1,
        tone="formal",
        no_conversion_days=7,
        trial_qty=5,
        use_genai=False,
        api_key=None,
        model=None,
    ):
        base = self.get_partner_pitch_scripts(
            partner_name=partner_name,
            action_sequence=action_sequence,
            tone=tone,
            use_genai=False,
        )
        if not base or base.get("status") != "ok":
            return {"status": "failed", "reason": "Unable to generate base pitch scripts for follow-up."}

        selected_action = base.get("selected_action", {}) or {}
        pricing = base.get("pricing", {}) or {}
        primary_offer = str(pricing.get("offer_name", selected_action.get("recommended_offer", "")))
        alt = self._pick_alternate_offer(partner_name=partner_name, primary_offer=primary_offer)
        followup = self._build_followup_templates(
            partner_name=partner_name,
            action=selected_action,
            tone=tone,
            pricing=pricing,
            no_conversion_days=int(no_conversion_days),
            alternate_offer=alt.get("alternate_offer", ""),
            trial_qty=int(trial_qty),
        )

        out = {
            "status": "ok",
            "partner_name": partner_name,
            "selected_action": selected_action,
            "pricing": pricing,
            "alternate_offer": alt.get("alternate_offer", ""),
            "alternate_source": alt.get("source", "none"),
            "followup": followup,
            "genai": None,
            "genai_error": None,
        }

        if use_genai:
            key = str(api_key or getattr(self, "openai_api_key", "") or "").strip()
            gm = str(model or os.getenv("OPENAI_MODEL", "gpt-4o")).strip()
            if not key:
                out["genai_error"] = "OpenAI API key missing. Add OPENAI_API_KEY to your .env file."
                return out

            prompt = (
                "Generate follow-up sales drafts after no conversion.\n"
                "Return exactly three sections:\n"
                "1) WhatsApp Follow-up\n"
                "2) Email Subject\n"
                "3) Email Body\n"
                "Requirements:\n"
                f"- Tone: {self._normalize_tone(tone)}\n"
                f"- No conversion for {int(no_conversion_days)} days.\n"
                "- Use revised hook and mention alternate bundle or smaller trial quantity.\n"
                "- Include product, price, margin-safe offer, and CTA.\n\n"
                f"Partner: {partner_name}\n"
                f"Selected action: {json.dumps(selected_action, ensure_ascii=True)}\n"
                f"Pricing context: {json.dumps(pricing, ensure_ascii=True)}\n"
                f"Alternate option: {json.dumps(alt, ensure_ascii=True)}\n"
                f"Deterministic follow-up drafts: {json.dumps(followup, ensure_ascii=True)}\n"
            )
            text_out, err = self._call_gemini_recommendation(
                prompt=prompt,
                api_key=key,
                model=gm,
            )
            out["genai"] = text_out
            out["genai_error"] = err

        return out

    def _ensure_recommendation_feedback_table(self):
        if getattr(self, "_feedback_table_ready", False):
            return
        ddl_table = text(
            """
            CREATE TABLE IF NOT EXISTS recommendation_feedback_events (
                id BIGSERIAL PRIMARY KEY,
                partner_name TEXT NOT NULL,
                cluster_label TEXT NULL,
                cluster_type TEXT NULL,
                action_type TEXT NOT NULL,
                recommended_offer TEXT NULL,
                action_sequence INT NULL,
                stage TEXT NOT NULL DEFAULT 'initial_pitch',
                channel TEXT NOT NULL DEFAULT 'whatsapp',
                tone TEXT NOT NULL DEFAULT 'formal',
                outcome TEXT NOT NULL,
                notes TEXT NULL,
                priority_score DOUBLE PRECISION NULL,
                confidence DOUBLE PRECISION NULL,
                lift DOUBLE PRECISION NULL,
                churn_probability DOUBLE PRECISION NULL,
                credit_risk_score DOUBLE PRECISION NULL,
                revenue_drop_pct DOUBLE PRECISION NULL,
                expected_revenue_at_risk_monthly DOUBLE PRECISION NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        ddl_idx_1 = text(
            """
            CREATE INDEX IF NOT EXISTS idx_reco_feedback_created_at
            ON recommendation_feedback_events (created_at DESC);
            """
        )
        ddl_idx_2 = text(
            """
            CREATE INDEX IF NOT EXISTS idx_reco_feedback_outcome_created
            ON recommendation_feedback_events (outcome, created_at DESC);
            """
        )
        ddl_idx_3 = text(
            """
            CREATE INDEX IF NOT EXISTS idx_reco_feedback_action_tone
            ON recommendation_feedback_events (action_type, tone);
            """
        )
        with self.engine.begin() as conn:
            conn.execute(ddl_table)
            conn.execute(ddl_idx_1)
            conn.execute(ddl_idx_2)
            conn.execute(ddl_idx_3)
        self._feedback_table_ready = True

    def record_recommendation_feedback(
        self,
        partner_name,
        action_sequence=1,
        outcome="accepted",
        stage="initial_pitch",
        channel="whatsapp",
        tone="formal",
        notes="",
    ):
        self._ensure_recommendation_feedback_table()

        outcome_norm = str(outcome or "").strip().lower()
        if outcome_norm not in {"accepted", "rejected", "won", "lost"}:
            return {
                "status": "failed",
                "reason": "Outcome must be one of: accepted, rejected, won, lost.",
            }

        stage_norm = str(stage or "").strip().lower()
        if stage_norm not in {"initial_pitch", "followup"}:
            stage_norm = "initial_pitch"

        channel_norm = str(channel or "").strip().lower()
        if channel_norm not in {"whatsapp", "email", "call", "in_person"}:
            channel_norm = "whatsapp"

        tone_norm = self._normalize_tone(tone)

        plan = self.get_partner_recommendation_plan(
            partner_name=partner_name,
            top_n=5,
            use_genai=False,
        )
        if not plan or plan.get("status") != "ok":
            return {"status": "failed", "reason": "Unable to load recommendation plan for feedback save."}

        actions = plan.get("actions", []) or []
        if not actions:
            return {"status": "failed", "reason": "No actions available to map feedback."}

        seq = max(1, int(action_sequence))
        selected = None
        for a in actions:
            if int(a.get("sequence", 0)) == seq:
                selected = a
                break
        if selected is None:
            selected = actions[0]

        report = self.get_partner_intelligence(partner_name) or {}
        facts = report.get("facts", pd.Series(dtype=float))
        cluster_label = str(report.get("cluster_label", "Unknown"))
        cluster_type = str(report.get("cluster_type", "Unknown"))

        def _to_float_or_none(v):
            try:
                if pd.isna(v):
                    return None
                return float(v)
            except Exception:
                return None

        query = text(
            """
            INSERT INTO recommendation_feedback_events (
                partner_name,
                cluster_label,
                cluster_type,
                action_type,
                recommended_offer,
                action_sequence,
                stage,
                channel,
                tone,
                outcome,
                notes,
                priority_score,
                confidence,
                lift,
                churn_probability,
                credit_risk_score,
                revenue_drop_pct,
                expected_revenue_at_risk_monthly
            )
            VALUES (
                :partner_name,
                :cluster_label,
                :cluster_type,
                :action_type,
                :recommended_offer,
                :action_sequence,
                :stage,
                :channel,
                :tone,
                :outcome,
                :notes,
                :priority_score,
                :confidence,
                :lift,
                :churn_probability,
                :credit_risk_score,
                :revenue_drop_pct,
                :expected_revenue_at_risk_monthly
            )
            RETURNING id
            """
        )
        with self.engine.begin() as conn:
            row = conn.execute(
                query,
                {
                    "partner_name": str(partner_name),
                    "cluster_label": cluster_label,
                    "cluster_type": cluster_type,
                    "action_type": str(selected.get("action_type", "Unknown")),
                    "recommended_offer": str(selected.get("recommended_offer", "")),
                    "action_sequence": int(selected.get("sequence", seq)),
                    "stage": stage_norm,
                    "channel": channel_norm,
                    "tone": tone_norm,
                    "outcome": outcome_norm,
                    "notes": str(notes or "")[:2000],
                    "priority_score": _to_float_or_none(selected.get("priority_score", None)),
                    "confidence": _to_float_or_none(facts.get("pitch_confidence", None)),
                    "lift": _to_float_or_none(facts.get("pitch_lift", None)),
                    "churn_probability": _to_float_or_none(facts.get("churn_probability", None)),
                    "credit_risk_score": _to_float_or_none(facts.get("credit_risk_score", None)),
                    "revenue_drop_pct": _to_float_or_none(facts.get("revenue_drop_pct", None)),
                    "expected_revenue_at_risk_monthly": _to_float_or_none(
                        facts.get("expected_revenue_at_risk_monthly", None)
                    ),
                },
            ).first()

        return {
            "status": "ok",
            "feedback_id": int(row[0]) if row else None,
            "partner_name": str(partner_name),
            "outcome": outcome_norm,
        }

    def _load_feedback_events(self, lookback_days=7):
        self._ensure_recommendation_feedback_table()
        days = max(1, int(lookback_days))
        query = text(
            """
            SELECT
                id,
                partner_name,
                cluster_label,
                cluster_type,
                action_type,
                recommended_offer,
                action_sequence,
                stage,
                channel,
                tone,
                outcome,
                notes,
                priority_score,
                confidence,
                lift,
                churn_probability,
                credit_risk_score,
                revenue_drop_pct,
                expected_revenue_at_risk_monthly,
                created_at
            FROM recommendation_feedback_events
            WHERE created_at >= NOW() - make_interval(days => :lookback_days)
            ORDER BY created_at DESC
            """
        )
        try:
            return pd.read_sql(query, self.engine, params={"lookback_days": days})
        except Exception:
            return pd.DataFrame()

    def get_weekly_feedback_learning_summary(
        self,
        lookback_days=7,
        use_genai=False,
        api_key=None,
        model=None,
    ):
        df = self._load_feedback_events(lookback_days=lookback_days)
        if df.empty:
            return {
                "status": "ok",
                "lookback_days": int(max(1, int(lookback_days))),
                "total_events": 0,
                "recommendation_type_performance": pd.DataFrame(),
                "messaging_style_performance": pd.DataFrame(),
                "summary_lines": [
                    "No feedback events captured in the selected window.",
                    "Save accepted/rejected/won/lost outcomes to activate learning insights.",
                ],
                "scoring_tuning": [],
                "genai": None,
                "genai_error": None,
            }

        df["outcome"] = df["outcome"].astype(str).str.lower().str.strip()
        df["tone"] = df["tone"].astype(str).str.lower().str.strip()
        df["channel"] = df["channel"].astype(str).str.lower().str.strip()
        for col in [
            "priority_score",
            "confidence",
            "lift",
            "churn_probability",
            "credit_risk_score",
            "revenue_drop_pct",
            "expected_revenue_at_risk_monthly",
        ]:
            df[col] = pd.to_numeric(df.get(col, np.nan), errors="coerce")

        positive = {"accepted", "won"}
        df["is_won"] = (df["outcome"] == "won").astype(int)
        df["is_positive"] = df["outcome"].isin(positive).astype(int)

        action_perf = (
            df.groupby("action_type", dropna=False)
            .agg(
                total=("id", "count"),
                won=("is_won", "sum"),
                positive=("is_positive", "sum"),
                avg_priority=("priority_score", "mean"),
                avg_churn=("churn_probability", "mean"),
                avg_credit=("credit_risk_score", "mean"),
            )
            .reset_index()
        )
        action_perf["win_rate"] = np.where(
            action_perf["total"] > 0, action_perf["won"] / action_perf["total"], 0.0
        )
        action_perf["positive_rate"] = np.where(
            action_perf["total"] > 0, action_perf["positive"] / action_perf["total"], 0.0
        )
        action_perf = action_perf.sort_values(by=["win_rate", "total"], ascending=[False, False])

        msg_perf = (
            df.groupby(["tone", "channel"], dropna=False)
            .agg(
                total=("id", "count"),
                won=("is_won", "sum"),
                positive=("is_positive", "sum"),
            )
            .reset_index()
        )
        msg_perf["win_rate"] = np.where(msg_perf["total"] > 0, msg_perf["won"] / msg_perf["total"], 0.0)
        msg_perf["positive_rate"] = np.where(
            msg_perf["total"] > 0, msg_perf["positive"] / msg_perf["total"], 0.0
        )
        msg_perf = msg_perf.sort_values(by=["win_rate", "total"], ascending=[False, False])

        total = int(len(df))
        overall_win_rate = float(df["is_won"].mean()) if total else 0.0
        best_action = action_perf.iloc[0] if not action_perf.empty else None
        best_style = msg_perf.iloc[0] if not msg_perf.empty else None

        summary_lines = [
            f"Captured {total} feedback events in the last {int(max(1, int(lookback_days)))} day(s).",
            f"Overall win rate is {overall_win_rate * 100:.1f}% and positive response rate is {float(df['is_positive'].mean()) * 100:.1f}%.",
        ]
        if best_action is not None:
            summary_lines.append(
                f"Best performing recommendation type: {best_action['action_type']} (win rate {float(best_action['win_rate']) * 100:.1f}% over {int(best_action['total'])} attempts)."
            )
        if best_style is not None:
            summary_lines.append(
                f"Best converting messaging style: {best_style['tone']} via {best_style['channel']} (win rate {float(best_style['win_rate']) * 100:.1f}%)."
            )

        scoring_tuning = []
        lost_df = df[df["outcome"].isin({"lost", "rejected"})]
        won_df = df[df["outcome"] == "won"]
        if not won_df.empty and not lost_df.empty:
            lost_churn = float(lost_df["churn_probability"].mean())
            won_churn = float(won_df["churn_probability"].mean())
            if np.isfinite(lost_churn) and np.isfinite(won_churn) and (lost_churn - won_churn) >= 0.08:
                scoring_tuning.append(
                    "Increase penalty on churn-heavy opportunities: lost/rejected cases carry materially higher churn probability than won deals."
                )

            lost_credit = float(lost_df["credit_risk_score"].mean())
            won_credit = float(won_df["credit_risk_score"].mean())
            if np.isfinite(lost_credit) and np.isfinite(won_credit) and (lost_credit - won_credit) >= 0.08:
                scoring_tuning.append(
                    "Increase credit-risk penalty in priority scoring: higher-credit-risk recommendations are converting worse."
                )

        high_priority = df[df["priority_score"] >= 70.0]
        if not high_priority.empty:
            hp_win = float(high_priority["is_won"].mean())
            if hp_win + 0.05 < overall_win_rate:
                scoring_tuning.append(
                    "Recalibrate high priority thresholds: high-scored actions are underperforming relative to portfolio average."
                )

        stage_perf = (
            df.groupby("stage", dropna=False)
            .agg(total=("id", "count"), win_rate=("is_won", "mean"))
            .reset_index()
        )
        if len(stage_perf) >= 2:
            stage_perf = stage_perf.sort_values(by="win_rate", ascending=False)
            top_stage = stage_perf.iloc[0]
            scoring_tuning.append(
                f"Execution signal: '{top_stage['stage']}' currently converts better ({float(top_stage['win_rate']) * 100:.1f}% win rate)."
            )

        if not scoring_tuning:
            scoring_tuning.append(
                "Collect more outcomes to tune scoring confidently; current sample is not yet strongly directional."
            )

        out = {
            "status": "ok",
            "lookback_days": int(max(1, int(lookback_days))),
            "total_events": total,
            "recommendation_type_performance": action_perf,
            "messaging_style_performance": msg_perf,
            "summary_lines": summary_lines,
            "scoring_tuning": scoring_tuning,
            "genai": None,
            "genai_error": None,
        }

        if use_genai:
            key = str(api_key or getattr(self, "openai_api_key", "") or "").strip()
            gm = str(model or os.getenv("OPENAI_MODEL", "gpt-4o")).strip()
            if not key:
                out["genai_error"] = "OpenAI API key missing. Add OPENAI_API_KEY to your .env file."
                return out

            prompt = (
                "You are a sales analytics copilot. Convert this weekly recommendation feedback summary into crisp business guidance.\n"
                "Return sections:\n"
                "1) Which recommendation types worked\n"
                "2) Which messaging style converted better\n"
                "3) What to tune in scoring\n"
                "Keep output practical and specific.\n\n"
                f"Lookback days: {out['lookback_days']}\n"
                f"Total events: {out['total_events']}\n"
                f"Deterministic summary lines: {json.dumps(summary_lines, ensure_ascii=True)}\n"
                f"Action performance (top 8): {json.dumps(action_perf.head(8).to_dict(orient='records'), ensure_ascii=True)}\n"
                f"Messaging performance (top 8): {json.dumps(msg_perf.head(8).to_dict(orient='records'), ensure_ascii=True)}\n"
                f"Tuning candidates: {json.dumps(scoring_tuning, ensure_ascii=True)}\n"
            )
            text_out, err = self._call_gemini_recommendation(
                prompt=prompt,
                api_key=key,
                model=gm,
            )
            out["genai"] = text_out
            out["genai_error"] = err

        return out

    def get_partner_recommendation_plan(
        self,
        partner_name,
        top_n=3,
        use_genai=False,
        api_key=None,
        model=None,
    ):
        self.ensure_clustering()
        self.ensure_churn_forecast()
        self.ensure_credit_risk()
        self.ensure_associations()

        report = self.get_partner_intelligence(partner_name)
        if not report:
            return {"status": "failed", "reason": "Partner intelligence unavailable."}

        actions = self._build_partner_actions(
            report,
            partner_name=partner_name,
            include_bundle_actions=True,
        )
        top_n = max(1, int(top_n))
        actions = actions[:top_n]
        for i, a in enumerate(actions, start=1):
            a["sequence"] = int(i)

        out = {
            "status": "ok",
            "partner_name": partner_name,
            "cluster_label": report.get("cluster_label", "Unknown"),
            "cluster_type": report.get("cluster_type", "Unknown"),
            "sequence_summary": self._build_sequence_text(actions),
            "actions": actions,
            "plain_language_explanation": self._build_plain_language_explanation(report, actions),
            "genai": None,
            "genai_error": None,
        }

        if use_genai:
            key = str(api_key or getattr(self, "openai_api_key", "") or "").strip()
            gm = str(model or os.getenv("OPENAI_MODEL", "gpt-4o")).strip()
            if not key:
                out["genai_error"] = "OpenAI API key missing. Add OPENAI_API_KEY to your .env file."
                return out

            facts = report.get("facts", pd.Series(dtype=float))
            gaps = report.get("gaps", pd.DataFrame())
            alerts = report.get("alerts", []) or []
            playbook = report.get("playbook", {}) or {}
            facts_payload = (
                facts.to_dict()
                if isinstance(facts, pd.Series)
                else dict(facts) if isinstance(facts, dict) else {}
            )
            gaps_payload = (
                gaps.head(20).to_dict(orient="records")
                if isinstance(gaps, pd.DataFrame) and not gaps.empty
                else []
            )
            prompt = (
                "You are a B2B sales copilot. Based on structured partner signals, write concise guidance.\n"
                "Return sections:\n"
                "1) Top 3 Recommended Actions\n"
                "2) Why each action is relevant\n"
                "3) Suggested execution sequence\n"
                "4) Risk controls and caveats\n"
                "Be specific, practical, and use numeric evidence where available.\n\n"
                f"Partner: {partner_name}\n"
                f"Cluster: {report.get('cluster_label', 'Unknown')} ({report.get('cluster_type', 'Unknown')})\n"
                f"Partner facts JSON: {json.dumps(facts_payload, ensure_ascii=True, default=str)}\n"
                f"Top gap rows JSON: {json.dumps(gaps_payload, ensure_ascii=True, default=str)}\n"
                f"Active alerts JSON: {json.dumps(alerts, ensure_ascii=True, default=str)}\n"
                f"Segment playbook JSON: {json.dumps(playbook, ensure_ascii=True, default=str)}\n"
                f"Deterministic recommendations JSON: {json.dumps(actions, ensure_ascii=True, default=str)}\n"
            )
            text, err = self._call_gemini_recommendation(prompt=prompt, api_key=key, model=gm)
            out["genai"] = text
            out["genai_error"] = err

        return out

    # =================================================================
    # UPGRADE (a): Collaborative Filtering — Partner-Similarity Recs
    # =================================================================

    def _build_collaborative_recommendations(self, partner_name, top_k=5):
        """
        Collaborative filtering: find partners with similar purchase patterns
        and recommend products that those peers buy but this partner doesn't.
        Uses cosine similarity on the purchase pivot matrix.
        """
        try:
            from sklearn.metrics.pairwise import cosine_similarity
        except ImportError:
            return []

        # Need the clustering pivot matrix. Keep only numeric spend columns.
        pivot_raw = getattr(self, "matrix_recent", None)
        if pivot_raw is None or pivot_raw.empty:
            return []
        if partner_name not in pivot_raw.index:
            return []
        pivot = pivot_raw.select_dtypes(include=[np.number]).copy()
        if pivot.empty:
            return []

        # Build binary purchase matrix
        binary_matrix = (pivot > 0).astype(float)
        partner_vec = binary_matrix.loc[[partner_name]]

        # Cosine similarity against all partners
        sim_scores = cosine_similarity(partner_vec, binary_matrix)[0]
        sim_series = pd.Series(sim_scores, index=binary_matrix.index)
        sim_series = sim_series.drop(partner_name, errors="ignore")

        # Top K most similar partners
        top_peers = sim_series.nlargest(int(max(1, top_k)))
        if top_peers.empty:
            return []
        peer_den = float(max(1, len(top_peers)))

        # Products bought by peers but NOT by this partner
        partner_products = set(binary_matrix.columns[binary_matrix.loc[partner_name] > 0])
        peer_products = {}
        for peer, sim in top_peers.items():
            peer_bought = set(binary_matrix.columns[binary_matrix.loc[peer] > 0])
            new_products = peer_bought - partner_products
            for prod in new_products:
                if prod not in peer_products:
                    peer_products[prod] = {"count": 0, "total_sim": 0.0, "avg_spend": 0.0}
                peer_products[prod]["count"] += 1
                peer_products[prod]["total_sim"] += float(sim)
                # Use actual spend for relevance
                peer_products[prod]["avg_spend"] += float(pivot.loc[peer, prod]) / peer_den

        if not peer_products:
            return []

        # Score: weighted by peer similarity × popularity
        recs = []
        for product, info in peer_products.items():
            score = info["total_sim"] * info["count"] / peer_den
            recs.append({
                "product": str(product),
                "collab_score": round(float(score), 4),
                "peer_count": info["count"],
                "avg_peer_spend": round(info["avg_spend"], 2),
                "source": "collaborative_filtering",
            })

        recs.sort(key=lambda x: x["collab_score"], reverse=True)
        return recs[: int(max(1, top_k))]

    # =================================================================
    # UPGRADE (b): Contextual Bandit for Action Selection
    # =================================================================

    def _init_bandit_state(self):
        """Initialize Thompson Sampling state for contextual bandit."""
        if not hasattr(self, "_bandit_alpha") or self._bandit_alpha is None:
            self._bandit_alpha = {}  # action_type → alpha (successes + 1)
            self._bandit_beta = {}   # action_type → beta (failures + 1)

    def _bandit_update_from_feedback(self, lookback_days=30):
        """
        Update bandit priors from feedback data.
        Reward mapping: won=1, accepted=0.5, rejected=0, lost=-0.5
        """
        self._init_bandit_state()
        try:
            df = self._load_feedback_events(lookback_days=lookback_days)
        except Exception:
            return

        if df.empty:
            return

        reward_map = {"won": 1.0, "accepted": 0.5, "rejected": 0.0, "lost": 0.0}

        for action_type, group in df.groupby("action_type"):
            action = str(action_type).strip()
            if not action:
                continue
            successes = 0.0
            failures = 0.0
            for _, row in group.iterrows():
                outcome = str(row.get("outcome", "")).strip().lower()
                reward = reward_map.get(outcome, 0.0)
                if reward >= 0.5:
                    successes += reward
                else:
                    failures += (1.0 - reward)

            self._bandit_alpha[action] = 1.0 + successes
            self._bandit_beta[action] = 1.0 + failures

    def _bandit_select_action(self, candidate_actions):
        """
        Thompson Sampling: draw from Beta(alpha, beta) for each action type
        and boost the priority score accordingly. Actions with better
        historical performance get probabilistically higher scores.
        """
        self._init_bandit_state()
        if not candidate_actions:
            return candidate_actions

        for action in candidate_actions:
            action_type = str(action.get("action_type", "")).strip()
            alpha = self._bandit_alpha.get(action_type, 1.0)
            beta = self._bandit_beta.get(action_type, 1.0)

            # Thompson sampling draw
            try:
                sample = float(np.random.beta(alpha, beta))
            except Exception:
                sample = 0.5

            # Boost priority score by bandit signal (±15 points)
            bandit_boost = (sample - 0.5) * 30.0
            original = float(action.get("priority_score", 50.0))
            action["priority_score"] = round(float(original + bandit_boost), 2)
            action["bandit_sample"] = round(sample, 4)
            action["bandit_alpha"] = round(float(alpha), 2)
            action["bandit_beta"] = round(float(beta), 2)

        # Re-sort by updated priority
        candidate_actions.sort(
            key=lambda x: float(x.get("priority_score", 0.0)), reverse=True
        )
        return candidate_actions

    # =================================================================
    # UPGRADE (c): Learned Priority Scoring
    # =================================================================

    def _compute_learned_priority_adjustments(self):
        """
        Compute per-action-type priority adjustments from historical feedback.
        Returns dict mapping action_type → adjustment factor.
        """
        try:
            df = self._load_feedback_events(lookback_days=60)
        except Exception:
            return {}

        if df.empty or len(df) < 10:
            return {}

        df["outcome"] = df["outcome"].astype(str).str.lower().str.strip()
        positive = {"accepted", "won"}
        df["is_positive"] = df["outcome"].isin(positive).astype(int)

        adjustments = {}
        overall_rate = float(df["is_positive"].mean())

        for action_type, group in df.groupby("action_type"):
            if len(group) < 3:
                continue
            win_rate = float(group["is_positive"].mean())
            # Adjustment: +/- up to 20 points based on performance vs average
            delta = (win_rate - overall_rate) * 40.0
            adjustments[str(action_type).strip()] = round(delta, 2)

        return adjustments

    def _apply_learned_scoring(self, actions):
        """Apply learned priority adjustments from feedback data."""
        adjustments = self._compute_learned_priority_adjustments()
        if not adjustments:
            return actions

        for action in actions:
            action_type = str(action.get("action_type", "")).strip()
            adj = adjustments.get(action_type, 0.0)
            if adj != 0.0:
                original = float(action.get("priority_score", 50.0))
                action["priority_score"] = round(float(original + adj), 2)
                action["learned_adjustment"] = round(adj, 2)

        actions.sort(key=lambda x: float(x.get("priority_score", 0.0)), reverse=True)
        return actions

    # =================================================================
    # UPGRADE (d): Recommendation Diversity
    # =================================================================

    @staticmethod
    def _enforce_diversity(actions, min_action_types=2, max_per_type=2):
        """
        Ensure top-N recommendations span at least min_action_types different
        action types. Also penalize repeats of the same rejected offer
        (novelty scoring).
        """
        if len(actions) <= 1:
            return actions

        # Group by action type
        type_buckets = {}
        for a in actions:
            at = str(a.get("action_type", "Unknown"))
            if at not in type_buckets:
                type_buckets[at] = []
            type_buckets[at].append(a)

        # If already diverse, just enforce per-type cap
        if len(type_buckets) >= min_action_types:
            result = []
            for at, bucket in type_buckets.items():
                bucket.sort(key=lambda x: float(x.get("priority_score", 0.0)), reverse=True)
                result.extend(bucket[:max_per_type])
            result.sort(key=lambda x: float(x.get("priority_score", 0.0)), reverse=True)
            return result

        # Not diverse enough: interleave from different types
        # Take top from each type in round-robin order
        sorted_types = sorted(
            type_buckets.keys(),
            key=lambda t: max(float(a.get("priority_score", 0.0)) for a in type_buckets[t]),
            reverse=True,
        )

        result = []
        seen_types = set()
        # First pass: one from each type
        for at in sorted_types:
            bucket = type_buckets[at]
            bucket.sort(key=lambda x: float(x.get("priority_score", 0.0)), reverse=True)
            result.append(bucket[0])
            seen_types.add(at)

        # Second pass: fill remaining up to max_per_type
        for at in sorted_types:
            bucket = type_buckets[at]
            for a in bucket[1:max_per_type]:
                result.append(a)

        result.sort(key=lambda x: float(x.get("priority_score", 0.0)), reverse=True)
        return result

    @staticmethod
    def _apply_novelty_penalty(actions, feedback_df=None):
        """
        Penalize re-recommending offers that were already rejected.
        Novelty scoring: reduce priority of previously rejected actions.
        """
        if feedback_df is None or feedback_df.empty:
            return actions

        # Build set of recently rejected offers
        rejected = feedback_df[feedback_df["outcome"].isin({"rejected", "lost"})]
        if rejected.empty:
            return actions

        rejected_offers = set(
            rejected["recommended_offer"].astype(str).str.lower().str.strip().tolist()
        )
        rejected_actions = set(
            rejected["action_type"].astype(str).str.lower().str.strip().tolist()
        )

        for action in actions:
            offer = str(action.get("recommended_offer", "")).lower().strip()
            at = str(action.get("action_type", "")).lower().strip()

            if offer in rejected_offers:
                # Heavy penalty: this exact offer was rejected
                penalty = -20.0
                action["novelty_penalty"] = penalty
                action["priority_score"] = max(0.0, float(action.get("priority_score", 50.0)) + penalty)
            elif at in rejected_actions:
                # Light penalty: same action type was rejected
                penalty = -8.0
                action["novelty_penalty"] = penalty
                action["priority_score"] = max(0.0, float(action.get("priority_score", 50.0)) + penalty)

        actions.sort(key=lambda x: float(x.get("priority_score", 0.0)), reverse=True)
        return actions

    # =================================================================
    # UPGRADE (e): Multi-Step Journey Optimization
    # =================================================================

    def get_partner_next_best_action(
        self,
        partner_name,
        previous_outcome=None,
        previous_action_type=None,
        top_n=3,
    ):
        """
        Dynamic multi-step journey: determine the next best action based on
        what happened with the previous recommendation.

        Journey logic:
        - If accepted → next: high-margin upsell
        - If no response after 7 days → followup with trial offer
        - If rejected → switch to retention/discount offer
        - If won → strategic expansion
        - If first contact → standard recommendation plan
        """
        self.ensure_clustering()
        self.ensure_churn_forecast()
        self.ensure_credit_risk()
        self.ensure_associations()

        report = self.get_partner_intelligence(partner_name)
        if not report:
            return {"status": "failed", "reason": "Partner intelligence unavailable."}

        # Build base actions
        actions = self._build_partner_actions(
            report,
            partner_name=partner_name,
            include_bundle_actions=True,
        )

        # Load recent feedback for this partner
        try:
            feedback_df = self._load_feedback_events(lookback_days=30)
            partner_feedback = feedback_df[
                feedback_df["partner_name"].astype(str) == str(partner_name)
            ] if not feedback_df.empty else pd.DataFrame()
        except Exception:
            partner_feedback = pd.DataFrame()
            feedback_df = pd.DataFrame()

        # Apply novelty penalty (don't re-recommend rejected offers)
        actions = self._apply_novelty_penalty(actions, partner_feedback)

        # Determine journey stage based on previous outcome
        journey_stage = "initial"
        journey_guidance = ""

        if previous_outcome:
            outcome = str(previous_outcome).strip().lower()
            prev_action = str(previous_action_type or "").strip()

            if outcome == "accepted":
                journey_stage = "upsell"
                journey_guidance = (
                    f"Partner accepted '{prev_action}'. "
                    "Advance to high-margin upsell or premium bundle expansion."
                )
                # Boost strategic expansion and cross-sell, suppress retention
                for a in actions:
                    at = str(a.get("action_type", "")).lower()
                    if "expansion" in at or "cross-sell" in at or "upsell" in at:
                        a["priority_score"] = float(a.get("priority_score", 50.0)) + 15.0
                    elif "retention" in at:
                        a["priority_score"] = max(0.0, float(a.get("priority_score", 50.0)) - 20.0)

            elif outcome == "won":
                journey_stage = "grow"
                journey_guidance = (
                    f"Deal won on '{prev_action}'. "
                    "Focus on deepening the relationship: category expansion, volume commitments."
                )
                for a in actions:
                    at = str(a.get("action_type", "")).lower()
                    if "expansion" in at:
                        a["priority_score"] = float(a.get("priority_score", 50.0)) + 20.0

            elif outcome in ("rejected", "lost"):
                journey_stage = "recover"
                journey_guidance = (
                    f"Partner rejected/lost on '{prev_action}'. "
                    "Switch to retention: discount offer, alternative product, or relationship nurture."
                )
                for a in actions:
                    at = str(a.get("action_type", "")).lower()
                    if "retention" in at or "credit-safe" in at or "nurture" in at:
                        a["priority_score"] = float(a.get("priority_score", 50.0)) + 15.0
                    elif "cross-sell" in at or "upsell" in at or "expansion" in at:
                        a["priority_score"] = max(0.0, float(a.get("priority_score", 50.0)) - 15.0)

            elif outcome == "no_response":
                journey_stage = "followup"
                journey_guidance = (
                    f"No response to '{prev_action}' after 7 days. "
                    "Send followup with trial offer (small quantity, low commitment)."
                )
                # Don't heavily change scores, but add followup action
                actions.insert(0, {
                    "action_type": "Trial Follow-up",
                    "recommended_offer": f"Small trial qty of {prev_action} offer",
                    "priority_score": 80.0,
                    "why_relevant": "No response to initial pitch. Trial reduces commitment barrier.",
                    "suggested_sequence": "Send lightweight trial offer, then wait 5 days for response.",
                })

        # Apply learned scoring from feedback
        actions = self._apply_learned_scoring(actions)

        # Apply contextual bandit if we have feedback
        try:
            self._bandit_update_from_feedback(lookback_days=30)
            actions = self._bandit_select_action(actions)
        except Exception:
            pass

        # Enforce diversity
        actions = self._enforce_diversity(actions, min_action_types=2, max_per_type=2)

        # Add collaborative filtering recommendations
        collab_recs = self._build_collaborative_recommendations(partner_name, top_k=3)

        # Inject collab recs into cross-sell action if available
        if collab_recs:
            for a in actions:
                if "cross-sell" in str(a.get("action_type", "")).lower():
                    a["collaborative_suggestions"] = collab_recs[:3]
                    break
            else:
                # No cross-sell action exists, add one
                if collab_recs:
                    top_rec = collab_recs[0]
                    actions.append({
                        "action_type": "Cross-sell Upsell",
                        "recommended_offer": top_rec["product"],
                        "priority_score": 50.0 + top_rec["collab_score"] * 20.0,
                        "why_relevant": (
                            f"Collaborative filtering: {top_rec['peer_count']} similar partners "
                            f"buy this with avg spend Rs {top_rec['avg_peer_spend']:,.0f}."
                        ),
                        "suggested_sequence": "Pitch alongside next regular order.",
                        "collaborative_suggestions": collab_recs[:3],
                        "source": "collaborative_filtering",
                    })

        # Final sort and limit
        actions.sort(key=lambda x: float(x.get("priority_score", 0.0)), reverse=True)
        actions = actions[:top_n]
        for i, a in enumerate(actions, start=1):
            a["sequence"] = int(i)

        facts = report.get("facts", pd.Series(dtype=float))

        return {
            "status": "ok",
            "partner_name": partner_name,
            "journey_stage": journey_stage,
            "journey_guidance": journey_guidance,
            "previous_outcome": previous_outcome,
            "cluster_label": report.get("cluster_label", "Unknown"),
            "cluster_type": report.get("cluster_type", "Unknown"),
            "actions": actions,
            "collaborative_recommendations": collab_recs,
            "sequence_summary": self._build_sequence_text(actions),
            "feedback_events_used": int(len(partner_feedback)) if not partner_feedback.empty else 0,
        }

    def get_enhanced_recommendation_plan(
        self,
        partner_name,
        top_n=3,
        use_genai=False,
        api_key=None,
        model=None,
    ):
        """
        Enhanced recommendation plan that integrates all 5 upgrades:
        collaborative filtering, contextual bandits, learned scoring,
        diversity constraints, and multi-step journey awareness.
        """
        # Start with base plan
        base_plan = self.get_partner_recommendation_plan(
            partner_name=partner_name,
            top_n=top_n * 2,  # Get extra to allow diversity filtering
            use_genai=False,
        )
        if not base_plan or base_plan.get("status") != "ok":
            return base_plan

        actions = base_plan.get("actions", [])

        # Load feedback for novelty/bandit
        try:
            feedback_df = self._load_feedback_events(lookback_days=30)
            partner_feedback = feedback_df[
                feedback_df["partner_name"].astype(str) == str(partner_name)
            ] if not feedback_df.empty else pd.DataFrame()
        except Exception:
            partner_feedback = pd.DataFrame()
            feedback_df = pd.DataFrame()

        # Apply all upgrades
        actions = self._apply_novelty_penalty(actions, partner_feedback)
        actions = self._apply_learned_scoring(actions)

        try:
            self._bandit_update_from_feedback(lookback_days=30)
            actions = self._bandit_select_action(actions)
        except Exception:
            pass

        actions = self._enforce_diversity(actions, min_action_types=2, max_per_type=2)

        # Add collaborative filtering
        collab_recs = self._build_collaborative_recommendations(partner_name, top_k=5)

        # Trim to top_n
        actions = actions[:top_n]
        for i, a in enumerate(actions, start=1):
            a["sequence"] = int(i)

        report = self.get_partner_intelligence(partner_name) or {}

        out = {
            "status": "ok",
            "partner_name": partner_name,
            "cluster_label": report.get("cluster_label", "Unknown"),
            "cluster_type": report.get("cluster_type", "Unknown"),
            "sequence_summary": self._build_sequence_text(actions),
            "actions": actions,
            "collaborative_recommendations": collab_recs,
            "plain_language_explanation": self._build_plain_language_explanation(report, actions),
            "upgrades_applied": [
                "collaborative_filtering",
                "contextual_bandits",
                "learned_priority_scoring",
                "recommendation_diversity",
                "novelty_penalty",
            ],
            "genai": None,
            "genai_error": None,
        }

        if use_genai:
            key = str(api_key or getattr(self, "openai_api_key", "") or "").strip()
            gm = str(model or os.getenv("OPENAI_MODEL", "gpt-4o")).strip()
            if not key:
                out["genai_error"] = "Gemini API key missing."
                return out

            facts = report.get("facts", pd.Series(dtype=float))
            prompt = (
                "You are a B2B sales copilot with advanced ML capabilities. "
                "Using these enhanced signals, write concise guidance.\n"
                "Return sections:\n"
                "1) Top Recommended Actions (with priority context)\n"
                "2) Why each action is relevant (cite ML signals)\n"
                "3) Suggested execution sequence\n"
                "4) Collaborative filtering insights (which similar partners inform this)\n\n"
                f"Partner: {partner_name}\n"
                f"Cluster: {report.get('cluster_label', 'Unknown')} ({report.get('cluster_type', 'Unknown')})\n"
                f"Health segment: {facts.get('health_segment', 'Unknown')}\n"
                f"Churn probability: {facts.get('churn_probability', 0)}\n"
                f"Credit risk score: {facts.get('credit_risk_score', 0)}\n"
                f"Enhanced recommendations: {json.dumps(actions, ensure_ascii=True, default=str)}\n"
                f"Collaborative recs: {json.dumps(collab_recs, ensure_ascii=True, default=str)}\n"
            )
            text_out, err = self._call_gemini_recommendation(prompt=prompt, api_key=key, model=gm)
            out["genai"] = text_out
            out["genai_error"] = err

        return out
