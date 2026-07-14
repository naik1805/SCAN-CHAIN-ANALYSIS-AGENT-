"""
Export requirement outputs to the project ``output/`` folder as JSON.

Currently records:
    SCD-FR-001  Identify failing scan chains
                (acceptance: failing scan chains identified from failure logs)

Usage:
    cd src
    python export_outputs.py            # parse all logs under data/logs
    python export_outputs.py --max-per-lot 2   # quick subset
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import numpy as np

from parser import discover_logs, parse_log_to_dataframe
from stil_parser import parse_stil_scan_structures, parse_hardware_topology_md, find_topology_md_file, resolve_chain, resolve_active_stil_file
from locate_cells import locate_failing_cells, enrich_with_positions
from topology_analysis import build_topology_analysis

APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parent
DATA_DIR = PROJECT_ROOT / "data"
LOG_DIR = DATA_DIR / "logs"
STIL_DIR = DATA_DIR / "stil"
OUTPUT_DIR = PROJECT_ROOT / "output"


def select_logs(max_per_lot: int | None) -> list[Path]:
    logs = discover_logs(LOG_DIR)
    if not max_per_lot:
        return logs
    kept: list[Path] = []
    seen: dict[str, int] = {}
    for p in logs:
        lot = p.parent.name
        if seen.get(lot, 0) < max_per_lot:
            kept.append(p)
            seen[lot] = seen.get(lot, 0) + 1
    return kept


def _apply_ml_to_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    # Ensure required columns
    from parser import NUMERIC_COLS
    required_cols = [
        "lot_id", "lot_pattern", "wafer_id", "die_id", "source_file", 
        "pattern_id", "chain_id", "chain", "fail_flop_id", "fail_type", 
        "expected_signature", "actual_signature", "root_cause_hint", 
        "failure_region", "status", "defect_type", "die_label",
        "predicted_root_cause", "prediction_confidence", "is_anomaly", "anomaly_score"
    ] + NUMERIC_COLS
    for col in required_cols:
        if col not in df.columns:
            df[col] = None

    import ml_pipeline as mlp
    classifier = mlp.load_classifier(df)
    if classifier is None:
        try:
            classifier, _ = mlp.train_root_cause_classifier(df)
            mlp.save_classifier(classifier)
        except Exception:
            pass
    if classifier is not None:
        try:
            df = mlp.predict_root_cause(classifier, df)
        except Exception:
            pass

    anomaly_detector = mlp.load_anomaly_detector(df)
    if anomaly_detector is None:
        try:
            anomaly_detector = mlp.train_anomaly_detector(df)
            mlp.save_anomaly_detector(anomaly_detector)
        except Exception:
            pass
    if anomaly_detector is not None:
        try:
            df = mlp.detect_anomalies(anomaly_detector, df)
        except Exception:
            pass
    return df


def load_failures(paths: list[Path]) -> pd.DataFrame:
    # Try loading from cache first
    from disk_cache import load_from_cache
    paths_info = []
    for p in paths:
        try:
            stat = p.stat()
            paths_info.append((str(p), stat.st_mtime, stat.st_size))
        except OSError:
            pass
            
    cached_df = load_from_cache(paths_info, PROJECT_ROOT)
    if cached_df is not None:
        print("Loaded parsed failures from cache!")
        df_out = cached_df.copy()
        for col in df_out.columns:
            if df_out[col].dtype.name == "category":
                df_out[col] = df_out[col].astype(object)
        df_out = _apply_ml_to_df(df_out)
        return df_out

    from concurrent.futures import ProcessPoolExecutor
    with ProcessPoolExecutor() as executor:
        results = executor.map(parse_log_to_dataframe, paths)
        
    frames = [df_sub for df_sub in results if not df_sub.empty]
    if not frames:
        return pd.DataFrame()
    df_out = pd.concat(frames, ignore_index=True)
    df_out = _apply_ml_to_df(df_out)
    return df_out



def build_fr001(df: pd.DataFrame, paths: list[Path]) -> dict:
    """Build the SCD-FR-001 result: failing scan chains identified from logs."""
    total = len(df)
    grp = df.groupby("chain")

    failing_chains = []
    for chain, sub in grp:
        ft = sub["fail_type"].value_counts().to_dict()
        failing_chains.append(
            {
                "chain": chain,
                "fail_count": int(len(sub)),
                "fail_pct": round(len(sub) / total * 100, 3) if total else 0.0,
                "distinct_patterns": int(sub["pattern_id"].nunique()),
                "distinct_fail_flops": int(sub["fail_flop_id"].nunique()),
                "lots_affected": int(sub["lot_id"].nunique()),
                "fail_type_breakdown": {k: int(v) for k, v in ft.items()},
                "example_chain_id": sub["chain_id"].iloc[0] if not sub.empty else "",
            }
        )
    failing_chains.sort(key=lambda d: d["fail_count"], reverse=True)
    for rank, item in enumerate(failing_chains, start=1):
        item["rank"] = rank

    return {
        "requirement_id": "SCD-FR-001",
        "requirement": "Identify failing scan chains",
        "acceptance_criteria": "Failing scan chains identified from failure logs.",
        "status": "satisfied" if failing_chains else "no_failures_found",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "logs_parsed": len(paths),
            "log_files": [p.relative_to(LOG_DIR).as_posix() for p in paths],
            "lots": sorted(df["lot_id"].dropna().unique().tolist()) if not df.empty else [],
        },
        "summary": {
            "total_fail_records": int(total),
            "distinct_failing_chains": int(df["chain"].nunique()) if not df.empty else 0,
            "distinct_failing_flops": int(df["fail_flop_id"].nunique()) if not df.empty else 0,
        },
        "failing_chains": failing_chains,
    }


def build_fr004(df: pd.DataFrame, paths: list[Path]) -> dict:
    """Build the SCD-FR-004 result: chains ranked by failure frequency."""
    from chain_ranking import available_ranking_features, rank_chains_by_frequency

    total = len(df)
    freq = rank_chains_by_frequency(df, method="dense")
    ranking_features = available_ranking_features()

    ranking = []
    for _, row in freq.iterrows():
        ranking.append(
            {
                "rank": int(row["rank"]),
                "chain": row["chain"],
                "fail_count": int(row["fail_count"]),
                "fail_pct": float(row["fail_pct"]),
                "cumulative_pct": float(row["cumulative_pct"]),
                "rank_method": row.get("rank_method", ranking_features["default_method"]),
            }
        )

    # Pareto 80/20: how many chains account for 80% of failures.
    chains_to_80 = int((freq["cumulative_pct"] <= 80.0).sum()) if not freq.empty else 0
    chains_to_80 = max(chains_to_80, 1) if ranking else 0

    return {
        "requirement_id": "SCD-FR-004",
        "requirement": "Rank scan chains by failure frequency",
        "acceptance_criteria": "Chains ranked based on failure frequency.",
        "status": "satisfied" if ranking else "no_failures_found",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "logs_parsed": len(paths),
            "lots": sorted(df["lot_id"].dropna().unique().tolist()) if not df.empty else [],
        },
        "ranking_feature": ranking_features,
        "summary": {
            "total_fail_records": int(total),
            "distinct_failing_chains": int(df["chain"].nunique()) if not df.empty else 0,
            "top_chain": ranking[0]["chain"] if ranking else None,
            "top_chain_fail_count": ranking[0]["fail_count"] if ranking else 0,
            "chains_covering_80pct": chains_to_80,
            "rank_method": ranking_features["default_method"],
        },
        "ranking": ranking,
    }


def build_fr002(df: pd.DataFrame, paths: list[Path], min_observations: int = 2,
                top_n: int = 500) -> dict:
    md_topo_file = find_topology_md_file(DATA_DIR)
    if md_topo_file:
        chain_map = parse_hardware_topology_md(md_topo_file)
        stil_name = md_topo_file.name
    else:
        active_stil = resolve_active_stil_file(df)
        chain_map = parse_stil_scan_structures(active_stil) if active_stil else {}
        stil_name = active_stil.name if active_stil else None

    suspects = locate_failing_cells(df, chain_map, min_observations=min_observations)
    if suspects.empty and not df.empty:
        suspects = locate_failing_cells(df, chain_map, min_observations=1)
        min_observations = 1

    def records(frame: pd.DataFrame) -> list[dict]:
        out = []
        for _, r in frame.iterrows():
            out.append({
                "chain": r["chain"],
                "instance": r["instance"],
                "chain_id": r["chain_id"],
                "suspected_cell": r["cell_name"],
                "fail_flop_id": r["fail_flop_id"],
                "bit_position": None if pd.isna(r["bit_position"]) else int(r["bit_position"]),
                "offset_from_scan_in": None if pd.isna(r["offset_from_scan_in"]) else int(r["offset_from_scan_in"]),
                "chain_length": int(r["chain_length"]),
                "observations": int(r["observations"]),
                "corroborating_patterns": int(r["corroborating_patterns"]),
                "chain_observations": int(r["chain_observations"]),
                "confidence": float(r["confidence"]),
                "dominant_fail_type": r["dominant_fail_type"],
                "dominant_region": r["dominant_region"],
                "dominant_root_cause": r["dominant_root_cause"],
                "predicted_root_cause": r.get("predicted_root_cause", "UNKNOWN"),
                "mean_ai_severity": None if pd.isna(r["mean_ai_severity"]) else float(r["mean_ai_severity"]),
                "mean_ai_severity_level": "N/A" if pd.isna(r["mean_ai_severity"]) else ("High" if float(r["mean_ai_severity"]) >= 0.8 else ("Medium" if float(r["mean_ai_severity"]) >= 0.4 else "Low")),
                "lots_affected": int(r["lots_affected"]),
                "scan_in": r["scan_in"],
                "scan_out": r["scan_out"],
                "scan_master_clock": r["scan_master_clock"],
            })
        return out

    # Best (highest-confidence) suspect per chain.
    per_chain_top = (
        suspects.sort_values("confidence", ascending=False)
        .groupby("chain_id", as_index=False).first()
        if not suspects.empty else suspects
    )

    return {
        "requirement_id": "SCD-FR-002",
        "requirement": "Locate failing scan cells",
        "acceptance_criteria": "Suspected failing scan cells identified with confidence score.",
        "method": (
            "Map FAIL_FLOP_ID -> bit position via STIL ScanLength, look up cell name, "
            "and compute composite diagnostic confidence score using a Logistic Regression "
            "ML model trained on historical microscope confirmation records (incorporating "
            "pattern support, chain location, and root cause classification)."
        ),
        "status": "satisfied" if not suspects.empty else "no_failures_found",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "logs_parsed": len(paths),
            "stil_file": stil_name,
            "stil_chains": len(chain_map),
            "min_observations": min_observations,
        },
        "summary": {
            "total_suspected_cells": int(len(suspects)),
            "chains_involved": int(suspects["chain_id"].nunique()) if not suspects.empty else 0,
            "max_confidence": float(suspects["confidence"].max()) if not suspects.empty else 0.0,
            "mean_confidence": round(float(suspects["confidence"].mean()), 4) if not suspects.empty else 0.0,
            "top_n_recorded": int(min(top_n, len(suspects))),
        },
        "per_chain_top_suspect": records(per_chain_top) if not suspects.empty else [],
        "top_suspected_cells": records(suspects.head(top_n)) if not suspects.empty else [],
    }


def build_fr003(df: pd.DataFrame = None) -> dict:
    """Build the SCD-FR-003 result: complete scan topology analysis."""
    md_topo_file = find_topology_md_file(DATA_DIR)
    if md_topo_file:
        chain_map = parse_hardware_topology_md(md_topo_file)
        stil_name = md_topo_file.name
    else:
        active_stil = resolve_active_stil_file(df)
        chain_map = parse_stil_scan_structures(active_stil) if active_stil else {}
        stil_name = active_stil.name if active_stil else None

    analysis = build_topology_analysis(chain_map, failures=df, log_dir=LOG_DIR)

    return {
        "requirement_id": "SCD-FR-003",
        "requirement": "Analyze scan chain topology",
        "acceptance_criteria": "Scan topology loaded and visualized correctly.",
        "status": analysis.get("status", "no_stil_loaded"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "stil_file": stil_name,
            "logs_analyzed": analysis.get("summary", {}).get("logs_analyzed", 0),
            "failure_records_analyzed": analysis.get("summary", {}).get("failure_records_analyzed", 0),
        },
        "number_of_scan_chains": analysis.get("number_of_scan_chains", 0),
        "summary": analysis.get("summary", {}),
        "chain_balance": analysis.get("chain_balance", {}),
        "shared_resources": analysis.get("shared_resources", {}),
        "compression_association": analysis.get("compression_association", {}),
        "connectivity_graph": {
            "node_count": analysis.get("connectivity_graph", {}).get("node_count", 0),
            "edge_count": analysis.get("connectivity_graph", {}).get("edge_count", 0),
            "nodes": analysis.get("connectivity_graph", {}).get("nodes", []),
            "edges": analysis.get("connectivity_graph", {}).get("edges", []),
        },
        "chains": analysis.get("chains", []),
    }


def build_fr005(df: pd.DataFrame, paths: list[Path]) -> dict:
    """Build the SCD-FR-005 result: scan-chain-to-failure correlation report."""
    correlations = []
    if df.empty:
        return {
            "requirement_id": "SCD-FR-005",
            "requirement": "Correlate failures with scan chains",
            "acceptance_criteria": "Scan-chain-to-failure correlation report generated.",
            "status": "no_failures_found",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "inputs": {
                "logs_parsed": len(paths),
                "total_fail_records": 0
            },
            "correlations": []
        }

    numerical_cols = ["ir_drop_mv", "thermal_c", "setup_slack_ps", "hold_slack_ps", "ai_severity_score"]
    valid_num_cols = [col for col in numerical_cols if col in df.columns]

    # Sort chains numerically
    def _num_key(c):
        val = "".join(ch for ch in c if ch.isdigit())
        return int(val) if val else 0
    unique_chains = sorted(df["chain"].dropna().unique(), key=_num_key)

    for chain_name in unique_chains:
        # Create binary indicator column in a temporary dataframe
        is_chain = (df["chain"] == chain_name).astype(int)
        
        # Pearson correlation for each valid numerical column
        pearson_corrs = {}
        for col in valid_num_cols:
            col_series = pd.to_numeric(df[col], errors="coerce")
            # We need standard deviation > 0 for both variables to compute correlation
            if col_series.nunique() > 1 and is_chain.nunique() > 1:
                r = float(is_chain.corr(col_series))
                pearson_corrs[col] = 0.0 if pd.isna(r) else round(r, 4)
            else:
                pearson_corrs[col] = 0.0
                
        # Categorical distributions for this chain
        chain_df = df[df["chain"] == chain_name]
        total_chain_fails = len(chain_df)
        
        # 1. Fail Type breakdown
        fail_type_pct = {}
        if not chain_df.empty and "fail_type" in chain_df.columns:
            fail_type_counts = chain_df["fail_type"].value_counts()
            for k, v in fail_type_counts.items():
                fail_type_pct[k] = round(float(v / total_chain_fails * 100), 2)
                
        # 2. Failure Region breakdown
        region_pct = {}
        if not chain_df.empty and "failure_region" in chain_df.columns:
            region_counts = chain_df["failure_region"].value_counts()
            for k, v in region_counts.items():
                region_pct[k] = round(float(v / total_chain_fails * 100), 2)
                
        # 3. Root Cause Hint breakdown
        root_cause_pct = {}
        if not chain_df.empty and "root_cause_hint" in chain_df.columns:
            rc_counts = chain_df["root_cause_hint"].value_counts()
            for k, v in rc_counts.items():
                root_cause_pct[k] = round(float(v / total_chain_fails * 100), 2)
                
        # Primary driver: the parameter in valid_num_cols with highest absolute pearson correlation
        primary_driver = None
        max_abs_r = -1.0
        for col, r in pearson_corrs.items():
            if abs(r) > max_abs_r:
                max_abs_r = abs(r)
                primary_driver = col
                
        correlations.append({
            "chain": chain_name,
            "failure_count": total_chain_fails,
            "pearson_correlations": pearson_corrs,
            "primary_physical_driver": primary_driver,
            "fail_type_percentages": fail_type_pct,
            "failure_region_percentages": region_pct,
            "root_cause_percentages": root_cause_pct
        })

    return {
        "requirement_id": "SCD-FR-005",
        "requirement": "Correlate failures with scan chains",
        "acceptance_criteria": "Scan-chain-to-failure correlation report generated.",
        "status": "satisfied" if correlations else "no_failures_analyzed",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "logs_parsed": len(paths),
            "total_fail_records": len(df)
        },
        "correlations": correlations
    }


def build_fr006(df: pd.DataFrame, paths: list[Path]) -> dict:
    """Build the SCD-FR-006 result: exact scan chain break locations."""
    from chain_breaks import detect_chain_breaks_detailed

    if df.empty:
        return {
            "requirement_id": "SCD-FR-006",
            "requirement": "Identify scan chain breaks",
            "acceptance_criteria": "Exact chain break locations detected and highlighted.",
            "status": "no_failures_found",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "inputs": {
                "logs_parsed": len(paths),
                "total_fail_records": 0
            },
            "breaks": []
        }

    md_topo_file = find_topology_md_file(DATA_DIR)
    if md_topo_file and md_topo_file.exists():
        chain_map = parse_hardware_topology_md(md_topo_file)
        stil_name = md_topo_file.name
    else:
        active_stil = resolve_active_stil_file(df)
        chain_map = parse_stil_scan_structures(active_stil) if active_stil else {}
        stil_name = active_stil.name if active_stil else None

    breaks = detect_chain_breaks_detailed(df, chain_map)
    # Ensure JSON-safe None for UNCERTAIN exact bit (pandas NaN → null)
    for b in breaks:
        exact_bit = b.get("exact_break_bit_position")
        if exact_bit is not None and isinstance(exact_bit, float) and np.isnan(exact_bit):
            b["exact_break_bit_position"] = None
        if b.get("location_status") != "CERTAIN":
            b["exact_break_bit_position"] = None
            b["exact_break_cell"] = "LOCATION_UNCERTAIN"

    confidences = [b.get("location_confidence", 0.0) for b in breaks]
    n_certain = sum(1 for b in breaks if b.get("location_status") == "CERTAIN")
    n_uncertain = len(breaks) - n_certain

    return {
        "requirement_id": "SCD-FR-006",
        "requirement": "Identify scan chain breaks",
        "acceptance_criteria": (
            "Chain break signatures detected; Exact Break Cell claimed only when "
            "location_status is CERTAIN (soft agreement ≥70% with ≥2 patterns)."
        ),
        "status": "satisfied" if breaks else "no_breaks_detected",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "localization": {
            "method": "per_pattern_first_mismatch_consensus",
            "description": (
                "Candidate break bit = consensus of per-pattern first EXPECTED vs ACTUAL "
                "mismatch indices from ScanOut; mapped to STIL ScanCells. "
                "Exact fields are populated only when location_status is CERTAIN "
                "(soft agreement ≥70% and ≥2 patterns); otherwise exact_break_cell is "
                "LOCATION_UNCERTAIN and candidate_* fields hold the review localization."
            ),
            "certain_soft_agreement_min": 0.70,
            "certain_min_patterns": 2,
        },
        "inputs": {
            "logs_parsed": len(paths),
            "total_fail_records": len(df),
            "stil_file": stil_name
        },
        "summary": {
            "total_detected_breaks": len(breaks),
            "location_certain_count": n_certain,
            "location_uncertain_count": n_uncertain,
            "unique_lots_affected": len({b["lot_id"] for b in breaks}),
            "unique_dice_affected": len({(b["lot_id"], b["source_file"]) for b in breaks}),
            "mean_location_confidence": round(float(np.mean(confidences)), 4) if confidences else 0.0,
            "exact_locations_reported": n_certain,
        },
        "breaks": breaks
    }


def build_fr007(df: pd.DataFrame, paths: list[Path]) -> dict:
    """Build the SCD-FR-007 result: Shift vs Capture Diagnostics."""
    md_topo_file = find_topology_md_file(DATA_DIR)
    if md_topo_file:
        chain_map = parse_hardware_topology_md(md_topo_file)
        stil_name = md_topo_file.name
    else:
        active_stil = resolve_active_stil_file(df)
        chain_map = parse_stil_scan_structures(active_stil) if active_stil else {}
        stil_name = active_stil.name if active_stil else None

    # Run cell localization first to resolve bit positions, cell names, and chain lengths
    enriched = enrich_with_positions(df, chain_map)

    broken_chains = set()
    if not enriched.empty:
        grouped = enriched.groupby(["source_file", "lot_id", "chain"])
        for (sf, lot, ch), sub in grouped:
            min_pos = sub["bit_position"].min()
            max_pos = sub["bit_position"].max()
            unique_pos = sub["bit_position"].nunique()
            c_len = sub["chain_length"].iloc[0] if "chain_length" in sub.columns else 234
            
            exp_bs = sub["expected_output"].iloc[0] if "expected_output" in sub.columns and pd.notna(sub["expected_output"].iloc[0]) else None
            if exp_bs and isinstance(exp_bs, str):
                last_care = len(exp_bs) - 1
                while last_care >= 0 and exp_bs[last_care] == 'X':
                    last_care -= 1
                max_possible_pos = last_care if last_care >= 0 else (c_len - 1)
            else:
                max_possible_pos = c_len - 1

            if min_pos > 0 and max_pos >= (max_possible_pos - 5) and unique_pos >= 5:
                broken_chains.add((sf, lot, ch))

    diagnoses = []
    shift_count = 0
    setup_count = 0
    setup_anomaly_count = 0
    hold_count = 0
    hold_anomaly_count = 0
    cell_defect_count = 0

    for _, row in enriched.iterrows():
        sf = row.get("source_file")
        lot = row.get("lot_id")
        ch = row.get("chain")
        
        is_shift = (sf, lot, ch) in broken_chains
        
        setup_slack = row.get("setup_slack_ps")
        if pd.isna(setup_slack) or setup_slack is None:
            setup_slack = 0.0
        else:
            setup_slack = float(setup_slack)

        hold_slack = row.get("hold_slack_ps")
        if pd.isna(hold_slack) or hold_slack is None:
            hold_slack = 0.0
        else:
            hold_slack = float(hold_slack)

        is_anomaly = row.get("is_anomaly", 0)
        if pd.isna(is_anomaly) or is_anomaly is None:
            is_anomaly = 0
        else:
            is_anomaly = int(is_anomaly)

        if is_shift:
            cls = "SHIFT_ISSUE"
            shift_count += 1
            details = f"Associated with scan chain break on chain {ch}."
        elif setup_slack < 0 and setup_slack <= hold_slack:
            if is_anomaly:
                cls = "CAPTURE_TIMING_SETUP_ANOMALY"
                setup_anomaly_count += 1
                details = f"Anomalous setup timing violation (slack: {setup_slack} ps)."
            else:
                cls = "CAPTURE_TIMING_SETUP"
                setup_count += 1
                details = f"Setup timing violation (slack: {setup_slack} ps)."
        elif hold_slack < 0 and hold_slack < setup_slack:
            if is_anomaly:
                cls = "CAPTURE_TIMING_HOLD_ANOMALY"
                hold_anomaly_count += 1
                details = f"Anomalous hold timing violation (slack: {hold_slack} ps)."
            else:
                cls = "CAPTURE_TIMING_HOLD"
                hold_count += 1
                details = f"Hold timing violation (slack: {hold_slack} ps)."
        else:
            cls = "CAPTURE_CELL_DEFECT"
            cell_defect_count += 1
            rc = row.get("predicted_root_cause", "UNKNOWN")
            details = f"Functional cell defect (RF predicted root cause: {rc})."

        diagnoses.append({
            "lot_id": lot,
            "source_file": Path(sf).name if sf else "Unknown",
            "pattern_id": str(row.get("pattern_id")),
            "chain": ch,
            "flop_id": row.get("fail_flop_id"),
            "bit_position": int(row["bit_position"]) if pd.notna(row.get("bit_position")) else None,
            "classification": cls,
            "details": details
        })

    diagnoses.sort(key=lambda x: (x["lot_id"], x["source_file"], x["pattern_id"], x["chain"]))

    return {
        "requirement_id": "SCD-FR-007",
        "requirement": "Detect shift and capture issues",
        "acceptance_criteria": "Shift/capture issues classified correctly.",
        "status": "satisfied" if diagnoses else "no_data",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "logs_parsed": len(paths),
            "total_fail_records": len(df),
            "stil_file": stil_name
        },
        "summary": {
            "total_diagnoses": len(diagnoses),
            "shift_issues": shift_count,
            "capture_timing_setup": setup_count,
            "capture_timing_setup_anomaly": setup_anomaly_count,
            "capture_timing_hold": hold_count,
            "capture_timing_hold_anomaly": hold_anomaly_count,
            "capture_cell_defect": cell_defect_count
        },
        "diagnoses": diagnoses
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-per-lot", type=int, default=None,
                    help="Limit logs per lot (omit to use all logs).")
    args = ap.parse_args()

    paths = select_logs(args.max_per_lot)
    print(f"Parsing {len(paths)} log file(s)...")
    df = load_failures(paths)
    print(f"Parsed {len(df):,} FAIL records.")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Load chain map
    md_topo_file = find_topology_md_file(DATA_DIR)
    if md_topo_file:
        chain_map = parse_hardware_topology_md(md_topo_file)
    else:
        active_stil = resolve_active_stil_file(df)
        chain_map = parse_stil_scan_structures(active_stil) if active_stil else {}

    exports = {
        "SCD-FR-001_failing_scan_chains.json": build_fr001(df, paths),
        "SCD-FR-004_chain_failure_ranking.json": build_fr004(df, paths),
        "SCD-FR-002_suspected_failing_cells.json": build_fr002(df, paths),
        "SCD-FR-003_scan_topology.json": build_fr003(df),
        "SCD-FR-005_failure_correlation.json": build_fr005(df, paths),
        "SCD-FR-006_scan_chain_breaks.json": build_fr006(df, paths),
        "SCD-FR-007_shift_capture_diagnosis.json": build_fr007(df, paths),
    }
    for fname, result in exports.items():
        out_path = OUTPUT_DIR / fname
        out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(f"Wrote {out_path}  [{result['requirement_id']}: {result['status']}]")

    # Generate HTML Report
    from report_generator import generate_html_report
    report_path = OUTPUT_DIR / "SCD-FR-008_scan_diagnosis_report.html"
    try:
        generate_html_report(
            df, chain_map, report_path,
            log_dir=LOG_DIR, project_root=PROJECT_ROOT,
        )
        print(f"Wrote {report_path}  [SCD-FR-008: satisfied]")
    except Exception as e:
        print(f"Failed to generate HTML report: {e}")

    # Generate PFA Debug Location Recommendations (SCD-FR-009)
    from debug_locations import calculate_cell_coordinates, export_pfa_locations
    try:
        coords_df = calculate_cell_coordinates(df, chain_map)
        pfa_res = export_pfa_locations(coords_df, OUTPUT_DIR)
        print(f"Wrote {OUTPUT_DIR / 'SCD-FR-009_debug_locations.json'}  [SCD-FR-009: {pfa_res['status']}]")
        print(f"Wrote {OUTPUT_DIR / 'SCD-FR-009_debug_locations.csv'}  [SCD-FR-009: {pfa_res['status']}]")
    except Exception as e:
        print(f"Failed to recommend debug locations: {e}")

    print(f"  failing chains: {df['chain'].nunique()}")
    print(f"  total fails:    {len(df):,}")


if __name__ == "__main__":
    main()
