import argparse
import os
import time

from ml_engine.sales_model import SalesIntelligenceEngine


def _build_engine_for_realtime():
    # Realtime worker should compute full scores and write serving table.
    os.environ["STRICT_VIEW_ONLY"] = "false"
    os.environ["ENABLE_REALTIME_PARTNER_SCORING"] = "true"
    os.environ["FAST_MODE"] = "false"
    eng = SalesIntelligenceEngine()
    eng.load_data(lightweight=False)
    eng.ensure_clustering()
    return eng


def process_once(engine, limit):
    jobs = engine.realtime_repo.claim_jobs(limit=limit)
    if not jobs:
        return 0

    processed = 0
    for job in jobs:
        job_id = int(job["id"])
        partner_name = job.get("partner_name")
        try:
            partners = [partner_name] if partner_name else engine.matrix.index.tolist()
            for p in partners:
                report = engine.get_partner_intelligence(p)
                if not report:
                    continue
                facts = report["facts"]
                engine.realtime_repo.upsert_live_score(
                    p,
                    {
                        "churn_probability": facts.get("churn_probability", 0.0),
                        "churn_risk_band": facts.get("churn_risk_band", "Unknown"),
                        "expected_revenue_at_risk_90d": facts.get(
                            "expected_revenue_at_risk_90d", 0.0
                        ),
                        "expected_revenue_at_risk_monthly": facts.get(
                            "expected_revenue_at_risk_monthly", 0.0
                        ),
                        "forecast_next_30d": facts.get("forecast_next_30d", 0.0),
                        "forecast_trend_pct": facts.get("forecast_trend_pct", 0.0),
                        "forecast_confidence": facts.get("forecast_confidence", 0.0),
                        "credit_risk_score": facts.get("credit_risk_score", 0.0),
                        "credit_risk_band": facts.get("credit_risk_band", "Unknown"),
                        "credit_utilization": facts.get("credit_utilization", 0.0),
                        "overdue_ratio": facts.get("overdue_ratio", 0.0),
                        "outstanding_amount": facts.get("outstanding_amount", 0.0),
                        "credit_adjusted_risk_value": facts.get(
                            "credit_adjusted_risk_value", 0.0
                        ),
                    },
                )
            engine.realtime_repo.mark_done(job_id)
            processed += 1
        except Exception as e:
            engine.realtime_repo.mark_failed(job_id, str(e))
    return processed


def main():
    parser = argparse.ArgumentParser(description="Local realtime worker for live score serving.")
    parser.add_argument("--once", action="store_true", help="Process one batch and exit.")
    parser.add_argument("--poll-seconds", type=int, default=15, help="Polling interval.")
    parser.add_argument("--limit", type=int, default=10, help="Max jobs per batch.")
    args = parser.parse_args()

    engine = _build_engine_for_realtime()
    if args.once:
        n = process_once(engine, args.limit)
        print(f"Processed jobs: {n}")
        return

    while True:
        n = process_once(engine, args.limit)
        if n:
            print(f"Processed jobs: {n}")
        time.sleep(max(2, int(args.poll_seconds)))


if __name__ == "__main__":
    main()
