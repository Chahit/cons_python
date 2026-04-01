import os
import urllib.parse
from pathlib import Path

from sqlalchemy import create_engine

from .associations_mixin import AssociationsMixin
from .base_loader_mixin import BaseLoaderMixin
from .churn_credit_stub_mixin import ChurnCreditStubMixin
from .clustering_mixin import ClusteringMixin
from .monitoring_mixin import MonitoringMixin
from .product_lifecycle_mixin import ProductLifecycleMixin
from .recommendation_mixin import RecommendationMixin
from .services.data_repository import DataRepository
from .services.realtime_repository import RealtimeRepository
from .services.cluster_governance_repository import ClusterGovernanceRepository
from .realtime_mixin import RealtimeMixin
from .chatbot_mixin import ChatbotMixin
from .sales_rep_mixin import SalesRepMixin


class SalesIntelligenceEngine(
    BaseLoaderMixin,
    ChurnCreditStubMixin,
    ClusteringMixin,
    AssociationsMixin,
    RecommendationMixin,
    RealtimeMixin,
    MonitoringMixin,
    ProductLifecycleMixin,
    ChatbotMixin,
    SalesRepMixin,
):
    @staticmethod
    def _load_local_env_file():
        env_path = Path(__file__).resolve().parents[1] / ".env"
        if not env_path.exists():
            return
        try:
            for raw in env_path.read_text(encoding="utf-8").splitlines():
                line = str(raw).strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                k = key.strip()
                if not k:
                    continue
                v = value.strip().strip('"').strip("'")
                # Local project .env should be the source of truth for app runtime flags.
                if os.environ.get(k) != v:
                    os.environ[k] = v
        except Exception:
            # Keep startup resilient even if .env has formatting issues.
            pass

    def __init__(self):
        self._load_local_env_file()
        # Prefer a full URL from env. Fallback to parts for local development.
        env_url = os.getenv("SALES_DB_URL")
        if env_url:
            self.db_url = env_url
        else:
            user = os.getenv("SALES_DB_USER", "postgres")
            password = urllib.parse.quote_plus(os.getenv("SALES_DB_PASSWORD", "CHAHIT123"))
            host = os.getenv("SALES_DB_HOST", "127.0.0.1")
            port = os.getenv("SALES_DB_PORT", "5432")
            name = os.getenv("SALES_DB_NAME", "dsr_live_local")
            self.db_url = f"postgresql://{user}:{password}@{host}:{port}/{name}"

        self.engine = create_engine(
            self.db_url,
            pool_pre_ping=True,
            pool_recycle=1800,
            connect_args={"connect_timeout": int(os.getenv("SALES_DB_CONNECT_TIMEOUT", "5"))},
        )
        self.repo = DataRepository(self.engine)
        self.realtime_repo = RealtimeRepository(self.engine)
        self.cluster_repo = ClusterGovernanceRepository(self.engine)

        self.df_ml = None
        self.df_fact = None
        self.df_stock_stats = None
        self.df_partner_features = None
        self.df_assoc_rules = None
        self.df_recent_group_spend = None
        self.df_monthly_revenue = None
        self.df_churn_training = None
        self.df_forecast = None
        self.df_credit_risk = None
        self.df_live_scores = None
        self.matrix_recent = None
        self.matrix = None
        self.default_min_confidence = float(os.getenv("MBA_MIN_CONFIDENCE", "0.15"))
        self.default_min_lift = float(os.getenv("MBA_MIN_LIFT", "1.0"))
        self.default_min_support = int(os.getenv("MBA_MIN_SUPPORT", "5"))
        self.default_include_low_support = (
            os.getenv("MBA_INCLUDE_LOW_SUPPORT", "false").lower() == "true"
        )
        self.gap_lookback_days = max(30, int(os.getenv("GAP_LOOKBACK_DAYS", "365")))
        self.mba_lookback_months = max(1, int(os.getenv("MBA_LOOKBACK_MONTHS", "12")))
        self.churn_history_months = max(9, int(os.getenv("CHURN_HISTORY_MONTHS", "15")))
        self.churn_horizon_days = max(30, int(os.getenv("CHURN_HORIZON_DAYS", "90")))
        self.forecast_history_months = max(3, int(os.getenv("FORECAST_HISTORY_MONTHS", "6")))
        self.churn_prob_high = float(os.getenv("CHURN_PROB_HIGH", "0.65"))
        self.churn_prob_medium = float(os.getenv("CHURN_PROB_MEDIUM", "0.35"))
        self.credit_risk_high = float(os.getenv("CREDIT_RISK_HIGH", "0.67"))
        self.credit_risk_medium = float(os.getenv("CREDIT_RISK_MEDIUM", "0.40"))
        self.rank_by_margin = os.getenv("RANK_BY_MARGIN", "true").lower() == "true"
        self.fast_mode = os.getenv("FAST_MODE", "true").lower() == "true"
        self.strict_view_only = os.getenv("STRICT_VIEW_ONLY", "true").lower() == "true"
        self.use_precomputed_assoc = (
            os.getenv("USE_PRECOMPUTED_ASSOC", "true").lower() == "true"
        )
        self.enable_realtime_partner_scoring = (
            os.getenv("ENABLE_REALTIME_PARTNER_SCORING", "false").lower() == "true"
        )
        self.data_quality_report = {}
        self.last_backtest = {}
        self.churn_model = None
        self._core_loaded = False
        self._clustering_ready = False
        self._churn_ready = False
        self._credit_ready = False
        self._associations_ready = False
        self._feedback_table_ready = False
        self._core_loaded_at = None
        self._clustering_loaded_at = None
        self._churn_loaded_at = None
        self._credit_loaded_at = None
        self._associations_loaded_at = None
        self.core_cache_ttl_sec = max(60, int(os.getenv("CORE_CACHE_TTL_SEC", "900")))
        self.cluster_cache_ttl_sec = max(60, int(os.getenv("CLUSTER_CACHE_TTL_SEC", "900")))
        self.assoc_cache_ttl_sec = max(60, int(os.getenv("ASSOC_CACHE_TTL_SEC", "900")))
        self.churn_cache_ttl_sec = max(60, int(os.getenv("CHURN_CACHE_TTL_SEC", "1800")))
        self.credit_cache_ttl_sec = max(60, int(os.getenv("CREDIT_CACHE_TTL_SEC", "1800")))
        self.df_dead_stock = None
        self.step_timings = {}
        self.churn_model_features = [
            # Original 7
            "recent_90_revenue",
            "prev_90_revenue",
            "recent_txns",
            "prev_txns",
            "recency_days",
            "growth_rate_90d",
            "revenue_drop_pct",
            # NEW behavioral signals
            "avg_order_value",
            "aov_trend",
            "category_count",
            "category_diversity_change",
            "engagement_velocity",
        ]
        self.churn_model_report = {}
        self.churn_shap_explainer = None
        self.churn_feature_importance = None
        self.survival_model = None
        self.survival_report = {}
        self.credit_risk_report = {}
        self.cluster_quality_report = {}
        self.cluster_business_validation_report = {}
        self.cluster_feature_baseline = None
        self._last_cluster_feature_report = {}
        self.cluster_min_stability = float(os.getenv("CLUSTER_MIN_STABILITY_ARI", "0.0"))
        self.cluster_outlier_min = float(os.getenv("CLUSTER_OUTLIER_MIN", "0.0"))
        self.cluster_outlier_max = float(os.getenv("CLUSTER_OUTLIER_MAX", "0.60"))
        self.cluster_min_count = int(os.getenv("CLUSTER_MIN_COUNT", "2"))
        self.cluster_vip_percentile = float(os.getenv("CLUSTER_VIP_PERCENTILE", "0.80"))
        self.cluster_vip_min_share = float(os.getenv("CLUSTER_VIP_MIN_SHARE", "0.20"))
        self.cluster_vip_max_share = float(os.getenv("CLUSTER_VIP_MAX_SHARE", "0.45"))
        self.cluster_growth_outlier_reassign = (
            os.getenv("CLUSTER_GROWTH_OUTLIER_REASSIGN", "true").lower() == "true"
        )
        self.cluster_growth_reassign_distance_quantile = float(
            os.getenv("CLUSTER_GROWTH_REASSIGN_DISTANCE_Q", "0.90")
        )
        self.cluster_growth_reassign_distance_multiplier = float(
            os.getenv("CLUSTER_GROWTH_REASSIGN_DISTANCE_MULT", "1.15")
        )
        self.cluster_growth_high_value_quantile = float(
            os.getenv("CLUSTER_GROWTH_HIGH_VALUE_Q", "0.70")
        )
        self.cluster_growth_reassign_high_value_multiplier = float(
            os.getenv("CLUSTER_GROWTH_REASSIGN_HIGH_VALUE_MULT", "1.50")
        )
        self.cluster_growth_fallback_outlier_ratio = float(
            os.getenv("CLUSTER_GROWTH_FALLBACK_OUTLIER_RATIO", "0.50")
        )
        self.alert_revenue_drop_sharp_pct = float(
            os.getenv("ALERT_REVENUE_DROP_SHARP_PCT", "35.0")
        )
        self.alert_churn_jump_delta = float(os.getenv("ALERT_CHURN_JUMP_DELTA", "0.15"))
        self.alert_churn_high_level = float(os.getenv("ALERT_CHURN_HIGH_LEVEL", "0.45"))
        self.alert_credit_jump_delta = float(os.getenv("ALERT_CREDIT_JUMP_DELTA", "0.15"))
        self.alert_credit_high_level = float(os.getenv("ALERT_CREDIT_HIGH_LEVEL", "0.55"))
        self.nl_query_partner_scan_limit = max(
            20, int(os.getenv("NL_QUERY_PARTNER_SCAN_LIMIT", "300"))
        )
        self.openai_api_key = os.getenv("OPENAI_API_KEY", "")
        self.openai_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        # ── Date range filter (set by the sidebar; persisted on engine instance) ─────
        self._date_start = None
        self._date_end = None

    # ────────────────────────────────────────────────────────────────
    # Date range helpers
    # ────────────────────────────────────────────────────────────────
    def set_date_range(self, date_start, date_end):
        """Called from sidebar. Stores the selected window for downstream filtering.

        Does NOT invalidate the engine cache — the full dataset is loaded once
        and filtered at query time via get_date_filtered_fact() / get_date_filtered_ml().
        Adjust gap_lookback_days to match the selected window so peer-gap analysis
        is always in sync with what the user is looking at.
        """
        import datetime
        import pandas as pd

        if isinstance(date_start, datetime.date):
            date_start = pd.Timestamp(date_start)
        if isinstance(date_end, datetime.date):
            date_end = pd.Timestamp(date_end)
        self._date_start = date_start
        self._date_end = date_end
        # Sync lookback window to the selected range
        if date_start and date_end:
            self.gap_lookback_days = max(30, (date_end - date_start).days)

    def get_date_filtered_fact(self):
        """Return df_fact filtered to the selected date window.

        Falls back to the full df_fact if no date range is set or if the
        DataFrame has no recognisable date column.
        """
        import pandas as pd
        if self.df_fact is None:
            return None
        if self._date_start is None or self._date_end is None:
            return self.df_fact
        # Detect the date column (handles different naming conventions)
        date_col = next(
            (c for c in ["sale_date", "date", "order_date", "transaction_date", "invoice_date"]
             if c in self.df_fact.columns),
            None,
        )
        if date_col is None:
            return self.df_fact
        df = self.df_fact.copy()
        df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
        mask = (df[date_col] >= self._date_start) & (df[date_col] <= self._date_end)
        filtered = df[mask]
        return filtered if not filtered.empty else self.df_fact

    def get_date_filtered_ml(self):
        """Return df_ml filtered to the selected date window (last_activity / date column)."""
        import pandas as pd
        if self.df_ml is None:
            return None
        if self._date_start is None or self._date_end is None:
            return self.df_ml
        date_col = next(
            (c for c in ["last_activity_date", "sale_date", "date", "order_date"]
             if c in self.df_ml.columns),
            None,
        )
        if date_col is None:
            return self.df_ml
        df = self.df_ml.copy()
        df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
        mask = (df[date_col] >= self._date_start) & (df[date_col] <= self._date_end)
        filtered = df[mask]
        return filtered if not filtered.empty else self.df_ml

