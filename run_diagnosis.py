"""
run_diagnosis.py — Diagnostic run script for ATPG scan chain diagnosis.

Fulfills requirements:
- SCD-FR-002: Locate failing scan cells (suspected cells with confidence scores).
- SCD-FR-003: Analyze scan chain topology (loaded from the new STIL template).
- SCD-FR-004: Rank scan chains by failure frequency (Pareto ranking).
- SCD-FR-005: Correlate failures with physical tester measurements.

Reads input logs from data/logs/ and STIL file from data/stil/.
Writes JSON reports to the output/ directory.
"""

from __future__ import annotations

import sys
import json
import logging
from pathlib import Path
from datetime import datetime, timezone
import pandas as pd
import numpy as np

# Add src/ folder to Python system path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from parser import discover_logs, parse_log_to_dataframe
from stil_parser import parse_stil_scan_structures, resolve_chain, chain_summary_rows
from locate_cells import locate_failing_cells, enrich_with_positions
from config import get_config
from chain_ranking import available_ranking_features, rank_chains_by_frequency

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger("run_diagnosis")


def run_full_diagnosis():
    cfg = get_config()
    project_root = cfg.project_root
    log_dir = project_root / "data" / "logs"
    stil_dir = project_root / "data" / "stil"
    output_dir = project_root / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    log.info("Starting Scan Chain Diagnosis...")
    
    # ── Discover and Parse Logs ──────────────────────────────────────────────
    log_files = discover_logs(log_dir)
    if not log_files:
        log.error(f"No log files found in {log_dir}. Please place log files there first.")
        sys.exit(1)
        
    log.info(f"Discovered {len(log_files)} log file(s).")
    
    # Check cache first for high speed
    from disk_cache import load_from_cache, save_to_cache
    paths_info = []
    for p in log_files:
        try:
            stat = p.stat()
            paths_info.append((str(p), stat.st_mtime, stat.st_size))
        except OSError:
            pass
            
    df = load_from_cache(paths_info, project_root)
    if df is not None:
        log.info("Warm cache hit: loaded failure records from Parquet cache.")
    else:
        log.info(f"Cache miss: parsing {len(log_files)} raw log files in parallel...")
        from concurrent.futures import ProcessPoolExecutor
        
        with ProcessPoolExecutor() as executor:
            # Parse all files in parallel processes
            results = executor.map(parse_log_to_dataframe, log_files)
            
        frames = [df_sub for df_sub in results if not df_sub.empty]
        
        if not frames:
            log.warning("No failure records (STATUS: FAIL) found in any log files.")
            df = pd.DataFrame()
        else:
            df = pd.concat(frames, ignore_index=True)
            log.info("Saving parsed failures to Parquet cache...")
            save_to_cache(df, paths_info, project_root)
            
    # Ensure all standard columns are present to prevent downstream errors
    from parser import NUMERIC_COLS
    required_cols = [
        "lot_id", "lot_pattern", "wafer_id", "die_id", "source_file", 
        "pattern_id", "chain_id", "chain", "fail_flop_id", "fail_type", 
        "expected_signature", "actual_signature", "root_cause_hint", 
        "failure_region", "status", "defect_type", "die_label",
        "predicted_root_cause", "prediction_confidence"
    ] + NUMERIC_COLS
    for col in required_cols:
        if col not in df.columns:
            df[col] = None
            
    # Convert categorical types back to string/object
    for col in df.columns:
        if df[col].dtype.name == "category":
            df[col] = df[col].astype(object)

    # ── Discover and Parse STIL ──────────────────────────────────────────────
    stil_files = sorted(stil_dir.glob("*.stil")) if stil_dir.exists() else []
    if not stil_files:
        log.error(f"No STIL file found in {stil_dir}. Cannot map scan topology.")
        sys.exit(1)
        
    stil_path = stil_files[0]
    log.info(f"Using STIL file: {stil_path.name}")
    chain_map = parse_stil_scan_structures(stil_path)
    log.info(f"Loaded scan chain map: {len(chain_map)} chains resolved.")

    # ── SCD-FR-003: Analyze scan chain topology ─────────────────────────────
    log.info("Processing SCD-FR-003: Scan Chain Topology...")
    fr003_report = {
        "requirement_id": "SCD-FR-003",
        "requirement": "Analyze scan chain topology",
        "acceptance_criteria": "Scan topology loaded and visualized correctly.",
        "status": "satisfied" if chain_map else "failed",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stil_file": stil_path.name,
        "summary": {
            "total_chains": len(chain_map),
            "max_chain_length": int(max([c["scan_length"] for c in chain_map.values() if c["scan_length"]])) if chain_map else 0,
            "total_flip_flops": int(sum([c["scan_length"] for c in chain_map.values() if c["scan_length"]])) if chain_map else 0,
        },
        "chains": chain_summary_rows(chain_map)
    }
    
    with open(output_dir / "SCD-FR-003_scan_topology.json", "w", encoding="utf-8") as f:
        json.dump(fr003_report, f, indent=2)
    log.info("SCD-FR-003 JSON report written.")

    # ── SCD-FR-004: Rank scan chains by failure frequency ───────────────────
    log.info("Processing SCD-FR-004: Failure Frequency Ranking...")
    freq = rank_chains_by_frequency(df, method="dense")
    ranking_features = available_ranking_features()
    ranking = []
    if not freq.empty:
        for _, row in freq.iterrows():
            chain = row["chain"]
            sub = df[df["chain"] == chain]
            ranking.append({
                "rank": int(row["rank"]),
                "chain": chain,
                "fail_count": int(row["fail_count"]),
                "fail_pct": float(row["fail_pct"]),
                "cumulative_pct": float(row["cumulative_pct"]),
                "rank_method": row.get("rank_method", ranking_features["default_method"]),
                "lots_affected": int(sub["lot_id"].nunique()) if "lot_id" in sub.columns else 0,
                "example_chain_id": sub["chain_id"].iloc[0] if not sub.empty and "chain_id" in sub.columns else "",
            })

    fr004_report = {
        "requirement_id": "SCD-FR-004",
        "requirement": "Rank scan chains by failure frequency",
        "acceptance_criteria": "Chains ranked based on failure frequency.",
        "status": "satisfied" if ranking else "no_failures_found",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ranking_feature": ranking_features,
        "summary": {
            "total_fail_records": len(df),
            "distinct_failing_chains": len(ranking),
            "top_failing_chain": ranking[0]["chain"] if ranking else None,
            "rank_method": ranking_features["default_method"],
        },
        "ranking": ranking
    }
    
    with open(output_dir / "SCD-FR-004_chain_failure_ranking.json", "w", encoding="utf-8") as f:
        json.dump(fr004_report, f, indent=2)
    log.info("SCD-FR-004 JSON report written.")

    # ── SCD-FR-002: Locate failing scan cells ────────────────────────────────
    log.info("Processing SCD-FR-002: Locate Failing Cells...")
    suspects = locate_failing_cells(df, chain_map, min_observations=2)
    min_obs = 2
    # Fallback to min_observations=1 if dataset is sparse
    if suspects.empty and not df.empty:
        suspects = locate_failing_cells(df, chain_map, min_observations=1)
        min_obs = 1
        
    suspect_records = []
    if not suspects.empty:
        for _, r in suspects.iterrows():
            suspect_records.append({
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
                "confidence": float(r["confidence"]),
                "dominant_fail_type": r["dominant_fail_type"],
                "dominant_region": r["dominant_region"],
                "dominant_root_cause": r["dominant_root_cause"]
            })
            
    fr002_report = {
        "requirement_id": "SCD-FR-002",
        "requirement": "Locate failing scan cells",
        "acceptance_criteria": "Suspected failing scan cells identified with confidence score.",
        "status": "satisfied" if suspect_records else "no_failures_found",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "configuration": {
            "min_observations": min_obs,
        },
        "summary": {
            "total_suspected_cells": len(suspect_records),
            "max_confidence": float(suspects["confidence"].max()) if not suspects.empty else 0.0,
        },
        "suspected_cells": suspect_records
    }
    
    with open(output_dir / "SCD-FR-002_suspected_failing_cells.json", "w", encoding="utf-8") as f:
        json.dump(fr002_report, f, indent=2)
    log.info("SCD-FR-002 JSON report written.")

    # ── SCD-FR-005: Correlate failures with scan chains ────────────────────
    log.info("Processing SCD-FR-005: Failure Correlation...")
    correlation_metrics = []
    if not df.empty:
        numerical_cols = ["ir_drop_mv", "thermal_c", "setup_slack_ps", "hold_slack_ps", "ai_severity_score"]
        valid_num_cols = [col for col in numerical_cols if col in df.columns]
        unique_chains = sorted(df["chain"].dropna().unique())
        
        for ch in unique_chains:
            is_ch = (df["chain"] == ch).astype(int)
            correlations = {}
            for col in valid_num_cols:
                col_series = pd.to_numeric(df[col], errors="coerce")
                if col_series.nunique() > 1:
                    r = is_ch.corr(col_series)
                    correlations[col] = 0.0 if pd.isna(r) else round(r, 4)
                else:
                    correlations[col] = 0.0
            
            # Get averages
            ch_fails = df[df["chain"] == ch]
            correlation_metrics.append({
                "chain": ch,
                "fail_count": len(ch_fails),
                "correlations": correlations,
                "averages": {
                    "ir_drop_mv": float(ch_fails["ir_drop_mv"].mean()) if "ir_drop_mv" in ch_fails.columns and ch_fails["ir_drop_mv"].notna().any() else None,
                    "thermal_c": float(ch_fails["thermal_c"].mean()) if "thermal_c" in ch_fails.columns and ch_fails["thermal_c"].notna().any() else None,
                    "setup_slack_ps": float(ch_fails["setup_slack_ps"].mean()) if "setup_slack_ps" in ch_fails.columns and ch_fails["setup_slack_ps"].notna().any() else None,
                    "hold_slack_ps": float(ch_fails["hold_slack_ps"].mean()) if "hold_slack_ps" in ch_fails.columns and ch_fails["hold_slack_ps"].notna().any() else None,
                }
            })

    fr005_report = {
        "requirement_id": "SCD-FR-005",
        "requirement": "Correlate failures with scan chains",
        "acceptance_criteria": "Scan-chain-to-failure correlation report generated.",
        "status": "satisfied" if correlation_metrics else "no_failures_found",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "correlation_metrics": correlation_metrics
    }
    
    with open(output_dir / "SCD-FR-005_failure_correlation.json", "w", encoding="utf-8") as f:
        json.dump(fr005_report, f, indent=2)
    log.info("SCD-FR-005 JSON report written.")

    log.info("All diagnostic requirements processed successfully!")


if __name__ == "__main__":
    run_full_diagnosis()
