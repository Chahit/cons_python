"""
ml_engine/services/drift_detector.py
──────────────────────────────────────────────────────────────────────────────
Cluster Drift Detector
━━━━━━━━━━━━━━━━━━━━━
Tracks cluster centroid positions across clustering runs and raises alerts
when a cluster's character has shifted significantly — even when its label
is unchanged. This detects "silent degradation" that ARI stability misses.

Usage (called from clustering_mixin.py):
    detector = ClusterDriftDetector(engine)
    detector.save_centroids(run_id, centroids_dict, feature_names)
    alerts = detector.compute_drift(centroids_dict, feature_names)
    detector.save_drift_alerts(run_id, alerts)
"""

import json
import logging
import numpy as np
import pandas as pd
from sqlalchemy import text

logger = logging.getLogger(__name__)


class ClusterDriftDetector:
    """
    Centroid-level drift detection for cluster intelligence.

    Args:
        engine:           SQLAlchemy engine (same as main app engine).
        drift_threshold:  Normalized L2 drift (0-1) to trigger a 'medium' alert.
        high_threshold:   Normalized L2 drift to trigger a 'high' alert.
    """

    def __init__(
        self,
        engine,
        drift_threshold: float = 0.25,
        high_threshold: float = 0.50,
    ):
        self.engine = engine
        self.drift_threshold = drift_threshold
        self.high_threshold = high_threshold

    # ── Persist centroid vectors ──────────────────────────────────────────────
    def save_centroids(
        self,
        run_id: int,
        centroids: dict,
        feature_names: list,
    ) -> None:
        """
        Persist cluster centroid vectors after a clustering run.

        Args:
            run_id:        Cluster model run ID (from cluster_model_runs).
            centroids:     {cluster_label: {"tier": str, "centroid": np.ndarray}}
            feature_names: Ordered list of feature names matching centroid dims.
        """
        if run_id is None or not centroids:
            return

        feat_json = json.dumps([str(f) for f in feature_names])

        try:
            with self.engine.begin() as conn:
                for label, info in centroids.items():
                    centroid_vec = info.get("centroid")
                    if centroid_vec is None:
                        continue
                    conn.execute(
                        text(
                            """
                            INSERT INTO cluster_centroids_history
                                (run_id, tier, cluster_label, centroid_json, feature_names)
                            VALUES
                                (:run_id, :tier, :cluster_label, :centroid_json, :feature_names)
                            """
                        ),
                        {
                            "run_id": int(run_id),
                            "tier": str(info.get("tier", "Unknown")),
                            "cluster_label": str(label),
                            "centroid_json": json.dumps(
                                [float(v) for v in np.asarray(centroid_vec)]
                            ),
                            "feature_names": feat_json,
                        },
                    )
            logger.info(f"[Drift] Saved {len(centroids)} cluster centroids for run_id={run_id}.")
        except Exception as exc:
            logger.warning(f"[Drift] Could not save centroids: {exc}")

    # ── Compute drift vs previous run ─────────────────────────────────────────
    def compute_drift(
        self,
        current_centroids: dict,
        feature_names: list,
    ) -> list:
        """
        Compare current centroids against the most recent historical snapshot.

        Returns:
            List of drift alert dicts (sorted by drift_score descending).
            Empty list if no prior history exists (first run).
        """
        alerts = []
        if not current_centroids:
            return alerts

        labels = list(current_centroids.keys())

        try:
            df = pd.read_sql(
                text(
                    """
                    SELECT DISTINCT ON (cluster_label)
                        cluster_label, tier, centroid_json, feature_names
                    FROM cluster_centroids_history
                    WHERE cluster_label = ANY(:labels)
                    ORDER BY cluster_label, recorded_at DESC
                    """
                ),
                self.engine,
                params={"labels": labels},
            )
        except Exception as exc:
            logger.warning(f"[Drift] Could not load centroid history: {exc}")
            return alerts

        if df.empty:
            logger.info("[Drift] No prior centroid history found — first run, skipping drift check.")
            return alerts

        feat_idx = {f: i for i, f in enumerate(feature_names)}

        for _, row in df.iterrows():
            label = row["cluster_label"]
            if label not in current_centroids:
                continue

            try:
                hist_centroid = np.array(json.loads(row["centroid_json"]), dtype=float)
                hist_features = json.loads(row["feature_names"])
                curr_centroid = np.array(
                    current_centroids[label]["centroid"], dtype=float
                )
                tier = str(current_centroids[label].get("tier", "Unknown"))

                # Only compare features present in both runs
                common = [f for f in hist_features if f in feat_idx]
                if len(common) < 3:
                    continue

                curr_vals = np.array(
                    [curr_centroid[feat_idx[f]] for f in common if f in feat_idx]
                )
                hist_vals = np.array(
                    [hist_centroid[hist_features.index(f)] for f in common]
                )

                if len(curr_vals) != len(hist_vals):
                    continue

                # Normalized absolute drift per feature
                scales = np.abs(hist_vals) + 1e-8
                normalized_diffs = np.abs(curr_vals - hist_vals) / scales
                drift_score = float(np.mean(normalized_diffs))

                if drift_score >= self.drift_threshold:
                    top_idx = np.argsort(normalized_diffs)[::-1][:5]
                    top_features = [common[i] for i in top_idx if i < len(common)]
                    severity = (
                        "high" if drift_score >= self.high_threshold else "medium"
                    )
                    alerts.append(
                        {
                            "cluster_label": label,
                            "tier": tier,
                            "drift_score": round(drift_score, 4),
                            "drift_threshold": self.drift_threshold,
                            "top_drifted_features": top_features,
                            "severity": severity,
                            "message": (
                                f"Cluster '{label}' ({tier}) has drifted "
                                f"{drift_score:.1%} from last run. "
                                f"Most changed: {', '.join(top_features[:3])}."
                            ),
                        }
                    )

            except Exception as exc:
                logger.debug(f"[Drift] Skipping '{label}': {exc}")
                continue

        alerts.sort(key=lambda x: x["drift_score"], reverse=True)
        if alerts:
            logger.warning(
                f"[Drift] {len(alerts)} drift alert(s): "
                + ", ".join(f"{a['cluster_label']}({a['drift_score']:.2f})" for a in alerts[:3])
            )
        return alerts

    # ── Persist alerts ────────────────────────────────────────────────────────
    def save_drift_alerts(self, run_id: int, alerts: list) -> None:
        """Persist drift alerts to cluster_drift_alerts table."""
        if run_id is None or not alerts:
            return
        try:
            with self.engine.begin() as conn:
                for a in alerts:
                    conn.execute(
                        text(
                            """
                            INSERT INTO cluster_drift_alerts
                                (run_id, cluster_label, drift_score, drift_threshold,
                                 top_drifted_features, severity)
                            VALUES
                                (:run_id, :cluster_label, :drift_score, :drift_threshold,
                                 :top_drifted_features, :severity)
                            """
                        ),
                        {
                            "run_id": int(run_id),
                            "cluster_label": str(a["cluster_label"]),
                            "drift_score": float(a["drift_score"]),
                            "drift_threshold": float(a["drift_threshold"]),
                            "top_drifted_features": json.dumps(a["top_drifted_features"]),
                            "severity": str(a["severity"]),
                        },
                    )
        except Exception as exc:
            logger.warning(f"[Drift] Could not persist drift alerts: {exc}")

    # ── History retrieval ─────────────────────────────────────────────────────
    def get_drift_history(self, cluster_label: str, n_runs: int = 10) -> pd.DataFrame:
        """Return drift score history for a given cluster (for trend charts)."""
        try:
            return pd.read_sql(
                text(
                    """
                    SELECT
                        ch.cluster_label,
                        ch.tier,
                        ch.recorded_at,
                        COALESCE(da.drift_score, 0)   AS drift_score,
                        COALESCE(da.severity, 'none') AS severity,
                        COALESCE(da.top_drifted_features, '[]') AS top_drifted_features
                    FROM cluster_centroids_history ch
                    LEFT JOIN cluster_drift_alerts da
                        ON ch.run_id = da.run_id
                       AND ch.cluster_label = da.cluster_label
                    WHERE ch.cluster_label = :label
                    ORDER BY ch.recorded_at DESC
                    LIMIT :n
                    """
                ),
                self.engine,
                params={"label": cluster_label, "n": n_runs},
            )
        except Exception:
            return pd.DataFrame()
