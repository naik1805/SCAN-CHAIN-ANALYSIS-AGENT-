"""
schema.py — Canonical failure-log field names and alias normalization.

Maps client-specific header variants to a single lowercase schema so
downstream FR modules never KeyError on optional columns.
"""

from __future__ import annotations

import re
from typing import Any

import pandas as pd

# ---------------------------------------------------------------------------
# Canonical column sets (shared with parser / validation / ML)
# ---------------------------------------------------------------------------

CANONICAL_NUMERIC_COLS: tuple[str, ...] = (
    "shift_cycles",
    "capture_cycles",
    "scan_fail_count",
    "transition_faults",
    "ir_drop_mv",
    "thermal_c",
    "setup_slack_ps",
    "hold_slack_ps",
    "test_time_ms",
    "ai_severity_score",
    "die_row",
    "die_col",
    "wafer_x",
    "wafer_y",
    "x1",
    "y1",
    "x2",
    "y2",
)

CANONICAL_STRING_COLS: tuple[str, ...] = (
    "lot_id",
    "lot_pattern",
    "wafer_id",
    "die_id",
    "source_file",
    "lot_folder",
    "pattern_id",
    "chain_id",
    "chain",
    "fail_flop_id",
    "fail_type",
    "expected_signature",
    "actual_signature",
    "expected_output",
    "actual_output",
    "root_cause_hint",
    "failure_region",
    "status",
    "defect_type",
    "die_label",
    "predicted_root_cause",
    "prediction_confidence",
    "is_anomaly",
    "anomaly_score",
)

REQUIRED_FAILURE_COLUMNS: frozenset[str] = frozenset({
    "lot_id",
    "source_file",
    "chain_id",
    "chain",
    "fail_flop_id",
    "fail_type",
})

OPTIONAL_FEATURE_COLUMNS: tuple[str, ...] = (
    "ir_drop_mv",
    "thermal_c",
    "setup_slack_ps",
    "hold_slack_ps",
    "die_row",
    "die_col",
    "wafer_x",
    "wafer_y",
    "die_label",
    "failure_region",
    "defect_type",
    "pattern_id",
    "shift_cycles",
    "capture_cycles",
)

ALL_CANONICAL_COLUMNS: tuple[str, ...] = CANONICAL_STRING_COLS + CANONICAL_NUMERIC_COLS

# ---------------------------------------------------------------------------
# Field alias map — variant token → canonical lowercase name
# ---------------------------------------------------------------------------

_ALIAS_SPECS: dict[str, list[str]] = {
    "lot_id": ["lot_id", "lot", "lot_number", "lotnum"],
    "lot_pattern": ["lot_pattern", "pattern_lot"],
    "wafer_id": ["wafer_id", "wafer", "wafer_number"],
    "die_id": ["die_id", "die", "die_number"],
    "die_label": ["die_label", "dielabel", "die_tag", "die_name"],
    "pattern_id": ["pattern_id", "patternid", "pat_id", "pattern"],
    "scan_chain_id": ["scan_chain_id", "scanchainid", "chain_id", "chain_name"],
    "channel_id": ["channel_id", "channelid", "channel"],
    "fail_flop_id": ["fail_flop_id", "fail_flop", "flop_id", "ff_id", "failing_flop"],
    "fail_type": ["fail_type", "failure_type", "fail_mode"],
    "expected_signature": ["expected_signature", "expected_sig", "exp_signature"],
    "actual_signature": ["actual_signature", "actual_sig", "act_signature"],
    "expected_output": ["expected_output", "expected_waveform", "exp_output"],
    "actual_output": ["actual_output", "actual_waveform", "act_output"],
    "status": ["status", "test_status", "result"],
    "root_cause_hint": ["root_cause_hint", "root_cause", "cause_hint"],
    "failure_region": ["failure_region", "fail_region", "region"],
    "defect_type": ["defect_type", "defect", "defect_category"],
    "shift_cycles": ["shift_cycles", "shift_cycle", "scan_shift_cycles"],
    "capture_cycles": ["capture_cycles", "capture_cycle"],
    "scan_fail_count": ["scan_fail_count", "fail_count", "scan_fails"],
    "transition_faults": ["transition_faults", "transition_fault"],
    "ir_drop_mv": ["ir_drop_mv", "ir_drop", "irdrop", "ir_drop_voltage"],
    "thermal_c": ["thermal_c", "thermal", "temperature", "temp_c"],
    "setup_slack_ps": ["setup_slack_ps", "setup_slack", "setup_slack_ps"],
    "hold_slack_ps": ["hold_slack_ps", "hold_slack"],
    "test_time_ms": ["test_time_ms", "test_time", "test_duration_ms"],
    "ai_severity_score": ["ai_severity_score", "severity_score", "ai_severity"],
    "die_row": ["die_row", "dierow", "row"],
    "die_col": ["die_col", "diecol", "die_column", "col"],
    "wafer_x": ["wafer_x", "wafer_x_mm", "waferx", "wafer_pos_x"],
    "wafer_y": ["wafer_y", "wafer_y_mm", "wafery", "wafer_pos_y"],
    "x1": ["x1", "die_x1", "bbox_x1"],
    "y1": ["y1", "die_y1", "bbox_y1"],
    "x2": ["x2", "die_x2", "bbox_x2"],
    "y2": ["y2", "die_y2", "bbox_y2"],
    "tester_name": ["tester_name", "tester", "ate_tester"],
    "test_program": ["test_program", "program"],
    "device_name": ["device_name", "device", "dut"],
    "operator_id": ["operator_id", "operator"],
    "test_mode": ["test_mode", "mode"],
    "scan_chains": ["scan_chains", "num_scan_chains", "chain_count"],
    "total_flops": ["total_flops", "total_ffs"],
    "total_patterns": ["total_patterns", "pattern_count"],
    "lot_folder": ["lot_folder", "lot_dir"],
}

# Uppercase keys stored in parser meta / record dicts
_META_STORAGE: dict[str, str] = {
    "tester_name": "TESTER_NAME",
    "test_program": "TEST_PROGRAM",
    "device_name": "DEVICE_NAME",
    "lot_id": "LOT_ID",
    "lot_pattern": "LOT_PATTERN",
    "wafer_id": "WAFER_ID",
    "die_id": "DIE_ID",
    "operator_id": "OPERATOR_ID",
    "test_mode": "TEST_MODE",
    "scan_chains": "SCAN_CHAINS",
    "total_flops": "TOTAL_FLOPS",
    "total_patterns": "TOTAL_PATTERNS",
    "defect_type": "DEFECT_TYPE",
    "die_label": "DIE_LABEL",
    "shift_cycles": "SHIFT_CYCLES",
    "capture_cycles": "CAPTURE_CYCLES",
    "die_row": "DIE_ROW",
    "die_col": "DIE_COL",
    "wafer_x": "WAFER_X",
    "wafer_y": "WAFER_Y",
    "x1": "X1",
    "y1": "Y1",
    "x2": "X2",
    "y2": "Y2",
}

_RECORD_STORAGE: dict[str, str] = {
    "pattern_id": "PATTERN_ID",
    "scan_chain_id": "SCAN_CHAIN_ID",
    "channel_id": "CHANNEL_ID",
    "shift_cycles": "SHIFT_CYCLES",
    "capture_cycles": "CAPTURE_CYCLES",
    "expected_signature": "EXPECTED_SIGNATURE",
    "actual_signature": "ACTUAL_SIGNATURE",
    "expected_output": "EXPECTED_OUTPUT",
    "actual_output": "ACTUAL_OUTPUT",
    "status": "STATUS",
    "fail_flop_id": "FAIL_FLOP_ID",
    "fail_type": "FAIL_TYPE",
    "scan_fail_count": "SCAN_FAIL_COUNT",
    "transition_faults": "TRANSITION_FAULTS",
    "ir_drop_mv": "IR_DROP_MV",
    "thermal_c": "THERMAL_C",
    "setup_slack_ps": "SETUP_SLACK_PS",
    "hold_slack_ps": "HOLD_SLACK_PS",
    "test_time_ms": "TEST_TIME_MS",
    "root_cause_hint": "ROOT_CAUSE_HINT",
    "failure_region": "FAILURE_REGION",
    "ai_severity_score": "AI_SEVERITY_SCORE",
}


def _normalize_token(key: str) -> str:
    """Normalize a raw header token for alias lookup."""
    s = key.strip()
    s = re.sub(r"[\s\-]+", "_", s)
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)
    return s.lower().strip("_")


def _build_alias_lookup() -> dict[str, str]:
    lookup: dict[str, str] = {}
    for canonical, variants in _ALIAS_SPECS.items():
        for variant in variants:
            lookup[_normalize_token(variant)] = canonical
        lookup[_normalize_token(canonical)] = canonical
    return lookup


ALIAS_LOOKUP: dict[str, str] = _build_alias_lookup()


def canonicalize_field_name(key: str) -> str:
    """Map a raw log field name to its canonical lowercase column name."""
    if not key:
        return key
    token = _normalize_token(key)
    return ALIAS_LOOKUP.get(token, token)


def resolve_meta_key(key: str) -> str | None:
    """Return uppercase meta storage key, or None if not a metadata field."""
    canon = canonicalize_field_name(key)
    return _META_STORAGE.get(canon)


def resolve_record_key(key: str) -> str:
    """Return uppercase record storage key for parser block dicts."""
    canon = canonicalize_field_name(key)
    return _RECORD_STORAGE.get(canon, key.strip().upper())


def normalize_record_dict(record: dict[str, Any]) -> dict[str, Any]:
    """Apply alias normalization to a single parsed record (any key casing)."""
    out: dict[str, Any] = {}
    for key, value in record.items():
        canon = canonicalize_field_name(key)
        storage = _RECORD_STORAGE.get(canon)
        out_key = storage if storage else canon
        if out_key not in out:
            out[out_key] = value
    return out


def normalize_failure_schema(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure all canonical columns exist; rename alias columns when safe."""
    if df.empty:
        return pd.DataFrame(columns=list(ALL_CANONICAL_COLUMNS))

    out = df.copy()

    rename: dict[str, str] = {}
    for col in list(out.columns):
        canon = canonicalize_field_name(str(col))
        if canon != col and canon not in out.columns:
            rename[col] = canon
    if rename:
        out = out.rename(columns=rename)

    for col in ALL_CANONICAL_COLUMNS:
        if col not in out.columns:
            out[col] = None

    if "scan_chain_id" in out.columns:
        mask = out["chain_id"].isna() | (out["chain_id"].astype(str).str.strip() == "")
        out.loc[mask, "chain_id"] = out.loc[mask, "scan_chain_id"]

    return out


__all__ = [
    "ALL_CANONICAL_COLUMNS",
    "CANONICAL_NUMERIC_COLS",
    "CANONICAL_STRING_COLS",
    "OPTIONAL_FEATURE_COLUMNS",
    "REQUIRED_FAILURE_COLUMNS",
    "canonicalize_field_name",
    "normalize_failure_schema",
    "normalize_record_dict",
    "resolve_meta_key",
    "resolve_record_key",
]
