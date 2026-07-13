"""test_parser.py — Unit tests for the log parser."""

from __future__ import annotations

import tempfile
import pandas as pd
import pytest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from parser import parse_log_file, records_to_dataframe, parse_log_to_dataframe


@pytest.fixture
def old_format_log() -> str:
    """Mock Tessent old-format log with brackets."""
    return """
TESTER_NAME        : ADVANTEST_V93000
LOT_ID             : LOT_OLD
DEVICE_NAME        : TEST_CHIP

[PATTERN_ID : 000841]
SCAN_CHAIN_ID       : core_des__edt_block_channel2
SHIFT_CYCLES        : 234
CAPTURE_CYCLES      : 2
STATUS              : FAIL
FAIL_FLOP_ID        : FF_914
FAIL_TYPE           : SCAN_SHIFT
SCAN_FAIL_COUNT     : 1
IR_DROP_MV          : 35
THERMAL_C           : 65
SETUP_SLACK_PS      : -15
HOLD_SLACK_PS       : 22

[PATTERN_ID : 000842]
SCAN_CHAIN_ID       : core_des__edt_block_channel1
SHIFT_CYCLES        : 234
STATUS              : PASS
"""


@pytest.fixture
def new_format_log() -> str:
    """Mock new-format log with expected/actual outputs and multiple channels."""
    return """
TESTER_NAME        : ADVANTEST_V93000
LOT_ID             : LOT_NEW
DEFECT_TYPE        : CENTER
DIE_LABEL          : fail_die_1
SHIFT_CYCLES       : 234
CAPTURE_CYCLES     : 2

==================================================================
PATTERN_ID : 000000
==================================================================
CHANNEL_ID : 1
SCAN_CHAIN_ID : core_des__edt_block_channel1
EXPECTED_OUTPUT : LHLLXL
ACTUAL_OUTPUT : LHLLXL
STATUS : PASS
IR_DROP_MV : 20
------------------------------------------------------------
CHANNEL_ID : 2
SCAN_CHAIN_ID : core_des__edt_block_channel2
EXPECTED_OUTPUT : LHLLXL
ACTUAL_OUTPUT : LHLHXL
STATUS : FAIL
IR_DROP_MV : 45
SETUP_SLACK_PS : -10
"""


def test_parse_old_format(old_format_log):
    with tempfile.NamedTemporaryFile("w+", suffix=".log", delete=False) as tmp:
        tmp.write(old_format_log)
        tmp_path = tmp.name

    try:
        meta, records = parse_log_file(tmp_path)
        assert meta["LOT_ID"] == "LOT_OLD"
        assert len(records) == 1
        assert records[0]["PATTERN_ID"] == "000841"
        assert records[0]["FAIL_FLOP_ID"] == "FF_914"
        assert records[0]["IR_DROP_MV"] == "35"
    finally:
        Path(tmp_path).unlink()


def test_parse_new_format(new_format_log):
    with tempfile.NamedTemporaryFile("w+", suffix=".log", delete=False) as tmp:
        tmp.write(new_format_log)
        tmp_path = tmp.name

    try:
        meta, records = parse_log_file(tmp_path)
        assert meta["LOT_ID"] == "LOT_NEW"
        assert meta["DEFECT_TYPE"] == "CENTER"
        
        # Mismatch is at index 3: Expected 'L', Actual 'H' (0-based)
        # Should generate 1 record with FAIL_FLOP_ID = FF_4 (3 + 1 = 4)
        assert len(records) == 1
        assert records[0]["PATTERN_ID"] == "000000"
        assert records[0]["CHANNEL_ID"] == "2"
        assert records[0]["FAIL_FLOP_ID"] == "FF_4"
        assert records[0]["STATUS"] == "FAIL"
        assert records[0]["IR_DROP_MV"] == "45"
        assert records[0]["SETUP_SLACK_PS"] == "-10"
    finally:
        Path(tmp_path).unlink()


def test_records_to_dataframe(new_format_log):
    with tempfile.NamedTemporaryFile("w+", suffix=".log", delete=False) as tmp:
        tmp.write(new_format_log)
        tmp_path = tmp.name

    try:
        meta, records = parse_log_file(tmp_path)
        df = records_to_dataframe(meta, records)
        assert not df.empty
        assert "lot_id" in df.columns
        assert df.loc[0, "lot_id"] == "LOT_NEW"
        assert df.loc[0, "root_cause_hint"] == "CENTER"  # defect_type mapped
        assert df.loc[0, "ir_drop_mv"] == 45
        assert df.loc[0, "setup_slack_ps"] == -10
    finally:
        Path(tmp_path).unlink()


def test_parse_compact_inline_format():
    compact_log = """
LOT_ID             : LOT_COMPACT
DEFECT_TYPE        : CENTER
DIE_LABEL          : fail_die_1

==============================================================
                     PATTERN EXECUTION LOG
==============================================================

P1 | CH1 EXPECTED_OUTPUT:X@{4}HHLLHLX@{8}
         ACTUAL_OUTPUT:X@{4}HHLLHLX@{8}
         STATUS:P

P1 | CH2 EXPECTED_OUTPUT:X@{4}HHLLHLX@{8}
         ACTUAL_OUTPUT:X@{4}HHLHHLX@{8}
         STATUS:F

PATTERN_METRICS
IR_DROP_MV:26
THERMAL_C:45
------------------------------------------------------------
"""
    with tempfile.NamedTemporaryFile("w+", suffix=".log", delete=False) as tmp:
        tmp.write(compact_log)
        tmp_path = tmp.name

    try:
        meta, records = parse_log_file(tmp_path)
        assert meta["LOT_ID"] == "LOT_COMPACT"
        assert meta["DEFECT_TYPE"] == "CENTER"
        
        # Mismatch at index 7: Expected 'L', Actual 'H'
        # Total length of exp: 4 (Xs) + 6 (HHLLHL) + 8 (Xs) = 18.
        # Waveform should be expanded to: XXXXHHLLHLXXXXXXXX
        # Index 0-3: X
        # Index 4: H, 5: H, 6: L, 7: L (Expected) vs H (Actual) -> Mismatch at index 7.
        # Should generate 1 record with FAIL_FLOP_ID = FF_8 (7 + 1 = 8)
        assert len(records) == 1
        assert records[0]["PATTERN_ID"] == "1"
        assert records[0]["CHANNEL_ID"] == "channel2"
        assert records[0]["FAIL_FLOP_ID"] == "FF_8"
        assert records[0]["STATUS"] == "FAIL"
        assert records[0]["IR_DROP_MV"] == "26"
        assert records[0]["THERMAL_C"] == "45"
    finally:
        Path(tmp_path).unlink()

