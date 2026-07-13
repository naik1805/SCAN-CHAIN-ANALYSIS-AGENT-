import sys
from pathlib import Path
from collections import Counter

PROJECT_ROOT = Path("C:/Users/Mohit/.antigravity/scan chain dianosis agent")

def main():
    log_dir = PROJECT_ROOT / "data/logs"
    log_files = sorted(log_dir.rglob("*.log"))
    
    status_counter = Counter()
    
    print(f"Scanning {len(log_files)} files for status lines...")
    for idx, lf in enumerate(log_files):
        print(f"Reading {lf.name} ({idx+1}/{len(log_files)})...")
        with lf.open("r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if "STATUS :" in line:
                    status_counter[line.strip()] += 1
                    
    print("\n--- Status Counts ---")
    for status, count in status_counter.items():
        print(f"{status}: {count}")

if __name__ == "__main__":
    main()
