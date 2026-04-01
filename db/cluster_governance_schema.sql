-- Cluster governance and fallback persistence

CREATE TABLE IF NOT EXISTS cluster_model_runs (
    id BIGSERIAL PRIMARY KEY,
    run_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status TEXT NOT NULL DEFAULT 'ok',
    approved BOOLEAN NOT NULL DEFAULT FALSE,
    reject_reason TEXT NULL,
    vip_method TEXT NULL,
    vip_chosen_k INT NULL,
    vip_silhouette DOUBLE PRECISION NULL,
    vip_calinski_harabasz DOUBLE PRECISION NULL,
    vip_stability_ari DOUBLE PRECISION NULL,
    growth_method TEXT NULL,
    growth_min_cluster_size INT NULL,
    growth_min_samples INT NULL,
    growth_outlier_ratio DOUBLE PRECISION NULL,
    growth_silhouette DOUBLE PRECISION NULL,
    growth_calinski_harabasz DOUBLE PRECISION NULL,
    growth_stability_ari DOUBLE PRECISION NULL,
    global_outlier_ratio DOUBLE PRECISION NULL,
    global_cluster_count INT NULL
);

CREATE INDEX IF NOT EXISTS idx_cluster_model_runs_run_at
ON cluster_model_runs (run_at DESC);

CREATE INDEX IF NOT EXISTS idx_cluster_model_runs_approved
ON cluster_model_runs (approved, run_at DESC);

CREATE TABLE IF NOT EXISTS cluster_assignments (
    run_id BIGINT NOT NULL REFERENCES cluster_model_runs(id) ON DELETE CASCADE,
    company_name TEXT NOT NULL,
    cluster INT NOT NULL,
    cluster_type TEXT NOT NULL,
    cluster_label TEXT NOT NULL,
    strategic_tag TEXT NOT NULL,
    PRIMARY KEY (run_id, company_name)
);

CREATE INDEX IF NOT EXISTS idx_cluster_assignments_company
ON cluster_assignments (company_name);
