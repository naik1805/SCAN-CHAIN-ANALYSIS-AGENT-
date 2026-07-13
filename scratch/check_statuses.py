import sys
from pathlib import Path

PROJECT_ROOT = Path("C:/Users/Mohit/.antigravity/scan chain dianosis agent")
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from parser import parse_log_file

def main():
    path = PROJECT_ROOT / "data/logs/LOT_1_Center/fail_die_1.log"
    meta, records = parse_log_file(path, keep_status=None) # Load all statuses!
    
    print(f"Total records in {path.name}: {len(records)}")
    statuses = {}
    for r in records:
        st = r.get("STATUS", "MISSING")
        statuses[st] = statuses.get(st, 0) + 1
    print("Status counts:", statuses)
    
    if records:
        print("\nExample record:")
        print(records[0])

if __name__ == "__main__":
    main()
