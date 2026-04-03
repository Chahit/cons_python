import json
import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment
from sklearn.cluster import HDBSCAN, KMeans, SpectralClustering, AgglomerativeClustering
from sklearn.metrics import adjusted_rand_score, calinski_harabasz_score, silhouette_score
from sklearn.mixture import GaussianMixture
from sklearn.preprocessing import RobustScaler


class ClusteringMixin:
    @staticmethod
    def _safe_ratio(num, den):
        den = np.where(den == 0, np.nan, den)
        return np.nan_to_num(num / den, nan=0.0, posinf=0.0, neginf=0.0)

    def _load_temporal_group_spend(self, days):
        """
        Partner-group spend over rolling window ending at max approved transaction date.
        """
        query = """
        WITH max_date_cte AS (
            SELECT MAX(date)::date AS last_recorded_date
            FROM transactions_dsr t
            WHERE {approved}
        )
        SELECT
            mp.company_name,
            mg.group_name,
            SUM(tp.net_amt) AS total_spend
        FROM transactions_dsr t
        JOIN transactions_dsr_products tp ON t.id = tp.dsr_id
        JOIN master_products p ON tp.product_id = p.id
        JOIN master_group mg ON p.group_id = mg.id
        JOIN master_party mp ON t.party_id = mp.id
        CROSS JOIN max_date_cte md
        WHERE {approved}
          AND t.date >= md.last_recorded_date - INTERVAL '{days} days'
        GROUP BY mp.company_name, mg.group_name
        """.format(approved=self._approved_condition("t"), days=int(days))
        try:
            return pd.read_sql(query, self.engine)
        except Exception:
            return pd.DataFrame(columns=["company_name", "group_name", "total_spend"])

    # ===================================================================
    # FEATURE ENGINEERING: RFM, Velocity, Entropy, Seasonality, Network
    # ===================================================================

    def _load_rfm_features(self):
        """
        RFM features per partner:
        - recency_days: days since last transaction
        - frequency: number of distinct transactions
        - monetary: total net spend
        """
        query = """
        WITH max_date_cte AS (
            SELECT MAX(date)::date AS ref_date
            FROM transactions_dsr t
            WHERE {approved}
        )
        SELECT
            mp.company_name,
            (md.ref_date - MAX(t.date)::date) AS recency_days,
            COUNT(DISTINCT t.id)              AS frequency,
            COALESCE(SUM(tp.net_amt), 0)      AS monetary
        FROM transactions_dsr t
        JOIN transactions_dsr_products tp ON t.id = tp.dsr_id
        JOIN master_party mp ON t.party_id = mp.id
        CROSS JOIN max_date_cte md
        WHERE {approved}
        GROUP BY mp.company_name, md.ref_date
        """.format(approved=self._approved_condition("t"))
        try:
            df = pd.read_sql(query, self.engine)
            df = df.set_index("company_name")
            df["recency_days"] = pd.to_numeric(df["recency_days"], errors="coerce").fillna(9999)
            df["frequency"] = pd.to_numeric(df["frequency"], errors="coerce").fillna(0)
            df["monetary"] = pd.to_numeric(df["monetary"], errors="coerce").fillna(0)
            return df[["recency_days", "frequency", "monetary"]]
        except Exception:
            return pd.DataFrame(columns=["recency_days", "frequency", "monetary"])

    def _load_purchase_velocity(self):
        """
        Purchase velocity per partner:
        - mean_gap_days: average inter-purchase interval
        - std_gap_days: standard deviation of gaps
        - velocity_trend: ratio of recent avg gap (last 90d) to overall avg gap
                          < 1 means accelerating, > 1 means slowing down
        """
        query = """
        WITH txn_dates AS (
            SELECT
                mp.company_name,
                t.date::date AS txn_date,
                ROW_NUMBER() OVER (PARTITION BY mp.company_name ORDER BY t.date) AS rn
            FROM transactions_dsr t
            JOIN master_party mp ON t.party_id = mp.id
            WHERE {approved}
            GROUP BY mp.company_name, t.date::date
        ),
        gaps AS (
            SELECT
                a.company_name,
                (b.txn_date - a.txn_date) AS gap_days
            FROM txn_dates a
            JOIN txn_dates b ON a.company_name = b.company_name AND b.rn = a.rn + 1
        )
        SELECT
            company_name,
            AVG(gap_days)    AS mean_gap_days,
            STDDEV(gap_days) AS std_gap_days,
            COUNT(*)         AS n_gaps
        FROM gaps
        GROUP BY company_name
        HAVING COUNT(*) >= 2
        """.format(approved=self._approved_condition("t"))
        try:
            df = pd.read_sql(query, self.engine)
            df = df.set_index("company_name")
            for c in ["mean_gap_days", "std_gap_days"]:
                df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
            # Coefficient of variation of gaps (regularity signal)
            df["gap_cv"] = np.where(
                df["mean_gap_days"] > 0,
                df["std_gap_days"] / df["mean_gap_days"],
                0.0,
            )
            return df[["mean_gap_days", "std_gap_days", "gap_cv"]]
        except Exception:
            return pd.DataFrame(columns=["mean_gap_days", "std_gap_days", "gap_cv"])

    def _compute_category_entropy(self, pivot):
        """
        Shannon entropy of each partner's category spend distribution.
        High entropy = diverse buyer. Low entropy = concentrated buyer.
        """
        if pivot is None or pivot.empty:
            return pd.DataFrame(columns=["category_entropy"], index=pivot.index if pivot is not None else [])

        totals = pivot.sum(axis=1).values.reshape(-1, 1)
        proportions = self._safe_ratio(pivot.values, totals)
        # Shannon entropy: -sum(p * log2(p)), treating 0*log(0) = 0
        with np.errstate(divide="ignore", invalid="ignore"):
            log_p = np.where(proportions > 0, np.log2(proportions), 0.0)
        entropy = -np.sum(proportions * log_p, axis=1)
        # Normalize by max possible entropy (log2 of number of categories)
        max_entropy = np.log2(max(pivot.shape[1], 1))
        norm_entropy = entropy / max_entropy if max_entropy > 0 else entropy

        return pd.DataFrame(
            {"category_entropy": entropy, "category_entropy_norm": norm_entropy},
            index=pivot.index,
        )

    def _load_seasonality_features(self):
        """
        Seasonality indicators per partner:
        - monthly_cv: coefficient of variation of monthly spend (high = seasonal)
        - dominant_quarter: quarter with highest spend (1-4), one-hot encoded
        - seasonal_amplitude: (max_quarter - min_quarter) / mean_quarter
        """
        query = """
        SELECT
            mp.company_name,
            EXTRACT(QUARTER FROM t.date) AS quarter,
            EXTRACT(MONTH FROM t.date)   AS month,
            SUM(tp.net_amt)              AS spend
        FROM transactions_dsr t
        JOIN transactions_dsr_products tp ON t.id = tp.dsr_id
        JOIN master_party mp ON t.party_id = mp.id
        WHERE {approved}
        GROUP BY mp.company_name, EXTRACT(QUARTER FROM t.date), EXTRACT(MONTH FROM t.date)
        """.format(approved=self._approved_condition("t"))
        try:
            df = pd.read_sql(query, self.engine)
            if df.empty:
                return pd.DataFrame(columns=["monthly_cv", "seasonal_amplitude",
                                             "season_q1", "season_q2", "season_q3", "season_q4"])

            # Monthly CV
            monthly = df.groupby("company_name")["spend"].agg(["mean", "std"]).fillna(0)
            monthly["monthly_cv"] = np.where(
                monthly["mean"] > 0, monthly["std"] / monthly["mean"], 0.0
            )

            # Quarterly amplitude
            quarterly = df.groupby(["company_name", "quarter"])["spend"].sum().unstack(fill_value=0)
            q_mean = quarterly.mean(axis=1)
            q_max = quarterly.max(axis=1)
            q_min = quarterly.min(axis=1)
            seasonal_amp = np.where(q_mean > 0, (q_max - q_min) / q_mean, 0.0)

            # Dominant quarter one-hot
            dominant_q = quarterly.idxmax(axis=1).astype(int) if not quarterly.empty else pd.Series(dtype=int)
            q_dummies = pd.DataFrame(0.0, index=quarterly.index,
                                     columns=["season_q1", "season_q2", "season_q3", "season_q4"])
            for idx in q_dummies.index:
                dq = dominant_q.get(idx, 1)
                col = f"season_q{int(dq)}"
                if col in q_dummies.columns:
                    q_dummies.loc[idx, col] = 1.0

            result = pd.DataFrame({
                "monthly_cv": monthly["monthly_cv"],
                "seasonal_amplitude": pd.Series(seasonal_amp, index=quarterly.index),
            })
            result = result.join(q_dummies, how="outer").fillna(0.0)
            return result
        except Exception:
            return pd.DataFrame(columns=["monthly_cv", "seasonal_amplitude",
                                         "season_q1", "season_q2", "season_q3", "season_q4"])

    def _compute_network_features(self, pivot, n_neighbors=5):
        """
        Network/co-purchase features:
        Partners with similar product portfolios should cluster together.
        Uses cosine similarity of spend vectors to derive:
        - mean_peer_sim: average cosine similarity to top-K most similar partners
        - max_peer_sim: highest similarity to any other partner
        - network_centrality: mean similarity to ALL partners (hub score)
        """
        if pivot is None or pivot.empty or len(pivot) < 3:
            return pd.DataFrame(
                columns=["net_mean_peer_sim", "net_max_peer_sim", "net_centrality"],
                index=pivot.index if pivot is not None else [],
            )

        from sklearn.metrics.pairwise import cosine_similarity

        vals = pivot.values.astype(float)
        # Normalize rows for cosine
        norms = np.linalg.norm(vals, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1.0, norms)
        normed = vals / norms

        sim_matrix = cosine_similarity(normed)
        np.fill_diagonal(sim_matrix, 0.0)  # Exclude self-similarity

        n = len(pivot)
        k = min(n_neighbors, n - 1)

        # Top-K peer similarities
        top_k_sims = np.sort(sim_matrix, axis=1)[:, -k:]  # Last K = highest K
        mean_peer_sim = top_k_sims.mean(axis=1)
        max_peer_sim = sim_matrix.max(axis=1)

        # Network centrality: mean similarity to all partners
        centrality = sim_matrix.mean(axis=1)

        return pd.DataFrame(
            {
                "net_mean_peer_sim": mean_peer_sim,
                "net_max_peer_sim": max_peer_sim,
                "net_centrality": centrality,
            },
            index=pivot.index,
        )

    def _compute_feature_drift(self, features):
        """
        Lightweight drift proxy against in-memory baseline stats.
        """
        if features is None or features.empty:
            return {"status": "empty"}
        current_mean = features.mean(axis=0).astype(float)
        current_std = features.std(axis=0).replace(0, np.nan).astype(float)

        if getattr(self, "cluster_feature_baseline", None) is None:
            self.cluster_feature_baseline = {
                "mean": current_mean.to_dict(),
                "std": current_std.fillna(0.0).to_dict(),
            }
            return {"status": "initialized", "mean_abs_z_shift": None}

        base_mean = pd.Series(self.cluster_feature_baseline.get("mean", {}), dtype=float)
        base_std = pd.Series(self.cluster_feature_baseline.get("std", {}), dtype=float).replace(
            0, np.nan
        )
        aligned_mean = current_mean.reindex(base_mean.index).fillna(0.0)
        aligned_std = base_std.reindex(base_mean.index)
        z = ((aligned_mean - base_mean) / aligned_std).replace([np.inf, -np.inf], np.nan)
        mean_abs_z = float(np.nanmean(np.abs(z.values))) if np.isfinite(z.values).any() else None

        # Update baseline each run to keep it adaptive in local deployment.
        self.cluster_feature_baseline = {
            "mean": current_mean.to_dict(),
            "std": current_std.fillna(0.0).to_dict(),
        }
        return {
            "status": "ok",
            "mean_abs_z_shift": round(mean_abs_z, 4) if mean_abs_z is not None else None,
        }

    def _feature_quality_guardrails(self, features):
        """
        Guardrails:
        - null ratio checks
        - zero-variance pruning
        - mix sum consistency checks
        """
        if features is None or features.empty:
            return features, {"status": "empty"}

        raw_cols = list(features.columns)
        null_ratio = float(features.isna().mean().max()) if len(raw_cols) else 0.0
        features = features.fillna(0.0)

        std = features.std(axis=0)
        keep_cols = std[std > 1e-9].index.tolist()
        dropped_zero_var = sorted(list(set(raw_cols) - set(keep_cols)))
        if keep_cols:
            features = features[keep_cols]
        else:
            # Keep at least one column to avoid model crash.
            features = features.assign(dummy_feature=1.0)
            dropped_zero_var = raw_cols

        mix_cols = [c for c in features.columns if c.startswith("mix::rw::")]
        mix_sum_error = None
        if mix_cols:
            sums = features[mix_cols].sum(axis=1)
            mix_sum_error = float(np.mean(np.abs(sums - 1.0)))

        report = {
            "status": "ok",
            "null_ratio_max": round(null_ratio, 4),
            "zero_var_dropped_count": int(len(dropped_zero_var)),
            "zero_var_dropped_sample": dropped_zero_var[:10],
            "mix_sum_mae": round(mix_sum_error, 6) if mix_sum_error is not None else None,
            "feature_count_after_prune": int(features.shape[1]),
        }
        return features, report

    def _build_cluster_features(self, subset_df):
        """
        Build behavior-first clustering features:
        - Mix features: category share of spend (dominant signal).
        - Scale features: log total spend, breadth, and state spend concentration.
        """
        if subset_df.empty:
            return pd.DataFrame(), pd.DataFrame(), pd.Series(dtype=str)

        # Resolve spend column — name varies by load path
        _spend_col = next(
            (c for c in ["total_spend", "total_revenue", "net_amt"] if c in subset_df.columns),
            None,
        )
        if _spend_col is None:
            _num_cols = subset_df.select_dtypes(include="number").columns.tolist()
            _spend_col = _num_cols[0] if _num_cols else None
        if _spend_col is None or "group_name" not in subset_df.columns:
            return pd.DataFrame(), pd.DataFrame(), pd.Series(dtype=str)

        pivot = subset_df.pivot_table(
            index="company_name",
            columns="group_name",
            values=_spend_col,
            aggfunc="sum",
            fill_value=0.0,
        )
        if pivot.empty:
            return pd.DataFrame(), pd.DataFrame(), pd.Series(dtype=str)

        # Temporal windows (3/6/12 months) for recency-aware behavior.
        windows = {90: None, 180: None, 365: None}
        if not self.strict_view_only:
            for d in windows:
                dfw = self._load_temporal_group_spend(d)
                if dfw is not None and not dfw.empty and "group_name" in dfw.columns:
                    _w_col = next(
                        (c for c in ["total_spend", "total_revenue", "net_amt"] if c in dfw.columns),
                        dfw.select_dtypes(include="number").columns[0]
                        if not dfw.select_dtypes(include="number").empty else None,
                    )
                    if _w_col:
                        windows[d] = dfw.pivot_table(
                            index="company_name",
                            columns="group_name",
                            values=_w_col,
                            aggfunc="sum",
                            fill_value=0.0,
                        )

        base_cols = set(pivot.columns.tolist())
        for d, w in windows.items():
            if w is not None:
                base_cols.update(w.columns.tolist())
        base_cols = sorted(list(base_cols))

        def _aligned_mix(window_df, cols):
            if window_df is None or window_df.empty:
                z = pd.DataFrame(0.0, index=pivot.index, columns=cols)
                return z
            tmp = window_df.reindex(index=pivot.index, columns=cols, fill_value=0.0)
            den = tmp.sum(axis=1).values.reshape(-1, 1)
            return pd.DataFrame(
                self._safe_ratio(tmp.values, den),
                index=tmp.index,
                columns=cols,
            )

        mix_90 = _aligned_mix(windows[90], base_cols)
        mix_180 = _aligned_mix(windows[180], base_cols)
        mix_365 = _aligned_mix(windows[365], base_cols)
        # Recency-weighted behavior mix.
        mix_rw = 0.5 * mix_90 + 0.3 * mix_180 + 0.2 * mix_365
        mix_rw.columns = [f"mix::rw::{c}" for c in mix_rw.columns]

        scale = pd.DataFrame(index=pivot.index)
        # Use 12m window spend for scale when available, else lifetime from view.
        scale_base = windows[365].reindex(index=pivot.index, columns=base_cols, fill_value=0.0) if windows[365] is not None else pivot.reindex(columns=base_cols, fill_value=0.0)
        scale["scale::log_total_spend"] = np.log1p(scale_base.sum(axis=1).astype(float))
        scale["scale::active_groups"] = (scale_base > 0).sum(axis=1).astype(float)
        # Concentration index: higher means narrower portfolio mix.
        totals = scale_base.sum(axis=1).values.reshape(-1, 1)
        mix_raw = self._safe_ratio(scale_base.values, totals)
        scale["scale::portfolio_concentration"] = (mix_raw**2).sum(axis=1)
        # Momentum: category breadth change (3m vs 12m).
        ag_90 = (windows[90].reindex(index=pivot.index, columns=base_cols, fill_value=0.0) > 0).sum(axis=1).astype(float) if windows[90] is not None else pd.Series(0.0, index=pivot.index)
        ag_365 = (scale_base > 0).sum(axis=1).astype(float)
        scale["scale::active_group_momentum"] = ag_90 - ag_365

        if "state" in subset_df.columns:
            state_map = (
                subset_df[["company_name", "state"]]
                .drop_duplicates("company_name")
                .set_index("company_name")["state"]
                .reindex(pivot.index)
                .fillna("Unknown")
            )
        else:
            state_map = pd.Series("Unknown", index=pivot.index, name="state")

        # --- RFM Features ---
        rfm_features = pd.DataFrame(index=pivot.index)
        if not self.strict_view_only:
            try:
                rfm = self._load_rfm_features()
                if not rfm.empty:
                    rfm = rfm.reindex(pivot.index).fillna(0.0)
                    rfm_features["rfm::log_recency"] = np.log1p(rfm["recency_days"].astype(float))
                    rfm_features["rfm::log_frequency"] = np.log1p(rfm["frequency"].astype(float))
                    rfm_features["rfm::log_monetary"] = np.log1p(rfm["monetary"].astype(float))
            except Exception:
                pass

        # --- Purchase Velocity ---
        velocity_features = pd.DataFrame(index=pivot.index)
        if not self.strict_view_only:
            try:
                vel = self._load_purchase_velocity()
                if not vel.empty:
                    vel = vel.reindex(pivot.index).fillna(0.0)
                    velocity_features["vel::log_mean_gap"] = np.log1p(vel["mean_gap_days"].astype(float))
                    velocity_features["vel::gap_cv"] = vel["gap_cv"].astype(float).clip(0, 5)
            except Exception:
                pass

        # --- Category Diversity Entropy ---
        entropy_features = pd.DataFrame(index=pivot.index)
        try:
            entropy_df = self._compute_category_entropy(scale_base)
            if not entropy_df.empty:
                entropy_df = entropy_df.reindex(pivot.index).fillna(0.0)
                entropy_features["div::entropy"] = entropy_df["category_entropy"].astype(float)
                entropy_features["div::entropy_norm"] = entropy_df["category_entropy_norm"].astype(float)
        except Exception:
            pass

        # --- Seasonality Indicators ---
        season_features = pd.DataFrame(index=pivot.index)
        if not self.strict_view_only:
            try:
                season = self._load_seasonality_features()
                if not season.empty:
                    season = season.reindex(pivot.index).fillna(0.0)
                    for col in season.columns:
                        season_features[f"season::{col}"] = season[col].astype(float)
            except Exception:
                pass

        # --- Network Co-Purchase Features ---
        network_features = pd.DataFrame(index=pivot.index)
        try:
            net = self._compute_network_features(scale_base)
            if not net.empty:
                net = net.reindex(pivot.index).fillna(0.0)
                for col in net.columns:
                    network_features[f"net::{col}"] = net[col].astype(float)
        except Exception:
            pass

        raw_features = pd.concat(
            [mix_rw, scale, rfm_features, velocity_features,
             entropy_features, season_features, network_features],
            axis=1,
        ).fillna(0.0)
        raw_features, fq = self._feature_quality_guardrails(raw_features)
        drift = self._compute_feature_drift(raw_features)
        self._last_cluster_feature_report = {"quality": fq, "drift": drift}

        # ── Group-weighted PCA + UMAP dimensionality reduction ────────────────
        features = self._compress_features_weighted_pca_umap(raw_features)
        return features, pivot, state_map

    def _compress_features_weighted_pca_umap(
        self, features: pd.DataFrame, umap_dims: int = 15
    ) -> pd.DataFrame:
        """
        Step 1 – Group-weighted PCA:
            Each feature namespace (mix, scale, rfm, vel, div, season, net)
            is PCA-compressed independently then scaled by its business priority weight.
            Weights: mix=40 %, rfm=30 %, velocity=20 %, rest share 10 %.

        Step 2 – UMAP:
            Concatenated weighted PCA output is reduced to `umap_dims` dimensions
            to defeat the curse of dimensionality (especially with <200 partners
            and 30-50 raw features).
        """
        from sklearn.decomposition import PCA
        from sklearn.preprocessing import RobustScaler as _RS

        # namespace prefix → business priority weight
        GROUP_WEIGHTS = {
            "mix":    0.40,
            "rfm":    0.30,
            "vel":    0.20,
            "scale":  0.04,
            "div":    0.02,
            "season": 0.02,
            "net":    0.02,
        }

        n_samples = len(features)
        compressed_parts = []

        for prefix, weight in GROUP_WEIGHTS.items():
            cols = [c for c in features.columns if c.startswith(f"{prefix}::")]
            if not cols:
                continue
            sub = features[cols].values.astype(np.float64)
            n_components = max(1, min(len(cols), max(1, n_samples // 6), 8))
            try:
                pca = PCA(n_components=n_components, random_state=42)
                compressed = pca.fit_transform(sub)
            except Exception:
                compressed = sub[:, :n_components]
            compressed = compressed * weight
            compressed_parts.append(compressed)

        if not compressed_parts:
            return features

        X_pca = np.hstack(compressed_parts)

        # UMAP reduction (graceful fallback if umap-learn not installed)
        target_dim = min(umap_dims, X_pca.shape[1], n_samples - 2)
        if target_dim >= X_pca.shape[1]:
            # Already small enough — skip UMAP
            result = pd.DataFrame(X_pca, index=features.index,
                                  columns=[f"pca_{i}" for i in range(X_pca.shape[1])])
            return result

        try:
            import umap
            # Adaptive n_neighbors: sqrt(n) gives good local/global balance.
            # Clamped: min 5 (too low = noisy), max 30 (too high = global structure lost).
            # WHY: default formula n_samples//5 undershoots for large datasets (200+ partners).
            n_neighbors = max(5, min(30, int(np.sqrt(n_samples))))

            # Adaptive min_dist based on dataset size.
            # WHY: small datasets need spread-out embeddings (0.1) to avoid over-compression;
            # large datasets need tighter clustering (0.01) to separate dense groups.
            if n_samples < 50:
                min_dist = 0.10   # spread out — small datasets compress too much
            elif n_samples <= 200:
                min_dist = 0.05   # balanced — typical size
            else:
                min_dist = 0.01   # tighter — large datasets have denser structure

            reducer = umap.UMAP(
                n_components=target_dim,
                n_neighbors=n_neighbors,
                min_dist=min_dist,
                metric="euclidean",
                random_state=42,
                low_memory=True,
            )
            X_umap = reducer.fit_transform(X_pca)
            result = pd.DataFrame(
                X_umap, index=features.index,
                columns=[f"umap_{i}" for i in range(target_dim)]
            )
            print(f"[Clustering] PCA→UMAP: {len(features.columns)} raw → {X_pca.shape[1]} PCA → {target_dim} UMAP dims "
                  f"(n_neighbors={n_neighbors}, min_dist={min_dist})")
        except ImportError:
            # umap-learn not installed — use PCA output directly
            result = pd.DataFrame(X_pca, index=features.index,
                                  columns=[f"pca_{i}" for i in range(X_pca.shape[1])])
            print(f"[Clustering] umap-learn not installed — using {X_pca.shape[1]} weighted-PCA dims (install with: pip install umap-learn)")
        except Exception as exc:
            result = pd.DataFrame(X_pca, index=features.index,
                                  columns=[f"pca_{i}" for i in range(X_pca.shape[1])])
            print(f"[Clustering] UMAP failed ({exc}) — using weighted-PCA dims")

        return result

    @staticmethod
    def _compute_quality_scores(X, labels):
        valid = labels != -1
        unique = np.unique(labels[valid]) if valid.any() else np.array([])
        if len(unique) < 2 or valid.sum() < 5:
            return {"silhouette": None, "calinski_harabasz": None}
        try:
            sil = float(silhouette_score(X[valid], labels[valid]))
        except Exception:
            sil = None
        try:
            ch = float(calinski_harabasz_score(X[valid], labels[valid]))
        except Exception:
            ch = None
        return {"silhouette": sil, "calinski_harabasz": ch}

    def _estimate_stability(self, X, labels, method, runs=5, random_state=42):
        """
        Bootstrap-like stability using ARI on overlapping indices.
        """
        rng = np.random.RandomState(random_state)
        n = X.shape[0]
        if n < 20:
            return None
        base_idx = np.arange(n)
        aris = []
        for _ in range(runs):
            sample_idx = np.sort(rng.choice(base_idx, size=max(10, int(0.8 * n)), replace=False))
            Xs = X[sample_idx]
            if method == "kmeans":
                k = len(np.unique(labels[labels != -1]))
                if k < 2:
                    continue
                model = KMeans(n_clusters=k, random_state=rng.randint(1, 10_000), n_init=10)
                ys = model.fit_predict(Xs)
            else:
                mcs = max(6, int(0.02 * len(sample_idx)))
                ms = max(3, int(mcs // 2))
                model = HDBSCAN(
                    min_cluster_size=mcs,
                    min_samples=ms,
                    metric="euclidean",
                    cluster_selection_method="eom",
                    copy=True,
                )
                ys = model.fit_predict(Xs).astype(int)

            base_subset = labels[sample_idx]
            mask = (base_subset != -1) & (ys != -1)
            if mask.sum() < 8 or len(np.unique(base_subset[mask])) < 2 or len(np.unique(ys[mask])) < 2:
                continue
            try:
                aris.append(float(adjusted_rand_score(base_subset[mask], ys[mask])))
            except Exception:
                continue
        if not aris:
            return None
        return float(np.mean(aris))

    def _growth_kmeans_fallback(self, X, random_state=42):
        """
        Partitioning fallback for growth segment when density clustering is unstable
        or marks too many partners as outliers.
        """
        n = X.shape[0]
        if n < 6:
            return None, {"status": "skipped", "reason": "insufficient_partners"}

        k_max = min(15, max(5, int(np.sqrt(n)) + 3), n - 1)
        candidate_ks = list(range(2, k_max + 1))
        best = None
        tried = []
        for k in candidate_ks:
            try:
                km = KMeans(n_clusters=k, random_state=int(random_state), n_init=10)
                y = km.fit_predict(X).astype(int)
                quality = self._compute_quality_scores(X, y)
                sil = quality.get("silhouette")
                sil_v = float(sil) if sil is not None else -1.0
                ch = quality.get("calinski_harabasz")
                ch_v = float(ch) if ch is not None else 0.0
                score = sil_v + 0.0005 * ch_v
                tried.append(
                    {
                        "k": int(k),
                        "silhouette": round(float(sil_v), 4),
                        "calinski_harabasz": round(float(ch_v), 2),
                        "score": round(float(score), 5),
                    }
                )
                if (best is None) or (score > best["score"]):
                    best = {
                        "labels": y,
                        "k": int(k),
                        "silhouette": sil if sil is not None else None,
                        "calinski_harabasz": ch if ch is not None else None,
                        "score": float(score),
                    }
            except Exception:
                continue

        if best is None:
            return None, {"status": "failed", "reason": "no_valid_kmeans_candidate", "candidates": tried}

        report = {
            "status": "ok",
            "chosen_k": int(best["k"]),
            "silhouette": round(float(best["silhouette"]), 4) if best["silhouette"] is not None else None,
            "calinski_harabasz": round(float(best["calinski_harabasz"]), 2)
            if best["calinski_harabasz"] is not None
            else None,
            "candidates": tried[:20],
        }
        return best["labels"], report

    def _reassign_growth_outliers(self, labels, X, features):
        """
        Reassign selected HDBSCAN outliers to nearest cluster if they are close to
        cluster boundary, with a more permissive rule for high-value partners.
        """
        labels = labels.copy().astype(int)
        out_idx = np.where(labels == -1)[0]
        in_idx = np.where(labels != -1)[0]
        report = {
            "enabled": bool(getattr(self, "cluster_growth_outlier_reassign", True)),
            "initial_outliers": int(len(out_idx)),
            "reassigned_count": 0,
            "reassigned_high_value": 0,
            "final_outliers": int(len(out_idx)),
            "status": "skipped",
        }

        if not report["enabled"]:
            return labels, report
        if len(out_idx) == 0 or len(in_idx) < 3:
            report["status"] = "not_needed"
            return labels, report

        unique_clusters = np.unique(labels[in_idx])
        if len(unique_clusters) < 1:
            report["status"] = "no_reference_clusters"
            return labels, report

        # Less aggressive reassignment: keep genuine outliers as insights
        dist_q = float(getattr(self, "cluster_growth_reassign_distance_quantile", 0.70))
        dist_q = max(0.50, min(0.85, dist_q))
        base_mult = float(getattr(self, "cluster_growth_reassign_distance_multiplier", 0.9))
        high_mult = float(getattr(self, "cluster_growth_reassign_high_value_multiplier", 1.1))
        high_q = float(getattr(self, "cluster_growth_high_value_quantile", 0.80))
        high_q = max(0.50, min(0.95, high_q))

        if "scale::log_total_spend" in features.columns:
            spend_signal = features["scale::log_total_spend"].astype(float)
        else:
            spend_signal = pd.Series(0.0, index=features.index, dtype=float)
        high_cutoff = float(spend_signal.quantile(high_q)) if len(spend_signal) else 0.0

        centroids = {}
        distance_cutoffs = {}
        for c in unique_clusters:
            c_mask = labels == int(c)
            c_points = X[c_mask]
            if c_points.shape[0] == 0:
                continue
            centroid = c_points.mean(axis=0)
            centroids[int(c)] = centroid
            d = np.linalg.norm(c_points - centroid, axis=1)
            if len(d) == 0:
                distance_cutoffs[int(c)] = np.inf
            else:
                distance_cutoffs[int(c)] = float(np.quantile(d, dist_q))

        if not centroids:
            report["status"] = "no_centroids"
            return labels, report

        reassigned = 0
        reassigned_hv = 0
        for ridx in out_idx:
            x = X[ridx]
            dists = {
                c: float(np.linalg.norm(x - centroid))
                for c, centroid in centroids.items()
            }
            if not dists:
                continue
            best_cluster, best_dist = min(dists.items(), key=lambda kv: kv[1])
            cutoff = float(distance_cutoffs.get(best_cluster, np.inf))
            if not np.isfinite(cutoff):
                continue

            partner_name = features.index[ridx]
            is_high_value = bool(float(spend_signal.get(partner_name, 0.0)) >= high_cutoff)
            allowed = cutoff * (high_mult if is_high_value else base_mult)
            if best_dist <= allowed:
                labels[ridx] = int(best_cluster)
                reassigned += 1
                if is_high_value:
                    reassigned_hv += 1

        report["reassigned_count"] = int(reassigned)
        report["reassigned_high_value"] = int(reassigned_hv)
        report["final_outliers"] = int((labels == -1).sum())
        report["status"] = "ok"
        return labels, report

    # ===================================================================
    # ENSEMBLE CLUSTERING ENGINE
    # ===================================================================

    def _run_gmm(self, X, k_range, random_state=42):
        """
        Run Gaussian Mixture Model over a range of K values.
        Returns best labels selected by BIC.
        """
        best = None
        for k in k_range:
            try:
                gmm = GaussianMixture(
                    n_components=k, covariance_type="full",
                    random_state=int(random_state), n_init=3, max_iter=200,
                )
                y = gmm.fit_predict(X).astype(int)
                bic = float(gmm.bic(X))
                if best is None or bic < best["bic"]:
                    best = {"labels": y, "k": k, "bic": bic}
            except Exception:
                continue
        return best

    def _run_spectral(self, X, k_range, random_state=42):
        """
        Run Spectral Clustering over a range of K values.
        Returns best labels selected by silhouette score.
        """
        best = None
        n = X.shape[0]
        # Spectral needs n >= k and enough samples
        for k in k_range:
            if k >= n:
                continue
            try:
                # Use nearest-neighbors affinity for robustness
                n_neighbors = min(max(7, int(0.05 * n)), n - 1)
                sc = SpectralClustering(
                    n_clusters=k, affinity="nearest_neighbors",
                    n_neighbors=n_neighbors,
                    random_state=int(random_state), n_init=5,
                    assign_labels="kmeans",
                )
                y = sc.fit_predict(X).astype(int)
                if len(np.unique(y)) < 2:
                    continue
                sil = float(silhouette_score(X, y))
                if best is None or sil > best["sil"]:
                    best = {"labels": y, "k": k, "sil": sil}
            except Exception:
                continue
        return best

    @staticmethod
    def _build_consensus_matrix(label_sets, n):
        """
        Vectorized consensus matrix — replaces O(n²) nested loop.
        C[i,j] = fraction of clustering runs where partners i and j share a cluster.
        Outlier labels (-1) are excluded. Uses np.equal.outer for 100× speedup.
        """
        C = np.zeros((n, n), dtype=np.float32)
        count = np.zeros((n, n), dtype=np.float32)
        for labels in label_sets:
            labels = np.asarray(labels, dtype=np.int32)
            valid = labels != -1
            # Boolean participation mask: outer AND of valid flags
            both_valid = np.outer(valid, valid)          # (n, n) bool
            # Boolean co-assignment: i and j share the same label
            same_cluster = np.equal.outer(labels, labels)  # (n, n) bool
            count += both_valid.astype(np.float32)
            C     += (both_valid & same_cluster).astype(np.float32)
        with np.errstate(divide="ignore", invalid="ignore"):
            C = np.where(count > 0, C / count, 0.0)
        np.fill_diagonal(C, 1.0)
        return C

    @staticmethod
    def _consensus_labels(consensus_matrix, n_clusters):
        """
        Derive final labels from consensus matrix via hierarchical (Ward) clustering.
        Converts consensus similarity → distance, then cuts the dendrogram.
        """
        distance = 1.0 - consensus_matrix
        np.fill_diagonal(distance, 0.0)
        distance = np.clip(distance, 0, 1)
        try:
            agg = AgglomerativeClustering(
                n_clusters=n_clusters, metric="precomputed",
                linkage="average",
            )
            return agg.fit_predict(distance).astype(int)
        except Exception:
            # Fallback to KMeans on consensus matrix if hierarchical fails
            try:
                km = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
                return km.fit_predict(consensus_matrix).astype(int)
            except Exception:
                return np.zeros(consensus_matrix.shape[0], dtype=int)

    def _select_k_business_aware(self, X, k_range, random_state=42):
        """
        Business-domain-informed K selection using multi-criteria scoring:
        - Silhouette score (separation quality)
        - BIC from GMM (model fit)
        - Gap statistic (vs uniform reference)
        - Business penalty for extreme K
        - Calinski-Harabasz score

        Returns: (best_k, candidates_report)
        """
        n = X.shape[0]
        rng = np.random.RandomState(int(random_state))
        candidates = []

        # Pre-compute reference gap statistic (uniform distribution)
        n_refs = 5
        for k in k_range:
            if k >= n:
                continue
            try:
                # KMeans fit for this k
                km = KMeans(n_clusters=k, random_state=int(random_state), n_init=10)
                y_km = km.fit_predict(X)
                inertia = float(km.inertia_)
                log_inertia = float(np.log(max(inertia, 1e-10)))

                # Silhouette
                if len(np.unique(y_km)) >= 2:
                    sil = float(silhouette_score(X, y_km))
                else:
                    sil = -1.0

                # CH score
                if len(np.unique(y_km)) >= 2:
                    ch = float(calinski_harabasz_score(X, y_km))
                else:
                    ch = 0.0

                # GMM BIC
                try:
                    gmm = GaussianMixture(
                        n_components=k, covariance_type="full",
                        random_state=int(random_state), n_init=2, max_iter=150,
                    )
                    gmm.fit(X)
                    bic = float(gmm.bic(X))
                except Exception:
                    bic = float("inf")

                # Gap statistic: compare log(inertia) vs expected under uniform
                ref_log_inertias = []
                for _ in range(n_refs):
                    X_ref = rng.uniform(
                        low=X.min(axis=0), high=X.max(axis=0), size=X.shape
                    )
                    km_ref = KMeans(n_clusters=k, random_state=rng.randint(1, 99999), n_init=5)
                    km_ref.fit(X_ref)
                    ref_log_inertias.append(float(np.log(max(float(km_ref.inertia_), 1e-10))))
                gap = float(np.mean(ref_log_inertias)) - log_inertia

                # Business penalty: penalize K too small or too large
                # Push ideal_k higher: n=60→8, n=100→9, n=200→11
                ideal_k = max(6, min(int(n ** 0.45), 14))
                # Asymmetric penalty: penalize too FEW clusters more than too MANY
                if k < ideal_k:
                    k_deviation = (ideal_k - k) / max(ideal_k, 1) * 1.5  # 1.5x penalty for too few
                else:
                    k_deviation = (k - ideal_k) / max(ideal_k, 1) * 0.5  # only 0.5x for too many
                business_penalty = min(k_deviation, 1.0)

                candidates.append({
                    "k": int(k),
                    "silhouette": round(sil, 4),
                    "calinski_harabasz": round(ch, 2),
                    "bic": round(bic, 2),
                    "gap_statistic": round(gap, 4),
                    "business_penalty": round(business_penalty, 4),
                })
            except Exception:
                continue

        if not candidates:
            return k_range[0] if k_range else 2, []

        # Normalize each criterion to [0, 1] for composite scoring
        sils = np.array([c["silhouette"] for c in candidates])
        chs = np.array([c["calinski_harabasz"] for c in candidates])
        bics = np.array([c["bic"] for c in candidates])
        gaps = np.array([c["gap_statistic"] for c in candidates])
        bps = np.array([c["business_penalty"] for c in candidates])

        def _norm(arr, invert=False):
            lo, hi = arr.min(), arr.max()
            if np.isclose(lo, hi):
                return np.full_like(arr, 0.5)
            normed = (arr - lo) / (hi - lo)
            return (1.0 - normed) if invert else normed

        n_sil = _norm(sils)           # Higher is better
        n_ch = _norm(chs)             # Higher is better
        n_bic = _norm(bics, invert=True)  # Lower is better
        n_gap = _norm(gaps)           # Higher is better
        n_bp = _norm(bps, invert=True)    # Lower penalty is better

        composite = (
            0.15 * n_sil     # Lower: silhouette always favors K=2-3
            + 0.10 * n_ch
            + 0.20 * n_bic
            + 0.20 * n_gap
            + 0.35 * n_bp    # Higher: enforce business-appropriate granularity
        )

        for i, c in enumerate(candidates):
            c["composite_score"] = round(float(composite[i]), 5)

        best_idx = int(np.argmax(composite))
        return candidates[best_idx]["k"], candidates

    def _ensemble_segment(self, X, features, segment_type, random_state=42):
        """
        Ensemble clustering pipeline:
        - VIP tier:    KMeans + GMM + Spectral → consensus → hierarchical cut
        - Growth tier: HDBSCAN + KMeans + GMM → consensus → hierarchical cut

        Returns: (labels, ensemble_report)
        """
        n = X.shape[0]
        if n < 6:
            return np.zeros(n, dtype=int), {
                "status": "too_few_partners", "n": n, "ensemble_used": False,
            }

        # --- Step 1: Business-rule K selection ---
        # Target ~12 partners per cluster (actionable for sales teams).
        # Algorithms run with this fixed K for label quality.
        import math
        target_cluster_size = int(getattr(self, "cluster_target_size", 12))
        business_k = math.ceil(n / target_cluster_size)
        best_k = max(4, min(business_k, 15, n - 1))
        k_range = list(range(max(2, best_k - 2), min(best_k + 3, n)))
        k_candidates = [{"k": best_k, "method": "business_rule", "target_size": target_cluster_size}]

        # --- Step 2: Run algorithms ALL at the same forced K ---
        label_sets = []
        algo_reports = []

        # Algorithm 1: KMeans at best_k — warm-started from HDBSCAN centroids when
        # available, otherwise falls back to k-means++ random init.
        hdbscan_centroids = None
        if n >= 8:
            try:
                _mcs = max(3, int(round(0.015 * n)))
                _ms  = max(2, _mcs - 1)
                _hdb_pre = HDBSCAN(
                    min_cluster_size=_mcs, min_samples=_ms,
                    metric="euclidean", cluster_selection_method="leaf", copy=True,
                )
                _y_pre = _hdb_pre.fit_predict(X).astype(int)
                _hdb_labels = _y_pre[_y_pre != -1]
                _hdb_X      = X[_y_pre != -1]
                _unique_hdb = np.unique(_hdb_labels)
                if len(_unique_hdb) >= 2:
                    # Build centroids for the HDBSCAN clusters found
                    _centroids = np.vstack([
                        _hdb_X[_hdb_labels == c].mean(axis=0) for c in _unique_hdb
                    ])
                    # If HDBSCAN found a different K than best_k, subsample / pad
                    if len(_centroids) >= best_k:
                        hdbscan_centroids = _centroids[:best_k]
                    else:
                        # Pad with KMeans++ centroids for remaining slots
                        from sklearn.cluster import _kmeans as _km_mod
                        hdbscan_centroids = None  # let k-means++ handle it
            except Exception:
                hdbscan_centroids = None

        try:
            if hdbscan_centroids is not None:
                km = KMeans(
                    n_clusters=best_k, init=hdbscan_centroids,
                    n_init=1, random_state=int(random_state),
                )
                algo_reports.append({"algo": "KMeans", "k": best_k, "init": "hdbscan_centroids", "status": "ok"})
            else:
                km = KMeans(
                    n_clusters=best_k, init="k-means++",
                    n_init=15, random_state=int(random_state),
                )
                algo_reports.append({"algo": "KMeans", "k": best_k, "init": "k-means++", "status": "ok"})
            y_km = km.fit_predict(X).astype(int)
            label_sets.append(y_km)
        except Exception as e:
            algo_reports.append({"algo": "KMeans", "status": "failed", "error": str(e)})

        # Algorithm 2: GMM at best_k (soft boundaries improve label quality)
        try:
            gmm = GaussianMixture(
                n_components=best_k, covariance_type="full" if best_k <= 10 else "diag",
                random_state=int(random_state), n_init=3, max_iter=200,
                reg_covar=1e-4,
            )
            y_gmm = gmm.fit_predict(X).astype(int)
            label_sets.append(y_gmm)
            algo_reports.append({"algo": "GMM", "k": best_k, "status": "ok"})
        except Exception as e:
            algo_reports.append({"algo": "GMM", "status": "failed", "error": str(e)})

        if segment_type == "VIP" and best_k <= 12 and n >= best_k + 2:
            # Spectral at best_k (VIP only, small n)
            try:
                n_neighbors = min(max(5, int(0.08 * n)), n - 1)
                sc = SpectralClustering(
                    n_clusters=best_k, affinity="nearest_neighbors",
                    n_neighbors=n_neighbors, random_state=int(random_state), n_init=10,
                )
                y_sc = sc.fit_predict(X).astype(int)
                label_sets.append(y_sc)
                algo_reports.append({"algo": "Spectral", "k": best_k, "status": "ok"})
            except Exception as e:
                algo_reports.append({"algo": "Spectral", "status": "failed", "error": str(e)})
        elif segment_type == "Growth" and n >= 8:
            # HDBSCAN for density detection only — use to validate, not as final labels
            try:
                base_mcs = max(3, int(round(0.01 * n)))
                base_mcs = min(base_mcs, max(4, int(0.03 * n)))
                ms = max(2, min(base_mcs - 1, 3))
                hdb = HDBSCAN(
                    min_cluster_size=base_mcs, min_samples=ms,
                    metric="euclidean", cluster_selection_method="leaf", copy=True,
                )
                y_hdb = hdb.fit_predict(X).astype(int)
                outlier_ratio = float((y_hdb == -1).mean())
                if outlier_ratio <= 0.25:
                    label_sets.append(y_hdb)
                    algo_reports.append({"algo": "HDBSCAN", "k": int(y_hdb.max() + 1),
                                         "outlier_ratio": outlier_ratio, "status": "ok"})
                else:
                    # Too many outliers — skip HDBSCAN from ensemble
                    algo_reports.append({"algo": "HDBSCAN", "status": "skipped",
                                         "reason": f"too_many_outliers_{outlier_ratio:.2f}"})
            except Exception as e:
                algo_reports.append({"algo": "HDBSCAN", "status": "failed", "error": str(e)})

        # --- Step 3: Final labels ---
        # Primary: KMeans at forced best_k (guaranteed exact K clusters)
        # Secondary: Consensus only if ≥2 algorithms succeeded
        ensemble_used = False
        if label_sets and label_sets[0] is not None:
            # KMeans labels always form the base (exact K)
            primary_labels = label_sets[0]
            if len(label_sets) >= 2:
                # Build consensus from forced-K label sets only (exclude HDBSCAN if it has -1)
                forced_k_sets = [ls for ls in label_sets if not (ls == -1).any()]
                if len(forced_k_sets) >= 2:
                    consensus = self._build_consensus_matrix(forced_k_sets, n)
                    consensus_labels = self._consensus_labels(consensus, best_k)
                    # Verify consensus actually produced best_k clusters
                    if len(np.unique(consensus_labels)) == best_k:
                        final_labels = consensus_labels
                        ensemble_used = True
                    else:
                        final_labels = primary_labels
                else:
                    final_labels = primary_labels
            else:
                final_labels = primary_labels
        else:
            final_labels = np.zeros(n, dtype=int)

        # --- Step 4: Growth segment outlier handling ---
        if segment_type == "Growth" and n >= 8:
            final_labels, reassign_report = self._reassign_growth_outliers(
                final_labels, X, features
            )
        else:
            reassign_report = {}

        # --- Step 5: Quality metrics ---
        quality = self._compute_quality_scores(X, final_labels)
        stability = self._estimate_stability(
            X, final_labels, method="kmeans"  # Use KMeans resampling for consensus stability
        )

        report = {
            "status": "ok",
            "ensemble_used": ensemble_used,
            "n_algorithms_successful": len(label_sets),
            "algorithm_reports": algo_reports,
            "chosen_k": int(best_k),
            "k_selection_method": "business_aware_composite",
            "k_candidates": k_candidates[:15],
            "silhouette": round(float(quality["silhouette"]), 4) if quality["silhouette"] is not None else None,
            "calinski_harabasz": round(float(quality["calinski_harabasz"]), 2) if quality["calinski_harabasz"] is not None else None,
            "stability_ari": round(float(stability), 4) if stability is not None else None,
            "n_partners": int(n),
        }
        if reassign_report:
            report["outlier_reassignment"] = reassign_report

        return final_labels, report

    # ===================================================================
    # TEMPORAL CLUSTER STABILITY TRACKING
    # ===================================================================

    def _match_clusters_hungarian(self, prev_labels, new_labels, prev_index, new_index):
        """
        Match cluster labels across two runs using the Hungarian algorithm.
        Maximizes overlap between previous and new cluster assignments
        for partners present in both runs.
        Returns: mapping dict {new_label: prev_label}
        """
        common = prev_index.intersection(new_index)
        if len(common) < 3:
            return {}

        # Ensure no duplicate index labels before reindex
        prev_labels = prev_labels[~prev_labels.index.duplicated(keep="last")]
        new_labels  = new_labels[~new_labels.index.duplicated(keep="last")]
        common = prev_labels.index.intersection(new_labels.index)
        if len(common) < 3:
            return {}

        prev_sub = prev_labels.reindex(common).dropna()
        new_sub  = new_labels.reindex(common).dropna()
        common_clean = prev_sub.index.intersection(new_sub.index)
        if len(common_clean) < 3:
            return {}

        prev_vals = prev_sub.loc[common_clean].values
        new_vals = new_sub.loc[common_clean].values

        prev_unique = np.unique(prev_vals)
        new_unique = np.unique(new_vals)

        if len(prev_unique) == 0 or len(new_unique) == 0:
            return {}

        # Build cost matrix (negative overlap for minimization)
        cost = np.zeros((len(new_unique), len(prev_unique)), dtype=float)
        for i, nc in enumerate(new_unique):
            for j, pc in enumerate(prev_unique):
                overlap = int(np.sum((new_vals == nc) & (prev_vals == pc)))
                cost[i, j] = -overlap  # Negate for minimization

        try:
            row_ind, col_ind = linear_sum_assignment(cost)
            mapping = {}
            for r, c in zip(row_ind, col_ind):
                if -cost[r, c] > 0:  # Only map if there's actual overlap
                    mapping[str(new_unique[r])] = str(prev_unique[c])
            return mapping
        except Exception:
            return {}

    def _track_temporal_transitions(self, current_matrix):
        """
        Compare current clustering with last approved run to detect:
        - Stable clusters (matched, similar composition)
        - New clusters (no match in previous run)
        - Dissolved clusters (previous clusters not matched)
        - Partner transitions (promoted to VIP, demoted, etc.)
        """
        report = {
            "status": "no_previous_run",
            "cluster_mapping": {},
            "stable_clusters": [],
            "new_clusters": [],
            "dissolved_clusters": [],
            "partner_transitions": {},
            "stability_score": None,
        }

        if not hasattr(self, "cluster_repo") or self.cluster_repo is None:
            return report

        # Load last approved assignments
        try:
            prev = self.cluster_repo.load_last_approved_assignments()
        except Exception:
            prev = None

        if prev is None or prev.empty or "cluster_label" not in prev.columns:
            return report

        if current_matrix is None or current_matrix.empty or "cluster_label" not in current_matrix.columns:
            report["status"] = "no_current_data"
            return report

        prev_labels = prev["cluster_label"].astype(str)
        new_labels = current_matrix["cluster_label"].astype(str)

        # ── Deduplicate: index must be unique for reindex/intersection to work ──
        prev_labels = prev_labels[~prev_labels.index.duplicated(keep="last")]
        new_labels  = new_labels[~new_labels.index.duplicated(keep="last")]

        # Match clusters via Hungarian algorithm
        mapping = self._match_clusters_hungarian(
            prev_labels, new_labels, prev_labels.index, new_labels.index
        )
        report["cluster_mapping"] = mapping

        # Identify stable, new, and dissolved clusters
        new_clusters_set = set(new_labels.unique())
        prev_clusters_set = set(prev_labels.unique())
        matched_new = set(mapping.keys())
        matched_prev = set(mapping.values())

        report["stable_clusters"] = sorted(list(matched_new))
        report["new_clusters"] = sorted(list(new_clusters_set - matched_new))
        report["dissolved_clusters"] = sorted(list(prev_clusters_set - matched_prev))

        # Track partner-level transitions
        common_partners = prev.index.intersection(current_matrix.index)
        transitions = {"stable": 0, "promoted": 0, "demoted": 0, "reassigned": 0}
        transition_details = []

        for partner in common_partners:
            prev_label = str(prev_labels.get(partner, ""))
            new_label = str(new_labels.get(partner, ""))
            prev_type = str(prev.get("cluster_type", pd.Series(dtype=str)).get(partner, ""))
            new_type = str(current_matrix.get("cluster_type", pd.Series(dtype=str)).get(partner, ""))

            if prev_label == new_label or mapping.get(new_label) == prev_label:
                transitions["stable"] += 1
            elif prev_type == "Growth" and new_type == "VIP":
                transitions["promoted"] += 1
                transition_details.append({"partner": partner, "from": prev_label, "to": new_label, "type": "promoted"})
            elif prev_type == "VIP" and new_type == "Growth":
                transitions["demoted"] += 1
                transition_details.append({"partner": partner, "from": prev_label, "to": new_label, "type": "demoted"})
            else:
                transitions["reassigned"] += 1

        report["partner_transitions"] = transitions
        report["transition_details"] = transition_details[:50]  # Cap for report size

        # Stability score: fraction of partners that stayed in matched clusters
        total_common = len(common_partners) if len(common_partners) > 0 else 1
        report["stability_score"] = round(
            float(transitions["stable"]) / total_common, 4
        )
        report["status"] = "ok"
        return report

    def get_temporal_cluster_report(self):
        """Return the temporal cluster stability report from the last run."""
        return dict(getattr(self, "temporal_cluster_report", {})) or {}

    # ===================================================================
    # PROCESS SEGMENT (ENSEMBLE-POWERED)
    # ===================================================================

    def _process_segment(self, subset_df, method="hdbscan"):
        """
        Run ensemble clustering on a partner subset and return:
        - partner-level metadata
        - segment quality report
        """
        features, pivot, state_map = self._build_cluster_features(subset_df)
        if features.empty:
            return (
                pd.DataFrame(columns=["cluster", "cluster_type", "cluster_label", "strategic_tag"]),
                {"status": "empty"},
            )

        scaler = RobustScaler()
        X = scaler.fit_transform(features.values)
        n = len(features)

        segment_type = "VIP" if method == "kmeans" else "Growth"

        # Use ensemble pipeline
        labels, seg_report = self._ensemble_segment(X, features, segment_type)
        seg_report["method"] = f"ensemble_{segment_type.lower()}"

        if segment_type == "VIP":
            cluster = pd.Series((1000 + labels).astype(int), index=features.index)
            cluster_type = "VIP"
            cluster_label = cluster.map(lambda v: f"VIP-{v - 1000}")
        else:
            cluster = pd.Series(labels, index=features.index)
            cluster_type = "Growth"
            cluster_label = cluster.map(lambda v: f"Growth-{v}" if v != -1 else "Uncategorized")
            seg_report["outlier_ratio"] = round(float((labels == -1).mean()), 4)

        top_group = pivot.idxmax(axis=1)
        strategic_tag = top_group.map(
            lambda g: f"{cluster_type} focus: {g}" if pd.notna(g) else f"{cluster_type} mixed"
        )

        out = pd.DataFrame(
            {
                "cluster": cluster,
                "cluster_type": cluster_type,
                "cluster_label": cluster_label,
                "strategic_tag": strategic_tag,
                "state": state_map,
            }
        )
        return out.drop(columns=["state"]), seg_report

    # ===================================================================
    # AUTO-GENERATED CLUSTER LABELS
    # ===================================================================

    def _build_cluster_centroid_profile(self, matrix):
        """
        Build a human-readable profile for each cluster based on:
        - Top product categories (spend share)
        - Scale metrics (avg spend, breadth)
        - Partner count
        Returns dict: {cluster_label: profile_string}
        """
        if matrix is None or matrix.empty:
            return {}

        meta_cols = {"state", "cluster", "cluster_type", "cluster_label", "strategic_tag"}
        # Strictly numeric only — matrix can contain date/object cols from view_ml_input
        product_cols = [
            c for c in matrix.columns
            if c not in meta_cols
            and pd.api.types.is_numeric_dtype(matrix[c])
        ]
        if not product_cols:
            return {}

        profiles = {}
        cluster_labels = matrix["cluster_label"].unique()

        for label in cluster_labels:
            label_str = str(label)
            if "Outlier" in label_str:
                continue

            members = matrix[matrix["cluster_label"] == label]
            n_partners = len(members)
            if n_partners == 0:
                continue

            cluster_type = str(members["cluster_type"].iloc[0])

            # Category spend analysis
            spend = members[product_cols].mean().sort_values(ascending=False)
            total_mean_spend = float(spend.sum())
            if total_mean_spend <= 0:
                continue

            # Top categories with share
            top_cats = []
            for cat, val in spend.head(5).items():
                share = (float(val) / total_mean_spend * 100) if total_mean_spend > 0 else 0
                if share > 2:  # Only include meaningful categories
                    top_cats.append(f"{cat} ({share:.0f}%)")

            # Scale classification
            if total_mean_spend > spend.quantile(0.75).sum() if len(spend) > 0 else 0:
                spend_level = "High-spend"
            elif total_mean_spend > spend.quantile(0.25).sum() if len(spend) > 0 else 0:
                spend_level = "Medium-spend"
            else:
                spend_level = "Low-spend"

            # Portfolio breadth
            active_cats = int((members[product_cols] > 0).mean(axis=0).gt(0.3).sum())
            if active_cats >= 6:
                breadth = "diversified portfolio"
            elif active_cats >= 3:
                breadth = "moderate portfolio"
            else:
                breadth = "focused/narrow portfolio"

            # Concentration
            spend_shares = spend / total_mean_spend
            hhi = float((spend_shares ** 2).sum())
            if hhi > 0.5:
                concentration = "highly concentrated in few categories"
            elif hhi > 0.25:
                concentration = "moderately concentrated"
            else:
                concentration = "well-distributed across categories"

            profile = (
                f"Cluster '{label_str}' ({cluster_type} tier, {n_partners} partners): "
                f"{spend_level}, {breadth}, {concentration}. "
                f"Top categories: {', '.join(top_cats[:4]) if top_cats else 'varied'}."
            )
            profiles[label_str] = profile

        return profiles

    def _generate_cluster_labels_llm(self, profiles):
        """
        Use OpenAI to generate business-meaningful cluster labels from centroid profiles.
        Returns dict: {old_label: new_label}
        """
        if not profiles:
            return {}

        key = str(getattr(self, "openai_api_key", "") or "").strip()
        model = str(getattr(self, "openai_model", "gpt-4o")).strip()
        if not key:
            return {}

        profiles_text = "\n".join(
            f"- {label}: {desc}" for label, desc in profiles.items()
        )

        prompt = f"""You are a business intelligence analyst. Based on these cluster profiles from a B2B distribution company, generate short, descriptive, business-meaningful labels for each cluster.

Cluster profiles:
{profiles_text}

Rules:
1. Each label must be 2-4 words, title-cased
2. Labels should describe the BUSINESS BEHAVIOR of the cluster (e.g., "Premium Diversified Buyers", "Niche Category Specialists", "High-Volume Core Clients")
3. Keep the tier prefix (VIP or Growth) but replace the generic number
4. Do NOT use generic labels like "Cluster A" or "Group 1"

Respond ONLY with a valid JSON object. No explanation, no markdown fences. Example:
{{
  "VIP-0": "VIP — Premium Multi-Category Leaders",
  "Growth-1": "Growth — Emerging Niche Specialists"
}}"""

        try:
            text_out, err = self._call_gemini_recommendation(
                prompt=prompt, api_key=key, model=model
            )
            if err or not text_out:
                return {}

            # Extract JSON from response — handle both raw JSON and ```-fenced output
            text_clean = text_out.strip()
            if "```" in text_clean:
                lines = text_clean.split("\n")
                text_clean = "\n".join(
                    l for l in lines if not l.strip().startswith("```")
                ).strip()
            # Find JSON boundaries in case LLM prepended/appended prose
            start = text_clean.find("{")
            end   = text_clean.rfind("}") + 1
            if start != -1 and end > start:
                text_clean = text_clean[start:end]
            mapping = json.loads(text_clean)
            if not isinstance(mapping, dict):
                return {}

            # Validate: labels must be meaningful strings (3– 80 chars)
            result = {}
            for old, new in mapping.items():
                if isinstance(new, str) and 3 <= len(new.strip()) <= 80:
                    result[str(old)] = new.strip()
            return result
        except Exception:
            return {}

    def _generate_cluster_labels_heuristic(self, profiles):
        """
        Generate business-meaningful cluster labels without LLM, using centroid profiles.

        Labels use recognizable business archetypes (Strategic Accounts, Category Champions,
        Win-Back Targets, etc.) rather than generic descriptors.
        Fallback when OpenAI API key is not available.
        """
        if not profiles:
            return {}

        # Business archetype definitions.
        # Each archetype is matched by a combination of spend level + breadth + concentration.
        # Priority order: more specific matches take precedence.
        ARCHETYPES = [
            # VIP archetypes
            ("VIP",    "High-spend",   "diversified",      None,               "Strategic Accounts"),
            ("VIP",    "High-spend",   None,               "highly concentrated", "Category Champions"),
            ("VIP",    "High-spend",   "moderate",         None,               "Core Revenue Drivers"),
            ("VIP",    "High-spend",   "focused",          None,               "Anchor Specialists"),
            ("VIP",    "Medium-spend", "diversified",      None,               "Emerging Power Buyers"),
            ("VIP",    "Medium-spend", None,               None,               "Steady Contributors"),
            ("VIP",    "Low-spend",    None,               None,               "Rising VIPs"),
            # Growth archetypes
            ("Growth", None,           None,               None,               None),  # fallthrough
        ]
        GROWTH_ARCHETYPES = [
            ("High-spend",   "diversified",  None,               "High-Growth Partners"),
            ("High-spend",   None,           "highly concentrated", "Niche Power Players"),
            ("High-spend",   None,           None,               "High-Volume Accounts"),
            ("Medium-spend", "diversified",  None,               "Balanced Growth Partners"),
            ("Medium-spend", "focused",      None,               "Category Growth Specialists"),
            ("Medium-spend", None,           None,               "Mid-Tier Growing Accounts"),
            ("Low-spend",    None,           None,               "Win-Back Targets"),
        ]

        result = {}
        seen_labels = {}   # base_label → first cluster_num that used it

        for label, profile in profiles.items():
            parts = label.split("-", 1)
            tier = parts[0] if parts else "Cluster"   # "VIP" or "Growth"
            cluster_num = parts[1] if len(parts) > 1 else "0"

            # Extract profile signals
            is_high   = "High-spend" in profile
            is_med    = "Medium-spend" in profile
            is_low    = "Low-spend" in profile
            is_div    = "diversified" in profile
            is_mod    = "moderate" in profile
            is_foc    = "focused" in profile or "narrow" in profile
            is_conc   = "highly concentrated" in profile
            is_well   = "well-distributed" in profile

            spend_level = "High-spend" if is_high else ("Medium-spend" if is_med else "Low-spend")
            breadth_str = "diversified" if is_div else ("moderate" if is_mod else ("focused" if is_foc else None))
            conc_str    = "highly concentrated" if is_conc else None

            # Match archetype
            archetype_name = None

            if tier == "VIP":
                for (t, sp, br, cn, name) in ARCHETYPES:
                    if t != "VIP":
                        continue
                    if sp and sp not in profile:
                        continue
                    if br and br not in profile:
                        continue
                    if cn and cn not in profile:
                        continue
                    archetype_name = name
                    break
                if archetype_name is None:
                    archetype_name = "Key Accounts"

            else:  # Growth
                for (sp, br, cn, name) in GROWTH_ARCHETYPES:
                    if sp and sp not in profile:
                        continue
                    if br and br not in profile:
                        continue
                    if cn and cn not in profile:
                        continue
                    archetype_name = name
                    break
                if archetype_name is None:
                    archetype_name = "Developing Partners"

            base_label = f"{tier} — {archetype_name}"

            # Deduplicate: if this base_label was already used, append cluster number
            if base_label in seen_labels:
                new_label = f"{base_label} {cluster_num}"
            else:
                new_label = base_label
                seen_labels[base_label] = cluster_num

            result[label] = new_label

        return result

    def _auto_label_clusters(self, matrix):
        """
        Orchestrator: try LLM labeling first, fall back to heuristic.
        Updates matrix cluster_label in place and returns label_report.
        """
        profiles = self._build_cluster_centroid_profile(matrix)
        if not profiles:
            return {"status": "no_profiles", "method": None, "labels": {}}

        # Try LLM first
        llm_labels = self._generate_cluster_labels_llm(profiles)
        if llm_labels and len(llm_labels) >= len(profiles) * 0.5:
            method = "openai_llm"
            label_map = llm_labels
        else:
            # Heuristic fallback
            label_map = self._generate_cluster_labels_heuristic(profiles)
            method = "heuristic"

        if label_map:
            # Apply new labels to matrix
            matrix["cluster_label"] = matrix["cluster_label"].map(
                lambda x: label_map.get(str(x), x)
            )
            # Also update strategic_tag to include new label
            matrix["strategic_tag"] = matrix.apply(
                lambda row: f"{label_map.get(str(row.get('cluster_label', '')), row.get('strategic_tag', ''))}"
                if str(row.get("cluster_label", "")) in label_map
                else row.get("strategic_tag", ""),
                axis=1,
            )

        return {
            "status": "ok",
            "method": method,
            "labels": label_map,
            "profiles_generated": len(profiles),
            "labels_applied": len(label_map),
        }

    def _cluster_quality_gate(self, report):
        if not report or report.get("status") != "ok":
            return False, "Cluster report unavailable."
        cluster_count = int(report.get("cluster_count", 0) or 0)
        if cluster_count < int(self.cluster_min_count):
            return False, f"Cluster count too low ({cluster_count})."

        outlier_ratio = report.get("outlier_ratio", None)
        if outlier_ratio is not None:
            outlier_ratio = float(outlier_ratio)
            if outlier_ratio < float(self.cluster_outlier_min) or outlier_ratio > float(
                self.cluster_outlier_max
            ):
                return False, f"Outlier ratio {outlier_ratio:.3f} outside gate."

        vip = report.get("vip_summary", {}) or {}
        growth = report.get("growth_summary", {}) or {}
        for tag, seg in [("VIP", vip), ("Growth", growth)]:
            s = seg.get("stability_ari", None)
            if s is not None and float(s) < float(self.cluster_min_stability):
                return False, f"{tag} stability_ari {float(s):.3f} below gate."

        return True, "Quality gate passed."

    def _persist_cluster_run(self, approved, reject_reason):
        payload = {
            "status": "ok" if approved else "rejected",
            "approved": bool(approved),
            "reject_reason": reject_reason,
            "vip_method": (self.cluster_quality_report.get("vip_summary") or {}).get("method"),
            "vip_chosen_k": (self.cluster_quality_report.get("vip_summary") or {}).get("chosen_k"),
            "vip_silhouette": (self.cluster_quality_report.get("vip_summary") or {}).get(
                "silhouette"
            ),
            "vip_calinski_harabasz": (self.cluster_quality_report.get("vip_summary") or {}).get(
                "calinski_harabasz"
            ),
            "vip_stability_ari": (self.cluster_quality_report.get("vip_summary") or {}).get(
                "stability_ari"
            ),
            "growth_method": (self.cluster_quality_report.get("growth_summary") or {}).get(
                "method"
            ),
            "growth_min_cluster_size": (
                self.cluster_quality_report.get("growth_summary") or {}
            ).get("min_cluster_size"),
            "growth_min_samples": (self.cluster_quality_report.get("growth_summary") or {}).get(
                "min_samples"
            ),
            "growth_outlier_ratio": (
                self.cluster_quality_report.get("growth_summary") or {}
            ).get("outlier_ratio"),
            "growth_silhouette": (self.cluster_quality_report.get("growth_summary") or {}).get(
                "silhouette"
            ),
            "growth_calinski_harabasz": (
                self.cluster_quality_report.get("growth_summary") or {}
            ).get("calinski_harabasz"),
            "growth_stability_ari": (
                self.cluster_quality_report.get("growth_summary") or {}
            ).get("stability_ari"),
            "global_outlier_ratio": self.cluster_quality_report.get("outlier_ratio"),
            "global_cluster_count": self.cluster_quality_report.get("cluster_count"),
        }
        run_id = self.cluster_repo.save_run(payload)
        if approved and run_id is not None and self.matrix is not None and not self.matrix.empty:
            assign = self.matrix[
                ["cluster", "cluster_type", "cluster_label", "strategic_tag"]
            ].copy()
            self.cluster_repo.save_assignments(run_id, assign)
        return run_id

    def _build_cluster_quality_report(self, matrix):
        if matrix is None or matrix.empty or "cluster_label" not in matrix.columns:
            return {"status": "empty"}

        non_outlier_mask = ~matrix["cluster_label"].astype(str).str.contains(
            "Outlier", case=False, na=False
        )
        cluster_sizes = (
            matrix.loc[non_outlier_mask, "cluster_label"].astype(str).value_counts()
            if non_outlier_mask.any()
            else pd.Series(dtype=float)
        )

        entropy = None
        if not cluster_sizes.empty:
            p = cluster_sizes / cluster_sizes.sum()
            entropy = float(-(p * np.log2(p)).sum())

        return {
            "status": "ok",
            "partner_count": int(len(matrix)),
            "cluster_count": int(cluster_sizes.shape[0]),
            "outlier_count": int((~non_outlier_mask).sum()),
            "outlier_ratio": round(float((~non_outlier_mask).mean()), 4),
            "cluster_entropy": round(entropy, 4) if entropy is not None else None,
            "largest_cluster_size": int(cluster_sizes.max()) if not cluster_sizes.empty else 0,
            "smallest_cluster_size": int(cluster_sizes.min()) if not cluster_sizes.empty else 0,
            "vip_summary": self.cluster_quality_report.get("vip_summary", {}),
            "growth_summary": self.cluster_quality_report.get("growth_summary", {}),
        }

    def run_cluster_business_validation(self, target_fraction=0.2, random_state=42):
        """
        Business validation of clustering utility.
        Compares a cluster-guided targeting strategy against simple baselines.
        """
        if (
            self.matrix is None
            or self.matrix.empty
            or self.df_partner_features is None
            or self.df_partner_features.empty
        ):
            self.cluster_business_validation_report = {"status": "failed", "reason": "Missing cluster/features data."}
            return self.cluster_business_validation_report

        pf = self.df_partner_features.copy()
        idx = self.matrix.index.intersection(pf.index)
        if idx.empty:
            self.cluster_business_validation_report = {"status": "failed", "reason": "No overlapping partners."}
            return self.cluster_business_validation_report

        df = self.matrix.loc[idx, ["cluster_label", "cluster_type", "strategic_tag"]].join(pf, how="left")
        required_defaults = {
            "degrowth_flag": False,
            "estimated_monthly_loss": 0.0,
            "recent_90_revenue": 0.0,
            "growth_rate_90d": 0.0,
            "churn_probability": 0.0,
            "credit_risk_score": 0.0,
        }
        for col, default in required_defaults.items():
            if col not in df.columns:
                df[col] = default

        df["degrowth_flag"] = df["degrowth_flag"].fillna(False).astype(bool)
        df["estimated_monthly_loss"] = df["estimated_monthly_loss"].fillna(0.0).astype(float)
        df["recent_90_revenue"] = df["recent_90_revenue"].fillna(0.0).astype(float)
        df["growth_rate_90d"] = df["growth_rate_90d"].fillna(0.0).astype(float)
        df["churn_probability"] = df["churn_probability"].fillna(0.0).astype(float)
        df["credit_risk_score"] = df["credit_risk_score"].fillna(0.0).astype(float)

        cluster_kpis = (
            df.groupby("cluster_label")
            .agg(
                partners=("cluster_label", "count"),
                degrowth_rate=("degrowth_flag", "mean"),
                avg_recent_90_revenue=("recent_90_revenue", "mean"),
                avg_growth_rate_90d=("growth_rate_90d", "mean"),
                avg_churn_probability=("churn_probability", "mean"),
                avg_credit_risk_score=("credit_risk_score", "mean"),
                total_est_monthly_loss=("estimated_monthly_loss", "sum"),
            )
            .reset_index()
        )
        cluster_kpis["degrowth_rate"] = (cluster_kpis["degrowth_rate"] * 100.0).round(2)
        cluster_kpis = cluster_kpis.sort_values(
            by=["total_est_monthly_loss", "avg_churn_probability"],
            ascending=[False, False],
        )

        n = len(df)
        k = max(1, int(round(float(target_fraction) * n)))
        rng = np.random.RandomState(int(random_state))

        # Cluster-guided strategy: prioritize clusters with high churn + loss, then partner-level risk.
        cluster_rank = (
            df.groupby("cluster_label")
            .agg(
                cluster_churn=("churn_probability", "mean"),
                cluster_loss=("estimated_monthly_loss", "sum"),
            )
            .sort_values(by=["cluster_churn", "cluster_loss"], ascending=[False, False])
        )
        cluster_order = cluster_rank.index.tolist()
        guided = (
            df.assign(
                _cluster_rank=df["cluster_label"].map({c: i for i, c in enumerate(cluster_order)}),
                _partner_score=0.7 * df["churn_probability"] + 0.3 * self._safe_ratio(df["estimated_monthly_loss"], np.maximum(df["estimated_monthly_loss"].max(), 1.0)),
            )
            .sort_values(by=["_cluster_rank", "_partner_score"], ascending=[True, False])
            .head(k)
        )

        top_rev = df.sort_values(by=["recent_90_revenue"], ascending=False).head(k)
        random_sel = df.sample(n=k, random_state=rng)

        def _eval(sample):
            return {
                "selected_partners": int(len(sample)),
                "hit_rate_degrowth_pct": round(float(sample["degrowth_flag"].mean() * 100.0), 2) if len(sample) else 0.0,
                "captured_est_monthly_loss": round(float(sample["estimated_monthly_loss"].sum()), 2),
                "avg_churn_probability": round(float(sample["churn_probability"].mean()), 4) if len(sample) else 0.0,
            }

        comparison = {
            "cluster_guided": _eval(guided),
            "top_revenue_baseline": _eval(top_rev),
            "random_baseline": _eval(random_sel),
        }

        self.cluster_business_validation_report = {
            "status": "ok",
            "target_fraction": float(target_fraction),
            "target_count": int(k),
            "cluster_kpis": cluster_kpis.to_dict(orient="records"),
            "comparison": comparison,
        }
        return self.cluster_business_validation_report

    def get_cluster_business_validation_report(self):
        return (
            dict(self.cluster_business_validation_report)
            if self.cluster_business_validation_report
            else {}
        )

    def run_clustering(self):
        """Tiered strategy: adaptive VIP tier -> KMeans, remaining tier -> HDBSCAN hybrid."""
        if self.df_ml is None:
            self.ensure_core_loaded()

        # ── Choose clustering data source ──────────────────────────────────────
        # df_recent_group_spend is long-format (company_name × group_name × total_spend)
        # which _build_cluster_features requires for category-mix features.
        # df_ml (view_ml_input) is a partner-level summary — no group_name column.
        _cluster_src = None
        if (
            self.df_recent_group_spend is not None
            and not self.df_recent_group_spend.empty
            and "group_name" in self.df_recent_group_spend.columns
        ):
            _cluster_src = self.df_recent_group_spend

        # Revenue ranking: use cluster_src if available, else df_ml
        _rank_src = _cluster_src if _cluster_src is not None else self.df_ml
        _rev_col = next(
            (c for c in ["total_spend", "total_revenue"] if c in _rank_src.columns),
            None,
        )
        if _rev_col:
            partner_totals = (
                _rank_src.groupby("company_name")[_rev_col].sum().sort_values(ascending=False)
            )
        else:
            _num = _rank_src.select_dtypes(include="number")
            partner_totals = (
                _rank_src[["company_name"]]
                .join(_num)
                .groupby("company_name")
                .sum()
                .sum(axis=1)
                .sort_values(ascending=False)
            )
        n_partners = int(len(partner_totals))
        if n_partners == 0:
            self.matrix = pd.DataFrame()
            self.cluster_quality_report = {"status": "empty", "reason": "No partners available for clustering."}
            return self.matrix

        # Pareto-based VIP split: partners whose cumulative spend
        # covers the top revenue share are VIP, capped at 35% of partners.
        vip_revenue_share = float(getattr(self, "cluster_vip_revenue_share", 0.60))
        vip_max_share = float(getattr(self, "cluster_vip_max_share", 0.35))
        vip_min_count = max(3, int(round(0.08 * n_partners)))
        vip_max_count = max(vip_min_count + 1, int(round(vip_max_share * n_partners)))

        cumulative_spend = partner_totals.cumsum() / partner_totals.sum()
        # Partners whose cumulative contribution reaches the revenue share
        vip_by_revenue = cumulative_spend[cumulative_spend <= vip_revenue_share].index.tolist()
        # Always include at least the top partner for the threshold crossover
        if len(vip_by_revenue) < len(cumulative_spend):
            vip_by_revenue.append(cumulative_spend.index[len(vip_by_revenue)])

        # Apply min/max bounds
        if len(vip_by_revenue) < vip_min_count:
            vip_by_revenue = partner_totals.head(vip_min_count).index.tolist()
        elif len(vip_by_revenue) > vip_max_count:
            vip_by_revenue = partner_totals.head(vip_max_count).index.tolist()

        vip_names = pd.Index(vip_by_revenue)
        mass_names = partner_totals.index.difference(vip_names)
        if len(mass_names) < 2 and n_partners >= 6:
            # Force at least 30% into Growth tier
            forced_vip_n = max(3, int(round(0.70 * n_partners)))
            vip_names = partner_totals.head(forced_vip_n).index
            mass_names = partner_totals.index.difference(vip_names)

        # Use long-format group spend for clustering (has group_name + total_spend)
        _src = _cluster_src if _cluster_src is not None else self.df_ml
        df_vip = _src[_src["company_name"].isin(vip_names)]
        df_mass = _src[_src["company_name"].isin(mass_names)]

        vip_meta, vip_report = self._process_segment(df_vip, method="kmeans")
        growth_meta, growth_report = self._process_segment(df_mass, method="hdbscan")
        cluster_meta = pd.concat([vip_meta, growth_meta], axis=0)

        # Build matrix from the long-format source (group_name → columns, spend → values)
        _matrix_src = _cluster_src if _cluster_src is not None else self.df_ml
        _pivot_val = next(
            (c for c in ["total_spend", "total_revenue"] if c in _matrix_src.columns),
            None,
        )
        if _pivot_val and "group_name" in _matrix_src.columns:
            self.matrix = _matrix_src.pivot_table(
                index="company_name",
                columns="group_name",
                values=_pivot_val,
                aggfunc="sum",
                fill_value=0,
            )
            # Deduplicate matrix index
            self.matrix = self.matrix[~self.matrix.index.duplicated(keep="last")]
        else:
            self.matrix = (
                _matrix_src.set_index("company_name")
                if "company_name" in _matrix_src.columns
                else _matrix_src.copy()
            )
        # Attach state — prefer df_ml (joined with master_state) over cluster_src
        _state_src = self.df_ml if "state" in self.df_ml.columns else _matrix_src
        if "state" in _state_src.columns and "company_name" in _state_src.columns:
            self.matrix["state"] = (
                _state_src[["company_name", "state"]]
                .drop_duplicates("company_name")
                .set_index("company_name")["state"]
                .reindex(self.matrix.index)
                .fillna("Unknown")
            )
        else:
            self.matrix["state"] = "Unknown"

        self.matrix["cluster"] = (
            cluster_meta["cluster"].reindex(self.matrix.index).fillna(-1).astype(int)
        )
        self.matrix["cluster_type"] = (
            cluster_meta["cluster_type"].reindex(self.matrix.index).fillna("Growth")
        )
        self.matrix["cluster_label"] = (
            cluster_meta["cluster_label"].reindex(self.matrix.index).fillna("Uncategorized")
        )
        self.matrix["strategic_tag"] = (
            cluster_meta["strategic_tag"].reindex(self.matrix.index).fillna("Growth mixed")
        )

        # Auto-generate business-meaningful cluster labels
        auto_label_report = self._auto_label_clusters(self.matrix)

        self.cluster_quality_report = {
            "vip_summary": vip_report,
            "growth_summary": growth_report,
            "auto_labeling": auto_label_report,
            "feature_report": getattr(self, "_last_cluster_feature_report", {}),
            "tiering": {
                "method": "pareto_revenue_split",
                "vip_revenue_share_target": round(float(vip_revenue_share), 4),
                "vip_max_partner_share": round(float(vip_max_share), 4),
                "vip_count": int(len(vip_names)),
                "growth_count": int(len(mass_names)),
                "vip_partner_pct": round(float(len(vip_names)) / max(n_partners, 1), 4),
            },
        }
        self.cluster_quality_report.update(self._build_cluster_quality_report(self.matrix))
        approved, reason = self._cluster_quality_gate(self.cluster_quality_report)
        self.cluster_quality_report["quality_gate"] = {
            "approved": bool(approved),
            "reason": reason,
        }
        self._persist_cluster_run(approved=approved, reject_reason=None if approved else reason)

        if not approved:
            fallback = self.cluster_repo.load_last_approved_assignments()
            if fallback is not None and not fallback.empty:
                for c in ["cluster", "cluster_type", "cluster_label", "strategic_tag"]:
                    if c in fallback.columns:
                        self.matrix[c] = fallback[c].reindex(self.matrix.index).fillna(
                            self.matrix[c]
                        )
                self.cluster_quality_report["fallback_applied"] = True
                self.cluster_quality_report["fallback_reason"] = reason
            else:
                self.cluster_quality_report["fallback_applied"] = False
                self.cluster_quality_report["fallback_reason"] = "No approved historical run found."
        # Temporal cluster stability tracking
        self.temporal_cluster_report = self._track_temporal_transitions(self.matrix)
        self.cluster_quality_report["temporal_tracking"] = self.temporal_cluster_report

        # Refresh business validation snapshot on each cluster run.
        self.run_cluster_business_validation()
        return self.matrix

    def get_cluster_quality_report(self):
        return dict(self.cluster_quality_report) if self.cluster_quality_report else {}

    def _get_live_baseline_value(self, partner_name, column_name):
        if (
            self.df_live_scores is None
            or self.df_live_scores.empty
            or partner_name not in self.df_live_scores.index
            or column_name not in self.df_live_scores.columns
        ):
            return np.nan
        try:
            val = self.df_live_scores.loc[partner_name, column_name]
            if isinstance(val, pd.Series):
                val = val.iloc[0]
            return float(val)
        except Exception:
            return np.nan

    def _compute_partner_alerts(self, partner_name, facts):
        alerts = []

        drop = float(facts.get("revenue_drop_pct", 0.0) or 0.0)
        degrowth_threshold = float(facts.get("degrowth_threshold_pct", 20.0) or 20.0)
        sharp_drop_threshold = max(
            float(getattr(self, "alert_revenue_drop_sharp_pct", 35.0)),
            degrowth_threshold,
        )
        if drop >= sharp_drop_threshold:
            severity = "critical" if drop >= (sharp_drop_threshold + 15.0) else "high"
            alerts.append(
                {
                    "code": "sharp_revenue_drop",
                    "severity": severity,
                    "title": "Sharp Revenue Drop",
                    "message": f"Revenue drop is {drop:.1f}%, above sharp-drop threshold {sharp_drop_threshold:.1f}%.",
                    "value": round(drop, 2),
                    "threshold": round(sharp_drop_threshold, 2),
                    "delta": None,
                }
            )

        churn_now = float(facts.get("churn_probability", 0.0) or 0.0)
        churn_prev = self._get_live_baseline_value(partner_name, "churn_probability")
        if np.isfinite(churn_prev):
            churn_delta = churn_now - float(churn_prev)
            if (
                churn_delta >= float(getattr(self, "alert_churn_jump_delta", 0.15))
                and churn_now >= float(getattr(self, "alert_churn_high_level", 0.45))
            ):
                alerts.append(
                    {
                        "code": "high_churn_jump",
                        "severity": "high",
                        "title": "High Churn Jump",
                        "message": (
                            f"Churn probability jumped from {float(churn_prev) * 100:.1f}% to "
                            f"{churn_now * 100:.1f}%."
                        ),
                        "value": round(churn_now, 4),
                        "threshold": round(
                            float(getattr(self, "alert_churn_high_level", 0.45)),
                            4,
                        ),
                        "delta": round(churn_delta, 4),
                    }
                )

        credit_now = float(facts.get("credit_risk_score", 0.0) or 0.0)
        credit_prev = self._get_live_baseline_value(partner_name, "credit_risk_score")
        if np.isfinite(credit_prev):
            credit_delta = credit_now - float(credit_prev)
            if (
                credit_delta >= float(getattr(self, "alert_credit_jump_delta", 0.15))
                and credit_now >= float(getattr(self, "alert_credit_high_level", 0.55))
            ):
                alerts.append(
                    {
                        "code": "high_credit_risk_jump",
                        "severity": "high",
                        "title": "High Credit Risk Jump",
                        "message": (
                            f"Credit risk rose from {float(credit_prev) * 100:.1f}% to "
                            f"{credit_now * 100:.1f}%."
                        ),
                        "value": round(credit_now, 4),
                        "threshold": round(
                            float(getattr(self, "alert_credit_high_level", 0.55)),
                            4,
                        ),
                        "delta": round(credit_delta, 4),
                    }
                )

        severity_rank = {"critical": 3, "high": 2, "medium": 1, "low": 0}
        alerts = sorted(
            alerts, key=lambda x: severity_rank.get(str(x.get("severity", "low")), 0), reverse=True
        )
        return alerts

    def _build_segment_playbook(
        self, facts, cluster_label, cluster_type, strategic_tag, alerts
    ):
        health_segment = str(facts.get("health_segment", "Unknown"))
        health_status = str(facts.get("health_status", "Unknown"))
        pitch = str(facts.get("top_affinity_pitch", "N/A"))
        drop = float(facts.get("revenue_drop_pct", 0.0) or 0.0)
        churn = float(facts.get("churn_probability", 0.0) or 0.0)
        credit = float(facts.get("credit_risk_score", 0.0) or 0.0)

        base_map = {
            "Champion": {
                "next_best_action": "Defend wallet share and expand premium mix.",
                "actions": [
                    "Schedule strategic account review with quarterly growth target.",
                    "Push high-margin bundles tied to current dominant category.",
                    "Lock in commitment using partner-specific pricing slabs.",
                ],
            },
            "Healthy": {
                "next_best_action": "Increase category penetration before momentum softens.",
                "actions": [
                    "Target top 3 peer-gap categories with monthly conversion goal.",
                    "Run add-on bundles from strongest affinity rules.",
                    "Track recency weekly and trigger follow-up if no purchase in 30 days.",
                ],
            },
            "At Risk": {
                "next_best_action": "Stabilize account with immediate retention intervention.",
                "actions": [
                    "Prioritize recovery call and collect blocker reasons this week.",
                    "Offer focused bundle/credit terms on historically strong categories.",
                    "Set 14-day reactivation checkpoint with owner accountability.",
                ],
            },
            "Critical": {
                "next_best_action": "Escalate recovery plan and protect downside exposure.",
                "actions": [
                    "Initiate management escalation with reactivation plan in 48 hours.",
                    "Limit risky exposure; align credit controls before new dispatch.",
                    "Run win-back campaign on proven SKUs with strict follow-up cadence.",
                ],
            },
        }
        default_block = {
            "next_best_action": "Run guided account review and define recovery plan.",
            "actions": [
                "Review last 90-day trend, peer gaps, and payment behavior.",
                "Select one retention action and one cross-sell action for this cycle.",
                "Re-evaluate account after next purchase cycle.",
            ],
        }
        block = base_map.get(health_segment, default_block)

        actions = list(block["actions"])
        if "Outlier" in str(cluster_label):
            actions.insert(
                0,
                "Treat as unique account: benchmark against state-level peers, not only cluster peers.",
            )
        elif str(cluster_type) == "VIP":
            actions.insert(0, "Use executive cadence: monthly business review with volume and margin targets.")

        if strategic_tag:
            actions.append(f"Cluster context: {strategic_tag}.")

        if pitch and pitch not in ("N/A", "None", ""):
            actions.append(f"Immediate pitch suggestion: {pitch}.")

        priority = "Normal"
        if any(str(a.get("severity")) == "critical" for a in alerts):
            priority = "Critical"
        elif any(str(a.get("severity")) == "high" for a in alerts):
            priority = "High"
        elif health_segment in {"At Risk", "Critical"} or "Risk" in health_status:
            priority = "High"

        rationale = (
            f"Segment={health_segment}, Status={health_status}, Drop={drop:.1f}%, "
            f"Churn={churn * 100:.1f}%, CreditRisk={credit * 100:.1f}%."
        )
        return {
            "title": f"{health_segment} Playbook",
            "priority": priority,
            "next_best_action": block["next_best_action"],
            "actions": actions[:6],
            "rationale": rationale,
        }

    def get_partner_intelligence(self, partner_name):
        """Return partner report: facts + peer gaps + cluster label."""
        self.ensure_clustering()
        if self.enable_realtime_partner_scoring:
            self.ensure_churn_forecast()
            self.ensure_credit_risk()
            self.ensure_associations()
        if self.matrix is None:
            return None
        if partner_name not in self.matrix.index:
            return None

        facts = {}
        if self.df_fact is not None and partner_name in self.df_fact.index:
            row = self.df_fact.loc[partner_name]
            if isinstance(row, pd.DataFrame):
                row = row.iloc[0]
            facts.update(row.to_dict())

        if (
            self.df_partner_features is not None
            and not self.df_partner_features.empty
            and partner_name in self.df_partner_features.index
        ):
            row = self.df_partner_features.loc[partner_name]
            facts.update(
                {
                    "health_status": row.get("health_status", facts.get("health_status", "Unknown")),
                    "health_segment": row.get("health_segment", "Unknown"),
                    "health_score": round(float(row.get("health_score", 0.0)), 3),
                    "revenue_drop_pct": round(float(row.get("revenue_drop_pct", 0.0)), 1),
                    "degrowth_flag": bool(row.get("degrowth_flag", False)),
                    "estimated_monthly_loss": round(float(row.get("estimated_monthly_loss", 0.0)), 2),
                    "recency_days": int(row.get("recency_days", 0)),
                    "degrowth_threshold_pct": round(float(row.get("degrowth_threshold_pct", 20.0)), 1),
                    "churn_probability": round(float(row.get("churn_probability", 0.0)), 4),
                    "churn_risk_band": row.get("churn_risk_band", "Unknown"),
                    "expected_revenue_at_risk_90d": round(
                        float(row.get("expected_revenue_at_risk_90d", 0.0)), 2
                    ),
                    "expected_revenue_at_risk_monthly": round(
                        float(row.get("expected_revenue_at_risk_monthly", 0.0)), 2
                    ),
                    "forecast_next_30d": round(float(row.get("forecast_next_30d", 0.0)), 2),
                    "forecast_trend_pct": round(float(row.get("forecast_trend_pct", 0.0)), 2),
                    "forecast_confidence": round(float(row.get("forecast_confidence", 0.0)), 3),
                    "forecast_history_months": int(row.get("forecast_history_months", 0))
                    if not pd.isna(row.get("forecast_history_months", np.nan))
                    else 0,
                    "credit_risk_score": round(float(row.get("credit_risk_score", 0.0)), 4),
                    "credit_risk_band": row.get("credit_risk_band", "Unknown"),
                    "credit_utilization": round(float(row.get("credit_utilization", 0.0)), 4),
                    "overdue_ratio": round(float(row.get("overdue_ratio", 0.0)), 4),
                    "outstanding_amount": round(float(row.get("outstanding_amount", 0.0)), 2),
                    "credit_adjusted_risk_value": round(
                        float(row.get("credit_adjusted_risk_value", 0.0)), 2
                    ),
                }
            )

        facts.setdefault("health_status", "Unknown")
        facts.setdefault("revenue_drop_pct", 0)
        facts.setdefault("top_affinity_pitch", "N/A")
        facts.setdefault("pitch_confidence", np.nan)
        facts.setdefault("pitch_lift", np.nan)
        facts.setdefault("pitch_expected_gain", np.nan)
        facts.setdefault("pitch_expected_margin", np.nan)
        facts.setdefault("churn_probability", 0.0)
        facts.setdefault("churn_risk_band", "Unknown")
        facts.setdefault("expected_revenue_at_risk_90d", 0.0)
        facts.setdefault("expected_revenue_at_risk_monthly", 0.0)
        facts.setdefault("forecast_next_30d", 0.0)
        facts.setdefault("forecast_trend_pct", 0.0)
        facts.setdefault("forecast_confidence", 0.0)
        facts.setdefault("credit_risk_score", 0.0)
        facts.setdefault("credit_risk_band", "Unknown")
        facts.setdefault("credit_utilization", 0.0)
        facts.setdefault("overdue_ratio", 0.0)
        facts.setdefault("outstanding_amount", 0.0)
        facts.setdefault("credit_adjusted_risk_value", 0.0)

        if self.enable_realtime_partner_scoring:
            best_pitch = self._get_top_affinity_pitch(
                partner_name,
                min_confidence=self.default_min_confidence,
                min_lift=self.default_min_lift,
            )
            if best_pitch is not None:
                facts["top_affinity_pitch"] = best_pitch.get(
                    "recommended_product", facts["top_affinity_pitch"]
                )
                facts["pitch_confidence"] = float(best_pitch.get("confidence", np.nan))
                facts["pitch_lift"] = float(best_pitch.get("lift", np.nan))
                facts["pitch_expected_gain"] = float(
                    best_pitch.get("expected_revenue_gain", np.nan)
                )
                facts["pitch_expected_margin"] = float(
                    best_pitch.get("expected_margin_gain", np.nan)
                )

        cluster_id = int(self.matrix.loc[partner_name, "cluster"])
        cluster_label = self.matrix.loc[partner_name, "cluster_label"]
        cluster_type = str(self.matrix.loc[partner_name, "cluster_type"])
        strategic_tag = str(self.matrix.loc[partner_name, "strategic_tag"])
        partner_state = str(self.matrix.loc[partner_name, "state"])
        gaps_df = pd.DataFrame()

        use_recent = (
            (not self.strict_view_only)
            and self.matrix_recent is not None
            and not self.matrix_recent.empty
            and partner_name in self.matrix_recent.index
        )
        facts["gap_horizon_days"] = int(self.gap_lookback_days) if use_recent else None
        if cluster_id != -1:
            cluster_members = self.matrix[self.matrix["cluster"] == cluster_id].index.tolist()
            peer_names = [name for name in cluster_members if name != partner_name]
            if peer_names:
                if use_recent:
                    peer_names = [name for name in peer_names if name in self.matrix_recent.index]
                    if not peer_names:
                        use_recent = False

                if use_recent:
                    peer_numeric = self.matrix_recent.loc[peer_names].drop(columns=["state"], errors="ignore")
                    partner_numeric = self.matrix_recent.loc[partner_name].drop(labels=["state"], errors="ignore")
                    annualization_factor_local = 365.0 / float(self.gap_lookback_days)
                else:
                    peers = self.matrix.loc[peer_names]
                    peer_numeric = peers.drop(
                        columns=["state", "cluster", "cluster_type", "cluster_label", "strategic_tag"],
                        errors="ignore",
                    )
                    partner_numeric = self.matrix.loc[partner_name].drop(
                        labels=["state", "cluster", "cluster_type", "cluster_label", "strategic_tag"],
                        errors="ignore",
                    )
                    annualization_factor_local = 1.0
                    facts["gap_horizon_days"] = None

                peer_avg = peer_numeric.mean()
                diff = (peer_avg - partner_numeric).clip(lower=0)
                gap_ratio = diff / peer_avg.replace(0, np.nan)

                same_state_peer_names = [
                    name for name in peer_names if str(self.matrix.loc[name, "state"]) == partner_state
                ]
                ratio_reference = peer_numeric
                if len(same_state_peer_names) >= 3:
                    ratio_reference = peer_numeric.loc[same_state_peer_names]

                ref_ratio_matrix = (peer_avg - ratio_reference).div(peer_avg.replace(0, np.nan), axis=1)
                positive_ratios = ref_ratio_matrix.where(ref_ratio_matrix > 0).stack().dropna()
                gap_ratio_cutoff = float(positive_ratios.quantile(0.70)) if not positive_ratios.empty else 0.15
                gap_ratio_cutoff = max(0.05, min(0.60, gap_ratio_cutoff))
                facts["gap_ratio_cutoff"] = round(gap_ratio_cutoff * 100.0, 1)

                valid_mask = (diff > 0) & (gap_ratio >= gap_ratio_cutoff)
                valid_gaps = diff[valid_mask].sort_values(ascending=False)

                if not valid_gaps.empty:
                    partner_total = float(partner_numeric.sum()) if float(partner_numeric.sum()) > 0 else np.nan
                    peer_total = float(peer_avg.sum()) if float(peer_avg.sum()) > 0 else np.nan
                    yearly_gap = valid_gaps.values * annualization_factor_local
                    monthly_gap = yearly_gap / 12.0
                    weekly_gap = yearly_gap / 52.0
                    partner_vals = partner_numeric[valid_gaps.index].values
                    peer_vals = peer_avg[valid_gaps.index].values
                    you_do_pct = np.where(
                        np.isnan(partner_total), 0.0, (partner_vals / partner_total) * 100.0
                    )
                    others_do_pct = np.where(
                        np.isnan(peer_total), 0.0, (peer_vals / peer_total) * 100.0
                    )

                    gaps_df = pd.DataFrame(
                        {
                            "Product": valid_gaps.index,
                            "Potential_Revenue": yearly_gap,
                            "Potential_Revenue_Yearly": yearly_gap,
                            "Potential_Revenue_Monthly": monthly_gap,
                            "Potential_Revenue_Weekly": weekly_gap,
                            "Gap_Ratio_Pct": (gap_ratio[valid_gaps.index].values * 100.0),
                            "Peer_Avg_Spend": peer_avg[valid_gaps.index].values * annualization_factor_local,
                            "You_Do_Pct": you_do_pct,
                            "Others_Do_Pct": others_do_pct,
                        }
                    )

        alerts = self._compute_partner_alerts(partner_name, facts)
        playbook = self._build_segment_playbook(
            facts=facts,
            cluster_label=cluster_label,
            cluster_type=cluster_type,
            strategic_tag=strategic_tag,
            alerts=alerts,
        )
        facts["active_alert_count"] = int(len(alerts))

        return {
            "facts": pd.Series(facts),
            "gaps": gaps_df,
            "cluster_label": cluster_label,
            "cluster_type": cluster_type,
            "cluster_info": strategic_tag,
            "alerts": alerts,
            "playbook": playbook,
        }
