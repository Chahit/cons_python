-- Local realtime serving schema (no cloud required)

CREATE TABLE IF NOT EXISTS score_recompute_jobs (
    id BIGSERIAL PRIMARY KEY,
    partner_name TEXT NULL,
    reason TEXT NOT NULL DEFAULT 'manual',
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ NULL,
    finished_at TIMESTAMPTZ NULL,
    error_message TEXT NULL
);

CREATE INDEX IF NOT EXISTS idx_score_recompute_jobs_status_created
ON score_recompute_jobs (status, created_at);

CREATE TABLE IF NOT EXISTS partner_live_scores (
    partner_name TEXT PRIMARY KEY,
    churn_probability DOUBLE PRECISION NOT NULL DEFAULT 0,
    churn_risk_band TEXT NOT NULL DEFAULT 'Unknown',
    expected_revenue_at_risk_90d DOUBLE PRECISION NOT NULL DEFAULT 0,
    expected_revenue_at_risk_monthly DOUBLE PRECISION NOT NULL DEFAULT 0,
    forecast_next_30d DOUBLE PRECISION NOT NULL DEFAULT 0,
    forecast_trend_pct DOUBLE PRECISION NOT NULL DEFAULT 0,
    forecast_confidence DOUBLE PRECISION NOT NULL DEFAULT 0,
    credit_risk_score DOUBLE PRECISION NOT NULL DEFAULT 0,
    credit_risk_band TEXT NOT NULL DEFAULT 'Unknown',
    credit_utilization DOUBLE PRECISION NOT NULL DEFAULT 0,
    overdue_ratio DOUBLE PRECISION NOT NULL DEFAULT 0,
    outstanding_amount DOUBLE PRECISION NOT NULL DEFAULT 0,
    credit_adjusted_risk_value DOUBLE PRECISION NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_partner_live_scores_updated_at
ON partner_live_scores (updated_at DESC);

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

CREATE INDEX IF NOT EXISTS idx_reco_feedback_created_at
ON recommendation_feedback_events (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_reco_feedback_outcome_created
ON recommendation_feedback_events (outcome, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_reco_feedback_action_tone
ON recommendation_feedback_events (action_type, tone);
