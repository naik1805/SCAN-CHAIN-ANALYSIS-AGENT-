"""SCD-FR-005 failure correlation analysis — shared by exports and FastAPI."""

from __future__ import annotations

from typing import Any, Optional

import numpy as np
import pandas as pd

PHYSICAL_TIMING_COLS = [
    "ir_drop_mv",
    "thermal_c",
    "setup_slack_ps",
    "hold_slack_ps",
    "ai_severity_score",
]

SCAN_LOAD_COLS = [
    "shift_cycles",
    "capture_cycles",
    "scan_fail_count",
    "transition_faults",
    "test_time_ms",
]

SPATIAL_COLS = [
    "die_row",
    "die_col",
    "wafer_x",
    "wafer_y",
]

TOPOLOGY_NUMERIC_COLS = [
    "scan_length",
    "instance_type_code",
    "compression_channel_count",
]

NUMERICAL_CORRELATION_COLS = (
    PHYSICAL_TIMING_COLS + SCAN_LOAD_COLS + SPATIAL_COLS + TOPOLOGY_NUMERIC_COLS
)

REGION_FIELD_PRIORITY = ["failure_region", "die_label", "die_row", "defect_type"]

_INSTANCE_TYPE_CODES = {"core_inst": 1, "phy_inst": 2, "unknown": 0}

_DRIVER_LABELS: dict[str, str] = {
    "ir_drop_mv": "IR Drop",
    "thermal_c": "Thermal",
    "setup_slack_ps": "Setup Slack",
    "hold_slack_ps": "Hold Slack",
    "ai_severity_score": "AI Severity",
    "shift_cycles": "Shift Cycles",
    "capture_cycles": "Capture Cycles",
    "scan_fail_count": "Scan Fail Count",
    "transition_faults": "Transition Faults",
    "test_time_ms": "Test Time",
    "die_row": "Die Row",
    "die_col": "Die Col",
    "wafer_x": "Wafer X",
    "wafer_y": "Wafer Y",
    "scan_length": "Scan Length",
    "instance_type_code": "Instance Type",
    "compression_channel_count": "Compression Channels",
}


def chain_sort_key(chain: str) -> tuple[int, str]:
    val = "".join(ch for ch in str(chain) if ch.isdigit())
    return (int(val) if val else 0, str(chain))


def safe_mean(series: pd.Series) -> Optional[float]:
    s = pd.to_numeric(series, errors="coerce")
    if s.empty or s.isna().all():
        return None
    mean = float(s.mean())
    return None if pd.isna(mean) else round(mean, 2)


def _nonempty_mask(series: pd.Series) -> pd.Series:
    as_str = series.astype(str).str.strip()
    return (
        series.notna()
        & (as_str != "")
        & (~as_str.str.upper().isin(["UNKNOWN", "NONE", "NAN", "NULL"]))
    )


def pick_categorical_field(df: pd.DataFrame, candidates: list[str]) -> Optional[str]:
    for col in candidates:
        if col not in df.columns:
            continue
        if _nonempty_mask(df[col]).any():
            return col
    return None


def _format_category_label(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "Unknown"
    text = str(value).strip()
    return text or "Unknown"


def categorical_percentages(chain_df: pd.DataFrame, col: str, total: int) -> dict[str, float]:
    if chain_df.empty or col not in chain_df.columns or total <= 0:
        return {}
    counts = chain_df[col].apply(_format_category_label).value_counts()
    return {
        label: round(float(count / total * 100), 2)
        for label, count in counts.items()
        if label and label != "Unknown"
    }


def _driver_label(col: str) -> str:
    return _DRIVER_LABELS.get(col, col.replace("_", " ").title())


def _population_stats(df: pd.DataFrame, cols: list[str]) -> dict[str, dict[str, float]]:
    stats: dict[str, dict[str, float]] = {}
    for col in cols:
        if col not in df.columns:
            continue
        s = pd.to_numeric(df[col], errors="coerce").dropna()
        if s.empty:
            continue
        std = float(s.std()) if len(s) > 1 else 0.0
        stats[col] = {
            "mean": float(s.mean()),
            "std": std if std > 0 else 1.0,
        }
    return stats


def _dominant_correlation_driver(
    row: pd.Series,
    stats: dict[str, dict[str, float]],
    cols: list[str],
) -> str | None:
    """Feature with largest |z-score| vs population — same numeric basis as Pearson r."""
    best_col: str | None = None
    best_z = -1.0
    for col in cols:
        if col not in stats:
            continue
        val = pd.to_numeric(row.get(col), errors="coerce")
        if pd.isna(val):
            continue
        mean = stats[col]["mean"]
        std = stats[col]["std"]
        z = abs((float(val) - mean) / std)
        if z > best_z:
            best_z = z
            best_col = col
    return _driver_label(best_col) if best_col else None


def _percentages_from_counts(counts: dict[str, int], total: int) -> dict[str, float]:
    if total <= 0:
        return {}
    return {
        label: round(float(count / total * 100), 2)
        for label, count in counts.items()
        if count > 0 and label
    }


def physical_timing_distribution(chain_df: pd.DataFrame, total: int) -> dict[str, float]:
    """Bucket failures by setup/hold slack — fields used in the correlation matrix."""
    if chain_df.empty or total <= 0:
        return {}
    counts = {
        "Setup Stress": 0,
        "Hold Stress": 0,
        "Setup + Hold Stress": 0,
        "Timing Within Spec": 0,
    }
    for _, row in chain_df.iterrows():
        setup = pd.to_numeric(row.get("setup_slack_ps"), errors="coerce")
        hold = pd.to_numeric(row.get("hold_slack_ps"), errors="coerce")
        setup_v = 0.0 if pd.isna(setup) else float(setup)
        hold_v = 0.0 if pd.isna(hold) else float(hold)
        if setup_v < 0 and hold_v < 0:
            counts["Setup + Hold Stress"] += 1
        elif setup_v < 0:
            counts["Setup Stress"] += 1
        elif hold_v < 0:
            counts["Hold Stress"] += 1
        else:
            counts["Timing Within Spec"] += 1
    return _percentages_from_counts(counts, total)


def _varying_columns(chain_df: pd.DataFrame, cols: list[str]) -> list[str]:
    """Columns that differ across failures on this chain (meaningful for within-chain distribution)."""
    varying: list[str] = []
    for col in cols:
        if col not in chain_df.columns:
            continue
        s = pd.to_numeric(chain_df[col], errors="coerce").dropna()
        if len(s) > 0 and s.nunique() > 1:
            varying.append(col)
    return varying


def correlation_driver_distribution(
    chain_df: pd.DataFrame,
    stats: dict[str, dict[str, float]],
    cols: list[str],
    total: int,
) -> dict[str, float]:
    """Per-failure dominant correlated feature (|z| vs population)."""
    if chain_df.empty or total <= 0:
        return {}
    use_cols = _varying_columns(chain_df, cols) or [c for c in cols if c in stats]
    counts: dict[str, int] = {}
    for _, row in chain_df.iterrows():
        label = _dominant_correlation_driver(row, stats, use_cols)
        if not label:
            continue
        counts[label] = counts.get(label, 0) + 1
    return _percentages_from_counts(counts, total)


def correlation_group_distribution(
    chain_df: pd.DataFrame,
    stats: dict[str, dict[str, float]],
    group_cols: dict[str, list[str]],
    total: int,
) -> dict[str, float]:
    """Roll up dominant driver into Physical / Scan Load / Spatial / Topology groups."""
    if chain_df.empty or total <= 0:
        return {}
    col_to_group = {
        col: group
        for group, cols in group_cols.items()
        for col in cols
    }
    all_cols = list(col_to_group.keys())
    use_cols = _varying_columns(chain_df, all_cols) or all_cols
    use_col_set = set(use_cols)
    counts: dict[str, int] = {}
    for _, row in chain_df.iterrows():
        best_col: str | None = None
        best_z = -1.0
        for col in use_cols:
            if col not in stats or col not in use_col_set:
                continue
            val = pd.to_numeric(row.get(col), errors="coerce")
            if pd.isna(val):
                continue
            z = abs((float(val) - stats[col]["mean"]) / stats[col]["std"])
            if z > best_z:
                best_z = z
                best_col = col
        if best_col:
            group = col_to_group[best_col]
            counts[group] = counts.get(group, 0) + 1
    return _percentages_from_counts(counts, total)


def _primary_driver(
    pearson_corrs: dict[str, float],
    candidates: Optional[list[str]] = None,
) -> Optional[str]:
    if not pearson_corrs:
        return None
    pool = pearson_corrs
    if candidates:
        pool = {k: v for k, v in pearson_corrs.items() if k in candidates}
    if not pool:
        return None
    return max(pool, key=lambda k: abs(pool[k]))


def _severity_level(avg_sev: Optional[float]) -> str:
    if avg_sev is None or pd.isna(avg_sev):
        return "N/A"
    if avg_sev >= 0.8:
        return "High"
    if avg_sev >= 0.4:
        return "Medium"
    return "Low"


def _compute_pearson_correlations(
    is_chain: pd.Series,
    df: pd.DataFrame,
    cols: list[str],
) -> dict[str, float]:
    pearson_corrs: dict[str, float] = {}
    for col in cols:
        if col not in df.columns:
            continue
        col_series = pd.to_numeric(df[col], errors="coerce")
        if col_series.nunique() > 1 and is_chain.nunique() > 1:
            r = float(is_chain.corr(col_series))
            pearson_corrs[col] = 0.0 if pd.isna(r) else round(r, 4)
        else:
            pearson_corrs[col] = 0.0
    return pearson_corrs


def _decompressor_chain_counts(chain_map: dict[str, dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for info in chain_map.values():
        dp = info.get("decompressor_pin") or "edt_channels_in[0]"
        counts[dp] = counts.get(dp, 0) + 1
    return counts


def enrich_failures_with_topology(
    df: pd.DataFrame,
    chain_map: dict[str, dict] | None,
) -> pd.DataFrame:
    """Attach per-row topology numerics used in Pearson correlation."""
    if df.empty or not chain_map:
        return df

    from stil_parser import resolve_chain
    from topology_analysis import infer_instance_type

    decomp_counts = _decompressor_chain_counts(chain_map)
    enriched = df.copy()
    scan_lengths: list[Any] = []
    instance_codes: list[int] = []
    channel_counts: list[int] = []

    for _, row in enriched.iterrows():
        chain = str(row.get("chain", ""))
        chain_id = str(row.get("chain_id", "") or "")
        info = resolve_chain(chain_map, chain_id, chain) or {}
        scan_lengths.append(info.get("scan_length"))
        it = info.get("instance_type") or infer_instance_type(chain_id or chain)
        instance_codes.append(_INSTANCE_TYPE_CODES.get(it, 0))
        dp = info.get("decompressor_pin") or "edt_channels_in[0]"
        channel_counts.append(decomp_counts.get(dp, 1))

    enriched["scan_length"] = scan_lengths
    enriched["instance_type_code"] = instance_codes
    enriched["compression_channel_count"] = channel_counts
    return enriched


def _topology_profile_for_chain(
    chain_map: dict[str, dict],
    chain_name: str,
    compression_meta: dict[str, Any],
) -> dict[str, Any]:
    from stil_parser import resolve_chain
    from topology_analysis import infer_instance_type

    info = resolve_chain(chain_map, "", chain_name) or {}
    chain_id = next(
        (cid for cid, cinfo in chain_map.items() if (cinfo.get("chain") or "").lower() == chain_name.lower()),
        chain_name,
    )
    instance_type = info.get("instance_type") or infer_instance_type(chain_id)
    return {
        "clock_domain": info.get("clock_domain") or info.get("scan_master_clock"),
        "scan_master_clock": info.get("scan_master_clock"),
        "scan_length": info.get("scan_length"),
        "instance_type": instance_type,
        "decompressor_pin": info.get("decompressor_pin"),
        "compactor_pin": info.get("compactor_pin"),
        "scan_in": info.get("scan_in"),
        "scan_out": info.get("scan_out"),
        "compression_ratio": compression_meta.get("compression_ratio"),
        "compression_logic": compression_meta.get("compression_logic"),
    }


def _build_summary(correlations: list[dict[str, Any]], total_fail_records: int) -> dict[str, Any]:
    strongest: Optional[dict[str, Any]] = None
    max_abs = -1.0
    for row in correlations:
        for metric, r in (row.get("pearson_correlations") or {}).items():
            abs_r = abs(float(r))
            if abs_r > max_abs:
                max_abs = abs_r
                strongest = {
                    "chain": row.get("chain"),
                    "metric": metric,
                    "r": round(float(r), 4),
                }
    strength = "weak"
    if max_abs >= 0.3:
        strength = "strong"
    elif max_abs >= 0.1:
        strength = "moderate"
    return {
        "chain_count": len(correlations),
        "total_fail_records": total_fail_records,
        "strongest_correlation": strongest,
        "max_abs_r": round(max_abs, 4) if max_abs >= 0 else 0.0,
        "correlation_strength": strength,
    }


def build_chain_averages_table(
    correlations: list[dict[str, Any]],
    valid_num_cols: list[str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in correlations:
        avgs = row.get("chain_averages") or {}
        avg_sev = avgs.get("ai_severity_score")
        entry: dict[str, Any] = {
            "chain": row.get("chain"),
            "failure_count": row.get("failure_count", 0),
            "primary_physical_driver": row.get("primary_physical_driver"),
            "primary_spatial_driver": row.get("primary_spatial_driver"),
            "primary_scan_load_driver": row.get("primary_scan_load_driver"),
            "avg_ir_drop_mv": avgs.get("ir_drop_mv"),
            "avg_thermal_c": avgs.get("thermal_c"),
            "avg_setup_slack_ps": avgs.get("setup_slack_ps"),
            "avg_hold_slack_ps": avgs.get("hold_slack_ps"),
            "avg_ai_severity_score": avg_sev,
            "severity_level": _severity_level(
                float(avg_sev) if avg_sev is not None else None
            ),
        }
        for col in valid_num_cols:
            if col in {
                "ir_drop_mv",
                "thermal_c",
                "setup_slack_ps",
                "hold_slack_ps",
                "ai_severity_score",
            }:
                continue
            entry[f"avg_{col}"] = avgs.get(col)
        rows.append(entry)
    return rows


def _pct_diff(chain_val: float, pop_val: float) -> Optional[float]:
    if pop_val == 0:
        return None
    return round((chain_val - pop_val) / abs(pop_val) * 100, 1)


def _timing_stress_rate(pct: dict[str, float]) -> float:
    return float(
        pct.get("Setup Stress", 0)
        + pct.get("Hold Stress", 0)
        + pct.get("Setup + Hold Stress", 0)
    )


def build_metric_comparisons(
    chain_averages: dict[str, Optional[float]],
    overall: dict[str, Optional[float]],
    cols: list[str],
) -> list[dict[str, Any]]:
    """Chain mean vs population mean for each correlated metric."""
    rows: list[dict[str, Any]] = []
    for col in cols:
        chain_val = chain_averages.get(col)
        pop_val = overall.get(col)
        if chain_val is None or pop_val is None:
            continue
        cv, pv = float(chain_val), float(pop_val)
        diff = cv - pv
        rows.append({
            "metric": col,
            "label": _driver_label(col),
            "chain_avg": round(cv, 2),
            "overall_avg": round(pv, 2),
            "delta": round(diff, 2),
            "pct_diff": _pct_diff(cv, pv),
            "direction": "higher" if diff > 0.001 else ("lower" if diff < -0.001 else "same"),
        })
    rows.sort(key=lambda r: abs(r.get("pct_diff") or 0), reverse=True)
    return rows


def build_distinguishing_factors(
    metric_comparisons: list[dict[str, Any]],
    limit: int = 8,
) -> list[dict[str, Any]]:
    """Rank metrics by how far this chain deviates from population average."""
    factors: list[dict[str, Any]] = []
    for row in metric_comparisons[:limit]:
        pct = row.get("pct_diff")
        if pct is None:
            continue
        factors.append({
            "label": row["label"],
            "metric": row["metric"],
            "pct_diff": pct,
            "direction": row["direction"],
            "chain_avg": row["chain_avg"],
            "overall_avg": row["overall_avg"],
        })
    return factors


def build_signature_bullets(
    chain_name: str,
    *,
    failure_count: int,
    physical_timing_pct: dict[str, float],
    spatial_pct: dict[str, float],
    distinguishing_factors: list[dict[str, Any]],
    pop_timing_stress: float,
) -> list[str]:
    """Plain-language chain signature lines for engineers."""
    bullets: list[str] = []
    bullets.append(f"{failure_count:,} failure records on {chain_name}.")

    stress = _timing_stress_rate(physical_timing_pct)
    if stress > 0:
        pp = round(stress - pop_timing_stress, 1)
        sign = "+" if pp >= 0 else ""
        bullets.append(
            f"{stress:.0f}% of failures show setup/hold timing stress "
            f"({sign}{pp} pp vs overall average)."
        )

    if spatial_pct:
        top_die = max(spatial_pct.items(), key=lambda x: x[1])
        bullets.append(
            f"Failures concentrated on {top_die[0]} ({top_die[1]:.0f}% of chain failures)."
        )

    if distinguishing_factors:
        top = distinguishing_factors[0]
        pct = top.get("pct_diff")
        if pct is not None and abs(pct) >= 0.5:
            dir_word = "above" if pct > 0 else "below"
            bullets.append(
                f"Most distinguishing vs average: {top['label']} "
                f"({abs(pct):.1f}% {dir_word} average)."
            )

    if len(bullets) == 1:
        bullets.append("No strong deviation from overall averages on correlated metrics.")
    return bullets


def build_signature_summary(
    correlations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """One-line signature per chain for overview table."""
    overview: list[dict[str, Any]] = []
    for row in correlations:
        factors = row.get("distinguishing_factors") or []
        bullets = row.get("signature_bullets") or []
        top = factors[0] if factors else {}
        overview.append({
            "chain": row.get("chain"),
            "failure_count": row.get("failure_count", 0),
            "top_factor": top.get("label"),
            "top_pct_diff": top.get("pct_diff"),
            "summary": bullets[1] if len(bullets) > 1 else (bullets[0] if bullets else ""),
        })
    overview.sort(
        key=lambda r: abs(float(r.get("top_pct_diff") or 0)),
        reverse=True,
    )
    return overview


def build_correlation_rows(
    df: pd.DataFrame,
    chain_map: dict[str, dict] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Optional[float]], dict[str, Any]]:
    """Per-chain Pearson correlations, categorical profiles, chain averages, and summary meta."""
    if df.empty or "chain" not in df.columns:
        return [], {}, {}

    work_df = enrich_failures_with_topology(df, chain_map)

    valid_physical = [c for c in PHYSICAL_TIMING_COLS if c in work_df.columns]
    valid_scan_load = [c for c in SCAN_LOAD_COLS if c in work_df.columns]
    valid_spatial = [c for c in SPATIAL_COLS if c in work_df.columns]
    valid_topology = [c for c in TOPOLOGY_NUMERIC_COLS if c in work_df.columns]
    valid_num_cols = valid_physical + valid_scan_load + valid_spatial + valid_topology

    compression_meta: dict[str, Any] = {}
    if chain_map:
        from topology_analysis import build_compression_association

        compression_meta = build_compression_association(chain_map)

    overall: dict[str, Optional[float]] = {
        col: safe_mean(work_df[col]) for col in valid_num_cols
    }
    region_field = pick_categorical_field(work_df, REGION_FIELD_PRIORITY)
    pop_stats = _population_stats(work_df, valid_num_cols)
    pop_timing_stress = _timing_stress_rate(
        physical_timing_distribution(work_df, len(work_df))
    )
    group_cols = {
        "Physical / Timing": valid_physical,
        "Scan / Test Load": valid_scan_load,
        "Spatial": valid_spatial,
        "Topology": valid_topology,
    }

    correlations: list[dict[str, Any]] = []
    unique_chains = sorted(
        work_df["chain"].dropna().astype(str).unique(),
        key=chain_sort_key,
    )

    for chain_name in unique_chains:
        is_chain = (work_df["chain"].astype(str) == chain_name).astype(int)
        chain_df = work_df[work_df["chain"].astype(str) == chain_name]
        total_chain_fails = len(chain_df)

        pearson_corrs = _compute_pearson_correlations(is_chain, work_df, valid_num_cols)
        spatial_corrs = {
            k: pearson_corrs[k] for k in valid_spatial if k in pearson_corrs
        }
        topology_corrs = {
            k: pearson_corrs[k] for k in valid_topology if k in pearson_corrs
        }

        physical_timing_pct = physical_timing_distribution(chain_df, total_chain_fails)
        spatial_pct = (
            categorical_percentages(chain_df, region_field, total_chain_fails)
            if region_field
            else {}
        )
        driver_pct = correlation_driver_distribution(
            chain_df, pop_stats, valid_num_cols, total_chain_fails,
        )
        group_pct = correlation_group_distribution(
            chain_df, pop_stats, group_cols, total_chain_fails,
        )

        chain_averages = {col: safe_mean(chain_df[col]) for col in valid_num_cols}
        metric_comparisons = build_metric_comparisons(chain_averages, overall, valid_num_cols)
        distinguishing_factors = build_distinguishing_factors(metric_comparisons)

        topology_profile: dict[str, Any] = {}
        if chain_map:
            topology_profile = _topology_profile_for_chain(
                chain_map, chain_name, compression_meta
            )

        correlations.append({
            "chain": chain_name,
            "failure_count": total_chain_fails,
            "pearson_correlations": pearson_corrs,
            "spatial_correlations": spatial_corrs,
            "topology_correlations": topology_corrs,
            "primary_physical_driver": _primary_driver(pearson_corrs, valid_physical),
            "primary_spatial_driver": _primary_driver(pearson_corrs, valid_spatial),
            "primary_scan_load_driver": _primary_driver(pearson_corrs, valid_scan_load),
            "primary_topology_driver": _primary_driver(pearson_corrs, valid_topology),
            "primary_driver": _primary_driver(pearson_corrs),
            "physical_timing_percentages": physical_timing_pct,
            "spatial_percentages": spatial_pct,
            "correlation_driver_percentages": driver_pct,
            "correlation_group_percentages": group_pct,
            # Legacy keys for exports / older clients
            "failure_region_percentages": spatial_pct,
            "chain_averages": chain_averages,
            "topology_profile": topology_profile,
            "metric_comparisons": metric_comparisons,
            "distinguishing_factors": distinguishing_factors,
            "signature_bullets": build_signature_bullets(
                chain_name,
                failure_count=total_chain_fails,
                physical_timing_pct=physical_timing_pct,
                spatial_pct=spatial_pct,
                distinguishing_factors=distinguishing_factors,
                pop_timing_stress=pop_timing_stress,
            ),
        })

    meta = {
        "region_field_used": region_field,
        "presentation": "chain_signature_profile",
        "signature_method": (
            "Chain Signature compares each chain's failure averages to the overall average across all failures. "
            "Distinguishing factors are ranked by percent difference from that average — "
            "no Pearson r required."
        ),
        "population_timing_stress_pct": round(pop_timing_stress, 1),
        "distribution_method": (
            "Timing stress from setup/hold slack; spatial from die/wafer fields; "
            "driver mix from largest deviation vs overall average per failure."
        ),
        "numerical_features": valid_num_cols,
        "correlation_feature_count": len(valid_num_cols) + (1 if region_field else 0),
        "chains_analyzed": len(correlations),
        "physical_features": valid_physical,
        "scan_load_features": valid_scan_load,
        "spatial_features": valid_spatial,
        "topology_fields": valid_topology,
        "topology_available": bool(chain_map),
        "compression_summary": compression_meta if chain_map else {},
        "summary": _build_summary(correlations, len(work_df)),
        "chain_averages_table": build_chain_averages_table(correlations, valid_num_cols),
        "chain_signature_overview": build_signature_summary(correlations),
    }
    return correlations, overall, meta
