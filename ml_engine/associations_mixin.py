import numpy as np
import pandas as pd
import importlib
from sqlalchemy import text

class AssociationsMixin:
    @staticmethod
    def _decorate_rule_quality(df, min_support, include_low_support):
        if "support_a" in df.columns and "support_b" in df.columns:
            df["low_support_flag"] = (df["support_a"] < int(min_support)) | (
                df["support_b"] < int(min_support)
            )
        else:
            df["low_support_flag"] = False

        if not include_low_support:
            df = df[~df["low_support_flag"]]

        conf = df.get("confidence_a_to_b", pd.Series(0.0, index=df.index)).fillna(0.0)
        lift = df.get("lift_a_to_b", pd.Series(0.0, index=df.index)).fillna(0.0)
        df["rule_strength"] = np.where(
            (conf >= 0.4) & (lift >= 1.5),
            "High",
            np.where((conf >= 0.2) & (lift >= 1.1), "Medium", "Low"),
        )
        return df

    def _load_associations_with_metrics(self):
        """
        Build association rules with confidence/lift from one canonical basket base.
        Falls back to the materialized view only if source tables are unavailable.
        """
        if self.use_precomputed_assoc or self.strict_view_only:
            try:
                df = self.repo.fetch_view_product_associations(limit=2000)
                if not df.empty:
                    # View-first fast path: derive lightweight defaults to keep UI/ranking functional.
                    max_pair = float(df["times_bought_together"].max()) if "times_bought_together" in df.columns else 1.0
                    max_pair = max(max_pair, 1.0)
                    if "support_a" not in df.columns:
                        df["support_a"] = df["times_bought_together"].astype(float)
                    if "support_b" not in df.columns:
                        df["support_b"] = df["times_bought_together"].astype(float)
                    if "confidence_a_to_b" not in df.columns:
                        df["confidence_a_to_b"] = (
                            df["times_bought_together"].astype(float) / max_pair
                        ).clip(0.05, 1.0)
                    if "lift_a_to_b" not in df.columns:
                        df["lift_a_to_b"] = 1.0 + (
                            df["times_bought_together"].astype(float) / max_pair
                        )
                    if "expected_revenue_gain" not in df.columns:
                        df["expected_revenue_gain"] = (
                            df["times_bought_together"].astype(float) * 1000.0
                        )
                    if "expected_margin_gain" not in df.columns:
                        df["expected_margin_gain"] = df["expected_revenue_gain"] * 0.15
                    if "margin_rate" not in df.columns:
                        df["margin_rate"] = 0.15
                    return df
            except Exception:
                pass
            if self.strict_view_only:
                return pd.DataFrame(
                    columns=[
                        "product_a",
                        "product_b",
                        "times_bought_together",
                        "support_a",
                        "support_b",
                        "confidence_a_to_b",
                        "lift_a_to_b",
                        "expected_revenue_gain",
                        "expected_margin_gain",
                        "margin_rate",
                    ]
                )

        query = """
        WITH max_date_cte AS (
            SELECT MAX(date)::date AS last_recorded_date
            FROM transactions_dsr t
            WHERE {approved}
        ),
        baskets AS (
            SELECT DISTINCT
                t.party_id,
                TO_CHAR(t.date, 'YYYY-MM') AS sale_month,
                p.product_name
            FROM transactions_dsr t
            JOIN transactions_dsr_products tp ON t.id = tp.dsr_id
            JOIN master_products p ON tp.product_id = p.id
            CROSS JOIN max_date_cte md
            WHERE {approved}
              AND t.date >= md.last_recorded_date - INTERVAL '{lookback_months} months'
        ),
        basket_total AS (
            SELECT COUNT(DISTINCT (party_id::text || '|' || sale_month)) AS total_baskets
            FROM baskets
        ),
        product_support AS (
            SELECT
                product_name,
                COUNT(*) AS product_basket_count
            FROM baskets
            GROUP BY product_name
        ),
        pair_support AS (
            SELECT
                a.product_name AS product_a,
                b.product_name AS product_b,
                COUNT(*) AS times_bought_together
            FROM baskets a
            JOIN baskets b
              ON a.party_id = b.party_id
             AND a.sale_month = b.sale_month
             AND a.product_name < b.product_name
            GROUP BY a.product_name, b.product_name
        ),
        avg_product_value AS (
            SELECT
                p.product_name,
                AVG(tp.net_amt) AS avg_line_revenue
            FROM transactions_dsr t
            JOIN transactions_dsr_products tp ON t.id = tp.dsr_id
            JOIN master_products p ON tp.product_id = p.id
            CROSS JOIN max_date_cte md
            WHERE {approved}
              AND t.date >= md.last_recorded_date - INTERVAL '{lookback_months} months'
            GROUP BY p.product_name
        ),
        avg_product_margin AS (
            SELECT
                p.product_name,
                AVG(
                    GREATEST(
                        tp.net_amt - (COALESCE(NULLIF(tp.transfer_price, 0), COALESCE(msp.transfer_price, 0)) * COALESCE(NULLIF(tp.qty, 0), 1)),
                        0
                    )
                ) AS avg_line_margin
            FROM transactions_dsr t
            JOIN transactions_dsr_products tp ON t.id = tp.dsr_id
            JOIN master_products p ON tp.product_id = p.id
            LEFT JOIN LATERAL (
                SELECT m.transfer_price
                FROM master_product_selling_price m
                WHERE m.product_id = tp.product_id
                ORDER BY m.formation_dt DESC NULLS LAST
                LIMIT 1
            ) msp ON TRUE
            CROSS JOIN max_date_cte md
            WHERE {approved}
              AND t.date >= md.last_recorded_date - INTERVAL '{lookback_months} months'
            GROUP BY p.product_name
        )
        SELECT
            ps.product_a,
            ps.product_b,
            ps.times_bought_together,
            COALESCE(psa.product_basket_count, 0) AS support_a,
            COALESCE(psb.product_basket_count, 0) AS support_b,
            bt.total_baskets,
            ROUND(
                ps.times_bought_together::numeric / NULLIF(psa.product_basket_count, 0),
                4
            ) AS confidence_a_to_b,
            ROUND(
                ps.times_bought_together::numeric / NULLIF(psb.product_basket_count, 0),
                4
            ) AS confidence_b_to_a,
            ROUND(
                (
                    ps.times_bought_together::numeric / NULLIF(psa.product_basket_count, 0)
                ) /
                (
                    psb.product_basket_count::numeric / NULLIF(bt.total_baskets, 0)
                ),
                4
            ) AS lift_a_to_b,
            ROUND(
                COALESCE(
                    ps.times_bought_together::numeric * apv.avg_line_revenue,
                    0
                ),
                2
            ) AS expected_revenue_gain,
            ROUND(
                COALESCE(
                    ps.times_bought_together::numeric * apm.avg_line_margin,
                    0
                ),
                2
            ) AS expected_margin_gain,
            ROUND(
                COALESCE(
                    apm.avg_line_margin / NULLIF(apv.avg_line_revenue, 0),
                    0
                ),
                4
            ) AS margin_rate
        FROM pair_support ps
        CROSS JOIN basket_total bt
        LEFT JOIN product_support psa ON ps.product_a = psa.product_name
        LEFT JOIN product_support psb ON ps.product_b = psb.product_name
        LEFT JOIN avg_product_value apv ON ps.product_b = apv.product_name
        LEFT JOIN avg_product_margin apm ON ps.product_b = apm.product_name
        ORDER BY ps.times_bought_together DESC
        LIMIT 2000
        """.format(
            approved=self._approved_condition("t"),
            lookback_months=int(self.mba_lookback_months),
        )
        try:
            df = pd.read_sql(query, self.engine)
            return df
        except Exception:
            try:
                df = pd.read_sql(
                    "SELECT * FROM view_product_associations ORDER BY times_bought_together DESC LIMIT 1000",
                    self.engine,
                )
            except Exception:
                return pd.DataFrame(
                    columns=[
                        "product_a",
                        "product_b",
                        "times_bought_together",
                        "confidence_a_to_b",
                        "lift_a_to_b",
                        "expected_revenue_gain",
                        "expected_margin_gain",
                        "margin_rate",
                    ]
                )

            # Fallback defaults when support tables are unavailable.
            df["confidence_a_to_b"] = np.nan
            df["lift_a_to_b"] = np.nan
            df["expected_revenue_gain"] = np.nan
            df["expected_margin_gain"] = np.nan
            df["margin_rate"] = np.nan
            return df

    def _get_partner_products(self, partner_name):
        if not partner_name:
            return set()
        if self.strict_view_only:
            # In strict/view-only mode, avoid transactional table queries and
            # derive partner history from already-loaded view data.
            if self.df_ml is not None and not self.df_ml.empty:
                partner_key = str(partner_name).strip().casefold()
                company = self.df_ml["company_name"].astype(str).str.strip().str.casefold()
                partner_rows = self.df_ml[company == partner_key]
                for col in ("product_name", "group_name"):
                    if col in partner_rows.columns:
                        vals = (
                            partner_rows[col]
                            .dropna()
                            .astype(str)
                            .str.strip()
                        )
                        products = set(v for v in vals.tolist() if v)
                        if products:
                            return products
            return set()
        query = text(
            """
            SELECT DISTINCT p.product_name
            FROM transactions_dsr t
            JOIN transactions_dsr_products tp ON t.id = tp.dsr_id
            JOIN master_products p ON tp.product_id = p.id
            JOIN master_party mp ON t.party_id = mp.id
            WHERE {approved}
              AND mp.company_name = :partner_name
            """
            .format(approved=self._approved_condition("t"))
        )
        try:
            df = pd.read_sql(query, self.engine, params={"partner_name": partner_name})
            if df.empty:
                return set()
            return set(df["product_name"].dropna().astype(str).tolist())
        except Exception:
            return set()

    def get_associations(
        self,
        search_term="",
        min_confidence=0.0,
        min_lift=0.0,
        min_support=None,
        include_low_support=None,
        limit=200,
    ):
        self.ensure_associations()

        df = self.df_assoc_rules.copy()
        if df.empty:
            return df

        if search_term:
            mask = (
                df["product_a"].astype(str).str.contains(search_term, case=False, na=False)
                | df["product_b"].astype(str).str.contains(search_term, case=False, na=False)
            )
            df = df[mask]

        if "confidence_a_to_b" in df.columns:
            df = df[
                df["confidence_a_to_b"].fillna(0).astype(float) >= float(min_confidence)
            ]
        if "lift_a_to_b" in df.columns:
            df = df[df["lift_a_to_b"].fillna(0).astype(float) >= float(min_lift)]

        if min_support is None:
            min_support = self.default_min_support
        if include_low_support is None:
            include_low_support = self.default_include_low_support

        df = self._decorate_rule_quality(df, min_support, include_low_support)
        strength_rank = {"High": 0, "Medium": 1, "Low": 2}
        df["rule_strength_rank"] = df["rule_strength"].map(strength_rank).fillna(3)

        df = df.sort_values(
            by=[
                "rule_strength_rank",
                "expected_margin_gain" if "expected_margin_gain" in df.columns and self.rank_by_margin else "expected_revenue_gain",
                "expected_revenue_gain",
                "times_bought_together",
            ],
            ascending=[True, False, False, False],
            na_position="last",
        )
        df = df.drop(columns=["rule_strength_rank"], errors="ignore")
        if "expected_revenue_gain" in df.columns:
            annualization = 12.0 / float(self.mba_lookback_months)
            df["expected_gain_yearly"] = df["expected_revenue_gain"].astype(float) * annualization
            df["expected_gain_monthly"] = df["expected_gain_yearly"] / 12.0
            df["expected_gain_weekly"] = df["expected_gain_yearly"] / 52.0
        if "expected_margin_gain" in df.columns:
            annualization = 12.0 / float(self.mba_lookback_months)
            df["expected_margin_yearly"] = df["expected_margin_gain"].astype(float) * annualization
            df["expected_margin_monthly"] = df["expected_margin_yearly"] / 12.0
            df["expected_margin_weekly"] = df["expected_margin_yearly"] / 52.0
        return df.head(limit)

    def _get_top_affinity_pitch(self, partner_name, min_confidence=0.15, min_lift=1.0):
        recos = self.get_partner_bundle_recommendations(
            partner_name=partner_name,
            min_confidence=min_confidence,
            min_lift=min_lift,
            min_support=self.default_min_support,
            include_low_support=self.default_include_low_support,
            top_n=1,
        )
        if recos.empty:
            return None
        return recos.iloc[0].to_dict()

    def get_partner_bundle_recommendations(
        self,
        partner_name,
        min_confidence=0.15,
        min_lift=1.0,
        min_support=None,
        include_low_support=None,
        top_n=10,
    ):
        if not partner_name:
            return pd.DataFrame()

        rules = self.get_associations(
            min_confidence=min_confidence,
            min_lift=min_lift,
            min_support=min_support,
            include_low_support=include_low_support,
            limit=1000,
        )
        if rules.empty:
            return pd.DataFrame()

        bought = self._get_partner_products(partner_name)
        if not bought:
            return pd.DataFrame()

        candidate = rules[
            rules["product_a"].astype(str).isin(bought)
            & ~rules["product_b"].astype(str).isin(bought)
        ].copy()

        if candidate.empty:
            return pd.DataFrame()

        candidate = candidate.rename(
            columns={
                "product_a": "trigger_product",
                "product_b": "recommended_product",
                "times_bought_together": "frequency",
                "confidence_a_to_b": "confidence",
                "lift_a_to_b": "lift",
            }
        )
        candidate = candidate.sort_values(
            by=[
                "expected_margin_gain" if "expected_margin_gain" in candidate.columns and self.rank_by_margin else "expected_revenue_gain",
                "expected_revenue_gain",
                "confidence",
                "frequency",
            ],
            ascending=[False, False, False, False],
            na_position="last",
        )
        if "expected_revenue_gain" in candidate.columns:
            annualization = 12.0 / float(self.mba_lookback_months)
            candidate["expected_gain_yearly"] = candidate["expected_revenue_gain"].astype(float) * annualization
            candidate["expected_gain_monthly"] = candidate["expected_gain_yearly"] / 12.0
            candidate["expected_gain_weekly"] = candidate["expected_gain_yearly"] / 52.0
        if "expected_margin_gain" in candidate.columns:
            annualization = 12.0 / float(self.mba_lookback_months)
            candidate["expected_margin_yearly"] = candidate["expected_margin_gain"].astype(float) * annualization
            candidate["expected_margin_monthly"] = candidate["expected_margin_yearly"] / 12.0
            candidate["expected_margin_weekly"] = candidate["expected_margin_yearly"] / 52.0
        return candidate[
            [
                "trigger_product",
                "recommended_product",
                "confidence",
                "lift",
                "frequency",
                "rule_strength",
                "low_support_flag",
                "expected_revenue_gain",
                "expected_gain_monthly",
                "expected_gain_weekly",
                "expected_gain_yearly",
                "expected_margin_gain",
                "expected_margin_monthly",
                "expected_margin_weekly",
                "expected_margin_yearly",
                "margin_rate",
            ]
        ].head(top_n)


    # =================================================================
    # UPGRADE 1: FP-Growth / Apriori with Dynamic Thresholds
    # =================================================================

    def _load_transaction_baskets(self, lookback_months=None):
        """Load raw transaction baskets for in-memory mining."""
        if self.strict_view_only:
            return pd.DataFrame()
        months = int(lookback_months or getattr(self, "mba_lookback_months", 6))
        query = """
        WITH max_date_cte AS (
            SELECT MAX(date)::date AS last_recorded_date
            FROM transactions_dsr t WHERE {approved}
        )
        SELECT
            t.party_id::text || '|' || TO_CHAR(t.date, 'YYYY-MM') AS basket_id,
            p.product_name, t.date::date AS txn_date, t.party_id, tp.net_amt
        FROM transactions_dsr t
        JOIN transactions_dsr_products tp ON t.id = tp.dsr_id
        JOIN master_products p ON tp.product_id = p.id
        CROSS JOIN max_date_cte md
        WHERE {approved}
          AND t.date >= md.last_recorded_date - INTERVAL '{months} months'
        """.format(approved=self._approved_condition("t"), months=months)
        try:
            return pd.read_sql(query, self.engine)
        except Exception:
            return pd.DataFrame()

    def mine_fpgrowth_rules(self, min_support=0.02, min_confidence=0.15, min_lift=1.0):
        """Mine association rules using FP-Growth with dynamic thresholds."""
        try:
            fp_mod = importlib.import_module("mlxtend.frequent_patterns")
            pp_mod = importlib.import_module("mlxtend.preprocessing")
            fpgrowth = getattr(fp_mod, "fpgrowth")
            association_rules = getattr(fp_mod, "association_rules")
            TransactionEncoder = getattr(pp_mod, "TransactionEncoder")
            _algo = fpgrowth
        except Exception:
            try:
                fp_mod = importlib.import_module("mlxtend.frequent_patterns")
                pp_mod = importlib.import_module("mlxtend.preprocessing")
                apriori = getattr(fp_mod, "apriori")
                association_rules = getattr(fp_mod, "association_rules")
                TransactionEncoder = getattr(pp_mod, "TransactionEncoder")
                _algo = apriori
            except Exception:
                return pd.DataFrame(), {"status": "unavailable", "reason": "mlxtend not installed"}

        baskets_df = self._load_transaction_baskets()
        if baskets_df.empty:
            return pd.DataFrame(), {"status": "failed", "reason": "No basket data"}
        baskets = baskets_df.groupby("basket_id")["product_name"].apply(list).tolist()
        if len(baskets) < 10:
            return pd.DataFrame(), {"status": "failed", "reason": "Insufficient baskets"}

        te = TransactionEncoder()
        te_array = te.fit(baskets).transform(baskets)
        basket_matrix = pd.DataFrame(te_array, columns=te.columns_)

        try:
            freq = _algo(basket_matrix, min_support=float(min_support), use_colnames=True)
        except Exception as e:
            return pd.DataFrame(), {"status": "failed", "reason": str(e)}
        if freq.empty:
            return pd.DataFrame(), {"status": "ok", "reason": "No frequent itemsets"}

        try:
            rules = association_rules(freq, metric="confidence", min_threshold=float(min_confidence))
        except Exception as e:
            return pd.DataFrame(), {"status": "failed", "reason": str(e)}
        if rules.empty:
            return pd.DataFrame(), {"status": "ok", "reason": "No rules above threshold"}
        rules = rules[rules["lift"] >= float(min_lift)]

        result = pd.DataFrame({
            "product_a": rules["antecedents"].apply(lambda x: ", ".join(sorted(x))),
            "product_b": rules["consequents"].apply(lambda x: ", ".join(sorted(x))),
            "support": rules["support"].round(4),
            "confidence_a_to_b": rules["confidence"].round(4),
            "lift_a_to_b": rules["lift"].round(4),
            "conviction": rules["conviction"].round(4) if "conviction" in rules.columns else np.nan,
            "source": "fpgrowth",
        }).sort_values("lift_a_to_b", ascending=False).reset_index(drop=True)

        return result, {
            "status": "ok", "algorithm": _algo.__name__,
            "total_baskets": len(baskets), "frequent_itemsets": len(freq),
            "rules_generated": len(result),
        }

    # =================================================================
    # UPGRADE 2: Temporal Decay
    # =================================================================

    def mine_temporally_weighted_rules(self, half_life_days=90, min_support=0.02, min_confidence=0.15):
        """Association rules with exponential temporal decay. Recent co-purchases weigh more."""
        from collections import defaultdict
        baskets_df = self._load_transaction_baskets()
        if baskets_df.empty:
            return pd.DataFrame(), {"status": "failed", "reason": "No basket data"}

        baskets_df["txn_date"] = pd.to_datetime(baskets_df["txn_date"], errors="coerce")
        max_date = baskets_df["txn_date"].max()
        if pd.isna(max_date):
            return pd.DataFrame(), {"status": "failed", "reason": "No valid dates"}

        days_ago = (max_date - baskets_df["txn_date"]).dt.days.fillna(0).astype(float)
        baskets_df["weight"] = np.exp(-np.log(2) / float(half_life_days) * days_ago)

        baskets = baskets_df.groupby("basket_id").agg(
            products=("product_name", list), weight=("weight", "mean"),
        )
        product_sup = defaultdict(float)
        pair_sup = defaultdict(float)
        total_w = 0.0
        for _, row in baskets.iterrows():
            prods = sorted(set(str(p) for p in row["products"]))
            w = float(row["weight"])
            total_w += w
            for p in prods:
                product_sup[p] += w
            for i in range(len(prods)):
                for j in range(i + 1, len(prods)):
                    pair_sup[(prods[i], prods[j])] += w

        if total_w == 0:
            return pd.DataFrame(), {"status": "failed", "reason": "Zero weight"}

        rows = []
        for (a, b), pw in pair_sup.items():
            sa, sb = product_sup.get(a, 0.0), product_sup.get(b, 0.0)
            if sa == 0 or sb == 0:
                continue
            sup = pw / total_w
            if sup < min_support:
                continue
            conf = pw / sa
            if conf < min_confidence:
                continue
            exp_b = sb / total_w
            lift = conf / exp_b if exp_b > 0 else 0.0
            rows.append({
                "product_a": a, "product_b": b,
                "weighted_support": round(sup, 4),
                "confidence_a_to_b": round(float(conf), 4),
                "lift_a_to_b": round(float(lift), 4),
                "source": "temporal_decay", "half_life_days": half_life_days,
            })
        result = pd.DataFrame(rows)
        if not result.empty:
            result = result.sort_values("lift_a_to_b", ascending=False).reset_index(drop=True)
        return result, {"status": "ok", "half_life_days": half_life_days,
                        "total_baskets": len(baskets), "rules_generated": len(result)}

    # =================================================================
    # UPGRADE 3: Sequential Pattern Mining
    # =================================================================

    def mine_sequential_patterns(self, max_gap_days=30, min_support_count=3, min_confidence=0.1):
        """Sequential patterns: A then B within N days, with partner company names."""
        from collections import defaultdict
        if self.strict_view_only:
            return pd.DataFrame(), {"status": "skipped"}

        months = int(getattr(self, "mba_lookback_months", 6))
        query = """
        WITH max_date_cte AS (
            SELECT MAX(date)::date AS last_recorded_date
            FROM transactions_dsr t WHERE {approved}
        )
        SELECT t.party_id, mp.company_name, p.product_name, t.date::date AS txn_date
        FROM transactions_dsr t
        JOIN transactions_dsr_products tp ON t.id = tp.dsr_id
        JOIN master_products p ON tp.product_id = p.id
        JOIN master_party mp ON mp.id = t.party_id
        CROSS JOIN max_date_cte md
        WHERE {approved}
          AND t.date >= md.last_recorded_date - INTERVAL '{months} months'
        ORDER BY t.party_id, t.date
        """.format(approved=self._approved_condition("t"), months=months)

        try:
            df = pd.read_sql(query, self.engine)
        except Exception:
            return pd.DataFrame(), {"status": "failed", "reason": "SQL error"}
        if df.empty or len(df) < 20:
            return pd.DataFrame(), {"status": "failed", "reason": "Insufficient data"}

        df["txn_date"] = pd.to_datetime(df["txn_date"], errors="coerce")
        seq_counts = defaultdict(int)
        prod_counts = defaultdict(int)
        seq_partners = defaultdict(set)
        total_partners = 0

        pid_to_name = df[["party_id", "company_name"]].drop_duplicates().set_index("party_id")["company_name"].to_dict()

        for pid, grp in df.groupby("party_id"):
            total_partners += 1
            grp = grp.sort_values("txn_date")
            events = grp.drop_duplicates(subset=["product_name", "txn_date"])[
                ["product_name", "txn_date"]].values.tolist()
            for prod, _ in events:
                prod_counts[str(prod)] += 1
            seen = set()
            for i in range(len(events)):
                for j in range(i + 1, len(events)):
                    pa, da = str(events[i][0]), events[i][1]
                    pb, db = str(events[j][0]), events[j][1]
                    if pa == pb:
                        continue
                    gap = (db - da).days
                    if gap < 0 or gap > max_gap_days:
                        continue
                    pair = (pa, pb)
                    if pair not in seen:
                        seq_counts[pair] += 1
                        seq_partners[pair].add(pid_to_name.get(pid, str(pid)))
                        seen.add(pair)

        rows = []
        for (a, b), cnt in seq_counts.items():
            if cnt < min_support_count:
                continue
            ac = prod_counts.get(a, 0)
            if ac == 0:
                continue
            conf = cnt / ac
            if conf < min_confidence:
                continue
            br = prod_counts.get(b, 0) / max(total_partners, 1)
            lift = conf / br if br > 0 else 0.0
            partner_list = sorted(seq_partners[(a, b)])
            rows.append({
                "product_a": a, "product_b": b,
                "sequence_count": cnt, "support_a": ac,
                "confidence_a_then_b": round(float(conf), 4),
                "lift": round(float(lift), 4),
                "max_gap_days": max_gap_days,
                "pattern": f"{a} -> {b} (within {max_gap_days}d)",
                "source": "sequential_pattern",
                "partner_names": ", ".join(partner_list),
            })
        result = pd.DataFrame(rows)
        if not result.empty:
            result = result.sort_values("lift", ascending=False).reset_index(drop=True)
        return result, {"status": "ok", "max_gap_days": max_gap_days,
                        "total_partners": total_partners, "sequential_rules": len(result)}

    # =================================================================
    # UPGRADE 4: Cross-Category Rules
    # =================================================================

    def mine_cross_category_upgrades(self, gap_days=60, min_support_count=3, min_confidence=0.05):
        """Cross-category: premium in X -> buys Y within N days."""
        from collections import defaultdict
        if self.strict_view_only:
            return pd.DataFrame(), {"status": "skipped"}


        months = int(getattr(self, "mba_lookback_months", 6))
        query = """
        WITH max_date_cte AS (
            SELECT MAX(date)::date AS last_recorded_date
            FROM transactions_dsr t WHERE {approved}
        )
        SELECT t.party_id, mp.company_name, mg.group_name AS category,
               p.product_name, tp.net_amt, t.date::date AS txn_date
        FROM transactions_dsr t
        JOIN transactions_dsr_products tp ON t.id = tp.dsr_id
        JOIN master_products p ON tp.product_id = p.id
        JOIN master_party mp ON mp.id = t.party_id
        LEFT JOIN master_group mg ON p.group_id = mg.id
        CROSS JOIN max_date_cte md
        WHERE {approved}
          AND t.date >= md.last_recorded_date - INTERVAL '{months} months'
          AND mg.group_name IS NOT NULL
        ORDER BY t.party_id, t.date
        """.format(approved=self._approved_condition("t"), months=months)

        try:
            df = pd.read_sql(query, self.engine)
        except Exception:
            return pd.DataFrame(), {"status": "failed", "reason": "SQL error"}
        if df.empty or len(df) < 20:
            return pd.DataFrame(), {"status": "failed", "reason": "Insufficient data"}

        df["txn_date"] = pd.to_datetime(df["txn_date"], errors="coerce")
        df["net_amt"] = pd.to_numeric(df["net_amt"], errors="coerce").fillna(0.0)
        cat_med = df.groupby("category")["net_amt"].median()
        df = df.merge(cat_med.rename("cat_median"), left_on="category", right_index=True, how="left")
        df["is_premium"] = df["net_amt"] > df["cat_median"]

        upgrade_counts = defaultdict(int)
        cat_partner_counts = defaultdict(int)
        upgrade_partners = defaultdict(set)
        total_partners = 0

        pid_to_name = df[["party_id", "company_name"]].drop_duplicates().set_index("party_id")["company_name"].to_dict()

        for pid, grp in df.groupby("party_id"):
            total_partners += 1
            grp = grp.sort_values("txn_date")
            for cat in grp["category"].unique():
                cat_partner_counts[str(cat)] += 1
            prem = grp[grp["is_premium"]][["category", "txn_date"]].drop_duplicates()
            seen = set()
            for _, pr in prem.iterrows():
                cx, dx = str(pr["category"]), pr["txn_date"]
                future = grp[
                    (grp["txn_date"] > dx)
                    & (grp["txn_date"] <= dx + pd.Timedelta(days=gap_days))
                    & (grp["category"] != cx)
                ]
                for cy in future["category"].unique():
                    pair = (cx, str(cy))
                    if pair not in seen:
                        upgrade_counts[pair] += 1
                        upgrade_partners[pair].add(pid_to_name.get(pid, str(pid)))
                        seen.add(pair)

        rows = []
        for (cx, cy), cnt in upgrade_counts.items():
            if cnt < min_support_count:
                continue
            xp = cat_partner_counts.get(cx, 0)
            if xp == 0:
                continue
            conf = cnt / xp
            if conf < min_confidence:
                continue
            yr = cat_partner_counts.get(cy, 0) / max(total_partners, 1)
            lift = conf / yr if yr > 0 else 0.0
            partner_list = sorted(upgrade_partners[(cx, cy)])
            rows.append({
                "category_x": cx, "category_y": cy,
                "upgrade_count": cnt, "partners_in_x": xp,
                "confidence": round(float(conf), 4),
                "lift": round(float(lift), 4),
                "gap_days": gap_days,
                "pattern": f"Premium in {cx} -> buys {cy} within {gap_days}d",
                "source": "cross_category",
                "partner_names": ", ".join(partner_list),
            })
        result = pd.DataFrame(rows)
        if not result.empty:
            result = result.sort_values("lift", ascending=False).reset_index(drop=True)
        return result, {"status": "ok", "gap_days": gap_days,
                        "total_partners": total_partners,
                        "cross_category_rules": len(result)}

    # =================================================================
    # Orchestrator
    # =================================================================

    def get_enhanced_associations(self, partner_name=None, min_support=0.02,
                                  min_confidence=0.15, min_lift=1.0,
                                  include_sequential=True, include_cross_category=True,
                                  include_temporal_decay=True, top_n=20):
        """Combines all association mining techniques into one result."""
        all_rules, reports = [], {}
        try:
            fp, r = self.mine_fpgrowth_rules(min_support=min_support,
                                             min_confidence=min_confidence, min_lift=min_lift)
            reports["fpgrowth"] = r
            if not fp.empty:
                all_rules.append(fp)
        except Exception as e:
            reports["fpgrowth"] = {"status": "error", "reason": str(e)}

        if include_temporal_decay:
            try:
                td, r = self.mine_temporally_weighted_rules(min_support=min_support,
                                                            min_confidence=min_confidence)
                reports["temporal_decay"] = r
                if not td.empty:
                    all_rules.append(td)
            except Exception as e:
                reports["temporal_decay"] = {"status": "error", "reason": str(e)}

        if include_sequential:
            try:
                sq, r = self.mine_sequential_patterns(min_confidence=min_confidence)
                reports["sequential"] = r
                if not sq.empty:
                    all_rules.append(sq)
            except Exception as e:
                reports["sequential"] = {"status": "error", "reason": str(e)}

        if include_cross_category:
            try:
                cc, r = self.mine_cross_category_upgrades(min_confidence=min_confidence)
                reports["cross_category"] = r
                if not cc.empty:
                    all_rules.append(cc)
            except Exception as e:
                reports["cross_category"] = {"status": "error", "reason": str(e)}

        out = {"status": "ok", "reports": reports,
               "all_rules_count": sum(len(r) for r in all_rules)}

        if partner_name:
            partner_products = self._get_partner_products(partner_name)
            if partner_products:
                precs = []
                for rdf in all_rules:
                    if "product_a" in rdf.columns and "product_b" in rdf.columns:
                        m = rdf[rdf["product_a"].astype(str).apply(
                                lambda x: any(p in x for p in partner_products))
                              & ~rdf["product_b"].astype(str).apply(
                                lambda x: any(p in x for p in partner_products))]
                        if not m.empty:
                            precs.append(m)
                    elif "category_x" in rdf.columns:
                        precs.append(rdf)
                out["partner_recommendations"] = (
                    pd.concat(precs, ignore_index=True).head(top_n) if precs else pd.DataFrame()
                )
        return out
