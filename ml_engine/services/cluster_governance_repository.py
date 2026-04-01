import pandas as pd
from sqlalchemy import text


class ClusterGovernanceRepository:
    def __init__(self, engine):
        self.engine = engine

    def save_run(self, payload):
        query = text(
            """
            INSERT INTO cluster_model_runs (
                status, approved, reject_reason,
                vip_method, vip_chosen_k, vip_silhouette, vip_calinski_harabasz, vip_stability_ari,
                growth_method, growth_min_cluster_size, growth_min_samples, growth_outlier_ratio,
                growth_silhouette, growth_calinski_harabasz, growth_stability_ari,
                global_outlier_ratio, global_cluster_count
            )
            VALUES (
                :status, :approved, :reject_reason,
                :vip_method, :vip_chosen_k, :vip_silhouette, :vip_calinski_harabasz, :vip_stability_ari,
                :growth_method, :growth_min_cluster_size, :growth_min_samples, :growth_outlier_ratio,
                :growth_silhouette, :growth_calinski_harabasz, :growth_stability_ari,
                :global_outlier_ratio, :global_cluster_count
            )
            RETURNING id
            """
        )
        try:
            with self.engine.begin() as conn:
                row = conn.execute(query, payload).first()
            return int(row[0]) if row else None
        except Exception:
            return None

    def save_assignments(self, run_id, assignments_df):
        if run_id is None or assignments_df is None or assignments_df.empty:
            return 0
        rows = assignments_df.reset_index().rename(columns={"index": "company_name"})
        needed = ["company_name", "cluster", "cluster_type", "cluster_label", "strategic_tag"]
        rows = rows[needed]
        inserted = 0
        try:
            with self.engine.begin() as conn:
                for r in rows.to_dict(orient="records"):
                    conn.execute(
                        text(
                            """
                            INSERT INTO cluster_assignments (
                                run_id, company_name, cluster, cluster_type, cluster_label, strategic_tag
                            )
                            VALUES (
                                :run_id, :company_name, :cluster, :cluster_type, :cluster_label, :strategic_tag
                            )
                            """
                        ),
                        {
                            "run_id": int(run_id),
                            "company_name": str(r["company_name"]),
                            "cluster": int(r["cluster"]),
                            "cluster_type": str(r["cluster_type"]),
                            "cluster_label": str(r["cluster_label"]),
                            "strategic_tag": str(r["strategic_tag"]),
                        },
                    )
                    inserted += 1
        except Exception:
            return 0
        return inserted

    def load_last_approved_assignments(self):
        query = """
        WITH last_ok AS (
            SELECT id
            FROM cluster_model_runs
            WHERE approved = TRUE
            ORDER BY run_at DESC
            LIMIT 1
        )
        SELECT
            a.company_name,
            a.cluster,
            a.cluster_type,
            a.cluster_label,
            a.strategic_tag
        FROM cluster_assignments a
        JOIN last_ok l ON a.run_id = l.id
        """
        try:
            df = pd.read_sql(query, self.engine)
            if df.empty:
                return df
            return df.set_index("company_name")
        except Exception:
            return pd.DataFrame()

