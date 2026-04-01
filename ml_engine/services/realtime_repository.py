import pandas as pd
from sqlalchemy import text


class RealtimeRepository:
    def __init__(self, engine):
        self.engine = engine

    def fetch_live_scores(self):
        try:
            return pd.read_sql("SELECT * FROM partner_live_scores", self.engine).set_index(
                "partner_name"
            )
        except Exception:
            return pd.DataFrame()

    def queue_job(self, partner_name=None, reason="manual"):
        query = text(
            """
            INSERT INTO score_recompute_jobs (partner_name, reason, status)
            VALUES (:partner_name, :reason, 'pending')
            RETURNING id
            """
        )
        with self.engine.begin() as conn:
            row = conn.execute(
                query,
                {
                    "partner_name": partner_name,
                    "reason": reason,
                },
            ).first()
        return int(row[0]) if row else None

    def queue_all_missing(self, partner_names, reason="bulk"):
        if not partner_names:
            return 0
        inserted = 0
        with self.engine.begin() as conn:
            for name in partner_names:
                row = conn.execute(
                    text(
                        """
                        INSERT INTO score_recompute_jobs (partner_name, reason, status)
                        VALUES (:partner_name, :reason, 'pending')
                        RETURNING id
                        """
                    ),
                    {"partner_name": name, "reason": reason},
                ).first()
                if row:
                    inserted += 1
        return inserted

    def claim_jobs(self, limit=10):
        query = text(
            """
            WITH cte AS (
                SELECT id
                FROM score_recompute_jobs
                WHERE status = 'pending'
                ORDER BY created_at ASC
                LIMIT :limit
                FOR UPDATE SKIP LOCKED
            )
            UPDATE score_recompute_jobs j
            SET status = 'running',
                started_at = NOW(),
                attempts = attempts + 1
            FROM cte
            WHERE j.id = cte.id
            RETURNING j.id, j.partner_name, j.reason, j.attempts
            """
        )
        with self.engine.begin() as conn:
            rows = conn.execute(query, {"limit": int(limit)}).mappings().all()
        return [dict(r) for r in rows]

    def mark_done(self, job_id):
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE score_recompute_jobs
                    SET status = 'done',
                        finished_at = NOW(),
                        error_message = NULL
                    WHERE id = :job_id
                    """
                ),
                {"job_id": int(job_id)},
            )

    def mark_failed(self, job_id, message):
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE score_recompute_jobs
                    SET status = 'failed',
                        finished_at = NOW(),
                        error_message = :message
                    WHERE id = :job_id
                    """
                ),
                {"job_id": int(job_id), "message": str(message)[:1000]},
            )

    def upsert_live_score(self, partner_name, payload):
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO partner_live_scores (
                        partner_name,
                        churn_probability,
                        churn_risk_band,
                        expected_revenue_at_risk_90d,
                        expected_revenue_at_risk_monthly,
                        forecast_next_30d,
                        forecast_trend_pct,
                        forecast_confidence,
                        credit_risk_score,
                        credit_risk_band,
                        credit_utilization,
                        overdue_ratio,
                        outstanding_amount,
                        credit_adjusted_risk_value,
                        updated_at
                    )
                    VALUES (
                        :partner_name,
                        :churn_probability,
                        :churn_risk_band,
                        :expected_revenue_at_risk_90d,
                        :expected_revenue_at_risk_monthly,
                        :forecast_next_30d,
                        :forecast_trend_pct,
                        :forecast_confidence,
                        :credit_risk_score,
                        :credit_risk_band,
                        :credit_utilization,
                        :overdue_ratio,
                        :outstanding_amount,
                        :credit_adjusted_risk_value,
                        NOW()
                    )
                    ON CONFLICT (partner_name) DO UPDATE SET
                        churn_probability = EXCLUDED.churn_probability,
                        churn_risk_band = EXCLUDED.churn_risk_band,
                        expected_revenue_at_risk_90d = EXCLUDED.expected_revenue_at_risk_90d,
                        expected_revenue_at_risk_monthly = EXCLUDED.expected_revenue_at_risk_monthly,
                        forecast_next_30d = EXCLUDED.forecast_next_30d,
                        forecast_trend_pct = EXCLUDED.forecast_trend_pct,
                        forecast_confidence = EXCLUDED.forecast_confidence,
                        credit_risk_score = EXCLUDED.credit_risk_score,
                        credit_risk_band = EXCLUDED.credit_risk_band,
                        credit_utilization = EXCLUDED.credit_utilization,
                        overdue_ratio = EXCLUDED.overdue_ratio,
                        outstanding_amount = EXCLUDED.outstanding_amount,
                        credit_adjusted_risk_value = EXCLUDED.credit_adjusted_risk_value,
                        updated_at = NOW()
                    """
                ),
                {
                    "partner_name": partner_name,
                    "churn_probability": float(payload.get("churn_probability", 0.0)),
                    "churn_risk_band": str(payload.get("churn_risk_band", "Unknown")),
                    "expected_revenue_at_risk_90d": float(
                        payload.get("expected_revenue_at_risk_90d", 0.0)
                    ),
                    "expected_revenue_at_risk_monthly": float(
                        payload.get("expected_revenue_at_risk_monthly", 0.0)
                    ),
                    "forecast_next_30d": float(payload.get("forecast_next_30d", 0.0)),
                    "forecast_trend_pct": float(payload.get("forecast_trend_pct", 0.0)),
                    "forecast_confidence": float(payload.get("forecast_confidence", 0.0)),
                    "credit_risk_score": float(payload.get("credit_risk_score", 0.0)),
                    "credit_risk_band": str(payload.get("credit_risk_band", "Unknown")),
                    "credit_utilization": float(payload.get("credit_utilization", 0.0)),
                    "overdue_ratio": float(payload.get("overdue_ratio", 0.0)),
                    "outstanding_amount": float(payload.get("outstanding_amount", 0.0)),
                    "credit_adjusted_risk_value": float(
                        payload.get("credit_adjusted_risk_value", 0.0)
                    ),
                },
            )

    def get_queue_status(self):
        try:
            q = pd.read_sql(
                """
                SELECT
                    SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending_jobs,
                    SUM(CASE WHEN status = 'running' THEN 1 ELSE 0 END) AS running_jobs,
                    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed_jobs
                FROM score_recompute_jobs
                """,
                self.engine,
            )
            ls = pd.read_sql(
                "SELECT MAX(updated_at) AS last_live_update, COUNT(*) AS scored_partners FROM partner_live_scores",
                self.engine,
            )
            data = {}
            if not q.empty:
                data.update(q.iloc[0].fillna(0).to_dict())
            if not ls.empty:
                data.update(ls.iloc[0].to_dict())
            return data
        except Exception:
            return {
                "pending_jobs": 0,
                "running_jobs": 0,
                "failed_jobs": 0,
                "last_live_update": None,
                "scored_partners": 0,
            }

    def get_job_status(self, job_id):
        query = text("SELECT status, error_message FROM score_recompute_jobs WHERE id = :job_id")
        with self.engine.begin() as conn:
            row = conn.execute(query, {"job_id": int(job_id)}).first()
        if row:
            return {"status": row[0], "error": row[1]}
        return None
