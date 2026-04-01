from dataclasses import asdict, dataclass, field


@dataclass
class DataQualityReport:
    rows: int = 0
    status: str = "ok"
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


@dataclass
class ChurnModelReport:
    status: str = "failed"
    reason: str = ""
    train_samples: int = 0
    valid_samples: int = 0
    positive_rate_train: float | None = None
    positive_rate_valid: float | None = None
    roc_auc: float | None = None
    avg_precision: float | None = None

    def to_dict(self):
        return asdict(self)


@dataclass
class CreditRiskReport:
    status: str = "failed"
    reason: str = ""
    covered_partners: int = 0
    high_risk_partners: int = 0
    avg_credit_risk_score: float | None = None

    def to_dict(self):
        return asdict(self)


@dataclass
class MonitoringSnapshot:
    data_quality_status: str = "unknown"
    partner_count: int = 0
    cluster_count: int = 0
    outlier_count: int = 0
    avg_health_score: float | None = None
    avg_churn_probability: float | None = None
    avg_credit_risk_score: float | None = None
    high_credit_risk_partners: int = 0

    def to_dict(self):
        return asdict(self)
