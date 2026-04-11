"""
Data schema contracts for major DB views and tables.

Each contract exposes a `validate(df)` classmethod returning a ValidationResult.
Use these at load time to catch structural drift early.

Contracts defined:
  - ViewMlInputContract       → view_ml_input
  - FactSalesIntelligenceContract → fact_sales_intelligence
  - ViewAgeingStockContract   → view_ageing_stock
  - PartnerFeaturesContract   → df_partner_features (in-memory)
  - ClusterAssignmentsContract → cluster_assignments / matrix

Usage:
    result = ViewMlInputContract.validate(df)
    if not result.valid:
        for err in result.errors:
            print(f"SCHEMA ERROR: {err}")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd


# ─────────────────────────────────────────────────────────────────
# Result container
# ─────────────────────────────────────────────────────────────────

@dataclass
class ValidationResult:
    valid: bool = True
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "valid": self.valid,
            "errors": self.errors,
            "warnings": self.warnings,
        }

    def merge(self, other: "ValidationResult") -> "ValidationResult":
        self.valid = self.valid and other.valid
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)
        return self


# ─────────────────────────────────────────────────────────────────
# Base helper
# ─────────────────────────────────────────────────────────────────

class _BaseContract:
    NAME: str = "unknown"

    # Each entry: (column_name, dtype_kind, nullable)
    # dtype_kind: "numeric" | "object" | "bool" | "datetime" | "any"
    COLUMNS: List[tuple] = []

    @classmethod
    def validate(cls, df: Optional[pd.DataFrame]) -> ValidationResult:
        result = ValidationResult()

        if df is None or df.empty:
            result.valid = False
            result.errors.append(f"{cls.NAME}: DataFrame is empty or None.")
            return result

        for col, dtype_kind, nullable in cls.COLUMNS:
            if col not in df.columns:
                result.valid = False
                result.errors.append(f"{cls.NAME}: Missing required column '{col}'.")
                continue

            series = df[col]
            null_ratio = float(series.isna().mean())
            if not nullable and null_ratio > 0:
                result.warnings.append(
                    f"{cls.NAME}: Column '{col}' has {null_ratio:.1%} nulls (expected non-null)."
                )

            if dtype_kind == "numeric":
                if not pd.api.types.is_numeric_dtype(series):
                    result.warnings.append(
                        f"{cls.NAME}: Column '{col}' expected numeric, got {series.dtype}."
                    )
            elif dtype_kind == "bool":
                if not (pd.api.types.is_bool_dtype(series) or
                        set(series.dropna().unique()).issubset({True, False, 0, 1, "true", "false"})):
                    result.warnings.append(
                        f"{cls.NAME}: Column '{col}' expected boolean-like values."
                    )
            elif dtype_kind == "datetime":
                if not pd.api.types.is_datetime64_any_dtype(series):
                    result.warnings.append(
                        f"{cls.NAME}: Column '{col}' expected datetime64, got {series.dtype}."
                    )
            # "object" and "any" — no strict dtype checks

        return result


# ─────────────────────────────────────────────────────────────────
# Contract 1 — view_ml_input
# ─────────────────────────────────────────────────────────────────

class ViewMlInputContract(_BaseContract):
    """
    Core ML input view: partner × product-group spend.
    Required for all feature engineering and clustering.
    """
    NAME = "view_ml_input"
    COLUMNS = [
        ("company_name", "object",  False),
        ("group_name",   "object",  False),
        ("total_spend",  "numeric", False),
        ("state",        "object",  True),
    ]

    @classmethod
    def validate(cls, df: Optional[pd.DataFrame]) -> ValidationResult:
        result = super().validate(df)
        if df is not None and "total_spend" in df.columns:
            neg = int((pd.to_numeric(df["total_spend"], errors="coerce").fillna(0) < 0).sum())
            if neg > 0:
                result.warnings.append(
                    f"{cls.NAME}: {neg} rows have negative total_spend — check for credit notes."
                )
            dupes = int(df.duplicated(subset=["company_name", "group_name"], keep=False).sum())
            if dupes > 0:
                result.warnings.append(
                    f"{cls.NAME}: {dupes} duplicate (company_name, group_name) rows detected."
                )
        return result


# ─────────────────────────────────────────────────────────────────
# Contract 2 — fact_sales_intelligence
# ─────────────────────────────────────────────────────────────────

class FactSalesIntelligenceContract(_BaseContract):
    """
    Pre-computed partner KPI fact table / view.
    Drives the Partner 360 and most downstream tabs.
    """
    NAME = "fact_sales_intelligence"
    COLUMNS = [
        ("company_name",        "object",  False),
        ("health_status",       "object",  True),
        ("recent_90_revenue",   "numeric", True),
        ("prev_90_revenue",     "numeric", True),
        ("lifetime_revenue",    "numeric", True),
        ("recency_days",        "numeric", True),
        ("revenue_drop_pct",    "numeric", True),
        ("growth_rate_90d",     "numeric", True),
    ]

    @classmethod
    def validate(cls, df: Optional[pd.DataFrame]) -> ValidationResult:
        result = super().validate(df)
        if df is not None and "recent_90_revenue" in df.columns:
            neg = int((pd.to_numeric(df["recent_90_revenue"], errors="coerce").fillna(0) < 0).sum())
            if neg > 0:
                result.warnings.append(
                    f"{cls.NAME}: {neg} partners with negative recent_90_revenue."
                )
        return result


# ─────────────────────────────────────────────────────────────────
# Contract 3 — view_ageing_stock
# ─────────────────────────────────────────────────────────────────

class ViewAgeingStockContract(_BaseContract):
    """
    Inventory ageing / dead-stock view.
    Used by the Inventory Liquidation module.
    """
    NAME = "view_ageing_stock"
    COLUMNS = [
        ("product_name",    "object",  False),
        ("total_stock_qty", "numeric", True),
        ("max_age_days",    "numeric", True),
    ]

    @classmethod
    def validate(cls, df: Optional[pd.DataFrame]) -> ValidationResult:
        result = super().validate(df)
        if df is not None and "max_age_days" in df.columns:
            neg = int((pd.to_numeric(df["max_age_days"], errors="coerce").fillna(0) < 0).sum())
            if neg > 0:
                result.warnings.append(
                    f"{cls.NAME}: {neg} rows have negative max_age_days — likely a date calculation error."
                )
        return result


# ─────────────────────────────────────────────────────────────────
# Contract 4 — partner_features (in-memory df_partner_features)
# ─────────────────────────────────────────────────────────────────

class PartnerFeaturesContract(_BaseContract):
    """
    In-memory partner feature matrix (df_partner_features).
    Built by BaseLoaderMixin._load_partner_features().
    Index is company_name.
    """
    NAME = "partner_features"
    COLUMNS = [
        ("churn_probability",    "numeric", True),
        ("credit_risk_score",    "numeric", True),
        ("health_score",         "numeric", True),
        ("health_segment",       "object",  True),
        ("recent_90_revenue",    "numeric", True),
        ("recency_days",         "numeric", True),
        ("revenue_drop_pct",     "numeric", True),
    ]

    @classmethod
    def validate(cls, df: Optional[pd.DataFrame]) -> ValidationResult:
        result = super().validate(df)
        if df is not None:
            for col in ("churn_probability", "credit_risk_score", "health_score"):
                if col in df.columns:
                    s = pd.to_numeric(df[col], errors="coerce").dropna()
                    out_of_range = int(((s < 0) | (s > 1)).sum())
                    if out_of_range > 0:
                        result.warnings.append(
                            f"{cls.NAME}: {out_of_range} values in '{col}' outside [0, 1]."
                        )
        return result


# ─────────────────────────────────────────────────────────────────
# Contract 5 — cluster_assignments (matrix)
# ─────────────────────────────────────────────────────────────────

class ClusterAssignmentsContract(_BaseContract):
    """
    Cluster assignment matrix (ai.matrix).
    Produced by ClusteringMixin.run_clustering().
    Index is company_name.
    """
    NAME = "cluster_assignments"
    COLUMNS = [
        ("cluster",       "numeric", False),
        ("cluster_type",  "object",  False),
        ("cluster_label", "object",  False),
        ("strategic_tag", "object",  True),
    ]

    @classmethod
    def validate(cls, df: Optional[pd.DataFrame]) -> ValidationResult:
        result = super().validate(df)
        if df is not None:
            if "cluster_type" in df.columns:
                allowed = {"VIP", "Growth"}
                bad = set(df["cluster_type"].dropna().unique()) - allowed
                if bad:
                    result.warnings.append(
                        f"{cls.NAME}: Unexpected cluster_type values: {sorted(bad)}. "
                        f"Expected one of {allowed}."
                    )
            if "cluster_label" in df.columns:
                blank = int(df["cluster_label"].astype(str).str.strip().eq("").sum())
                if blank > 0:
                    result.warnings.append(
                        f"{cls.NAME}: {blank} partners have blank cluster_label."
                    )
        return result


# ─────────────────────────────────────────────────────────────────
# Convenience: validate all known DataFrames at once
# ─────────────────────────────────────────────────────────────────

def validate_all(
    df_ml: Optional[pd.DataFrame] = None,
    df_fact: Optional[pd.DataFrame] = None,
    df_stock: Optional[pd.DataFrame] = None,
    df_partner_features: Optional[pd.DataFrame] = None,
    df_matrix: Optional[pd.DataFrame] = None,
) -> Dict[str, ValidationResult]:
    results = {}
    if df_ml is not None:
        results["view_ml_input"] = ViewMlInputContract.validate(df_ml)
    if df_fact is not None:
        results["fact_sales_intelligence"] = FactSalesIntelligenceContract.validate(df_fact)
    if df_stock is not None:
        results["view_ageing_stock"] = ViewAgeingStockContract.validate(df_stock)
    if df_partner_features is not None:
        results["partner_features"] = PartnerFeaturesContract.validate(df_partner_features)
    if df_matrix is not None:
        results["cluster_assignments"] = ClusterAssignmentsContract.validate(df_matrix)
    return results
