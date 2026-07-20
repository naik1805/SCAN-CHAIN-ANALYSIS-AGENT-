"""
Scan-chain ATPG log parser.

Handles the real Tessent / Advantest block-structured tester log:

    [PATTERN_ID : 000841]
    SCAN_CHAIN_ID       : core_des__...__edt_block_channel2
    SHIFT_CYCLES        : 234
    CAPTURE_CYCLES      : 2
    EXPECTED_SIGNATURE  : 0xC0B63B
    ACTUAL_SIGNATURE    : 0x69B55C
    STATUS              : FAIL
    FAIL_FLOP_ID        : FF_914
    FAIL_TYPE           : SCAN_SHIFT
    SCAN_FAIL_COUNT     : 1
    ...
    FAIL_ANALYSIS:
      ROOT_CAUSE_HINT   : UNKNOWN
      FAILURE_REGION    : CLOCK_DOMAIN_B
      AI_SEVERITY_SCORE : 0.95

Files are large (~15 MB each, ~30k pattern blocks), so parsing is done as a
single streaming pass per file that keeps only the FAIL blocks.

Implements SCD-FR-001 (identify failing scan chains / cells from the logs).
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from schema import (
    CANONICAL_NUMERIC_COLS,
    canonicalize_field_name,
    normalize_failure_schema,
    resolve_meta_key,
    resolve_record_key,
)

# --- regexes (SCD-FR-001) ---------------------------------------------------
# Pattern block header, e.g. "[PATTERN_ID : 000841]"
PATTERN_HEADER_RE = re.compile(r"\[\s*PATTERN_ID\s*:\s*([0-9A-Za-z_]+)\s*\]")
# Generic "KEY : VALUE" field line (handles leading indent of FAIL_ANALYSIS).
FIELD_RE = re.compile(r"^\s*([A-Z_]+)\s*:\s*(.*?)\s*$")
# Short channel label extracted from the long hierarchical chain name.
CHANNEL_RE = re.compile(r"(channel\d+|chain_?\d+|ch_?\d+)", re.IGNORECASE)

# Top-of-file metadata keys we want to carry onto every failure record.
# Alias resolution is handled by schema.resolve_meta_key().

NUMERIC_COLS = list(CANONICAL_NUMERIC_COLS)


def _short_chain(chain_id: str) -> str:
    """Reduce a long hierarchical chain name to its 'channelN' label."""
    if not chain_id:
        return "UNKNOWN"
    m = CHANNEL_RE.search(chain_id)
    return m.group(1).lower() if m else chain_id


def parse_log_file(path: str | Path, keep_status: str = "FAIL") -> tuple[dict, list[dict]]:
    """Stream a single log file and return (file_metadata, failure_records).

    Only blocks whose STATUS matches *keep_status* are returned (default FAIL).
    Supports both traditional Tessent log format and the new Pattern-Channel-Inline
    format with compressed waveforms (e.g. X@{68}).
    """
    path = Path(path)
    meta: dict[str, str] = {"SOURCE_FILE": path.name, "LOT_FOLDER": path.parent.name}
    records: list[dict] = []

    current_pattern_id = None
    current_block = None
    seen_first_pattern = False

    def flush(block: dict[str, str] | None) -> None:
        if block and block.get("STATUS", "").upper() == keep_status.upper():
            expected = block.get("EXPECTED_OUTPUT")
            actual = block.get("ACTUAL_OUTPUT")
            if expected and actual:
                # Compare EXPECTED_OUTPUT and ACTUAL_OUTPUT to find failing bit positions
                mismatches = []
                for i in range(min(len(expected), len(actual))):
                    char_exp = expected[i]
                    char_act = actual[i]
                    if char_exp != char_act and char_exp != 'X' and char_act != 'X':
                        mismatches.append(i)
                
                if mismatches:
                    # Emit one record per mismatching bit/flop to align with locate_cells.py
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

    # Detect if file is in the new inline format (Pattern_Channel_Inline)
    is_inline_format = False
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as fh:
            for _ in range(50):
                line = fh.readline()
                if not line:
                    break
                if "EXPECTED_OUTPUT" in line and "|" in line:
                    is_inline_format = True
                    break
    except Exception:
        pass

    if is_inline_format:
        current_pattern_records = []
        parsing_metrics = False
        metrics = {}
        
        # Regexes for parsing
        line_re = re.compile(r"^P(\d+)\s*\|\s*CH(\d+)\s+EXPECTED_OUTPUT\s*:\s*(.*)$", re.IGNORECASE)
        act_re = re.compile(r"^\s*ACTUAL_OUTPUT\s*:\s*(.*)$", re.IGNORECASE)
        status_re = re.compile(r"^\s*STATUS\s*:\s*(\S+)$", re.IGNORECASE)
        
        def expand_waveform(val: str) -> str:
            def repl(match):
                return "X" * int(match.group(1))
            return re.sub(r"X@\{(\d+)\}", repl, val)
            
        def flush_pattern_records():
            nonlocal current_pattern_records, metrics
            if current_pattern_records:
                for rec in current_pattern_records:
                    for mk, mv in metrics.items():
                        rec[mk] = mv
                    flush(rec)
                current_pattern_records = []
                metrics = {}

        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                line = raw.strip()
                if not line:
                    continue
                
                # Check for metadata headers before PATTERN EXECUTION LOG
                if not seen_first_pattern:
                    if "PATTERN EXECUTION LOG" in line:
                        seen_first_pattern = True
                        continue
                    if ":" in line:
                        parts = line.split(":", 1)
                        key = parts[0].strip()
                        value = parts[1].strip()
                        meta_key = resolve_meta_key(key)
                        if meta_key:
                            meta[meta_key] = value
                    continue
                
                # We are in pattern execution log section
                if line.startswith("P") and "|" in line:
                    if parsing_metrics:
                        flush_pattern_records()
                        parsing_metrics = False
                        
                    m = line_re.match(line)
                    if m:
                        pat_id = m.group(1)
                        ch_num = m.group(2)
                        exp_out = expand_waveform(m.group(3))
                        
                        current_block = {
                            "PATTERN_ID": pat_id,
                            "CHANNEL_ID": f"channel{ch_num}",
                            "CHAIN": f"channel{ch_num}",
                            "EXPECTED_OUTPUT": exp_out,
                            "STATUS": "FAIL" # Default, updated by STATUS:P/F
                        }
                    continue
                    
                if "ACTUAL_OUTPUT" in line and current_block is not None:
                    m = act_re.match(line)
                    if m:
                        current_block["ACTUAL_OUTPUT"] = expand_waveform(m.group(1))
                    continue
                    
                if "STATUS" in line and current_block is not None:
                    m = status_re.match(line)
                    if m:
                        st_val = m.group(1).upper()
                        current_block["STATUS"] = "PASS" if st_val == "P" else ("FAIL" if st_val == "F" else st_val)
                        current_pattern_records.append(current_block)
                        current_block = None
                    continue
                    
                if line == "PATTERN_METRICS":
                    parsing_metrics = True
                    continue
                    
                if parsing_metrics and ":" in line:
                    parts = line.split(":", 1)
                    key = parts[0].strip()
                    value = parts[1].strip()
                    metrics[resolve_record_key(key)] = value
                    continue
                    
                if line == "------------------------------------------------------------":
                    if parsing_metrics:
                        flush_pattern_records()
                        parsing_metrics = False
                    continue
            
            # Flush any remaining pattern at the end of the file
            flush_pattern_records()
            
    else:
        # Traditional format parser
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                line = raw.strip()
                if not line:
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
                        meta_key = resolve_meta_key(key)
                        if meta_key:
                            meta[meta_key] = value
                    else:
                        if current_block is not None:
                            current_block[resolve_record_key(key)] = value

            if current_block is not None:
                flush(current_block)

    return meta, records


def records_to_dataframe(meta: dict, records: list[dict]) -> pd.DataFrame:
    """Convert raw failure records (+ file meta) into a typed DataFrame dynamically."""
    if not records:
        cols = ["lot_id", "lot_pattern", "wafer_id", "die_id", "source_file",
                "pattern_id", "chain_id", "chain", "fail_flop_id", "fail_type",
                "expected_signature", "actual_signature", "root_cause_hint",
                "failure_region"] + NUMERIC_COLS
        return pd.DataFrame(columns=cols)

    rows = []
    for rec in records:
        row = {}
        # Add metadata keys (lowercase)
        for k, v in meta.items():
            row[k.lower()] = v
        # Ensure lot_id is present
        if "lot_id" not in row or not row["lot_id"]:
            row["lot_id"] = meta.get("LOT_ID", meta.get("LOT_FOLDER", ""))
            
        # Add all record keys (canonical lowercase)
        for k, v in rec.items():
            row[canonicalize_field_name(k)] = v
            
        # Map specific standard columns if they were not in lowercase form
        if "scan_chain_id" in row and "chain_id" not in row:
            row["chain_id"] = row["scan_chain_id"]
        if "chain" not in row:
            row["chain"] = _short_chain(row.get("chain_id", ""))
        # Ensure chain_id is present
        if "chain_id" not in row or not row["chain_id"]:
            row["chain_id"] = row.get("chain", "")
            
        # Carry wafer-level defect_type over as root_cause_hint
        if "root_cause_hint" not in row or row["root_cause_hint"] == "UNKNOWN" or not row["root_cause_hint"]:
            row["root_cause_hint"] = row.get("defect_type", meta.get("DEFECT_TYPE", "UNKNOWN"))
            
        rows.append(row)

    df = pd.DataFrame(rows)
    df = normalize_failure_schema(df)

    # Dynamically cast columns that look numeric
    string_cols = {
        "lot_id", "lot_pattern", "wafer_id", "die_id", "source_file", 
        "pattern_id", "chain_id", "chain", "fail_flop_id", "fail_type", 
        "expected_signature", "actual_signature", "root_cause_hint", 
        "failure_region", "status", "defect_type", "die_label",
        "predicted_root_cause"
    }
    for col in df.columns:
        if col in string_cols:
            continue
        # Check if we can convert it to numeric
        converted = pd.to_numeric(df[col], errors="coerce")
        # If not all values become NaN, apply it
        if not converted.isna().all():
            df[col] = converted
            
    # Calculate simulated/heuristic AI severity score based on physical tester metrics
    if "ai_severity_score" in df.columns:
        ir = df["ir_drop_mv"].fillna(0.0)
        therm = df["thermal_c"].fillna(40.0)
        
        s_ir = (ir / 60.0).clip(0.0, 1.0)
        s_therm = ((therm - 35.0) / 70.0).clip(0.0, 1.0)
        
        # Calculate min timing slack
        min_slack = df[["setup_slack_ps", "hold_slack_ps"]].min(axis=1).fillna(30.0)
        s_timing = (1.0 - (min_slack / 40.0)).clip(0.0, 1.0)
        
        computed_severity = 0.3 * s_ir + 0.3 * s_therm + 0.4 * s_timing
        
        # Add deterministic variance based on pattern ID
        def make_noise(pat):
            try:
                nums = re.findall(r"\d+", str(pat))
                val = int(nums[0]) if nums else 0
                return ((val % 100) / 500.0) - 0.1
            except Exception:
                return 0.0
                
        noise = df["pattern_id"].map(make_noise)
        computed_severity = (computed_severity + noise).clip(0.15, 0.98).round(3)
        df["ai_severity_score"] = df["ai_severity_score"].fillna(computed_severity)

    return normalize_failure_schema(df)


def parse_log_to_dataframe(path: str | Path, keep_status: str = "FAIL") -> pd.DataFrame:
    """Convenience: parse one file straight into a typed failure DataFrame."""
    meta, records = parse_log_file(path, keep_status=keep_status)
    return records_to_dataframe(meta, records)


def discover_logs(log_dir: str | Path) -> list[Path]:
    """Recursively list all .log files under *log_dir* (sorted)."""
    log_dir = Path(log_dir)
    if not log_dir.exists():
        return []
    return sorted(log_dir.rglob("*.log"))

