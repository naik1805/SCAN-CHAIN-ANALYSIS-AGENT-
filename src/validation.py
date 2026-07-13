"""
validation.py — Input validation and data quality checks.

All inbound DataFrames and config objects pass through this module
before any processing begins.  Failures raise typed exceptions from
``exceptions.py`` with actionable messages.

Public API::

    validate_log_dataframe(df)       → raises ValidationError if schema bad
    validate_chain_map(chain_map)    → raises ValidationError if map empty/corrupt
    data_quality_report(df)          → dict of completeness metrics
    detect_duplicate_records(df)     → DataFrame of duplicate rows
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from exceptions import ValidationError

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Required columns that every parsed log DataFrame must contain
# ---------------------------------------------------------------------------

_REQUIRED_COLUMNS: frozenset[str] = frozenset({
    "lot_id",
    "source_file",
    "chain_id",
    "chain",
    "fail_flop_id",
    "fail_type",
})

_PHYSICAL_FEATURE_COLUMNS: tuple[str, ...] = (
    "ir_drop_mv",
    "thermal_c",
    "setup_slack_ps",
    "hold_slack_ps",
)


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

def validate_log_dataframe(df: pd.DataFrame) -> None:
    """Assert that *df* conforms to the expected failure-log schema.

    Args:
        df: Parsed failure DataFrame produced by ``parser.parse_log_to_dataframe``.

    Raises:
        ValidationError: If required columns are missing or the DataFrame is empty.
    """
    if df.empty:
        raise ValidationError(
            "Parsed DataFrame is empty — no FAIL records found. "
            "Check that the log files contain STATUS : FAIL blocks."
        )

    missing = sorted(_REQUIRED_COLUMNS - set(df.columns))
    if missing:
        raise ValidationError(
            "Parsed log DataFrame is missing required columns.",
            missing_columns=missing,
        )

    # Warn (don't raise) if physical feature columns are absent — ML is optional
    missing_feat = [c for c in _PHYSICAL_FEATURE_COLUMNS if c not in df.columns]
    if missing_feat:
        log.warning(
            "Physical feature columns %s are missing — ML root-cause "
            "prediction will be skipped.",
            missing_feat,
        )


def validate_chain_map(chain_map: dict[str, Any]) -> None:
    """Assert that *chain_map* is a non-empty dict of chain descriptors.

    Args:
        chain_map: Dict returned by ``stil_parser.parse_stil_scan_structures``
                   or ``parse_hardware_topology_md``.

    Raises:
        ValidationError: If the map is None, not a dict, or contains no chains.
    """
    if not isinstance(chain_map, dict):
        raise ValidationError(
            f"chain_map must be a dict, got {type(chain_map).__name__}."
        )
    if not chain_map:
        raise ValidationError(
            "chain_map is empty — no scan chains were parsed from the STIL / "
            "topology file.  Check that the file exists and is correctly formatted."
        )


# ---------------------------------------------------------------------------
# Data quality report
# ---------------------------------------------------------------------------

def data_quality_report(df: pd.DataFrame) -> dict[str, Any]:
    """Compute per-column completeness and overall data quality metrics.

    Args:
        df: Any DataFrame (typically the parsed failure log).

    Returns:
        Dict with keys:
        - ``total_records``     : int — total row count
        - ``columns``           : dict[str, dict] — per-column stats
        - ``overall_completeness_pct`` : float — mean completeness across all cols
        - ``duplicate_count``   : int — number of exact duplicate rows
    """
    if df.empty:
        return {
            "total_records": 0,
            "columns": {},
            "overall_completeness_pct": 0.0,
            "duplicate_count": 0,
        }

    total = len(df)
    col_stats: dict[str, dict] = {}
    completeness_values: list[float] = []

    for col in df.columns:
        null_count = int(df[col].isna().sum())
        completeness = round((total - null_count) / total * 100, 2)
        completeness_values.append(completeness)
        col_stats[col] = {
            "null_count": null_count,
            "completeness_pct": completeness,
            "dtype": str(df[col].dtype),
        }

    overall = round(sum(completeness_values) / len(completeness_values), 2) if completeness_values else 0.0
    dup_count = int(df.duplicated().sum())

    return {
        "total_records": total,
        "columns": col_stats,
        "overall_completeness_pct": overall,
        "duplicate_count": dup_count,
    }


# ---------------------------------------------------------------------------
# Duplicate detection
# ---------------------------------------------------------------------------

def detect_duplicate_records(df: pd.DataFrame) -> pd.DataFrame:
    """Return a DataFrame of exact duplicate rows.

    Args:
        df: Parsed failure DataFrame.

    Returns:
        Subset of *df* containing only duplicate rows (all occurrences).
        Empty DataFrame if no duplicates are found.
    """
    if df.empty:
        return df
    mask = df.duplicated(keep=False)
    duplicates = df[mask].copy()
    if not duplicates.empty:
        log.warning(
            "Detected %d duplicate records out of %d total (%.1f%%).",
            len(duplicates),
            len(df),
            len(duplicates) / len(df) * 100,
        )
    return duplicates


__all__ = [
    "validate_log_dataframe",
    "validate_chain_map",
    "data_quality_report",
    "detect_duplicate_records",
]
