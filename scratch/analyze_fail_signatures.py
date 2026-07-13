import sys
from pathlib import Path
import pandas as pd
import numpy as np

PROJECT_ROOT = Path("C:/Users/Mohit/.antigravity/scan chain dianosis agent")
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from parser import discover_logs
from disk_cache import load_from_cache, _cache_key, _cache_dir
from stil_parser import parse_stil_scan_structures
from locate_cells import enrich_with_positions

def main():
    log_dir = PROJECT_ROOT / "data" / "logs"
    stil_dir = PROJECT_ROOT / "data" / "stil"
    
    logs = discover_logs(log_dir)
    stil_files = sorted(stil_dir.glob("*.stil"))
    
    print(f"Discovered logs: {len(logs)}")
    
    paths_info = []
    for p in logs:
        try:
            stat = p.stat()
            paths_info.append((str(p), stat.st_mtime, stat.st_size))
        except OSError:
            pass
            
    print(f"Paths info count: {len(paths_info)}")
    if paths_info:
        key = _cache_key(paths_info)
        print(f"Cache key: {key}")
        cache_folder = _cache_dir(PROJECT_ROOT)
        print(f"Cache folder: {cache_folder}")
        print(f"Expected file: {cache_folder / f'logs_{key}.parquet'}")
        print(f"File exists: {(cache_folder / f'logs_{key}.parquet').exists()}")
        
    df = load_from_cache(paths_info, PROJECT_ROOT)
    if df is None:
        print("Cache empty. Loading from files directly...")
        from parser import parse_log_to_dataframe
        frames = []
        for p in logs:
            df_sub = parse_log_to_dataframe(p, keep_status="FAIL")
            if not df_sub.empty:
                frames.append(df_sub)
        df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        
    print(f"Total failures loaded: {len(df)}")
    if df.empty:
        return
        
    # Ensure standard columns are present
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
            
    if not stil_files:
        print("No STIL files found.")
        return
        
    chain_map = parse_stil_scan_structures(stil_files[0])
    enriched = enrich_with_positions(df, chain_map)
    
    # Let's inspect the bit positions for each failing chain
    grouped = enriched.groupby("chain")
    print("\n--- Failure patterns per chain ---")
    for name, sub in grouped:
        min_pos = sub["bit_position"].min()
        max_pos = sub["bit_position"].max()
        unique_pos = sub["bit_position"].nunique()
        c_len = sub["chain_length"].iloc[0] if "chain_length" in sub.columns else "unknown"
        
        print(f"Chain {name:10} | total_fails={len(sub):3} | unique_bits={unique_pos:3} | min_pos={min_pos} | max_pos={max_pos} | chain_len={c_len}")
        print("  Bit positions:", sorted(sub["bit_position"].dropna().unique().tolist()))
        print("  Fail flops:   ", sub["fail_flop_id"].unique().tolist())

if __name__ == "__main__":
    main()
