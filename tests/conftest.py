"""conftest.py — Shared pytest fixtures for the Scan Chain Diagnosis Agent test suite."""

from __future__ import annotations

import pandas as pd
import pytest


@pytest.fixture
def minimal_failures_df() -> pd.DataFrame:
    """A valid failure DataFrame with 15 rows, exceeding min_training_samples=10."""
    return pd.DataFrame({
        "lot_id":           ["LOT_A"] * 15,
        "source_file":      ["log_01.log"] * 15,
        "chain_id":         [f"core__edt_block_channel{i % 3 + 1}" for i in range(15)],
        "chain":            [f"channel{i % 3 + 1}" for i in range(15)],
        "fail_flop_id":     [f"FF_{i * 10 + 1}" for i in range(15)],
        "fail_type":        ["SCAN_SHIFT", "STR", "CAPTURE"] * 5,
        "pattern_id":       [f"{i:06d}" for i in range(15)],
        "root_cause_hint":  [
            "SETUP_TIMING_VIOLATION", "IR_DROP_AND_HOLD_FAILURE",
            "SETUP_TIMING_VIOLATION", "IR_DROP_AND_HOLD_FAILURE",
            "SETUP_TIMING_VIOLATION", "IR_DROP_AND_HOLD_FAILURE",
            "SETUP_TIMING_VIOLATION", "IR_DROP_AND_HOLD_FAILURE",
            "SETUP_TIMING_VIOLATION", "IR_DROP_AND_HOLD_FAILURE",
            "SETUP_TIMING_VIOLATION", "IR_DROP_AND_HOLD_FAILURE",
            "UNKNOWN", "UNKNOWN", "UNKNOWN",
        ],
        "failure_region":   ["CLOCK_DOMAIN_A", "CENTER_HOTSPOT", "CLOCK_DOMAIN_B"] * 5,
        "ir_drop_mv":       [20, 65, 30, 55, 70, 25, 60, 45, 35, 50, 22, 68, 28, 52, 72],
        "thermal_c":        [50, 85, 55, 80, 90, 52, 83, 75, 58, 78, 51, 87, 56, 82, 91],
        "setup_slack_ps":   [-10, -40, -5, -35, -45, -8, -38, -30, -12, -32, -9, -42, -6, -36, -46],
        "hold_slack_ps":    [5, -20, 8, -15, -25, 6, -18, -12, 7, -14, 5, -22, 9, -16, -26],
        "ai_severity_score": [0.7, 0.95, 0.6, 0.92, 0.98, 0.68, 0.94, 0.88, 0.72, 0.90,
                              0.71, 0.96, 0.61, 0.93, 0.99],
        "shift_cycles":     [234] * 15,
    })


@pytest.fixture
def minimal_chain_map() -> dict:
    """A minimal chain_map with 3 scan chains."""
    return {
        "core__edt_block_channel1": {
            "chain_id": "core__edt_block_channel1",
            "chain": "channel1",
            "chain_name": "channel1",
            "scan_length": 234,
            "scan_in": "scan_in[0]",
            "scan_out": "scan_out[0]",
            "scan_master_clock": "clk_scan",
            "cell_order": [f"U_core/ff_{i}" for i in range(234)],
            "hierarchical_path": "U_core",
            "decompressor_pin": "edt_channels[0]",
            "compactor_pin": "edt_channels[0]",
        },
        "core__edt_block_channel2": {
            "chain_id": "core__edt_block_channel2",
            "chain": "channel2",
            "chain_name": "channel2",
            "scan_length": 234,
            "scan_in": "scan_in[1]",
            "scan_out": "scan_out[1]",
            "scan_master_clock": "clk_scan",
            "cell_order": [f"U_core/ff2_{i}" for i in range(234)],
            "hierarchical_path": "U_core",
            "decompressor_pin": "edt_channels[1]",
            "compactor_pin": "edt_channels[1]",
        },
        "core__edt_block_channel3": {
            "chain_id": "core__edt_block_channel3",
            "chain": "channel3",
            "chain_name": "channel3",
            "scan_length": 234,
            "scan_in": "scan_in[2]",
            "scan_out": "scan_out[2]",
            "scan_master_clock": "clk_scan",
            "cell_order": [f"U_core/ff3_{i}" for i in range(234)],
            "hierarchical_path": "U_core",
            "decompressor_pin": "edt_channels[2]",
            "compactor_pin": "edt_channels[2]",
        },
    }
