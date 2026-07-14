"""Tests for SCD-FR-006 exact scan chain break localization."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from chain_breaks import locate_exact_break_for_group


def _make_break_group(
    break_bit: int = 40,
    chain_length: int = 100,
    n_patterns: int = 8,
    noise_downstream: bool = False,
) -> pd.DataFrame:
    """Synthetic unload fails: bits [0..break_bit) clean, [break_bit..end] fail."""
    rows = []
    for p in range(n_patterns):
        start = break_bit
        if noise_downstream and p == 0:
            # one noisy low bit on a single pattern only
            rows.append({
                "pattern_id": f"P{p:04d}",
                "bit_position": 2,
                "chain": "chain_1",
                "chain_id": "core_chain_1",
                "lot_id": "LOT_A",
                "source_file": "die_01.log",
                "chain_length": chain_length,
                "cell_name": "FF[2]",
                "expected_output": "H" * chain_length,
                "actual_output": "L" * chain_length,
                "fail_flop_id": "FF_3",
            })
        for bit in range(start, chain_length):
            rows.append({
                "pattern_id": f"P{p:04d}",
                "bit_position": bit,
                "chain": "chain_1",
                "chain_id": "core_chain_1",
                "lot_id": "LOT_A",
                "source_file": "die_01.log",
                "chain_length": chain_length,
                "cell_name": f"U_core/reg_ff[{bit}]",
                "expected_output": "H" * chain_length,
                "actual_output": "L" * chain_length,
                "fail_flop_id": f"FF_{bit + 1}",
            })
    return pd.DataFrame(rows)


def test_exact_break_certain_high_soft_agreement():
    """High soft agreement with ≥2 patterns → CERTAIN and real exact cell/bit."""
    sub = _make_break_group(break_bit=40)
    result = locate_exact_break_for_group(sub, chain_map={})
    assert result is not None
    assert result["location_status"] == "CERTAIN"
    assert result["exact_break_bit_position"] == 40
    assert result["exact_break_cell"] == "U_core/reg_ff[40]"
    assert result["candidate_break_bit_position"] == 40
    assert result["candidate_break_cell"] == "U_core/reg_ff[40]"
    assert result["location_confidence"] >= 0.85
    assert result["soft_agreement"] == 1.0
    assert result["location_confidence"] == result["soft_agreement"]
    assert "first_mismatch" in result["localization_method"]


def test_confidence_handles_first_mismatch_jitter_still_certain():
    """Patterns jitter ±2 bits — soft agreement stays high → CERTAIN; no fake floor."""
    rows = []
    true_break = 50
    chain_length = 100
    for p, offset in enumerate([0, -2, 1, 2, -1, 0, 1, -2]):
        start = true_break + offset
        for bit in range(start, chain_length):
            rows.append({
                "pattern_id": f"P{p:04d}",
                "bit_position": bit,
                "chain": "chain_1",
                "chain_id": "core_chain_1",
                "lot_id": "LOT_A",
                "source_file": "die_01.log",
                "chain_length": chain_length,
                "cell_name": f"U_core/reg_ff[{bit}]",
                "expected_output": "H" * chain_length,
                "actual_output": "L" * chain_length,
                "fail_flop_id": f"FF_{bit + 1}",
            })
    sub = pd.DataFrame(rows)
    result = locate_exact_break_for_group(sub, {})
    assert result is not None
    assert result["exact_agreement"] < 0.5
    assert result["soft_agreement"] >= 0.75
    assert result["location_confidence"] == result["soft_agreement"]
    assert result["location_confidence"] >= 0.75
    assert result["location_status"] == "CERTAIN"
    assert result["exact_break_bit_position"] is not None
    assert result["exact_break_cell"] != "LOCATION_UNCERTAIN"


def test_uncertain_when_soft_agreement_low():
    """Wide first-mismatch scatter → UNCERTAIN; candidate kept, exact not claimed."""
    rows = []
    chain_length = 100
    # First mismatches spread far apart so soft (±5) agreement is low
    starts = [20, 35, 50, 65, 80, 25, 55, 70]
    for p, start in enumerate(starts):
        for bit in range(start, chain_length):
            rows.append({
                "pattern_id": f"P{p:04d}",
                "bit_position": bit,
                "chain": "chain_1",
                "chain_id": "core_chain_1",
                "lot_id": "LOT_A",
                "source_file": "die_01.log",
                "chain_length": chain_length,
                "cell_name": f"U_core/reg_ff[{bit}]",
                "expected_output": "H" * chain_length,
                "actual_output": "L" * chain_length,
                "fail_flop_id": f"FF_{bit + 1}",
            })
    sub = pd.DataFrame(rows)
    result = locate_exact_break_for_group(sub, {})
    assert result is not None
    assert result["soft_agreement"] < 0.70
    assert result["location_status"] == "UNCERTAIN"
    assert result["exact_break_cell"] == "LOCATION_UNCERTAIN"
    assert result["exact_break_bit_position"] is None
    assert result["candidate_break_bit_position"] is not None
    assert result["candidate_break_cell"] is not None
    assert "LOCATION_UNCERTAIN" not in str(result["candidate_break_cell"])
    assert "soft_agreement" in result["location_status_reason"]


def test_no_break_when_failures_start_at_scan_out():
    sub = _make_break_group(break_bit=0)
    result = locate_exact_break_for_group(sub, chain_map={})
    assert result is None


def test_single_pattern_localizes_but_uncertain():
    """One pattern can localize a candidate, but CERTAIN requires ≥2 patterns."""
    sub = _make_break_group(break_bit=25, chain_length=80, n_patterns=1)
    result = locate_exact_break_for_group(sub, {})
    assert result is not None
    assert result["patterns_analyzed"] == 1
    assert result["location_status"] == "UNCERTAIN"
    assert result["exact_break_bit_position"] is None
    assert result["exact_break_cell"] == "LOCATION_UNCERTAIN"
    assert result["candidate_break_bit_position"] == 25
    assert result["candidate_break_cell"] == "U_core/reg_ff[25]"


def test_detect_chain_breaks_dataframe():
    sub = _make_break_group(break_bit=25, chain_length=80)
    result = locate_exact_break_for_group(sub, {})
    assert result["break_bit_position"] == 25
    assert result["patterns_agreeing"] == 8
    assert result["location_status"] == "CERTAIN"
    assert result["exact_break_bit_position"] == 25
    assert result["candidate_break_bit_position"] == 25
