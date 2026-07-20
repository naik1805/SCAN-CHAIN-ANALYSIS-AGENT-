"""Load failure frames and topology via existing parsers / cache (no algorithm changes)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd

from .paths import CACHE_DIR, DATA_DIR, LOG_DIR, OUTPUT_DIR, PROJECT_ROOT, ensure_src_on_path


def _paths_info(paths: list[Path]) -> list[tuple[str, float, int]]:
    info: list[tuple[str, float, int]] = []
    for p in paths:
        try:
            st = p.stat()
            info.append((str(p), st.st_mtime, st.st_size))
        except OSError:
            continue
    return info


def select_logs(max_per_lot: int | None = None) -> list[Path]:
    """Return ATE log paths. ``max_per_lot=None`` (or <=0) keeps **all** logs."""
    ensure_src_on_path()
    from parser import discover_logs

    logs = list(discover_logs(LOG_DIR))
    if max_per_lot is None or max_per_lot <= 0:
        return logs

    kept: list[Path] = []
    seen: dict[str, int] = {}
    for p in logs:
        lot = p.parent.name
        if seen.get(lot, 0) < max_per_lot:
            kept.append(p)
            seen[lot] = seen.get(lot, 0) + 1
    return kept


def active_stil_filename() -> str:
    """Return the STIL (or topology markdown) basename in use."""
    ensure_src_on_path()
    from stil_parser import (
        find_topology_md_file,
        resolve_active_stil_file,
    )

    md = find_topology_md_file(DATA_DIR)
    if md:
        return md.name
    stil = resolve_active_stil_file()
    return stil.name if stil else "—"


def active_log_filenames(max_per_lot: int | None = None) -> list[str]:
    """Return log labels as ``<lot_folder>/<filename>`` for uniqueness across lots."""
    return [f"{p.parent.name}/{p.name}" for p in select_logs(max_per_lot=max_per_lot)]


def _prepare_failures_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize dtypes and run sklearn ML (RandomForest + IsolationForest)."""
    if df.empty:
        return df
    out = df.copy()
    for col in out.columns:
        if out[col].dtype.name == "category":
            out[col] = out[col].astype(object)
    import ml_pipeline as mlp

    return mlp.apply_failure_ml(out)


def summarize_failure_ml_status(df: pd.DataFrame) -> dict[str, Any]:
    """Plain-language ML status for client-facing UI."""
    empty = {
        "active": False,
        "failure_records_analyzed": 0,
        "root_cause_model": "Random Forest",
        "anomaly_model": "Isolation Forest",
        "confidence_model": "Gradient Boosting (verified history)",
        "root_causes_estimated": 0,
        "anomaly_flagged_count": 0,
        "anomaly_flagged_pct": 0.0,
        "client_summary": "AI models are ready — load failure logs to run analysis.",
    }
    if df is None or df.empty:
        return empty

    n = int(len(df))
    has_pred = "predicted_root_cause" in df.columns
    has_anomaly = "is_anomaly" in df.columns

    root_estimated = 0
    if has_pred:
        pred = df["predicted_root_cause"].fillna("UNKNOWN").astype(str).str.upper().str.strip()
        root_estimated = int(((pred != "UNKNOWN") & (pred != "") & (pred != "N/A")).sum())

    anomaly_count = int(df["is_anomaly"].sum()) if has_anomaly and df["is_anomaly"].notna().any() else 0
    anomaly_pct = round(anomaly_count / n * 100, 1) if n else 0.0
    rf_active = has_pred and root_estimated > 0

    if rf_active:
        summary = (
            f"AI analyzed {n:,} test failures. "
            f"Root cause estimated for {root_estimated:,} records. "
            f"{anomaly_pct:.1f}% flagged as unusual for engineer review. "
            f"Scan-cell confidence uses a model trained on past physical confirmations."
        )
    else:
        summary = (
            f"{n:,} failures loaded — root-cause AI will run when physical features are available."
        )

    return {
        "active": rf_active,
        "failure_records_analyzed": n,
        "root_cause_model": "Random Forest",
        "anomaly_model": "Isolation Forest",
        "confidence_model": "Gradient Boosting (verified history)",
        "root_causes_estimated": root_estimated,
        "anomaly_flagged_count": anomaly_count,
        "anomaly_flagged_pct": anomaly_pct,
        "client_summary": summary,
    }


def load_failures(max_per_lot: int | None = None) -> tuple[pd.DataFrame, str]:
    """Return (failures_df, source_label). Prefers disk cache, then parse.

    Default ``max_per_lot=None`` loads **every** discovered ATE log so FAIL
    record counts match the full parsed population (not a per-lot sample).

    Parsed/cached rows are enriched with ``ml_pipeline.apply_failure_ml``
    (RandomForest root-cause + IsolationForest anomalies) before localization.
    """
    ensure_src_on_path()
    from disk_cache import load_from_cache, save_to_cache
    from parser import parse_log_to_dataframe, records_to_dataframe
    from schema import normalize_failure_schema

    paths = select_logs(max_per_lot=max_per_lot)
    if not paths:
        # Warm parquet fallback (any recent cache)
        parquets = sorted(CACHE_DIR.glob("logs_*.parquet"), key=lambda p: p.stat().st_mtime, reverse=True)
        if parquets:
            df = normalize_failure_schema(pd.read_parquet(parquets[0]))
            return _prepare_failures_frame(df), f"cache:{parquets[0].name}"
        return records_to_dataframe({}, []), "empty"

    info = _paths_info(paths)
    cached = load_from_cache(info, PROJECT_ROOT)
    if cached is not None and not cached.empty:
        return _prepare_failures_frame(normalize_failure_schema(cached)), f"cache:{len(paths)} logs"

    frames = [parse_log_to_dataframe(p, keep_status="FAIL") for p in paths]
    frames = [f for f in frames if f is not None and not f.empty]
    if not frames:
        return records_to_dataframe({}, []), "empty"
    df = pd.concat(frames, ignore_index=True)
    save_to_cache(df, info, PROJECT_ROOT)
    return _prepare_failures_frame(df), f"parsed:{len(paths)} logs"


def load_chain_map() -> tuple[dict, str]:
    ensure_src_on_path()
    from stil_parser import (
        find_topology_md_file,
        parse_hardware_topology_md,
        parse_stil_scan_structures,
        resolve_active_stil_file,
    )

    md = find_topology_md_file(DATA_DIR)
    if md:
        return parse_hardware_topology_md(md), f"topology:{md.name}"
    stil = resolve_active_stil_file()
    if stil:
        return parse_stil_scan_structures(stil), f"stil:{stil.name}"
    return {}, "none"


def read_export_json(name: str) -> dict[str, Any] | None:
    path = OUTPUT_DIR / name
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


@lru_cache(maxsize=1)
def list_filter_options_cached() -> dict[str, list[str]]:
    df, _ = load_failures(max_per_lot=None)
    lots: list[str] = []
    wafers: list[str] = []
    if not df.empty:
        if "lot_id" in df.columns:
            lots = sorted(df["lot_id"].dropna().astype(str).unique().tolist())
        if "wafer_id" in df.columns:
            wafers = sorted(df["wafer_id"].dropna().astype(str).unique().tolist())
    # Honest: no fab/tester columns in current schema
    return {
        "lots": lots,
        "wafers": wafers,
        "testers": [],
        "fabs": [],
        "dates": [],
    }
