"""
Diagnosis service — presentation aggregation only.

Calls existing FR helpers (ranking, breaks, locate_cells, topology, confidence)
without modifying their algorithms. Falls back to ``output/SCD-FR-*.json`` exports
when live compute is unavailable.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
import hashlib
import time

import pandas as pd

from api.models.schemas import (
    CopilotResponse,
    DatasetSummary,
    DiagnosisDashboard,
    FilterOptions,
    KpiCard,
    KpiWorkspace,
    MlStatusSummary,
    SparkPoint,
    WorkspacePanel,
)

from .data_loader import (
    active_log_filenames,
    active_stil_filename,
    list_filter_options_cached,
    load_chain_map,
    load_failures,
    read_export_json,
    select_logs,
    summarize_failure_ml_status,
)
from .paths import DATA_DIR, OUTPUT_DIR, PROJECT_ROOT, ensure_src_on_path

LOG_DIR = DATA_DIR / "logs"

# In-process dashboard cache keyed by log fingerprint (+ lot/wafer)
_DASHBOARD_CACHE: dict[str, tuple[float, DiagnosisDashboard]] = {}


def _logs_fingerprint() -> str:
    paths = select_logs(max_per_lot=None)
    parts: list[str] = []
    for p in paths:
        try:
            st = p.stat()
            parts.append(f"{p}:{st.st_mtime_ns}:{st.st_size}")
        except OSError:
            parts.append(str(p))
    raw = "|".join(parts) if parts else "empty"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _production_cfg() -> Any:
    ensure_src_on_path()
    from config import get_config

    return get_config().production


def _run_production_hardening(
    failures: pd.DataFrame,
    suspects: pd.DataFrame,
    breaks_df: pd.DataFrame,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Lot-holdout validation + review seed + optional auto-retrain."""
    ensure_src_on_path()
    from holdout_validation import compute_production_validation
    from model_lifecycle import maybe_retrain, lifecycle_summary
    from review_queue import queue_summary, seed_review_queue

    cfg = _production_cfg()
    fp = _logs_fingerprint()
    breaks_records = _df_to_records(breaks_df)

    # Seed pending reviews only for a new / empty dataset fingerprint.
    # Same data that was already reviewed stays at 0 pending until logs change.
    if getattr(cfg, "auto_seed_reviews", True):
        try:
            from review_queue import load_queue, _queue_path, _save_json

            q = load_queue()
            prev_fp = q.get("seeded_fingerprint")
            if not prev_fp and int(queue_summary().get("total") or 0) > 0:
                # Stamp current data so we do not re-seed reviewed history
                q["seeded_fingerprint"] = fp
                _save_json(_queue_path(), q)
            elif prev_fp != fp or int(queue_summary().get("total") or 0) == 0:
                seed_review_queue(suspects, breaks_records, fingerprint=fp)
        except Exception:
            import logging
            logging.getLogger(__name__).exception("review queue seed failed")

    # Always read live queue for KPI — never stale relative to reviews
    live_reviews = queue_summary()

    try:
        retrain_info = maybe_retrain(
            failures,
            force=False,
            threshold=int(getattr(cfg, "retrain_feedback_threshold", 25) or 25),
        )
    except Exception as exc:
        retrain_info = {"retrained": False, "reason": f"error:{exc}"}

    try:
        validation = compute_production_validation(
            failures,
            suspects,
            breaks_records,
            fingerprint=fp,
            use_cache=True,
        )
    except Exception as exc:
        validation = {
            "readiness_grade": "unknown",
            "readiness_score_pct": None,
            "client_summary": f"Validation error: {exc}",
        }

    validation["review_queue"] = live_reviews
    validation["lifecycle"] = lifecycle_summary()
    validation["model_lifecycle"] = validation["lifecycle"]
    validation["last_retrain_attempt"] = {
        "retrained": retrain_info.get("retrained"),
        "reason": retrain_info.get("reason"),
    }
    validation["retrain"] = retrain_info
    return validation, live_reviews


def sync_review_queue(*, seed_if_needed: bool = True, limit: int = 100) -> dict[str, Any]:
    """Live review summary + pending items; seed when log fingerprint changes.

    Used by the Pending Reviews KPI/workspace so confirms and new-data seeds
    show up without requiring a full page reload / full dashboard rebuild.
    """
    ensure_src_on_path()
    from review_queue import (
        load_queue,
        pending_items,
        queue_summary,
        seed_review_queue,
        _queue_path,
        _save_json,
    )
    from model_lifecycle import lifecycle_summary

    fp = _logs_fingerprint()
    q = load_queue()
    prev_fp = q.get("seeded_fingerprint")
    seeded = False
    seed_info: dict[str, Any] = {}

    if seed_if_needed:
        total = int(queue_summary().get("total") or 0)
        needs_seed = (prev_fp != fp) or total == 0
        if not prev_fp and total > 0:
            # Legacy queue without fingerprint — stamp, do not re-seed history
            q["seeded_fingerprint"] = fp
            _save_json(_queue_path(), q)
            needs_seed = False
        if needs_seed:
            try:
                from api.adapters.data_loader import load_chain_map, load_failures
                from chain_breaks import detect_chain_breaks
                from locate_cells import locate_failing_cells

                failures, _ = load_failures(max_per_lot=None)
                chain_map, _ = load_chain_map()
                suspects = locate_failing_cells(failures, chain_map, min_observations=2)
                breaks_df = detect_chain_breaks(failures, chain_map)
                seed_info = seed_review_queue(
                    suspects,
                    _df_to_records(breaks_df),
                    fingerprint=fp,
                )
                seeded = int(seed_info.get("added") or 0) > 0 or bool(seed_info.get("new_dataset"))
                _DASHBOARD_CACHE.clear()
            except Exception as exc:
                import logging

                logging.getLogger(__name__).exception("sync_review_queue seed failed")
                seed_info = {"error": str(exc)}

    summary = queue_summary()
    return {
        "summary": summary,
        "items": pending_items(limit=limit),
        "lifecycle": lifecycle_summary(),
        "fingerprint": fp,
        "seeded": seeded,
        "seed": seed_info,
    }


def apply_review_summary_to_dashboard_kpis(
    dash: DiagnosisDashboard,
    summary: dict[str, Any],
) -> DiagnosisDashboard:
    """Patch Pending Reviews KPI + production_validation from a live queue summary."""
    pending = int(summary.get("pending") or 0)
    confirmed = int(summary.get("confirmed") or 0)
    feedback = int(summary.get("feedback_records") or 0)
    kpis = []
    for card in dash.kpis:
        if card.id == "pending_reviews":
            kpis.append(
                card.model_copy(
                    update={
                        "value": pending,
                        "badge": f"{confirmed} confirmed · {feedback} verified feedback",
                        "status": "ok",
                    }
                )
            )
        else:
            kpis.append(card)
    prod = dict(dash.production_validation or {})
    prod["review_queue"] = summary
    return dash.model_copy(update={"kpis": kpis, "production_validation": prod})


# ---------------------------------------------------------------------------
# Presentation helpers
# ---------------------------------------------------------------------------

def _debug_location_count(fr009: dict[str, Any] | None) -> int:
    if not fr009:
        return 0
    summary = fr009.get("summary") if isinstance(fr009.get("summary"), dict) else {}
    for key in ("total_recommended_cells", "total_locations", "total_debug_locations"):
        if summary.get(key) is not None:
            try:
                return int(summary[key])
            except (TypeError, ValueError):
                pass
    for key in ("recommendations", "locations", "debug_locations", "cells"):
        val = fr009.get(key)
        if isinstance(val, list):
            return len(val)
    return 0


def _build_unavailable_dashboard(exc: Optional[Exception] = None) -> DiagnosisDashboard:
    """Empty dashboard shell with real discovered log/failure counts (no decorative KPIs)."""
    opts = list_filter_options_cached()
    logs = active_log_filenames(max_per_lot=None)
    try:
        failures_df, src = load_failures(max_per_lot=None)
    except Exception:
        failures_df = pd.DataFrame()
        src = "unavailable"
    ml = summarize_failure_ml_status(failures_df)
    err = f"{type(exc).__name__}: {exc}" if exc else "engine unavailable"
    return DiagnosisDashboard(
        data_source="fastapi-live",
        mode="live",
        filters=FilterOptions(**opts),
        dataset_summary=DatasetSummary(
            stil_file=active_stil_filename(),
            log_files=logs,
            log_file_count=len(logs),
            total_failure_records=int(len(failures_df)),
            failing_chains=0,
            all_chains=0,
            failing_flops=0,
        ),
        ml_status=MlStatusSummary(**ml) if isinstance(ml, dict) else MlStatusSummary(),
        kpis=[],
        ranking=[],
        correlations=[],
        shift_capture={},
        confidence={},
        topology_summary={},
        breaks_table=[],
        cells_table=[],
        reports_meta={"html_exists": (OUTPUT_DIR / "SCD-FR-008_scan_diagnosis_report.html").exists()},
        footer=f"Dashboard unavailable ({err}). Loader: {src}.",
    )


def _spark_from_lots(df: pd.DataFrame, value_fn) -> list[SparkPoint]:
    if df.empty or "lot_id" not in df.columns:
        return []
    points: list[SparkPoint] = []
    for lot, sub in df.groupby("lot_id", sort=True):
        try:
            points.append(SparkPoint(x=str(lot), y=float(value_fn(sub))))
        except Exception:
            continue
    return points[:12]


def _trend_pct(spark: list[SparkPoint]) -> Optional[float]:
    if len(spark) < 2:
        return None
    a, b = spark[-2].y, spark[-1].y
    if a == 0:
        return None
    return round(((b - a) / abs(a)) * 100, 1)


def _filter_df(df: pd.DataFrame, lot: Optional[str], wafer: Optional[str]) -> pd.DataFrame:
    out = df
    if lot and "lot_id" in out.columns:
        out = out[out["lot_id"].astype(str) == str(lot)]
    if wafer and "wafer_id" in out.columns:
        out = out[out["wafer_id"].astype(str) == str(wafer)]
    return out


def _df_to_records(df: pd.DataFrame, n: Optional[int] = None) -> list[dict[str, Any]]:
    """Serialize dataframe rows for JSON; safe for categorical / nullable dtypes.

    When ``n`` is None, return all rows (no silent truncation). Pass ``n`` only
    when a deliberate cap is required (e.g. chart preview payloads).
    """
    if df is None or df.empty:
        return []
    # Categorical fillna("") raises; cast to object first.
    out = (df.head(n) if n is not None else df).astype(object)
    return out.where(pd.notna(out), "").to_dict(orient="records")


# Preferred column order for FR-001 raw FAIL extraction (matches Streamlit Phase 1).
_FAIL_RECORD_COLUMN_ORDER = [
    "source_file", "lot_folder", "tester_name", "test_program", "device_name",
    "lot_id", "defect_type", "die_label", "die_row", "die_col",
    "x1", "y1", "x2", "y2", "wafer_x", "wafer_y",
    "test_mode", "shift_cycles", "capture_cycles", "scan_chains", "total_patterns",
    "pattern_id", "channel_id", "chain", "expected_output", "status", "actual_output",
    "fail_flop_id", "fail_type", "failure_region", "root_cause_hint",
    "ir_drop_mv", "thermal_c", "setup_slack_ps", "hold_slack_ps",
    "ai_severity_score", "wafer_id", "instance", "chain_id",
]


def _fail_records_from_df(failures: pd.DataFrame) -> list[dict[str, Any]]:
    """Serialize all FAIL records for drill-down (SCD-FR-001 raw extraction)."""
    if failures is None or failures.empty:
        return []
    # Drop bulky nested / non-tabular columns if present
    drop_cols = [c for c in failures.columns if c in ("expected_actual_bitstreams",)]
    df = failures.drop(columns=drop_cols, errors="ignore").copy()
    # Stringify long bitstream fields for stable JSON
    for col in ("expected_output", "actual_output"):
        if col in df.columns:
            df[col] = df[col].map(lambda v: "" if pd.isna(v) else str(v))
    preferred = [c for c in _FAIL_RECORD_COLUMN_ORDER if c in df.columns]
    rest = [c for c in df.columns if c not in preferred]
    return _df_to_records(df[preferred + rest])


def _enrich_break_rows_for_visualizer(
    rows: list[dict[str, Any]],
    chain_map: dict[str, Any],
) -> list[dict[str, Any]]:
    """Attach STIL topology fields needed by the React break schematic."""
    ensure_src_on_path()
    from stil_parser import resolve_chain

    enriched: list[dict[str, Any]] = []
    for row in rows:
        r = dict(row)
        chain_id = str(r.get("chain_id") or r.get("chain") or "")
        chain = str(r.get("chain") or chain_id)
        info = resolve_chain(chain_map, chain_id, chain) if chain_map else None
        if info:
            if not r.get("chain_length"):
                r["chain_length"] = info.get("scan_length")
            r["hierarchical_path"] = info.get("hierarchical_path") or "U_core/unknown"
            r["decompressor_pin"] = info.get("decompressor_pin") or "UNKNOWN"
            r["compactor_pin"] = info.get("compactor_pin") or "UNKNOWN"
            r.setdefault("scan_in", info.get("scan_in") or "UNKNOWN")
            r.setdefault("scan_out", info.get("scan_out") or "UNKNOWN")
        else:
            r.setdefault("hierarchical_path", "U_core/unknown")
            r.setdefault("decompressor_pin", "UNKNOWN")
            r.setdefault("compactor_pin", "UNKNOWN")
        enriched.append(r)
    return enriched


def _breaks_distribution_by_lot(breaks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """FR-006 drill-down: break signature count per lot (Streamlit Phase 4 parity)."""
    if not breaks:
        return []
    counts: dict[str, int] = {}
    for row in breaks:
        lot = str(row.get("lot_id") or "UNKNOWN")
        counts[lot] = counts.get(lot, 0) + 1
    return [
        {"lot_id": lot, "scan_chain_break_count": count}
        for lot, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def _chain_sort_key(chain: str) -> tuple[int, str]:
    val = "".join(ch for ch in str(chain) if ch.isdigit())
    return (int(val) if val else 0, str(chain))


def _build_correlation_rows(
    df: pd.DataFrame,
    chain_map: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Optional[float]], dict[str, Any]]:
    """FR-005 per-chain Pearson correlations, categorical profiles, and chain averages."""
    ensure_src_on_path()
    from correlation_analysis import build_correlation_rows

    if chain_map is None:
        chain_map, _ = load_chain_map()
    return build_correlation_rows(df, chain_map=chain_map or None)


def _correlation_feature_count(corr_meta: dict[str, Any] | None) -> int:
    """Count metrics included in FR-005 chain signature / correlation analysis."""
    if not corr_meta:
        return 0
    explicit = corr_meta.get("correlation_feature_count")
    if explicit is not None:
        return int(explicit)
    count = len(corr_meta.get("numerical_features") or [])
    if corr_meta.get("region_field_used"):
        count += 1
    return count


REPORT_HTML_FILENAME = "SCD-FR-008_scan_diagnosis_report.html"


def report_html_path() -> Path:
    return OUTPUT_DIR / REPORT_HTML_FILENAME


def ensure_report_html_current() -> Path:
    """Regenerate FR-008 HTML when missing or still using the legacy capped layout."""
    path = report_html_path()
    needs_regen = not path.is_file()
    if not needs_regen:
        try:
            sample = path.read_text(encoding="utf-8", errors="ignore")[:12000]
            if "row-count" not in sample or "table-scroll" not in sample:
                needs_regen = True
            if "report-layout-v2" not in sample:
                needs_regen = True
        except OSError:
            needs_regen = True
    if needs_regen:
        ensure_src_on_path()
        from report_generator import generate_html_report

        df, _ = load_failures(max_per_lot=None)
        chain_map, _ = load_chain_map()
        path.parent.mkdir(parents=True, exist_ok=True)
        generate_html_report(
            df,
            chain_map,
            path,
            log_dir=LOG_DIR,
            project_root=PROJECT_ROOT,
        )
    return path


def _kpi_display(kpis: list[KpiCard], kpi_id: str, default: str = "—") -> str:
    card = next((k for k in kpis if k.id == kpi_id), None)
    if not card:
        return default
    return str(card.value)


def _build_report_preview(dash: DiagnosisDashboard) -> dict[str, Any]:
    """Structured FR-008-style summary for the diagnosis reports workspace."""
    html_path = ensure_report_html_current()
    html_exists = html_path.is_file()
    generated_at: str | None = None
    if html_exists:
        generated_at = datetime.fromtimestamp(
            html_path.stat().st_mtime, tz=timezone.utc,
        ).isoformat()

    ds = dash.dataset_summary
    kpis = dash.kpis
    sc = dash.shift_capture or {}
    topo = dash.topology_summary or {}
    breaks = dash.breaks_table or []
    n_certain = sum(1 for b in breaks if b.get("location_status") == "CERTAIN")
    n_uncertain = len(breaks) - n_certain

    sig_highlights: list[dict[str, Any]] = []
    for row in dash.correlations or []:
        bullets = row.get("signature_bullets") or []
        sig_highlights.append({
            "chain": row.get("chain"),
            "failure_count": row.get("failure_count"),
            "summary": bullets[1] if len(bullets) > 1 else (bullets[0] if bullets else ""),
        })
    sig_highlights.sort(key=lambda r: int(r.get("failure_count") or 0), reverse=True)

    debug_export = read_export_json("SCD-FR-009_debug_locations.json") or {}
    debug_n = _debug_location_count(debug_export)

    # Full lists aligned with the HTML report (min_obs=1 for cells).
    fr002 = read_export_json("SCD-FR-002_suspected_failing_cells.json") or {}
    ranked_all = list(dash.ranking or [])
    breaks_all = list(breaks)
    cells_all: list[dict[str, Any]] = []
    try:
        failures, _ = load_failures(max_per_lot=None)
        chain_map, _ = load_chain_map()
        ensure_src_on_path()
        from locate_cells import locate_failing_cells

        suspects = locate_failing_cells(failures, chain_map, min_observations=1)
        cells_all = _df_to_records(suspects) if not suspects.empty else []
    except Exception:
        cells_all = []
    if not cells_all:
        cells_all = list(
            fr002.get("suspected_cells")
            or fr002.get("top_suspected_cells")
            or dash.cells_table
            or []
        )

    sections: list[dict[str, Any]] = [
        {
            "number": 1,
            "title": "Executive Summary",
            "description": "Overview of the scan test failure analysis.",
            "stats": [
                {"label": "Failure records", "value": f"{ds.total_failure_records:,}"},
                {"label": "Log files", "value": str(ds.log_file_count)},
                {"label": "Failing chains", "value": str(ds.failing_chains)},
                {"label": "Topology chains", "value": str(topo.get("total_scan_chains", ds.all_chains))},
            ],
        },
        {
            "number": 2,
            "title": "Failing Scan Chains (FR-001)",
            "description": "Distinct scan chains with FAIL records in parsed logs.",
            "stats": [
                {"label": "Failing chains", "value": _kpi_display(kpis, "failing_chains")},
                {"label": "Top chain", "value": _kpi_display(kpis, "top_failing_chain")},
            ],
        },
        {
            "number": 3,
            "title": "Scan Chain Topology (FR-003)",
            "description": f"Loaded from {ds.stil_file or '—'}.",
            "stats": [
                {"label": "Chains in topology", "value": _kpi_display(kpis, "topology_chains")},
                {"label": "STIL / topology file", "value": ds.stil_file or "—"},
            ],
        },
        {
            "number": 4,
            "title": "Chain Breaks (FR-006)",
            "description": "Exact break localization with CERTAIN / UNCERTAIN status.",
            "stats": [
                {"label": "Breaks detected", "value": _kpi_display(kpis, "chain_breaks")},
                {"label": "CERTAIN", "value": str(n_certain)},
                {"label": "UNCERTAIN", "value": str(n_uncertain)},
            ],
        },
        {
            "number": 5,
            "title": "Chain Ranking (FR-004)",
            "description": "Chains ordered by failure frequency.",
            "stats": [
                {"label": "Chains ranked", "value": _kpi_display(kpis, "ranked_chains")},
                {"label": "Top failing chain", "value": _kpi_display(kpis, "top_failing_chain")},
            ],
        },
        {
            "number": 6,
            "title": "Suspected Failing Cells (FR-002)",
            "description": "Localized scan cells with confidence scores.",
            "stats": [
                {"label": "Suspected cells", "value": _kpi_display(kpis, "failing_cells")},
                {"label": "Diagnosis confidence", "value": _kpi_display(kpis, "avg_confidence")},
            ],
        },
        {
            "number": 7,
            "title": "Failure Correlations (FR-005)",
            "description": "Chain signature profiles — metrics compared vs overall average.",
            "stats": [
                {"label": "Metrics analyzed", "value": _kpi_display(kpis, "failure_correlations")},
                {"label": "Chains profiled", "value": str(len(dash.correlations or []))},
            ],
        },
        {
            "number": 8,
            "title": "Shift vs Capture (FR-007)",
            "description": "Failures classified by shift-path vs capture timing / cell defect.",
            "stats": [
                {"label": "Shift issues", "value": str(sc.get("shift_issues", 0))},
                {"label": "Capture (total)", "value": str(sc.get("capture_total", 0))},
                {"label": "All classified", "value": str(sc.get("total", 0))},
            ],
        },
        {
            "number": 9,
            "title": "Debug Locations (FR-009)",
            "description": "Recommended silicon coordinates for physical debug.",
            "stats": [
                {"label": "Debug locations", "value": _kpi_display(kpis, "debug_locations")},
                {"label": "Recommendations", "value": str(debug_n)},
            ],
        },
    ]

    return {
        "html_exists": html_exists,
        "filename": REPORT_HTML_FILENAME,
        "path": str(html_path.relative_to(PROJECT_ROOT)).replace("\\", "/") if html_exists else None,
        "generated_at": generated_at,
        "stil_file": ds.stil_file,
        "log_file_count": ds.log_file_count,
        "total_failure_records": ds.total_failure_records,
        "sections": sections,
        "top_ranked_chains": ranked_all,
        "ranked_chains_count": len(ranked_all),
        "chain_signatures": sig_highlights,
        "chain_signatures_count": len(sig_highlights),
        "top_suspected_cells": cells_all,
        "suspected_cells_count": len(cells_all),
        "breaks": breaks_all,
        "breaks_count": len(breaks_all),
        "shift_capture": sc,
        "ml_summary": dash.ml_status.client_summary if dash.ml_status else None,
    }


def _broken_chain_keys(breaks_df: pd.DataFrame) -> set[tuple[Any, Any, Any]]:
    broken: set[tuple[Any, Any, Any]] = set()
    if breaks_df is not None and not breaks_df.empty:
        for _, r in breaks_df.iterrows():
            broken.add((r.get("source_file"), r.get("lot_id"), r.get("chain")))
    return broken


def _failure_slacks(row: pd.Series) -> tuple[float, float]:
    setup_slack = row.get("setup_slack_ps")
    hold_slack = row.get("hold_slack_ps")
    try:
        setup_slack = 0.0 if pd.isna(setup_slack) else float(setup_slack)
    except (TypeError, ValueError):
        setup_slack = 0.0
    try:
        hold_slack = 0.0 if pd.isna(hold_slack) else float(hold_slack)
    except (TypeError, ValueError):
        hold_slack = 0.0
    return setup_slack, hold_slack


def _classify_failure_row(
    row: pd.Series,
    broken: set[tuple[Any, Any, Any]],
    *,
    has_anomaly: bool,
    has_pred_rc: bool,
) -> tuple[str, str]:
    """Return (classification, details) for one failure — mirrors Streamlit FR-007."""
    key = (row.get("source_file"), row.get("lot_id"), row.get("chain"))
    chain = row.get("chain", "")
    if key in broken:
        return "SHIFT_ISSUE", f"Associated with scan chain break on chain {chain}."
    setup_slack, hold_slack = _failure_slacks(row)
    is_anom = int(row.get("is_anomaly", 0) or 0) if has_anomaly else 0
    if setup_slack < 0 and setup_slack <= hold_slack:
        if is_anom:
            return (
                "CAPTURE_TIMING_SETUP_ANOMALY",
                f"Anomalous setup timing violation (slack: {setup_slack} ps).",
            )
        return "CAPTURE_TIMING_SETUP", f"Setup timing violation (slack: {setup_slack} ps)."
    if hold_slack < 0 and hold_slack < setup_slack:
        if is_anom:
            return (
                "CAPTURE_TIMING_HOLD_ANOMALY",
                f"Anomalous hold timing violation (slack: {hold_slack} ps).",
            )
        return "CAPTURE_TIMING_HOLD", f"Hold timing violation (slack: {hold_slack} ps)."
    rc = row.get("predicted_root_cause", "UNKNOWN") if has_pred_rc else "UNKNOWN"
    return "CAPTURE_CELL_DEFECT", f"Functional cell defect (RF predicted root cause: {rc})."


def _classify_shift_capture(failures: pd.DataFrame, breaks_df: pd.DataFrame) -> dict[str, int]:
    """Mirror Phase-7 classification counts used in Streamlit (presentation only)."""
    if failures is None or failures.empty:
        return {
            "shift_issues": 0,
            "capture_timing_setup": 0,
            "capture_timing_setup_anomaly": 0,
            "capture_timing_hold": 0,
            "capture_timing_hold_anomaly": 0,
            "capture_cell_defect": 0,
            "capture_total": 0,
            "total": 0,
        }

    broken = _broken_chain_keys(breaks_df)
    has_anomaly = "is_anomaly" in failures.columns
    has_pred_rc = "predicted_root_cause" in failures.columns

    shift = setup = setup_anom = hold = hold_anom = defect = 0
    for _, r in failures.iterrows():
        cls, _ = _classify_failure_row(
            r, broken, has_anomaly=has_anomaly, has_pred_rc=has_pred_rc,
        )
        if cls == "SHIFT_ISSUE":
            shift += 1
        elif cls == "CAPTURE_TIMING_SETUP":
            setup += 1
        elif cls == "CAPTURE_TIMING_SETUP_ANOMALY":
            setup_anom += 1
        elif cls == "CAPTURE_TIMING_HOLD":
            hold += 1
        elif cls == "CAPTURE_TIMING_HOLD_ANOMALY":
            hold_anom += 1
        else:
            defect += 1
    capture_total = setup + setup_anom + hold + hold_anom + defect
    return {
        "shift_issues": shift,
        "capture_timing_setup": setup,
        "capture_timing_setup_anomaly": setup_anom,
        "capture_timing_hold": hold,
        "capture_timing_hold_anomaly": hold_anom,
        "capture_cell_defect": defect,
        "capture_total": capture_total,
        "total": shift + capture_total,
    }


def _build_diagnostics_registry(
    failures: pd.DataFrame,
    breaks_df: pd.DataFrame,
) -> list[dict[str, Any]]:
    """Per-failure FR-007 registry rows for the diagnostics table (Streamlit parity)."""
    if failures is None or failures.empty:
        return []

    broken = _broken_chain_keys(breaks_df)
    has_anomaly = "is_anomaly" in failures.columns
    has_pred_rc = "predicted_root_cause" in failures.columns
    records: list[dict[str, Any]] = []
    for _, r in failures.iterrows():
        cls, det = _classify_failure_row(
            r, broken, has_anomaly=has_anomaly, has_pred_rc=has_pred_rc,
        )
        source_file = r.get("source_file")
        records.append({
            "lot_id": r.get("lot_id"),
            "source_file": Path(source_file).name if source_file else source_file,
            "pattern_id": r.get("pattern_id"),
            "chain": r.get("chain"),
            "fail_flop_id": r.get("fail_flop_id"),
            "setup_slack_ps": r.get("setup_slack_ps"),
            "hold_slack_ps": r.get("hold_slack_ps"),
            "classification": cls,
            "diagnosis_details": det,
        })
    return records


def _load_full_topology() -> dict[str, Any]:
    """Live FR-003 topology; falls back to export JSON when chain map is empty."""
    ensure_src_on_path()
    from topology_analysis import build_topology_analysis

    try:
        chain_map, _ = load_chain_map()
        if chain_map:
            failures, _ = load_failures(max_per_lot=None)
            return build_topology_analysis(chain_map, failures=failures, log_dir=LOG_DIR)
    except Exception:
        pass
    return read_export_json("SCD-FR-003_scan_topology.json") or {}


def _topology_registry_rows(chains_detail: list[dict]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for c in chains_detail:
        ca = c.get("compression_association") or {}
        cid = str(c.get("scan_chain_id") or "")
        rows.append({
            "scan_chain_id": cid,
            "scan_chain_id_short": (cid[:55] + "…") if len(cid) > 55 else cid,
            "chain_name": c.get("chain_name"),
            "chain_short_name": c.get("chain_short_name"),
            "instance_type": c.get("instance_type"),
            "chain_length": c.get("chain_length"),
            "scan_input_si": c.get("scan_input_si"),
            "scan_output_so": c.get("scan_output_so"),
            "clock_domain": c.get("clock_domain"),
            "scan_enable_se": c.get("scan_enable_se"),
            "decompressor_pin": ca.get("decompressor_pin"),
            "compactor_pin": ca.get("compactor_pin"),
            "cell_count": len(c.get("scan_cell_names") or []),
        })
    return rows


def _topology_balance_chart(chains_detail: list[dict], balance: dict) -> list[dict[str, Any]]:
    mean = float(balance.get("mean_length") or 0)
    rows: list[dict[str, Any]] = []
    for c in chains_detail:
        inst = c.get("instance_type", "")
        short = "core" if inst == "core_inst" else ("phy" if inst == "phy_inst" else inst)
        name = c.get("chain_name") or c.get("chain_short_name") or "?"
        label = f"{name} ({short})" if short else name
        length = int(c.get("chain_length") or 0)
        rows.append({
            "chain": label,
            "chain_name": name,
            "chain_length": length,
            "deviation_from_mean": round(length - mean, 2),
        })
    return rows


def _topology_compression_rows(compression: dict) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for ch in compression.get("channel_mapping") or []:
        for c in ch.get("chains") or []:
            cid = str(c.get("chain_id") or "")
            rows.append({
                "decompressor_pin": ch.get("decompressor_pin"),
                "compactor_pin": ch.get("compactor_pin"),
                "chain_name": c.get("chain_name"),
                "scan_chain_id": (cid[:60] + "…") if len(cid) > 60 else cid,
                "scan_input_si": c.get("scan_in"),
                "scan_output_so": c.get("scan_out"),
                "chain_length": c.get("scan_length"),
            })
    return rows


def _topology_chain_entries(
    chains_detail: list[dict],
    chain_map: dict,
    failures: pd.DataFrame,
) -> list[dict[str, Any]]:
    """Chain rows for interactive schematic (Streamlit FR-003 section 8)."""
    ensure_src_on_path()
    from locate_cells import locate_failing_cells

    suspects = locate_failing_cells(failures, chain_map, min_observations=1)
    entries: list[dict[str, Any]] = []
    for idx, c in enumerate(chains_detail):
        cid = c.get("scan_chain_id")
        sel = chain_map.get(cid) if cid else None
        if not sel:
            continue
        chain_id = sel.get("chain_id")
        chain_short = sel.get("chain") or c.get("chain_short_name") or ""
        suspect_positions: dict[int, dict] = {}
        if not suspects.empty:
            if chain_id in suspects["chain_id"].values:
                chain_suspects = suspects[suspects["chain_id"] == chain_id]
            else:
                chain_suspects = suspects[suspects["chain"] == chain_short]
            for _, r in chain_suspects.iterrows():
                bp = r.get("bit_position")
                if pd.notna(bp):
                    suspect_positions[int(bp)] = {
                        "cell_name": r.get("cell_name"),
                        "confidence": float(r.get("confidence") or 0),
                        "observations": int(r.get("observations") or 0),
                        "fail_flop_id": r.get("fail_flop_id"),
                    }
        entries.append({
            "uid": f"c{idx}",
            "scan_chain_id": cid,
            "chain_name": c.get("chain_name"),
            "instance_type": c.get("instance_type"),
            "scan_length": sel.get("scan_length") or c.get("chain_length") or 234,
            "scan_in": sel.get("scan_in") or c.get("scan_input_si"),
            "scan_out": sel.get("scan_out") or c.get("scan_output_so"),
            "decompressor_pin": sel.get("decompressor_pin")
            or (c.get("compression_association") or {}).get("decompressor_pin"),
            "compactor_pin": sel.get("compactor_pin")
            or (c.get("compression_association") or {}).get("compactor_pin"),
            "hierarchical_path": sel.get("hierarchical_path"),
            "suspect_positions": suspect_positions,
        })
    return entries


def _build_from_live(lot: Optional[str], wafer: Optional[str]) -> DiagnosisDashboard:
    ensure_src_on_path()
    from chain_breaks import detect_chain_breaks
    from chain_ranking import rank_chains_by_frequency
    from locate_cells import locate_failing_cells
    from topology_analysis import build_topology_analysis

    failures, src_label = load_failures(max_per_lot=None)
    chain_map, topo_label = load_chain_map()
    failures = _filter_df(failures, lot, wafer)

    if failures.empty:
        logs = active_log_filenames(max_per_lot=None)
        return DiagnosisDashboard(
            data_source="fastapi-live",
            mode="live",
            filters=FilterOptions(**list_filter_options_cached()),
            dataset_summary=DatasetSummary(
                stil_file=active_stil_filename(),
                log_files=logs,
                log_file_count=len(logs),
            ),
            ml_status=MlStatusSummary(**summarize_failure_ml_status(failures)),
            kpis=[],
            footer=f"Data source: FastAPI (live empty — {src_label})",
        )

    ranked = rank_chains_by_frequency(failures, method="dense")
    breaks_df = detect_chain_breaks(failures, chain_map)
    # Match Streamlit Phase 3 default: require ≥2 corroborating observations
    # so one-off noise does not inflate the suspected-cell KPI.
    suspects = locate_failing_cells(failures, chain_map, min_observations=2)
    topology = build_topology_analysis(chain_map, failures=failures)
    sc = _classify_shift_capture(failures, breaks_df)

    corr_rows, _overall_corr, _corr_meta = _build_correlation_rows(failures)
    corr_feature_count = _correlation_feature_count(_corr_meta)

    top_chain = ranked.iloc[0]["chain"] if not ranked.empty else "N/A"
    top_fails = int(ranked.iloc[0]["fail_count"]) if not ranked.empty else 0
    total_lots = int(failures["lot_id"].nunique()) if not failures.empty and "lot_id" in failures.columns else 0
    top_lots = (
        int(failures[failures["chain"] == top_chain]["lot_id"].nunique())
        if top_chain != "N/A"
        else 0
    )

    n_certain = int((breaks_df["location_status"] == "CERTAIN").sum()) if not breaks_df.empty and "location_status" in breaks_df.columns else 0
    n_uncertain = int(len(breaks_df) - n_certain) if not breaks_df.empty else 0

    # Diagnosis Confidence KPI: fail-weighted mean of per-chain top-1 (not mean of all dilute suspects)
    ensure_src_on_path()
    try:
        from confidence_score import CONFIDENCE_DEFINITION, aggregate_diagnosis_confidence
        conf_meta = aggregate_diagnosis_confidence(suspects, top_k=1)
        mean_conf = conf_meta.get("mean_suspect_confidence")
        confidence_definition = conf_meta.get("confidence_definition", CONFIDENCE_DEFINITION)
    except Exception:
        mean_conf = float(suspects["confidence"].mean()) if not suspects.empty and "confidence" in suspects.columns else None
        confidence_definition = None
        conf_meta = {}

    # FR-010 style analysis quality (same weights as Streamlit Phase 10 presentation)
    e_topo = 1.0 if chain_map else 0.0
    n_failing_chains = int(failures["chain"].nunique())
    n_localized = int(suspects["chain"].nunique()) if not suspects.empty and "chain" in suspects.columns else 0
    e_local = min(1.0, n_localized / n_failing_chains) if n_failing_chains else 1.0
    non_null_slacks = int(failures["setup_slack_ps"].notna().sum()) if "setup_slack_ps" in failures.columns else 0
    e_metrics = float(non_null_slacks / len(failures)) if len(failures) else 1.0
    analysis_quality = round(0.2 * 1.0 + 0.2 * e_topo + 0.3 * e_local + 0.15 * e_metrics + 0.15 * 1.0, 4)

    report_exists = (OUTPUT_DIR / "SCD-FR-008_scan_diagnosis_report.html").exists()
    debug_export = read_export_json("SCD-FR-009_debug_locations.json")
    debug_count = _debug_location_count(debug_export)
    conf_summary = _compute_diagnosis_confidence_summary(
        suspects,
        _df_to_records(breaks_df),
        _debug_recommendations(debug_export),
        failures=failures,
        ml_status=summarize_failure_ml_status(failures),
        analysis_quality=analysis_quality,
        has_topology=bool(chain_map),
    )
    overall_conf_pct = conf_summary.get("overall_confidence_pct")

    prod_validation, review_summary = _run_production_hardening(failures, suspects, breaks_df)

    spark_chains = _spark_from_lots(failures, lambda s: s["chain"].nunique())
    spark_cells = _spark_from_lots(failures, lambda s: s["fail_flop_id"].nunique())
    spark_fails = _spark_from_lots(failures, lambda s: len(s))

    topo_count = int(topology.get("summary", {}).get("total_scan_chains") or topology.get("number_of_scan_chains") or len(chain_map) or 0)

    kpis = [
        KpiCard(
            id="failing_chains",
            section="overview",
            label="Distinct failing scan chains",
            value=n_failing_chains,
            trend_pct=_trend_pct(spark_chains),
            badge="Detected from Failure Logs",
            badge_tone="danger",
            sparkline=spark_chains,
            help="SCD-FR-001 distinct failing chains in active dataset",
        ),
        KpiCard(
            id="failing_cells",
            section="overview",
            label="Failing Scan Cells",
            value=int(len(suspects)) if not suspects.empty else 0,
            trend_pct=_trend_pct(spark_cells),
            badge="Confidence Score Available" if mean_conf is not None else "Flop IDs from logs",
            badge_tone="warning",
            sparkline=spark_cells,
            help="SCD-FR-002 suspected cells with ≥2 corroborating observations (Streamlit Phase 3 default)",
            caption=f"{int(len(suspects))} chain×cell suspects (min_observations=2)",
        ),
        KpiCard(
            id="chain_breaks",
            section="overview",
            label="Chain Breaks Detected",
            value=int(len(breaks_df)),
            badge=f"{n_certain} CERTAIN / {n_uncertain} UNCERTAIN",
            badge_tone="danger",
            sparkline=spark_fails,
            help="SCD-FR-006 detect_chain_breaks — CERTAIN/UNCERTAIN unchanged",
        ),
        KpiCard(
            id="shift_capture",
            section="overview",
            label="Shift / Capture Issues",
            value=int(sc["total"]),
            badge=f"Shift {sc['shift_issues']} · Capture {sc['capture_total']}",
            badge_tone="warning",
            help="SCD-FR-007 classification counts (same rules as Streamlit Phase 7)",
        ),
        KpiCard(
            id="topology_chains",
            section="engineering",
            label="Chains in Topology",
            value=topo_count,
            badge="Loaded & Visualized" if topo_count else "No topology",
            badge_tone="success" if topo_count else "neutral",
            help=f"SCD-FR-003 · {topo_label}",
        ),
        KpiCard(
            id="ranked_chains",
            section="engineering",
            label="Chains Ranked",
            value=int(len(ranked)),
            badge="Failure Frequency Ranking",
            badge_tone="info",
            help="SCD-FR-004 rank_chains_by_frequency(dense)",
        ),
        KpiCard(
            id="failure_correlations",
            section="engineering",
            label="Failure Correlations",
            value=corr_feature_count,
            badge=f"{len(corr_rows)} chains · metrics vs average",
            badge_tone="info",
            help=(
                "SCD-FR-005 · number of failure metrics compared per chain "
                "(timing, scan load, spatial, topology, plus die/region when present)"
            ),
        ),
        KpiCard(
            id="top_failing_chain",
            section="engineering",
            label="Top Failing Chain",
            value=str(top_chain),
            badge=(
                f"{top_fails} failures · {top_lots} of {total_lots} lots"
                if total_lots
                else f"{top_fails} failures · {top_lots} lots"
            ),
            badge_tone="danger",
            help=(
                "Highest fail_count from FR-004 dense ranking. "
                "Lot count = lots where this chain failed (not total lots ingested)."
            ),
        ),
        KpiCard(
            id="diagnosis_reports",
            section="ai",
            label="Diagnosis Reports",
            value=1 if report_exists else 0,
            badge="FR-008 HTML available" if report_exists else "Generate in Streamlit / export",
            badge_tone="success" if report_exists else "neutral",
            help="SCD-FR-008 report artifact presence under output/",
        ),
        KpiCard(
            id="debug_locations",
            section="ai",
            label="Debug Locations",
            value=debug_count if debug_count else ("N/A" if debug_export is None else 0),
            status="na" if debug_export is None and debug_count == 0 else "ok",
            badge="FR-009 debug coordinates",
            badge_tone="warning",
            caption=None if debug_export else "No FR-009 export found — open Streamlit Phase 9 or re-export",
            help="SCD-FR-009 debug location recommendations",
        ),
        KpiCard(
            id="avg_confidence",
            section="ai",
            label="Diagnosis Confidence",
            value=(
                f"{overall_conf_pct:.1f}%"
                if overall_conf_pct is not None
                else "N/A"
            ),
            status="ok" if overall_conf_pct is not None else "na",
            badge=conf_summary.get("trust_label") or "ML + logic",
            badge_tone="success" if (conf_summary.get("overall_confidence") or 0) >= 0.5 else "warning",
            help="SCD-FR-010 — how well ML models and diagnosis logic performed overall",
        ),
        KpiCard(
            id="pending_reviews",
            section="ai",
            label="Pending Reviews",
            value=int(review_summary.get("pending") or 0),
            status="ok",
            badge=(
                f"{int(review_summary.get('confirmed') or 0)} confirmed · "
                f"{int(review_summary.get('feedback_records') or 0)} verified feedback"
            ),
            badge_tone="warning" if int(review_summary.get("pending") or 0) else "success",
            caption="Engineer confirm/reject queue — feeds cell-confidence retrain",
            help="Production review queue: confirm or reject top cell/break leads",
        ),
    ]

    # Full tables for UI pagination — do not silently truncate cells/breaks.
    breaks_table = _df_to_records(breaks_df)
    cells_table = _df_to_records(suspects)
    ranking = _df_to_records(ranked)

    log_names = active_log_filenames(max_per_lot=None)
    stil_name = active_stil_filename()
    failing_flops = int(len(suspects)) if not suspects.empty else (
        int(failures["fail_flop_id"].nunique())
        if "fail_flop_id" in failures.columns
        else 0
    )
    dataset_summary = DatasetSummary(
        stil_file=stil_name,
        log_files=log_names,
        log_file_count=len(log_names),
        total_failure_records=int(len(failures)),
        failing_chains=n_failing_chains,
        all_chains=int(topo_count),
        failing_flops=failing_flops,
    )

    return DiagnosisDashboard(
        data_source="fastapi-live",
        mode="live",
        filters=FilterOptions(**list_filter_options_cached()),
        dataset_summary=dataset_summary,
        ml_status=MlStatusSummary(**summarize_failure_ml_status(failures)),
        production_validation=prod_validation,
        kpis=kpis,
        ranking=ranking,
        correlations=corr_rows,
        shift_capture=sc,
        confidence={
            "mean_suspect_confidence": mean_conf,
            "analysis_quality_score": analysis_quality,
            "localized_chains": n_localized,
            "failing_chains": n_failing_chains,
            "per_chain_top_mean": conf_meta.get("per_chain_top_mean"),
            "global_mean_all_suspects": conf_meta.get("global_mean_all_suspects"),
            "max_confidence": conf_meta.get("max_confidence"),
            "confidence_definition": confidence_definition,
            "overall_confidence": conf_summary.get("overall_confidence"),
            "overall_confidence_pct": conf_summary.get("overall_confidence_pct"),
            "full_pipeline_confidence": conf_summary.get("full_pipeline_confidence"),
            "full_pipeline_confidence_pct": conf_summary.get("full_pipeline_confidence_pct"),
            "trust_label": conf_summary.get("trust_label"),
            "categories": conf_summary.get("categories") or [],
            "ml_categories": conf_summary.get("ml_categories") or [],
            "logic_categories": conf_summary.get("logic_categories") or [],
            "ml_summary": conf_summary.get("ml_summary"),
        },
        topology_summary={
            "total_scan_chains": topo_count,
            "source": topo_label,
            "summary": {
                "total_scan_chains": topo_count,
                "total_flip_flops": (topology.get("summary") or {}).get("total_flip_flops"),
                "max_chain_length": (topology.get("summary") or {}).get("max_chain_length"),
                "min_chain_length": (topology.get("summary") or {}).get("min_chain_length"),
                "mean_chain_length": (topology.get("summary") or {}).get("mean_chain_length"),
            },
        },
        breaks_table=breaks_table,
        cells_table=cells_table,
        reports_meta={"html_exists": report_exists, "path": "output/SCD-FR-008_scan_diagnosis_report.html"},
        footer=f"Data source: FastAPI (live - {src_label})",
    )


def _build_from_exports() -> DiagnosisDashboard:
    """Aggregate real export JSON produced by the diagnosis engine."""
    fr001 = read_export_json("SCD-FR-001_failing_scan_chains.json") or {}
    fr002 = read_export_json("SCD-FR-002_suspected_failing_cells.json") or {}
    fr003 = read_export_json("SCD-FR-003_scan_topology.json") or {}
    fr004 = read_export_json("SCD-FR-004_chain_failure_ranking.json") or {}
    fr005 = read_export_json("SCD-FR-005_failure_correlation.json") or {}
    fr006 = read_export_json("SCD-FR-006_scan_chain_breaks.json") or {}
    fr007 = read_export_json("SCD-FR-007_shift_capture_diagnosis.json") or {}
    fr009 = read_export_json("SCD-FR-009_debug_locations.json")

    s1 = fr001.get("summary", {})
    s2 = fr002.get("summary", {})
    s3 = fr003.get("summary", {}) or {"total_scan_chains": fr003.get("number_of_scan_chains")}
    s4 = fr004.get("summary", {})
    s6 = fr006.get("summary", {})
    s7 = fr007.get("summary", {})

    shift = int(s7.get("shift_issues", 0) or 0)
    capture = int(
        (s7.get("capture_timing_setup", 0) or 0)
        + (s7.get("capture_timing_setup_anomaly", 0) or 0)
        + (s7.get("capture_timing_hold", 0) or 0)
        + (s7.get("capture_timing_hold_anomaly", 0) or 0)
        + (s7.get("capture_cell_defect", 0) or 0)
    )
    ranking = fr004.get("ranking", []) or []
    corr = fr005.get("correlations", []) or []
    corr_feature_count = _correlation_feature_count(
        {
            "correlation_feature_count": fr005.get("correlation_feature_count"),
            "numerical_features": fr005.get("numerical_features"),
            "region_field_used": fr005.get("region_field_used"),
        }
    )
    breaks = fr006.get("breaks", []) or []
    # Prefer full suspected-cell list; fall back to legacy keys (no silent [:N] truncate).
    cells = (
        fr002.get("suspected_cells")
        or fr002.get("top_suspected_cells")
        or fr002.get("per_chain_top_suspect")
        or []
    )
    report_exists = (OUTPUT_DIR / "SCD-FR-008_scan_diagnosis_report.html").exists()
    debug_count = _debug_location_count(fr009)
    conf_summary = _compute_diagnosis_confidence_summary(
        cells, breaks, _debug_recommendations(fr009),
        ml_status={
            "active": bool(s2.get("root_causes_estimated")),
            "failure_records_analyzed": int(s1.get("total_fail_records") or s1.get("fail_record_count") or 0),
            "root_causes_estimated": int(s2.get("root_causes_estimated") or 0),
            "anomaly_flagged_count": 0,
            "anomaly_flagged_pct": 0.0,
            "client_summary": s2.get("client_summary"),
        },
        analysis_quality=float(s2.get("analysis_quality_score")) if s2.get("analysis_quality_score") is not None else None,
        has_topology=bool(s3.get("total_scan_chains")),
    )
    overall_conf_pct = conf_summary.get("overall_confidence_pct")

    mean_conf = s2.get("mean_confidence")
    # Prefer dashboard KPI if export was rebuilt with the calibrated aggregate
    if s2.get("diagnosis_confidence") is not None:
        mean_conf = s2.get("diagnosis_confidence")
    # Recompute fail-weighted per-chain top-1 from export rows when summary is stale
    # (older exports stored dilute mean_confidence ≈ mean of all suspects).
    export_cells = cells
    conf_definition = s2.get("confidence_definition")
    global_mean_export = s2.get("global_mean_all_suspects")
    max_conf_export = s2.get("max_confidence")
    if export_cells:
        try:
            ensure_src_on_path()
            from confidence_score import CONFIDENCE_DEFINITION, aggregate_diagnosis_confidence
            conf_meta = aggregate_diagnosis_confidence(pd.DataFrame(export_cells), top_k=1)
            if conf_meta.get("mean_suspect_confidence") is not None:
                mean_conf = conf_meta["mean_suspect_confidence"]
            conf_definition = conf_meta.get("confidence_definition", conf_definition or CONFIDENCE_DEFINITION)
            global_mean_export = conf_meta.get("global_mean_all_suspects", global_mean_export)
            max_conf_export = conf_meta.get("max_confidence", max_conf_export)
        except Exception:
            pass
    top_chain = s4.get("top_chain", "N/A")
    top_fails = s4.get("top_chain_fail_count", 0)

    kpis = [
        KpiCard(id="failing_chains", section="overview", label="Distinct failing scan chains",
                value=int(s1.get("distinct_failing_chains", 0)), badge="Detected from Failure Logs", badge_tone="danger",
                help="From SCD-FR-001 export"),
        KpiCard(id="failing_cells", section="overview", label="Failing Scan Cells",
                value=int(s2.get("total_suspected_cells", 0)), badge="Confidence Score Available", badge_tone="warning",
                help="From SCD-FR-002 export"),
        KpiCard(id="chain_breaks", section="overview", label="Chain Breaks Detected",
                value=int(s6.get("total_detected_breaks", len(breaks))), badge="Topology View Available", badge_tone="danger",
                help="From SCD-FR-006 export"),
        KpiCard(id="shift_capture", section="overview", label="Shift / Capture Issues",
                value=shift + capture, badge=f"Shift {shift} · Capture {capture}", badge_tone="warning",
                help="From SCD-FR-007 export"),
        KpiCard(id="topology_chains", section="engineering", label="Chains in Topology",
                value=int(s3.get("total_scan_chains", 0) or 0), badge="Loaded & Visualized", badge_tone="success",
                help="From SCD-FR-003 export"),
        KpiCard(id="ranked_chains", section="engineering", label="Chains Ranked",
                value=int(s1.get("distinct_failing_chains", len(ranking))), badge="Failure Frequency Ranking", badge_tone="info",
                help="From SCD-FR-004 export"),
        KpiCard(id="failure_correlations", section="engineering", label="Failure Correlations",
                value=corr_feature_count,
                badge=f"{len(corr)} chains · metrics vs average",
                badge_tone="info",
                help="SCD-FR-005 · failure metrics compared per chain (from export)"),
        KpiCard(id="top_failing_chain", section="engineering", label="Top Failing Chain",
                value=str(top_chain), badge=f"{top_fails} Failures", badge_tone="danger",
                help="From SCD-FR-004 summary"),
        KpiCard(id="diagnosis_reports", section="ai", label="Diagnosis Reports",
                value=1 if report_exists else 0, badge="FR-008 HTML", badge_tone="success" if report_exists else "neutral"),
        KpiCard(id="debug_locations", section="ai", label="Debug Locations",
                value=debug_count if fr009 else "N/A", status="ok" if fr009 else "na",
                badge="FR-009", badge_tone="warning",
                caption=None if fr009 else "No FR-009 export present"),
        KpiCard(id="avg_confidence", section="ai", label="Diagnosis Confidence",
                value=(
                    f"{overall_conf_pct:.1f}%"
                    if overall_conf_pct is not None
                    else "N/A"
                ),
                status="ok" if overall_conf_pct is not None else "na",
                badge=conf_summary.get("trust_label") or "ML + logic",
                badge_tone="success" if (conf_summary.get("overall_confidence") or 0) >= 0.5 else "warning",
                help="SCD-FR-010 overall diagnostic trust from exports"),
        KpiCard(id="pending_reviews", section="ai", label="Pending Reviews",
                value="N/A", status="na", badge="Export status placeholder", badge_tone="neutral",
                caption="No review queue in engine — placeholder tied to report export"),
    ]

    opts = list_filter_options_cached()
    cells_n = len(cells)
    stil_name = active_stil_filename()
    log_names = active_log_filenames(max_per_lot=None)
    n_fail = int(s1.get("total_fail_records") or s1.get("fail_record_count") or 0)
    return DiagnosisDashboard(
        data_source="fastapi-exports",
        mode="live",
        filters=FilterOptions(**opts),
        dataset_summary=DatasetSummary(
            stil_file=stil_name,
            log_files=log_names,
            log_file_count=len(log_names),
            total_failure_records=n_fail,
            failing_chains=int(s1.get("distinct_failing_chains", len(ranking)) or 0),
            all_chains=int(s3.get("total_scan_chains") or 0),
            failing_flops=int(s2.get("unique_cells") or s2.get("suspected_cell_count") or cells_n),
        ),
        ml_status=MlStatusSummary(
            active=True,
            failure_records_analyzed=n_fail,
            root_causes_estimated=n_fail,
            client_summary=(
                f"Saved report data ({n_fail:,} failures). "
                "Live mode re-runs Random Forest and anomaly detection on every refresh."
            ),
        ),
        kpis=kpis,
        ranking=ranking,
        correlations=corr,
        shift_capture={
            "shift_issues": shift,
            "capture_total": capture,
            **{k: s7.get(k) for k in s7},
        },
        confidence={
            "mean_suspect_confidence": mean_conf,
            "confidence_definition": conf_definition,
            "global_mean_all_suspects": global_mean_export,
            "max_confidence": max_conf_export,
        },
        topology_summary={"total_scan_chains": s3.get("total_scan_chains"), "summary": s3},
        breaks_table=breaks,
        cells_table=cells,
        reports_meta={"html_exists": report_exists},
        footer="Data source: FastAPI (export JSON artifacts)",
    )


# Symbols that must exist for the live React path — regression guard when editing this file.
_REQUIRED_LIVE_SYMBOLS: tuple[str, ...] = (
    "_classify_shift_capture",
    "_breaks_distribution_by_lot",
    "_build_from_live",
    "_build_suspected_cells_panel",
    "get_dashboard",
    "get_kpi_workspace",
)


def validate_live_path() -> dict[str, object]:
    """Smoke-test the live dashboard path (run at API startup and in pytest).

    Counts are derived from discovered logs + ``load_failures`` — never hardcoded.
    """
    errors: list[str] = []

    for sym in _REQUIRED_LIVE_SYMBOLS:
        obj = globals().get(sym)
        if obj is None or not callable(obj):
            errors.append(f"missing or non-callable: {sym}")

    expected_log_count = len(select_logs(max_per_lot=None))
    failures_df, load_label = load_failures(max_per_lot=None)
    expected_failure_records = int(len(failures_df))

    failure_records = 0
    log_file_count = 0
    try:
        dash = _build_from_live(None, None)
        failure_records = int(dash.dataset_summary.total_failure_records or 0)
        log_file_count = int(dash.dataset_summary.log_file_count or 0)

        if dash.data_source != "fastapi-live":
            errors.append(f"unexpected data_source: {dash.data_source}")
        footer = (dash.footer or "").lower()
        if "stale export json was not used" in footer or "live diagnosis error" in footer:
            errors.append(dash.footer or "live dashboard error footer")

        if expected_log_count == 0:
            errors.append("no ATE logs discovered under data/logs")
        elif log_file_count != expected_log_count:
            errors.append(
                f"log_file_count mismatch: dashboard={log_file_count} "
                f"discovered={expected_log_count}"
            )

        if expected_log_count > 0 and expected_failure_records == 0:
            errors.append(f"logs discovered ({expected_log_count}) but zero FAIL rows parsed")
        elif failure_records != expected_failure_records:
            errors.append(
                f"failure_records mismatch: dashboard={failure_records} "
                f"loader={expected_failure_records} ({load_label})"
            )

        ws = get_kpi_workspace("chain_breaks", mode="live")
        kinds = [p.kind for p in ws.panels]
        if "breaks_by_lot" not in kinds:
            errors.append("chain_breaks workspace missing breaks_by_lot panel")
    except Exception as exc:
        errors.append(f"{type(exc).__name__}: {exc}")

    return {
        "ok": not errors,
        "failure_records": failure_records,
        "log_file_count": log_file_count,
        "expected_failure_records": expected_failure_records,
        "expected_log_count": expected_log_count,
        "load_source": load_label,
        "errors": errors,
    }


def get_dashboard(
    mode: str = "live",
    lot: Optional[str] = None,
    wafer: Optional[str] = None,
    *,
    force: bool = False,
) -> DiagnosisDashboard:
    """Live dashboard with fingerprint cache; review KPIs overlaid cheaply."""
    try:
        ensure_src_on_path()
        from review_queue import queue_summary

        cfg = _production_cfg()
        ttl = int(getattr(cfg, "dashboard_cache_ttl_sec", 0) or 0)
        fp = _logs_fingerprint()
        # Data-only key — review confirms must not force a full diagnosis rebuild
        cache_key = f"{fp}|{lot or ''}|{wafer or ''}"

        if force:
            _DASHBOARD_CACHE.pop(cache_key, None)

        dash: DiagnosisDashboard | None = None
        if ttl > 0 and not lot and not wafer and not force:
            hit = _DASHBOARD_CACHE.get(cache_key)
            if hit and (time.time() - hit[0]) < ttl:
                dash = hit[1]

        if dash is None:
            dash = _build_from_live(lot, wafer)
            if ttl > 0 and not lot and not wafer:
                _DASHBOARD_CACHE[cache_key] = (time.time(), dash)

        # Overlay live review counts (JSON read) so Pending Reviews stays current
        try:
            dash = apply_review_summary_to_dashboard_kpis(dash, queue_summary())
        except Exception:
            pass
        return dash
    except Exception as live_exc:
        # Code/import bugs must surface immediately — never mask with stale export JSON (960-cap).
        if isinstance(live_exc, (NameError, AttributeError, ImportError, TypeError, SyntaxError)):
            import logging
            logging.getLogger(__name__).exception("live dashboard programmer error")
            return DiagnosisDashboard(
                data_source="fastapi-live",
                mode="live",
                filters=FilterOptions(**list_filter_options_cached()),
                kpis=[],
                footer=(
                    f"Live diagnosis error ({type(live_exc).__name__}): {live_exc}. "
                    "Stale export JSON was not used — fix the API and refresh."
                ),
                ml_status=MlStatusSummary(
                    client_summary=(
                        "Live API failed due to an internal error. "
                        "Counts may be wrong until this is fixed — do not use old export totals."
                    ),
                ),
            )
        # Operational failures only: optional export fallback (may be older capped runs).
        try:
            dash = _build_from_exports()
            if dash.kpis:
                dash.footer = (
                    f"{dash.footer} — live recompute failed: "
                    f"{type(live_exc).__name__}: {live_exc}"
                )
                if dash.ml_status:
                    dash.ml_status.client_summary = (
                        f"{dash.ml_status.client_summary} "
                        f"(Live run failed; showing saved exports which may be an older subset.)"
                    )
                try:
                    from review_queue import queue_summary

                    dash = apply_review_summary_to_dashboard_kpis(dash, queue_summary())
                except Exception:
                    pass
                return dash
        except Exception:
            pass
        return _build_unavailable_dashboard(live_exc)


def _build_suspected_cells_panel(
    mode: str = "live",
    min_observations: int = 2,
) -> WorkspacePanel | None:
    """FR-002 workspace panel matching Streamlit Phase 3 (slider-driven)."""
    try:
        ensure_src_on_path()
        from locate_cells import locate_failing_cells

        failures, src = load_failures(max_per_lot=None)
        chain_map, _ = load_chain_map()
        suspects = locate_failing_cells(
            failures, chain_map, min_observations=min_observations
        )
        if suspects.empty:
            return WorkspacePanel(
                kind="cells_table",
                title="Failing Scan Cells (SCD-FR-002)",
                description=(
                    f"No failing scan cells at min_observations={min_observations}. "
                    "Lower the threshold."
                ),
                table=[],
                chart={"type": "bar_h_confidence", "data": []},
                meta={
                    "min_observations": min_observations,
                    "suspected_cells": 0,
                    "failing_scan_cells": 0,
                    "chains_involved": 0,
                    "max_confidence": None,
                    "source": src,
                },
            )

        show_cols = [
            c for c in [
                "chain", "instance", "cell_name", "fail_flop_id", "bit_position",
                "offset_from_scan_in", "chain_length", "observations",
                "corroborating_patterns", "chain_observations", "confidence",
                "dominant_fail_type", "dominant_region", "dominant_root_cause",
                "predicted_root_cause", "mean_ai_severity", "lots_affected",
                "scan_in", "scan_out", "scan_master_clock",
            ] if c in suspects.columns
        ]
        table = _df_to_records(suspects[show_cols])
        top = suspects.head(25).copy()
        chart_rows = []
        for _, r in top.iterrows():
            chart_rows.append({
                "label": f"{r.get('chain')} ({r.get('instance')}) · {r.get('fail_flop_id')}",
                "chain": r.get("chain"),
                "instance": r.get("instance"),
                "fail_flop_id": r.get("fail_flop_id"),
                "cell_name": r.get("cell_name"),
                "confidence": float(r.get("confidence") or 0),
                "observations": int(r.get("observations") or 0),
                "bit_position": r.get("bit_position"),
            })

        max_conf = float(suspects["confidence"].max()) if "confidence" in suspects.columns else None
        # Sanity: max must equal the top table confidence (genuine, not a display constant)
        if table and max_conf is not None:
            table_max = max(float(r.get("confidence") or 0) for r in table)
            max_conf = table_max
        chains_n = (
            int(suspects["chain_id"].nunique())
            if "chain_id" in suspects.columns
            else int(suspects["chain"].nunique())
        )
        return WorkspacePanel(
            kind="cells_table",
            title="Failing Scan Cells (SCD-FR-002)",
            description=(
                "Diagnosis-tool localization (not SmarTest): failing flop → bit position "
                "(via STIL chain length) → exact scan cell name. "
                "Max confidence = highest per-cell score in the filtered table "
                "(0.50×evidence + 0.50×calibrated GBM confirmation prob); not a hardcoded value."
            ),
            table=table,
            chart={"type": "bar_h_confidence", "data": chart_rows},
            meta={
                "min_observations": min_observations,
                "suspected_cells": int(len(suspects)),
                "failing_scan_cells": int(len(suspects)),
                "chains_involved": chains_n,
                "max_confidence": max_conf,
                "max_confidence_definition": (
                    "max(confidence) over failing scan cells after min_observations filter; "
                    "confidence = 0.50*evidence + 0.50*calibrated_GBM_confirmation_prob"
                ),
                "source": src,
            },
        )
    except Exception as exc:
        # Log and return an error panel so the UI surfaces the failure (no silent None).
        import logging
        logging.getLogger(__name__).exception("failing scan cells panel failed: %s", exc)
        return WorkspacePanel(
            kind="cells_table",
            title="Failing Scan Cells (SCD-FR-002)",
            description=f"Could not build failing scan cells panel: {exc}",
            table=[],
            chart={"type": "bar_h_confidence", "data": []},
            meta={
                "min_observations": min_observations,
                "suspected_cells": 0,
                "failing_scan_cells": 0,
                "chains_involved": 0,
                "max_confidence": None,
                "error": str(exc),
            },
        )


def _parse_confidence_value(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(num):
        return None
    return round(num, 4)


def _mean_confidence(values: list[float]) -> Optional[float]:
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def _trust_label(confidence: Optional[float]) -> str:
    if confidence is None:
        return "N/A"
    if confidence >= 0.75:
        return "High trust"
    if confidence >= 0.5:
        return "Moderate trust"
    return "Low trust"


def _top1_per_chain(df: pd.DataFrame, sort_col: str) -> pd.DataFrame:
    """Best suspect per chain — production actionable lead."""
    if df.empty or sort_col not in df.columns:
        return df.iloc[0:0]
    chain_key = "chain_id" if "chain_id" in df.columns else "chain"
    if chain_key not in df.columns:
        return df.nlargest(1, sort_col)
    return df.sort_values(sort_col, ascending=False).groupby(chain_key, sort=False).head(1)


def _load_ml_validation_meta() -> dict[str, Any]:
    """Holdout / training metadata shown alongside runtime trust scores."""
    try:
        ensure_src_on_path()
        from confidence_score import load_confidence_model
        from ml_pipeline import load_classifier_metrics

        rc = load_classifier_metrics()
        cell = load_confidence_model() or {}
        cv = rc.get("cv_accuracy")
        pos = cell.get("positive_rate")
        return {
            "root_cause_cv_accuracy_pct": round(float(cv) * 100, 1) if cv is not None else None,
            "root_cause_n_train": rc.get("n_train"),
            "root_cause_n_classes": rc.get("n_classes"),
            "cell_gbm_n_train": cell.get("n_train"),
            "cell_gbm_positive_rate_pct": round(float(pos) * 100, 1) if pos is not None else None,
        }
    except Exception:
        return {}


def _compute_diagnosis_confidence_summary(
    suspects: pd.DataFrame | list[dict[str, Any]],
    breaks: list[dict[str, Any]],
    debug_locs: list[dict[str, Any]],
    *,
    failures: pd.DataFrame | None = None,
    ml_status: dict[str, Any] | None = None,
    analysis_quality: float | None = None,
    has_topology: bool = False,
) -> dict[str, Any]:
    """FR-010: overall trust plus one score per ML model and logic module."""
    suspects_df = suspects if isinstance(suspects, pd.DataFrame) else pd.DataFrame(suspects or [])
    top1_suspects = _top1_per_chain(suspects_df, "confidence")
    top1_ml = _top1_per_chain(suspects_df, "ml_confidence")

    cell_confs: list[float] = []
    if not top1_suspects.empty and "confidence" in top1_suspects.columns:
        cell_confs = [
            float(v) for v in top1_suspects["confidence"].dropna().tolist()
            if _parse_confidence_value(v) is not None
        ]

    break_confs: list[float] = []
    for record in breaks:
        conf = _parse_confidence_value(record.get("location_confidence"))
        if conf is not None:
            break_confs.append(conf)

    debug_confs: list[float] = []
    for record in debug_locs:
        conf = _parse_confidence_value(record.get("confidence"))
        if conf is not None:
            debug_confs.append(conf)

    def col_mean(df: pd.DataFrame, col: str) -> Optional[float]:
        if df.empty or col not in df.columns:
            return None
        series = pd.to_numeric(df[col], errors="coerce").dropna()
        if series.empty:
            return None
        return round(float(series.mean()), 4)

    ml_root_score: Optional[float] = None
    root_count = 0
    if failures is not None and not failures.empty:
        if "prediction_confidence" in failures.columns:
            pc_all = pd.to_numeric(failures["prediction_confidence"], errors="coerce").dropna()
            if not pc_all.empty:
                ml_root_score = round(float(pc_all.mean()), 4)
                root_count = int(len(pc_all))
        if ml_root_score is None and "predicted_root_cause" in failures.columns:
            n_fail = len(failures)
            pred = failures["predicted_root_cause"].fillna("UNKNOWN").astype(str).str.upper().str.strip()
            known = ~pred.isin({"UNKNOWN", "", "N/A"})
            root_count = int(known.sum())
            coverage = root_count / n_fail if n_fail else 0.0
            pred_strength = 0.5
            validation = _load_ml_validation_meta()
            cv_acc = validation.get("root_cause_cv_accuracy_pct")
            if cv_acc is not None:
                pred_strength = float(cv_acc) / 100.0
            elif "prediction_confidence" in failures.columns:
                pc = pd.to_numeric(failures.loc[known, "prediction_confidence"], errors="coerce").dropna()
                if not pc.empty:
                    pred_strength = float(pc.mean())
            ml_root_score = round(0.55 * coverage + 0.45 * pred_strength, 4)
    elif ml_status and int(ml_status.get("failure_records_analyzed") or 0) > 0:
        n_fail = int(ml_status["failure_records_analyzed"])
        root_count = int(ml_status.get("root_causes_estimated") or 0)
        if n_fail > 0:
            ml_root_score = round(root_count / n_fail, 4)

    ml_cell_score = col_mean(top1_ml, "ml_confidence") or col_mean(suspects_df, "ml_confidence")
    ml_evidence_score = col_mean(top1_suspects, "evidence_score") or col_mean(suspects_df, "evidence_score")
    cell_ml_count = len(top1_ml) if not top1_ml.empty else len(suspects_df)

    ml_anomaly_score: Optional[float] = None
    anomaly_count = 0
    if ml_status and ml_status.get("active"):
        flagged_pct = float(ml_status.get("anomaly_flagged_pct") or 0) / 100.0
        anomaly_count = int(ml_status.get("anomaly_flagged_count") or 0)
        # Model ran; lower anomaly share = cleaner bulk diagnosis signal
        ml_anomaly_score = round(max(0.0, 1.0 - flagged_pct * 0.65), 4)

    pipeline_score = round(float(analysis_quality), 4) if analysis_quality is not None else None
    if pipeline_score is None and failures is not None and not failures.empty:
        n_chains = int(failures["chain"].nunique()) if "chain" in failures.columns else 0
        n_localized = int(suspects_df["chain"].nunique()) if not suspects_df.empty and "chain" in suspects_df.columns else 0
        e_topo = 1.0 if has_topology else 0.0
        e_local = min(1.0, n_localized / n_chains) if n_chains else 0.0
        slack = failures["setup_slack_ps"] if "setup_slack_ps" in failures.columns else pd.Series(dtype=float)
        e_metrics = float(slack.notna().sum() / len(failures)) if len(failures) else 0.0
        pipeline_score = round(0.2 + 0.2 * e_topo + 0.3 * e_local + 0.15 * e_metrics + 0.15, 4)

    categories: list[dict[str, Any]] = []

    def add_category(
        cat_id: str,
        label: str,
        requirement: str,
        pillar: str,
        score: Optional[float],
        count: int,
        hint: str,
    ) -> None:
        if score is None:
            return
        categories.append({
            "id": cat_id,
            "label": label,
            "requirement": requirement,
            "pillar": pillar,
            "count": count,
            "confidence": score,
            "confidence_pct": round(score * 100, 1),
            "hint": hint,
        })

    add_category(
        "ml_root_cause",
        "Root cause AI",
        "Random Forest",
        "ml",
        ml_root_score,
        root_count,
        "Mean model certainty (max class probability) across all failures with valid features.",
    )
    add_category(
        "ml_cell_confidence",
        "Cell confidence ML",
        "Gradient Boosting",
        "ml",
        ml_cell_score,
        cell_ml_count,
        "Mean ML P(verified) on the top suspect cell per chain — the lead you would act on.",
    )
    add_category(
        "ml_anomaly",
        "Data quality",
        "Isolation Forest",
        "ml",
        ml_anomaly_score,
        anomaly_count,
        "How clean the bulk failure data is (low outlier rate). High = fewer unusual records to review.",
    )
    add_category(
        "logic_cell_localization",
        "Cell localization",
        "FR-002 rules",
        "logic",
        _mean_confidence(cell_confs),
        len(cell_confs),
        "Rule-based confidence on the top suspect cell per chain (flop mapping + corroborating evidence).",
    )
    if ml_evidence_score is not None:
        add_category(
            "logic_cell_evidence",
            "Evidence scoring",
            "FR-002 rules",
            "logic",
            ml_evidence_score,
            len(top1_suspects) if not top1_suspects.empty else len(suspects_df),
            "Pattern repetition strength on the top suspect per chain, before ML blending.",
        )
    add_category(
        "logic_chain_breaks",
        "Chain break detection",
        "FR-006 rules",
        "logic",
        _mean_confidence(break_confs),
        len(break_confs),
        "Pattern agreement logic locating the scan chain break bit.",
    )
    add_category(
        "logic_debug_locations",
        "Debug coordinates",
        "FR-009 rules",
        "logic",
        _mean_confidence(debug_confs),
        len(debug_confs),
        "Geometry and priority rules for silicon debug recommendations.",
    )
    add_category(
        "logic_pipeline",
        "Diagnosis pipeline",
        "Data + topology",
        "logic",
        pipeline_score,
        int(failures.shape[0]) if failures is not None and not failures.empty else 0,
        "Log quality, topology coverage, and localization reach across failing chains.",
    )

    pillar_scores = [float(c["confidence"]) for c in categories]
    overall = round(sum(pillar_scores) / len(pillar_scores), 4) if pillar_scores else None

    # Headline trust = weighted actionable leads (what production engineers act on).
    actionable_weights = {
        "ml_root_cause": 0.35,
        "ml_cell_confidence": 0.35,
        "logic_cell_localization": 0.20,
        "logic_cell_evidence": 0.10,
    }
    weighted = 0.0
    weight_sum = 0.0
    for cat in categories:
        w = actionable_weights.get(str(cat.get("id")))
        if w is None:
            continue
        weighted += w * float(cat["confidence"])
        weight_sum += w
    actionable_overall = round(weighted / weight_sum, 4) if weight_sum else overall
    headline = actionable_overall if actionable_overall is not None else overall

    return {
        "overall_confidence": headline,
        "overall_confidence_pct": round(headline * 100, 1) if headline is not None else None,
        "full_pipeline_confidence": overall,
        "full_pipeline_confidence_pct": round(overall * 100, 1) if overall is not None else None,
        "trust_label": _trust_label(headline),
        "categories": categories,
        "ml_categories": [c for c in categories if c.get("pillar") == "ml"],
        "logic_categories": [c for c in categories if c.get("pillar") == "logic"],
        "total_results": sum(int(c.get("count") or 0) for c in categories),
        "ml_summary": (ml_status or {}).get("client_summary"),
        "model_validation": _load_ml_validation_meta(),
        "scoring_note": (
            "ML scores use actionable leads (top cell per chain) and model-reported probabilities — "
            "not diluted averages over every alternate suspect."
        ),
    }


def _diagnosis_confidence_from_dashboard(dash: DiagnosisDashboard) -> dict[str, Any]:
    debug_export = read_export_json("SCD-FR-009_debug_locations.json") or {}
    analysis_q = dash.confidence.get("analysis_quality_score") if dash.confidence else None
    ml_dict = dash.ml_status.model_dump() if dash.ml_status else {}
    return _compute_diagnosis_confidence_summary(
        list(dash.cells_table or []),
        list(dash.breaks_table or []),
        _debug_recommendations(debug_export),
        ml_status=ml_dict,
        analysis_quality=float(analysis_q) if analysis_q is not None else None,
        has_topology=bool((dash.topology_summary or {}).get("total_scan_chains")),
    )


def _count_diagnosis_confidence_results(
    suspects: pd.DataFrame,
    breaks_df: pd.DataFrame,
    debug_export: dict[str, Any] | None,
) -> int:
    """Number of diagnosis results that carry a confidence score (FR-010)."""
    n = 0
    if suspects is not None and not suspects.empty and "confidence" in suspects.columns:
        n += int(suspects["confidence"].notna().sum())
    if breaks_df is not None and not breaks_df.empty:
        n += int(len(breaks_df))
    n += _debug_location_count(debug_export)
    return n


def _debug_recommendations(debug_export: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not debug_export:
        return []
    locs = (
        debug_export.get("recommendations")
        or debug_export.get("locations")
        or debug_export.get("debug_locations")
        or debug_export.get("cells")
        or []
    )
    return locs if isinstance(locs, list) else []


_DEBUG_PRIORITY_ORDER = {"High": 0, "Medium": 1, "Low": 2}


def _debug_location_rank_key(rec: dict[str, Any]) -> tuple[float, float, float, str]:
    pri = float(_DEBUG_PRIORITY_ORDER.get(str(rec.get("priority") or ""), 3))
    conf = float(_parse_confidence_value(rec.get("confidence")) or 0)
    dies = float(rec.get("distinct_dies_affected") or 0)
    return (pri, -conf, -dies, str(rec.get("cell_name") or ""))


def _debug_location_coords(rec: dict[str, Any]) -> tuple[Any, Any]:
    loc = rec.get("local_coordinates")
    if isinstance(loc, dict):
        return loc.get("x_um"), loc.get("y_um")
    return rec.get("x_local_um"), rec.get("y_local_um")


def _debug_location_evidence_bullets(rec: dict[str, Any]) -> list[str]:
    conf = _parse_confidence_value(rec.get("confidence"))
    conf_pct = round(conf * 100, 1) if conf is not None else None
    root = rec.get("predicted_root_cause") or "UNKNOWN"
    priority = rec.get("priority") or "—"
    dies = rec.get("distinct_dies_affected")
    occs = rec.get("die_occurrences") or rec.get("occurrences") or []
    occ_count = len(occs) if isinstance(occs, list) else 0
    chain = rec.get("chain") or "—"
    cell = rec.get("cell_name") or rec.get("fail_flop_id") or "—"
    offset = (
        rec.get("logical_offset")
        if rec.get("logical_offset") is not None
        else rec.get("offset_from_scan_in")
    )
    bullets: list[str] = []
    if conf_pct is not None:
        bullets.append(
            f"Diagnosis confidence {conf_pct}% (GBM confirmation calibration + evidence blend)"
        )
    bullets.append(f"Predicted root cause: {root}")
    bullets.append(f"Debug priority: {priority}")
    if dies is not None:
        bullets.append(f"Distinct dies affected: {dies}")
    if occ_count:
        bullets.append(f"{occ_count} wafer occurrence(s) in failure logs")
    if offset is not None:
        bullets.append(f"Logical offset {offset} on chain {chain}")
    bullets.append(f"Target cell {cell} selected from corroborating scan failures")
    return bullets


def _debug_location_selection_rationale(rec: dict[str, Any]) -> str:
    conf = _parse_confidence_value(rec.get("confidence"))
    conf_pct = round(conf * 100, 1) if conf is not None else "—"
    priority = rec.get("priority") or "—"
    root = rec.get("predicted_root_cause") or "UNKNOWN"
    return (
        f"Ranked by debug priority ({priority}) and diagnosis confidence ({conf_pct}%), "
        f"with root cause {root} and multi-die recurrence."
    )


def _enrich_debug_location_row(rec: dict[str, Any], rank: int) -> dict[str, Any]:
    conf = _parse_confidence_value(rec.get("confidence"))
    x_um, y_um = _debug_location_coords(rec)
    occs = rec.get("die_occurrences") or rec.get("occurrences") or []
    occ_count = len(occs) if isinstance(occs, list) else 0
    offset = (
        rec.get("logical_offset")
        if rec.get("logical_offset") is not None
        else rec.get("offset_from_scan_in")
    )
    bullets = _debug_location_evidence_bullets(rec)
    return {
        **rec,
        "rank": rank,
        "confidence_pct": round(conf * 100, 1) if conf is not None else None,
        "pfa_priority": rec.get("priority"),
        "logical_offset": offset,
        "x_um": x_um,
        "y_um": y_um,
        "die_occurrence_count": occ_count,
        "evidence_bullets": bullets,
        "selection_rationale": _debug_location_selection_rationale(rec),
        "evidence_summary": rec.get("supporting_evidence") or (bullets[0] if bullets else ""),
    }


def _dedupe_best_debug_location_per_chain(recs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best: dict[str, dict[str, Any]] = {}
    for rec in recs:
        chain = str(rec.get("chain") or "")
        if not chain:
            continue
        if chain not in best or _debug_location_rank_key(rec) < _debug_location_rank_key(best[chain]):
            best[chain] = rec
    return sorted(best.values(), key=_debug_location_rank_key)


def _debug_location_table_row(row: dict[str, Any]) -> dict[str, Any]:
    """Flatten nested fields for paginated table display."""
    return {
        k: v
        for k, v in row.items()
        if k not in ("die_occurrences", "occurrences", "local_coordinates", "evidence_bullets")
    }


def _build_debug_locations_panels(fr009: dict[str, Any]) -> list[WorkspacePanel]:
    locs = _debug_recommendations(fr009)
    if not locs:
        return [
            WorkspacePanel(
                kind="debug_locations_panel",
                title="Debug locations (FR-009)",
                description="No FR-009 recommendations in export.",
                table=[],
                meta={"total_recommendations": 0},
            ),
        ]

    sorted_locs = sorted(locs, key=_debug_location_rank_key)
    enriched_all = [_enrich_debug_location_row(r, i + 1) for i, r in enumerate(sorted_locs)]
    top_per_chain = _dedupe_best_debug_location_per_chain(locs)
    top_sorted = sorted(top_per_chain, key=_debug_location_rank_key)
    top_enriched = [_enrich_debug_location_row(r, i + 1) for i, r in enumerate(top_sorted)]

    summary = fr009.get("summary") if isinstance(fr009.get("summary"), dict) else {}
    meta = {
        **summary,
        "total_recommendations": len(locs),
        "kpi_total_recommended_cells": _debug_location_count(fr009),
        "unique_chains": len({r.get("chain") for r in locs if r.get("chain")}),
        "top_per_chain_count": len(top_per_chain),
        "scoring_note": (
            "Ranked by debug priority (High > Medium > Low), then diagnosis confidence, "
            "then dies affected. Top cards show the best location per chain; the full table "
            "lists every suspect-cell recommendation from FR-009."
        ),
        "top_recommendations": top_enriched[:20],
    }

    return [
        WorkspacePanel(
            kind="debug_locations_panel",
            title="Debug locations (FR-009)",
            description=(
                "Ranked debug locations with supporting evidence. "
                f"{len(locs):,} total recommendations · {len(top_per_chain):,} chains with a top pick."
            ),
            table=top_enriched[:20],
            meta=meta,
        ),
        WorkspacePanel(
            kind="debug_locations_table",
            title="All debug location recommendations",
            description=f"Full FR-009 export ({len(locs):,} rows) — paginated below.",
            table=[_debug_location_table_row(r) for r in enriched_all],
            meta={"total_rows": len(locs)},
        ),
    ]


def _build_diagnosis_confidence_rows(
    suspects: pd.DataFrame | list[dict[str, Any]],
    breaks: list[dict[str, Any]],
    debug_locs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Unified per-result confidence table for FR-010 drill-down."""
    rows: list[dict[str, Any]] = []

    if isinstance(suspects, pd.DataFrame):
        suspect_records = _df_to_records(suspects) if not suspects.empty else []
    else:
        suspect_records = suspects

    for record in suspect_records:
        conf = _parse_confidence_value(record.get("confidence"))
        if conf is None:
            continue
        rows.append({
            "diagnosis_type": "Failing scan cell",
            "requirement": "FR-002",
            "chain": record.get("chain"),
            "target": record.get("cell_name") or record.get("fail_flop_id"),
            "fail_flop_id": record.get("fail_flop_id"),
            "confidence": conf,
            "confidence_pct": round(conf * 100, 1),
            "status": None,
            "detail": f"{record.get('observations', 0)} corroborating observations",
        })

    for record in breaks:
        conf = _parse_confidence_value(record.get("location_confidence"))
        if conf is None:
            continue
        target = (
            record.get("suspected_break_cell")
            or record.get("break_cell_name")
            or record.get("cell_name")
        )
        if not target and record.get("break_bit_position") is not None:
            target = f"bit {record.get('break_bit_position')}"
        rows.append({
            "diagnosis_type": "Chain break",
            "requirement": "FR-006",
            "chain": record.get("chain"),
            "target": target,
            "fail_flop_id": record.get("fail_flop_id"),
            "confidence": conf,
            "confidence_pct": round(conf * 100, 1),
            "status": record.get("location_status"),
            "detail": record.get("break_rationale") or record.get("diagnosis_details") or "",
        })

    for record in debug_locs:
        conf = _parse_confidence_value(record.get("confidence"))
        if conf is None:
            continue
        rows.append({
            "diagnosis_type": "Debug location",
            "requirement": "FR-009",
            "chain": record.get("chain"),
            "target": record.get("cell_name") or record.get("fail_flop_id"),
            "fail_flop_id": record.get("fail_flop_id"),
            "confidence": conf,
            "confidence_pct": round(conf * 100, 1),
            "status": record.get("priority"),
            "detail": (record.get("supporting_evidence") or "")[:120],
        })

    rows.sort(key=lambda r: float(r.get("confidence") or 0), reverse=True)
    return rows


def _build_diagnosis_confidence_panels(
    dash: DiagnosisDashboard,
    min_observations: int = 2,
) -> list[WorkspacePanel]:
    """FR-010 workspace — confidence score on every diagnosis result."""
    min_obs = max(1, min(20, int(min_observations or 2)))
    suspects = pd.DataFrame()
    breaks: list[dict[str, Any]] = []
    failures = pd.DataFrame()
    chain_map: dict[str, Any] = {}
    try:
        ensure_src_on_path()
        from chain_breaks import detect_chain_breaks
        from locate_cells import locate_failing_cells

        failures, src = load_failures(max_per_lot=None)
        chain_map, _ = load_chain_map()
        suspects = locate_failing_cells(
            failures, chain_map, min_observations=min_obs,
        )
        breaks_df = detect_chain_breaks(failures, chain_map)
        breaks = _df_to_records(breaks_df)
        load_src = src
    except Exception as exc:
        import logging
        logging.getLogger(__name__).exception("diagnosis confidence panel failed: %s", exc)
        suspects = pd.DataFrame(dash.cells_table or [])
        breaks = list(dash.breaks_table or [])
        load_src = f"dashboard-fallback ({exc})"
        summary_fb = _diagnosis_confidence_from_dashboard(dash)
        return [
            WorkspacePanel(
                kind="diagnosis_confidence",
                title="Diagnosis confidence (FR-010)",
                description=(
                    "How well our ML models and rule-based diagnosis logic performed — "
                    "one trust score per model and per logic module."
                ),
                table=summary_fb.get("categories") or [],
                meta={**summary_fb, "min_observations": min_obs, "source": load_src},
            ),
        ]

    debug_export = read_export_json("SCD-FR-009_debug_locations.json") or {}
    debug_locs = _debug_recommendations(debug_export)
    ml_status = summarize_failure_ml_status(failures) if not failures.empty else {}
    n_chains = int(failures["chain"].nunique()) if not failures.empty and "chain" in failures.columns else 0
    n_localized = int(suspects["chain"].nunique()) if not suspects.empty and "chain" in suspects.columns else 0
    e_topo = 1.0 if chain_map else 0.0
    e_local = min(1.0, n_localized / n_chains) if n_chains else 0.0
    slack_col = failures["setup_slack_ps"] if not failures.empty and "setup_slack_ps" in failures.columns else pd.Series(dtype=float)
    e_metrics = float(slack_col.notna().sum() / len(failures)) if len(failures) else 0.0
    pipeline_q = round(0.2 + 0.2 * e_topo + 0.3 * e_local + 0.15 * e_metrics + 0.15, 4)
    summary = _compute_diagnosis_confidence_summary(
        suspects,
        breaks,
        debug_locs,
        failures=failures,
        ml_status=ml_status,
        analysis_quality=pipeline_q,
        has_topology=bool(chain_map),
    )

    return [
        WorkspacePanel(
            kind="diagnosis_confidence",
            title="Diagnosis confidence (FR-010)",
            description=(
                "How well our ML models and rule-based diagnosis logic performed — "
                "one trust score per model and per logic module."
            ),
            table=summary.get("categories") or [],
            meta={
                **summary,
                "min_observations": min_obs,
                "source": load_src,
            },
        ),
    ]


def get_kpi_workspace(
    kpi_id: str,
    mode: str = "live",
    min_observations: int = 2,
) -> KpiWorkspace:
    # Fast path: review queue must feel instant after confirm/reject — do not rebuild
    # the full diagnosis dashboard (that can take many seconds after cache clear).
    if kpi_id == "pending_reviews":
        synced = sync_review_queue(seed_if_needed=True, limit=100)
        qsum = synced.get("summary") or {}
        items = synced.get("items") or []
        return KpiWorkspace(
            kpi_id=kpi_id,
            title="Pending Reviews",
            status="ok",
            summary={
                "value": int(qsum.get("pending") or 0),
                "badge": (
                    f"{int(qsum.get('confirmed') or 0)} confirmed · "
                    f"{int(qsum.get('feedback_records') or 0)} verified feedback"
                ),
                "seeded": synced.get("seeded"),
                "fingerprint": synced.get("fingerprint"),
            },
            panels=[
                WorkspacePanel(
                    kind="review_queue",
                    title="Engineer review queue",
                    description=(
                        "Confirm or reject top cell and break leads. "
                        "Confirmed cells become verified feedback and trigger model retrain at threshold."
                    ),
                    table=items,
                    meta={
                        **qsum,
                        "lifecycle": synced.get("lifecycle") or {},
                        "actions": ["confirm", "reject", "defer"],
                        "seeded": synced.get("seeded"),
                        "fingerprint": synced.get("fingerprint"),
                    },
                )
            ],
        )

    dash = get_dashboard(mode=mode)
    card = next((k for k in dash.kpis if k.id == kpi_id), None)
    if kpi_id == "failing_chains":
        title = "Distinct failing scan chains"
    elif kpi_id == "failing_cells":
        title = "Failing Scan Cells (SCD-FR-002)"
    elif kpi_id == "avg_confidence":
        title = "Diagnosis Confidence (SCD-FR-010)"
    else:
        title = card.label if card else kpi_id.replace("_", " ").title()

    panels: list[WorkspacePanel] = []
    min_obs = max(1, min(20, int(min_observations or 2)))

    # FR-001 raw FAIL extraction — all parsed log rows (Streamlit Phase 1 expander)
    if kpi_id == "failing_chains":
        try:
            # Broad lot coverage so drill-down shows full parsed FAIL population
            failures, src = load_failures(max_per_lot=None)
            fail_records = _fail_records_from_df(failures)
            n_fail = len(fail_records)
            panels.append(WorkspacePanel(
                kind="fail_records",
                title="Show parsed failure records (raw extraction)",
                description=f"{n_fail:,} FAIL records parsed (SCD-FR-001).",
                table=fail_records,
                meta={"record_count": n_fail, "source": src},
            ))
        except Exception as exc:
            panels.append(WorkspacePanel(
                kind="fail_records",
                title="Show parsed failure records (raw extraction)",
                description=f"Could not load FAIL records: {exc}",
                table=[],
            ))

    if kpi_id in ("failing_chains", "ranked_chains", "top_failing_chain"):
        panels.append(WorkspacePanel(
            kind="ranking_table",
            title="Chain failure ranking (FR-004)",
            description="Dense rank by failure frequency",
            table=dash.ranking,
            chart={"type": "bar_h", "data": dash.ranking},
        ))
    if kpi_id == "failing_cells":
        cells_panel = _build_suspected_cells_panel(mode=mode, min_observations=min_obs)
        if cells_panel is not None:
            panels.append(cells_panel)
        else:
            # Should not happen after error-panel return; keep defensive fallback.
            # Defensive fallback: always include chart so UI never sees chart=null.
            fallback_rows = list(dash.cells_table or [])
            chart_rows = []
            for r in fallback_rows[:25]:
                chart_rows.append({
                    "label": f"{r.get('chain')} · {r.get('fail_flop_id') or r.get('suspected_cell')}",
                    "chain": r.get("chain"),
                    "fail_flop_id": r.get("fail_flop_id"),
                    "cell_name": r.get("cell_name") or r.get("suspected_cell"),
                    "confidence": float(r.get("confidence") or 0),
                    "observations": int(r.get("observations") or 0),
                })
            panels.append(WorkspacePanel(
                kind="cells_table",
                title="Failing Scan Cells (SCD-FR-002)",
                description="Builder returned no panel; showing dashboard export fallback.",
                table=fallback_rows,
                chart={"type": "bar_h_confidence", "data": chart_rows},
                meta={
                    **(dash.confidence or {}),
                    "min_observations": min_obs,
                    "failing_scan_cells": len(fallback_rows),
                    "suspected_cells": len(fallback_rows),
                },
            ))
    if kpi_id == "avg_confidence":
        panels.extend(_build_diagnosis_confidence_panels(dash, min_observations=min_obs))
    if kpi_id == "chain_breaks":
        breaks_rows = list(dash.breaks_table or [])
        try:
            chain_map, _ = load_chain_map()
            breaks_rows = _enrich_break_rows_for_visualizer(breaks_rows, chain_map)
        except Exception:
            pass
        lot_rows = _breaks_distribution_by_lot(breaks_rows)
        panels.append(WorkspacePanel(
            kind="breaks_by_lot",
            title="Breaks Distribution by Lot",
            description="Number of detected scan chain break signatures per lot (SCD-FR-006).",
            table=lot_rows,
            meta={"total_break_signatures": len(breaks_rows), "lots_affected": len(lot_rows)},
        ))
        panels.append(WorkspacePanel(
            kind="break_visualizer",
            title="Interactive Scan Chain Break Visualizer",
            description=(
                "Select affected die and broken scan chain to view the zoomed schematic. "
                "Orange = upstream of break, red = break/candidate bit, teal = downstream."
            ),
            table=breaks_rows,
        ))
        panels.append(WorkspacePanel(
            kind="breaks_table",
            title="Scan chain breaks (FR-006)",
            description="CERTAIN / UNCERTAIN location status from detect_chain_breaks",
            table=breaks_rows,
        ))
    if kpi_id == "shift_capture":
        panels.append(WorkspacePanel(
            kind="shift_capture",
            title="Shift vs Capture (FR-007)",
            meta=dash.shift_capture,
            chart={"type": "pie", "data": dash.shift_capture},
        ))
        try:
            failures, _ = load_failures(max_per_lot=None)
            ensure_src_on_path()
            from chain_breaks import detect_chain_breaks

            chain_map, _ = load_chain_map()
            breaks_df = detect_chain_breaks(failures, chain_map)
            registry = _build_diagnostics_registry(failures, breaks_df)
            panels.append(WorkspacePanel(
                kind="diagnostics_registry",
                title="Diagnostics Registry Table",
                description=(
                    "Per-failure shift/capture classification (SCD-FR-007). "
                    "Search and download the full registry as CSV."
                ),
                table=registry,
                meta={"record_count": len(registry)},
            ))
        except Exception as exc:
            panels.append(WorkspacePanel(
                kind="diagnostics_registry",
                title="Diagnostics Registry Table",
                description=f"Could not build diagnostics registry: {exc}",
                table=[],
            ))
    if kpi_id in ("topology_chains",):
        try:
            topo = _load_full_topology()
            chains = list(topo.get("chains") or [])
            summary = topo.get("summary") or {}
            balance = topo.get("chain_balance") or summary.get("chain_balance") or {}
            shared = topo.get("shared_resources") or {}
            compression = topo.get("compression_association") or summary.get("compression") or {}
            full_graph = topo.get("connectivity_graph") or {}

            ensure_src_on_path()
            from schematic_diagram import build_system_connectivity_data

            chain_map, topo_src = load_chain_map()
            failures, _ = load_failures(max_per_lot=None)
            system_graph = build_system_connectivity_data(chains, compression, full_graph)
            chain_entries = _topology_chain_entries(chains, chain_map, failures)

            panels.append(WorkspacePanel(
                kind="topology_overview",
                title="Scan Chain Topology Analysis (SCD-FR-003)",
                description=(
                    "Complete topology from STIL scan structures and ATE logs — "
                    "chain identity, cell order, connectivity, clocks, compression, "
                    "physical placement, balance, shared resources, and connectivity graph."
                ),
                meta={
                    "number_of_scan_chains": topo.get("number_of_scan_chains", len(chains)),
                    "summary": summary,
                    "chain_balance": balance,
                    "compression": compression,
                    "source": topo_src,
                    "status": topo.get("status"),
                },
            ))
            panels.append(WorkspacePanel(
                kind="topology_chain_balance",
                title="Chain Balance",
                description="Scan chain length distribution and balance metrics.",
                table=_topology_balance_chart(chains, balance),
                chart={"type": "bar_v", "data": _topology_balance_chart(chains, balance)},
                meta=balance,
            ))
            panels.append(WorkspacePanel(
                kind="topology_shared_resources",
                title="Shared Resources",
                description="Clocks, scan-enable signals, and decompressor channels shared across chains.",
                meta={
                    **shared,
                    "active_clocks": summary.get("active_clocks", []),
                    "scan_enable_signals": summary.get("scan_enable_signals", []),
                },
            ))
            panels.append(WorkspacePanel(
                kind="topology_compression",
                title="Compression Association (EDT)",
                description="EDT decompressor/compactor channel mapping to scan chains.",
                table=_topology_compression_rows(compression),
                meta={
                    "decompressor_channels": compression.get("decompressor_channels"),
                    "compactor_channels": compression.get("compactor_channels"),
                    "compression_ratio": compression.get("compression_ratio"),
                },
            ))
            panels.append(WorkspacePanel(
                kind="topology_registry",
                title="Complete Scan Chain Registry",
                description="All scan chains with SI/SO, clock domain, scan enable, and compression pins.",
                table=_topology_registry_rows(chains),
            ))
            panels.append(WorkspacePanel(
                kind="topology_connectivity",
                title="Connectivity Graph",
                description=(
                    "System-level DFT connectivity (JTAG → TAP → EDT → decompressor → "
                    "chains → compactor). Full cell-level graph available in export JSON."
                ),
                meta={
                    "system_graph": system_graph,
                    "full_graph_stats": {
                        "node_count": full_graph.get("node_count"),
                        "edge_count": full_graph.get("edge_count"),
                    },
                },
            ))
            panels.append(WorkspacePanel(
                kind="topology_schematic",
                title="Interactive Scan Chain Schematic",
                description=(
                    "Select a chain to view cell order, connectivity, physical placement, "
                    "and log evidence. Click chain rows in the system diagram."
                ),
                table=chain_entries,
                meta={"chains": chains},
            ))
        except Exception as exc:
            panels.append(WorkspacePanel(
                kind="topology_overview",
                title="Scan Chain Topology Analysis (SCD-FR-003)",
                description=f"Could not load topology: {exc}",
                meta=dash.topology_summary,
            ))
    if kpi_id == "failure_correlations":
        correlations = list(dash.correlations or [])
        overall_averages: dict[str, Any] = {}
        corr_meta: dict[str, Any] = {}
        try:
            failures, _ = load_failures(max_per_lot=None)
            if not failures.empty:
                correlations, overall_averages, corr_meta = _build_correlation_rows(failures)
        except Exception:
            pass
        if not correlations:
            correlations = list(dash.correlations or [])
        shared_meta = {
            "overall_averages": overall_averages,
            "chains": [str(c.get("chain")) for c in correlations if c.get("chain")],
            **corr_meta,
        }
        panels.append(WorkspacePanel(
            kind="chain_signature_overview",
            title="Chain Signature Overview",
            description=(
                "All chains ranked by how much their failure profile deviates from the overall average."
            ),
            table=corr_meta.get("chain_signature_overview") or [],
            meta=shared_meta,
        ))
        panels.append(WorkspacePanel(
            kind="chain_signature_profile",
            title="Chain Signature Profile",
            description=(
                "Select a chain to see plain-language signature, metric comparison vs average, "
                "ranked distinguishing factors, and failure distributions."
            ),
            table=correlations,
            meta=shared_meta,
        ))
        panels.append(WorkspacePanel(
            kind="correlation_chain_averages",
            title="Scan Chain Average Physical Metrics & Severity Levels",
            description="Per-chain mean IR drop, temperature, slack, and AI severity.",
            table=corr_meta.get("chain_averages_table") or [],
            meta=shared_meta,
        ))
    if kpi_id == "diagnosis_reports":
        preview = _build_report_preview(dash)
        panels.append(WorkspacePanel(
            kind="reports",
            title="Scan Diagnosis Report (FR-008)",
            description="Full analysis summary — preview below, download HTML for the complete report.",
            meta=preview,
            table=preview.get("top_ranked_chains") or [],
        ))
    if kpi_id == "debug_locations":
        fr009 = read_export_json("SCD-FR-009_debug_locations.json") or {}
        panels.extend(_build_debug_locations_panels(fr009))

    if not panels:
        panels.append(WorkspacePanel(
            kind="empty",
            title=title,
            description="No specialized workspace panels for this KPI yet.",
            meta={"kpi_id": kpi_id},
        ))

    summary_value = card.value if card else None
    summary_badge = card.badge if card else None
    if kpi_id == "failing_cells":
        cells_meta = next((p.meta for p in panels if p.kind == "cells_table"), {}) or {}
        if cells_meta.get("suspected_cells") is not None:
            summary_value = cells_meta["suspected_cells"]
        summary_badge = f"min_observations={min_obs}"
    if kpi_id == "avg_confidence":
        conf_meta = next((p.meta for p in panels if p.kind == "diagnosis_confidence"), {}) or {}
        pct = conf_meta.get("overall_confidence_pct")
        if pct is not None:
            summary_value = f"{pct}%"
        summary_badge = str(conf_meta.get("trust_label") or "FR-010")
    if kpi_id == "debug_locations":
        dl_meta = next((p.meta for p in panels if p.kind == "debug_locations_panel"), {}) or {}
        total = dl_meta.get("total_recommendations") or dl_meta.get("kpi_total_recommended_cells")
        if total is not None:
            summary_value = int(total)
        chains = dl_meta.get("top_per_chain_count")
        if chains is not None:
            summary_badge = f"FR-009 · {chains} chains"
        else:
            summary_badge = "FR-009"

    return KpiWorkspace(
        kpi_id=kpi_id,
        title=title,
        status=card.status if card else "ok",
        summary={"value": summary_value, "badge": summary_badge, "min_observations": min_obs},
        panels=panels,
        data_source=dash.data_source,
        message=(
            "Diagnosis-tool localization (not SmarTest): failing flop → bit position "
            "(via STIL chain length) → exact scan cell name."
            if kpi_id == "failing_cells"
            else (
                "How well ML models and diagnosis logic performed — open for per-module scores."
                if kpi_id == "avg_confidence"
                else (card.caption if card else None)
            )
        ),
    )


def copilot_answer(question: str, kpi_id: Optional[str] = None, mode: str = "live") -> CopilotResponse:
    dash = get_dashboard(mode=mode)
    q = (question or "").strip().lower()
    citations = [f"dashboard:{dash.data_source}"]
    if "break" in q:
        n = next((k.value for k in dash.kpis if k.id == "chain_breaks"), "N/A")
        return CopilotResponse(
            answer=f"The engine reports {n} chain-break signature(s) via SCD-FR-006 (CERTAIN/UNCERTAIN gates unchanged).",
            citations=citations + ["SCD-FR-006"],
            data_source=dash.data_source,
        )
    if "rank" in q or "top" in q:
        top = next((k.value for k in dash.kpis if k.id == "top_failing_chain"), "N/A")
        return CopilotResponse(
            answer=f"Top failing chain by dense frequency rank (SCD-FR-004) is {top}.",
            citations=citations + ["SCD-FR-004"],
            data_source=dash.data_source,
        )
    if "confidence" in q:
        conf = next((k.value for k in dash.kpis if k.id == "avg_confidence"), "N/A")
        return CopilotResponse(
            answer=f"Average / analysis confidence currently shown as {conf} (FR-002 / FR-010 presentation).",
            citations=citations + ["SCD-FR-002", "SCD-FR-010"],
            data_source=dash.data_source,
        )
    kpi_note = f" Focus KPI: {kpi_id}." if kpi_id else ""
    chains = next((k.value for k in dash.kpis if k.id == "failing_chains"), "N/A")
    return CopilotResponse(
        answer=(
            f"Scan Diagnosis summary — failing chains: {chains}. "
            f"Ask about breaks, ranking, or confidence for a focused answer.{kpi_note}"
        ),
        citations=citations + ["SCD-FR-001"],
        data_source=dash.data_source,
    )
