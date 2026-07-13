import sys
import time
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from parser import discover_logs, parse_log_to_dataframe
from disk_cache import save_to_cache
from config import get_config
import ml_pipeline as mlp

def main():
    cfg = get_config()
    project_root = cfg.project_root
    log_dir = project_root / "data/logs"
    
    print("Discovering logs...")
    log_files = discover_logs(log_dir)
    print(f"Found {len(log_files)} log files.")
    
    paths_info = []
    for p in log_files:
        stat = p.stat()
        paths_info.append((str(p), stat.st_mtime, stat.st_size))
        
    print("Parsing log files...")
    t0 = time.time()
    frames = []
    for i, p in enumerate(log_files):
        t_sub_0 = time.time()
        df_sub = parse_log_to_dataframe(p, keep_status="FAIL")
        t_sub_1 = time.time()
        print(f"[{i+1}/{len(log_files)}] Parsed {p.name} in {t_sub_1 - t_sub_0:.2f} seconds. Rows: {len(df_sub)}")
        if not df_sub.empty:
            frames.append(df_sub)
            
    t1 = time.time()
    print(f"Total parsing took {t1 - t0:.2f} seconds.")
    
    if not frames:
        print("No failures found in any log files. Exiting.")
        return
        
    df = pd.concat(frames, ignore_index=True)
    print(f"Combined DataFrame shape: {df.shape}")
    
    # Save to Parquet cache
    print("Saving to cache...")
    save_to_cache(df, paths_info, project_root)
    print("Cache saved.")
    
    # Train ML models
    print("Training root cause classifier (RandomForest)...")
    try:
        classifier, metrics = mlp.train_root_cause_classifier(df)
        mlp.save_classifier(classifier)
        print("RandomForest model trained and saved successfully.")
        print("Metrics:", metrics)
    except Exception as e:
        print("RandomForest training failed/skipped:", e)
        
    print("Training anomaly detector (IsolationForest)...")
    try:
        anomaly_detector = mlp.train_anomaly_detector(df)
        mlp.save_anomaly_detector(anomaly_detector)
        print("IsolationForest model trained and saved successfully.")
    except Exception as e:
        print("IsolationForest training failed/skipped:", e)

if __name__ == "__main__":
    main()
