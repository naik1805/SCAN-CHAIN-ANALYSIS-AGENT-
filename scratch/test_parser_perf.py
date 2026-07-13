import sys
import time
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# Let's write the optimized parsing function here to test it
def parse_log_file_optimized(path, keep_status="FAIL"):
    path = Path(path)
    meta = {"SOURCE_FILE": path.name, "LOT_FOLDER": path.parent.name}
    records = []

    current_pattern_id = None
    current_block = None
    seen_first_pattern = False

    META_KEYS = {
        "TESTER_NAME", "TEST_PROGRAM", "DEVICE_NAME", "LOT_ID", "LOT_PATTERN",
        "WAFER_ID", "DIE_ID", "OPERATOR_ID", "TEST_MODE", "SCAN_CHAINS",
        "TOTAL_FLOPS", "TOTAL_PATTERNS", "DEFECT_TYPE", "DIE_LABEL"
    }

    def flush(block):
        if block and block.get("STATUS", "").upper() == keep_status.upper():
            expected = block.get("EXPECTED_OUTPUT")
            actual = block.get("ACTUAL_OUTPUT")
            if expected and actual:
                # Compare expected and actual
                mismatches = []
                for i in range(min(len(expected), len(actual))):
                    if expected[i] != actual[i] and expected[i] != 'X' and actual[i] != 'X':
                        mismatches.append(i)
                
                if mismatches:
                    for bit_pos in mismatches:
                        rec = block.copy()
                        flop_num = bit_pos + 1
                        rec["FAIL_FLOP_ID"] = f"FF_{flop_num}"
                        rec["FAIL_TYPE"] = "SCAN_SHIFT"
                        records.append(rec)
                else:
                    records.append(block)
            else:
                records.append(block)

    t0 = time.time()
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            line = raw.strip()
            if ":" not in line:
                continue

            if "PATTERN_ID" in line:
                if current_block is not None:
                    flush(current_block)
                current_pattern_id = line.split(":", 1)[1].strip(" ]\t")
                current_block = {"PATTERN_ID": current_pattern_id}
                seen_first_pattern = True
                continue

            if "CHANNEL_ID" in line:
                if current_block is not None:
                    flush(current_block)
                chan_id = line.split(":", 1)[1].strip()
                current_block = {"PATTERN_ID": current_pattern_id, "CHANNEL_ID": chan_id}
                continue

            parts = line.split(":", 1)
            if len(parts) == 2:
                key = parts[0].strip()
                value = parts[1].strip()
                if not seen_first_pattern:
                    if key in META_KEYS:
                        meta[key] = value
                else:
                    if current_block is not None:
                        current_block[key] = value

        if current_block is not None:
            flush(current_block)

    t1 = time.time()
    print(f"Parsing took {t1 - t0:.2f} seconds.")
    print(f"Metadata: {meta}")
    print(f"Number of records parsed: {len(records)}")
    if records:
        print(f"First record: {records[0]}")
    return meta, records

if __name__ == "__main__":
    log_path = Path(__file__).parent.parent / "data/logs/LOT_1_Center/fail_die_1.log"
    if log_path.exists():
        parse_log_file_optimized(log_path)
    else:
        print("Log file not found at", log_path)
